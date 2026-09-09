<template>
  <div class="space-y-10">
    <div class="flex items-end justify-between">
      <div>
        <h2 class="text-[20px] font-semibold tracking-[-0.02em] text-ink">甘特视图</h2>
        <p class="mt-1 text-[11px] tracking-wide text-muted">横向时间轴 · 依赖连线 · 点击条形查看详情</p>
      </div>
      <n-space :size="8">
        <n-select v-model:value="goalId" :options="goalOpts" placeholder="按目标" clearable style="width: 168px" @update:value="load" />
        <n-select v-model:value="zoom" :options="zoomOpts" style="width: 96px" @update:value="onZoom" />
        <n-button strong secondary style="border-radius: 20px" @click="load">刷新</n-button>
      </n-space>
    </div>

    <n-alert v-if="loadError" type="error" title="加载失败" :show-icon="false" style="border-radius: 16px" class="text-[12px]">
      {{ loadError }}
    </n-alert>

    <n-card v-if="loading && !tasks.length && !loadError" class="apple-card" :bordered="false" content-style="padding: 32px 40px;">
      <n-skeleton text :repeat="5" :sharp="false" />
    </n-card>

    <n-card v-else-if="!loadError && !tasks.length" class="apple-card" :bordered="false" content-style="padding: 32px 40px;">
      <n-empty description="暂无任务，可先创建目标并生成计划" />
    </n-card>

    <n-card v-else-if="!loadError" class="apple-card" :bordered="false" content-style="padding: 32px 40px;">
      <div ref="wrapRef" class="overflow-auto px-2">
        <div class="min-w-[720px]">
          <div class="flex border-b border-[var(--c-hairline)] text-[11px] tracking-widest font-medium text-muted bg-surface rounded-t-[12px] px-4">
            <div class="w-[160px] shrink-0 py-2">任务</div>
            <div class="flex-1 flex">
              <div v-for="d in ticks" :key="d.key" class="flex-1 text-center py-2 border-l border-[var(--c-hairline)]">{{ d.label }}</div>
            </div>
          </div>
          <div v-for="t in tasks" :key="t.id" class="flex items-center h-[36px] border-b border-[var(--c-hairline)] px-4">
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
          <svg v-if="tasks.length > 1 && depLines.length" :width="svgW" :viewBox="`0 0 ${svgW} 20`" height="20" class="mt-2" role="img" aria-label="依赖连线"><line v-for="(l, i) in depLines" :key="`${l.from}-${l.to}-${i}`" :x1="l.x1" :y1="8" :x2="l.x2" :y2="8" stroke="var(--c-border)" stroke-dasharray="4 4"><title>{{ l.from }}→{{ l.to }} {{ l.relation }}</title></line></svg>
        </div>
      </div>
    </n-card>

    <n-card class="apple-card" :bordered="false" v-if="current" content-style="padding: 32px 40px;">
      <div class="text-[13px] font-semibold tracking-[-0.01em] text-ink">{{ current.title }}</div>
      <div class="mt-1 text-[11px] tracking-wide text-muted">{{ new Date(current.planned_start).toLocaleString() }} → {{ new Date(current.planned_end).toLocaleString() }}</div>
      <n-space class="mt-3" :size="8">
        <n-button size="small" style="border-radius: 20px" @click="mark('doing')">开始</n-button>
        <n-button size="small" type="primary" style="border-radius: 20px" @click="mark('done')">完成</n-button>
      </n-space>
    </n-card>
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'GanttView' })
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { NCard, NSpace, NButton, NSelect, NEmpty, NAlert, NSkeleton, useMessage } from 'naive-ui'
import { updateTask } from '@/api/tasks'
import { listGoals } from '@/api/goals'
import { fetchGraph } from '@/api/graph'
import { useTasksStore } from '@/stores/tasks'
import type { TaskItem, TaskStatus, GraphEdge } from '@/types'
import { extractErrorMessage } from '@/api/client'
import { buildGanttTicks, buildDepLines } from '@/utils/gantt'

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
const loading = computed(() => tasksStore.loading)
const loadError = ref('')
const current = ref<TaskItem | null>(null)
// 真连线数据源：GET /graph edges（type/relation 双兼容，见 utils/gantt.buildDepLines）
const graphEdges = ref<GraphEdge[]>([])
// 自适应容器宽：ResizeObserver 主路径，失败回退 720
const wrapRef = ref<HTMLElement | null>(null)
const containerW = ref(720)
let ro: ResizeObserver | null = null
function syncWidth(): void {
  try {
    const w = wrapRef.value?.clientWidth
    if (typeof w === 'number' && Number.isFinite(w) && w > 0) containerW.value = Math.max(320, Math.floor(w))
  } catch {}
}
function onZoom(v: string): void {
  zoom.value = v === 'week' ? 'week' : 'day'
}

const range = computed(() => {
  if (!tasks.value.length) return { min: new Date(), max: new Date(Date.now() + 7 * 86400000) }
  const mins = Math.min(...tasks.value.map((t) => new Date(t.planned_start).getTime()))
  const maxs = Math.max(...tasks.value.map((t) => new Date(t.planned_end).getTime()))
  return { min: new Date(mins), max: new Date(maxs) }
})
const ticks = computed(() => buildGanttTicks(range.value.min, range.value.max, zoom.value))
const totalMs = computed(() => Math.max(1, range.value.max.getTime() - range.value.min.getTime()))
function barStyle(t: TaskItem): Record<string, string> {
  const s = new Date(t.planned_start).getTime()
  const e = new Date(t.planned_end).getTime()
  const left = ((s - range.value.min.getTime()) / totalMs.value) * 100
  const width = Math.max(6, ((e - s) / totalMs.value) * 100)
  const bg = t.status === 'done' ? '#10b981' : t.status === 'doing' ? '#f59e0b' : t.status === 'delayed' ? '#ef4444' : '#3b82f6'
  return { left: left + '%', width: width + '%', background: bg }
}
const svgW = computed(() => containerW.value)
const depLines = computed(() => buildDepLines(tasks.value, graphEdges.value, range.value, svgW.value))
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
  loadError.value = ''
  try {
    await tasksStore.load({ goal_id: goalId.value || undefined, page: 1, size: 100 })
  } catch (e: unknown) {
    loadError.value = extractErrorMessage(e)
    message.error(loadError.value)
  }
  try {
    const g = await listGoals({ page: 1, size: 100 })
    goalOpts.value = g.data.items.map((x) => ({ label: `#${x.id} ${x.title}`, value: x.id }))
  } catch {}
  try {
    const gr = await fetchGraph({})
    graphEdges.value = Array.isArray(gr.data.edges) ? gr.data.edges : []
  } catch {
    graphEdges.value = []
  }
}
async function reloadForce(): Promise<void> {
  try {
    await tasksStore.load({ goal_id: goalId.value || undefined, page: 1, size: 100 }, { force: true })
  } catch (e: unknown) {
    loadError.value = extractErrorMessage(e)
    message.error(loadError.value)
  }
}
onMounted(() => {
  void load()
  syncWidth()
  try {
    if (typeof ResizeObserver !== 'undefined' && wrapRef.value) {
      ro = new ResizeObserver(() => syncWidth())
      ro.observe(wrapRef.value)
    } else if (typeof window !== 'undefined') {
      window.addEventListener('resize', syncWidth)
    }
  } catch {}
})
onBeforeUnmount(() => {
  try { ro?.disconnect() } catch {}
  ro = null
  try { window.removeEventListener('resize', syncWidth) } catch {}
})
</script>
