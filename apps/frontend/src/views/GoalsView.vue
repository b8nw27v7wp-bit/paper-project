<template>
  <div class="space-y-10">
    <div class="flex items-end justify-between">
      <div>
        <h2 class="text-[20px] font-semibold tracking-[-0.02em] text-ink">目标</h2>
        <p class="mt-1 text-[11px] tracking-wide text-muted">F01 目标 · F02 智能规划 · 批量导入 · 看板</p>
      </div>
      <n-space :size="8" align="center">
        <n-input v-model:value="keyword" placeholder="搜索标题/科目" clearable style="width: 168px" @update:value="onSearch" />
        <n-select v-model:value="filterStatus" :options="statusOpts" style="width: 132px" placeholder="状态" clearable @update:value="onStatus" />
        <n-select v-model:value="subjectFilter" :options="subjectOpts" style="width: 132px" placeholder="科目" clearable @update:value="onSearch" />
        <button
          :class="capsuleClass(boardMode)"
          @click="boardMode = !boardMode"
        >
          {{ boardMode ? '列表' : '看板' }}
        </button>
        <button class="px-3.5 py-1.5 text-[13px] font-medium rounded-full bg-[var(--c-surface)] text-ink hover:bg-[var(--c-border)] transition-colors" @click="showImport = true">批量导入</button>
        <button class="px-4 py-1.5 text-[13px] font-medium rounded-full bg-[var(--c-ink)] text-white hover:bg-[var(--c-ink-hover)] transition-colors" @click="openCreate">新建目标</button>
      </n-space>
    </div>

    <n-grid v-if="boardMode" :cols="2" :x-gap="24">
      <n-gi>
        <n-card class="apple-card" :bordered="false" title="进行中" content-style="padding: 24px;">
          <div class="space-y-3">
            <div v-for="g in activeItems" :key="g.id" class="rounded-[16px] bg-[var(--c-surface)] p-4">
              <div class="text-[13px] font-semibold tracking-[-0.01em] text-ink">{{ g.title }}</div>
              <div class="text-[11px] tracking-wide text-muted mt-1">{{ g.subject || '—' }} · {{ fmtDate(g.deadline) }}</div>
              <n-space class="mt-3" :size="6">
                <n-button size="tiny" type="primary" style="border-radius: 20px" @click="openPlan(g)">规划</n-button>
                <n-button size="tiny" style="border-radius: 20px" @click="openEdit(g)">编辑</n-button>
                <n-button size="tiny" style="border-radius: 20px" @click="toggleArchived(g)">归档</n-button>
              </n-space>
            </div>
            <n-empty v-if="!activeItems.length" description="暂无目标，新建一个" class="py-8">
              <template #extra>
                <n-button size="small" style="border-radius: 20px" @click="openCreate">新建目标</n-button>
              </template>
            </n-empty>
          </div>
        </n-card>
      </n-gi>
      <n-gi>
        <n-card class="apple-card" :bordered="false" title="已归档" content-style="padding: 24px;">
          <div class="space-y-3">
            <div v-for="g in archivedItems" :key="g.id" class="rounded-[16px] bg-[var(--c-surface)] p-4">
              <div class="text-[13px] font-medium tracking-[-0.01em] text-ink">{{ g.title }}</div>
              <div class="text-[11px] tracking-wide text-muted mt-1">{{ fmtDate(g.deadline) }}</div>
              <n-space class="mt-3" :size="6">
                <n-button size="tiny" style="border-radius: 20px" @click="toggleArchived(g)">激活</n-button>
                <n-button size="tiny" type="error" style="border-radius: 20px" @click="remove(g)">删除</n-button>
              </n-space>
            </div>
            <n-empty v-if="!archivedItems.length" description="暂无归档" class="py-8" />
          </div>
        </n-card>
      </n-gi>
    </n-grid>

    <n-card v-else class="apple-card" :bordered="false" content-style="padding: 0 24px 24px 24px;" aria-label="目标列表">
      <n-skeleton v-if="loading && !filtered.length" text :repeat="4" :sharp="false" class="mt-4" />
      <div v-else-if="filtered.length" class="table-scroll">
        <n-data-table
          :columns="columns"
          :data="filtered"
          :pagination="false"
          :loading="loading"
          :row-key="(r: GoalItem) => r.id"
          :bordered="false"
          :single-line="false"
          size="small"
          class="goals-table"
        />
      </div>
      <n-empty v-else-if="!loading" description="暂无目标，新建一个" class="py-10">
        <template #extra>
          <n-button size="small" type="primary" style="border-radius: 20px" @click="openCreate">新建目标</n-button>
        </template>
      </n-empty>
      <div v-if="filtered.length" class="flex justify-end items-center mt-8 pt-4">
        <span class="text-[11px] tracking-wide text-muted mr-4">{{ total }} 条 · 第 {{ page }} 页</span>
        <n-pagination
          v-model:page="page"
          :page-size="size"
          :item-count="total"
          :page-sizes="[10, 20, 50]"
          show-size-picker
          @update:page="load"
          @update:page-size="onSize"
        />
      </div>
    </n-card>

    <n-modal v-model:show="showModal" preset="card" :title="editing ? '编辑目标' : '新建目标'" style="width: 640px; border-radius: 16px">
      <GoalForm ref="formRef" :value="form" @update:value="form = $event" />
      <template #footer>
        <n-space justify="end" :size="8">
          <button class="px-4 py-1.5 text-[13px] font-medium rounded-full bg-[var(--c-surface)] text-ink" @click="showModal = false">取消</button>
          <button class="px-4 py-1.5 text-[13px] font-medium rounded-full bg-[var(--c-ink)] text-white disabled:opacity-50" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showImport" preset="card" title="批量导入 CSV" style="width: 640px; border-radius: 16px">
      <div class="space-y-3">
        <div class="text-[12px] leading-5 text-muted">格式: title,description,deadline(ISO),subject  每行一条，逗号分隔 · deadline 需 &gt; now+1天</div>
        <n-input v-model:value="csvText" type="textarea" placeholder="30天过六级,冲刺六级,2026-09-20T00:00:00Z,英语" :autosize="{ minRows: 4 }" />
        <n-alert v-if="importErr" type="error" :show-icon="false" class="text-[12px]">{{ importErr }}</n-alert>
        <div class="text-[11px] tracking-wide text-muted">示例已填 2 行预览 · 将逐条 POST /goals · 失败自动计数</div>
      </div>
      <template #footer>
        <n-space justify="end" :size="8">
          <n-button @click="showImport = false" style="border-radius: 20px">取消</n-button>
          <n-button @click="fillDemo" style="border-radius: 20px">填示例</n-button>
          <n-button type="primary" :loading="importing" style="border-radius: 20px" @click="doImport">导入</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showPlan" preset="card" title="智能规划 · SSE" style="width: 720px; border-radius: 16px">
      <n-space vertical :size="12">
        <n-card size="small" v-if="planGoal" style="border-radius: 12px; background: var(--c-surface); border: none">
          目标: {{ planGoal.title }} ({{ planGoal ? fmtDate(planGoal.deadline) : '' }}) · {{ planGoal.subject || '—' }}
        </n-card>
        <n-form label-placement="left" label-width="100" size="small">
          <n-form-item label="每日时长"><n-input-number v-model:value="planHours" :min="1" :max="8" /> 小时</n-form-item>
          <n-form-item label="规划模式">
            <div class="flex rounded-full border border-hairline bg-surface/50 p-0.5" role="radiogroup" aria-label="规划模式">
              <button
                :class="['px-3 py-1 text-[11px] rounded-full transition-colors', planMode === 'single' ? 'bg-ink text-white' : 'text-muted hover:text-ink']"
                role="radio"
                :aria-checked="planMode === 'single'"
                @click="planMode = 'single'"
              >单智能体</button>
              <button
                :class="['px-3 py-1 text-[11px] rounded-full transition-colors', planMode === 'multi' ? 'bg-ink text-white' : 'text-muted hover:text-ink']"
                role="radio"
                :aria-checked="planMode === 'multi'"
                @click="planMode = 'multi'"
              >多智能体</button>
            </div>
          </n-form-item>
        </n-form>
        <n-button type="primary" :loading="planning" style="border-radius: 20px" @click="doPlan" v-if="!traceId">开始生成</n-button>
        <PlanStream v-if="traceId" :trace-id="traceId" :mentor="mentorMsg" :citations="planCitations" @done="onPlanDone" />
      </n-space>
      <template #footer>
        <n-space justify="end" :size="8">
          <n-button @click="showPlan = false" style="border-radius: 20px">关闭</n-button>
          <n-button type="primary" style="border-radius: 20px" @click="goCalendar" v-if="traceId">查看日历</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'GoalsView' })
