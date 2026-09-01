<template>
  <div class="space-y-10">
    <div class="flex items-end justify-between">
      <div>
        <h2 class="text-[24px] font-semibold tracking-[-0.02em] text-ink">甘特视图</h2>
        <p class="mt-1 text-[13px] tracking-[-0.01em] text-muted">横向时间轴 · 依赖连线 · 拖拽联动</p>
      </div>
      <n-space :size="8">
        <n-select v-model:value="goalId" :options="goalOpts" placeholder="按目标" clearable style="width: 168px" @update:value="load" />
        <n-select v-model:value="zoom" :options="zoomOpts" style="width: 96px" />
        <n-button strong secondary style="border-radius: 20px" @click="load">刷新</n-button>
      </n-space>
    </div>

    <n-card class="apple-card" content-style="padding: 32px;">
      <div class="overflow-auto">
        <div class="min-w-[720px]">
          <div class="flex border-b border-[#f5f5f7] text-[11px] tracking-widest font-medium text-muted bg-[#f5f5f7]/60 rounded-t-[12px] px-2">
            <div class="w-[160px] shrink-0 py-2">任务</div>
            <div class="flex-1 flex">
              <div v-for="d in ticks" :key="d.key" class="flex-1 text-center py-2 border-l border-[#f5f5f7]">{{ d.label }}</div>
            </div>
          </div>
          <div v-for="t in tasks" :key="t.id" class="flex items-center h-[36px] border-b border-[#f5f5f7]">
            <div class="w-[160px] shrink-0 truncate text-[12px] tracking-[-0.01em] text-ink pr-2">{{ t.title }}</div>
            <div class="flex-1 relative h-full">
              <div
                class="absolute top-[8px] h-[20px] rounded-full flex items-center px-2 text-[11px] text-white cursor-pointer"
                :style="barStyle(t)"
                @click="open(t)"
              >
                {{ t.status }}
              </div>
            </div>
          </div>
          <svg v-if="tasks.length > 1" :width="svgW" height="20" class="mt-2"><line v-for="(l, i) in depLines" :key="i" :x1="l.x1" :y1="8" :x2="l.x2" :y2="8" stroke="#d1d5db" stroke-dasharray="4 4" /></svg>
        </div>
      </div>
      <n-empty v-if="!tasks.length" description="暂无任务" class="mt-6" />
    </n-card>

    <n-card class="apple-card" v-if="current" content-style="padding: 32px;">
      <div class="text-[13px] font-semibold tracking-[-0.01em] text-ink">{{ current.title }}</div>
      <div class="text-[12px] tracking-wide text-muted mt-1">{{ new Date(current.planned_start).toLocaleString() }} → {{ new Date(current.planned_end).toLocaleString() }}</div>
      <n-space class="mt-3" :size="8">
        <n-button size="small" style="border-radius: 20px" @click="mark('doing')">开始</n-button>
        <n-button size="small" type="primary" style="border-radius: 20px" @click="mark('done')">完成</n-button>
      </n-space>
    </n-card>
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'GanttView' })
import { ref, computed, onMounted } from 'vue'
import { NCard, NSpace, NButton, NSelect, NEmpty, useMessage } from 'naive-ui'
import { updateTask } from '@/api/tasks'
import { listGoals } from '@/api/goals'
import { useTasksStore } from '@/stores/tasks'
import type { TaskItem, TaskStatus } from '@/types'
import { extractErrorMessage } from '@/api/client'

const message = useMessage()
const tasksStore = useTasksStore()
const goalId = ref<number | null>(null)
const goalOpts = ref<Array<{ label: string; value: number }>>([])
const zoom = ref<string>('day')
const zoomOpts = [
  { label: '日', value: 'day' },
  { label: '周', value: 'week' },
]
const tasks = computed(() => tasksStore.items)
const current = ref<TaskItem | null>(null)

const range = computed(() => {
  if (!tasks.value.length) return { min: new Date(), max: new Date(Date.now() + 7 * 86400000) }
  const mins = Math.min(...tasks.value.map((t) => new Date(t.planned_start).getTime()))
  const maxs = Math.max(...tasks.value.map((t) => new Date(t.planned_end).getTime()))
  return { min: new Date(mins), max: new Date(maxs) }
})
const ticks = computed(() => {
  const r = range.value
  const days = Math.max(7, Math.ceil((r.max.getTime() - r.min.getTime()) / 86400000) + 1)
  return Array.from({ length: Math.min(days, 14) }, (_, i) => {
    const d = new Date(r.min)
    d.setDate(d.getDate() + i)
    return { key: d.toISOString().slice(0, 10), label: d.toISOString().slice(5, 10) }
  })
})
const totalMs = computed(() => Math.max(1, range.value.max.getTime() - range.value.min.getTime()))
function barStyle(t: TaskItem): Record<string, string> {
  const s = new Date(t.planned_start).getTime()
  const e = new Date(t.planned_end).getTime()
  const left = ((s - range.value.min.getTime()) / totalMs.value) * 100
  const width = Math.max(6, ((e - s) / totalMs.value) * 100)
  const bg = t.status === 'done' ? '#10b981' : t.status === 'doing' ? '#f59e0b' : t.status === 'delayed' ? '#ef4444' : '#3b82f6'
  return { left: left + '%', width: width + '%', background: bg }
}
const svgW = computed(() => 720)
const depLines = computed(() => {
  const sorted = [...tasks.value].sort((a, b) => new Date(a.planned_start).getTime() - new Date(b.planned_start).getTime())
  return sorted.slice(0, -1).map((_, i) => {
    const a = sorted[i]
    const b = sorted[i + 1]
    const ax = ((new Date(a.planned_end).getTime() - range.value.min.getTime()) / totalMs.value) * svgW.value
    const bx = ((new Date(b.planned_start).getTime() - range.value.min.getTime()) / totalMs.value) * svgW.value
    return { x1: ax, x2: bx }
  })
})
function open(t: TaskItem): void {
  current.value = t
}
async function mark(s: TaskStatus): Promise<void> {
  if (!current.value) return
  try {
    await updateTask(current.value.id, { status: s })
    message.success('已更新')
    tasksStore.invalidateAll()
    void reloadForce()
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
  }
}
async function load(_v?: unknown): Promise<void> {
  try {
    await tasksStore.load({ goal_id: goalId.value || undefined, page: 1, size: 100 })
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
  }
  try {
    const g = await listGoals({ page: 1, size: 100 })
    goalOpts.value = g.data.items.map((x) => ({ label: `#${x.id} ${x.title}`, value: x.id }))
  } catch {}
}
async function reloadForce(): Promise<void> {
  try {
    await tasksStore.load({ goal_id: goalId.value || undefined, page: 1, size: 100 }, { force: true })
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
  }
}
onMounted(() => {
  void load()
})
</script>
