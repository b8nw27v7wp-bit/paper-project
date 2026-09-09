// Calendar 热力纯函数：按可视 range 聚合，便于单测
// viewMode: timeGridWeek=7 / dayGridMonth=30 / timeGridDay=1，兜底 7
import type { TaskItem } from '@/types'

export interface HeatItem {
  date: string
  hours: number
  count: number
  rate: number
  color: string
}

export function getCalendarRangeDays(viewMode: string): number {
  if (viewMode === 'dayGridMonth') return 30
  if (viewMode === 'timeGridWeek') return 7
  if (viewMode === 'timeGridDay') return 1
  return 7
}

function heatColor(hours: number): string {
  const intensity = Math.min(1, hours / 8)
  return `rgba(29,29,31,${(0.06 + intensity * 0.12).toFixed(3)})`
}

// 本地聚合：按 planned_start 日期分组，排序后按 rangeDays 截断（替代 slice(0,7) 写死）
export function buildHeat(tasks: TaskItem[], rangeDays: number): HeatItem[] {
  const n = Math.max(1, Math.floor(rangeDays) || 7)
  const map: Record<string, { hours: number; count: number; done: number }> = {}
  for (const t of tasks) {
    const d = String(t.planned_start).slice(0, 10)
    if (!d) continue
    if (!map[d]) map[d] = { hours: 0, count: 0, done: 0 }
    const h = (new Date(t.planned_end).getTime() - new Date(t.planned_start).getTime()) / 3600000
    map[d].hours += Number.isFinite(h) && h > 0 ? h : 0
    map[d].count += 1
    if (t.status === 'done') map[d].done += 1
  }
  return Object.entries(map)
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .slice(0, n)
    .map(([date, v]) => {
      const rate = v.count ? v.done / v.count : 0
      return { date, hours: v.hours, count: v.count, rate, color: heatColor(v.hours) }
    })
}
