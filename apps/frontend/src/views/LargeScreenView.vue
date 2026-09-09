<template>
  <div class="space-y-10">
    <div class="flex items-end justify-between">
      <div>
        <router-link to="/agent" class="inline-flex items-center gap-1 text-[12px] tracking-wide text-muted hover:text-ink transition-colors" aria-label="回到智能体工作台">← 回到智能体工作台</router-link>
        <h2 class="mt-2 text-[20px] font-semibold tracking-[-0.02em] text-ink">大屏驾驶舱</h2>
        <p class="mt-1 text-[11px] tracking-wide text-muted">P3 ECharts 大屏 · 完成率/拖延率/图谱热力 · 周维度</p>
      </div>
      <n-space :size="8" align="center">
        <n-select v-model:value="range" :options="rangeOpts" style="width: 120px" @update:value="load" />
        <n-button strong secondary style="border-radius: 20px" :loading="loading" @click="load">刷新</n-button>
        <n-button style="border-radius: 20px" @click="goExp">去实验</n-button>
      </n-space>
    </div>

    <n-grid :cols="4" :x-gap="16">
      <n-gi><n-card class="stat-card" :bordered="false" aria-label="完成率"><div class="text-[11px] tracking-widest font-medium text-muted">完成率</div><div class="mt-2 text-[28px] font-semibold tracking-[-0.03em] text-ink">{{ (overview.completion_rate * 100).toFixed(1) }}%</div><div class="text-[11px] tracking-wide text-muted">{{ range }}均值</div></n-card></n-gi>
      <n-gi><n-card class="stat-card" :bordered="false" aria-label="拖延率"><div class="text-[11px] tracking-widest font-medium text-muted">拖延率</div><div class="mt-2 text-[28px] font-semibold tracking-[-0.03em] text-ink">{{ (overview.delay_rate * 100).toFixed(1) }}%</div><div class="text-[11px] tracking-wide text-muted">{{ range }}均值</div></n-card></n-gi>
      <n-gi><n-card class="stat-card" :bordered="false" aria-label="平均负荷"><div class="text-[11px] tracking-widest font-medium text-muted">平均负荷</div><div class="mt-2 text-[28px] font-semibold tracking-[-0.03em] text-ink">{{ overview.avg_load.toFixed(1) }}<span class="text-[14px] font-normal text-muted"> h/天</span></div><div class="text-[11px] tracking-wide text-muted">任务时长</div></n-card></n-gi>
      <n-gi><n-card class="stat-card" :bordered="false" aria-label="图谱覆盖"><div class="text-[11px] tracking-widest font-medium text-muted">图谱覆盖</div><div class="mt-2 text-[22px] font-semibold tracking-[-0.01em] text-ink">{{ graph.nodes.length }} 节点 / {{ graph.edges.length }} 边</div><div class="text-[11px] tracking-wide text-muted">PREREQ 热力</div></n-card></n-gi>
    </n-grid>

    <n-skeleton v-if="loading && !hasTrend" text :repeat="3" :sharp="false" />
    <n-alert v-else-if="loadError" title="加载失败，请重试" type="error" :show-icon="false" class="rounded-[12px">
      <span class="text-[13px] tracking-[-0.01em]">大屏加载失败：{{ loadError }}</span>
      <div class="mt-2">
        <n-button size="small" style="border-radius: 20px" :loading="loading" @click="load">重试</n-button>
      </div>
    </n-alert>
    <template v-else>
    <n-card class="apple-card" :bordered="false" content-style="padding: 24px;">
      <template #header><span class="text-[13px] font-semibold tracking-[-0.01em] text-ink">趋势：完成率 × 负荷</span><span class="ml-2 text-[11px] tracking-wide text-muted">散点已去重 · 详见 Dashboard</span></template>
      <v-chart v-if="hasTrend" :key="isDark ? 'dark-trend' : 'light-trend'" :option="trendOpt" style="height: 320px" autoresize />
      <n-empty v-else description="暂无趋势数据，去目标页新建目标" class="py-10">
        <template #extra>
          <n-button size="small" type="primary" style="border-radius: 20px" @click="goGoals">去目标页</n-button>
        </template>
      </n-empty>
    </n-card>

    <n-card class="apple-card" :bordered="false" content-style="padding: 24px;">
      <template #header><span class="text-[13px] font-semibold tracking-[-0.01em] text-ink">图谱热力（按学科密度）</span></template>
      <v-chart v-if="hasGraph" :key="isDark ? 'dark-heat' : 'light-heat'" :option="heatOpt" style="height: 280px" autoresize />
      <n-empty v-else description="暂无图谱数据，去知识库入库" class="py-10">
        <template #extra>
          <n-button size="small" style="border-radius: 20px" @click="goRag">去知识库</n-button>
        </template>
      </n-empty>
      <div class="mt-2 text-[11px] tracking-wide text-muted">热力值 ∝ 节点数/学科，颜色越深依赖越密</div>
    </n-card>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
