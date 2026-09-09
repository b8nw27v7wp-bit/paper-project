<template>
  <div class="space-y-10">
    <div class="flex items-end justify-between">
      <div>
        <h2 class="text-[20px] font-semibold tracking-[-0.02em] text-ink">大屏</h2>
        <p class="mt-1 text-[11px] tracking-wide text-muted">P3 评估 · 完成率/拖延/负荷 · 浅色极简 · 克制配色</p>
      </div>
      <n-space :size="8" align="center">
        <n-select v-model:value="range" :options="rangeOpts" style="width: 120px" @update:value="load" />
        <n-button strong secondary style="border-radius: 20px" @click="load">刷新</n-button>
        <n-button style="border-radius: 20px" @click="runExp('A')">实验A</n-button>
        <n-button style="border-radius: 20px" @click="runExp('B')">实验B</n-button>
      </n-space>
    </div>

    <n-card class="agent-banner" :bordered="false" style="background: #1d1d1f; border-radius: 16px" content-style="padding: 24px 28px;" aria-label="智能体解读入口">
      <div class="flex items-center justify-between gap-6 flex-wrap">
        <div class="min-w-0">
          <div class="text-[11px] tracking-widest font-medium text-white/50">AGENT INSIGHT</div>
          <div class="mt-2 text-[17px] font-semibold tracking-[-0.01em] text-white">让智能体解读你最近的表现</div>
          <div class="mt-1 text-[12px] tracking-wide text-white/70 truncate">
            近{{ range === '7d' ? '7' : '30' }}天 · 完成率 {{ (overview.completion_rate * 100).toFixed(1) }}% · 拖延率 {{ (overview.delay_rate * 100).toFixed(1) }}% · 平均负荷 {{ overview.avg_load.toFixed(1) }} h/天
          </div>
        </div>
        <n-button color="#ffffff" style="border-radius: 20px; color: #1d1d1f; font-weight: 500" :disabled="sending" @click="sendToAgent">就此生成周计划 / 解读</n-button>
      </div>
    </n-card>

    <n-grid :cols="3" :x-gap="16">
      <n-gi><n-card class="stat-card" :bordered="false" aria-label="完成率"><div class="text-[11px] tracking-widest font-medium text-muted">完成率</div><div class="mt-2 text-[22px] font-semibold tracking-[-0.03em] text-ink">{{ (overview.completion_rate * 100).toFixed(1) }}%</div></n-card></n-gi>
      <n-gi><n-card class="stat-card" :bordered="false" aria-label="拖延率"><div class="text-[11px] tracking-widest font-medium text-muted">拖延率</div><div class="mt-2 text-[22px] font-semibold tracking-[-0.03em] text-ink">{{ (overview.delay_rate * 100).toFixed(1) }}%</div></n-card></n-gi>
      <n-gi><n-card class="stat-card" :bordered="false" aria-label="平均负荷"><div class="text-[11px] tracking-widest font-medium text-muted">平均负荷</div><div class="mt-2 text-[22px] font-semibold tracking-[-0.03em] text-ink">{{ overview.avg_load.toFixed(1) }}<span class="text-[12px] font-normal text-muted"> h/天</span></div></n-card></n-gi>
    </n-grid>

    <n-grid :cols="3" :x-gap="16">
      <n-gi><n-card class="stat-card" :bordered="false" aria-label="LLM成本"><div class="text-[11px] tracking-widest font-medium text-muted">LLM 成本</div><div class="mt-2 text-[22px] font-semibold tracking-[-0.03em] text-ink">¥{{ (overview.llm_cost ?? 0).toFixed(3) }}</div><div class="mt-1 text-[11px] tracking-wide text-muted">按 DeepSeek 0.002/任务估算</div></n-card></n-gi>
      <n-gi><n-card class="stat-card" :bordered="false" aria-label="专注时长"><div class="text-[11px] tracking-widest font-medium text-muted">专注时长</div><div class="mt-2 text-[22px] font-semibold tracking-[-0.03em] text-ink">{{ formatFocus(overview.focus_seconds) }}</div><div class="mt-1 text-[11px] tracking-wide text-muted">番茄 pomodoro 累计</div></n-card></n-gi>
      <n-gi><n-card class="stat-card" :bordered="false" aria-label="溢出计数"><div class="text-[11px] tracking-widest font-medium text-muted">溢出计数</div><div class="mt-2 text-[22px] font-semibold tracking-[-0.03em] text-ink">{{ overview.overflow_count ?? 0 }}</div><div class="mt-1 text-[11px] tracking-wide text-muted">截断 overflow 独立计数</div></n-card></n-gi>
    </n-grid>

    <n-card class="apple-card" :bordered="false" content-style="padding: 24px;">
      <template #header><span class="text-[13px] font-semibold tracking-[-0.01em] text-ink">趋势 · 完成率 × 负荷</span><span class="ml-2 text-[11px] tracking-wide text-muted">32px留白 · 无框卡片</span></template>
      <n-skeleton v-if="loading && !hasTrend" text :repeat="3" :sharp="false" />
      <n-alert v-else-if="loadError" title="加载失败，请重试" type="error" :show-icon="false" class="mt-2" style="border-radius: 12px">
        <span class="text-[13px] tracking-[-0.01em]">趋势加载失败：{{ loadError }}</span>
        <div class="mt-2">
          <n-button size="small" style="border-radius: 20px" :loading="loading" @click="load">重试</n-button>
        </div>
      </n-alert>
      <v-chart v-else-if="hasTrend" :key="isDark ? 'dark' : 'light'" :option="trendOpt" style="height: 300px" autoresize />
      <n-empty v-else description="暂无趋势数据，去目标页新建目标" class="py-10">
        <template #extra>
          <n-button size="small" type="primary" style="border-radius: 20px" @click="goGoals">去目标页</n-button>
        </template>
      </n-empty>
    </n-card>

    <n-card class="apple-card" :bordered="false" content-style="padding: 24px;" aria-label="全年热力图">
      <template #header><span class="text-[13px] font-semibold tracking-[-0.01em] text-ink">全年热力 · 完成率</span><span class="ml-2 text-[11px] tracking-wide text-muted">近365天 · 周一到周日</span></template>
      <n-skeleton v-if="yearLoading && !hasYear" text :repeat="3" :sharp="false" />
      <n-alert v-else-if="yearError" title="加载失败，请重试" type="error" :show-icon="false" class="mt-2" style="border-radius: 12px">
        <span class="text-[13px] tracking-[-0.01em]">全年数据加载失败：{{ yearError }}</span>
        <div class="mt-2">
          <n-button size="small" style="border-radius: 20px" :loading="yearLoading" @click="loadYear">重试</n-button>
        </div>
      </n-alert>
      <div v-else-if="hasYear">
        <div class="year-heatmap" role="img" aria-label="全年完成率热力图">
          <div v-for="(week, wi) in yearWeeks" :key="wi" class="year-week">
            <div
              v-for="(cell, di) in week"
              :key="di"
              class="year-cell"
              :class="{ 'year-cell--empty': cell.date == null }"
              :title="yearTitle(cell)"
              :style="cell.date == null ? {} : { backgroundColor: yearColor(cell.rate) }"
            />
          </div>
        </div>
        <div class="mt-3 flex items-center gap-3 text-[11px] tracking-wide text-muted">
          <span>少</span>
          <span class="year-legend" :style="{ backgroundColor: yearColor(0) }" />
          <span class="year-legend" :style="{ backgroundColor: yearColor(0.2) }" />
          <span class="year-legend" :style="{ backgroundColor: yearColor(0.6) }" />
          <span class="year-legend" :style="{ backgroundColor: yearColor(0.9) }" />
          <span>多</span>
          <span class="ml-2">悬停查看日期与完成率</span>
        </div>
      </div>
      <n-empty v-else description="暂无全年数据" class="py-10" />
    </n-card>

    <n-card class="apple-card" :bordered="false" content-style="padding: 24px;">
      <template #header><span class="text-[13px] font-semibold tracking-[-0.01em] text-ink">实验 · 对比散点</span></template>
      <v-chart v-if="hasTrend" :key="isDark ? 'dark-scatter' : 'light-scatter'" :option="scatterOpt" style="height: 240px" autoresize />
      <n-empty v-else description="暂无趋势数据，去目标页新建目标" class="py-6">
        <template #extra>
          <n-button size="small" style="border-radius: 20px" @click="goGoals">去目标页</n-button>
        </template>
      </n-empty>
      <n-code v-if="hasExp" :code="JSON.stringify(exp, null, 2)" language="json" class="mt-4" />
      <div v-else class="mt-2 text-[11px] tracking-wide text-muted">暂无实验结果，点击上方实验A/B 运行</div>
    </n-card>
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'DashboardView' })
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { NCard, NSpace, NButton, NSelect, NGrid, NGi, NCode, NEmpty, NSkeleton, NAlert, useMessage } from 'naive-ui'
import VChart from 'vue-echarts'
import { fetchStatsOverview, fetchStatsTrend, runStatsExperiment } from '@/api/stats'
import { listGoals } from '@/api/goals'
import type { StatsOverview, StatsTrend } from '@/types'
import { extractErrorMessage } from '@/api/client'
import { useDarkChart } from '@/utils/chartTheme'

