<template>
  <div class="space-y-10">
    <div class="flex items-end justify-between">
      <div>
        <h2 class="text-[24px] font-semibold tracking-[-0.02em] text-ink">对比实验</h2>
        <p class="mt-1 text-[13px] tracking-[-0.01em] text-muted">P3 双实验 · 多Agent vs 单Agent 盲评 · 有/无记忆完成率</p>
      </div>
      <n-space :size="8">
        <n-input v-model:value="goalTitle" placeholder="目标标题" style="width: 168px" />
        <n-input v-model:value="query" placeholder="记忆query" style="width: 144px" />
        <n-button strong secondary style="border-radius: 20px" :loading="loading" @click="runAll">一键对比</n-button>
      </n-space>
    </div>

    <n-grid :cols="2" :x-gap="24">
      <n-gi>
        <n-card class="apple-card" title="实验A · 多Agent vs 单Agent（盲评合理性）" content-style="padding: 32px;">
          <template #header-extra><n-tag :type="aDelta >= 0.5 ? 'success' : 'warning'" style="border-radius: 20px">Δ {{ aDelta.toFixed(2) }}</n-tag></template>
          <v-chart :option="optA" style="height: 260px" autoresize />
          <n-table size="small" class="mt-3" :bordered="false">
            <thead><tr><th>组</th><th>合理性</th><th>冲突率</th><th>盲评ID</th></tr></thead>
            <tbody>
              <tr><td>Single</td><td>{{ singleRationality }}</td><td>{{ singleConflict }}</td><td>{{ blindedSingle }}</td></tr>
              <tr><td>Multi (6节点)</td><td>{{ multiRationality }}</td><td>{{ multiConflict }}</td><td>{{ blindedMulti }}</td></tr>
            </tbody>
          </n-table>
          <div class="mt-3 text-[12px] leading-5 text-muted">{{ conclusionA }}</div>
        </n-card>
      </n-gi>
      <n-gi>
        <n-card class="apple-card" title="实验B · 有/无记忆完成率（7日）" content-style="padding: 32px;">
          <template #header-extra><n-tag :type="bDelta >= 0.1 ? 'success' : 'default'" style="border-radius: 20px">+{{ (bDelta * 100).toFixed(1) }}%</n-tag></template>
          <v-chart :option="optB" style="height: 260px" autoresize />
          <n-table size="small" class="mt-3" :bordered="false">
            <thead><tr><th>组</th><th>完成率</th><th>召回</th><th>盲评</th></tr></thead>
            <tbody>
              <tr><td>无记忆</td><td>{{ withoutRate }}</td><td>{{ withoutHits }}</td><td>Q</td></tr>
              <tr><td>有记忆(pgvector)</td><td>{{ withRate }}</td><td>{{ withHits }}</td><td>P</td></tr>
            </tbody>
          </n-table>
          <div class="mt-3 text-[12px] leading-5 text-muted">提升 {{ improvement }} · {{ hasDelta ? '有记忆显著更优' : '' }}</div>
        </n-card>
      </n-gi>
    </n-grid>

    <n-card class="apple-card" title="实验溯源" content-style="padding: 32px;">
      <n-code :code="JSON.stringify({ agent: expA, memory: expB }, null, 2)" language="json" />
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { NCard, NSpace, NButton, NInput, NGrid, NGi, NTag, NTable, NCode, useMessage } from 'naive-ui'
import VChart from 'vue-echarts'
import { apiClient } from '@/api/client'
import { extractErrorMessage, isRecord } from '@/api/client'

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
const expA = ref<ExpA>({ groups: { single: {}, multi: {} }, samples: [] })
const expB = ref<ExpB>({})

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

const optA = computed(() => ({
  tooltip: { trigger: 'axis' as const },
  legend: { data: ['合理性', '冲突率'], textStyle: { color: '#86868b', fontSize: 11 } },
  grid: { left: 32, right: 16, top: 32, bottom: 24, containLabel: true },
  xAxis: { type: 'category' as const, data: ['Single', 'Multi'], axisLine: { lineStyle: { color: '#f5f5f7' } }, axisLabel: { color: '#86868b' } },
  yAxis: [
    { type: 'value' as const, max: 5, axisLine: { show: false }, splitLine: { lineStyle: { color: '#f5f5f7' } } },
    { type: 'value' as const, max: 1, axisLine: { show: false }, splitLine: { show: false } },
  ],
  series: [
    { name: '合理性', type: 'bar' as const, data: [singleRationality.value, multiRationality.value], itemStyle: { color: '#1d1d1f', borderRadius: [8, 8, 0, 0] }, barWidth: 28 },
    { name: '冲突率', type: 'line' as const, yAxisIndex: 1, data: [singleConflict.value, multiConflict.value], smooth: true, lineStyle: { color: '#86868b' } },
  ],
}))
const optB = computed(() => ({
  tooltip: { trigger: 'axis' as const },
  grid: { left: 32, right: 16, top: 12, bottom: 24 },
  xAxis: { type: 'category' as const, data: ['无记忆', '有记忆'], axisLine: { lineStyle: { color: '#f5f5f7' } }, axisLabel: { color: '#86868b' } },
  yAxis: { type: 'value' as const, max: 1, axisLine: { show: false }, splitLine: { lineStyle: { color: '#f5f5f7' } } },
  series: [
    {
      type: 'bar' as const,
      data: [withoutRate.value, withRate.value],
      itemStyle: { color: '#0071e3', borderRadius: [8, 8, 0, 0] },
      label: { show: true, formatter: '{c}' },
      barWidth: 28,
    },
  ],
}))

function toDataEnvelope<T>(raw: unknown): T {
  if (isRecord(raw) && 'data' in raw) return (raw as Record<string, unknown>).data as T
  return raw as T
}

async function runAll(): Promise<void> {
  loading.value = true
  try {
    const [ra, rb] = await Promise.all([
      apiClient.get('/experiments/agent-comparison', { params: { goal_title: goalTitle.value } }),
      apiClient.get('/experiments/memory-ablation', { params: { query: query.value } }),
    ])
    expA.value = toDataEnvelope<ExpA>(ra.data)
    expB.value = toDataEnvelope<ExpB>(rb.data)
    message.success('双实验完成')
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
  } finally {
    loading.value = false
  }
}
onMounted(() => {
  void runAll()
})
</script>
