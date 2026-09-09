import { apiClient, isApiEnvelope, isElectronEnv } from './client'
import type { ApiEnvelope, PlanLogItem, PlanCreateResult } from '@/types'

// — typed 事件负载 — 旧9事件语义不变：thought/tool_call_start/tool_call_end/tool_call/task_created/critic_feedback/mentor_msg/reflector_patch/done
// 新增第10事件 approval_required（后端并行新增，契约锁定）：data={trace_id,tasks_preview,approve_token,expires_in}
export interface ApprovalTaskPreview {
  title: string
  planned_start?: string
  planned_end?: string
  priority?: number
}
export interface ApprovalRequiredData {
  trace_id: string
  tasks_preview: ApprovalTaskPreview[]
  approve_token: string
  expires_in: number
}
export interface StreamError extends Error {
  status?: number
  terminal?: boolean
}
export function makeStreamError(message: string, status?: number, terminal?: boolean): StreamError {
  const e = new Error(message) as StreamError
  if (status != null) e.status = status
  if (terminal) e.terminal = true
  return e
}
export function getStreamErrorStatus(e: unknown): number | undefined {
  try {
    const s = (e as { status?: unknown })?.status
    if (typeof s === 'number') return s
    if (e instanceof Error) {
      const m = e.message.match(/stream\s+(\d{3})/i)
      if (m) return Number(m[1])
      if (/\b404\b/.test(e.message)) return 404
      if (/\b401\b/.test(e.message)) return 401
    }
  } catch {}
  return undefined
}
// 复用 api/client.ts 的401逻辑：清 token 并跳 /login（动态 import 避免循环依赖）
export function handleStreamUnauthorized(): void {
  try {
    localStorage.removeItem('token')
    localStorage.removeItem('user_id')
  } catch {}
  try {
    const cur = typeof window !== 'undefined' ? window.location.pathname : ''
    if (cur !== '/login' && typeof window !== 'undefined') {
      // 与 client.ts:88 一致：回跳保留站内 path+search，供登录后返回
      const back = window.location.pathname + window.location.search
      import('@/router').then((m) => {
        const router = (m as unknown as { default: { push: (p: unknown) => void } }).default
        try { router.push({ path: '/login', query: { redirect: back } }) } catch {}
      }).catch(() => {
        try { window.location.href = '/login?redirect=' + encodeURIComponent(back) } catch {}
      })
    }
  } catch {}
}
export interface PlanStreamHandlers {
  onThought?: (d: { agent?: string; text?: string } & Record<string, unknown>) => void
  onTool?: (d: { tool: string; args: Record<string, unknown> } & Record<string, unknown>) => void
  onToolStart?: (d: { tool: string; agent?: string; args?: Record<string, unknown> } & Record<string, unknown>) => void
  onToolEnd?: (d: { tool: string; agent?: string; result?: unknown } & Record<string, unknown>) => void
  onTask?: (d: { task: Record<string, unknown> } & Record<string, unknown>) => void
  onCritic?: (d: { feedback?: string; rewrites?: number } & Record<string, unknown>) => void
  onMentor?: (d: { text: string } & Record<string, unknown>) => void
  onReflector?: (d: { patch: Record<string, unknown> } & Record<string, unknown>) => void
  onApproval?: (d: ApprovalRequiredData & Record<string, unknown>) => void
  onDone?: (d: { trace_id: string; count?: number; source?: string; rewrites?: number; approved?: boolean; forked_from?: string; forked_from_seq?: number } & Record<string, unknown>) => void
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

// 一次性 stream_ticket 缓存：POST /plans 返回后按 trace_id 暂存，供 fetch 流首连一次性使用
const streamTicketCache = new Map<string, string>()
export function cacheStreamTicket(trace_id: string, ticket: string): void {
  if (trace_id && ticket) streamTicketCache.set(trace_id, ticket)
}
export function takeStreamTicket(trace_id: string): string | undefined {
  const t = streamTicketCache.get(trace_id)
  if (t) streamTicketCache.delete(trace_id)
  return t
}
export function peekStreamTicket(trace_id: string): string | undefined {
  return streamTicketCache.get(trace_id)
}

// 创建计划 — 强类型返回（附带 stream_ticket 时自动缓存，供 SSE 首连使用）
// requireApproval=true 仅 multi 有效：POST 会阻塞等审批，调用方应后台 fire 后用
// listPendingApprovals 发现 trace，再订阅流拿 approval_required token
// Wave3：approval 四档 + 会话语义透传（默认旧语义：approval 缺省、ephemeral/fork=false、resume/output_schema 空即省略）
export type ApprovalMode = 'untrusted' | 'on-request' | 'never' | 'granular'
export interface CreatePlanExtra {
  approval?: ApprovalMode | string
  ephemeral?: boolean
  resume?: string
  fork?: boolean
  output_schema?: string
}
export async function createPlan(
  goal_id: number,
  preferences?: { hours_per_day: number },
  mode: 'single' | 'multi' = 'multi',
  requireApproval = false,
  extra?: CreatePlanExtra,
): Promise<ApiEnvelope<PlanCreateResult & { stream_ticket?: string; stream_ticket_expires_in?: number }>> {
  const body: Record<string, unknown> = { goal_id, preferences }
  if (requireApproval) body.require_approval = true
  if (extra?.approval != null && String(extra.approval).trim() !== '') {
    body.approval = String(extra.approval).trim()
  }
  if (extra?.ephemeral === true) body.ephemeral = true
  if (extra?.resume != null && String(extra.resume).trim() !== '') {
    body.resume = String(extra.resume).trim()
  }
  if (extra?.fork === true) body.fork = true
  if (extra?.output_schema != null && String(extra.output_schema).trim() !== '') {
    body.output_schema = String(extra.output_schema).trim()
  }
  const { data } = await apiClient.post('/plans', body, { params: { mode } })
  try {
    const inner = (data as Record<string, unknown>)?.data as Record<string, unknown> | undefined
    const holder = (inner ?? data) as Record<string, unknown>
    const tid = holder?.trace_id
    const ticket = holder?.stream_ticket
    if (typeof tid === 'string' && typeof ticket === 'string' && ticket) cacheStreamTicket(tid, ticket)
  } catch {}
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

export interface PendingApprovalItem {
  trace_id: string
  goal_id: number | null
  preview_count: number
  expires_in: number
}

// 待审批发现：POST multi+require_approval 阻塞等待期间，用此接口发现 trace_id
export async function listPendingApprovals(): Promise<ApiEnvelope<{ items: PendingApprovalItem[]; total: number }>> {
  const { data } = await apiClient.get('/plans/pending-approvals')
  return data
}

// 等待属于 goalId 的审批会话出现（找不到返回 null；timeoutMs 默认 90s，每 2s 轮询）
export async function waitForPendingApproval(goalId: number | null, timeoutMs = 90000): Promise<string | null> {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    try {
      const res = await listPendingApprovals()
      const items = res?.data?.items ?? []
      const hit = goalId != null ? items.find((it) => it.goal_id === goalId) : items[0]
      if (hit?.trace_id) return hit.trace_id
    } catch {}
    if (Date.now() >= deadline) return null
    await new Promise((r) => setTimeout(r, 2000))
  }
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
  status: 'completed' | 'replan' | 'running' | 'failed'
  // Wave-B B5：后端 sessions 暂无该字段时前端从本地映射回显，不硬造
  ephemeral?: boolean
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
  // 防御：结构性包络也可能缺 items（如 {} 空 data），归一化防 store 污染致渲染冻结
  const norm = (v: unknown): ApiEnvelope<PlanSessionsPage> => {
    const r = (v ?? {}) as Record<string, unknown>
    const d = (r.data ?? {}) as Record<string, unknown>
    return {
      code: typeof r.code === 'number' ? r.code : 200,
      msg: typeof r.msg === 'string' ? r.msg : 'ok',
      data: {
        items: Array.isArray(d.items) ? (d.items as PlanSessionItem[]) : [],
        total: Number.isFinite(Number(d.total)) ? Number(d.total) : 0,
        page: Number.isFinite(Number(d.page)) && Number(d.page) >= 1 ? Number(d.page) : page,
        size,
      },
    }
  }
  if (isApiEnvelope<PlanSessionsPage>(data)) {
    const n = norm(data)
    if (Array.isArray((data as ApiEnvelope<PlanSessionsPage>).data?.items)) return data
    return n
  }
  const maybe = (data as Record<string, unknown>)?.data as unknown
  if (maybe && typeof maybe === 'object' && Array.isArray((maybe as Record<string, unknown>).items)) {
    return { code: 200, msg: 'ok', data: maybe as PlanSessionsPage }
  }
  return { code: 200, msg: 'ok', data: { items: [], total: 0, page, size } }
}

// fetch 流式 SSE 订阅（prod 鉴权加固：EventSource 无法带 Authorization 头，改 fetch+ReadableStream）
// 约定：服务器为每条事件附 id (递增)，前端存 lastEventId，断联后以 ?trace_id=xxx&last_event_id=NN&ticket=yyy 重连
// 事件契约保持：旧9事件 thought/tool_call/tool_call_start/tool_call_end/task_created/critic_feedback/mentor_msg/reflector_patch/done 语义不变 + id/retry
// 新增 approval_required 由后端并行提供，前端仅分发不改旧语义；401 清 token 跳登录，404/maxRetries 耗尽走 terminal 不再无缝重连
export function subscribePlanStream(
  trace_id: string,
  handlers: PlanStreamHandlers,
  opts?: { lastEventId?: string | number; retryMs?: number; maxRetries?: number; ticket?: string },
): EventSource {
  let lastId: string = opts?.lastEventId != null ? String(opts.lastEventId) : ''
  let retries = 0
  const maxRetries = opts?.maxRetries ?? 5
  const baseRetry = opts?.retryMs ?? 1200
  // ticket 一次性：显式传入优先，否则取 createPlan 缓存（首连后即消费，重连只用 Bearer+lastId）
  let pendingTicket: string | undefined = opts?.ticket ?? takeStreamTicket(trace_id)
  let firstAttempt = true
  let closedByDone = false
  let abort: AbortController | null = null
  let timer: number | null = null

  type SSEListener = (e: MessageEvent) => void
  const external = new Map<string, Set<SSEListener>>()
  let onmessageProp: SSEListener | null = null
  let onerrorProp: ((e: Event) => void) | null = null

  const emitExternal = (type: string, dataStr: string, id: string) => {
    const evt = { data: dataStr, lastEventId: id || lastId, type } as unknown as MessageEvent
    const set = external.get(type)
    if (set) for (const cb of Array.from(set)) { try { cb(evt) } catch {} }
    if (type === 'message' && onmessageProp) { try { onmessageProp(evt) } catch {} }
  }

  const dispatchParsed = (evtName: string, dataStr: string, id: string) => {
    if (id != null && String(id) !== '') lastId = String(id)
    let parsed: Record<string, unknown>
    try { parsed = dataStr ? (JSON.parse(dataStr) as Record<string, unknown>) : {} } catch { parsed = {} }
    try {
      if (evtName === 'thought') handlers.onThought?.(parsed as { agent?: string; text?: string })
      else if (evtName === 'tool_call') handlers.onTool?.(parsed as { tool: string; args: Record<string, unknown> })
      else if (evtName === 'tool_call_start') handlers.onToolStart?.(parsed as { tool: string; agent?: string; args?: Record<string, unknown> })
      else if (evtName === 'tool_call_end') handlers.onToolEnd?.(parsed as { tool: string; agent?: string; result?: unknown })
      else if (evtName === 'task_created') handlers.onTask?.(parsed as { task: Record<string, unknown> })
      else if (evtName === 'critic_feedback' || evtName === 'critic') handlers.onCritic?.(parsed as { feedback?: string })
      else if (evtName === 'mentor_msg' || evtName === 'mentor') handlers.onMentor?.(parsed as { text: string })
      else if (evtName === 'reflector_patch') handlers.onReflector?.(parsed as { patch: Record<string, unknown> })
      else if (evtName === 'approval_required') handlers.onApproval?.(parsed as unknown as ApprovalRequiredData & Record<string, unknown>)
      else if (evtName === 'done') {
        try { handlers.onDone?.(parsed as { trace_id: string }) } catch {}
        closedByDone = true
        try { abort?.abort() } catch {}
        return
      }
    } catch {}
    emitExternal(evtName, dataStr, id)
    if (evtName !== 'message') emitExternal('message', dataStr, id)
  }

  const parseBlock = (block: string) => {
    let ev = 'message'
    const dataLines: string[] = []
    let id = ''
    for (const raw of block.split('\n')) {
      const line = raw.replace(/\r$/, '')
      if (!line || line.startsWith(':')) continue
      const ci = line.indexOf(':')
      if (ci === -1) continue
      const field = line.slice(0, ci).trim()
      let val = line.slice(ci + 1)
      if (val.startsWith(' ')) val = val.slice(1)
      if (field === 'event') ev = val.trim() || 'message'
      else if (field === 'data') dataLines.push(val)
      else if (field === 'id') id = val.trim()
    }
    // 空块不分发
    if (!ev && dataLines.length === 0 && !id) return
    dispatchParsed(ev, dataLines.join('\n'), id)
  }

  const buildUrl = (withTicket: boolean) => {
    const qs = new URLSearchParams({ trace_id })
    if (lastId) {
      qs.set('last_event_id', lastId)
      qs.set('lastEventId', lastId)
    }
    if (withTicket && pendingTicket) qs.set('ticket', pendingTicket)
    const base = isElectronEnv() ? 'http://127.0.0.1:8000/api/v1/plans/stream' : '/api/v1/plans/stream'
    return `${base}?${qs.toString()}`
  }

  const buildHeaders = (): Record<string, string> => {
    const h: Record<string, string> = { Accept: 'text/event-stream' }
    try {
      const token = typeof localStorage !== 'undefined' ? localStorage.getItem('token') : null
      if (token) h['Authorization'] = `Bearer ${token}`
      else {
        const uid = typeof localStorage !== 'undefined' ? localStorage.getItem('user_id') : null
        if (uid) h['X-User-Id'] = uid
      }
    } catch {}
    if (lastId) h['Last-Event-ID'] = lastId
    return h
  }

  const scheduleReconnect = (err: unknown) => {
    if (closedByDone) return
    const st = getStreamErrorStatus(err)
    const msg = err instanceof Error ? err.message : String(err ?? '')
    // 401 → 清 token 跳 /login（复用 client 逻辑），停止重连
    if (st === 401) {
      handleStreamUnauthorized()
      try { handlers.onError?.(err) } catch {}
      try { onerrorProp?.(err as Event) } catch {}
      closedByDone = true
      try { abort?.abort() } catch {}
      return
    }
    // 404 → 停止重连，交由 workbench 置 failed+空态提示
    if (st === 404 || /stream 404/.test(msg)) {
      const term = makeStreamError(msg || 'stream 404', 404, true)
      try { handlers.onError?.(term) } catch {}
      try { onerrorProp?.(term as unknown as Event) } catch {}
      closedByDone = true
      try { abort?.abort() } catch {}
      return
    }
    // 已标记 terminal 的错误不再重连
    if ((err as { terminal?: boolean })?.terminal) {
      try { handlers.onError?.(err) } catch {}
      try { onerrorProp?.(err as Event) } catch {}
      closedByDone = true
      return
    }
    if (retries < maxRetries) {
      const delay = baseRetry * Math.pow(1.5, retries)
      retries++
      try { handlers.onError?.(err) } catch {}
      try { onerrorProp?.(err as Event) } catch {}
      timer = window.setTimeout(() => { if (!closedByDone) void connect() }, delay)
    } else {
      // maxRetries 耗尽 → terminal，workbench 置 failed，不再无缝重连
      const term = makeStreamError(msg || 'stream failed', st, true)
      try { handlers.onError?.(term) } catch {}
      try { onerrorProp?.(term as unknown as Event) } catch {}
      closedByDone = true
    }
  }

  const connect = async () => {
    if (closedByDone) return
    const useTicket = firstAttempt && !!pendingTicket
    const url = buildUrl(useTicket)
    firstAttempt = false
    // ticket 仅首连携带（一次性），后续重连靠 Bearer+lastId
    pendingTicket = undefined
    const ctrl = new AbortController()
    abort = ctrl
    try {
      const resp = await fetch(url, { headers: buildHeaders(), signal: ctrl.signal })
      if (!resp.ok) {
        // 401/404 进 terminal 路径（onError 区分处理），其余按可重连错误处理
        const term = makeStreamError(`stream ${resp.status}`, resp.status, resp.status === 401 || resp.status === 404)
        if (resp.status === 401 || resp.status === 404) {
          scheduleReconnect(term)
          return
        }
        throw term
      }
      if (!resp.body) throw makeStreamError(`stream ${resp.status}`)
      const reader = resp.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buf = ''
      let gotEvent = false
      for (;;) {
        const { done, value } = await reader.read()
        if (closedByDone) { try { reader.cancel() } catch {} ; break }
        if (done) break
        buf += decoder.decode(value, { stream: true })
        buf = buf.replace(/\r\n/g, '\n')
        let idx: number
        while ((idx = buf.indexOf('\n\n')) !== -1) {
          const block = buf.slice(0, idx)
          buf = buf.slice(idx + 2)
          if (block.trim() === '') continue
          gotEvent = true
          parseBlock(block)
          if (closedByDone) { try { reader.cancel() } catch {} ; break }
        }
        if (closedByDone) break
      }
      // 尾部残留块
      if (!closedByDone && buf.trim() !== '') { try { parseBlock(buf) ; gotEvent = true } catch {} }
      if (closedByDone) return
      // 流正常结束但未收到 done（服务端截断）视为可重连；若已有事件且 lastId 推进则重连续播
      scheduleReconnect(new Error(gotEvent ? 'stream ended' : 'empty stream'))
    } catch (e: unknown) {
      if (closedByDone) return
      try {
        const name = (e as DOMException)?.name
        if (name === 'AbortError') return
      } catch {}
      scheduleReconnect(e)
    }
  }

  void connect()

  const wrapper = {
    close() {
      closedByDone = true
      if (timer != null) { try { window.clearTimeout(timer) } catch {} ; timer = null }
      try { abort?.abort() } catch {}
    },
    addEventListener(type: string, cb: EventListener) {
      const fn = cb as unknown as SSEListener
      if (!external.has(type)) external.set(type, new Set())
      external.get(type)?.add(fn)
    },
    removeEventListener(type: string, cb: EventListener) {
      external.get(type)?.delete(cb as unknown as SSEListener)
    },
    get readyState() { return closedByDone ? 2 : 1 },
  } as unknown as EventSource & { onmessage: SSEListener | null; onerror: ((e: Event) => void) | null }
  try {
    Object.defineProperty(wrapper, 'onmessage', {
      get: () => onmessageProp,
      set: (v: SSEListener | null) => { onmessageProp = v },
    })
    Object.defineProperty(wrapper, 'onerror', {
      get: () => onerrorProp,
      set: (v: ((e: Event) => void) | null) => { onerrorProp = v },
    })
  } catch {}
  return wrapper as EventSource
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

export function streamWorkbench(
  trace_id: string,
  handlers: PlanStreamHandlers,
  opts?: { lastEventId?: string | number; ticket?: string; retryMs?: number; maxRetries?: number },
): EventSource {
  // 别名封装，供 workbench store 与 PlanStream/GoalsView 复用（收敛 SSE 入口）
  return subscribePlanStream(trace_id, handlers, opts)
}

export async function abortPlan(trace_id: string): Promise<ApiEnvelope<{ aborted: boolean }>> {
  const { data } = await apiClient.post(`/plans/${trace_id}/abort`, {})
  if (isApiEnvelope<{ aborted: boolean }>(data)) return data
  const maybe = (data as Record<string, unknown>)?.data as unknown
  if (maybe && typeof maybe === 'object') return { code: 200, msg: 'ok', data: maybe as { aborted: boolean } }
  return { code: 200, msg: 'ok', data: { aborted: true } }
}

export async function approvePlan(trace_id: string, approved: boolean, token: string): Promise<ApiEnvelope<{ trace_id: string; approved: boolean }>> {
  const { data } = await apiClient.post(`/plans/${trace_id}/approve`, { approved, token })
  if (isApiEnvelope<{ trace_id: string; approved: boolean }>(data)) return data
  const maybe = (data as Record<string, unknown>)?.data as unknown
  if (maybe && typeof maybe === 'object') return { code: 200, msg: 'ok', data: maybe as { trace_id: string; approved: boolean } }
  return { code: 200, msg: 'ok', data: { trace_id, approved } }
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

// Wave-B：审批规则三件套（后端契约锁定，风格对齐 approvePlan/abortPlan + isApiEnvelope）
export type ApproveRuleDecision = 'Allow' | 'Prompt' | 'Forbidden'
export interface ApproveRule {
  prefix: string
  decision: string
  justification?: string | null
}
export interface ApproveRuleResult {
  trace_id: string
  prefix: string
  decision: string
  justification?: string | null
}

export async function createApproveRule(
  trace_id: string,
  payload: { prefix: string; decision: string; justification?: string },
): Promise<ApiEnvelope<ApproveRuleResult>> {
  const body: Record<string, unknown> = { prefix: payload.prefix, decision: payload.decision }
  if (payload.justification != null && String(payload.justification).trim() !== '') {
    body.justification = String(payload.justification)
  }
  const { data } = await apiClient.post(`/plans/${trace_id}/approve-rule`, body)
  if (isApiEnvelope<ApproveRuleResult>(data)) return data
  const maybe = (data as Record<string, unknown>)?.data as unknown
  if (maybe && typeof maybe === 'object') return { code: 200, msg: 'ok', data: maybe as ApproveRuleResult }
  return { code: 200, msg: 'ok', data: data as ApproveRuleResult }
}

export async function listApproveRules(): Promise<ApiEnvelope<{ rules: ApproveRule[]; total: number }>> {
  const { data } = await apiClient.get('/plans/approve-rules')
  if (isApiEnvelope<{ rules: ApproveRule[]; total: number }>(data)) return data
  const maybe = (data as Record<string, unknown>)?.data as unknown
  if (maybe && typeof maybe === 'object' && Array.isArray((maybe as Record<string, unknown>).rules)) {
    return { code: 200, msg: 'ok', data: maybe as { rules: ApproveRule[]; total: number } }
  }
  return { code: 200, msg: 'ok', data: { rules: [], total: 0 } }
}

export async function deleteApproveRule(prefix: string): Promise<ApiEnvelope<{ deleted: boolean }>> {
  const { data } = await apiClient.delete('/plans/approve-rules', { data: { prefix } })
  if (isApiEnvelope<{ deleted: boolean }>(data)) return data
  const maybe = (data as Record<string, unknown>)?.data as unknown
  if (maybe && typeof maybe === 'object') return { code: 200, msg: 'ok', data: maybe as { deleted: boolean } }
  return { code: 200, msg: 'ok', data: { deleted: true } }
}

// Wave-B B4：终态聚合直读（供复刻）
export interface PlanLastTask {
  title: string
  planned_start?: string
  planned_end?: string
  priority?: number
  [k: string]: unknown
}
export interface PlanLast {
  trace_id: string
  tasks: PlanLastTask[]
  done: Record<string, unknown>
  count: number
}

export async function getPlanLast(trace_id: string): Promise<ApiEnvelope<PlanLast>> {
  const { data } = await apiClient.get(`/plans/${trace_id}/last`)
  if (isApiEnvelope<PlanLast>(data)) return data
  const maybe = (data as Record<string, unknown>)?.data as unknown
  if (maybe && typeof maybe === 'object' && Array.isArray((maybe as Record<string, unknown>).tasks)) {
    return { code: 200, msg: 'ok', data: maybe as PlanLast }
  }
  return { code: 200, msg: 'ok', data: { trace_id, tasks: [], done: {}, count: 0 } }
}

// 复刻守卫：tasks 空即阻断（畸形包络回退空数组不静默建空会话，由调用方 toast）
export function ensureForkTasks(tasks: unknown): asserts tasks is PlanLastTask[] {
  if (!Array.isArray(tasks) || tasks.length === 0) {
    throw new Error('源会话暂无任务，无法复刻')
  }
}

// Wave-B B3：追问入队（store.steer 复用此入口便于单测，语义与原 store.steer 一致）
export async function steerPlan(trace_id: string, message: string): Promise<ApiEnvelope<{ queued: number }>> {
  const { data } = await apiClient.post(`/plans/${trace_id}/steer`, { message: message.slice(0, 2000) })
  if (isApiEnvelope<{ queued: number }>(data)) return data
  const maybe = (data as Record<string, unknown>)?.data as unknown
  if (maybe && typeof maybe === 'object' && typeof (maybe as Record<string, unknown>).queued === 'number') {
    return { code: 200, msg: 'ok', data: maybe as { queued: number } }
  }
  const flat = (data as Record<string, unknown>)?.queued
  if (typeof flat === 'number') return { code: 200, msg: 'ok', data: { queued: flat } }
  return { code: 200, msg: 'ok', data: { queued: 1 } }
}

// Wave-B B6：工具详情清单（description + schema），失败由调用方回退 manifest name/label
export interface AgentToolDetailed {
  name: string
  label?: string
  description?: string
  schema?: unknown
}

export async function listAgentTools(): Promise<ApiEnvelope<AgentToolDetailed[]>> {
  const { data } = await apiClient.get('/agent/tools')
  if (isApiEnvelope<AgentToolDetailed[]>(data) && Array.isArray(data.data)) return data
  const maybe = (data as Record<string, unknown>)?.data as unknown
  if (Array.isArray(maybe)) return { code: 200, msg: 'ok', data: maybe as AgentToolDetailed[] }
  if (maybe && typeof maybe === 'object' && Array.isArray((maybe as Record<string, unknown>).tools)) {
    return { code: 200, msg: 'ok', data: (maybe as Record<string, unknown>).tools as AgentToolDetailed[] }
  }
  if (Array.isArray(data)) return { code: 200, msg: 'ok', data: data as unknown as AgentToolDetailed[] }
  return { code: 200, msg: 'ok', data: [] }
}

// 工具：校验 PlanLog 数组
export function isPlanLogArray(v: unknown): v is PlanLogItem[] {
  return Array.isArray(v) && v.every((x) => typeof x === 'object' && x !== null && typeof (x as Record<string, unknown>).trace_id === 'string')
}
