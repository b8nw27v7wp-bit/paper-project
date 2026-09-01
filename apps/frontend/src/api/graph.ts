import { apiClient, isApiEnvelope, isRecord } from './client'
import type { ApiEnvelope, GraphData, GraphNode, GraphEdge } from '@/types'

export type GraphNodeDTO = GraphNode
export type GraphEdgeDTO = GraphEdge
export type GraphDTO = GraphData

function isGraphData(v: unknown): v is GraphData {
  if (!isRecord(v)) return false
  const r = v as Record<string, unknown>
  return Array.isArray(r.nodes) && Array.isArray(r.edges)
}

function ensureGraph(v: unknown): GraphData {
  if (isGraphData(v)) return v as GraphData
  const maybe = (v as Record<string, unknown>)?.data as unknown
  if (isGraphData(maybe)) return maybe as GraphData
  return { nodes: [], edges: [] }
}

export async function fetchGraph(params: { subject?: string; keyword?: string; limit?: number } = {}): Promise<ApiEnvelope<GraphData>> {
  if (params.limit !== undefined) params.limit = Math.min(200, Math.max(1, Math.floor(params.limit)))
  const { data } = await apiClient.get('/graph', { params })
  if (isApiEnvelope<GraphData>(data)) {
    const g = ensureGraph(data.data)
    return { ...data, data: g }
  }
  const maybe = (data as Record<string, unknown>)?.data as unknown
  if (maybe) {
    const g = ensureGraph(maybe)
    return { code: 200, msg: 'ok', data: g }
  }
  return { code: 200, msg: 'ok', data: ensureGraph(data) }
}

export async function fetchSubgraph(subject: string): Promise<ApiEnvelope<GraphData>> {
  const { data } = await apiClient.get('/graph/subgraph', { params: { subject } })
  if (isApiEnvelope<GraphData>(data)) return { ...data, data: ensureGraph(data.data) }
  const maybe = (data as Record<string, unknown>)?.data as unknown
  if (isGraphData(maybe)) return { code: 200, msg: 'ok', data: maybe as GraphData }
  return { code: 200, msg: 'ok', data: ensureGraph(data) }
}

export async function searchPrereqs(keyword: string): Promise<ApiEnvelope<GraphData>> {
  const { data } = await apiClient.get('/graph', { params: { keyword } })
  if (isApiEnvelope<GraphData>(data)) return { ...data, data: ensureGraph(data.data) }
  const maybe = (data as Record<string, unknown>)?.data as unknown
  if (isGraphData(maybe)) return { code: 200, msg: 'ok', data: maybe as GraphData }
  return { code: 200, msg: 'ok', data: ensureGraph(data) }
}

// 便捷：按学科聚类统计，供热力图
export function groupBySubject(nodes: GraphNode[]): Record<string, number> {
  const map: Record<string, number> = {}
  for (const n of nodes) {
    const k = (n.subject as string) || (n.label as string) || '通用'
    map[k] = (map[k] ?? 0) + 1
  }
  return map
}
