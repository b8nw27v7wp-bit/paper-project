<template>
  <div class="space-y-10">
    <!-- 三端统一 PLANNER_API 反馈闭环：顶部展示 patch.week_load 与 Inspector 跳转 -->
    <n-alert v-if="report" type="info" :show-icon="true" :title="`反馈闭环 · 最新 Patch · ${report.week}`" class="rounded-[12px]">
      <div class="text-[13px] leading-6">
        <span class="font-medium">week_load:</span> {{ patchWeekLoad }}
      </div>
      <div class="mt-2 flex items-center gap-2">
        <n-button size="small" type="primary" style="border-radius: 20px" @click="goInspector">Inspector → 工作台{{ patchTrace ? ' trace=' + patchTrace.slice(0, 8) : '' }}</n-button>
      </div>
    </n-alert>
    <div class="flex items-end justify-between">
      <div>
        <h2 class="text-[20px] font-semibold tracking-[-0.02em] text-ink">周反思</h2>
        <p class="mt-1 text-[11px] tracking-wide text-muted">F11 自进化 · APScheduler 周日23:00 · 完成率/拖延/负荷 · Patch 回注</p>
      </div>
      <n-space :size="8" align="center">
        <n-input v-model:value="weekInput" placeholder="2026-W34" style="width: 132px" clearable />
        <n-button size="small" style="border-radius: 20px" @click="fetchWeek">按周查询</n-button>
        <n-button type="primary" style="border-radius: 20px" :loading="running" @click="runNow">立即生成</n-button>
      </n-space>
    </div>

    <n-grid :cols="4" :x-gap="16">
      <n-gi><n-card class="stat-card" :bordered="false" aria-label="完成率"><div class="text-[11px] tracking-widest font-medium text-muted">完成率</div><div class="mt-2 text-[28px] font-semibold tracking-[-0.03em] text-ink">{{ ((report?.completion_rate ?? 0) * 100).toFixed(1) }}%</div><div class="mt-1 h-1 rounded-full bg-[var(--c-surface)] overflow-hidden"><div class="h-full bg-[var(--c-ink)]" :style="{ width: ((report?.completion_rate ?? 0) * 100).toFixed(1) + '%' }" /></div></n-card></n-gi>
      <n-gi><n-card class="stat-card" :bordered="false" aria-label="拖延率"><div class="text-[11px] tracking-widest font-medium text-muted">拖延率</div><div class="mt-2 text-[28px] font-semibold tracking-[-0.03em] text-ink">{{ ((report?.delay_rate ?? 0) * 100).toFixed(1) }}%</div><div class="mt-1 h-1 rounded-full bg-[var(--c-surface)] overflow-hidden"><div class="h-full bg-[var(--c-muted)]" :style="{ width: ((report?.delay_rate ?? 0) * 100).toFixed(1) + '%' }" /></div></n-card></n-gi>
      <n-gi><n-card class="stat-card" :bordered="false" aria-label="平均负荷"><div class="text-[11px] tracking-widest font-medium text-muted">平均负荷</div><div class="mt-2 text-[28px] font-semibold tracking-[-0.03em] text-ink">{{ (report?.avg_load ?? 0).toFixed(1) }}<span class="text-[14px] font-normal text-muted"> h/天</span></div><div class="mt-1 text-[11px] tracking-wide text-muted">下周 Patch · reduce_load / add_buffer</div></n-card></n-gi>
      <n-gi><n-card class="stat-card" :bordered="false" aria-label="本周专注"><div class="text-[11px] tracking-widest font-medium text-muted">本周专注</div><div v-if="hasFocus" class="mt-2 text-[28px] font-semibold tracking-[-0.03em] text-ink">{{ focusHours }}<span class="text-[14px] font-normal text-muted"> 小时</span></div><div v-else class="mt-2 text-[11px] leading-5 tracking-wide text-muted">暂无专注记录，去任务抽屉记一个番茄</div><div v-if="!hasFocus" class="mt-2"><n-button size="small" style="border-radius: 20px" @click="goCalendar">去日历</n-button></div></n-card></n-gi>
    </n-grid>

    <n-card class="apple-card print-report" :bordered="false" content-style="padding: 24px;">
      <template #header>
        <div class="flex items-center justify-between w-full">
          <span class="text-[13px] font-semibold tracking-[-0.01em] text-ink">最新反思 · {{ report?.week ?? '—' }}</span>
          <n-space :size="8">
            <n-dropdown :options="exportOpts" @select="handleExport">
              <n-button size="small" style="border-radius: 20px">导出</n-button>
            </n-dropdown>
            <n-button size="small" style="border-radius: 20px" :loading="loading" @click="loadLatest">刷新</n-button>
            <span class="text-[11px] tracking-wide text-muted">{{ report?.created_at ? new Date(String(report.created_at)).toLocaleString() : '' }}</span>
          </n-space>
        </div>
      </template>
      <n-skeleton v-if="loading && !report" text :repeat="3" :sharp="false" />
      <n-alert v-else-if="loadError" title="加载失败，请重试" type="error" :show-icon="false" class="rounded-[12px]">
        <span class="text-[13px] tracking-[-0.01em]">反思加载失败：{{ loadError }}</span>
        <div class="mt-2">
          <n-button size="small" style="border-radius: 20px" :loading="loading" @click="loadLatest">重试</n-button>
        </div>
      </n-alert>
      <n-spin v-else :show="loading">
        <div v-if="report" class="space-y-4">
          <div class="rounded-[16px] bg-[var(--c-surface)] p-4">
            <div class="text-[11px] tracking-widest font-medium text-muted">ANALYSIS</div>
            <div class="mt-2 text-[13px] leading-6 tracking-[-0.01em] text-ink whitespace-pre-wrap">{{ report.analysis || '—' }}</div>
          </div>
          <div class="rounded-[16px] bg-[var(--c-bg)] p-4" style="box-shadow: 0 1px 3px rgba(0,0,0,0.04)">
            <div class="text-[11px] tracking-widest font-medium text-muted">NEXT_PLAN_PATCH</div>
            <n-code :code="JSON.stringify(report.next_plan_patch ?? {}, null, 2)" language="json" class="mt-2" />
          </div>
          <div class="text-[11px] tracking-wide text-muted">下周 Planner 将自动合并 patch · reduce_load 与 add_buffer 已在 prompt 中注入</div>
        </div>
        <n-empty v-else description="暂无反思报告，点击立即生成" class="py-10">
          <template #extra>
            <n-button size="small" type="primary" style="border-radius: 20px" :loading="running" @click="runNow">立即生成</n-button>
          </template>
        </n-empty>
      </n-spin>
    </n-card>

    <n-card class="apple-card" :bordered="false" content-style="padding: 0 24px 24px 24px;">
      <template #header>
        <div class="flex items-center justify-between w-full">
          <span class="text-[13px] font-semibold tracking-[-0.01em] text-ink">历史 · 按周</span>
          <n-button size="small" style="border-radius: 20px" @click="loadLatest">刷新最新</n-button>
        </div>
      </template>
      <div v-if="history.length" class="table-scroll table-scroll--narrow">
        <n-data-table
          :columns="cols"
          :data="history"
          :pagination="false"
          size="small"
          :bordered="false"
          :single-line="false"
          :row-key="(r: ReflectionReport) => r.week"
        />
      </div>
      <n-empty v-else description="暂无历史反思，点击立即生成" class="py-10">
        <template #extra>
          <n-button size="small" style="border-radius: 20px" :loading="running" @click="runNow">立即生成</n-button>
        </template>
      </n-empty>
      <div v-if="history.length" class="mt-6 flex justify-between items-center">
        <span class="text-[11px] tracking-wide text-muted">周维度聚合 · task_execution_log 7日趋势</span>
        <n-button size="small" style="border-radius: 20px" @click="loadLatest">刷新最新</n-button>
      </div>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref, h, onMounted, computed } from 'vue'
