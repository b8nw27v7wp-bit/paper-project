<template>
  <div class="space-y-10">
    <div class="flex items-end justify-between">
      <div>
        <h2 class="text-[24px] font-semibold tracking-[-0.02em] text-ink">日历</h2>
        <p class="mt-1 text-[13px] tracking-[-0.01em] text-muted">F03 甘特 · 拖拽即更新 · 批量操作 · 热力负荷 — 联调已完成</p>
      </div>
      <n-space :size="8">
        <n-select v-model:value="viewMode" :options="viewOpts" style="width: 112px" />
        <n-select v-model:value="goalId" :options="goalOpts" placeholder="按目标" clearable style="width: 168px" @update:value="load" />
        <n-select v-model:value="statusFilter" :options="statusOpts" placeholder="状态" clearable style="width: 112px" @update:value="load" />
        <n-button strong secondary style="border-radius: 20px" @click="load">刷新</n-button>
        <n-button type="primary" style="border-radius: 20px" @click="showBatch = true">批量建任务</n-button>
      </n-space>
    </div>

    <n-card class="apple-card" content-style="padding: 32px;">
      <div class="flex items-center justify-between mb-4">
        <span class="text-[11px] tracking-widest font-medium text-muted">负荷热力 · 日小时 · 克制配色 #1d1d1f 透明度</span>
        <n-switch v-model:value="showHeat" size="small"><template #checked>热力开</template><template #unchecked>热力关</template></n-switch>
      </div>
      <div v-if="showHeat" class="grid grid-cols-7 gap-2 mb-6">
        <div v-for="h in heat" :key="h.date" class="rounded-[16px] p-3 text-center border border-transparent" :style="{ background: h.color }">
          <div class="text-[11px] tracking-wide text-muted">{{ h.date.slice(5) }}</div>
          <div class="text-[13px] font-semibold tracking-[-0.01em] text-ink">{{ h.hours.toFixed(1) }}h</div>
          <div class="text-[10px] tracking-wide text-muted">{{ h.count }}项 · {{ (h.rate * 100).toFixed(0) }}%</div>
        </div>
      </div>
      <FullCalendar :options="calOpts" ref="calRef" />
    </n-card>

    <n-card v-if="selectedIds.length" class="apple-card" style="background: #fffbe6 !important">
      <n-space align="center" justify="space-between">
        <span class="text-[13px] font-medium tracking-[-0.01em] text-ink">已选 {{ selectedIds.length }} 项</span>
        <n-space :size="8">
          <n-button size="small" type="primary" style="border-radius: 20px" @click="batchComplete">批量完成</n-button>
          <n-button size="small" style="border-radius: 20px" @click="batchReschedule(1)">批量+1天</n-button>
          <n-button size="small" style="border-radius: 20px" @click="batchReschedule(7)">批量+1周</n-button>
          <n-button size="small" style="border-radius: 20px" @click="selectedIds = []">清空</n-button>
        </n-space>
      </n-space>
    </n-card>

    <n-card class="apple-card" v-if="traceId" content-style="padding: 32px;">
      <template #header><span class="text-[13px] font-semibold tracking-[-0.01em] text-ink">计划轨迹 {{ traceId }}</span></template>
      <n-spin :show="loadingPlan">
        <n-data-table
          v-if="planLogs.length"
          :columns="planCols"
          :data="planLogs"
          :pagination="false"
          size="small"
          :bordered="false"
          :row-key="(r: PlanLogItem) => String(r.id ?? r.agent_name + r.created_at)"
        />
        <n-empty v-else description="暂无计划日志" />
        <div class="mt-4 flex justify-end">
          <n-button size="small" style="border-radius: 20px" @click="loadPlan">刷新轨迹</n-button>
        </div>
      </n-spin>
    </n-card>

    <n-card class="apple-card" content-style="padding: 24px;" aria-label="任务列表">
      <template #header>
        <div class="flex items-center justify-between w-full">
          <span class="text-[13px] font-semibold tracking-[-0.01em] text-ink">列表（多选批量操作）</span>
          <n-checkbox :checked="allChecked" label="全选" @update:checked="toggleAll" />
        </div>
      </template>
      <n-skeleton v-if="tasksStore.loading && !tasks.length" text :repeat="4" :sharp="false" />
      <n-data-table
        v-else
        :columns="cols"
        :data="tasks"
        :pagination="false"
        size="small"
        :bordered="false"
        :row-key="(r: TaskItem) => r.id"
        :checked-row-keys="selectedIds"
        @update:checked-row-keys="onCheck"
      />
    </n-card>

    <TaskDrawer v-model="showDrawer" :task="current" @refresh="load" @delete="onDelete" />

    <n-modal v-model:show="showBatch" preset="card" title="批量创建任务 (POST /tasks/batch)" style="width: 640px; border-radius: 16px">
      <n-form :model="batch" label-placement="left" label-width="90">
        <n-form-item label="目标ID"><n-input-number v-model:value="batch.goal_id" class="w-full" /></n-form-item>
        <n-form-item label="标题前缀"><n-input v-model:value="batch.prefix" placeholder="如: 背单词" /></n-form-item>
        <n-form-item label="天数"><n-input-number v-model:value="batch.days" :min="1" :max="14" class="w-full" /></n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end" :size="8"><n-button style="border-radius: 20px" @click="showBatch = false">取消</n-button><n-button type="primary" style="border-radius: 20px" :loading="batching" @click="doBatch">生成</n-button></n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'CalendarView' })
