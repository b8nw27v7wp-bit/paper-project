import { apiClient, isApiEnvelope, isElectronEnv } from './client'
import type { ApiEnvelope, PlanLogItem, PlanCreateResult } from '@/types'

// — typed 事件负载 — 8事件：thought/tool_call_start/tool_call_end/tool_call/task_created/critic_feedback/mentor_msg/reflector_patch/done
export interface PlanStreamHandlers {
  onThought?: (d: { agent?: string; text?: string } & Record<string, unknown>) => void
  onTool?: (d: { tool: string; args: Record<string, unknown> } & Record<string, unknown>) => void
  onToolStart?: (d: { tool: string; agent?: string; args?: Record<string, unknown> } & Record<string, unknown>) => void
  onToolEnd?: (d: { tool: string; agent?: string; result?: unknown } & Record<string, unknown>) => void
  onTask?: (d: { task: Record<string, unknown> } & Record<string, unknown>) => void
  onCritic?: (d: { feedback?: string; rewrites?: number } & Record<string, unknown>) => void
  onMentor?: (d: { text: string } & Record<string, unknown>) => void
  onReflector?: (d: { patch: Record<string, unknown> } & Record<string, unknown>) => void
  onDone?: (d: { trace_id: string; count?: number; source?: string; rewrites?: number } & Record<string, unknown>) => void
  onError?: (e: Event | unknown) => void
}

export interface WorkbenchGraphNode {
  id: string
  name: string
  status: 'pending' | 'running' | 'success' | 'error'
  started_at: string | null
  finished_at: string | null
}
export interface WorkbenchGraphEdge {
  from: string
  to: string
  type: string
}
export interface WorkbenchGraph {
  nodes: WorkbenchGraphNode[]
  edges: WorkbenchGraphEdge[]
  status: string
  trace_id: string
  rewrites?: number
}
export interface WorkbenchInspector {
  state: Record<string, unknown>
  logs: PlanLogItem[]
  patch: Record<string, unknown>
  trace_id: string
}

export interface AgentToolEntry {
  name: string
  label?: string
  description?: string
  schema?: unknown
}

export interface AgentManifest {
  name: string
  description: string
  version: string
  tools: AgentToolEntry[]
  entry: string
  stream: string
  graph: string
  inspector: string
  cli: string
  sub_agents: string[]
}

// 创建计划 — 强类型返回
export async function createPlan(
  goal_id: number,
  preferences?: { hours_per_day: number },
  mode: 'single' | 'multi' = 'multi',
): Promise<ApiEnvelope<PlanCreateResult>> {
  const { data } = await apiClient.post('/plans', { goal_id, preferences }, { params: { mode } })
  if (!isApiEnvelope<PlanCreateResult>(data)) {
    return { code: 200, msg: 'ok', data: data as PlanCreateResult } as ApiEnvelope<PlanCreateResult>
  }
  return data
}

export interface PlanSessionNodeSummary {
  has_log: boolean
  rewrites?: number
  replan?: boolean
}

export interface PlanSessionItem {
  trace_id: string
  mode: 'single' | 'multi'
  goal_id: number
  goal_title: string
  started_at: string | null
  last_event_at: string | null
  event_count: number
  node_summary: Record<string, PlanSessionNodeSummary>
  status: 'completed' | 'replan' | 'running'
}

export interface PlanSessionsPage {
  items: PlanSessionItem[]
  total: number
  page: number
  size: number
}

export async function listSessions(page = 1, size = 20): Promise<ApiEnvelope<PlanSessionsPage>> {
  if (size > 100) size = 100
  if (page < 1) page = 1
  const { data } = await apiClient.get('/plans/sessions', { params: { page, size } })
  if (isApiEnvelope<PlanSessionsPage>(data)) return data
  const maybe = (data as Record<string, unknown>)?.data as unknown
  if (maybe && typeof maybe === 'object' && Array.isArray((maybe as Record<string, unknown>).items)) {
    return { code: 200, msg: 'ok', data: maybe as PlanSessionsPage }
  }
  return { code: 200, msg: 'ok', data: { items: [], total: 0, page, size } }
}

