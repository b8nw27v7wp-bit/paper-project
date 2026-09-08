<template>
  <div class="space-y-10">
    <div class="flex items-end justify-between">
      <div>
        <h2 class="text-[20px] font-semibold tracking-[-0.02em] text-ink">对比实验</h2>
        <p class="mt-1 text-[11px] tracking-wide text-muted">P3 双实验 · 多Agent vs 单Agent 盲评 · 有/无记忆完成率</p>
      </div>
      <n-space :size="8" align="center">
        <n-input v-model:value="goalTitle" placeholder="目标标题" style="width: 168px" />
        <n-input v-model:value="query" placeholder="记忆query" style="width: 144px" />
        <n-button strong secondary style="border-radius: 20px" :loading="loading" @click="runAll">一键对比</n-button>
      </n-space>
    </div>

    <n-skeleton v-if="loading && !hasResult" text :repeat="3" :sharp="false" />
    <n-alert v-else-if="loadError" title="加载失败，请重试" type="error" :show-icon="false" class="rounded-[12px]">
      <span class="text-[13px] tracking-[-0.01em]">实验加载失败：{{ loadError }}</span>
      <div class="mt-2">
        <n-button size="small" style="border-radius: 20px" :loading="loading" @click="runAll">重试</n-button>
      </div>
    </n-alert>
    <template v-else>
    <n-empty v-if="!hasResult && !loading" description="暂未运行实验，点击一键对比" class="py-10">
      <template #extra>
        <n-button size="small" type="primary" style="border-radius: 20px" :loading="loading" @click="runAll">一键对比</n-button>
      </template>
    </n-empty>
    <n-grid v-else :cols="2" :x-gap="24">
      <n-gi>
        <n-card class="apple-card" :bordered="false" content-style="padding: 24px;">
          <template #header><span class="text-[13px] font-semibold tracking-[-0.01em] text-ink">实验A · 多Agent vs 单Agent（盲评合理性）</span></template>
          <template #header-extra><n-tag :type="aDelta >= 0.5 ? 'success' : 'warning'" style="border-radius: 20px">Δ {{ aDelta.toFixed(2) }}</n-tag></template>
          <v-chart :key="isDark ? 'dark-a' : 'light-a'" :option="optA" style="height: 260px" autoresize />
          <div class="table-scroll table-scroll--narrow">
            <n-table size="small" class="mt-3" :bordered="false">
            <thead><tr><th class="text-[11px] font-medium tracking-widest text-muted">组</th><th class="text-[11px] font-medium tracking-widest text-muted">合理性</th><th class="text-[11px] font-medium tracking-widest text-muted">冲突率</th><th class="text-[11px] font-medium tracking-widest text-muted">盲评ID</th></tr></thead>
            <tbody>
              <tr><td class="text-[13px] text-ink">Single</td><td class="text-[13px] text-ink">{{ singleRationality }}</td><td class="text-[13px] text-ink">{{ singleConflict }}</td><td class="text-[13px] text-ink">{{ blindedSingle }}</td></tr>
              <tr><td class="text-[13px] text-ink">Multi (6节点)</td><td class="text-[13px] text-ink">{{ multiRationality }}</td><td class="text-[13px] text-ink">{{ multiConflict }}</td><td class="text-[13px] text-ink">{{ blindedMulti }}</td></tr>
            </tbody>
          </n-table>
          </div>
          <div class="mt-3 text-[12px] leading-5 text-muted">{{ conclusionA }}</div>
        </n-card>
      </n-gi>
      <n-gi>
        <n-card class="apple-card" :bordered="false" content-style="padding: 24px;">
          <template #header><span class="text-[13px] font-semibold tracking-[-0.01em] text-ink">实验B · 有/无记忆完成率（7日）</span></template>
          <template #header-extra><n-tag :type="bDelta >= 0.1 ? 'success' : 'default'" style="border-radius: 20px">+{{ (bDelta * 100).toFixed(1) }}%</n-tag></template>
          <v-chart :key="isDark ? 'dark-b' : 'light-b'" :option="optB" style="height: 260px" autoresize />
          <div class="table-scroll table-scroll--narrow">
            <n-table size="small" class="mt-3" :bordered="false">
            <thead><tr><th class="text-[11px] font-medium tracking-widest text-muted">组</th><th class="text-[11px] font-medium tracking-widest text-muted">完成率</th><th class="text-[11px] font-medium tracking-widest text-muted">召回</th><th class="text-[11px] font-medium tracking-widest text-muted">盲评</th></tr></thead>
            <tbody>
              <tr><td class="text-[13px] text-ink">无记忆</td><td class="text-[13px] text-ink">{{ withoutRate }}</td><td class="text-[13px] text-ink">{{ withoutHits }}</td><td class="text-[13px] text-ink">Q</td></tr>
              <tr><td class="text-[13px] text-ink">有记忆(pgvector)</td><td class="text-[13px] text-ink">{{ withRate }}</td><td class="text-[13px] text-ink">{{ withHits }}</td><td class="text-[13px] text-ink">P</td></tr>
            </tbody>
          </n-table>
          </div>
          <div class="mt-3 text-[12px] leading-5 text-muted">提升 {{ improvement }} · {{ hasDelta ? '有记忆显著更优' : '' }}</div>
        </n-card>
      </n-gi>
    </n-grid>

    <n-card v-if="hasResult" class="apple-card" :bordered="false" content-style="padding: 24px;">
      <template #header><span class="text-[13px] font-semibold tracking-[-0.01em] text-ink">实验溯源</span></template>
      <n-code :code="JSON.stringify({ agent: expA, memory: expB }, null, 2)" language="json" />
    </n-card>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
