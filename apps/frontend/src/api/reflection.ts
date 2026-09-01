import { apiClient, isApiEnvelope } from './client'
import type { ApiEnvelope } from '@/types'

export interface ReflectionReport { user_id: number; week: string; completion_rate: number; delay_rate: number; avg_load: number; analysis: string; next_plan_patch: Record<string, unknown>; created_at?: string }

export async function fetchLatestReflection(): Promise<ApiEnvelope<ReflectionReport>> {
  const { data } = await apiClient.get('/reflection/latest')
  if (!isApiEnvelope<ReflectionReport>(data)) throw new TypeError('reflection latest envelope invalid')
  return data
}

export async function fetchWeekReflection(week: string): Promise<ApiEnvelope<ReflectionReport>> {
  const { data } = await apiClient.get('/reflection/week', { params: { week } })
  if (!isApiEnvelope<ReflectionReport>(data)) throw new TypeError('reflection week envelope invalid')
  return data
}

export async function runReflection(week?: string): Promise<ApiEnvelope<ReflectionReport>> {
  const { data } = await apiClient.post('/reflection/run', null, { params: week ? { week } : {} })
  if (!isApiEnvelope<ReflectionReport>(data)) throw new TypeError('reflection run envelope invalid')
  return data
}
