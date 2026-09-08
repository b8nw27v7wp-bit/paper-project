import { apiClient, isApiEnvelope } from './client'
import type { ApiEnvelope } from '@/types'

export interface LlmModel { id: string; name?: string; provider?: string; model?: string; base?: string; contextWindow?: number }

export const MODEL_STORAGE_KEY = 'workbench:model'

export const FALLBACK_MODEL_OPTIONS: Array<{ label: string; value: string }> = [
  { label: '自动', value: 'auto' },
  { label: '默认', value: 'default' },
]

function pickArrayFromObject(o: Record<string, unknown>): unknown[] {
  for (const k of ['models', 'items', 'list', 'data']) {
    const v = o[k]
    if (Array.isArray(v)) return v as unknown[]
  }
  return []
}

/** 兼容解析：包络 data 可能是数组或对象，做归一化，失败返回空数组由上层回退 */
export function normalizeLlmModels(raw: unknown): LlmModel[] {
  let data: unknown = raw
  if (isApiEnvelope<unknown>(raw)) {
    data = (raw as ApiEnvelope<unknown>).data
  } else if (raw && typeof raw === 'object' && !Array.isArray(raw) && 'data' in (raw as Record<string, unknown>)) {
    const inner = (raw as Record<string, unknown>).data
    data = isApiEnvelope<unknown>(inner) ? (inner as ApiEnvelope<unknown>).data : inner
  }
  let list: unknown[] = []
  if (Array.isArray(data)) {
    list = data
  } else if (data && typeof data === 'object' && !Array.isArray(data)) {
    const o = data as Record<string, unknown>
    list = pickArrayFromObject(o)
    if (!list.length) {
      const entries = Object.entries(o)
      const looksLikeMap = entries.length > 0 && entries.length <= 20
        && entries.every(([, v]) => v && typeof v === 'object' && ('model' in (v as object) || 'id' in (v as object)))
      if (looksLikeMap) {
        list = entries.map(([k, v]) => ({ provider: k, ...((v as Record<string, unknown>) ?? {}) }))
      }
    }
  }
  const out: LlmModel[] = []
  for (const e of list) {
    if (typeof e === 'string') {
      const s = e.trim()
      if (s) out.push({ id: s, name: s })
      continue
    }
    if (!e || typeof e !== 'object' || Array.isArray(e)) continue
    const r = e as Record<string, unknown>
    const id = String(r.id ?? r.model ?? r.name ?? r.provider ?? '').trim()
    if (!id) continue
    const provider = r.provider != null ? String(r.provider) : undefined
    const name = String(r.name ?? r.model ?? r.id ?? provider ?? id)
    const model = r.model != null ? String(r.model) : undefined
    const base = r.base != null ? String(r.base) : undefined
    const contextWindow = typeof r.contextWindow === 'number' ? (r.contextWindow as number) : undefined
    out.push({ id, name, provider, model, base, contextWindow })
  }
  const seen = new Set<string>()
  return out.filter((m) => {
    if (seen.has(m.id)) return false
    seen.add(m.id)
    return true
  })
}

export function toModelOptions(models: LlmModel[]): Array<{ label: string; value: string }> {
  return models.map((m) => ({ label: String(m.name ?? m.id), value: m.id }))
}

export function getStoredModel(): string {
  try {
    return localStorage.getItem(MODEL_STORAGE_KEY) || 'auto'
  } catch {
    return 'auto'
  }
}

export function setStoredModel(v: string): void {
  try {
    localStorage.setItem(MODEL_STORAGE_KEY, v)
  } catch {}
}

export async function fetchLlmModels(): Promise<ApiEnvelope<LlmModel[]>> {
  const { data } = await apiClient.get('/llm/models')
  const normalized = normalizeLlmModels(data)
  if (isApiEnvelope<LlmModel[]>(data)) {
    return { code: data.code, msg: data.msg, data: normalized }
  }
  return { code: 200, msg: 'ok', data: normalized }
}

/** 模型下拉选项：成功取接口模型名，失败/空回退两档（自动/默认），永不抛错 */
export async function fetchLlmModelOptions(): Promise<Array<{ label: string; value: string }>> {
  try {
    const res = await fetchLlmModels()
    const opts = toModelOptions(res.data ?? [])
    if (opts.length) return opts
    return [...FALLBACK_MODEL_OPTIONS]
  } catch {
    return [...FALLBACK_MODEL_OPTIONS]
  }
}