// 带 Last-Event-ID 的 SSE 订阅 — 支持断线重连
// 约定：服务器为每条事件附 id (递增)，前端存 lastEventId，断联后以 ?trace_id=xxx&last_event_id=NN 重连
export function subscribePlanStream(
  trace_id: string,
  handlers: PlanStreamHandlers,
  opts?: { lastEventId?: string | number; retryMs?: number; maxRetries?: number },
): EventSource {
  let lastId: string = opts?.lastEventId != null ? String(opts.lastEventId) : ''
  let retries = 0
  const maxRetries = opts?.maxRetries ?? 3
  const baseRetry = opts?.retryMs ?? 3000

  const buildUrl = () => {
    const qs = new URLSearchParams({ trace_id })
    if (lastId) qs.set('last_event_id', lastId)
    const base = isElectronEnv() ? 'http://127.0.0.1:8000/api/v1/plans/stream' : '/api/v1/plans/stream'
    return `${base}?${qs.toString()}`
  }

  let es: EventSource | null = null
  let closedByDone = false

  const attach = (source: EventSource) => {
    // 以服务器 id 为真，移除本地 bumpId 自增，lastId 仅由 storeLastId 更新
    const storeLastId = (e: MessageEvent) => {
      const lid = (e as MessageEvent & { lastEventId?: string }).lastEventId
      if (lid != null && String(lid) !== '') lastId = String(lid)
    }

    const add = (evt: string, cb: (d: Record<string, unknown>) => void) => {
      source.addEventListener(evt, (e: MessageEvent) => {
        storeLastId(e)
        try {
          cb(JSON.parse((e as MessageEvent).data) as Record<string, unknown>)
        } catch {}
      })
    }
    add('thought', (d) => handlers.onThought?.(d as { agent?: string; text?: string }))
    add('tool_call', (d) => handlers.onTool?.(d as { tool: string; args: Record<string, unknown> }))
    add('tool_call_start', (d) => handlers.onToolStart?.(d as { tool: string; agent?: string; args?: Record<string, unknown> }))
    add('tool_call_end', (d) => handlers.onToolEnd?.(d as { tool: string; agent?: string; result?: unknown }))
    add('task_created', (d) => handlers.onTask?.(d as { task: Record<string, unknown> }))
    add('critic_feedback', (d) => handlers.onCritic?.(d as { feedback?: string }))
    // 兼容后端可能发 critic (无后缀)
    add('critic', (d) => handlers.onCritic?.(d as { feedback?: string }))
    add('mentor_msg', (d) => handlers.onMentor?.(d as { text: string }))
    add('mentor', (d) => handlers.onMentor?.(d as { text: string }))
    add('reflector_patch', (d) => handlers.onReflector?.(d as { patch: Record<string, unknown> }))
    source.addEventListener('done', (e: MessageEvent) => {
      storeLastId(e)
      try {
        handlers.onDone?.(JSON.parse((e as MessageEvent).data) as { trace_id: string })
      } catch {}
      closedByDone = true
      source.close()
    })
    source.onerror = (e: Event) => {
      if (closedByDone) return
      // 若未完成且重连次数未超限，则指数退避重连
      if (retries < maxRetries) {
        const delay = baseRetry * Math.pow(1.5, retries)
        retries++
        source.close()
        handlers.onError?.(e)
        // 延迟后以 lastId 重建
        window.setTimeout(() => {
          if (closedByDone) return
          es = new EventSource(buildUrl())
          attach(es)
        }, delay)
      } else {
        handlers.onError?.(e)
        source.close()
      }
    }
    // 通用 message 也记录 id
    source.onmessage = (e: MessageEvent) => {
      storeLastId(e)
    }
  }

  es = new EventSource(buildUrl())
  attach(es)

  // 为外部 close 提供包装，确保断开后不再重连
  const originalClose = es.close.bind(es)
  const proxy = es as EventSource & { _manualClose?: boolean }
  proxy.close = () => {
    closedByDone = true
    originalClose()
  }
  // 外部可通过 es.close() 主动关闭；内部重连会替换 es 引用，但返回的最初引用 close 可终止链
  // 为确保外部持有的是可控实例，提供包装返回
  return proxy
}

export async function getPlanLogs(trace_id: string): Promise<ApiEnvelope<PlanLogItem[]>> {
  const { data } = await apiClient.get(`/plans/${trace_id}/logs`)
  if (!isApiEnvelope<PlanLogItem[]>(data)) {
    const maybe = (data as Record<string, unknown>)?.data as unknown
    if (Array.isArray(maybe)) return { code: 200, msg: 'ok', data: maybe as PlanLogItem[] } as ApiEnvelope<PlanLogItem[]>
    if (Array.isArray(data)) return { code: 200, msg: 'ok', data: data as unknown as PlanLogItem[] } as ApiEnvelope<PlanLogItem[]>
    return { code: 200, msg: 'ok', data: [] } as ApiEnvelope<PlanLogItem[]>
  }
  return data
}

export async function getPlanGraph(trace_id: string): Promise<ApiEnvelope<WorkbenchGraph>> {
  const { data } = await apiClient.get(`/plans/${trace_id}/graph`)
  if (isApiEnvelope<WorkbenchGraph>(data)) return data
  const maybe = (data as Record<string, unknown>)?.data as unknown
  if (maybe && typeof maybe === 'object' && Array.isArray((maybe as Record<string, unknown>).nodes)) {
    return { code: 200, msg: 'ok', data: maybe as WorkbenchGraph }
  }
  return { code: 200, msg: 'ok', data: { nodes: [], edges: [], status: 'unknown', trace_id } }
}

export async function getPlanInspector(trace_id: string): Promise<ApiEnvelope<WorkbenchInspector>> {
  const { data } = await apiClient.get(`/plans/${trace_id}/inspector`)
  if (isApiEnvelope<WorkbenchInspector>(data)) return data
  const maybe = (data as Record<string, unknown>)?.data as unknown
  if (maybe && typeof maybe === 'object' && 'state' in (maybe as Record<string, unknown>)) {
    return { code: 200, msg: 'ok', data: maybe as WorkbenchInspector }
  }
  return { code: 200, msg: 'ok', data: { state: {}, logs: [], patch: {}, trace_id } }
}

export function streamWorkbench(trace_id: string, handlers: PlanStreamHandlers, opts?: { lastEventId?: string | number }): EventSource {
  // 别名封装，供 workbench store 使用
  return subscribePlanStream(trace_id, handlers, opts)
}

export async function getAgentManifest(): Promise<ApiEnvelope<AgentManifest>> {
  const { data } = await apiClient.get('/agent/manifest')
  if (isApiEnvelope<AgentManifest>(data)) return data
  const maybe = (data as Record<string, unknown>)?.data as unknown
  if (maybe && typeof maybe === 'object' && 'name' in (maybe as Record<string, unknown>)) {
    return { code: 200, msg: 'ok', data: maybe as AgentManifest }
  }
  return { code: 200, msg: 'ok', data: data as AgentManifest }
}

// 工具：校验 PlanLog 数组
export function isPlanLogArray(v: unknown): v is PlanLogItem[] {
  return Array.isArray(v) && v.every((x) => typeof x === 'object' && x !== null && typeof (x as Record<string, unknown>).trace_id === 'string')
}
