<template>
  <div class="bg-[var(--c-bg)] border border-hairline rounded-[16px] p-4 mp-panel transition-all duration-200 ease-out">
    <!-- 头部：标题 + 状态 + 计数 -->
    <div class="flex items-center justify-between gap-2">
      <span class="text-[13px] font-semibold text-ink">任务监控</span>
      <span :class="['text-[11px] px-2 py-0.5 rounded-full font-medium', statusBadgeClass]">{{ statusText }}</span>
    </div>
    <div class="mt-1 text-[11px] text-muted">任务 {{ counts.tasks }} · 事件 {{ counts.events }}</div>

    <!-- 顶部 Progress 步骤条 -->
    <div class="mt-3">
      <div class="text-[11px] text-muted mb-2">进度</div>
      <div v-if="nodes.length" class="flex items-start" role="list" aria-label="节点进度">
        <template v-for="(n, i) in nodes" :key="n.id">
          <div class="flex flex-col items-center shrink-0 w-10" role="listitem" :aria-label="`${n.name} ${n.status}`">
            <span :class="['w-2.5 h-2.5 rounded-full', nodeDotClass(n.status), isRunning(n.status) ? 'mp-pulse' : '']" />
            <span class="mt-1 text-[11px] text-muted truncate max-w-[44px]">{{ n.name }}</span>
          </div>
          <div v-if="i < nodes.length - 1" :class="['flex-1 h-px mt-[5px] mx-1', lineClass(n.status)]" />
        </template>
      </div>
      <div v-else class="text-[12px] text-muted">暂无进度</div>
    </div>

    <!-- 审批区：复用 TranscriptNotice 审批卡片样式 -->
    <div v-if="showApproval" class="mt-4 border-t border-hairline pt-3">
      <div class="flex items-center gap-2">
        <span class="text-[11px] tracking-widest px-1.5 py-0.5 rounded-full font-medium bg-[#fef3c7] text-[#92400e]">待审批</span>
        <span v-if="typeof expiresIn === 'number' && expiresIn > 0" class="text-[11px] text-muted">{{ expiresIn }}s 后过期</span>
      </div>
      <div class="mt-2 text-[12px] font-medium text-ink">规划任务需确认（{{ tasksPreview.length }} 个）</div>
      <div class="mt-2 space-y-1.5 max-h-[180px] overflow-auto">
        <div
          v-for="(t, i) in tasksPreview"
          :key="`${t.title}-${i}`"
          class="flex items-center justify-between gap-2 bg-[var(--c-bg)] rounded-[8px] px-2.5 py-1.5 border border-hairline"
        >
          <span class="text-[12px] text-ink truncate">{{ t.title }}</span>
          <span class="text-[11px] text-muted shrink-0">{{ fmtDate(t.planned_start) }} · P{{ t.priority ?? 3 }}</span>
        </div>
        <div v-if="!tasksPreview.length" class="text-[12px] text-muted">暂无任务预览</div>
      </div>
      <div class="mt-3 flex items-center gap-2">
        <button
          class="px-3.5 py-1.5 text-[12px] font-medium rounded-full bg-ink text-white hover:bg-[var(--c-ink-hover)] transition-colors disabled:opacity-40"
          :disabled="busy || approvalStatus !== 'pending'"
          aria-label="批准计划"
          @click="decide(true)"
        >{{ busy && pendingOk ? '批准中…' : '批准' }}</button>
        <button
          class="px-3.5 py-1.5 text-[12px] font-medium rounded-full bg-[var(--c-bg)] border border-hairline text-ink hover:bg-[var(--c-surface)] transition-colors disabled:opacity-40"
          :disabled="busy || approvalStatus !== 'pending'"
          aria-label="拒绝计划"
          @click="decide(false)"
        >{{ busy && !pendingOk ? '拒绝中…' : '拒绝' }}</button>
        <span v-if="errMsg" class="text-[11px] text-[#991b1b]">{{ errMsg }}</span>
      </div>
    </div>
    <div v-else-if="hasDecided" class="mt-4 border-t border-hairline pt-3 text-[12px] text-muted">
      {{ approvalStatus === 'approved' ? '已批准' : '已拒绝' }}
    </div>

    <!-- 引用区 -->
    <div class="mt-4 border-t border-hairline pt-3">
      <div class="text-[11px] text-muted mb-2">引用（{{ citations.length }}）</div>
      <div v-if="citations.length" class="space-y-1.5 max-h-[160px] overflow-auto">
        <div
          v-for="(c, i) in citations"
          :key="`${citationKey(c)}-${i}`"
          class="rounded-[8px] border border-hairline px-2.5 py-1.5"
        >
          <div class="text-[12px] text-ink truncate">{{ citationTitle(c) }}</div>
          <div v-if="citationSnippet(c)" class="mt-0.5 text-[11px] text-muted line-clamp-2 break-words">{{ citationSnippet(c) }}</div>
        </div>
      </div>
      <div v-else class="text-[12px] text-muted">暂无引用</div>
    </div>

    <!-- 产物区 -->
    <div v-if="status === 'completed'" class="mt-4 border-t border-hairline pt-3">
      <div class="text-[11px] text-muted">产物</div>
      <div class="mt-1.5 flex items-center justify-between gap-2">
        <span class="text-[12px] text-ink">共 {{ counts.tasks || tasksPreview.length }} 个任务</span>
        <button
          class="px-3.5 py-1.5 text-[12px] font-medium rounded-full bg-ink text-white hover:bg-[var(--c-ink-hover)] transition-colors"
          aria-label="去日历查看"
          @click="goCalendar"
        >去日历查看</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { approvePlan } from '@/api/plans'