import { ref, computed, onMounted, h, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useTasksStore } from '@/stores/tasks'
import {
  NCard,
  NSpace,
  NButton,
  NSelect,
  NDataTable,
  NModal,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NTag,
  useMessage,
  NSpin,
  NEmpty,
  NCheckbox,
  NSwitch,
  NSkeleton,
} from 'naive-ui'
import FullCalendar from '@fullcalendar/vue3'
import dayGridPlugin from '@fullcalendar/daygrid'
import timeGridPlugin from '@fullcalendar/timegrid'
import interactionPlugin from '@fullcalendar/interaction'
import { updateTask, batchCreateTasks, deleteTask } from '@/api/tasks'
import { listGoals } from '@/api/goals'
import { getPlanLogs } from '@/api/plans'
import TaskDrawer from '@/components/TaskDrawer.vue'
import type { TaskItem, PlanLogItem } from '@/types'
import { extractErrorMessage } from '@/api/client'
import type { DataTableColumns } from 'naive-ui'

const route = useRoute()
const message = useMessage()
const tasksStore = useTasksStore()
const goalId = ref<number | null>(Number(route.query.goal_id) || null)
const statusFilter = ref<string | null>(null)
const viewMode = ref<string>('timeGridWeek')
const viewOpts = [
  { label: '周视图', value: 'timeGridWeek' },
  { label: '月视图', value: 'dayGridMonth' },
]
const showHeat = ref(true)
const goalOpts = ref<Array<{ label: string; value: number }>>([])
const statusOpts = [
  { label: 'todo', value: 'todo' },
  { label: 'doing', value: 'doing' },
  { label: 'done', value: 'done' },
  { label: 'delayed', value: 'delayed' },
]
const tasks = computed(() => tasksStore.items)
const showDrawer = ref(false)
const current = ref<TaskItem | null>(null)
const calRef = ref<{ getApi?: () => { changeView: (v: string) => void } } | null>(null)
const showBatch = ref(false)
const batch = ref({ goal_id: 1, prefix: '学习任务', days: 3 })
const batching = ref(false)
const traceId = ref<string | null>((route.query.trace_id as string) || null)
const planLogs = ref<PlanLogItem[]>([])
const loadingPlan = ref(false)
const selectedIds = ref<number[]>([])

const allChecked = computed(() => tasks.value.length > 0 && selectedIds.value.length === tasks.value.length)
function toggleAll(v: boolean): void {
  selectedIds.value = v ? tasks.value.map((t) => t.id) : []
}
function onCheck(keys: Array<string | number>): void {
  selectedIds.value = keys as number[]
}

const heat = computed(() => {
  const map: Record<string, { hours: number; count: number; done: number }> = {}
  tasks.value.forEach((t) => {
    const d = String(t.planned_start).slice(0, 10)
    if (!map[d]) map[d] = { hours: 0, count: 0, done: 0 }
    const h = (new Date(t.planned_end).getTime() - new Date(t.planned_start).getTime()) / 3600000
    map[d].hours += h
    map[d].count += 1
    if (t.status === 'done') map[d].done += 1
  })
  return Object.entries(map)
    .slice(0, 7)
    .map(([date, v]) => {
      const rate = v.count ? v.done / v.count : 0
      const intensity = Math.min(1, v.hours / 8)
      const bg = `rgba(29,29,31,${(0.06 + intensity * 0.12).toFixed(3)})`
      return { date, hours: v.hours, count: v.count, rate, color: bg }
    })
})

