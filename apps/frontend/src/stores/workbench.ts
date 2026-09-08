import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { streamWorkbench, getPlanGraph, getPlanInspector, getAgentManifest, peekStreamTicket, getStreamErrorStatus } from '@/api/plans'
import type { WorkbenchGraph, WorkbenchInspector, WorkbenchGraphNode, AgentManifest, ApprovalRequiredData } from '@/api/plans'

export type TranscriptKind = 'user' | 'thought' | 'tool' | 'plan' | 'critic' | 'mentor' | 'reflector' | 'compact' | 'done' | 'approval'

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

export interface TranscriptApproval {
  traceId: string
  tasksPreview: TranscriptTask[]
  approveToken: string
  expiresIn: number
  status: 'pending' | 'approved' | 'rejected'
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
  tokensEstimate?: number
  time: string
  approval?: TranscriptApproval
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
  // 一次性 stream_ticket：由 createPlan 缓存或外部传入，首连消费后清空（重连走 Bearer+lastId）
  const streamTicket = ref<string>('')
  // Inspector 日志过滤：agent_name 下拉，空串=全部
  const logAgentFilter = ref<string>('')
  const failMessage = ref<string>('')

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

  const agentNameOptions = computed<string[]>(() => {
    const s = new Set<string>()
    for (const l of inspector.value.logs) {
      if (l.agent_name) s.add(l.agent_name)
    }
    return Array.from(s).sort()
  })

  const filteredLogs = computed(() => {
    if (!logAgentFilter.value) return inspector.value.logs
    return inspector.value.logs.filter((l) => l.agent_name === logAgentFilter.value)
  })

  // 待审批派生：右栏 MonitorPanel 显隐 + 会话 pill 共用，事件契约不变
  const hasPendingApproval = computed(() =>
    transcript.value.some((it) => it.kind === 'approval' && it.approval?.status === 'pending'),
  )
  const pendingApproval = computed<TranscriptApproval | null>(() =>
    transcript.value.find((it) => it.kind === 'approval' && it.approval?.status === 'pending')?.approval ?? null,
  )

  function uid(): string {
    return `t${Date.now()}${Math.random().toString(36).slice(2, 8)}`
  }

  function transcriptChars(): number {
    let n = 0
    for (const it of transcript.value) {
      if (it.text) n += it.text.length
      if (it.feedback) n += it.feedback.length
      if (it.tasks) {
        for (const t of it.tasks) {
          if (t.title) n += t.title.length
        }
      }
    }
    return n
  }

  function buildDoneUsageText(elapsedMs: number, tokensEstimate: number): string {
    return `耗时 ${(elapsedMs / 1000).toFixed(1)} 秒 · 约 ${tokensEstimate} tokens（估算）`
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
    streamTicket.value = ''
    logAgentFilter.value = ''
    failMessage.value = ''
    toolStartMap.clear()
    if (es) {
      try { es.close() } catch {}
      es = null
    }
  }

  function setTraceId(id: string, ticket?: string) {
    if (traceId.value !== id) {
      reset()
      traceId.value = id
    }
    // ticket 优先显式传入，否则自动拾取 createPlan 缓存（fetch 首连一次性）
    if (ticket) streamTicket.value = ticket
    else if (id) {
      try {
        const cached = peekStreamTicket(id)
        if (cached) streamTicket.value = cached
      } catch {}
    }
  }

