// Wave-2 P1-15 设置收敛：pins/names/model/draft/hours/approval 六处散落 localStorage 键收敛到此一处
// 行为不变：键名/钳制/截断语义与原散落实现逐一对齐（sessions.ts pins/names、llm.ts model、
// workbench draft/hours、SettingsView approval），不改 SSE/包络契约
import { defineStore } from 'pinia'
import { ref } from 'vue'

export const PINS_KEY = 'workbench:pins'
export const NAMES_KEY = 'workbench:names'
export const MODEL_KEY = 'workbench:model'
export const DRAFT_KEY = 'workbench:draft'
export const HOURS_KEY = 'workbench:hours_per_day'
export const APPROVAL_KEY = 'settings:require-approval'

export type StoredSessionName = string | { name: string; auto: boolean }

// —— pins ——
export function getPins(): string[] {
  try {
    const raw = localStorage.getItem(PINS_KEY)
    if (!raw) return []
    const v: unknown = JSON.parse(raw)
    if (!Array.isArray(v)) return []
    return v.filter((x): x is string => typeof x === 'string' && x.length > 0).slice(0, 500)
  } catch { return [] }
}

export function setPins(pins: string[]): string[] {
  const next = (Array.isArray(pins) ? pins : [])
    .filter((x): x is string => typeof x === 'string' && x.length > 0)
    .slice(0, 500)
  try { localStorage.setItem(PINS_KEY, JSON.stringify(next)) } catch {}
  return [...next]
}

// —— names ——
export function getNames(): Record<string, StoredSessionName> {
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

export function setNames(names: Record<string, StoredSessionName>): void {
  try { localStorage.setItem(NAMES_KEY, JSON.stringify(names)) } catch {}
}

// —— model（与 api/llm.ts getStoredModel/setStoredModel 同语义：缺省 'auto'）——
export function getModel(): string {
  try {
    return localStorage.getItem(MODEL_KEY) || 'auto'
  } catch {
    return 'auto'
  }
}

export function setModel(v: string): void {
  try {
    localStorage.setItem(MODEL_KEY, v)
  } catch {}
}

// —— draft（与 workbench scheduleDraftSave 同语义：空去键，否则截断 2000）——
export function getDraft(): string {
  try {
    return localStorage.getItem(DRAFT_KEY) ?? ''
  } catch { return '' }
}

export function setDraft(v: string): void {
  try {
    const t = (v ?? '').trim()
    if (!t) localStorage.removeItem(DRAFT_KEY)
    else localStorage.setItem(DRAFT_KEY, v.slice(0, 2000))
  } catch {}
}

export function clearDraft(): void {
  try { localStorage.removeItem(DRAFT_KEY) } catch {}
}

// —— hours（1-8 取整，非法回退 null 由调用方默认 2）——
export function getHours(): number | null {
  try {
    const raw = localStorage.getItem(HOURS_KEY)
    if (!raw) return null
    const n = Number(raw)
    if (Number.isFinite(n) && n >= 1 && n <= 8) return Math.floor(n)
    return null
  } catch { return null }
}

export function setHours(n: number): number | null {
  const v = Math.floor(Number(n))
  if (!Number.isFinite(v) || v < 1 || v > 8) return null
  try { localStorage.setItem(HOURS_KEY, String(v)) } catch {}
  return v
}

// —— require-approval（'1' 开）——
export function getRequireApproval(): boolean {
  try { return localStorage.getItem(APPROVAL_KEY) === '1' } catch { return false }
}

export function setRequireApproval(v: boolean): void {
  try { localStorage.setItem(APPROVAL_KEY, v ? '1' : '0') } catch {}
}

export const useSettingsStore = defineStore('settings', () => {
  const hours = ref<number>(getHours() ?? 2)
  const requireApproval = ref<boolean>(getRequireApproval())
  const model = ref<string>(getModel())
  const draft = ref<string>(getDraft())

  function saveHours(v: number | null): void {
    const n = setHours(Number(v))
    if (n != null) hours.value = n
  }

  function saveApproval(v: boolean): void {
    requireApproval.value = v
    setRequireApproval(v)
  }

  function saveModel(v: string): void {
    model.value = v
    setModel(v)
  }

  function saveDraft(v: string): void {
    draft.value = v
    setDraft(v)
  }

  function refresh(): void {
    hours.value = getHours() ?? 2
    requireApproval.value = getRequireApproval()
    model.value = getModel()
    draft.value = getDraft()
  }

  return { hours, requireApproval, model, draft, saveHours, saveApproval, saveModel, saveDraft, refresh }
})