const events = computed(() =>
  tasks.value.map((t) => ({
    id: String(t.id),
    title: t.title,
    start: t.planned_start,
    end: t.planned_end,
    backgroundColor: t.status === 'done' ? '#10b981' : t.status === 'doing' ? '#f59e0b' : t.status === 'delayed' ? '#ef4444' : '#3b82f6',
    borderColor: 'transparent',
    textColor: '#ffffff',
    classNames: ['fc-event-no-border'],
  })),
)

const calOpts = computed(
  () =>
    ({
      plugins: [dayGridPlugin, timeGridPlugin, interactionPlugin],
      initialView: viewMode.value,
      headerToolbar: { left: 'prev,next today', center: 'title', right: 'dayGridMonth,timeGridWeek,timeGridDay' },
      editable: true,
      selectable: true,
      locale: 'zh-cn',
      events: events.value,
      eventClick: (info: { event: { id: string } }) => {
        const id = Number(info.event.id)
        current.value = tasks.value.find((t) => String(t.id) === String(id)) ?? null
        showDrawer.value = true
      },
      eventDrop: async (info: { event: { id: string; start: Date | null; end: Date | null }; revert: () => void }) => {
        const id = Number(info.event.id)
        if (!info.event.start) return
        try {
          await updateTask(id, { planned_start: info.event.start.toISOString(), planned_end: info.event.end?.toISOString() })
          message.success('已更新时间')
          tasksStore.invalidateAll()
          void reloadForce()
        } catch (e: unknown) {
          message.error(extractErrorMessage(e))
          info.revert()
        }
      },
      eventResize: async (info: { event: { id: string; start: Date | null; end: Date | null }; revert: () => void }) => {
        const id = Number(info.event.id)
        if (!info.event.start) return
        try {
          await updateTask(id, { planned_start: info.event.start.toISOString(), planned_end: info.event.end?.toISOString() })
          message.success('已调整时长')
          tasksStore.invalidateAll()
          void reloadForce()
        } catch (e: unknown) {
          message.error(extractErrorMessage(e))
          info.revert()
        }
      },
    }) as unknown as Record<string, unknown>,
)

watch(viewMode, () => {
  const api = calRef.value?.getApi?.()
  if (api) api.changeView(viewMode.value)
})

const cols: DataTableColumns<TaskItem> = [
  { type: 'selection', width: 40 } as unknown as DataTableColumns<TaskItem>[number],
  { title: 'ID', key: 'id', width: 64 },
  { title: '标题', key: 'title' },
  {
    title: '开始',
    key: 'planned_start',
    width: 168,
    render: (r: TaskItem) => new Date(r.planned_start).toLocaleString(),
  },
  {
    title: '结束',
    key: 'planned_end',
    width: 168,
    render: (r: TaskItem) => new Date(r.planned_end).toLocaleString(),
  },
  { title: '优先级', key: 'priority', width: 72 },
  {
    title: '状态',
    key: 'status',
    width: 88,
    render: (r: TaskItem) =>
      h(
        NTag,
        { type: r.status === 'done' ? 'success' : r.status === 'delayed' ? 'error' : 'info', size: 'small', style: 'border-radius:20px' },
        { default: () => r.status },
      ),
  },
  {
    title: '操作',
    key: 'actions',
    width: 150,
    render: (r: TaskItem) =>
      h(NSpace, { size: 6 }, {
        default: () => [
          h(NButton, { size: 'small', style: 'border-radius:20px', onClick: () => { current.value = r; showDrawer.value = true } }, { default: () => '打卡' }),
          h(NButton, { size: 'small', type: 'error', style: 'border-radius:20px', onClick: () => void onDelete(r.id) }, { default: () => '删除' }),
        ],
      }),
  },
]

