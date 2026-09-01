import { apiClient, isApiEnvelope } from './client'
import type { ApiEnvelope, Paginated } from '@/types'

export interface RagChunk { id: number; content: string; score?: number; type?: string; subject?: string | null; created_at?: string | null }

export async function ingestRag(file: File, subject?: string): Promise<ApiEnvelope<{ chunks: number; knowledges: number; triples: unknown[] }>> {
  const fd = new FormData()
  fd.append('file', file)
  if (subject) fd.append('subject', subject)
  const { data } = await apiClient.post('/rag/ingest', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
  if (!isApiEnvelope<{ chunks: number; knowledges: number; triples: unknown[] }>(data)) throw new TypeError('rag ingest envelope invalid')
  return data
}

export async function searchRag(params: { q: string; top_k?: number; subject?: string }): Promise<ApiEnvelope<{ chunks: RagChunk[]; graph: unknown[] }>> {
  if (params.top_k !== undefined) params.top_k = Math.min(20, Math.max(1, Math.floor(params.top_k)))
  const { data } = await apiClient.get('/rag/search', { params })
  if (!isApiEnvelope<{ chunks: RagChunk[]; graph: unknown[] }>(data)) throw new TypeError('rag search envelope invalid')
  return data
}

export async function listChunks(params: { subject?: string; page?: number; size?: number } = {}): Promise<ApiEnvelope<Paginated<RagChunk>>> {
  if (params.size !== undefined) params.size = Math.min(100, Math.max(1, Math.floor(params.size)))
  if (params.page !== undefined) params.page = Math.max(1, Math.floor(params.page))
  const { data } = await apiClient.get('/rag/chunks', { params })
  if (!isApiEnvelope<Paginated<RagChunk>>(data)) throw new TypeError('rag chunks envelope invalid')
  return data
}
