<template>
  <div class="space-y-10">
    <div class="flex items-end justify-between">
      <div>
        <router-link to="/agent" class="inline-flex items-center gap-1 text-[12px] tracking-wide text-muted hover:text-ink transition-colors" aria-label="回到智能体工作台">← 回到智能体工作台</router-link>
        <h2 class="mt-2 text-[24px] font-semibold tracking-[-0.02em] text-ink">大屏驾驶舱</h2>
        <p class="mt-1 text-[13px] tracking-[-0.01em] text-muted">P3 ECharts 大屏 · 完成率/拖延率/图谱热力 · 周维度 — 极简克制</p>
      </div>
      <n-space :size="8">
        <n-select v-model:value="range" :options="rangeOpts" style="width: 120px" @update:value="load" />
        <n-button strong secondary style="border-radius: 20px" :loading="loading" @click="load">刷新</n-button>
        <n-button style="border-radius: 20px" @click="goExp">去实验</n-button>
      </n-space>
    </div>

    <n-grid :cols="4" :x-gap="16">
      <n-gi><n-card class="apple-card" content-style="padding: 32px;"><div class="text-[11px] tracking-widest font-medium text-muted">完成率</div><div class="mt-2 text-[28px] font-semibold tracking-[-0.03em] text-ink">{{ (overview.completion_rate * 100).toFixed(1) }}%</div><div class="text-[11px] tracking-wide text-muted">{{ range }}均值</div></n-card></n-gi>
      <n-gi><n-card class="apple-card" content-style="padding: 32px;"><div class="text-[11px] tracking-widest font-medium text-muted">拖延率</div><div class="mt-2 text-[28px] font-semibold tracking-[-0.03em] text-ink">{{ (overview.delay_rate * 100).toFixed(1) }}%</div><div class="text-[11px] tracking-wide text-muted">{{ range }}均值</div></n-card></n-gi>
      <n-gi><n-card class="apple-card" content-style="padding: 32px;"><div class="text-[11px] tracking-widest font-medium text-muted">平均负荷</div><div class="mt-2 text-[28px] font-semibold tracking-[-0.03em] text-ink">{{ overview.avg_load.toFixed(1) }}<span class="text-[14px] font-normal text-muted"> h/天</span></div><div class="text-[11px] tracking-wide text-muted">任务时长</div></n-card></n-gi>
      <n-gi><n-card class="apple-card" content-style="padding: 32px;"><div class="text-[11px] tracking-widest font-medium text-muted">图谱覆盖</div><div class="mt-2 text-[22px] font-semibold tracking-[-0.01em] text-ink">{{ graph.nodes.length }} 节点 / {{ graph.edges.length }} 边</div><div class="text-[11px] tracking-wide text-muted">PREREQ 热力</div></n-card></n-gi>
    </n-grid>

    <n-grid :cols="2" :x-gap="24">
      <n-gi>
        <n-card class="apple-card" title="趋势：完成率 × 负荷" content-style="padding: 32px;">
          <v-chart :option="trendOpt" style="height: 320px" autoresize />
        </n-card>
      </n-gi>
      <n-gi>
        <n-card class="apple-card" title="拖延 vs 完成（散点）" content-style="padding: 32px;">
          <v-chart :option="scatterOpt" style="height: 320px" autoresize />
        </n-card>
      </n-gi>
    </n-grid>

    <n-card class="apple-card" title="图谱热力（按学科密度）" content-style="padding: 32px;">
      <v-chart :option="heatOpt" style="height: 280px" autoresize />
      <div class="mt-2 text-[11px] tracking-wide text-muted">热力值 ∝ 节点数/学科，颜色越深依赖越密</div>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { NCard, NSpace, NButton, NSelect, NGrid, NGi, useMessage } from 'naive-ui'
import VChart from 'vue-echarts'
import { apiClient } from '@/api/client'
import type { StatsOverview, GraphData } from '@/types'
import { extractErrorMessage, isRecord } from '@/api/client'

