import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { listSessions } from '@/api/plans'
import { apiClient } from '@/api/client'
import { getPins as readPinsSetting, setPins as writePinsSetting, getNames as readNamesSetting, setNames as writeNamesSetting } from '@/stores/settings'
import type { PlanSessionItem } from '@/api/plans'

const EPHEMERAL_KEY = 'workbench:ephemeral'

export type StoredSessionName = string | { name: string; auto: boolean }

export type SessionGroupKey = '今天' | '本周' | '更早'

export interface SessionGroup {
  key: SessionGroupKey
  items: PlanSessionItem[]
}

export type SessionPill = 'running' | 'pending' | 'completed' | 'failed'

export type KanbanGroupKey = '进行中' | '待审批' | '已完成' | '失败'

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
  if (p === 'failed') return '失败'
  return '进行中'
}

function readPins(): string[] {
  // 收敛到 stores/settings（同键 workbench:pins，行为不变）
  return readPinsSetting()
}

function readNames(): Record<string, StoredSessionName> {
  // 收敛到 stores/settings（同键 workbench:names，行为不变）
  return readNamesSetting()
}

function normalizeNameEntry(v: StoredSessionName | undefined): { name: string; auto: boolean } {
  if (typeof v === 'string') return { name: v, auto: false }
  if (v && typeof v === 'object' && typeof v.name === 'string') {
    return { name: v.name, auto: v.auto === true }
  }
  return { name: '', auto: false }
}

function readEphemeral(): string[] {
  try {
    const raw = localStorage.getItem(EPHEMERAL_KEY)
    if (!raw) return []
    const v: unknown = JSON.parse(raw)
    if (!Array.isArray(v)) return []
    return v.filter((x): x is string => typeof x === 'string' && x.length > 0).slice(0, 500)
  } catch { return [] }
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
  // Wave-B B5：瞬态会话本地映射（create 回执/本地 recentlyCreated，不硬造）
  const ephemeralTraces = ref<string[]>(readEphemeral())

  function persistPins() {
    try { pins.value = writePinsSetting(pins.value) } catch {}
  }

  function persistNames() {
    try { writeNamesSetting(names.value) } catch {}
  }

  function persistEphemeral() {
    try { localStorage.setItem(EPHEMERAL_KEY, JSON.stringify(ephemeralTraces.value)) } catch {}
  }

  function markEphemeral(traceId: string): void {
    if (!traceId) return
    if (!ephemeralTraces.value.includes(traceId)) {
      ephemeralTraces.value.unshift(traceId)
      ephemeralTraces.value = ephemeralTraces.value.slice(0, 500)
      persistEphemeral()
    }
  }

  function isEphemeral(traceId: string, item?: PlanSessionItem): boolean {
    // 优先后端字段（未来 sessions 项若带 ephemeral 则直接信任），否则本地映射，不硬造
    try {
      const flag = (item as unknown as Record<string, unknown> | undefined)?.ephemeral
      if (flag === true) return true
    } catch {}
    if (!traceId) return false
    return ephemeralTraces.value.includes(traceId)
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

  function removeTraceLocal(traceId: string): void {
    if (!traceId) return
    pins.value = pins.value.filter((t) => t !== traceId)
    delete names.value[traceId]
    ephemeralTraces.value = ephemeralTraces.value.filter((t) => t !== traceId)
    persistPins()
    persistNames()
    persistEphemeral()
    // 仅清本地展示，不删后端数据；仅当 items 实际包含该 trace 才减 total，避免删非当页漂移
    const existed = items.value.some((s) => s.trace_id === traceId)
    items.value = items.value.filter((s) => s.trace_id !== traceId)
    if (existed) total.value = Math.max(0, total.value - 1)
  }

  function removeTrace(traceId: string): void {
    removeTraceLocal(traceId)
  }

  // Wave-2 P0-6 会话真删：先调 DELETE /plans/sessions/{trace_id}；
  // 403/404 抛错由调用方 toast 且不本地删（避免 refresh 回跳闪烁）；网络错/5xx 才回退本地删
  async function deleteSession(traceId: string): Promise<void> {
    if (!traceId) return
    try {
      await apiClient.delete(`/plans/sessions/${encodeURIComponent(traceId)}`)
    } catch (e: unknown) {
      const status = (e as { response?: { status?: unknown } })?.response?.status
      if (status === 403 || status === 404) throw e
      // 后端未就绪/网络错/5xx：回退本地，保证可用
      removeTraceLocal(traceId)
      return
    }
    removeTraceLocal(traceId)
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
    const buckets: Record<KanbanGroupKey, PlanSessionItem[]> = { '进行中': [], '待审批': [], '已完成': [], '失败': [] }
    const resolve = resolveState ?? ((s) => getSessionPill(s))
    for (const s of list) buckets[kanbanKeyOf(resolve(s))].push(s)
    return (['进行中', '待审批', '已完成', '失败'] as KanbanGroupKey[]).map((key) => ({ key, items: buckets[key] }))
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

  return { items, total, page, size, loading, hasMore, pins, names, ephemeralTraces, getPins, isPinned, togglePin, getName, getManualName, isAutoName, displayName, setName, markEphemeral, isEphemeral, removeTrace, deleteSession, groupSessions, kanbanGroups, fetchPage, loadMore, refresh, reset }
})
