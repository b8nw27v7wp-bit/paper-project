import { apiClient, isApiEnvelope, isRecord } from './client'
import type { ApiEnvelope, TaskItem, TaskCreatePayload, Paginated, TaskStatus } from '@/types'

export type Task = TaskItem

export interface ListTasksParams {
  goal_id?: number
  status?: TaskStatus | string
  page?: number
  size?: number
}

function isTaskItem(v: unknown): v is TaskItem {
  if (!isRecord(v)) return false
  return typeof v.title === 'string' && typeof v.planned_start === 'string' && typeof v.planned_end === 'string'
}

function unwrapPaginated(data: unknown): Paginated<TaskItem> {
  if (isApiEnvelope<Paginated<TaskItem>>(data) && data.data && typeof data.data === 'object' && 'items' in data.data) {
    return data.data as Paginated<TaskItem>
  }
  const maybe = (data as Record<string, unknown>)?.data as unknown
  if (maybe && typeof maybe === 'object' && 'items' in (maybe as Record<string, unknown>)) {
    return maybe as Paginated<TaskItem>
  }
  return { items: [], total: 0, page: 1, size: 100 }
}

export async function listTasks(params: ListTasksParams = {}): Promise<ApiEnvelope<Paginated<TaskItem>>> {
  if (params.size !== undefined) params.size = Math.min(100, Math.max(1, Math.floor(params.size)))
  if (params.page !== undefined) params.page = Math.max(1, Math.floor(params.page))
  const { data } = await apiClient.get('/tasks', { params })
  const paginated = unwrapPaginated(data)
  if (paginated.items.length) {
    const first = paginated.items[0]
    if (!isTaskItem(first)) {
      // 非法形状仍透传，由调用方展示
    }
  }
  const envelope = isApiEnvelope<Paginated<TaskItem>>(data) ? data : { code: 200, msg: 'ok', data: paginated }
  if (!envelope.data || !('items' in envelope.data)) {
    ;(envelope as ApiEnvelope<Paginated<TaskItem>>).data = paginated
  }
  return envelope as ApiEnvelope<Paginated<TaskItem>>
}

export async function updateTask(id: number, payload: Partial<TaskCreatePayload>): Promise<ApiEnvelope<TaskItem>> {
  if (payload.planned_start && payload.planned_end) {
    const s = new Date(payload.planned_start)
    const e = new Date(payload.planned_end)
    if (!Number.isNaN(s.getTime()) && !Number.isNaN(e.getTime()) && e.getTime() <= s.getTime()) {
      throw new Error('planned_end 必须大于 planned_start')
    }
    // 统一 ISO 时区
    try { payload.planned_start = s.toISOString(); payload.planned_end = e.toISOString() } catch {}
  }
  const { data } = await apiClient.put(`/tasks/${id}`, payload)
  if (!isApiEnvelope<TaskItem>(data)) return { code: 200, msg: 'ok', data: data as TaskItem } as ApiEnvelope<TaskItem>
  return data
}

export async function batchCreateTasks(tasks: TaskCreatePayload[]): Promise<ApiEnvelope<{ created: number; items: TaskItem[] }>> {
  const { data } = await apiClient.post('/tasks/batch', { tasks })
  // 后端实际返回 Task[] 数组（plans.py:160 code 200 data: Task[]），前端曾期待 {created,items}
  if (isApiEnvelope<TaskItem[]>(data) && Array.isArray((data as ApiEnvelope<TaskItem[]>).data)) {
    const arr = (data as ApiEnvelope<TaskItem[]>).data
    return { code: 200, msg: 'ok', data: { created: arr.length, items: arr } } as ApiEnvelope<{ created: number; items: TaskItem[] }>
  }
  if (Array.isArray((data as Record<string, unknown>)?.data)) {
    const arr = (data as Record<string, unknown>).data as TaskItem[]
    return { code: 200, msg: 'ok', data: { created: arr.length, items: arr } } as ApiEnvelope<{ created: number; items: TaskItem[] }>
  }
  if (!isApiEnvelope<{ created: number; items: TaskItem[] }>(data)) {
    return { code: 200, msg: 'ok', data: { created: tasks.length, items: [] } } as ApiEnvelope<{ created: number; items: TaskItem[] }>
  }
  return data
}

export async function completeTask(
  id: number,
  payload: { actual_duration: number; completion_rate: number; delay_reason?: string },
): Promise<ApiEnvelope<Record<string, unknown>>> {
  const { data } = await apiClient.post(`/tasks/${id}/complete`, payload)
  if (!isApiEnvelope<Record<string, unknown>>(data)) {
    return { code: 200, msg: 'ok', data: (data as Record<string, unknown>) ?? {} } as ApiEnvelope<Record<string, unknown>>
  }
  return data
}

export async function deleteTask(id: number): Promise<ApiEnvelope<Record<string, unknown>>> {
  const res = await apiClient.delete(`/tasks/${id}`)
  if (res.status === 204 || res.data === '' || res.data == null) {
    return { code: 200, msg: 'ok', data: {} } as ApiEnvelope<Record<string, unknown>>
  }
  const data = res.data as unknown
  if (!isApiEnvelope<Record<string, unknown>>(data)) {
    return { code: 200, msg: 'ok', data: (data as Record<string, unknown>) ?? {} } as ApiEnvelope<Record<string, unknown>>
  }
  return data
}

// 批量更新辅助 — 供日历批量改期/完成
export async function batchUpdateTasks(
  ids: number[],
  patch: Partial<TaskCreatePayload>,
): Promise<{ ok: number; fail: number; errors: Array<{ id: number; message: string }> }> {
  let ok = 0
  let fail = 0
  const errors: Array<{ id: number; message: string }> = []
  for (const id of ids) {
    try {
      await updateTask(id, patch)
      ok++
    } catch (e: unknown) {
      fail++
      errors.push({ id, message: e instanceof Error ? e.message : String(e) })
    }
  }
  return { ok, fail, errors }
}