const message = useMessage()
const router = useRouter()
const range = ref<string>('7d')
const rangeOpts = [
  { label: '7天', value: '7d' },
  { label: '30天', value: '30d' },
]
const loading = ref(false)
const overview = ref<StatsOverview>({ completion_rate: 0, delay_rate: 0, avg_load: 0, llm_cost: 0 })
const trendData = ref<{ dates: string[]; rates: number[]; loads: number[] }>({ dates: [], rates: [], loads: [] })
const graph = ref<GraphData>({ nodes: [], edges: [] })

const trendOpt = computed(() => ({
  tooltip: { trigger: 'axis' as const, backgroundColor: '#1d1d1f', textStyle: { color: '#fff', fontSize: 11 } },
  legend: { data: ['完成率', '负荷'], textStyle: { color: '#86868b', fontSize: 11 } },
  grid: { left: 40, right: 16, top: 24, bottom: 24, containLabel: true },
  xAxis: { type: 'category' as const, data: trendData.value.dates, axisLine: { lineStyle: { color: '#f5f5f7' } }, axisLabel: { color: '#86868b', fontSize: 11 } },
  yAxis: [
    { type: 'value' as const, max: 1, name: '完成率', axisLine: { show: false }, splitLine: { lineStyle: { color: '#f5f5f7' } } },
    { type: 'value' as const, name: '负荷 h', axisLine: { show: false }, splitLine: { show: false } },
  ],
  series: [
    { name: '完成率', type: 'line' as const, smooth: true, data: trendData.value.rates, areaStyle: { opacity: 0.06, color: 'rgba(29,29,31,0.06)' }, lineStyle: { width: 2, color: '#1d1d1f' }, itemStyle: { color: '#1d1d1f' } },
    { name: '负荷', type: 'bar' as const, yAxisIndex: 1, data: trendData.value.loads, itemStyle: { color: '#a1a1a6', borderRadius: [8, 8, 0, 0] }, barWidth: 12 },
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
const heatOpt = computed(() => {
  const bySub: Record<string, number> = {}
  graph.value.nodes.forEach((n) => {
    const s = (n.subject as string) || (n.name as string) || '通用'
    bySub[s] = (bySub[s] || 0) + 1
  })
  const subs = Object.keys(bySub)
  const data: Array<[number, number, number]> = subs.map((s, i) => [i, 0, bySub[s]])
  return {
    tooltip: { position: 'top' as const },
    grid: { left: 80, right: 20, top: 10, bottom: 30 },
    xAxis: { type: 'category' as const, data: subs, splitArea: { show: true }, axisLabel: { color: '#86868b', fontSize: 11 } },
    yAxis: { type: 'category' as const, data: ['密度'], splitArea: { show: true } },
    visualMap: {
      min: 0,
      max: Math.max(...Object.values(bySub), 1),
      calculable: true,
      orient: 'horizontal' as const,
      left: 'center',
      bottom: 0,
      inRange: { color: ['#f5f5f7', '#0071e3'] },
    },
    series: [{ type: 'heatmap' as const, data, label: { show: true, color: '#1d1d1f' } }],
  }
})

function unwrapData<T>(raw: unknown): T {
  if (isRecord(raw) && 'data' in raw) {
    const inner = (raw as Record<string, unknown>).data as unknown
    if (inner && typeof inner === 'object') return inner as T
  }
  return raw as T
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const [ov, tr, g] = await Promise.all([
      apiClient.get('/stats/overview', { params: { range: range.value } }),
      apiClient.get('/stats/trend', { params: { range: range.value } }),
      apiClient.get('/graph', { params: { limit: 50 } }).catch(() => ({ data: { data: { nodes: [], edges: [] } } })),
    ])
    overview.value = unwrapData<StatsOverview>(ov.data) ?? overview.value
    // trend unwrap
    const td = unwrapData<Record<string, unknown>>(tr.data)
    if (td && typeof td === 'object' && 'dates' in td) {
      trendData.value = { dates: (td.dates as string[]) || [], rates: (td.rates as number[]) || [], loads: (td.loads as number[]) || [] }
    }
    const gd = unwrapData<GraphData>(g.data)
    if (gd && Array.isArray(gd.nodes)) graph.value = { nodes: gd.nodes || [], edges: gd.edges || [] }
    else graph.value = { nodes: [], edges: [] }
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
  } finally {
    loading.value = false
  }
}
function goExp(): void {
  router.push('/experiments')
}
onMounted(() => {
  void load()
})
</script>
