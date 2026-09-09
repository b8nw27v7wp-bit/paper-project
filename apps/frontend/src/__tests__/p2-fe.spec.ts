import { describe, it, expect, vi } from 'vitest'

// P2-FE 回归：Gantt 粒度/真连线 · Calendar range 聚合 · HealthCheck 回退 · Inspector/MCP
// 风格对齐 waveb.spec.ts：mock apiClient（保留纯函数真实逻辑），不依赖后端/PG
vi.mock('@/api/client', () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn(), put: vi.fn() },
  rootClient: { get: vi.fn() },
  isApiEnvelope: (v: unknown) => {
    const o = v as Record<string, unknown>
    return !!o && typeof o === 'object' && typeof o.code === 'number' && typeof o.msg === 'string' && 'data' in o
  },
  isRecord: (v: unknown) => typeof v === 'object' && v !== null && !Array.isArray(v),
  extractErrorMessage: (e: unknown) => (e instanceof Error ? e.message : String(e)),
  isElectronEnv: () => false,
}))

import { buildGanttTicks, buildDepLines } from '@/utils/gantt'
import { buildHeat, getCalendarRangeDays } from '@/utils/calendarHeat'
import { FALLBACK_API_ROUTES, parseOpenapiPaths, resolveMockLabel } from '@/utils/openapi'
import { filterInspectorLogs, hasToolCallsOption, buildMcpSubtitle } from '@/utils/inspector'
import type { TaskItem, GraphEdge, PlanLogItem } from '@/types'

function task(id: number, title: string, s: string, e: string, status: TaskItem['status'] = 'todo'): TaskItem {
  return { id, goal_id: 1, title, planned_start: s, planned_end: e, priority: 3, status, created_at: s }
}

describe('P2-FE Gantt 粒度切换', () => {
  it('day 粒度按天 ticks（7天窗口=7个）', () => {
    const ticks = buildGanttTicks(new Date('2026-09-01T00:00:00Z'), new Date('2026-09-07T00:00:00Z'), 'day')
    expect(ticks.length).toBe(7)
    expect(ticks[0]?.label).toBe('09-01')
  })

  it('week 粒度按周聚合（14天=2个，与 day 数量不同）', () => {
    const min = new Date('2026-09-01T00:00:00Z')
    const max = new Date('2026-09-14T00:00:00Z')
    const day = buildGanttTicks(min, max, 'day')
    const week = buildGanttTicks(min, max, 'week')
    expect(week.length).toBe(2)
    expect(week.length).toBeLessThan(day.length)
  })
})

describe('P2-FE Gantt 真连线（graph.edges）', () => {
  it('仅边两端命中 tasks 才连线，杜绝时间排序假连', () => {
    const tasks = [
      task(1, '背单词', '2026-09-01T09:00:00Z', '2026-09-01T10:00:00Z'),
      task(2, '学语法', '2026-09-02T09:00:00Z', '2026-09-02T10:00:00Z'),
      task(3, '做阅读', '2026-09-03T09:00:00Z', '2026-09-03T10:00:00Z'),
    ]
    const range = { min: new Date('2026-09-01T00:00:00Z'), max: new Date('2026-09-04T00:00:00Z') }
    const edges: GraphEdge[] = [{ from: '背单词', to: '学语法', type: 'PREREQUISITE', relation: 'PREREQUISITE' }]
    const lines = buildDepLines(tasks, edges, range, 720)
    // 真边只有 1 条；若按旧假连（时间排序相邻）应为 2 条
    expect(lines.length).toBe(1)
    expect(lines[0]?.relation).toBe('PREREQUISITE')
    expect(lines[0]?.from).toBe('背单词')
  })

  it('type/relation 双兼容 + 无匹配回空（不造假线）', () => {
    const tasks = [task(1, 'A', '2026-09-01T09:00:00Z', '2026-09-01T10:00:00Z')]
    const range = { min: new Date('2026-09-01T00:00:00Z'), max: new Date('2026-09-02T00:00:00Z') }
    expect(buildDepLines(tasks, [{ from: 'X', to: 'Y', type: 'next' }], range, 720)).toEqual([])
    expect(buildDepLines(tasks, [], range, 720)).toEqual([])
  })
})

