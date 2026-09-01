import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { subscribePlanStream, getPlanGraph, getPlanInspector, getAgentManifest } from '@/api/plans'
import type { WorkbenchGraph, WorkbenchInspector, WorkbenchGraphNode, AgentManifest } from '@/api/plans'
import type { PlanLogItem } from '@/types'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  time: string
  agent?: string
  toolCalls?: Array<{ tool: string; args?: Record<string, unknown>; result?: unknown; startAt?: string; endAt?: string; _id?: string }>
  collapsed?: boolean
  citations?: unknown[]
}

export const useWorkbenchStore = defineStore('workbench', () => {
  const traceId = ref<string | null>(null)
  const messages = ref<ChatMessage[]>([])
  const graph = ref<WorkbenchGraph>({ nodes: [], edges: [], status: 'pending', trace_id: '' })
  const inspector = ref<WorkbenchInspector>({ state: {}, logs: [], patch: {}, trace_id: '' })
  const status = ref<'idle' | 'running' | 'completed' | 'failed'>('idle')
  const lastEventId = ref<string>('')
  const manifest = ref<AgentManifest | null>(null)

  // SSE handle
  let es: EventSource | null = null
  // 工具调用树：以唯一 id 关联 start/end，支持并行同工具调用不覆盖
  const toolStartMap = new Map<string, number>() // tool -> idx (latest) + tool:${_id} -> idx for parallel safety

  const graphNodes = computed(() => graph.value.nodes)
  const hasReplan = computed(() => graph.value.edges.some((e) => e.type === 'replan'))

  // 与 app/agents/graph.py:456 保持一致：week_load/daily_load/reallocate 来自 inspector.patch
  const weekLoadEntries = computed<[string, number][]>(() => {
    const patch = (inspector.value.patch || {}) as Record<string, unknown>
    const wl = patch.week_load as Record<string, number> | undefined
    if (wl && typeof wl === 'object' && !Array.isArray(wl)) {
      return Object.entries(wl).filter(([, v]) => typeof v === 'number') as [string, number][]
    }
    return []
  })

  const dailyLoadEntries = computed<[string, number][]>(() => {
    const patch = (inspector.value.patch || {}) as Record<string, unknown>
    const dl = patch.daily_load as Record<string, number> | undefined
    if (dl && typeof dl === 'object' && !Array.isArray(dl)) {
      return Object.entries(dl).filter(([, v]) => typeof v === 'number') as [string, number][]
    }
    return []
  })

  const reallocateInfo = computed<string>(() => {
    const patch = (inspector.value.patch || {}) as Record<string, unknown>
    const ra = patch.reallocate as Record<string, unknown> | undefined
    if (ra && typeof ra === 'object' && ra.from && ra.to) return `${String(ra.from)} → ${String(ra.to)} ${String((ra as Record<string, unknown>).hours ?? '')}h`
    const instr = patch.instructions as unknown
    if (Array.isArray(instr) && instr.length) return String(instr[0])
    return ''
  })

  function reset() {
    messages.value = []
    graph.value = { nodes: [], edges: [], status: 'pending', trace_id: traceId.value || '' }
    inspector.value = { state: {}, logs: [], patch: {}, trace_id: traceId.value || '' }
    status.value = 'idle'
    lastEventId.value = ''
    toolStartMap.clear()
    if (es) {
      try { es.close() } catch {}
      es = null
    }
  }

  function setTraceId(id: string) {
    if (traceId.value !== id) {
      reset()
      traceId.value = id
    }
  }

  function pushSystem(text: string) {
    messages.value.push({ id: `s${Date.now()}${Math.random().toString(36).slice(2, 6)}`, role: 'system', content: text, time: new Date().toLocaleTimeString() })
  }

  function pushAssistant(content: string, opts?: Partial<ChatMessage>) {
    messages.value.push({ id: `a${Date.now()}${Math.random().toString(36).slice(2, 6)}`, role: 'assistant', content, time: new Date().toLocaleTimeString(), collapsed: false, ...opts })
  }

  function addToolStart(tool: string, args?: Record<string, unknown>, agent?: string) {
    const uid = `t${Date.now()}${Math.random().toString(36).slice(2, 8)}`
    const msg: ChatMessage = {
      id: uid,
      role: 'assistant',
      agent: agent || tool,
      content: `${tool} 调用中…`,
      time: new Date().toLocaleTimeString(),
      toolCalls: [{ tool, args, _id: uid, startAt: new Date().toISOString() }],
      collapsed: false,
    }
    messages.value.push(msg)
    const idx = messages.value.length - 1
    toolStartMap.set(tool, idx)
    toolStartMap.set(`${tool}:${uid}`, idx)
  }

  function finishTool(tool: string, result?: unknown) {
    // 倒序查找首个同 tool 且无 result 的调用，支持并行多次同工具不覆盖
    for (let i = messages.value.length - 1; i >= 0; i--) {
      const m = messages.value[i]
      const tc = m.toolCalls?.[0]
      if (tc && tc.tool === tool && tc.result === undefined) {
        tc.result = result
        tc.endAt = new Date().toISOString()
        m.content = `${tool} 完成`
        return
      }
    }
    // 若未找到未完成的 start，则作为独立完成记录
    messages.value.push({
      id: `te${Date.now()}${Math.random().toString(36).slice(2, 6)}`,
      role: 'assistant',
      agent: tool,
      content: `${tool} 完成`,
      time: new Date().toLocaleTimeString(),
      toolCalls: [{ tool, result, endAt: new Date().toISOString() }],
    })
  }

  async function fetchGraph() {
    if (!traceId.value) return
    try {
      const res = await getPlanGraph(traceId.value)
      graph.value = res.data
    } catch {}
  }

  async function fetchInspector() {
    if (!traceId.value) return
    try {
      const res = await getPlanInspector(traceId.value)
      inspector.value = res.data
    } catch {}
  }

  async function fetchManifest() {
    try {
      const res = await getAgentManifest()
      manifest.value = res.data
    } catch {}
  }

  function subscribe() {
    if (!traceId.value) return
    if (es) { try { es.close() } catch {}; es = null }
    status.value = 'running'
    // 首字节 <2s 已由后端保障，此处记录开始时间供测试
    const start = performance.now()
    es = subscribePlanStream(
      traceId.value,
      {
        onThought: (d) => {
          pushAssistant(String(d.text || ''), { agent: String(d.agent || 'planner') })
        },
        onToolStart: (d) => {
          addToolStart(String(d.tool), d.args as Record<string, unknown>, String(d.agent || d.tool))
        },
        onTool: (d) => {
          // 统一工具调用记录（前端气泡+可折叠子调用树），倒序更新最近未完成同名，支持并行
          const tool = String(d.tool)
          let found = false
          for (let i = messages.value.length - 1; i >= 0; i--) {
            const m = messages.value[i]
            const tc = m.toolCalls?.[0]
            if (tc && tc.tool === tool && tc.result === undefined) {
              tc.args = d.args as Record<string, unknown>
              found = true
              break
            }
          }
          if (!found) {
            addToolStart(tool, d.args as Record<string, unknown>)
          }
        },
        onToolEnd: (d) => {
          finishTool(String(d.tool), d.result)
        },
        onTask: (d) => {
          const t = d.task as Record<string, unknown>
          pushAssistant(`创建任务：${String(t.title)}`, { toolCalls: [{ tool: 'task_created', args: t }] })
        },
        onCritic: (d) => {
          const fb = String(d.feedback || '')
          pushAssistant(fb ? `Critic：${fb}` : 'Critic：校验通过', { agent: 'critic' })
          if (fb) status.value = 'running'
        },
        onMentor: (d) => {
          pushAssistant(String(d.text || ''), { agent: 'mentor' })
        },
        onReflector: (d) => {
          pushAssistant(`Reflector 补丁：${JSON.stringify(d.patch).slice(0, 120)}`, { agent: 'reflector' })
          inspector.value.patch = d.patch as Record<string, unknown>
        },
        onDone: (d) => {
          status.value = 'completed'
          pushSystem(`规划完成 trace=${String(d.trace_id).slice(0, 8)} · ${String(d.count || 0)} 任务 · rewrites=${String(d.rewrites || 0)}`)
          // 完成后刷新 graph/inspector，确保与 DB 一致
          void fetchGraph()
          void fetchInspector()
          // 记录 lastEventId 完成态
          const elapsed = performance.now() - start
          void elapsed // 可供埋点：首包<2s
        },
        onError: () => {
          // SSE 错误由 api/plans 内部重连，记录 lastEventId 供续播（以服务器 id 为准）
        },
      },
      { lastEventId: lastEventId.value || undefined, retryMs: 1200, maxRetries: 5 },
    )

    // 以服务器 id 为真，同步 lastEventId（移除本地 bumpId 自增，双轨以服务器为准）
    const syncServerId = (e: MessageEvent) => {
      const lid = (e as MessageEvent & { lastEventId?: string }).lastEventId
      if (lid) lastEventId.value = String(lid)
    }
    try {
      es.addEventListener('message', syncServerId as unknown as EventListener)
      const evtNames: string[] = ['thought','tool_call','tool_call_start','tool_call_end','task_created','critic_feedback','critic','mentor_msg','mentor','reflector_patch','done']
      for (const n of evtNames) {
        es.addEventListener(n, syncServerId as unknown as EventListener)
      }
    } catch {}
  }

  function unsubscribe() {
    if (es) { try { es.close() } catch {}; es = null }
    status.value = status.value === 'running' ? 'completed' : status.value
  }

  function selectNode(node: WorkbenchGraphNode) {
    // 点击穿透 Inspector：高亮对应日志
    const logs = inspector.value.logs
    const matched = logs.find((l) => l.agent_name === node.id)
    if (matched) {
      inspector.value.state = { ...inspector.value.state, _selectedAgent: node.id, _selectedLog: matched }
    } else {
      inspector.value.state = { ...inspector.value.state, _selectedAgent: node.id }
    }
  }

  return { traceId, messages, graph, inspector, status, lastEventId, graphNodes, hasReplan, manifest, weekLoadEntries, dailyLoadEntries, reallocateInfo, setTraceId, reset, pushSystem, pushAssistant, fetchGraph, fetchInspector, fetchManifest, subscribe, unsubscribe, selectNode }
})
