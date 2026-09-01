import { apiClient, isApiEnvelope, isRecord } from './client'
import type { ApiEnvelope, MCPServer, MCPTool } from '@/types'

export type MCPServerDTO = MCPServer
export type MCPToolDTO = MCPTool

function isServerArray(v: unknown): v is MCPServer[] {
  return Array.isArray(v) && v.every((x) => isRecord(x) && typeof (x as Record<string, unknown>).name === 'string')
}

function isToolArray(v: unknown): v is MCPTool[] {
  return Array.isArray(v) && v.every((x) => isRecord(x) && typeof (x as Record<string, unknown>).full_name === 'string')
}

function ensureServers(v: unknown): MCPServer[] {
  if (Array.isArray(v) && isServerArray(v)) return v
  const maybe = (v as Record<string, unknown>)?.data as unknown
  if (Array.isArray(maybe) && isServerArray(maybe)) return maybe
  if (isRecord(v) && Array.isArray((v as Record<string, unknown>).servers) && isServerArray((v as Record<string, unknown>).servers as unknown)) {
    return (v as Record<string, unknown>).servers as MCPServer[]
  }
  return []
}

function ensureTools(v: unknown): MCPTool[] {
  if (Array.isArray(v) && isToolArray(v)) return v
  const maybe = (v as Record<string, unknown>)?.data as unknown
  if (Array.isArray(maybe) && isToolArray(maybe)) return maybe
  return []
}

export async function listMCPServers(): Promise<ApiEnvelope<MCPServer[]>> {
  const { data } = await apiClient.get('/mcp/servers')
  if (isApiEnvelope<MCPServer[]>(data)) {
    const arr = ensureServers(data.data)
    return { ...data, data: arr }
  }
  const arr = ensureServers(data)
  return { code: 200, msg: 'ok', data: arr }
}

export async function listMCPTools(): Promise<ApiEnvelope<MCPTool[]>> {
  const { data } = await apiClient.get('/mcp/tools')
  if (isApiEnvelope<MCPTool[]>(data)) {
    const arr = ensureTools(data.data)
    return { ...data, data: arr }
  }
  const arr = ensureTools(data)
  return { code: 200, msg: 'ok', data: arr }
}

export async function callMCPTool(
  server: string,
  tool: string,
  args: Record<string, unknown>,
): Promise<ApiEnvelope<Record<string, unknown>>> {
  const { data } = await apiClient.post('/mcp/call', { server, tool, args })
  if (isApiEnvelope<Record<string, unknown>>(data)) return data
  const maybe = (data as Record<string, unknown>)?.data as unknown
  if (isRecord(maybe)) return { code: 200, msg: 'ok', data: maybe as Record<string, unknown> }
  return { code: 200, msg: 'ok', data: (data as Record<string, unknown>) ?? {} }
}

// 兼容文档中的命名
export const fetchMCPServers = listMCPServers

// 守卫：供 UI 对接使用
export function isMCPServer(v: unknown): v is MCPServer {
  if (!isRecord(v)) return false
  return typeof (v as Record<string, unknown>).name === 'string' && typeof (v as Record<string, unknown>).status === 'string'
}
