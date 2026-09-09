// HealthCheck 纯函数：openapi 驱动清单 + mock 标识真实显示，便于单测
// 不改后端契约，/openapi.json 非信封（FastAPI 原生），失败回退硬编码表

export interface ApiRouteRow {
  method: string
  path: string
  desc: string
}

export const FALLBACK_API_ROUTES: ApiRouteRow[] = [
  { method: 'GET', path: '/health', desc: '根探针 (K8s/Docker)' },
  { method: 'GET', path: '/api/v1/health', desc: 'v1 健康 (含 services)' },
  { method: 'GET', path: '/api/v1/mcp/servers', desc: 'MCP 服务列表' },
  { method: 'GET', path: '/api/v1/mcp/tools', desc: 'MCP 工具列表' },
  { method: 'POST', path: '/api/v1/mcp/call', desc: 'MCP 工具调用' },
  { method: 'GET', path: '/docs', desc: 'Swagger' },
  { method: 'GET', path: '/api/v1/plans/stream', desc: 'SSE 含 Last-Event-ID' },
  { method: 'POST', path: '/api/v1/goals', desc: '目标 CRUD' },
]

// 解析 /openapi.json paths -> 清单行；非法/空输入回退空数组（调用方再回退硬编码表）
export function parseOpenapiPaths(doc: unknown): ApiRouteRow[] {
  if (!doc || typeof doc !== 'object') return []
  const paths = (doc as Record<string, unknown>).paths
  if (!paths || typeof paths !== 'object') return []
  const out: ApiRouteRow[] = []
  for (const [p, v] of Object.entries(paths as Record<string, unknown>)) {
    if (!v || typeof v !== 'object') continue
    for (const [m, op] of Object.entries(v as Record<string, unknown>)) {
      const method = m.toUpperCase()
      if (!['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'].includes(method)) continue
      let desc = ''
      try {
        const rec = op as Record<string, unknown>
        const s = rec.summary
        const d = rec.description
        if (typeof s === 'string' && s.trim()) desc = s.trim().slice(0, 80)
        else if (typeof d === 'string' && d.trim()) desc = d.trim().slice(0, 80)
      } catch {}
      out.push({ method, path: String(p), desc })
    }
  }
  out.sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : a.method < b.method ? -1 : 1))
  return out
}

// mock 标识：有真实 command 即显示 command；缺失时按 capabilities.has_key 真实显示
export function resolveMockLabel(command: unknown, hasKey: boolean | null | undefined): string {
  const c = typeof command === 'string' ? command.trim() : ''
  if (c) return c
  return hasKey === true ? 'live' : 'mock'
}
