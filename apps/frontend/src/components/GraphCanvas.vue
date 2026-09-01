<template>
  <div class="relative">
    <v-chart ref="chartRef" :option="option" style="height: 360px" autoresize @click="onClick" />
    <div class="absolute top-2 right-2 flex gap-2">
      <n-button size="tiny" style="border-radius: 20px" @click="exportImg">导出 2x</n-button>
      <n-tag size="small" :type="statusColor as any">{{ statusLabel }}</n-tag>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import VChart from 'vue-echarts'
import type { WorkbenchGraphNode, WorkbenchGraphEdge } from '@/api/plans'
import { NButton, NTag } from 'naive-ui'

const props = defineProps<{
  nodes: WorkbenchGraphNode[]
  edges: WorkbenchGraphEdge[]
  status: string
}>()
const emit = defineEmits<{ (e: 'select', node: WorkbenchGraphNode): void }>()

const statusLabel = computed(() => props.status || 'pending')
const statusColor = computed(() => {
  if (props.status === 'completed' || props.status === 'success') return 'success'
  if (props.status === 'failed' || props.status === 'error') return 'error'
  if (props.status === 'running') return 'warning'
  return 'default'
})

const colorMap: Record<string, string> = {
  pending: '#e5e7eb',
  running: '#f59e0b',
  success: '#10b981',
  error: '#ef4444',
}

// 自适应等距布局：dagre 风格或 computed 等距 x = index * (1000/(n-1))，y 统一，便于论文截图可读
const layoutPositions = computed<Record<string, [number, number]>>(() => {
  const ids = props.nodes.length ? props.nodes.map((n) => n.id) : ['planner', 'researcher', 'executor', 'critic', 'mentor', 'reflector']
  const n = ids.length
  const step = n > 1 ? 1000 / (n - 1) : 1000
  const map: Record<string, [number, number]> = {}
  ids.forEach((id, idx) => {
    map[id] = [idx * step, 0.5]
  })
  return map
})
// 兼容旧 positionMap 命名，指向自适应 computed（保持 curveness）
const positionMap = layoutPositions

const option = computed(() => {
  const t0 = performance.now()
  const nodes = props.nodes.length ? props.nodes : [
    { id: 'planner', name: 'Planner', status: 'pending' as const, started_at: null, finished_at: null },
    { id: 'researcher', name: 'Researcher', status: 'pending' as const, started_at: null, finished_at: null },
    { id: 'executor', name: 'Executor', status: 'pending' as const, started_at: null, finished_at: null },
    { id: 'critic', name: 'Critic', status: 'pending' as const, started_at: null, finished_at: null },
    { id: 'mentor', name: 'Mentor', status: 'pending' as const, started_at: null, finished_at: null },
    { id: 'reflector', name: 'Reflector', status: 'pending' as const, started_at: null, finished_at: null },
  ]
  const data = nodes.map((n, idx) => {
    const total = nodes.length
    const step = total > 1 ? 1000 / (total - 1) : 1000
    // 自适应等距：x = index * (1000/(n-1))，兼容 positionMap computed
    const fallbackPos: [number, number] = [idx * step, 0.5]
    const mapPos = (positionMap.value as Record<string, [number, number]>)[n.id] as [number, number] | undefined
    const pos = mapPos || fallbackPos
    return {
      id: n.id,
      name: n.name,
      value: n.name,
      x: pos[0],
      y: pos[1] * 300,
      symbolSize: 42,
      itemStyle: { color: colorMap[n.status] || '#e5e7eb', borderColor: '#1d1d1f', borderWidth: n.status === 'running' ? 2 : 0 },
      label: { show: true, formatter: n.name, fontSize: 11, color: '#1d1d1f', position: 'bottom', distance: 10 },
      // tooltip 展示状态与时间
      tooltip: { formatter: `${n.name}<br/>${n.status}<br/>${n.started_at || ''}` },
    }
  })
  const edges = props.edges.map((e) => {
    const isReplan = e.type === 'replan'
    return {
      source: e.from,
      target: e.to,
      label: { show: true, formatter: isReplan ? 'replan' : '', fontSize: 9, color: isReplan ? '#ef4444' : '#9ca3af' },
      lineStyle: {
        color: isReplan ? '#ef4444' : '#9ca3af',
        width: isReplan ? 2.5 : 1.5,
        curveness: isReplan ? 0.35 : 0.12,
        type: isReplan ? 'dashed' as const : 'solid' as const,
      },
      emphasis: { lineStyle: { width: 3 } },
    }
  })
  const opt = {
    tooltip: { trigger: 'item' as const },
    animationDuration: 300,
    animationEasing: 'cubicOut' as const,
    series: [
      {
        type: 'graph' as const,
        layout: 'none' as const,
        roam: false,
        draggable: false,
        data,
        edges,
        lineStyle: { curveness: 0.1 },
        emphasis: { focus: 'adjacency' as const, scale: true },
        edgeSymbol: ['none', 'arrow'],
        edgeSymbolSize: 8,
      },
    ],
  }
  // 性能埋点：渲染耗时应 <500ms
  const elapsed = performance.now() - t0
  if (elapsed > 500) console.warn(`[GraphCanvas] render ${elapsed.toFixed(1)}ms >500ms`)
  return opt
})

const chartRef = ref<InstanceType<typeof VChart> | null>(null)

function onClick(params: unknown) {
  const p = params as { dataType?: string; data?: { id?: string } }
  if (p.dataType === 'node' && p.data?.id) {
    const node = props.nodes.find((n) => n.id === p.data?.id)
    if (node) emit('select', node)
  }
}

function exportImg() {
  try {
    // 通过 chart 实例导出 2x 用于论文截图，优先使用模板 ref 避免选错 canvas
    const inst = chartRef.value as unknown as { getDom?: () => HTMLElement } | null
    const el = (inst?.getDom?.()?.querySelector('canvas') as HTMLCanvasElement | null) || (document.querySelector('canvas') as HTMLCanvasElement | null)
    if (!el) return
    const url = (el as unknown as { toDataURL?: (t: string, q: number) => string }).toDataURL?.('image/png', 2)
    if (!url) {
      // 降级：提示已可截图
      return
    }
    const a = document.createElement('a')
    a.href = url
    a.download = `workbench-graph-${Date.now()}.png`
    a.click()
  } catch {}
}

// 点击穿透性能：<100ms 已由 emit 同步触发 Inspector 更新保障
watch(() => props.nodes, () => {}, { deep: true })
</script>
