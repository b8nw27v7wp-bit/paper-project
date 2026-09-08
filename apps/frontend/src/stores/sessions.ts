import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { listSessions } from '@/api/plans'
import type { PlanSessionItem } from '@/api/plans'

const PINS_KEY = 'workbench:pins'
const NAMES_KEY = 'workbench:names'

export type StoredSessionName = string | { name: string; auto: boolean }

export type SessionGroupKey = '今天' | '本周' | '更早'

export interface SessionGroup {
  key: SessionGroupKey
  items: PlanSessionItem[]
}

export type SessionPill = 'running' | 'pending' | 'completed' | 'failed'

export type KanbanGroupKey = '进行中' | '待审批' | '已完成'

export interface KanbanGroup {
  key: KanbanGroupKey
  items: PlanSessionItem[]
}

/** 左栏 pill 状态判定唯一来源：视图与看板共用，current 缺省时按纯后端 status 判定 */
export function getSessionPill(
  s: PlanSessionItem,
  current?: { traceId: string | null; hasPendingApproval: boolean },
): SessionPill {
  if (current?.traceId && s.trace_id === current.traceId && current.hasPendingApproval) return 'pending'
  const st = s.status as string
  if (st === 'replan') return 'pending'
  if (st === 'completed') return 'completed'
  if (st === 'failed') return 'failed'
  return 'running'
}

function kanbanKeyOf(p: SessionPill): KanbanGroupKey {
  if (p === 'pending') return '待审批'
  if (p === 'completed') return '已完成'
  return '进行中'
}

function readPins(): string[] {
  try {
    const raw = localStorage.getItem(PINS_KEY)
    if (!raw) return []
    const v: unknown = JSON.parse(raw)
    if (!Array.isArray(v)) return []
    return v.filter((x): x is string => typeof x === 'string' && x.length > 0).slice(0, 500)
  } catch { return [] }
}

function readNames(): Record<string, StoredSessionName> {
  try {
    const raw = localStorage.getItem(NAMES_KEY)
    if (!raw) return {}
    const v: unknown = JSON.parse(raw)
    if (!v || typeof v !== 'object' || Array.isArray(v)) return {}
    const out: Record<string, StoredSessionName> = {}
    for (const [k, val] of Object.entries(v as Record<string, unknown>)) {
      if (typeof val === 'string' && val.trim()) {
        out[k] = val.trim().slice(0, 60)
        continue
      }
      if (val && typeof val === 'object' && !Array.isArray(val)) {
        const rec = val as Record<string, unknown>
        if (typeof rec.name === 'string' && rec.name.trim()) {
          out[k] = { name: rec.name.trim().slice(0, 60), auto: rec.auto === true }
        }
      }
    }
    return out
  } catch { return {} }
}

function normalizeNameEntry(v: StoredSessionName | undefined): { name: string; auto: boolean } {
  if (typeof v === 'string') return { name: v, auto: false }
  if (v && typeof v === 'object' && typeof v.name === 'string') {
    return { name: v.name, auto: v.auto === true }
  }
  return { name: '', auto: false }
}

function sessionTimeMs(s: PlanSessionItem): number {
  const v = s.last_event_at || s.started_at
  if (!v) return 0
  const t = new Date(v).getTime()
  return Number.isNaN(t) ? 0 : t
}

function bucketOf(s: PlanSessionItem, now = Date.now()): SessionGroupKey {
  const t = sessionTimeMs(s)
  if (!t) return '更早'
  const d = new Date(t)
  const cur = new Date(now)
  const sameDay = d.getFullYear() === cur.getFullYear() && d.getMonth() === cur.getMonth() && d.getDate() === cur.getDate()
  if (sameDay) return '今天'
  if (now - t < 7 * 86400000) return '本周'
  return '更早'
}