import { extractErrorMessage } from '@/api/client'
import { useWorkbenchStore } from '@/stores/workbench'

interface TaskPreview {
  title: string
  planned_start?: string
  planned_end?: string
  priority?: number
}

interface ProgressNode {
  id: string
  name: string
  status: string
}

interface CitationItem {
  chunk_id?: string
  score?: number
  source?: string
  url?: string
  snippet?: string
  title?: string
}

interface PanelCounts {
  tasks: number
  events: number
}

const props = withDefaults(
  defineProps<{
    status: string
    tasksPreview: TaskPreview[]
    approveToken: string
    traceId: string
    expiresIn: number
    nodes: ProgressNode[]
    citations: CitationItem[]
    counts: PanelCounts
  }>(),
  {
    status: 'running',
    tasksPreview: () => [],
    approveToken: '',
    traceId: '',
    expiresIn: 0,
    nodes: () => [],
    citations: () => [],
    counts: () => ({ tasks: 0, events: 0 }),
  },
)

const emit = defineEmits<{ (e: 'resolved', approved: boolean): void }>()

const router = useRouter()
const busy = ref(false)
const pendingOk = ref(true)
const errMsg = ref('')
const approvalStatus = ref<'pending' | 'approved' | 'rejected'>('pending')

// 跨会话/换 token 残留：token 或 trace 切换即重置本地决议态，避免“已批准”串台隐藏新审批卡
watch([() => props.approveToken, () => props.traceId], () => {
  approvalStatus.value = 'pending'
  busy.value = false
  errMsg.value = ''
})

const hasDecided = computed(() => approvalStatus.value !== 'pending' && !!props.approveToken)

// awaiting 以 workbench 待审批驱动，但必须校验 traceId，避免全局串台；文案与徽同源 effectiveStatus
const storeAwaiting = computed(() => {
  try {
    const wb = useWorkbenchStore()
    if (!wb.hasPendingApproval) return false
    // 无 traceId 透传时不兜底为 awaiting，避免跨会话打架
    if (!props.traceId) return false
    const pend = wb.pendingApproval
    if (pend?.traceId) return pend.traceId === props.traceId
    return wb.traceId === props.traceId
  } catch {
    return false
  }
})
const effectiveStatus = computed(() => {
  if (props.status === 'awaiting' || storeAwaiting.value) return 'awaiting'
  return props.status
})

// approveToken 且 status==='awaiting'，或 tasksPreview 非空且未决
const showApproval = computed(
  () =>
    !!props.approveToken &&
    approvalStatus.value === 'pending' &&
    (effectiveStatus.value === 'awaiting' || props.tasksPreview.length > 0),
)