describe('P2-FE Calendar range 聚合', () => {
  it('week=7 / month=30 可视 range 天数', () => {
    expect(getCalendarRangeDays('timeGridWeek')).toBe(7)
    expect(getCalendarRangeDays('dayGridMonth')).toBe(30)
  })

  it('month 聚合保留 30 天、week 截断 7 天（替代 slice(0,7) 写死）', () => {
    const tasks: TaskItem[] = Array.from({ length: 10 }, (_, i) => {
      const d = `2026-09-${String(i + 1).padStart(2, '0')}`
      return task(i + 1, `任务${i + 1}`, `${d}T09:00:00Z`, `${d}T10:00:00Z`)
    })
    expect(buildHeat(tasks, 7).length).toBe(7)
    expect(buildHeat(tasks, 30).length).toBe(10)
    expect(buildHeat(tasks, 30)[0]?.date).toBe('2026-09-01')
  })
})

describe('P2-FE HealthCheck 回退', () => {
  it('openapi 非法输入回空，调用方回退硬编码表', () => {
    expect(parseOpenapiPaths(null)).toEqual([])
    expect(parseOpenapiPaths({})).toEqual([])
    expect(FALLBACK_API_ROUTES.length).toBeGreaterThan(0)
  })

  it('openapi paths 动态解析 method/path/desc', () => {
    const rows = parseOpenapiPaths({
      paths: {
        '/api/v1/tasks/calendar': { get: { summary: '日历聚合' } },
        '/api/v1/goals': { post: { summary: '新建目标' } },
      },
    })
    expect(rows.map((r) => `${r.method} ${r.path}`)).toContain('GET /api/v1/tasks/calendar')
    expect(rows.find((r) => r.path === '/api/v1/tasks/calendar')?.desc).toBe('日历聚合')
  })

  it('mock 标识按 capabilities.has_key 真实显示', () => {
    expect(resolveMockLabel('python -m app', true)).toBe('python -m app')
    expect(resolveMockLabel('', true)).toBe('live')
    expect(resolveMockLabel('', false)).toBe('mock')
    expect(resolveMockLabel(null, null)).toBe('mock')
  })
})

describe('P2-FE Inspector/MCP', () => {
  it('关键词 complements agent 过滤', () => {
    const logs: PlanLogItem[] = [
      { trace_id: 't', agent_name: 'planner', input: { q: '背单词' }, created_at: '' },
      { trace_id: 't', agent_name: 'critic', input: { q: '语法' }, created_at: '' },
    ]
    expect(filterInspectorLogs(logs, { agent: 'planner', keyword: '' }).length).toBe(1)
    expect(filterInspectorLogs(logs, { keyword: '语法' }).map((l) => l.agent_name)).toEqual(['critic'])
  })

  it('tool_calls 缺失隐藏该选项、有则可滤', () => {
    const empty: PlanLogItem[] = [{ trace_id: 't', agent_name: 'planner', created_at: '' }]
    expect(hasToolCallsOption(empty)).toBe(false)
    const logs: PlanLogItem[] = [
      { trace_id: 't', agent_name: 'planner', tool_calls: [{ tool: 'rag' }], created_at: '' },
      { trace_id: 't', agent_name: 'critic', created_at: '' },
    ]
    expect(hasToolCallsOption(logs)).toBe(true)
    expect(filterInspectorLogs(logs, { onlyWithTools: true }).length).toBe(1)
  })

  it('MCP 副标题动态计数 + 真实连接态', () => {
    expect(buildMcpSubtitle({ total: 0, running: 0, loading: true, hasError: false })).toContain('加载中')
    expect(buildMcpSubtitle({ total: 3, running: 3, loading: false, hasError: false })).toContain('已连接')
    expect(buildMcpSubtitle({ total: 3, running: 1, loading: false, hasError: false })).toContain('1/3')
  })
})
