<template>
  <div class="space-y-10">
    <div class="flex items-end justify-between">
      <div>
        <h2 class="text-[24px] font-semibold tracking-[-0.02em] text-ink">知识图谱</h2>
        <p class="mt-1 text-[13px] tracking-[-0.01em] text-muted">ECharts Graph · 前置依赖 · PREREQ 可视化</p>
      </div>
      <n-space :size="8">
        <n-input v-model:value="subject" placeholder="学科 如: 英语" style="width: 144px" clearable />
        <n-input v-model:value="keyword" placeholder="关键词" style="width: 144px" clearable />
        <n-button strong secondary style="border-radius: 20px" :loading="loading" @click="load">刷新</n-button>
      </n-space>
    </div>

    <n-grid :cols="3" :x-gap="24">
      <n-gi><n-card class="apple-card" content-style="padding: 32px;"><div class="text-[11px] tracking-widest font-medium text-muted">节点</div><div class="mt-2 text-[22px] font-semibold tracking-[-0.03em] text-ink">{{ graph.nodes.length }}</div></n-card></n-gi>
      <n-gi><n-card class="apple-card" content-style="padding: 32px;"><div class="text-[11px] tracking-widest font-medium text-muted">边 PREREQ</div><div class="mt-2 text-[22px] font-semibold tracking-[-0.03em] text-ink">{{ graph.edges.length }}</div></n-card></n-gi>
      <n-gi><n-card class="apple-card" content-style="padding: 32px;"><div class="text-[11px] tracking-widest font-medium text-muted">学科</div><div class="mt-2 text-[14px] font-medium tracking-[-0.01em] text-ink">{{ subject || '全部' }}</div></n-card></n-gi>
    </n-grid>

    <n-card class="apple-card" content-style="padding: 32px;">
      <v-chart :option="opt" style="height: 420px" autoresize />
      <div class="mt-3 text-[11px] tracking-wide text-muted">点击节点查看前置链 · 拖拽可布局</div>
    </n-card>

    <n-grid :cols="2" :x-gap="24">
      <n-gi>
        <n-card class="apple-card" title="节点列表" content-style="padding: 32px;">
          <n-data-table :columns="nodeCols" :data="graph.nodes" :pagination="{ pageSize: 5 }" size="small" :bordered="false" :row-key="(r: GraphNode) => r.id || r.name" />
        </n-card>
      </n-gi>
      <n-gi>
        <n-card class="apple-card" title="选中节点依赖" content-style="padding: 32px;">
          <div v-if="selected" class="space-y-2">
            <div class="text-[13px] font-semibold tracking-[-0.01em] text-ink">{{ selected.name }}</div>
            <div class="text-[12px] tracking-wide text-muted">前置: {{ prereqs.join(' → ') || '无' }}</div>
          </div>
          <n-empty v-else description="点击图谱节点" />
          <n-data-table class="mt-4" :columns="edgeCols" :data="graph.edges" :pagination="{ pageSize: 5 }" size="small" :bordered="false" :row-key="(r: GraphEdge) => r.from + r.to" />
        </n-card>
      </n-gi>
    </n-grid>
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'KnowledgeGraphView' })
import { ref, computed, onMounted } from 'vue'
import { NCard, NSpace, NButton, NInput, NGrid, NGi, NDataTable, NEmpty, useMessage, type DataTableColumns } from 'naive-ui'
import VChart from 'vue-echarts'
import { fetchGraph } from '@/api/graph'
import type { GraphData, GraphNode, GraphEdge } from '@/types'
import { extractErrorMessage } from '@/api/client'

const message = useMessage()
const subject = ref('')
const keyword = ref('')
const loading = ref(false)
const graph = ref<GraphData>({ nodes: [], edges: [] })
const selected = ref<GraphNode | null>(null)

const prereqs = computed<string[]>(() => {
  if (!selected.value) return []
  const incoming = graph.value.edges.filter((e) => e.to === selected.value?.name).map((e) => e.from)
  return incoming
})
const opt = computed(() => ({
  tooltip: { trigger: 'item' as const },
  series: [
    {
      type: 'graph' as const,
      layout: 'force' as const,
      roam: true,
      draggable: true,
      force: { repulsion: 120, edgeLength: 90 },
      label: { show: true, fontSize: 11, color: '#1d1d1f' },
      data: graph.value.nodes.map((n) => ({ id: n.id || n.name, name: n.name, value: n.name, category: 0, symbolSize: 18 })),
      edges: graph.value.edges.map((e) => ({ source: e.from, target: e.to, label: { show: true, formatter: e.relation || 'PREREQ', fontSize: 9 } })),
      lineStyle: { color: '#9ca3af', curveness: 0.1 },
      emphasis: { focus: 'adjacency' as const },
      itemStyle: { color: '#1d1d1f' },
    },
  ],
}))
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
  try {
    const res = await fetchGraph({ subject: subject.value || undefined, keyword: keyword.value || undefined })
    const d = res.data
    graph.value = { nodes: d.nodes || [], edges: d.edges || [] }
    if (!graph.value.nodes.length) message.warning('暂无图谱数据，请先在 RAG/Graph 中构建')
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
  } finally {
    loading.value = false
  }
}
onMounted(() => {
  void load()
})
</script>