const { isDark, palette } = useDarkChart()

const AGENT_PREFILL_KEY = 'agent:prefill'
// 公共契约：sessionStorage['agent:prefill'] = JSON {text?: string, goal_id?: number, source: 'dashboard', mode?: 'single'|'multi', hours?: number}，智能体工作台读取后预填上下文并校验 source
interface AgentPrefill { text?: string; goal_id?: number; source: 'dashboard'; mode?: 'single' | 'multi'; hours?: number }

const router = useRouter()
const message = useMessage()

const range = ref<string>('7d')
const rangeOpts = [
  { label: '7天', value: '7d' },
  { label: '30天', value: '30d' },
]
const overview = ref<StatsOverview>({ completion_rate: 0, delay_rate: 0, avg_load: 0, llm_cost: 0 })
const trendData = ref<StatsTrend>({ dates: [], rates: [], loads: [] })
const yearTrend = ref<StatsTrend>({ dates: [], rates: [], loads: [] })
const yearLoading = ref(false)
const yearError = ref('')
const exp = ref<Record<string, unknown>>({})
const sending = ref(false)
const loading = ref(false)
const loadError = ref('')
const activeGoalId = ref<number | null>(null)

const hasTrend = computed(() => (trendData.value.dates?.length ?? 0) > 0)
const hasExp = computed(() => Object.keys(exp.value ?? {}).length > 0)
const hasYear = computed(() => (yearTrend.value.dates?.length ?? 0) > 0)