const planCols: DataTableColumns<PlanLogItem> = [
  { title: 'Agent', key: 'agent_name', width: 110 },
  { title: '输入', key: 'input', render: (r: PlanLogItem) => JSON.stringify(r.input ?? {}).slice(0, 80) },
  { title: '输出', key: 'output', render: (r: PlanLogItem) => JSON.stringify(r.output ?? {}).slice(0, 80) },
  { title: '时间', key: 'created_at', width: 172, render: (r: PlanLogItem) => new Date(r.created_at).toLocaleString() },
]

async function batchComplete(): Promise<void> {
  for (const id of selectedIds.value) {
    try {
      await updateTask(id, { status: 'done' })
    } catch {}
  }
  message.success(`批量完成 ${selectedIds.value.length}`)
  selectedIds.value = []
  tasksStore.invalidateAll()
  void reloadForce()
}
async function batchReschedule(days: number): Promise<void> {
  for (const id of selectedIds.value) {
    const t = tasks.value.find((x) => x.id === id)
    if (!t) continue
    const s = new Date(t.planned_start)
    s.setDate(s.getDate() + days)
    const e = new Date(t.planned_end)
    e.setDate(e.getDate() + days)
    try {
      await updateTask(id, { planned_start: s.toISOString(), planned_end: e.toISOString() })
    } catch {}
  }
  message.success(`批量改期 +${days}天`)
  selectedIds.value = []
  tasksStore.invalidateAll()
  void reloadForce()
}

async function load(_val?: unknown): Promise<void> {
  try {
    await tasksStore.load({ goal_id: goalId.value || undefined, status: statusFilter.value || undefined, page: 1, size: 100 })
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
  }
}
async function reloadForce(): Promise<void> {
  try {
    await tasksStore.load({ goal_id: goalId.value || undefined, status: statusFilter.value || undefined, page: 1, size: 100 }, { force: true })
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
  }
}
async function loadGoals(): Promise<void> {
  try {
    const res = await listGoals({ page: 1, size: 100 })
    goalOpts.value = res.data.items.map((g) => ({ label: `#${g.id} ${g.title}`, value: g.id }))
    if (!batch.value.goal_id && res.data.items[0]) batch.value.goal_id = res.data.items[0].id
  } catch {}
}
async function loadPlan(): Promise<void> {
  if (!traceId.value) return
  loadingPlan.value = true
  try {
    const res = await getPlanLogs(traceId.value)
    planLogs.value = res.data || []
  } catch {
    planLogs.value = []
  } finally {
    loadingPlan.value = false
  }
}
async function doBatch(): Promise<void> {
  batching.value = true
  try {
    const base = new Date()
    base.setHours(9, 0, 0, 0)
    const tasksPayload = Array.from({ length: batch.value.days }, (_, i) => {
      const s = new Date(base)
      s.setDate(base.getDate() + i)
      const e = new Date(s)
      e.setHours(s.getHours() + 1)
      return {
        goal_id: batch.value.goal_id,
        title: `${batch.value.prefix} ${i + 1}`,
        planned_start: s.toISOString(),
        planned_end: e.toISOString(),
        priority: 3 as const,
        status: 'todo' as const,
      }
    })
    await batchCreateTasks(tasksPayload)
    message.success(`已批量创建 ${tasksPayload.length} 条`)
    showBatch.value = false
    tasksStore.invalidateAll()
    void reloadForce()
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
  } finally {
    batching.value = false
  }
}
async function onDelete(id: number): Promise<void> {
  if (!window.confirm('删除任务?')) return
  try {
    await deleteTask(id)
    message.success('已删除')
    tasksStore.invalidateAll()
    void reloadForce()
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
  }
}
onMounted(() => {
  void loadGoals()
  void load()
  if (traceId.value) void loadPlan()
})
</script>

<style scoped>
:deep(.fc-event) { border: none !important; box-shadow: 0 1px 3px rgba(0,0,0,0.08) !important; border-radius: 8px !important; }
:deep(.fc-col-header-cell) { background: #fff !important; border-color: #f5f5f7 !important; }
:deep(.fc-daygrid-day), :deep(.fc-timegrid-col) { border-color: #f5f5f7 !important; }
:deep(.fc-toolbar-title) { font-size: 13px !important; font-weight: 600 !important; letter-spacing: -0.01em !important; color: #1d1d1f !important; }
</style>
