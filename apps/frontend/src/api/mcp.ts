import { apiClient } from './client'

export interface MCPServer {
  name: string
  status: string
  command?: string
  tools?: string[]
  running?: boolean
}

export interface MCPTool {
  server: string
  tool: string
  full_name: string
  description?: string
}

export async function listMCPServers() {
  const { data } = await apiClient.get('/mcp/servers')
  return data
}

export async function listMCPTools() {
  const { data } = await apiClient.get('/mcp/tools')
  return data
}

export async function callMCPTool(server: string, tool: string, args: any) {
  const { data } = await apiClient.post('/mcp/call', { server, tool, args })
  return data
}

// 兼容文档中的命名
export const fetchMCPServers = listMCPServers
