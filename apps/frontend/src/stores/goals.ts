import { defineStore } from 'pinia'
import { ref } from 'vue'
import { listGoals as fetchGoalsApi, type ListGoalsParams } from '@/api/goals'
import type { GoalItem, Paginated } from '@/types'
import { TTLCache, stableKey } from './cache'

const CACHE_TTL = 30_000

export const useGoalsStore = defineStore('goals', () => {
  const cache = new TTLCache<Paginated<GoalItem>>(CACHE_TTL, 128)
  const items = ref<GoalItem[]>([])
  const total = ref(0)
  const loading = ref(false)
  const lastParams = ref<ListGoalsParams | null>(null)

  function keyOf(params: ListGoalsParams): string {
    return `goals:${stableKey(params as unknown as Record<string, unknown>)}`
  }

  async function load(params: ListGoalsParams = {}, opts?: { force?: boolean; swr?: boolean }): Promise<Paginated<GoalItem>> {
    const key = keyOf(params)
    if (!opts?.force) {
      const hit = cache.get(key)
      if (hit) {
        items.value = hit.items
        total.value = hit.total
        lastParams.value = params
        // SWR 后台刷新
        if (opts?.swr !== false) void refresh(params)
        return hit
      }
      const stale = cache.getStale(key)
      if (stale) {
        items.value = stale.items
        total.value = stale.total
      }
    }
    return await refresh(params)
  }

  async function refresh(params: ListGoalsParams = {}): Promise<Paginated<GoalItem>> {
    const key = keyOf(params)
    loading.value = true
    try {
      const res = await fetchGoalsApi(params)
      const paginated = res.data
      cache.set(key, paginated)
      items.value = paginated.items
      total.value = paginated.total
      lastParams.value = params
      return paginated
    } finally {
      loading.value = false
    }
  }

  function invalidate(params?: ListGoalsParams): void {
    if (params) cache.invalidate(keyOf(params))
    else cache.invalidate()
  }

  return { items, total, loading, lastParams, load, refresh, invalidate, cache }
})
