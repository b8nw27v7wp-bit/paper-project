import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { subscribePlanStream, getPlanGraph, getPlanInspector, getAgentManifest } from '@/api/plans'
import type { WorkbenchGraph, WorkbenchInspector, WorkbenchGraphNode, AgentManifest } from '@/api/plans'

export type TranscriptKind = 'user' | 'thought' | 'tool' | 'plan' | 'critic' | 'mentor' | 'reflector' | 'compact' | 'done'

export interface TranscriptTool {
  tool: string
  agent?: string
  args?: Record<string, unknown>
  result?: unknown
  error?: string
  startAt?: string
  endAt?: string
  status: 'running' | 'ok' | 'error'
}

export interface TranscriptTask {
  title: string
  planned_start?: string
  planned_end?: string
  priority?: number
}

export interface TranscriptItem {
  id: string
  kind: TranscriptKind
  agent?: string
  text?: string
  tools?: TranscriptTool[]
  tasks?: TranscriptTask[]
  patch?: Record<string, unknown>
  feedback?: string
  rewrites?: number
  count?: number
  elapsedMs?: number
  time: string
}

export const useWorkbenchStore = defineStore('workbench', () => {
  const traceId = ref<string | null>(null)
  const transcript = ref<TranscriptItem[]>([])
  const graph = ref<WorkbenchGraph>({ nodes: [], edges: [], status: 'pending', trace_id: '' })
  const inspector = ref<WorkbenchInspector>({ state: {}, logs: [], patch: {}, trace_id: '' })
  const status = ref<'idle' | 'running' | 'completed' | 'failed'>('idle')
  const lastEventId = ref<string>('')
  const manifest = ref<AgentManifest | null>(null)
  const reconnecting = ref(false)
  const selectedNodeId = ref<string>('')

  let es: EventSource | null = null
  let startedAt = 0
  const toolStartMap = new Map<string, number>()

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

  function uid(): string {
    return `t${Date.now()}${Math.random().toString(36).slice(2, 8)}`
  }

  function pushItem(item: TranscriptItem) {
    transcript.value.push(item)
    if (transcript.value.length > 200) transcript.value = transcript.value.slice(-200)
  }

  function reset() {
    transcript.value = []
    graph.value = { nodes: [], edges: [], status: 'pending', trace_id: traceId.value || '' }
    inspector.value = { state: {}, logs: [], patch: {}, trace_id: traceId.value || '' }
    status.value = 'idle'
    lastEventId.value = ''
    reconnecting.value = false
    selectedNodeId.value = ''
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

  function pushUser(text: string) {
    pushItem({ id: uid(), kind: 'user', text, time: new Date().toLocaleTimeString() })
  }

  function findRunningTool(tool: string): TranscriptTool | null {
    for (let i = transcript.value.length - 1; i >= 0; i--) {
      const it = transcript.value[i]
      if (it.kind !== 'tool' || !it.tools?.length) continue
      const tc = it.tools[it.tools.length - 1]
      if (tc && tc.tool === tool && tc.status === 'running') return tc
    }
    return null
  }

  function addToolStart(tool: string, agent?: string, args?: Record<string, unknown>) {
    const existing = findRunningTool(tool)
    if (existing) {
      if (args) existing.args = args
      return
    }
    const item: TranscriptItem = {
      id: uid(),
      kind: 'tool',
      agent: agent || tool,
      tools: [{ tool, agent, args, status: 'running', startAt: new Date().toISOString() }],
      time: new Date().toLocaleTimeString(),
    }
    pushItem(item)
    const idx = transcript.value.length - 1
    toolStartMap.set(tool, idx)
    toolStartMap.set(`${tool}:${item.id}`, idx)
  }

  function updateToolArgs(tool: string, args?: Record<string, unknown>) {
    const tc = findRunningTool(tool)
    if (tc && args) tc.args = args
    else if (!tc) addToolStart(tool, undefined, args)
  }

  function finishTool(tool: string, result?: unknown, error?: string) {
    for (let i = transcript.value.length - 1; i >= 0; i--) {
      const it = transcript.value[i]
      if (it.kind !== 'tool' || !it.tools?.length) continue
      const tc = it.tools[it.tools.length - 1]
      if (tc && tc.tool === tool && tc.status === 'running') {
        tc.result = result
        tc.error = error
        tc.endAt = new Date().toISOString()
        tc.status = error ? 'error' : 'ok'
        return
      }
    }
    pushItem({
      id: uid(),
      kind: 'tool',
      agent: tool,
      tools: [{ tool, result, error, endAt: new Date().toISOString(), status: error ? 'error' : 'ok' }],
      time: new Date().toLocaleTimeString(),
    })
  }

  function handleThought(d: { agent?: string; text?: string; id?: string; type?: string; dropped?: number }) {
    if (d.type === 'compact_summary') {
      pushItem({ id: uid(), kind: 'compact', agent: 'compaction', count: Number(d.dropped ?? 0), text: String(d.text || ''), time: new Date().toLocaleTimeString() })
      return
    }
    const text = String(d.text || '')
    if (!text) return
    if (d.id) {
      const found = transcript.value.find((it) => it.kind === 'thought' && it.id === `th-${String(d.id)}`)
      if (found) {
        found.text = found.text && found.text.includes(text) ? found.text : (found.text || '') + text
        return
      }
      pushItem({ id: `th-${String(d.id)}`, kind: 'thought', agent: String(d.agent || 'planner'), text, time: new Date().toLocaleTimeString() })
      return
    }
    const last = transcript.value[transcript.value.length - 1]
    if (last && last.kind === 'thought' && last.agent === String(d.agent || 'planner')) {
      last.text = last.text && last.text.includes(text) ? last.text : (last.text || '') + text
      return
    }
    pushItem({ id: uid(), kind: 'thought', agent: String(d.agent || 'planner'), text, time: new Date().toLocaleTimeString() })
  }

  function handleTask(d: { task: Record<string, unknown> }) {
    const t = d.task
    const task: TranscriptTask = {
      title: String(t.title ?? ''),
      planned_start: t.planned_start != null ? String(t.planned_start) : undefined,
      planned_end: t.planned_end != null ? String(t.planned_end) : undefined,
      priority: Number(t.priority ?? 3),
    }
    const last = transcript.value[transcript.value.length - 1]
    if (last && last.kind === 'plan') {
      last.tasks = [...(last.tasks || []), task]
      return
    }
    pushItem({ id: uid(), kind: 'plan', tasks: [task], time: new Date().toLocaleTimeString() })
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

  function syncServerId(e: MessageEvent) {
    const lid = (e as MessageEvent & { lastEventId?: string }).lastEventId
    if (lid) lastEventId.value = String(lid)
  }

  function subscribe() {
    if (!traceId.value) return
    if (es) { try { es.close() } catch {}; es = null }
    status.value = 'running'
    startedAt = performance.now()
    es = subscribePlanStream(
      traceId.value,
      {
        onThought: (d) => {
          handleThought(d as { agent?: string; text?: string; id?: string; type?: string; dropped?: number })
        },
        onToolStart: (d) => {
          addToolStart(String(d.tool), d.agent != null ? String(d.agent) : undefined, d.args as Record<string, unknown>)
        },
        onTool: (d) => {
          updateToolArgs(String(d.tool), d.args as Record<string, unknown>)
        },
        onToolEnd: (d) => {
          const err = d.error != null ? String(d.error) : undefined
          finishTool(String(d.tool), d.result, err)
        },
        onTask: (d) => {
          handleTask(d as { task: Record<string, unknown> })
        },
        onCritic: (d) => {
          pushItem({ id: uid(), kind: 'critic', agent: 'critic', feedback: String(d.feedback || ''), rewrites: Number(d.rewrites ?? 0), time: new Date().toLocaleTimeString() })
        },
        onMentor: (d) => {
          pushItem({ id: uid(), kind: 'mentor', agent: 'mentor', text: String(d.text || ''), time: new Date().toLocaleTimeString() })
        },
        onReflector: (d) => {
          pushItem({ id: uid(), kind: 'reflector', agent: 'reflector', patch: d.patch as Record<string, unknown>, time: new Date().toLocaleTimeString() })
          inspector.value.patch = d.patch as Record<string, unknown>
        },
        onDone: (d) => {
          status.value = 'completed'
          reconnecting.value = false
          pushItem({
            id: uid(),
            kind: 'done',
            count: Number(d.count ?? 0),
            rewrites: Number(d.rewrites ?? 0),
            elapsedMs: Math.round(performance.now() - startedAt),
            time: new Date().toLocaleTimeString(),
          })
          void fetchGraph()
          void fetchInspector()
        },
        onError: () => {
          reconnecting.value = true
        },
      },
      { lastEventId: lastEventId.value || undefined, retryMs: 1200, maxRetries: 5 },
    )

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
    selectedNodeId.value = node.id
    const logs = inspector.value.logs
    const matched = logs.find((l) => l.agent_name === node.id)
    if (matched) {
      inspector.value.state = { ...inspector.value.state, _selectedAgent: node.id, _selectedLog: matched }
    } else {
      inspector.value.state = { ...inspector.value.state, _selectedAgent: node.id }
    }
  }

  return { traceId, transcript, graph, inspector, status, lastEventId, reconnecting, selectedNodeId, graphNodes, hasReplan, manifest, weekLoadEntries, dailyLoadEntries, reallocateInfo, setTraceId, reset, pushUser, fetchGraph, fetchInspector, fetchManifest, subscribe, unsubscribe, selectNode }
})
