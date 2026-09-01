import { apiClient, isApiEnvelope } from './client'
import type { ApiEnvelope } from '@/types'

export interface LlmModel { id: string; name?: string; provider?: string; contextWindow?: number }

export async function fetchLlmModels(): Promise<ApiEnvelope<LlmModel[]>> {
  const { data } = await apiClient.get('/llm/models')
  if (!isApiEnvelope<LlmModel[]>(data)) {
    // 兼容直接数组
    if (Array.isArray((data as Record<string, unknown>)?.data)) {
      return { code: 200, msg: 'ok', data: (data as Record<string, unknown>).data as LlmModel[] } as ApiEnvelope<LlmModel[]>
    }
    throw new TypeError('llm models envelope invalid')
  }
  return data
}
