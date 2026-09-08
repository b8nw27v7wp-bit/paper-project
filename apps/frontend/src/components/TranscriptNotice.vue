<template>
  <div :class="['w-full max-w-[92%] rounded-[12px] border p-3', shellClass]">
    <div class="flex items-center gap-2">
      <span :class="['text-[11px] tracking-widest px-1.5 py-0.5 rounded-full font-medium', badgeClass]">{{ label }}</span>
      <span v-if="rewrites" class="text-[11px] text-muted">rewrites ×{{ rewrites }}</span>
      <span v-if="kind === 'approval' && typeof expiresIn === 'number'" class="text-[11px] text-muted">{{ remaining }}s 后过期</span>
      <span v-if="kind === 'approval' && approvalStatus && approvalStatus !== 'pending'" class="text-[11px] text-muted">{{ approvalStatusText }}</span>
    </div>
    <div v-if="kind === 'mentor'" class="mt-1.5 text-[13px] leading-5 text-ink">
      <Markdown :source="text || ''" />
    </div>
    <div v-else-if="kind === 'reflector'">
      <div v-if="patch && Object.keys(patch).length" class="mt-1.5">
        <Markdown :source="codeBlock(patch)" />
      </div>
      <div v-else class="mt-1.5 text-[12px] text-muted">无补丁（critic 通过）</div>
    </div>
    <div v-else-if="kind === 'approval'" class="mt-2 approval-pop">
      <div class="text-[12px] font-medium text-ink">规划任务需确认（{{ tasksPreview?.length ?? 0 }} 个）</div>
      <div class="mt-2 space-y-1.5 max-h-[180px] overflow-auto">
        <div v-for="(t, i) in tasksPreview ?? []" :key="`${t.title}-${i}`" class="flex items-center justify-between gap-2 bg-[var(--c-bg)] rounded-[8px] px-2.5 py-1.5 border border-hairline">
          <span class="text-[12px] text-ink truncate">{{ t.title }}</span>
          <span class="text-[11px] text-muted shrink-0">{{ fmtDate(t.planned_start) }} · P{{ t.priority ?? 3 }}</span>
        </div>
        <div v-if="!(tasksPreview?.length)" class="text-[12px] text-muted">暂无任务预览</div>
      </div>
      <div class="mt-3 flex items-center gap-2">
        <button
          class="px-3.5 py-1.5 text-[12px] font-medium rounded-full bg-ink text-white hover:bg-[var(--c-ink-hover)] transition-colors disabled:opacity-40"
          :disabled="busy || approvalStatus === 'approved' || approvalStatus === 'rejected'"
          aria-label="批准计划"
          @click="decide(true)"
        >{{ busy && pendingOk ? '批准中…' : approvalStatus === 'approved' ? '已批准' : '批准' }}</button>
        <button
          class="px-3.5 py-1.5 text-[12px] font-medium rounded-full bg-[var(--c-bg)] border border-hairline text-ink hover:bg-[var(--c-surface)] transition-colors disabled:opacity-40"
          :disabled="busy || approvalStatus === 'approved' || approvalStatus === 'rejected'"
          aria-label="拒绝计划"
          @click="decide(false)"
        >{{ busy && !pendingOk ? '拒绝中…' : approvalStatus === 'rejected' ? '已拒绝' : '拒绝' }}</button>
        <span v-if="errMsg" class="text-[11px] text-[#991b1b]">{{ errMsg }}</span>
      </div>
    </div>
    <div v-else class="mt-1.5 text-[12px] leading-5 text-ink whitespace-pre-wrap break-words">{{ text || '校验通过' }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, onMounted, onBeforeUnmount } from 'vue'
import Markdown from '@/components/Markdown.vue'
import { approvePlan } from '@/api/plans'
import { extractErrorMessage } from '@/api/client'
import { useWorkbenchStore } from '@/stores/workbench'
import type { ApprovalTaskPreview } from '@/types'

const props = defineProps<{
  kind: 'critic' | 'mentor' | 'reflector' | 'approval'
  text?: string
  patch?: Record<string, unknown>
  rewrites?: number
  tasksPreview?: ApprovalTaskPreview[]
  approveToken?: string
  traceId?: string
  expiresIn?: number
  approvalStatus?: 'pending' | 'approved' | 'rejected'
}>()
const emit = defineEmits<{ (e: 'resolved', approved: boolean): void }>()