interface YearCell { date: string | null; rate: number | null }

// 年热力图：列为周，行为周一到周日，不足补空
const yearWeeks = computed<YearCell[][]>(() => {
  const dates = yearTrend.value.dates ?? []
  const rates = yearTrend.value.rates ?? []
  if (!dates.length) return []
  const first = new Date(dates[0] + 'T00:00:00')
  const offset = Number.isNaN(first.getTime()) ? 0 : (first.getDay() + 6) % 7
  const weeks: YearCell[][] = []
  for (let i = 0; i < dates.length; i++) {
    const pos = offset + i
    const wi = Math.floor(pos / 7)
    const di = pos % 7
    if (!weeks[wi]) weeks[wi] = Array.from({ length: 7 }, () => ({ date: null, rate: null }))
    weeks[wi][di] = { date: dates[i], rate: typeof rates[i] === 'number' ? rates[i] : 0 }
  }
  return weeks
})

function yearColor(rate: number | null): string {
  if (rate == null) return 'transparent'
  const p = palette.value
  if (isDark.value) {
    if (rate <= 0) return p.split
    if (rate < 0.4) return 'rgba(57,211,83,0.35)'
    if (rate < 0.8) return 'rgba(57,211,83,0.65)'
    return '#39d353'
  }
  if (rate <= 0) return '#ebedf0'
  if (rate < 0.4) return '#9be9a8'
  if (rate < 0.8) return '#40c463'
  return '#216e39'
}

function yearTitle(cell: YearCell): string {
  if (!cell.date) return ''
  return `${cell.date} 完成率 ${(((cell.rate ?? 0)) * 100).toFixed(1)}%`
}

