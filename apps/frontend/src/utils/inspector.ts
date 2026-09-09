// Inspector 过滤纯函数：agent 下拉 complements 关键词 + tool_calls 存在性，便于单测
// 数据结构：logs[].tool_calls（缺失隐藏该选项由调用方 v-if hasToolCallsLogs）
import type { PlanLogItem } from '@/types'

export interface InspectorFilter {
  agent?: string
  keyword?: string
  onlyWithTools?: boolean
}

export function hasToolCallsOption(logs: PlanLogItem[]): boolean {
  return logs.some((l) => Array.isArray(l.tool_calls) && l.tool_calls.length > 0)
}

export function filterInspectorLogs(logs: PlanLogItem[], f: InspectorFilter): PlanLogItem[] {
  const agent = (f.agent ?? '').trim()
  const kw = (f.keyword ?? '').trim().toLowerCase()
  const onlyTools = f.onlyWithTools === true
  return logs.filter((l) => {
    if (agent && l.agent_name !== agent) return false
    if (onlyTools && !(Array.isArray(l.tool_calls) && l.tool_calls.length > 0)) return false
    if (kw) {
      const hay = [l.agent_name ?? '', safeJson(l.input), safeJson(l.output)].join(' ').toLowerCase()
      if (!hay.includes(kw)) return false
    }
    return true
  })
}

function safeJson(v: unknown): string {
  try {
    const s = JSON.stringify(v ?? '')
    return typeof s === 'string' ? s : String(v ?? '')
  } catch {
    return String(v ?? '')
  }
}

// MCP 副标题：动态 serverOpts 计数 + 真实连接态（替代“3 servers·mock联调”写死）
export function buildMcpSubtitle(opts: { total: number; running: number; loading: boolean; hasError: boolean }): string {
  const { total, running, loading, hasError } = opts
  let state = '未连接'
  if (hasError && total === 0) state = '离线'
  else if (total === 0) state = loading ? '加载中' : '未连接'
  else if (running === total) state = '已连接'
  else state = `${running}/${total} 运行中`
  return `Model Context Protocol · ${total} servers · ${state}`
}
