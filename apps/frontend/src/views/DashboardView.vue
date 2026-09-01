<template>
  <div class="space-y-10">
    <div class="flex items-end justify-between">
      <div>
        <h2 class="text-[24px] font-semibold tracking-[-0.02em] text-ink">大屏</h2>
        <p class="mt-1 text-[13px] tracking-[-0.01em] text-muted">P3 评估 · 完成率/拖延/负荷 · 浅色极简 · 克制配色</p>
      </div>
      <n-space :size="8">
        <n-select v-model:value="range" :options="rangeOpts" style="width: 120px" @update:value="load" />
        <n-button strong secondary style="border-radius: 20px" @click="load">刷新</n-button>
        <n-button style="border-radius: 20px" @click="runExp('A')">实验A</n-button>
        <n-button style="border-radius: 20px" @click="runExp('B')">实验B</n-button>
      </n-space>
    </div>

    <n-grid :cols="3" :x-gap="16">
      <n-gi><n-card class="stat-card" aria-label="完成率"><div class="text-[11px] tracking-widest font-medium text-muted">完成率</div><div class="mt-2 text-[28px] font-semibold tracking-[-0.03em] text-ink">{{ (overview.completion_rate * 100).toFixed(1) }}%</div><div class="mt-1 h-1 rounded-full bg-[#f5f5f7] overflow-hidden"><div class="h-full bg-[#1d1d1f]" :style="{ width: (overview.completion_rate * 100).toFixed(1) + '%' }" /></div></n-card></n-gi>
      <n-gi><n-card class="stat-card" aria-label="拖延率"><div class="text-[11px] tracking-widest font-medium text-muted">拖延率</div><div class="mt-2 text-[28px] font-semibold tracking-[-0.03em] text-ink">{{ (overview.delay_rate * 100).toFixed(1) }}%</div><div class="mt-1 h-1 rounded-full bg-[#f5f5f7] overflow-hidden"><div class="h-full bg-[#86868b]" :style="{ width: (overview.delay_rate * 100).toFixed(1) + '%' }" /></div></n-card></n-gi>
      <n-gi><n-card class="stat-card" aria-label="平均负荷"><div class="text-[11px] tracking-widest font-medium text-muted">平均负荷</div><div class="mt-2 text-[28px] font-semibold tracking-[-0.03em] text-ink">{{ overview.avg_load.toFixed(1) }}<span class="text-[14px] font-normal text-muted"> h/天</span></div><div class="mt-1 text-[11px] tracking-wide text-muted">克制 · 8h 热力基准</div></n-card></n-gi>
    </n-grid>

    <n-card class="apple-card" content-style="padding: 32px;">
      <template #header><span class="text-[13px] font-semibold tracking-[-0.01em] text-ink">趋势 · 完成率 × 负荷</span><span class="ml-2 text-[11px] tracking-wide text-muted">32px留白 · 无框卡片</span></template>
      <v-chart :option="trendOpt" style="height: 300px" autoresize />
    </n-card>

    <n-card class="apple-card" content-style="padding: 32px;">
      <template #header><span class="text-[13px] font-semibold tracking-[-0.01em] text-ink">实验 · 对比散点</span></template>
      <v-chart :option="scatterOpt" style="height: 240px" autoresize />
      <n-code :code="JSON.stringify(exp, null, 2)" language="json" class="mt-4" />
    </n-card>
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'DashboardView' })
import { ref, computed, onMounted } from 'vue'
import { NCard, NSpace, NButton, NSelect, NGrid, NGi, NCode, useMessage } from 'naive-ui'
import VChart from 'vue-echarts'
import { fetchStatsOverview, fetchStatsTrend, runStatsExperiment } from '@/api/stats'
import type { StatsOverview, StatsTrend } from '@/types'
import { extractErrorMessage } from '@/api/client'

const range = ref<string>('7d')
const rangeOpts = [
  { label: '7天', value: '7d' },
  { label: '30天', value: '30d' },
]
const overview = ref<StatsOverview>({ completion_rate: 0, delay_rate: 0, avg_load: 0, llm_cost: 0 })
const trendData = ref<StatsTrend>({ dates: [], rates: [], loads: [] })
const exp = ref<Record<string, unknown>>({})
const message = useMessage()

const trendOpt = computed(() => ({
  tooltip: { trigger: 'axis' as const, backgroundColor: '#1d1d1f', textStyle: { color: '#fff', fontSize: 11 } },
  legend: { data: ['完成率', '负荷'], textStyle: { color: '#86868b', fontSize: 11 }, top: 0 },
  grid: { left: 40, right: 16, top: 36, bottom: 24, containLabel: true },
  xAxis: { type: 'category' as const, data: trendData.value.dates as string[], axisLine: { lineStyle: { color: '#f5f5f7' } }, axisLabel: { color: '#86868b', fontSize: 11 } },
  yAxis: [
    { type: 'value' as const, max: 1, axisLine: { show: false }, splitLine: { lineStyle: { color: '#f5f5f7' } }, axisLabel: { color: '#86868b' } },
    { type: 'value' as const, axisLine: { show: false }, splitLine: { show: false }, axisLabel: { color: '#86868b' } },
  ],
  series: [
    {
      name: '完成率',
      type: 'line' as const,
      data: trendData.value.rates as number[],
      smooth: true,
      lineStyle: { color: '#1d1d1f', width: 2 },
      itemStyle: { color: '#1d1d1f' },
      areaStyle: { color: 'rgba(29,29,31,0.06)' },
    },
    { name: '负荷', type: 'bar' as const, yAxisIndex: 1, data: trendData.value.loads as number[], itemStyle: { color: '#a1a1a6', borderRadius: [8, 8, 0, 0] }, barWidth: 12 },
  ],
}))

const scatterOpt = computed(() => ({
  tooltip: { trigger: 'item' as const },
  grid: { left: 40, right: 16, top: 12, bottom: 24 },
  xAxis: { name: '完成率', min: 0, max: 1, axisLine: { lineStyle: { color: '#f5f5f7' } }, splitLine: { lineStyle: { color: '#f5f5f7' } } },
  yAxis: { name: '负荷', min: 0, axisLine: { lineStyle: { color: '#f5f5f7' } }, splitLine: { lineStyle: { color: '#f5f5f7' } } },
  series: [
    {
      type: 'scatter' as const,
      data: trendData.value.rates.map((r, i) => [r, trendData.value.loads[i] ?? 0]),
      itemStyle: { color: '#1d1d1f', opacity: 0.8 },
      symbolSize: 8,
    },
  ],
}))

async function load(): Promise<void> {
  try {
    const r = await fetchStatsOverview(range.value)
    overview.value = r.data
    const t = await fetchStatsTrend(range.value === '7d' ? '7d' : '30d')
    trendData.value = t.data
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
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
onMounted(() => {
  void load()
})
</script>
