import { defineStore } from 'pinia'
import { ref } from 'vue'
import { listTasks as fetchTasksApi, type ListTasksParams } from '@/api/tasks'
import type { TaskItem, Paginated } from '@/types'
import { TTLCache, stableKey } from './cache'

const CACHE_TTL = 30_000

export const useTasksStore = defineStore('tasks', () => {
  const cache = new TTLCache<Paginated<TaskItem>>(CACHE_TTL, 256)
  const items = ref<TaskItem[]>([])
  const total = ref(0)
  const loading = ref(false)

  function keyOf(params: ListTasksParams): string {
    return `tasks:${stableKey(params as unknown as Record<string, unknown>)}`
  }

  async function load(params: ListTasksParams = {}, opts?: { force?: boolean }): Promise<Paginated<TaskItem>> {
    const key = keyOf(params)
    if (!opts?.force) {
      const hit = cache.get(key)
      if (hit) {
        items.value = hit.items
        // total 未在 tasks/list 中返回时用 items 长度兜底
        total.value = (hit as unknown as { total?: number }).total ?? hit.items.length
        // SWR
        void refresh(params)
        return hit
      }
      const stale = cache.getStale(key)
      if (stale) {
        items.value = stale.items
        total.value = (stale as unknown as { total?: number }).total ?? stale.items.length
      }
    }
    return await refresh(params)
  }

  async function refresh(params: ListTasksParams = {}): Promise<Paginated<TaskItem>> {
    const key = keyOf(params)
    loading.value = true
    try {
      const res = await fetchTasksApi(params)
      const paginated = res.data
      cache.set(key, paginated)
      items.value = paginated.items
      total.value = paginated.total
      return paginated
    } finally {
      loading.value = false
    }
  }

  function invalidate(params?: ListTasksParams): void {
    if (params) cache.invalidate(keyOf(params))
    else cache.invalidate()
  }
  function invalidateAll(): void { cache.invalidate() }

  return { items, total, loading, load, refresh, invalidate, invalidateAll, cache }
})