import { ref, h, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useGoalsStore } from '@/stores/goals'
import {
  NCard,
  NSpace,
  NButton,
  NSelect,
  NDataTable,
  NPagination,
  NModal,
  useMessage,
  NTag,
  NForm,
  NFormItem,
  NInputNumber,
  NInput,
  NAlert,
  NGrid,
  NGi,
  NEmpty,
  NDropdown,
  NSkeleton,
} from 'naive-ui'
import GoalForm from '@/components/GoalForm.vue'
import PlanStream from '@/components/PlanStream.vue'
import { createGoal, updateGoal, deleteGoal, getGoal } from '@/api/goals'
import { createPlan } from '@/api/plans'
import type { GoalItem, GoalCreatePayload } from '@/types'
import { extractErrorMessage } from '@/api/client'

const router = useRouter()
const message = useMessage()
const goalsStore = useGoalsStore()
// 保持模板兼容：对外仍暴露 items/total/loading 但由 store 驱动
const items = computed(() => goalsStore.items)
const total = computed(() => goalsStore.total)
const page = ref(1)
const size = ref(20)
const loading = computed(() => goalsStore.loading)
const filterStatus = ref<string | null>(null)
const keyword = ref('')
const subjectFilter = ref<string | null>(null)
const boardMode = ref(false)
const showImport = ref(false)
const csvText = ref('')
const importErr = ref('')
const importing = ref(false)
const statusOpts = [
  { label: '进行中', value: 'active' },
  { label: '已归档', value: 'archived' },
]

