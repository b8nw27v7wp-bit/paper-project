<template>
  <div class="space-y-10">
    <div class="flex items-end justify-between">
      <div>
        <h2 class="text-[20px] font-semibold tracking-[-0.02em] text-ink">知识图谱</h2>
        <p class="mt-1 text-[11px] tracking-wide text-muted">前置依赖可视化 · 点击节点查看前置链</p>
      </div>
      <n-space :size="8">
        <n-input v-model:value="subject" placeholder="学科 如: 英语" style="width: 144px" clearable />
        <n-input v-model:value="keyword" placeholder="关键词" style="width: 144px" clearable />
        <n-button strong secondary style="border-radius: 20px" :loading="loading" @click="load">刷新</n-button>
      </n-space>
    </div>

    <n-grid :cols="3" :x-gap="24">
      <n-gi><n-card class="apple-card" :bordered="false" content-style="padding: 32px;"><div class="text-[11px] tracking-widest font-medium text-muted">节点</div><div class="mt-2 text-[22px] font-semibold tracking-[-0.03em] text-ink">{{ graph.nodes.length }}</div></n-card></n-gi>
      <n-gi><n-card class="apple-card" :bordered="false" content-style="padding: 32px;"><div class="text-[11px] tracking-widest font-medium text-muted">边 PREREQ</div><div class="mt-2 text-[22px] font-semibold tracking-[-0.03em] text-ink">{{ graph.edges.length }}</div></n-card></n-gi>
      <n-gi><n-card class="apple-card" :bordered="false" content-style="padding: 32px;"><div class="text-[11px] tracking-widest font-medium text-muted">学科</div><div class="mt-2 text-[14px] font-medium tracking-[-0.01em] text-ink">{{ subject || '全部' }}</div></n-card></n-gi>
    </n-grid>

    <n-alert v-if="loadError" type="error" title="加载失败" :show-icon="false" style="border-radius: 16px" class="text-[12px]">
      {{ loadError }}
    </n-alert>

    <n-card class="apple-card" :bordered="false" content-style="padding: 32px;">
      <template #header><span class="text-[13px] font-semibold tracking-[-0.01em] text-ink">力导向图</span><span class="ml-2 text-[11px] tracking-wide text-muted">拖拽可布局 · 缩放漫游</span></template>
      <n-skeleton v-if="loading" text :repeat="5" :sharp="false" />
      <div v-else-if="graph.nodes.length" class="rounded-[16px] bg-[var(--c-bg)] px-4 py-2">
        <v-chart :key="isDark ? 'dark' : 'light'" :option="opt" style="height: 420px" autoresize />
        <div class="mt-3 text-[11px] tracking-wide text-muted">点击节点查看前置链 · 拖拽可布局</div>
      </div>
      <n-empty v-else description="暂无图谱数据，请先去知识库上传文档构建">
        <template #extra>
          <n-button size="small" type="primary" style="border-radius: 20px" @click="goRag">去知识库上传</n-button>
        </template>
      </n-empty>
    </n-card>

    <n-grid :cols="2" :x-gap="24">
      <n-gi>
        <n-card class="apple-card" :bordered="false" content-style="padding: 32px;">
          <template #header><span class="text-[13px] font-semibold tracking-[-0.01em] text-ink">节点列表</span></template>
          <div class="table-scroll table-scroll--narrow">
            <n-data-table :columns="nodeCols" :data="graph.nodes" :pagination="{ pageSize: 5 }" size="small" :bordered="false" :single-line="false" :row-key="(r: GraphNode) => r.id || r.name" class="graph-table" />
          </div>
          <n-empty v-if="!loading && !loadError && !graph.nodes.length" description="暂无节点" class="mt-4" size="small" />
        </n-card>
      </n-gi>
      <n-gi>
        <n-card class="apple-card" :bordered="false" content-style="padding: 32px;">
          <template #header><span class="text-[13px] font-semibold tracking-[-0.01em] text-ink">选中节点依赖</span></template>
          <div v-if="selected" class="space-y-2">
            <div class="text-[13px] font-semibold tracking-[-0.01em] text-ink">{{ selected.name }}</div>
            <div class="text-[11px] tracking-wide text-muted">前置: {{ prereqs.join(' → ') || '无' }}</div>
          </div>
          <n-empty v-else description="点击图谱节点查看前置链" size="small" />
          <div class="table-scroll table-scroll--narrow">
            <n-data-table class="mt-4 graph-table" :columns="edgeCols" :data="graph.edges" :pagination="{ pageSize: 5 }" size="small" :bordered="false" :single-line="false" :row-key="(r: GraphEdge) => r.from + r.to" />
          </div>
        </n-card>
      </n-gi>
    </n-grid>
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'KnowledgeGraphView' })
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { NCard, NSpace, NButton, NInput, NGrid, NGi, NDataTable, NEmpty, NAlert, NSkeleton, useMessage, type DataTableColumns } from 'naive-ui'
import VChart from 'vue-echarts'
import { fetchGraph } from '@/api/graph'
import type { GraphData, GraphNode, GraphEdge } from '@/types'
import { extractErrorMessage } from '@/api/client'
import { useDarkChart } from '@/utils/chartTheme'