defineOptions({ name: 'ExperimentsView' })
import { NCard, NSpace, NButton, NInput, NGrid, NGi, NTag, NTable, NCode, NEmpty, NSkeleton, NAlert, useMessage } from 'naive-ui'
import VChart from 'vue-echarts'
import { apiClient } from '@/api/client'
import { extractErrorMessage, isRecord } from '@/api/client'
import { useDarkChart } from '@/utils/chartTheme'

const { isDark, palette } = useDarkChart()

interface ExpAGroups {
  single: { rationality?: number; conflict?: number }
  multi: { rationality?: number; conflict?: number }
}
interface ExpA {
  groups: ExpAGroups
  samples: Array<{ blinded_id?: string }>
  delta?: { rationality?: number }
  conclusion?: string
}
interface ExpB {
  without_memory?: { completion_rate?: number; hits?: number }
  with_memory?: { completion_rate?: number; hits?: number }
  without?: { completion?: number }
  with?: { completion?: number }
  delta?: number
  improvement?: string
}

const message = useMessage()
const goalTitle = ref('演示目标')
const query = ref('学习')
const loading = ref(false)
const loadError = ref('')
const expA = ref<ExpA>({ groups: { single: {}, multi: {} }, samples: [] })
const expB = ref<ExpB>({})

const hasResult = computed(() => (expA.value.samples?.length ?? 0) > 0 || Object.keys(expB.value ?? {}).length > 0)

const aDelta = computed(() => expA.value?.delta?.rationality ?? 0)
const bDelta = computed(() => expB.value?.delta ?? 0)
const singleRationality = computed(() => expA.value.groups?.single?.rationality ?? 0)
const singleConflict = computed(() => expA.value.groups?.single?.conflict ?? 0)
const multiRationality = computed(() => expA.value.groups?.multi?.rationality ?? 0)
const multiConflict = computed(() => expA.value.groups?.multi?.conflict ?? 0)
const blindedSingle = computed(() => expA.value.samples?.[0]?.blinded_id ?? '—')
const blindedMulti = computed(() => expA.value.samples?.[1]?.blinded_id ?? '—')
const conclusionA = computed(() => expA.value.conclusion ?? '')
const withoutRate = computed(() => expB.value.without_memory?.completion_rate ?? expB.value.without?.completion ?? 0)
const withRate = computed(() => expB.value.with_memory?.completion_rate ?? expB.value.with?.completion ?? 0)
const withoutHits = computed(() => expB.value.without_memory?.hits ?? '—')
const withHits = computed(() => expB.value.with_memory?.hits ?? '—')
const improvement = computed(() => expB.value.improvement ?? '')
const hasDelta = computed(() => Boolean(expB.value.delta))

const optA = computed(() => {
  const p = palette.value
  return {
    tooltip: { trigger: 'axis' as const, backgroundColor: p.tooltipBg, textStyle: { color: p.tooltipText, fontSize: 11 } },
    legend: { data: ['合理性', '冲突率'], textStyle: { color: p.muted, fontSize: 11 } },
    grid: { left: 32, right: 16, top: 32, bottom: 24, containLabel: true },
    xAxis: { type: 'category' as const, data: ['Single', 'Multi'], axisLine: { lineStyle: { color: p.axis } }, axisLabel: { color: p.muted } },
    yAxis: [
      { type: 'value' as const, max: 5, axisLine: { show: false }, splitLine: { lineStyle: { color: p.split } }, axisLabel: { color: p.muted } },
      { type: 'value' as const, max: 1, axisLine: { show: false }, splitLine: { show: false }, axisLabel: { color: p.muted } },
    ],
    series: [
      { name: '合理性', type: 'bar' as const, data: [singleRationality.value, multiRationality.value], itemStyle: { color: p.seriesInk, borderRadius: [8, 8, 0, 0] }, barWidth: 28 },
      { name: '冲突率', type: 'line' as const, yAxisIndex: 1, data: [singleConflict.value, multiConflict.value], smooth: true, lineStyle: { color: p.muted }, itemStyle: { color: p.muted } },
    ],
  }
})
const optB = computed(() => {
  const p = palette.value
  return {
    tooltip: { trigger: 'axis' as const, backgroundColor: p.tooltipBg, textStyle: { color: p.tooltipText, fontSize: 11 } },
    grid: { left: 32, right: 16, top: 12, bottom: 24 },
    xAxis: { type: 'category' as const, data: ['无记忆', '有记忆'], axisLine: { lineStyle: { color: p.axis } }, axisLabel: { color: p.muted } },
    yAxis: { type: 'value' as const, max: 1, axisLine: { show: false }, splitLine: { lineStyle: { color: p.split } }, axisLabel: { color: p.muted } },
    series: [
      {
        type: 'bar' as const,
        data: [withoutRate.value, withRate.value],
        itemStyle: { color: isDark.value ? '#0a84ff' : '#0071e3', borderRadius: [8, 8, 0, 0] },
        label: { show: true, formatter: '{c}', color: p.text },
        barWidth: 28,
      },
    ],
  }
})

function toDataEnvelope<T>(raw: unknown): T {
  if (isRecord(raw) && 'data' in raw) return (raw as Record<string, unknown>).data as T
  return raw as T
}

async function runAll(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const [ra, rb] = await Promise.all([
      apiClient.get('/experiments/agent-comparison', { params: { goal_title: goalTitle.value } }),
      apiClient.get('/experiments/memory-ablation', { params: { query: query.value } }),
    ])
    expA.value = toDataEnvelope<ExpA>(ra.data)
    expB.value = toDataEnvelope<ExpB>(rb.data)
    message.success('双实验完成')
  } catch (e: unknown) {
    const msg = extractErrorMessage(e)
    loadError.value = msg
    message.error(msg)
  } finally {
    loading.value = false
  }
}
onMounted(() => {
  void runAll()
})
</script>
