<template>
  <div class="space-y-10">
    <div class="flex items-end justify-between">
      <div>
        <h2 class="text-[24px] font-semibold tracking-[-0.02em] text-ink">周视图</h2>
        <p class="mt-1 text-[13px] tracking-[-0.01em] text-muted">周维度聚合 · 负荷/完成率 · 批量拖拽改期 — 白底无框</p>
      </div>
      <n-space :size="8">
        <n-button size="small" style="border-radius: 20px" @click="shift(-7)">上一周</n-button>
        <n-button size="small" style="border-radius: 20px" @click="today">本周</n-button>
        <n-button size="small" style="border-radius: 20px" @click="shift(7)">下一周</n-button>
        <n-select v-model:value="goalId" :options="goalOpts" placeholder="按目标" clearable style="width: 168px" @update:value="load" />
        <n-button strong secondary style="border-radius: 20px" @click="load">刷新</n-button>
      </n-space>
    </div>

    <n-card class="apple-card" content-style="padding: 32px;">
      <div class="grid grid-cols-7 gap-3">
        <div v-for="d in days" :key="d.key" class="rounded-[16px] bg-[#f5f5f7] p-3">
          <div class="text-[11px] tracking-widest font-medium text-muted">{{ d.label }}</div>
          <div class="text-[13px] font-semibold tracking-[-0.01em] text-ink">{{ d.dateLabel }}</div>
          <div class="mt-2 h-1.5 rounded-full bg-white overflow-hidden"><div class="h-full bg-[#1d1d1f]" :style="{ width: d.loadPct + '%' }" /></div>
          <div class="mt-1 text-[11px] tracking-wide text-muted">{{ d.loadHours.toFixed(1) }}h · {{ (d.rate * 100).toFixed(0) }}%</div>
          <n-tag size="small" :type="d.overload ? 'error' : 'default'" class="mt-1" style="border-radius: 20px">{{ d.count }} 任务</n-tag>
        </div>
      </div>
    </n-card>

    <n-card v-if="selected.length" class="apple-card" style="background: #fffbe6 !important">
      <n-space align="center" justify="space-between">
        <span class="text-[13px] font-medium tracking-[-0.01em] text-ink">已选 {{ selected.length }} 项</span>
        <n-space :size="8">
          <n-button size="small" style="border-radius: 20px" @click="batchDone">批量完成</n-button>
          <n-button size="small" style="border-radius: 20px" @click="batchShift(1)">批量+1天</n-button>
          <n-button size="small" style="border-radius: 20px" @click="batchShift(7)">批量+1周</n-button>
          <n-button size="small" style="border-radius: 20px" @click="selected = []">清空</n-button>
        </n-space>
      </n-space>
    </n-card>

    <div class="grid grid-cols-7 gap-4">
      <n-card v-for="d in days" :key="d.key" class="apple-card" size="small" :title="d.label">
        <div class="space-y-2 min-h-[160px]">
          <div
            v-for="t in d.tasks"
            :key="t.id"
            class="rounded-xl bg-[#f5f5f7] p-2 flex items-center justify-between cursor-move"
            draggable="true"
            @dragstart="onDrag(t)"
            @dragover.prevent
            @drop="onDrop(d)"
          >
            <n-checkbox :checked="selected.includes(t.id)" @update:checked="(v: boolean) => toggle(t.id, v)" />
            <span class="text-[12px] tracking-[-0.01em] text-ink truncate flex-1 ml-2">{{ t.title }}</span>
            <n-tag size="tiny" :type="t.status === 'done' ? 'success' : t.status === 'doing' ? 'warning' : 'default'" style="border-radius: 20px">{{ t.status }}</n-tag>
          </div>
          <n-empty v-if="!d.tasks.length" description="空" size="small" />
        </div>
      </n-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NCard, NSpace, NButton, NSelect, NTag, NCheckbox, NEmpty, useMessage } from 'naive-ui'
import { updateTask } from '@/api/tasks'
import { listGoals } from '@/api/goals'
import { useTasksStore } from '@/stores/tasks'
import type { TaskItem } from '@/types'
import { extractErrorMessage } from '@/api/client'