const label = computed(() => {
  if (props.kind === 'critic') return 'Critic'
  if (props.kind === 'mentor') return 'Mentor'
  if (props.kind === 'approval') return '待审批'
  return 'Reflector'
})
const shellClass = computed(() => {
  if (props.kind === 'critic') return props.text ? 'bg-[#fffbeb] border-[#fde68a]' : 'bg-[#f5f5f7] border-hairline'
  if (props.kind === 'mentor') return 'bg-[#eff6ff] border-[#bfdbfe]'
  if (props.kind === 'approval') return 'bg-[#fffbeb] border-[#fde68a]'
  return 'bg-[#faf5ff] border-[#e9d5ff]'
})
const badgeClass = computed(() => {
  if (props.kind === 'critic') return props.text ? 'bg-[#fef3c7] text-[#92400e]' : 'bg-white text-muted border border-hairline'
  if (props.kind === 'mentor') return 'bg-[#dbeafe] text-[#1e40af]'
  if (props.kind === 'approval') return 'bg-[#fef3c7] text-[#92400e]'
  return 'bg-[#f3e8ff] text-[#6b21a8]'
})
const approvalStatusText = computed(() => {
  if (props.approvalStatus === 'approved') return '已批准'
  if (props.approvalStatus === 'rejected') return '已拒绝'
  return ''
})

const busy = ref(false)
const pendingOk = ref(true)
const errMsg = ref('')

// 审批倒计时：expiresIn 快照为 remaining，每秒递减；卸载清 timer
const remaining = ref(typeof props.expiresIn === 'number' ? Math.max(0, Math.floor(props.expiresIn)) : 0)
let countdownTimer: ReturnType<typeof setInterval> | null = null
let expiryNotified = false

function clearCountdown(): void {
  if (countdownTimer) {
    try { clearInterval(countdownTimer) } catch {}
    countdownTimer = null
  }
}

function maybeNotifyExpiry(): void {
  try {
    if (props.kind !== 'approval') return
    if (props.approvalStatus && props.approvalStatus !== 'pending') return
    if (expiryNotified) return
    if (remaining.value > 60 || remaining.value <= 0) return
    const nav = window as unknown as { Notification?: typeof Notification }
    if (!nav.Notification) return
    expiryNotified = true
    const count = props.tasksPreview?.length ?? 0
    const fire = (): void => {
      try {
        new nav.Notification!('审批即将过期', { body: `有 ${count} 个任务待审批，请及时处理` })
      } catch {}
    }
    try {
      const perm = nav.Notification.permission
      if (perm === 'granted') {
        fire()
        return
      }
      if (perm === 'denied') return
      try {
        const p = nav.Notification.requestPermission()
        if (p && typeof (p as Promise<string>).then === 'function') {
          ;(p as Promise<string>).then((r) => { if (r === 'granted') fire() }).catch(() => {})
        }
      } catch {}
    } catch {}
  } catch {}
}

function startCountdown(): void {
  clearCountdown()
  if (props.kind !== 'approval') return
  if (typeof props.expiresIn !== 'number') return
  if (props.approvalStatus && props.approvalStatus !== 'pending') return
  maybeNotifyExpiry()
  if (remaining.value <= 0) return
  countdownTimer = setInterval(() => {
    try {
      if (remaining.value > 0) remaining.value -= 1
      maybeNotifyExpiry()
      if (remaining.value <= 0) clearCountdown()
    } catch {}
  }, 1000)
}

watch(
  () => props.expiresIn,
  (v) => {
    if (typeof v === 'number') {
      remaining.value = Math.max(0, Math.floor(v))
      expiryNotified = false
      startCountdown()
    } else {
      clearCountdown()
    }
  },
)

watch(
  () => props.approvalStatus,
  (s) => {
    if (s && s !== 'pending') clearCountdown()
  },
)

onMounted(() => {
  startCountdown()
})

onBeforeUnmount(() => {
  clearCountdown()
})

function codeBlock(v: Record<string, unknown>): string {
  try { return '```json\n' + JSON.stringify(v, null, 2) + '\n```' } catch { return '```\n' + String(v) + '\n```' }
}

function fmtDate(v?: string): string {
  if (!v) return '—'
  try {
    const d = new Date(v)
    if (Number.isNaN(d.getTime())) return v.slice(0, 10)
    return d.toLocaleDateString()
  } catch { return v.slice(0, 10) }
}

async function decide(approved: boolean): Promise<void> {
  if (!props.traceId || !props.approveToken) {
    errMsg.value = '缺少审批凭证'
    return
  }
  if (busy.value) return
  busy.value = true
  pendingOk.value = approved
  errMsg.value = ''
  try {
    await approvePlan(props.traceId, approved, props.approveToken)
    try {
      const wb = useWorkbenchStore()
      wb.resolveApproval(props.approveToken, approved)
      // 批准后服务端继续落库：延迟重同步拿尾部 done/任务，避免转录重复
      if (approved) setTimeout(() => { try { wb.resync() } catch {} }, 4000)
    } catch {}
    emit('resolved', approved)
  } catch (e: unknown) {
    errMsg.value = extractErrorMessage(e)
  } finally {
    busy.value = false
  }
}
</script>