function fmtDate(v: string): string {
  try {
    return new Date(v).toLocaleDateString()
  } catch {
    return String(v).slice(0, 10)
  }
}

function capsuleClass(active: boolean): string {
  return active
    ? 'px-3.5 py-1.5 text-[13px] font-medium rounded-full bg-[var(--c-ink)] text-white transition-colors'
    : 'px-3.5 py-1.5 text-[13px] font-medium rounded-full bg-[var(--c-surface)] text-muted hover:text-ink transition-colors'
}

const subjectOpts = computed(() => {
  const s = new Set(items.value.map((x) => x.subject).filter((v): v is string => Boolean(v)))
  return Array.from(s).map((v) => ({ label: v, value: v }))
})
const filtered = computed(() =>
  items.value.filter((g) => {
    if (keyword.value && !`${g.title}${g.subject ?? ''}`.includes(keyword.value)) return false
    if (subjectFilter.value && g.subject !== subjectFilter.value) return false
    return true
  }),
)
const activeItems = computed(() => filtered.value.filter((g) => g.status === 'active'))
const archivedItems = computed(() => filtered.value.filter((g) => g.status === 'archived'))
function onSearch(): void {
  /* computed 自动过滤，配合大留白与即时搜索 */
}

const showModal = ref(false)
const editing = ref<GoalItem | null>(null)
const form = ref<{ title: string; description: string; deadline: number | null; subject: string; status: 'active' | 'archived' }>({
  title: '',
  description: '',
  deadline: null,
  subject: '',
  status: 'active',
})
const formRef = ref<{ validate: () => Promise<void> } | null>(null)
const saving = ref(false)