const message = useMessage()
const route = useRoute()
const router = useRouter()
const tasksStore = useTasksStore()
const goalId = ref<number | null>(Number(route.query.goal_id) || null)
const goalOpts = ref<Array<{ label: string; value: number }>>([])
const tasks = computed(() => tasksStore.items)
const selected = ref<number[]>([])
const weekStart = ref<Date>(startOfWeek(new Date()))
const dragTask = ref<TaskItem | null>(null)

function startOfWeek(d: Date): Date {
  const n = new Date(d)
  const day = n.getDay() || 7
  n.setDate(n.getDate() - (day - 1))
  n.setHours(0, 0, 0, 0)
  return n
}
function shift(days: number): void {
  const n = new Date(weekStart.value)
  n.setDate(n.getDate() + days)
  weekStart.value = n
  void load()
}
function today(): void {
  weekStart.value = startOfWeek(new Date())
  void load()
}
interface DayBucket {
  key: string
  label: string
  dateLabel: string
  tasks: TaskItem[]
  loadHours: number
  count: number
  rate: number
  loadPct: number
  overload: boolean
}
const days = computed<DayBucket[]>(() => {
  // 预建 Map: dateKey -> tasks，避免 7次全量 filter（O(n*7) → O(n)）
  const map = new Map<string, TaskItem[]>()
  for (const t of tasks.value) {
    const k = String(t.planned_start).slice(0, 10)
    const arr = map.get(k)
    if (arr) arr.push(t)
    else map.set(k, [t])
  }
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(weekStart.value)
    d.setDate(d.getDate() + i)
    const key = d.toISOString().slice(0, 10)
    const dayTasks = map.get(key) ?? []
    const loadHours = dayTasks.reduce((s, t) => s + (new Date(t.planned_end).getTime() - new Date(t.planned_start).getTime()) / 3600000, 0)
    const done = dayTasks.filter((t) => t.status === 'done').length
    return {
      key,
      label: ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][i],
      dateLabel: key.slice(5),
      tasks: dayTasks,
      loadHours,
      count: dayTasks.length,
      rate: dayTasks.length ? done / dayTasks.length : 0,
      loadPct: Math.min(100, loadHours * 12.5),
      overload: loadHours > 8,
    }
  })
})
function toggle(id: number, v: boolean): void {
  if (v) selected.value = [...selected.value, id]
  else selected.value = selected.value.filter((x) => x !== id)
}
function onDrag(t: TaskItem): void {
  dragTask.value = t
}
async function onDrop(day: DayBucket): Promise<void> {
  if (!dragTask.value) return
  const t = dragTask.value
  const old = new Date(t.planned_start)
  const dur = new Date(t.planned_end).getTime() - old.getTime()
  const ns = new Date(day.key + 'T' + old.toISOString().slice(11))
  const ne = new Date(ns.getTime() + dur)
  try {
    await updateTask(t.id, { planned_start: ns.toISOString(), planned_end: ne.toISOString() })
    message.success('已改期')
    tasksStore.invalidateAll()
    void reloadForce()
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
  }
}
async function batchDone(): Promise<void> {
  for (const id of selected.value) {
    try {
      await updateTask(id, { status: 'done' })
    } catch {}
  }
  message.success('批量完成')
  selected.value = []
  tasksStore.invalidateAll()
  void reloadForce()
}
async function batchShift(daysN: number): Promise<void> {
  for (const id of selected.value) {
    const t = tasks.value.find((x) => x.id === id)
    if (!t) continue
    const s = new Date(t.planned_start)
    s.setDate(s.getDate() + daysN)
    const e = new Date(t.planned_end)
    e.setDate(e.getDate() + daysN)
    try {
      await updateTask(id, { planned_start: s.toISOString(), planned_end: e.toISOString() })
    } catch {}
  }
  message.success('批量改期')
  selected.value = []
  tasksStore.invalidateAll()
  void reloadForce()
}
async function load(): Promise<void> {
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
watch(goalId, (v) => {
  void router.replace({ query: { ...route.query, goal_id: v ? String(v) : undefined } })
})
onMounted(() => {
  void load()
})
</script>
