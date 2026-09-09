<template>
  <div class="space-y-10">
    <div class="flex items-end justify-between">
      <div>
        <h2 class="text-[20px] font-semibold tracking-[-0.02em] text-ink">通知</h2>
        <p class="mt-1 text-[11px] tracking-wide text-muted">桌面通知 · 本地已读 · 白底无框</p>
      </div>
      <n-space :size="8" align="center">
        <span class="text-[11px] tracking-wide text-muted">{{ unreadCount }} 条未读</span>
        <n-button size="small" style="border-radius: 20px" :disabled="!items.length || !unreadCount" @click="markAllRead">全部已读</n-button>
        <n-button size="small" style="border-radius: 20px" :disabled="!readIds.size" @click="markAllUnread">标为全未读</n-button>
        <n-button size="small" style="border-radius: 20px" :loading="loading" @click="load">刷新</n-button>
      </n-space>
    </div>

    <n-card class="apple-card" :bordered="false" content-style="padding: 24px;" aria-label="通知列表">
      <n-skeleton v-if="loading && !items.length && !loadError" text :repeat="3" :sharp="false" />
      <n-alert v-else-if="loadError" title="加载失败，请重试" type="error" :show-icon="false" class="rounded-[12px]">
        <span class="text-[13px] tracking-[-0.01em]">通知加载失败：{{ loadError }}</span>
        <div class="mt-2">
          <n-button size="small" style="border-radius: 20px" :loading="loading" @click="load">重试</n-button>
        </div>
      </n-alert>
      <div v-else-if="items.length" class="space-y-3">
        <div
          v-for="(n, idx) in items"
          :key="idOf(n, idx)"
          class="rounded-[16px] bg-[var(--c-surface)] p-4 flex items-start gap-3"
        >
          <span
            :class="['mt-1.5 w-2 h-2 rounded-full shrink-0', isRead(idOf(n, idx)) ? 'bg-[var(--c-border)]' : 'bg-[#0071e3]']"
            :aria-label="isRead(idOf(n, idx)) ? '已读' : '未读'"
          />
          <div class="min-w-0 flex-1">
            <div class="text-[13px] font-semibold tracking-[-0.01em] text-ink truncate">{{ n.title || '通知' }}</div>
            <div class="mt-1 text-[13px] leading-5 tracking-[-0.01em] text-ink whitespace-pre-wrap">{{ n.body || '—' }}</div>
            <div class="mt-1 text-[11px] tracking-wide text-muted">{{ timeOf(n) }}</div>
          </div>
          <n-button v-if="!isRead(idOf(n, idx))" size="tiny" secondary style="border-radius: 20px" class="shrink-0" @click="markOne(idOf(n, idx))">标为已读</n-button>
        </div>
      </div>
      <n-empty v-else description="暂无通知" class="py-10">
        <template #extra>
          <n-button size="small" style="border-radius: 20px" :loading="loading" @click="load">刷新</n-button>
        </template>
      </n-empty>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { NCard, NSpace, NButton, NSkeleton, NAlert, NEmpty } from 'naive-ui'
import { fetchNotifications, type NotifyPayload } from '@/api/desktop'
import { extractErrorMessage } from '@/api/client'

defineOptions({ name: 'NotificationsView' })

// 已读仅本地 localStorage：后端无已读端点，不硬造服务端同步（旧 syncDesktop({notifications_read}) 被静默忽略，已去掉）
const READ_KEY = 'notifications:read-ids'

type RawNotify = NotifyPayload & { id?: number | string; created_at?: string; time?: string; createdAt?: string }

const items = ref<RawNotify[]>([])
const loading = ref(false)
const loadError = ref('')
const readIds = ref<Set<string>>(new Set())

function loadReadIds(): void {
  try {
    const raw = localStorage.getItem(READ_KEY)
    if (!raw) {
      readIds.value = new Set()
      return
    }
    const arr = JSON.parse(raw) as unknown
    if (Array.isArray(arr)) {
      readIds.value = new Set(arr.filter((x): x is string => typeof x === 'string'))
    }
  } catch {
    readIds.value = new Set()
  }
}

function persistReadIds(): void {
  try { localStorage.setItem(READ_KEY, JSON.stringify(Array.from(readIds.value))) } catch {}
}

function idOf(n: RawNotify, idx: number): string {
  if (n.id !== undefined && n.id !== null && String(n.id).length) return String(n.id)
  return `${idx}:${n.title ?? ''}:${n.body ?? ''}`
}

function timeOf(n: RawNotify): string {
  const raw = n.created_at ?? n.time ?? n.createdAt ?? ''
  if (!raw) return '—'
  try {
    const t = new Date(raw)
    if (Number.isNaN(t.getTime())) return raw
    return t.toLocaleString()
  } catch {
    return raw
  }
}

function isRead(id: string): boolean {
  return readIds.value.has(id)
}

function markOne(id: string): void {
  const next = new Set(readIds.value)
  next.add(id)
  readIds.value = next
  persistReadIds()
}

function markAllRead(): void {
  const next = new Set(readIds.value)
  items.value.forEach((n, idx) => { next.add(idOf(n, idx)) })
  readIds.value = next
  persistReadIds()
}

// 诚实命名：清空已读标记 = 全部回未读，无服务端态，不做无效 sync
function markAllUnread(): void {
  readIds.value = new Set()
  persistReadIds()
}

const unreadCount = computed(() => items.value.filter((n, idx) => !readIds.value.has(idOf(n, idx))).length)

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const res = await fetchNotifications()
    const list = res.data.items as unknown
    items.value = Array.isArray(list) ? (list as RawNotify[]) : []
  } catch (e: unknown) {
    loadError.value = extractErrorMessage(e)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadReadIds()
  void load()
})
</script>
