import { apiClient, isApiEnvelope } from './client'
import type { ApiEnvelope } from '@/types'

export interface MemoryChunk { id: number; content: string; score?: number; type: string; source_id?: number | null; created_at?: string | null }
export interface MemorySearchParams { q: string; top_k?: number; type?: string }

export async function searchMemory(params: MemorySearchParams): Promise<ApiEnvelope<MemoryChunk[]>> {
  const top_k = params.top_k !== undefined ? Math.min(20, Math.max(1, Math.floor(params.top_k))) : 5
  const { data } = await apiClient.get('/memory/search', { params: { q: params.q, top_k, type: params.type } })
  // 后端返回 {code,msg,data: MemoryChunk[]} 或 {data: {items}} 兼容
  if (isApiEnvelope<MemoryChunk[]>(data)) return data
  // 兼容 data 为直接数组
  if (Array.isArray((data as Record<string, unknown>)?.data)) {
    return { code: 200, msg: 'ok', data: (data as Record<string, unknown>).data as MemoryChunk[] } as ApiEnvelope<MemoryChunk[]>
  }
  throw new TypeError('memory/search envelope invalid')
}

export async function createMemory(payload: { content: string; type?: string }): Promise<ApiEnvelope<MemoryChunk>> {
  const { data } = await apiClient.post('/memory', payload)
  if (!isApiEnvelope<MemoryChunk>(data)) throw new TypeError('memory create envelope invalid')
  return data
}
