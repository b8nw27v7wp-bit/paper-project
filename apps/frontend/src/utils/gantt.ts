// Gantt 纯函数：粒度 ticks + 真连线（graph.edges），便于单测
// 不改后端契约，边字段兼容 type/relation 双写（后端 graph.py:45-50 同时返回两者）
import type { TaskItem, GraphEdge } from '@/types'

export type GanttZoom = 'day' | 'week' | string

export interface GanttTick {
  key: string
  label: string
}

export interface GanttDepLine {
  x1: number
  x2: number
  from: string
  to: string
  relation: string
}

export function buildGanttTicks(min: Date, max: Date, zoom: GanttZoom): GanttTick[] {
  const z = zoom === 'week' ? 'week' : 'day'
  if (z === 'week') {
    const days = Math.max(7, Math.ceil((max.getTime() - min.getTime()) / 86400000) + 1)
    const weeks = Math.max(1, Math.ceil(days / 7))
    const n = Math.min(weeks, 8)
    return Array.from({ length: n }, (_, i) => {
      const d = new Date(min)
      d.setDate(d.getDate() + i * 7)
      return { key: d.toISOString().slice(0, 10) + `-w${i}`, label: d.toISOString().slice(5, 10) }
    })
  }
  const days = Math.max(7, Math.ceil((max.getTime() - min.getTime()) / 86400000) + 1)
  return Array.from({ length: Math.min(days, 14) }, (_, i) => {
    const d = new Date(min)
    d.setDate(d.getDate() + i)
    return { key: d.toISOString().slice(0, 10), label: d.toISOString().slice(5, 10) }
  })
}

function edgeRelation(e: GraphEdge): string {
  const r = (e.relation ?? e.type ?? 'PREREQ') as string
  return r || 'PREREQ'
}

// 真连线：仅当边两端都能映射到当前 tasks 才连线，杜绝按时间排序假连
// 映射优先级：String(id) 精确 > title 精确 > title 包含（双向），无匹配即丢弃该边
export function buildDepLines(
  tasks: TaskItem[],
  edges: GraphEdge[],
  range: { min: Date; max: Date },
  svgW: number,
): GanttDepLine[] {
  if (!tasks.length || !edges.length || !svgW) return []
  const totalMs = Math.max(1, range.max.getTime() - range.min.getTime())
  const byId = new Map<string, TaskItem>()
  const byTitle = new Map<string, TaskItem>()
  for (const t of tasks) {
    byId.set(String(t.id), t)
    if (t.title && !byTitle.has(t.title)) byTitle.set(t.title, t)
  }
  function resolve(name: string): TaskItem | undefined {
    const k = String(name ?? '')
    if (!k) return undefined
    const direct = byId.get(k) ?? byTitle.get(k)
    if (direct) return direct
    for (const t of tasks) {
      if (t.title && (t.title.includes(k) || k.includes(t.title))) return t
    }
    return undefined
  }
  const out: GanttDepLine[] = []
  for (const e of edges) {
    const a = resolve(e.from)
    const b = resolve(e.to)
    if (!a || !b || a.id === b.id) continue
    const ax = ((new Date(a.planned_end).getTime() - range.min.getTime()) / totalMs) * svgW
    const bx = ((new Date(b.planned_start).getTime() - range.min.getTime()) / totalMs) * svgW
    if (!Number.isFinite(ax) || !Number.isFinite(bx)) continue
    out.push({ x1: ax, x2: bx, from: e.from, to: e.to, relation: edgeRelation(e) })
  }
  return out
}