// Wave-2 P1-9：专注秒数格式化（缺失回退 —）
function formatFocus(seconds?: number): string {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) return '—'
  const s = Math.floor(seconds)
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m`
  return `${(s / 3600).toFixed(1)}h`
}

const trendOpt = computed(() => {
  const p = palette.value
  return {
    tooltip: { trigger: 'axis' as const, backgroundColor: p.tooltipBg, textStyle: { color: p.tooltipText, fontSize: 11 } },
    legend: { data: ['完成率', '负荷'], textStyle: { color: p.muted, fontSize: 11 }, top: 0 },
    grid: { left: 40, right: 16, top: 36, bottom: 24, containLabel: true },
    xAxis: { type: 'category' as const, data: trendData.value.dates as string[], axisLine: { lineStyle: { color: p.axis } }, axisLabel: { color: p.muted, fontSize: 11 } },
    yAxis: [
      { type: 'value' as const, max: 1, axisLine: { show: false }, splitLine: { lineStyle: { color: p.split } }, axisLabel: { color: p.muted } },
      { type: 'value' as const, axisLine: { show: false }, splitLine: { show: false }, axisLabel: { color: p.muted } },
    ],
    series: [
      {
        name: '完成率',
        type: 'line' as const,
        data: trendData.value.rates as number[],
        smooth: true,
        lineStyle: { color: p.seriesInk, width: 2 },
        itemStyle: { color: p.seriesInk },
        areaStyle: { color: p.area },
      },
      { name: '负荷', type: 'bar' as const, yAxisIndex: 1, data: trendData.value.loads as number[], itemStyle: { color: p.seriesMuted, borderRadius: [8, 8, 0, 0] }, barWidth: 12 },
    ],
  }
})

const scatterOpt = computed(() => {
  const p = palette.value
  return {
    tooltip: { trigger: 'item' as const, backgroundColor: p.tooltipBg, textStyle: { color: p.tooltipText, fontSize: 11 } },
    grid: { left: 40, right: 16, top: 12, bottom: 24 },
    xAxis: { name: '完成率', nameTextStyle: { color: p.muted }, min: 0, max: 1, axisLine: { lineStyle: { color: p.axis } }, splitLine: { lineStyle: { color: p.split } }, axisLabel: { color: p.muted } },
    yAxis: { name: '负荷', nameTextStyle: { color: p.muted }, min: 0, axisLine: { lineStyle: { color: p.axis } }, splitLine: { lineStyle: { color: p.split } }, axisLabel: { color: p.muted } },
    series: [
      {
        type: 'scatter' as const,
        data: trendData.value.rates.map((r, i) => [r, trendData.value.loads[i] ?? 0]),
        itemStyle: { color: p.seriesInk, opacity: 0.8 },
        symbolSize: 8,
      },
    ],
  }
})

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const r = await fetchStatsOverview(range.value)
    overview.value = r.data
    const t = await fetchStatsTrend(range.value === '7d' ? '7d' : '30d')
    trendData.value = t.data
  } catch (e: unknown) {
    const msg = extractErrorMessage(e)
    loadError.value = msg
    message.error(msg)
  } finally {
    loading.value = false
  }
}
async function runExp(type: 'A' | 'B'): Promise<void> {
  try {
    const r = await runStatsExperiment(type)
    exp.value = r.data as Record<string, unknown>
    message.success(`实验${type}完成`)
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
  }
}
async function loadGoal(): Promise<void> {
  try {
    const r = await listGoals({ page: 1, size: 5 })
    const items = r.data?.items ?? []
    const target = items.find(g => g.status === 'active') ?? items[0]
    if (target) activeGoalId.value = target.id
  } catch {}
}

// 年热力图独立调用：不影响上方 7d/30d 切换逻辑
async function loadYear(): Promise<void> {
  yearLoading.value = true
  yearError.value = ''
  try {
    const y = await fetchStatsTrend('365d')
    yearTrend.value = y.data
  } catch (e: unknown) {
    yearError.value = extractErrorMessage(e)
  } finally {
    yearLoading.value = false
  }
}

function goGoals(): void {
  try { void router.push('/goals') } catch {}
}

function sendToAgent(): void {
  if (sending.value) return
  sending.value = true
  const o = overview.value
  const text = `近${range.value === '7d' ? '7' : '30'}天概览：完成率 ${(o.completion_rate * 100).toFixed(1)}%，拖延率 ${(o.delay_rate * 100).toFixed(1)}%，平均负荷 ${o.avg_load.toFixed(1)} h/天。请据此解读我的学习状态并生成下周计划。`
  // 偏好 hours：由平均负荷启发，钳制 1-8，默认 2；mode 默认 multi，与工作台 Composer 一致
  const hours = Math.min(8, Math.max(1, Math.round(o.avg_load) || 2))
  const prefill: AgentPrefill = { text, source: 'dashboard', mode: 'multi', hours }
  if (activeGoalId.value != null) prefill.goal_id = activeGoalId.value
  try { sessionStorage.setItem(AGENT_PREFILL_KEY, JSON.stringify(prefill)) } catch {}
  void router.push('/agent')
  sending.value = false
}
onMounted(() => {
  void load()
  void loadYear()
  void loadGoal()
})
</script>

<style scoped>
.year-heatmap { display: flex; gap: 3px; overflow-x: auto; padding-bottom: 4px; }
.year-week { display: flex; flex-direction: column; gap: 3px; flex-shrink: 0; }
.year-cell { width: 11px; height: 11px; border-radius: 3px; background-color: #ebedf0; }
.year-cell--empty { background-color: transparent; border: 1px solid var(--c-border); box-sizing: border-box; }
.year-legend { display: inline-block; width: 11px; height: 11px; border-radius: 3px; }
</style>