const showPlan = ref(false)
const planGoal = ref<GoalItem | null>(null)
const planHours = ref(4)
const planMode = ref<'single' | 'multi'>('multi')
const traceId = ref<string | null>(null)
const mentorMsg = ref('')
const planCitations = ref<unknown[]>([])
const planning = ref(false)

const columns = [
  { title: 'ID', key: 'id', width: 64 },
  { title: '标题', key: 'title', ellipsis: { tooltip: true } as const },
  { title: '科目', key: 'subject', width: 96 },
  {
    title: '截止',
    key: 'deadline',
    width: 132,
    render: (r: GoalItem) => fmtDate(r.deadline),
  },
  {
    title: '状态',
    key: 'status',
    width: 88,
    render: (r: GoalItem) =>
      h(
        NTag,
        { type: r.status === 'active' ? 'success' : 'warning', size: 'small', style: 'border-radius: 20px; font-size: 11px' },
        { default: () => r.status },
      ),
  },
  {
    title: '操作',
    key: 'actions',
    width: 200,
    render: (r: GoalItem) =>
      h(NSpace, { size: 6, align: 'center' }, {
        default: () => [
          h(NButton, { size: 'small', type: 'primary', style: 'border-radius:20px', onClick: () => openPlan(r) }, { default: () => '规划' }),
          h(NButton, { size: 'small', style: 'border-radius:20px', onClick: () => viewTasks(r) }, { default: () => '任务' }),
          h(
            NDropdown,
            {
              trigger: 'click',
              options: [
                { label: '编辑', key: 'edit' },
                { label: r.status === 'active' ? '归档' : '激活', key: 'archive' },
                { label: '删除', key: 'del' },
              ],
              onSelect: (k: string) => {
                if (k === 'edit') void openEdit(r)
                else if (k === 'archive') void toggleArchived(r)
                else if (k === 'del') void remove(r)
              },
            },
            { default: () => h(NButton, { size: 'small', style: 'border-radius:20px' }, { default: () => '···' }) },
          ),
        ],
      }),
  },
]

function openPlan(row: GoalItem): void {
  planGoal.value = row
  planHours.value = 4
  planMode.value = 'multi'
  traceId.value = null
  mentorMsg.value = ''
  planCitations.value = []
  showPlan.value = true
}
async function doPlan(): Promise<void> {
  if (!planGoal.value) return
  planning.value = true
  try {
    const res = await createPlan(planGoal.value.id, { hours_per_day: planHours.value }, planMode.value)
    traceId.value = res.data.trace_id
    mentorMsg.value = res.data.mentor_msg ?? ''
    planCitations.value = (res.data.citations as unknown[] ?? []) as unknown[]
    message.success(`已生成 ${res.data.tasks.length} 任务`)
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
  } finally {
    planning.value = false
  }
}
function onPlanDone(): void {
  void load()
}
function goCalendar(): void {
  showPlan.value = false
  if (planGoal.value) router.push(`/calendar?goal_id=${planGoal.value.id}`)
}

async function load(_page?: number | unknown): Promise<void> {
  // 兼容分页回调传 number，忽略参数走 store
  try {
    const res = await goalsStore.load({ status: filterStatus.value || undefined, page: page.value, size: size.value })
    await clampPage(res.total)
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
  }
}
async function reloadForce(): Promise<void> {
  try {
    const res = await goalsStore.load({ status: filterStatus.value || undefined, page: page.value, size: size.value }, { force: true })
    await clampPage(res.total)
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
  }
}
// 分页越界钳制：筛选/删除后总数收缩导致当前页落空时，回退到末页并补拉一次
async function clampPage(total: number): Promise<void> {
  const maxP = Math.max(1, Math.ceil(total / size.value))
  if (page.value > maxP) {
    page.value = maxP
    await goalsStore.load({ status: filterStatus.value || undefined, page: page.value, size: size.value }, { force: true })
  }
}
function onStatus(): void {
  page.value = 1
  void load()
}
function onSize(v: number): void {
  size.value = v
  page.value = 1
  void load()
}