defineOptions({ name: 'ReflectionView' })
import { useRouter } from 'vue-router'
import { NCard, NSpace, NButton, NInput, NGrid, NGi, NDataTable, NCode, NSpin, NEmpty, NAlert, NSkeleton, NDropdown, useMessage, type DataTableColumns } from 'naive-ui'
import { fetchLatestReflection, fetchWeekReflection, runReflection, type ReflectionReport } from '@/api/reflection'
import { fetchStatsOverview } from '@/api/stats'
import type { StatsOverview } from '@/types'
import { extractErrorMessage } from '@/api/client'

const router = useRouter()
const message = useMessage()
const report = ref<ReflectionReport | null>(null)
const history = ref<ReflectionReport[]>([])
const loading = ref<boolean>(false)
const running = ref<boolean>(false)
const loadError = ref<string>('')
const weekInput = ref<string>('')

type OverviewWithFocus = StatsOverview & { focus_seconds?: number }
const focusOverview = ref<OverviewWithFocus>({ completion_rate: 0, delay_rate: 0, avg_load: 0, llm_cost: 0 })
const focusHours = computed<string>(() => (((focusOverview.value.focus_seconds ?? 0) / 3600).toFixed(1)))
const hasFocus = computed<boolean>(() => (focusOverview.value.focus_seconds ?? 0) > 0)

async function loadFocus(): Promise<void> {
  try {
    const res = await fetchStatsOverview('7d')
    focusOverview.value = res.data as OverviewWithFocus
  } catch {}
}

function goCalendar(): void {
  try { void router.push('/calendar') } catch {}
}

const exportOpts = [
  { label: '复制 Markdown', key: 'copy' },
  { label: '下载 Markdown 文件', key: 'download' },
  { label: '打印报告', key: 'print' },
]

function buildMarkdown(): string {
  const r = report.value
  if (!r) return ''
  const lines: string[] = []
  lines.push(`# 周反思 ${r.week}`)
  lines.push('')
  lines.push(`- 完成率：${(r.completion_rate * 100).toFixed(1)}%`)
  lines.push(`- 拖延率：${(r.delay_rate * 100).toFixed(1)}%`)
  lines.push(`- 平均负荷：${r.avg_load.toFixed(1)} 小时每天`)
  lines.push('')
  lines.push('## 分析')
  lines.push('')
  lines.push(r.analysis || '暂无分析')
  lines.push('')
  lines.push('## 下周计划补丁')
  lines.push('')
  lines.push('```json')
  lines.push(JSON.stringify(r.next_plan_patch ?? {}, null, 2))
  lines.push('```')
  return lines.join('\n')
}