export const useSessionsStore = defineStore('sessions', () => {
  const items = ref<PlanSessionItem[]>([])
  const total = ref(0)
  const page = ref(1)
  const size = ref(20)
  const loading = ref(false)
  const hasMore = computed(() => items.value.length < total.value)

  const pins = ref<string[]>(readPins())
  const names = ref<Record<string, StoredSessionName>>(readNames())

  function persistPins() {
    try { localStorage.setItem(PINS_KEY, JSON.stringify(pins.value)) } catch {}
  }

  function persistNames() {
    try { localStorage.setItem(NAMES_KEY, JSON.stringify(names.value)) } catch {}
  }

  function getPins(): string[] {
    return [...pins.value]
  }

  function isPinned(traceId: string): boolean {
    return pins.value.includes(traceId)
  }

  function togglePin(traceId: string): string[] {
    if (!traceId) return getPins()
    const i = pins.value.indexOf(traceId)
    if (i >= 0) pins.value.splice(i, 1)
    else pins.value.unshift(traceId)
    persistPins()
    return getPins()
  }

  function getName(traceId: string): string {
    return normalizeNameEntry(names.value[traceId]).name
  }

  function getManualName(traceId: string): string {
    const e = normalizeNameEntry(names.value[traceId])
    return e.auto ? '' : e.name
  }

  function isAutoName(traceId: string): boolean {
    const e = normalizeNameEntry(names.value[traceId])
    return Boolean(e.name) && e.auto
  }

  function displayName(traceId: string, fallback: string): string {
    // 优先手动名：手动名非空直接返回，否则自动名，最后回退目标标题
    const manual = getManualName(traceId)
    if (manual) return manual
    const n = getName(traceId)
    return n || fallback || traceId.slice(0, 8)
  }

  function setName(traceId: string, name: string, auto = false): void {
    if (!traceId) return
    const v = name.trim().slice(0, 60)
    if (!v) delete names.value[traceId]
    else if (auto) names.value[traceId] = { name: v, auto: true }
    else names.value[traceId] = v
    persistNames()
  }

  function removeTrace(traceId: string): void {
    if (!traceId) return
    pins.value = pins.value.filter((t) => t !== traceId)
    delete names.value[traceId]
    persistPins()
    persistNames()
    // 仅清本地展示，不删后端数据
    items.value = items.value.filter((s) => s.trace_id !== traceId)
    total.value = Math.max(0, total.value - 1)
  }

  function groupSessions(query?: string): SessionGroup[] {
    const q = (query ?? '').trim().toLowerCase()
    let list = [...items.value]
    if (q) {
      list = list.filter((s) => {
        const title = (getName(s.trace_id) || s.goal_title || '').toLowerCase()
        return title.includes(q) || s.trace_id.toLowerCase().includes(q)
      })
    }
    const pinSet = new Set(pins.value)
    list.sort((a, b) => {
      const pa = pinSet.has(a.trace_id) ? 0 : 1
      const pb = pinSet.has(b.trace_id) ? 0 : 1
      if (pa !== pb) return pa - pb
      return sessionTimeMs(b) - sessionTimeMs(a)
    })
    const buckets: Record<SessionGroupKey, PlanSessionItem[]> = { '今天': [], '本周': [], '更早': [] }
    const now = Date.now()
    for (const s of list) buckets[bucketOf(s, now)].push(s)
    const out: SessionGroup[] = []
    for (const key of ['今天', '本周', '更早'] as SessionGroupKey[]) {
      if (buckets[key].length) out.push({ key, items: buckets[key] })
    }
    return out
  }

  function kanbanGroups(query?: string, resolveState?: (s: PlanSessionItem) => SessionPill): KanbanGroup[] {
    const q = (query ?? '').trim().toLowerCase()
    let list = [...items.value]
    if (q) {
      list = list.filter((s) => {
        const title = (getName(s.trace_id) || s.goal_title || '').toLowerCase()
        return title.includes(q) || s.trace_id.toLowerCase().includes(q)
      })
    }
    const pinSet = new Set(pins.value)
    list.sort((a, b) => {
      const pa = pinSet.has(a.trace_id) ? 0 : 1
      const pb = pinSet.has(b.trace_id) ? 0 : 1
      if (pa !== pb) return pa - pb
      return sessionTimeMs(b) - sessionTimeMs(a)
    })
    const buckets: Record<KanbanGroupKey, PlanSessionItem[]> = { '进行中': [], '待审批': [], '已完成': [] }
    const resolve = resolveState ?? ((s) => getSessionPill(s))
    for (const s of list) buckets[kanbanKeyOf(resolve(s))].push(s)
    return (['进行中', '待审批', '已完成'] as KanbanGroupKey[]).map((key) => ({ key, items: buckets[key] }))
  }

  async function fetchPage(p = 1) {
    if (loading.value) return
    loading.value = true
    try {
      const res = await listSessions(p, size.value)
      const data = res.data
      if (p <= 1) items.value = data.items
      else {
        const known = new Set(items.value.map((s) => s.trace_id))
        items.value = [...items.value, ...data.items.filter((s) => !known.has(s.trace_id))]
      }
      total.value = data.total
      page.value = data.page
    } catch {}
    finally { loading.value = false }
  }

  async function loadMore() {
    if (!hasMore.value) return
    await fetchPage(page.value + 1)
  }

  async function refresh() {
    await fetchPage(1)
  }

  function reset() {
    items.value = []
    total.value = 0
    page.value = 1
  }

  return { items, total, page, size, loading, hasMore, pins, names, getPins, isPinned, togglePin, getName, getManualName, isAutoName, displayName, setName, removeTrace, groupSessions, kanbanGroups, fetchPage, loadMore, refresh, reset }
})
