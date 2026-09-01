import { apiClient, rootClient, isApiEnvelope, isRecord } from './client'
import type { ApiEnvelope, HealthStatus, ServiceHealth } from '@/types'

// 守卫：HealthStatus
function isHealthStatus(v: unknown): v is HealthStatus {
  if (!isRecord(v)) return false
  const s = (v as Record<string, unknown>).status
  return s === 'ok' || s === 'degraded' || s === 'unknown'
}

function ensureHealth(data: unknown): HealthStatus {
  if (isApiEnvelope<HealthStatus>(data) && isHealthStatus(data.data)) return data.data
  const maybe = (data as Record<string, unknown>)?.data as unknown
  if (isHealthStatus(maybe)) return maybe as HealthStatus
  if (isHealthStatus(data)) return data as HealthStatus
  // 兜底
  return { status: 'unknown' as ServiceHealth, version: 'unknown' }
}

export async function fetchRootHealth(): Promise<ApiEnvelope<HealthStatus> & { raw: unknown }> {
  const { data } = await rootClient.get('/health')
  const health = ensureHealth(data)
  if (isApiEnvelope<HealthStatus>(data)) return { ...data, data: health, raw: data } as ApiEnvelope<HealthStatus> & { raw: unknown }
  return { code: 200, msg: 'ok', data: health, raw: data } as ApiEnvelope<HealthStatus> & { raw: unknown }
}

export async function fetchHealth(): Promise<ApiEnvelope<HealthStatus>> {
  const { data } = await apiClient.get('/health')
  const health = ensureHealth(data)
  if (isApiEnvelope<HealthStatus>(data)) return { ...data, data: health } as ApiEnvelope<HealthStatus>
  if (isRecord(data) && 'data' in data) {
    const inner = (data as Record<string, unknown>).data
    if (isHealthStatus(inner)) return { code: 200, msg: 'ok', data: inner as HealthStatus }
  }
  if (isHealthStatus(data)) return { code: 200, msg: 'ok', data: data as HealthStatus }
  return { code: 200, msg: 'ok', data: health }
}

export async function fetchV1Detailed(): Promise<ApiEnvelope<{ status: ServiceHealth; checks: Record<string, ServiceHealth> }>> {
  const { data } = await apiClient.get('/health/detailed')
  if (isApiEnvelope<{ status: ServiceHealth; checks: Record<string, ServiceHealth> }>(data)) return data
  const maybe = (data as Record<string, unknown>)?.data as unknown
  if (
    maybe &&
    typeof maybe === 'object' &&
    'status' in (maybe as Record<string, unknown>) &&
    'checks' in (maybe as Record<string, unknown>)
  ) {
    return { code: 200, msg: 'ok', data: maybe as { status: ServiceHealth; checks: Record<string, ServiceHealth> } }
  }
  return { code: 200, msg: 'ok', data: { status: 'unknown', checks: {} } }
}

// 便捷：判断是否健康
export function isHealthy(h: HealthStatus): boolean {
  return h.status === 'ok'
}

// 聚合展示：services 全绿才 ok
export function deriveOverall(services?: Record<string, ServiceHealth>): ServiceHealth {
  if (!services) return 'unknown'
  const vals = Object.values(services)
  if (vals.every((v) => v === 'ok' || v === 'unknown')) return 'ok'
  if (vals.some((v) => v === 'degraded')) return 'degraded'
  return 'unknown'
}
