/**
 * 通用 TTL 缓存 — 30s stale-while-revalidate，LRU 512
 * 纯内存，不依赖外部库，便于 Goals/Tasks 复用
 */
export interface CacheEntry<T> {
  data: T
  ts: number
  key: string
}

export class TTLCache<T> {
  private map = new Map<string, CacheEntry<T>>()
  private ttlMs: number
  private max: number
  constructor(ttlMs = 30_000, max = 512) {
    this.ttlMs = ttlMs
    this.max = max
  }
  private evictIfNeeded(): void {
    if (this.map.size <= this.max) return
    const first = this.map.keys().next().value as string | undefined
    if (first) this.map.delete(first)
  }
  get(key: string, now = Date.now()): T | null {
    const e = this.map.get(key)
    if (!e) return null
    if (now - e.ts > this.ttlMs) return null
    // LRU 提升
    this.map.delete(key)
    this.map.set(key, e)
    return e.data
  }
  // stale 可读（即使过期也返回，供 SWR）
  getStale(key: string): T | null {
    return this.map.get(key)?.data ?? null
  }
  isFresh(key: string, now = Date.now()): boolean {
    const e = this.map.get(key)
    if (!e) return false
    return now - e.ts <= this.ttlMs
  }
  set(key: string, data: T): void {
    this.map.set(key, { key, data, ts: Date.now() })
    this.evictIfNeeded()
  }
  invalidate(key?: string): void {
    if (key) this.map.delete(key)
    else this.map.clear()
  }
  invalidatePrefix(prefix: string): void {
    for (const k of Array.from(this.map.keys())) if (k.startsWith(prefix)) this.map.delete(k)
  }
}

export function stableKey(obj: Record<string, unknown>): string {
  const keys = Object.keys(obj).sort()
  return keys.map((k) => `${k}=${JSON.stringify(obj[k])}`).join('&')
}
