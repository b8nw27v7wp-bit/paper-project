// 共享类型 — 前后端复用 / 契约层 (P1+P2)
// 设计：Goal/Task/PlanLog/Health + ApiEnvelope + 前端友好 DTO
// 约束：零 any，显式联合，Record<string,unknown> 承接 JSONB

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

export interface TaskDTO {
  id: number
  goal_id: number
  title: string
  planned_start: string // ISO
  planned_end: string // ISO
  priority: Priority
  status: TaskStatus
  source_agent?: string | null
  citations?: Citation[] | Record<string, unknown> | null
  created_at: string
}

export interface TaskCreateDTO {
  goal_id?: number | null
  title: string
  planned_start: string
  planned_end: string
  priority?: Priority
  status?: TaskStatus
  source_agent?: string | null
  citations?: Citation[] | Record<string, unknown> | null
}

export interface GoalDTO {
  id: number
  user_id: number
  title: string
  description?: string | null
  deadline: string // ISO
  subject?: string | null
  status: GoalStatus
  created_at: string
  tasks?: TaskDTO[]
}

export interface GoalCreateDTO {
  title: string
  description?: string | null
  deadline: string // ISO
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

export interface HealthEnvelope extends ApiEnvelope<HealthStatus> {}

export interface PlanLogDTO {
  id?: number
  trace_id: string
  agent_name: string // planner | researcher | executor | critic | mentor | reflector
  input?: Record<string, unknown> | null
  output?: Record<string, unknown> | null
  tool_calls?: Array<Record<string, unknown>> | null
  created_at: string
}

export type PlanEventKind =
  | 'thought'
  | 'tool_call'
  | 'task_created'
  | 'critic_feedback'
  | 'mentor_msg'
  | 'reflector_patch'
  | 'done'

export interface PlanStreamPayloads {
  thought: { agent?: string; text?: string }
  tool_call: { tool: string; args: Record<string, unknown> }
  task_created: { task: Pick<TaskDTO, 'title' | 'planned_start' | 'planned_end' | 'priority'> & Record<string, unknown> }
  critic_feedback: { feedback?: string; rewrites?: number }
  mentor_msg: { text: string }
  reflector_patch: { patch: Record<string, unknown> }
  done: { trace_id: string; count?: number; source?: string; rewrites?: number }
}

export interface PlanCreateResult {
  trace_id: string
  tasks: TaskDTO[]
  mentor_msg?: string
  citations?: Citation[]
  mode: 'multi' | 'single'
  rewrites?: number
  critic_feedback?: string
}

export interface StatsOverview {
  completion_rate: number // 0..1
  delay_rate: number // 0..1
  avg_load: number // hours/day
}

export interface StatsTrend {
  dates: string[]
  rates: number[]
  loads: number[]
}

export interface GraphNodeDTO {
  id: string
  name: string
  label?: string
  category?: number
  subject?: string | null
}

export interface GraphEdgeDTO {
  from: string
  to: string
  relation?: string
}

export interface GraphDTO {
  nodes: GraphNodeDTO[]
  edges: GraphEdgeDTO[]
}

export interface MCPServerDTO {
  name: string
  status: string
  command?: string
  tools?: string[]
  running?: boolean
}

export interface MCPToolDTO {
  server: string
  tool: string
  full_name: string
  description?: string
}

// 运行时守卫 — isApiEnvelope / isTask
export function isApiEnvelope<T>(v: unknown): v is ApiEnvelope<T> {
  if (!v || typeof v !== 'object') return false
  const o = v as Record<string, unknown>
  return typeof o.code === 'number' && typeof o.msg === 'string' && 'data' in o
}

export function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

export function assertTask(v: unknown): asserts v is TaskDTO {
  if (!isRecord(v) || typeof (v as Record<string, unknown>).title !== 'string') {
    throw new TypeError('invalid TaskDTO')
  }
}
