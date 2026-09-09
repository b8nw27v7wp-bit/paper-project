import { apiClient, isApiEnvelope, isRecord } from './client'
import type { ApiEnvelope, StatsOverview, StatsTrend } from '@/types'

function ensureOverview(v: unknown): StatsOverview {
  if (isRecord(v)) {
    const r = v as Record<string, unknown>
    if (typeof r.completion_rate === 'number' && typeof r.delay_rate === 'number') {
      return {
        completion_rate: Number(r.completion_rate) || 0,
        delay_rate: Number(r.delay_rate) || 0,
        avg_load: Number(r.avg_load ?? 0),
        // 成本估算：按 DeepSeek 0.002/任务
        llm_cost: Number((r.llm_cost as number) ?? 0),
        // Wave-2 P1-9：透传后端已有 focus_seconds/overflow_count，缺失即 undefined 由视图回退
        focus_seconds: typeof r.focus_seconds === 'number' ? Math.max(0, Math.floor(r.focus_seconds)) : undefined,
        overflow_count: typeof r.overflow_count === 'number' ? Math.max(0, Math.floor(r.overflow_count)) : undefined,
      }
    }
  }
  return { completion_rate: 0, delay_rate: 0, avg_load: 0, llm_cost: 0 }
}

function ensureTrend(v: unknown): StatsTrend {
  if (isRecord(v)) {
    const r = v as Record<string, unknown>
    if (Array.isArray(r.dates) && Array.isArray(r.rates) && Array.isArray(r.loads)) {
      return { dates: r.dates as string[], rates: r.rates as number[], loads: r.loads as number[] }
    }
  }
  return { dates: [], rates: [], loads: [] }
}

export async function fetchStatsOverview(range: string = '7d'): Promise<ApiEnvelope<StatsOverview>> {
  const { data } = await apiClient.get('/stats/overview', { params: { range } })
  if (isApiEnvelope<StatsOverview>(data)) {
    return { ...data, data: ensureOverview(data.data) }
  }
  const maybe = (data as Record<string, unknown>)?.data as unknown
  if (maybe) return { code: 200, msg: 'ok', data: ensureOverview(maybe) }
  return { code: 200, msg: 'ok', data: ensureOverview(data) }
}

export async function fetchStatsTrend(range: string = '30d'): Promise<ApiEnvelope<StatsTrend>> {
  const { data } = await apiClient.get('/stats/trend', { params: { range } })
  if (isApiEnvelope<StatsTrend>(data)) {
    return { ...data, data: ensureTrend(data.data) }
  }
  const maybe = (data as Record<string, unknown>)?.data as unknown
  if (maybe) return { code: 200, msg: 'ok', data: ensureTrend(maybe) }
  return { code: 200, msg: 'ok', data: ensureTrend(data) }
}

export async function runStatsExperiment(
  type: 'A' | 'B' = 'A',
): Promise<ApiEnvelope<Record<string, unknown>>> {
  const { data } = await apiClient.post('/stats/experiment', null, { params: { type } })
  if (isApiEnvelope<Record<string, unknown>>(data)) return data
  const maybe = (data as Record<string, unknown>)?.data as unknown
  if (isRecord(maybe)) return { code: 200, msg: 'ok', data: maybe }
  return { code: 200, msg: 'ok', data: (data as Record<string, unknown>) ?? {} }
}

// 额外：拉取大屏聚合（overview + trend 合并）
export async function fetchDashboardBundle(range: string = '7d'): Promise<{ overview: StatsOverview; trend: StatsTrend }> {
  const [ov, tr] = await Promise.all([fetchStatsOverview(range), fetchStatsTrend(range)])
  return { overview: ov.data, trend: tr.data }
}
