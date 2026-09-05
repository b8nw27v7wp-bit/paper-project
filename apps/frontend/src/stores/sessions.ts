import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { listSessions } from '@/api/plans'
import type { PlanSessionItem } from '@/api/plans'

export const useSessionsStore = defineStore('sessions', () => {
  const items = ref<PlanSessionItem[]>([])
  const total = ref(0)
  const page = ref(1)
  const size = ref(20)
  const loading = ref(false)
  const hasMore = computed(() => items.value.length < total.value)

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

  return { items, total, page, size, loading, hasMore, fetchPage, loadMore, refresh, reset }
})