const statusText = computed(() => {
  if (effectiveStatus.value === 'awaiting') return '等待审批'
  if (effectiveStatus.value === 'running') return '运行中'
  if (effectiveStatus.value === 'completed') return '已完成'
  if (effectiveStatus.value === 'failed') return '已失败'
  return effectiveStatus.value || '运行中'
})

const statusBadgeClass = computed(() => {
  if (effectiveStatus.value === 'completed') return 'bg-[#dcfce7] text-[#166534]'
  if (effectiveStatus.value === 'failed') return 'bg-[#fee2e2] text-[#991b1b]'
  if (effectiveStatus.value === 'awaiting') return 'bg-[#fef3c7] text-[#92400e]'
  return 'bg-[#dbeafe] text-[#1e40af]'
})

type NodeKind = 'success' | 'running' | 'error' | 'pending'

function normalizeNodeStatus(s: string): NodeKind {
  const v = (s || '').toLowerCase()
  if (v === 'success' || v === 'completed' || v === 'done' || v === 'ok') return 'success'
  if (v === 'running' || v === 'active' || v === 'in_progress' || v === 'progress') return 'running'
  if (v === 'error' || v === 'failed' || v === 'fail') return 'error'
  return 'pending'
}

function isRunning(s: string): boolean {
  return normalizeNodeStatus(s) === 'running'
}

function nodeDotClass(s: string): string {
  const k = normalizeNodeStatus(s)
  if (k === 'success') return 'bg-[#10b981]'
  if (k === 'running') return 'bg-[#0071e3]'
  if (k === 'error') return 'bg-[#ef4444]'
  return 'bg-[#e8e8ed]'
}

function lineClass(s: string): string {
  return normalizeNodeStatus(s) === 'success' ? 'bg-[#10b981]/40' : 'bg-[#e8e8ed]'
}

function fmtDate(v?: string): string {
  if (!v) return '—'
  try {
    const d = new Date(v)
    if (Number.isNaN(d.getTime())) return v.slice(0, 10)
    return d.toLocaleDateString()
  } catch {
    return v.slice(0, 10)
  }
}

function citationKey(c: CitationItem): string {
  return String(c.chunk_id || c.url || c.source || c.title || 'citation')
}

function citationTitle(c: CitationItem): string {
  return String(c.source || c.url || c.title || c.chunk_id || '引用')
}

function citationSnippet(c: CitationItem): string {
  return typeof c.snippet === 'string' ? c.snippet : ''
}

function goCalendar(): void {
  void router.push('/calendar')
}

async function decide(approved: boolean): Promise<void> {
  if (!props.traceId || !props.approveToken) {
    errMsg.value = '缺少审批凭证'
    return
  }
  if (busy.value || approvalStatus.value !== 'pending') return
  // 跨卡竞态：同 token 已被转录卡决议则同步本地并直接返回，避免重复批准/过期 token 二次 POST
  try {
    const wb = useWorkbenchStore()
    const it = wb.transcript.find((x) => x.kind === 'approval' && x.approval?.approveToken === props.approveToken)
    if (it?.approval && it.approval.status !== 'pending') {
      approvalStatus.value = it.approval.status
      return
    }
  } catch {}
  busy.value = true
  pendingOk.value = approved
  errMsg.value = ''
  try {
    await approvePlan(props.traceId, approved, props.approveToken)
    try {
      const wb = useWorkbenchStore()
      wb.resolveApproval(props.approveToken, approved)
      // Wave-2：批准后服务端继续落库，照抄 TranscriptNotice:219 经单 timer 延迟重同步拿尾部
      if (approved) { try { wb.resyncDelayed() } catch {} }
    } catch {
      // store 调用失败不阻断 emit，父组件可自行处理
    }
    approvalStatus.value = approved ? 'approved' : 'rejected'
    emit('resolved', approved)
  } catch (e: unknown) {
    errMsg.value = extractErrorMessage(e)
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.mp-pulse {
  animation: mp-pulse 1.2s ease-in-out infinite;
}
@keyframes mp-pulse {
  0%,
  100% {
    box-shadow: 0 0 0 0 rgba(0, 113, 227, 0.35);
  }
  50% {
    box-shadow: 0 0 0 5px rgba(0, 113, 227, 0);
  }
}
@media (prefers-reduced-motion: reduce) {
  .mp-pulse {
    animation: none;
  }
}
</style>
