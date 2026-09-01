import { apiClient, isApiEnvelope } from './client'
import type { ApiEnvelope } from '@/types'

export interface ExpResult { experiment: string; blinded: boolean; delta?: number; improvement?: string; samples?: unknown[]; [k: string]: unknown }

export async function fetchMemoryAblation(query = '学习', top_k = 5): Promise<ApiEnvelope<ExpResult>> {
  const { data } = await apiClient.get('/experiments/memory-ablation', { params: { query, top_k } })
  if (!isApiEnvelope<ExpResult>(data)) throw new TypeError('experiments memory-ablation envelope invalid')
  return data
}
export async function fetchAgentComparison(): Promise<ApiEnvelope<ExpResult>> {
  const { data } = await apiClient.get('/experiments/agent-comparison')
  if (!isApiEnvelope<ExpResult>(data)) throw new TypeError('experiments agent-comparison envelope invalid')
  return data
}
export async function fetchGraphEvidence(query = '链表', top_k = 5): Promise<ApiEnvelope<ExpResult>> {
  const { data } = await apiClient.get('/experiments/graph-evidence', { params: { query, top_k } })
  if (!isApiEnvelope<ExpResult>(data)) throw new TypeError('experiments graph-evidence envelope invalid')
  return data
}
export async function fetchSuite(): Promise<ApiEnvelope<Record<string, ExpResult>>> {
  const { data } = await apiClient.get('/experiments/suite')
  if (!isApiEnvelope<Record<string, ExpResult>>(data)) throw new TypeError('experiments suite envelope invalid')
  return data
}