function openCreate(): void {
  editing.value = null
  form.value = { title: '', description: '', deadline: Date.now() + 2 * 86400000, subject: '', status: 'active' }
  showModal.value = true
}
async function openEdit(row: GoalItem): Promise<void> {
  try {
    const res = await getGoal(row.id)
    const g = res.data
    editing.value = g
    form.value = {
      title: g.title,
      description: g.description ?? '',
      deadline: new Date(g.deadline).getTime(),
      subject: g.subject ?? '',
      status: g.status,
    }
    showModal.value = true
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
  }
}
async function toggleArchived(row: GoalItem): Promise<void> {
  try {
    await updateGoal(row.id, { status: row.status === 'active' ? 'archived' : 'active' })
    message.success('已更新')
    goalsStore.invalidate()
    void reloadForce()
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
  }
}
async function remove(row: GoalItem): Promise<void> {
  if (!window.confirm(`删除目标 ${row.title} ?`)) return
  try {
    await deleteGoal(row.id)
    message.success('已删除')
    goalsStore.invalidate()
    void reloadForce()
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
  }
}
function viewTasks(row: GoalItem): void {
  router.push(`/calendar?goal_id=${row.id}`)
}
function fillDemo(): void {
  csvText.value = `30天过六级,冲刺六级,${new Date(Date.now() + 5 * 86400000).toISOString()},英语\n数据结构刷题,图与树,${new Date(Date.now() + 7 * 86400000).toISOString()},数据结构`
}
async function doImport(): Promise<void> {
  importErr.value = ''
  const lines = csvText.value.trim().split('\n').filter(Boolean)
  if (!lines.length) {
    importErr.value = '请输入至少一行'
    return
  }
  importing.value = true
  let ok = 0
  let fail = 0
  for (const line of lines) {
    const [title, desc, deadline, subject] = line.split(',').map((s) => s?.trim())
    if (!title || !deadline) {
      fail++
      continue
    }
    const payload: GoalCreatePayload = { title, description: desc, deadline, subject, status: 'active' }
    try {
      await createGoal(payload)
      ok++
    } catch {
      fail++
    }
  }
  importing.value = false
  message.success(`导入完成 成功${ok} 失败${fail}`)
  if (ok) {
    showImport.value = false
    csvText.value = ''
    goalsStore.invalidate()
    void reloadForce()
  } else importErr.value = `全部失败，请检查 deadline 需 > now+1天`
}
async function save(): Promise<void> {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  saving.value = true
  try {
    const payload: Record<string, unknown> = { ...form.value }
    if (typeof payload.deadline === 'number') payload.deadline = new Date(payload.deadline as number).toISOString()
    if (editing.value) {
      await updateGoal(editing.value.id, payload as Partial<GoalCreatePayload>)
      message.success('已更新')
    } else {
      await createGoal(payload as unknown as GoalCreatePayload)
      message.success('已创建')
    }
    showModal.value = false
    goalsStore.invalidate()
    void reloadForce()
  } catch (e: unknown) {
    const maybe = e as Record<string, unknown>
    const nested = (maybe as Record<string, unknown>)?.response as Record<string, unknown> | undefined
    const data = nested?.data as Record<string, unknown> | undefined
    const inner = (data?.data as Record<string, unknown> | undefined)?.errors as Array<{ msg: string }> | undefined
    const msg = inner?.[0]?.msg || extractErrorMessage(e)
    message.error(msg)
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<style scoped>
.goals-table :deep(.n-data-table__pagination) { margin-top: 32px; }
.goals-table :deep(.n-data-table-thead th) { background: var(--c-bg) !important; font-size: 11px; letter-spacing: 0.08em; color: var(--c-muted); font-weight: 510; border-bottom: 1px solid var(--c-hairline) !important; }
.goals-table :deep(.n-data-table-td) { border-bottom: 1px solid var(--c-hairline) !important; font-size: 13px; }
</style>
