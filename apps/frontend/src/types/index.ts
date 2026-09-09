/**
 * 前端共享类型 — 对齐 packages/shared，零 any 前端实现
 * 保留 axios 兼容，Task[] / Record<string,unknown> 明确化
 * 供 src/api/* 与 components/views 统一导入，替代分散 any
 */

export type GoalStatus = 'active' | 'archived'
export type TaskStatus = 'todo' | 'doing' | 'done' | 'delayed'
export type Priority = 1 | 2 | 3 | 4 | 5

export interface Citation {
  chunk_id?: string
  score?: number
  source?: string
  url?: string
  snippet?: string
}

export interface TaskItem {
  id: number
  goal_id: number
  title: string
  planned_start: string
  planned_end: string
  priority: Priority
  status: TaskStatus
  source_agent?: string | null
  citations?: Citation[] | Record<string, unknown> | null
  created_at: string
}

export interface TaskCreatePayload {
  goal_id: number
  title: string
  planned_start: string
  planned_end: string
  priority?: Priority
  status?: TaskStatus
  source_agent?: string | null
  citations?: Citation[] | Record<string, unknown> | null
  id?: number
}

export interface GoalItem {
  id: number
  user_id: number
  title: string
  description?: string | null
  deadline: string
  subject?: string | null
  status: GoalStatus
  created_at: string
  tasks?: TaskItem[]
}

export interface GoalCreatePayload {
  title: string
  description?: string | null
  deadline: string
  subject?: string | null
  status?: GoalStatus
}

export interface Paginated<T> {
  items: T[]
  total: number
  page: number
  size: number
}

export interface ApiEnvelope<T> {
  code: number
  msg: string
  data: T
}

export type ServiceHealth = 'ok' | 'degraded' | 'unknown'

export interface HealthStatus {
  status: ServiceHealth
  version: string
  uptime_seconds?: number
  services?: Record<string, ServiceHealth>
  checks?: Record<string, ServiceHealth>
}

export interface PlanLogItem {
  id?: number
  trace_id: string
  agent_name: string
  input?: Record<string, unknown> | null
  output?: Record<string, unknown> | null
  tool_calls?: Array<Record<string, unknown>> | null
  citations?: Citation[] | Record<string, unknown> | null
  created_at: string
}

export interface ApprovalTaskPreview {
  title: string
  planned_start?: string
  planned_end?: string
  priority?: number
}

export interface ApprovalRequiredPayload {
  trace_id: string
  tasks_preview: ApprovalTaskPreview[]
  approve_token: string
  expires_in: number
}

export interface AgentPrefill {
  text?: string
  goal_id?: number
  source: string
  mode?: 'single' | 'multi'
  hours?: number
}

export interface PlanCreateResult {
  trace_id: string
  tasks: TaskItem[]
  mentor_msg?: string
  citations?: Citation[]
  mode: 'multi' | 'single'
  rewrites?: number
  critic_feedback?: string
}

export interface StatsOverview {
  completion_rate: number
  delay_rate: number
  avg_load: number
  llm_cost?: number
  // Wave-2 P1-9：后端 overview 已有数（stats.py:134 focus_seconds/overflow_count），按需扩展，缺失即 undefined
  focus_seconds?: number
  overflow_count?: number
}

export interface StatsTrend {
  dates: string[]
  rates: number[]
  loads: number[]
}

export interface GraphNode {
  id: string
  name: string
  label?: string
  category?: number
  subject?: string | null
}

export interface GraphEdge {
  from: string
  to: string
  relation?: string
  type?: string
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface MCPServer {
  name: string
  status: string
  command?: string
  tools?: string[]
  running?: boolean
}

export interface MCPTool {
  server: string
  tool: string
  full_name: string
  description?: string
}

// 类型守卫 — client.ts 复用，保留 axios 兼容
export function isApiEnvelope<T>(v: unknown): v is ApiEnvelope<T> {
  return (
    typeof v === 'object' &&
    v !== null &&
    typeof (v as Record<string, unknown>).code === 'number' &&
    typeof (v as Record<string, unknown>).msg === 'string' &&
    'data' in (v as Record<string, unknown>)
  )
}

export function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

export function isTaskArray(v: unknown): v is TaskItem[] {
  return Array.isArray(v) && v.every((x) => isRecord(x) && typeof (x as Record<string, unknown>).title === 'string')
}

// 通用荷载/分页守卫
export function isPaginated<T>(v: unknown): v is Paginated<T> {
  if (!isRecord(v)) return false
  return Array.isArray((v as Record<string, unknown>).items) && typeof (v as Record<string, unknown>).total === 'number'
}

// 健康状态守卫
export function isHealthStatus(v: unknown): v is HealthStatus {
  if (!isRecord(v)) return false
  const s = (v as Record<string, unknown>).status
  return s === 'ok' || s === 'degraded' || s === 'unknown'
}