const { isDark, palette } = useDarkChart()

const router = useRouter()
const message = useMessage()
const subject = ref('')
const keyword = ref('')
const loading = ref(false)
const loadError = ref('')
const graph = ref<GraphData>({ nodes: [], edges: [] })
const selected = ref<GraphNode | null>(null)

function goRag(): void {
  void router.push('/rag')
}

const prereqs = computed<string[]>(() => {
  if (!selected.value) return []
  const incoming = graph.value.edges.filter((e) => e.to === selected.value?.name).map((e) => e.from)
  return incoming
})
const opt = computed(() => {
  const p = palette.value
  return {
    tooltip: { trigger: 'item' as const, backgroundColor: p.tooltipBg, textStyle: { color: p.tooltipText, fontSize: 11 } },
    series: [
      {
        type: 'graph' as const,
        layout: 'force' as const,
        roam: true,
        draggable: true,
        force: { repulsion: 120, edgeLength: 90 },
        label: { show: true, fontSize: 11, color: p.text },
        data: graph.value.nodes.map((n) => ({ id: n.id || n.name, name: n.name, value: n.name, category: 0, symbolSize: 18 })),
        edges: graph.value.edges.map((e) => ({ source: e.from, target: e.to, label: { show: true, formatter: e.relation || 'PREREQ', fontSize: 9, color: p.muted } })),
        lineStyle: { color: isDark.value ? '#4b4b4d' : '#9ca3af', curveness: 0.1 },
        emphasis: { focus: 'adjacency' as const },
        itemStyle: { color: isDark.value ? '#f5f5f7' : '#1d1d1f', borderColor: p.axis, borderWidth: 1 },
      },
    ],
  }
})
const nodeCols: DataTableColumns<GraphNode> = [
  { title: '名称', key: 'name' },
  { title: 'ID', key: 'id', render: (r: GraphNode) => r.id || r.name },
]
const edgeCols: DataTableColumns<GraphEdge> = [
  { title: 'From', key: 'from' },
  { title: 'To', key: 'to' },
  { title: 'Relation', key: 'relation', render: (r: GraphEdge) => r.relation || 'PREREQ' },
]

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const res = await fetchGraph({ subject: subject.value || undefined, keyword: keyword.value || undefined })
    const d = res.data
    graph.value = { nodes: d.nodes || [], edges: d.edges || [] }
    if (!graph.value.nodes.length) message.warning('暂无图谱数据，请先在知识库中上传文档构建')
  } catch (e: unknown) {
    loadError.value = extractErrorMessage(e)
    message.error(loadError.value)
  } finally {
    loading.value = false
  }
}
onMounted(() => {
  void load()
})
</script>

<style scoped>
.graph-table :deep(.n-data-table-thead th) { background: var(--c-bg) !important; font-size: 11px; letter-spacing: 0.08em; color: var(--c-muted); font-weight: 510; border-bottom: 1px solid var(--c-hairline) !important; }
.graph-table :deep(.n-data-table-td) { border-bottom: 1px solid var(--c-hairline) !important; }
</style>