defineOptions({ name: 'LargeScreenView' })
import { useRouter } from 'vue-router'
import { NCard, NSpace, NButton, NSelect, NGrid, NGi, NEmpty, NSkeleton, NAlert, useMessage } from 'naive-ui'
import VChart from 'vue-echarts'
import { apiClient } from '@/api/client'
import type { StatsOverview, GraphData } from '@/types'
import { extractErrorMessage, isRecord } from '@/api/client'
import { useDarkChart } from '@/utils/chartTheme'

const { isDark, palette } = useDarkChart()

const message = useMessage()
const router = useRouter()
const range = ref<string>('7d')
const rangeOpts = [
  { label: '7天', value: '7d' },
  { label: '30天', value: '30d' },
]
const loading = ref(false)
const loadError = ref('')
const overview = ref<StatsOverview>({ completion_rate: 0, delay_rate: 0, avg_load: 0, llm_cost: 0 })
const trendData = ref<{ dates: string[]; rates: number[]; loads: number[] }>({ dates: [], rates: [], loads: [] })
const graph = ref<GraphData>({ nodes: [], edges: [] })

const hasTrend = computed(() => (trendData.value.dates?.length ?? 0) > 0)
const hasGraph = computed(() => (graph.value.nodes?.length ?? 0) > 0)

const trendOpt = computed(() => {
  const p = palette.value
  return {
    tooltip: { trigger: 'axis' as const, backgroundColor: p.tooltipBg, textStyle: { color: p.tooltipText, fontSize: 11 } },
    legend: { data: ['完成率', '负荷'], textStyle: { color: p.muted, fontSize: 11 } },
    grid: { left: 40, right: 16, top: 24, bottom: 24, containLabel: true },
    xAxis: { type: 'category' as const, data: trendData.value.dates, axisLine: { lineStyle: { color: p.axis } }, axisLabel: { color: p.muted, fontSize: 11 } },
    yAxis: [
      { type: 'value' as const, max: 1, name: '完成率', nameTextStyle: { color: p.muted }, axisLine: { show: false }, splitLine: { lineStyle: { color: p.split } }, axisLabel: { color: p.muted } },
      { type: 'value' as const, name: '负荷 h', nameTextStyle: { color: p.muted }, axisLine: { show: false }, splitLine: { show: false }, axisLabel: { color: p.muted } },
    ],
    series: [
      { name: '完成率', type: 'line' as const, smooth: true, data: trendData.value.rates, areaStyle: { opacity: 0.08, color: p.area }, lineStyle: { width: 2, color: p.seriesInk }, itemStyle: { color: p.seriesInk } },
      { name: '负荷', type: 'bar' as const, yAxisIndex: 1, data: trendData.value.loads, itemStyle: { color: p.seriesMuted, borderRadius: [8, 8, 0, 0] }, barWidth: 12 },
    ],
  }
})
const heatOpt = computed(() => {
  const p = palette.value
  const bySub: Record<string, number> = {}
  graph.value.nodes.forEach((n) => {
    const s = (n.subject as string) || (n.name as string) || '通用'
    bySub[s] = (bySub[s] || 0) + 1
  })
  const subs = Object.keys(bySub)
  const data: Array<[number, number, number]> = subs.map((s, i) => [i, 0, bySub[s]])
  return {
    tooltip: { position: 'top' as const, backgroundColor: p.tooltipBg, textStyle: { color: p.tooltipText, fontSize: 11 } },
    grid: { left: 80, right: 20, top: 10, bottom: 30 },
    xAxis: { type: 'category' as const, data: subs, splitArea: { show: true }, axisLabel: { color: p.muted, fontSize: 11 }, axisLine: { lineStyle: { color: p.axis } } },
    yAxis: { type: 'category' as const, data: ['密度'], splitArea: { show: true }, axisLabel: { color: p.muted }, axisLine: { lineStyle: { color: p.axis } } },
    visualMap: {
      min: 0,
      max: Math.max(...Object.values(bySub), 1),
      calculable: true,
      orient: 'horizontal' as const,
      left: 'center',
      bottom: 0,
      textStyle: { color: p.muted },
      inRange: { color: isDark.value ? ['#2c2c2e', '#0a84ff'] : ['#f5f5f7', '#0071e3'] },
    },
    series: [{ type: 'heatmap' as const, data, label: { show: true, color: p.text } }],
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
  loadError.value = ''
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
    const msg = extractErrorMessage(e)
    loadError.value = msg
    message.error(msg)
  } finally {
    loading.value = false
  }
}
function goGoals(): void {
  try { router.push('/goals') } catch {}
}
function goRag(): void {
  try { router.push('/rag') } catch {}
}
function goExp(): void {
  try { void router.push('/experiments') } catch {}
}
onMounted(() => {
  void load()
})
</script>
