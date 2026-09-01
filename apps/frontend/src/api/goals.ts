import { apiClient, isApiEnvelope } from './client'
import type { ApiEnvelope, GoalItem, GoalCreatePayload, Paginated } from '@/types'

// 显式重导出，供外部复用，保持零 any
export type Goal = GoalItem
export type GoalCreate = GoalCreatePayload

// 分页参数
export interface ListGoalsParams {
  status?: string
  page?: number
  size?: number
}

function assertGoal(v: unknown): asserts v is GoalItem {
  if (!v || typeof v !== 'object') throw new TypeError('invalid goal')
  const o = v as Record<string, unknown>
  if (typeof o.title !== 'string' || typeof o.deadline !== 'string') throw new TypeError('invalid goal shape')
}

// 守卫 + 解包
function unwrapPaginated(data: unknown): Paginated<GoalItem> {
  // 后端返回 {code,msg,data:{items,total,page,size}}
  if (isApiEnvelope<Paginated<GoalItem>>(data) && data.data && typeof data.data === 'object' && 'items' in data.data) {
    const p = data.data as Paginated<GoalItem>
    if (Array.isArray(p.items) && typeof p.total === 'number') return p
  }
  // 兼容直接 {data:{items}}
  const maybe = (data as Record<string, unknown>)?.data as unknown
  if (maybe && typeof maybe === 'object' && 'items' in (maybe as Record<string, unknown>)) {
    return maybe as Paginated<GoalItem>
  }
  // 兜底
  return (data as Paginated<GoalItem>) ?? { items: [], total: 0, page: 1, size: 20 }
}

export async function listGoals(params: ListGoalsParams = {}): Promise<ApiEnvelope<Paginated<GoalItem>>> {
  // 分页归一：与后端 le100 对齐，前端默认 20，超限前置 clamp
  if (params.size !== undefined) params.size = Math.min(100, Math.max(1, Math.floor(params.size)))
  if (params.page !== undefined) params.page = Math.max(1, Math.floor(params.page))
  const { data } = await apiClient.get('/goals', { params })
  if (!isApiEnvelope<Paginated<GoalItem>>(data)) {
    // 仍尝试解析并包一层，保证调用方 res.data.items 可用
  }
  // 跨层标准化：确保 data.data.items 存在
  const paginated = unwrapPaginated(data)
  // 校验少量样本
  if (paginated.items.length) {
    try { assertGoal(paginated.items[0]) } catch { /* ignore */ }
  }
  // 保持与既往调用兼容：返回 envelope，但内部已标准化
  const envelope = isApiEnvelope<Paginated<GoalItem>>(data) ? data : { code: 200, msg: 'ok', data: paginated }
  // 若 envelope.data 仍非分页，覆盖
  if (!envelope.data || !('items' in envelope.data)) {
    ;(envelope as ApiEnvelope<Paginated<GoalItem>>).data = paginated
  }
  return envelope as ApiEnvelope<Paginated<GoalItem>>
}

export async function createGoal(payload: GoalCreatePayload): Promise<ApiEnvelope<GoalItem>> {
  // 前置校验与 05-API 3.2 对齐：title 1-200 + deadline>now+1d，失败前不发请求提升体验
  const title = (payload.title || '').trim()
  if (!title || title.length > 200) throw new Error('标题需 1-200 字符')
  if (!payload.deadline) throw new Error('截止时间必填')
  try {
    const d = new Date(payload.deadline)
    if (Number.isNaN(d.getTime())) throw new Error('截止时间非 ISO8601')
    if (d.getTime() <= Date.now() + 86400000) throw new Error('截止时间需 > 当前时间+1天')
    // 统一用 toISOString 带时区，避免 YYYY-MM-DD 漂1天
    payload.deadline = d.toISOString()
  } catch (e) {
    if (e instanceof Error && e.message.includes('截止')) throw e
    throw new Error('截止时间非 ISO8601')
  }
  const { data } = await apiClient.post('/goals', payload)
  if (!isApiEnvelope<GoalItem>(data)) {
    return { code: 200, msg: 'ok', data: data as GoalItem } as ApiEnvelope<GoalItem>
  }
  return data
}

export async function getGoal(id: number): Promise<ApiEnvelope<GoalItem>> {
  const { data } = await apiClient.get(`/goals/${id}`)
  if (!isApiEnvelope<GoalItem>(data)) {
    return { code: 200, msg: 'ok', data: data as GoalItem } as ApiEnvelope<GoalItem>
  }
  return data
}

export async function updateGoal(id: number, payload: Partial<GoalCreatePayload>): Promise<ApiEnvelope<GoalItem>> {
  if (payload.title !== undefined) {
    const t = (payload.title || '').trim()
    if (!t || t.length > 200) throw new Error('标题需 1-200 字符')
    payload.title = t
  }
  if (payload.deadline) {
    try {
      const d = new Date(payload.deadline)
      if (Number.isNaN(d.getTime())) throw new Error('截止时间非 ISO8601')
      // 更新时同样 toISOString 统一时区，避免 YYYY-MM-DD 漂移
      payload.deadline = d.toISOString()
    } catch (e) {
      if (e instanceof Error && e.message.includes('截止')) throw e
      throw new Error('截止时间非 ISO8601')
    }
  }
  const { data } = await apiClient.put(`/goals/${id}`, payload)
  if (!isApiEnvelope<GoalItem>(data)) {
    return { code: 200, msg: 'ok', data: data as GoalItem } as ApiEnvelope<GoalItem>
  }
  return data
}

export async function deleteGoal(id: number): Promise<ApiEnvelope<Record<string, unknown>>> {
  const res = await apiClient.delete(`/goals/${id}`)
  // 204 No Content 视为成功，后端 goals.py:102 204 空体
  if (res.status === 204 || res.data === '' || res.data == null) {
    return { code: 200, msg: 'ok', data: {} } as ApiEnvelope<Record<string, unknown>>
  }
  const data = res.data as unknown
  if (!isApiEnvelope<Record<string, unknown>>(data)) {
    return { code: 200, msg: 'ok', data: (data as Record<string, unknown>) ?? {} } as ApiEnvelope<Record<string, unknown>>
  }
  return data
}

// 批量辅助：前端批量导入CSV场景，逐条创建时的错误聚合
export interface BatchCreateResult {
  ok: number
  fail: number
  errors: Array<{ index: number; message: string }>
}

export async function batchCreateGoals(items: GoalCreatePayload[]): Promise<BatchCreateResult> {
  let ok = 0
  let fail = 0
  const errors: Array<{ index: number; message: string }> = []
  for (let i = 0; i < items.length; i++) {
    try {
      await createGoal(items[i])
      ok++
    } catch (e: unknown) {
      fail++
      const msg = e instanceof Error ? e.message : String(e)
      errors.push({ index: i, message: msg })
    }
  }
  return { ok, fail, errors }
}
