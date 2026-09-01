<template>
  <div class="space-y-10">
    <div class="flex items-end justify-between">
      <div>
        <h2 class="text-[24px] font-semibold tracking-[-0.02em] text-ink">批量任务</h2>
        <p class="mt-1 text-[13px] tracking-[-0.01em] text-muted">批量创建 / 编辑 / 校验 · 一次提交多任务 — 大留白</p>
      </div>
      <n-space :size="8">
        <n-select v-model:value="goalId" :options="goalOpts" placeholder="目标" style="width: 180px" />
        <n-button strong secondary style="border-radius: 20px" @click="addRow">新增行</n-button>
        <n-button style="border-radius: 20px" @click="validate">校验</n-button>
        <n-button type="primary" style="border-radius: 20px" :loading="saving" @click="submit">提交 {{ rows.length }} 条</n-button>
      </n-space>
    </div>

    <n-card class="apple-card" content-style="padding: 32px;">
      <n-alert v-if="errors.length" type="error" class="mb-4" :show-icon="false">
        <div class="text-[12px] leading-5" v-for="(e, i) in errors" :key="i">• {{ e }}</div>
      </n-alert>
      <n-data-table :columns="cols" :data="rows" :pagination="false" size="small" :bordered="false" :row-key="(r: Row) => r._k" />
      <div class="flex justify-between mt-6">
        <n-space :size="8">
          <n-button size="small" style="border-radius: 20px" @click="pasteDemo">填示例</n-button>
          <n-button size="small" style="border-radius: 20px" @click="clearAll">清空</n-button>
        </n-space>
        <span class="text-[11px] tracking-wide text-muted self-center">拖拽表头可排序 · 校验后提交 · 无框表格</span>
      </div>
    </n-card>

    <n-card class="apple-card" title="CSV 粘贴导入" content-style="padding: 32px;">
      <n-input v-model:value="csv" type="textarea" placeholder="title,planned_start,planned_end,priority&#10;背单词,2026-08-26T09:00:00Z,2026-08-26T10:00:00Z,3" :autosize="{ minRows: 3 }" />
      <n-button class="mt-3" size="small" style="border-radius: 20px" @click="importCsv">解析并追加</n-button>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref, h, onMounted } from 'vue'
import { NCard, NSpace, NButton, NSelect, NDataTable, NInput, NAlert, NInputNumber, useMessage, type DataTableColumns } from 'naive-ui'
import { batchCreateTasks } from '@/api/tasks'
import { listGoals } from '@/api/goals'
import type { TaskCreatePayload } from '@/types'
import { extractErrorMessage } from '@/api/client'

interface Row {
  _k: number
  title: string
  planned_start: string
  planned_end: string
  priority: number
}

const message = useMessage()
const goalId = ref<number | null>(null)
const goalOpts = ref<Array<{ label: string; value: number }>>([])
const rows = ref<Row[]>([{ _k: Date.now(), title: '', planned_start: new Date().toISOString().slice(0, 16), planned_end: new Date(Date.now() + 3600000).toISOString().slice(0, 16), priority: 3 }])
const errors = ref<string[]>([])
const saving = ref(false)
const csv = ref('')

function addRow(): void {
  rows.value = [...rows.value, { _k: Date.now() + Math.random(), title: '', planned_start: new Date().toISOString().slice(0, 16), planned_end: new Date(Date.now() + 3600000).toISOString().slice(0, 16), priority: 3 }]
}
function clearAll(): void {
  rows.value = []
  errors.value = []
}
function pasteDemo(): void {
  rows.value = [
    { _k: 1, title: '背单词 Day1', planned_start: '2026-08-26T09:00', planned_end: '2026-08-26T10:00', priority: 3 },
    { _k: 2, title: '背单词 Day2', planned_start: '2026-08-27T09:00', planned_end: '2026-08-27T10:00', priority: 3 },
  ]
}
function importCsv(): void {
  const lines = csv.value.trim().split('\n').filter(Boolean)
  if (!lines.length) return
  const header = lines[0].toLowerCase().includes('title') ? 1 : 0
  for (let i = header; i < lines.length; i++) {
    const [title, s, e, p] = lines[i].split(',')
    rows.value.push({ _k: Date.now() + i, title: (title || '').trim(), planned_start: (s || '').trim(), planned_end: (e || '').trim(), priority: Number(p) || 3 })
  }
  message.success(`已追加 ${lines.length - header} 行`)
}
function validate(): boolean {
  const errs: string[] = []
  if (!goalId.value) errs.push('请选择目标')
  rows.value.forEach((r, i) => {
    if (!r.title?.trim()) errs.push(`行${i + 1}: 标题为空`)
    const s = new Date(r.planned_start)
    const e = new Date(r.planned_end)
    if (isNaN(s.getTime()) || isNaN(e.getTime())) errs.push(`行${i + 1}: 时间格式错误`)
    else if (e <= s) errs.push(`行${i + 1}: 结束需大于开始`)
    if (r.priority < 1 || r.priority > 5) errs.push(`行${i + 1}: 优先级1-5`)
  })
  errors.value = errs
  if (!errs.length) message.success('校验通过')
  return errs.length === 0
}
async function submit(): Promise<void> {
  if (!validate()) return
  saving.value = true
  try {
    const gid = goalId.value as number
    const payload: TaskCreatePayload[] = rows.value.map((r) => ({
      goal_id: gid,
      title: r.title.trim(),
      planned_start: new Date(r.planned_start).toISOString(),
      planned_end: new Date(r.planned_end).toISOString(),
      priority: r.priority as TaskCreatePayload['priority'],
      status: 'todo',
    }))
    await batchCreateTasks(payload)
    message.success(`已创建 ${payload.length} 条`)
    rows.value = []
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
  } finally {
    saving.value = false
  }
}
const cols: DataTableColumns<Row> = [
  { title: '标题', key: 'title', render: (r: Row) => h(NInput, { value: r.title, placeholder: '任务标题', size: 'small', onUpdateValue: (v: string) => (r.title = v) }) },
  { title: '开始', key: 'planned_start', width: 190, render: (r: Row) => h(NInput, { value: r.planned_start, size: 'small', placeholder: '2026-08-26T09:00', onUpdateValue: (v: string) => (r.planned_start = v) }) },
  { title: '结束', key: 'planned_end', width: 190, render: (r: Row) => h(NInput, { value: r.planned_end, size: 'small', onUpdateValue: (v: string) => (r.planned_end = v) }) },
  { title: '优先级', key: 'priority', width: 110, render: (r: Row) => h(NInputNumber, { value: r.priority, min: 1, max: 5, size: 'small', onUpdateValue: (v: number | null) => (r.priority = v || 3) }) },
  { title: '操作', key: 'act', width: 80, render: (r: Row) => h(NButton, { size: 'tiny', type: 'error', style: 'border-radius:20px', onClick: () => (rows.value = rows.value.filter((x) => x._k !== r._k)) }, { default: () => '删除' }) },
]
onMounted(() => {
  void (async () => {
    try {
      const g = await listGoals({ page: 1, size: 100 })
      goalOpts.value = g.data.items.map((x) => ({ label: `#${x.id} ${x.title}`, value: x.id }))
      if (g.data.items[0]) goalId.value = g.data.items[0].id
    } catch {}
  })()
})
</script>