async function handleExport(key: string | number): Promise<void> {
  if (!report.value) { message.warning('暂无反思报告，先生成一份'); return }
  if (key === 'copy') {
    const md = buildMarkdown()
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(md)
      } else {
        const ta = document.createElement('textarea')
        ta.value = md
        document.body.appendChild(ta)
        ta.select()
        document.execCommand('copy')
        document.body.removeChild(ta)
      }
      message.success('已复制 Markdown')
    } catch {
      message.error('复制失败，请重试')
    }
    return
  }
  if (key === 'download') {
    try {
      const md = buildMarkdown()
      const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `周反思-${report.value.week}.md`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      message.success('已下载 Markdown 文件')
    } catch {
      message.error('下载失败，请重试')
    }
    return
  }
  if (key === 'print') {
    try { window.print() } catch {}
  }
}

// 三端统一 PLANNER_API 反馈闭环：展示 patch.week_load 与 Inspector 跳转
const patchWeekLoad = computed<string>(() => {
  const patch = (report.value?.next_plan_patch || {}) as Record<string, unknown>
  const wl = patch.week_load as Record<string, number> | undefined
  if (wl && typeof wl === 'object' && !Array.isArray(wl) && Object.keys(wl).length) {
    return JSON.stringify(wl)
  }
  // 兼容 daily_load 或完整 patch
  if (Object.keys(patch).length) return JSON.stringify(patch).slice(0, 160)
  return '—'
})
const patchTrace = computed<string | undefined>(() => {
  const patch = (report.value?.next_plan_patch || {}) as Record<string, unknown>
  const t = (patch.trace ?? patch.trace_id) as string | undefined
  return typeof t === 'string' && t.length ? t : undefined
})
function goInspector(): void {
  const t = patchTrace.value
  if (t) void router.push('/agent?trace=' + t)
  else void router.push('/agent')
}

const cols: DataTableColumns<ReflectionReport> = [
  { title: '周', key: 'week', width: 120 },
  { title: '完成率', key: 'completion_rate', width: 96, render: (r: ReflectionReport) => h('span', { class: 'text-[13px] font-medium text-ink' }, (r.completion_rate * 100).toFixed(1) + '%') },
  { title: '拖延率', key: 'delay_rate', width: 96, render: (r: ReflectionReport) => (r.delay_rate * 100).toFixed(1) + '%' },
  { title: '负荷', key: 'avg_load', width: 88, render: (r: ReflectionReport) => r.avg_load.toFixed(1) + 'h' },
  { title: 'Analysis', key: 'analysis', ellipsis: { tooltip: true } as const, render: (r: ReflectionReport) => String(r.analysis).slice(0, 80) },
  { title: '时间', key: 'created_at', width: 172, render: (r: ReflectionReport) => r.created_at ? new Date(String(r.created_at)).toLocaleString() : '—' },
]

async function loadLatest(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const res = await fetchLatestReflection()
    report.value = res.data as ReflectionReport
    // 推入历史去重
    const idx = history.value.findIndex(x => x.week === report.value?.week)
    if (report.value) {
      if (idx >= 0) history.value[idx] = report.value
      else history.value = [report.value, ...history.value].slice(0, 10)
    }
  } catch (e: unknown) {
    const msg = extractErrorMessage(e)
    if (msg.includes('404') || msg.includes('暂无')) {
      report.value = null
    } else {
      loadError.value = msg
      message.error(msg)
    }
  } finally {
    loading.value = false
  }
}
async function fetchWeek(): Promise<void> {
  if (!weekInput.value.trim()) { message.warning('请输入周 如 2026-W34'); return }
  loading.value = true
  loadError.value = ''
  try {
    const res = await fetchWeekReflection(weekInput.value.trim())
    report.value = res.data as ReflectionReport
    message.success('已加载 ' + weekInput.value)
  } catch (e: unknown) {
    const msg = extractErrorMessage(e)
    loadError.value = msg
    message.error(msg)
  } finally {
    loading.value = false
  }
}
async function runNow(): Promise<void> {
  running.value = true
  loadError.value = ''
  try {
    const res = await runReflection(weekInput.value.trim() || undefined)
    report.value = res.data as ReflectionReport
    const idx = history.value.findIndex(x => x.week === report.value?.week)
    if (report.value) {
      if (idx >= 0) history.value[idx] = report.value
      else history.value = [report.value, ...history.value].slice(0, 10)
    }
    message.success('已生成反思 ' + (report.value.week ?? ''))
  } catch (e: unknown) {
    const msg = extractErrorMessage(e)
    loadError.value = msg
    message.error(msg)
  } finally {
    running.value = false
  }
}
onMounted(() => { void loadLatest(); void loadFocus() })
</script>