  function setStreamTicket(ticket: string) {
    streamTicket.value = ticket || ''
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

  function handleApproval(d: ApprovalRequiredData) {
    const list = Array.isArray(d.tasks_preview) ? d.tasks_preview : []
    const tasksPreview: TranscriptTask[] = list.map((t) => ({
      title: String(t.title ?? ''),
      planned_start: t.planned_start != null ? String(t.planned_start) : undefined,
      planned_end: t.planned_end != null ? String(t.planned_end) : undefined,
      priority: Number(t.priority ?? 3),
    }))
    pushItem({
      id: uid(),
      kind: 'approval',
      agent: 'planner',
      tasks: tasksPreview,
      time: new Date().toLocaleTimeString(),
      approval: {
        traceId: String(d.trace_id || traceId.value || ''),
        tasksPreview,
        approveToken: String(d.approve_token || ''),
        expiresIn: Number(d.expires_in ?? 0),
        status: 'pending',
      },
    })
  }

  function resolveApproval(approveToken: string, ok: boolean) {
    const it = transcript.value.find((x) => x.kind === 'approval' && x.approval?.approveToken === approveToken)
    if (it?.approval) it.approval.status = ok ? 'approved' : 'rejected'
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
    reconnecting.value = false
    failMessage.value = ''
    startedAt = performance.now()
    // 收敛复用 streamWorkbench 别名（首连一次性 ticket，重连 Bearer+lastId）
    es = streamWorkbench(
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
          const err = (d as Record<string, unknown>).error != null ? String((d as Record<string, unknown>).error) : undefined
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
        onApproval: (d) => {
          handleApproval(d as ApprovalRequiredData)
        },
        onDone: (d) => {
          status.value = 'completed'
          reconnecting.value = false
          failMessage.value = ''
          const elapsedMs = Math.round(performance.now() - startedAt)
          const tokensEstimate = Math.ceil(transcriptChars() / 4)
          pushItem({
            id: uid(),
            kind: 'done',
            count: Number(d.count ?? 0),
            rewrites: Number(d.rewrites ?? 0),
            elapsedMs,
            tokensEstimate,
            text: buildDoneUsageText(elapsedMs, tokensEstimate),
            time: new Date().toLocaleTimeString(),
          })
          void fetchGraph()
          void fetchInspector()
        },
        onError: (e: unknown) => {
          const st = getStreamErrorStatus(e)
          const msg = e instanceof Error ? e.message : String(e ?? '')
          const terminal = Boolean((e as { terminal?: boolean })?.terminal)
          // 401 已由 plans.ts 清 token 跳 /login，这里仅停止重连
          if (st === 401) {
            reconnecting.value = false
            return
          }
          // 404 / maxRetries 耗尽 → failed，不再无缝重连，视图按 failed 渲染空态提示
          if (st === 404 || /404/.test(msg) || terminal || /max retries|stream failed|exhausted/i.test(msg)) {
            reconnecting.value = false
            status.value = 'failed'
            failMessage.value = st === 404 || /404/.test(msg)
              ? '规划会话不存在（404），请重新发起规划'
              : '连接中断，已停止重连，可点击重试'
            const last = transcript.value[transcript.value.length - 1]
            if (!last || last.kind !== 'thought' || last.text !== failMessage.value) {
              pushItem({ id: uid(), kind: 'thought', agent: 'system', text: failMessage.value, time: new Date().toLocaleTimeString() })
            }
            return
          }
          reconnecting.value = true
        },
      },
      { lastEventId: lastEventId.value || undefined, retryMs: 1200, maxRetries: 5, ticket: streamTicket.value || undefined },
    )
    // ticket 一次性已移交首连，重连靠 Bearer+lastId，清空避免复用 401
    streamTicket.value = ''

    try {
      es.addEventListener('message', syncServerId as unknown as EventListener)
      const evtNames: string[] = ['thought','tool_call','tool_call_start','tool_call_end','task_created','critic_feedback','critic','mentor_msg','mentor','reflector_patch','approval_required','done']
      for (const n of evtNames) {
        es.addEventListener(n, syncServerId as unknown as EventListener)
      }
    } catch {}
  }

  function unsubscribe() {
    if (es) { try { es.close() } catch {}; es = null }
    reconnecting.value = false
    if (status.value === 'running') status.value = 'completed'
  }

  // 重同步：审批通过后服务端继续落库，流是连接时快照，需重置后重连拿尾部（done/任务）
  function resync() {
    const id = traceId.value
    if (!id) return
    reset()
    traceId.value = id
    subscribe()
    void fetchGraph()
    void fetchInspector()
  }

  // 延迟重同步：审批面板 emit 后调用，默认 4s（事件契约不变，仅复用 resync）
  function resyncDelayed(ms = 4000) {
    window.setTimeout(() => { try { resync() } catch {} }, ms)
  }

  function selectNode(node: WorkbenchGraphNode) {
    selectNodeById(node.id)
  }

  function selectNodeById(id: string) {
    if (!id) return
    selectedNodeId.value = id
    const logs = inspector.value.logs
    const matched = logs.find((l) => l.agent_name === id)
    if (matched) {
      inspector.value.state = { ...inspector.value.state, _selectedAgent: id, _selectedLog: matched }
    } else {
      inspector.value.state = { ...inspector.value.state, _selectedAgent: id }
    }
  }

  return { traceId, transcript, graph, inspector, status, lastEventId, reconnecting, selectedNodeId, streamTicket, logAgentFilter, failMessage, agentNameOptions, filteredLogs, graphNodes, hasReplan, hasPendingApproval, pendingApproval, manifest, weekLoadEntries, dailyLoadEntries, reallocateInfo, setTraceId, setStreamTicket, reset, resync, resyncDelayed, pushUser, fetchGraph, fetchInspector, fetchManifest, subscribe, unsubscribe, selectNode, selectNodeById, resolveApproval }
})
