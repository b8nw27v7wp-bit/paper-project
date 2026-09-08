<template>
  <div class="space-y-6">
    <n-alert
      v-if="done"
      type="success"
      :show-icon="false"
      style="border-radius: 16px; background: var(--c-surface); border: none"
    >
      <span class="text-[13px] font-medium tracking-[-0.01em] text-ink">已生成 {{ tasks.length }} 个任务</span>
      <span class="ml-2 text-[12px] text-muted">{{ mentor }}</span>
    </n-alert>

    <n-alert
      v-if="failed"
      type="error"
      :show-icon="false"
      style="border-radius: 16px"
    >
      <span class="text-[12px]">{{ failTip }}</span>
    </n-alert>

    <!-- 虚拟化仅末20条 + 200帽 + 滚动容器，带 enter/leave 动效 -->
    <div ref="scrollRef" class="max-h-[320px] overflow-auto pr-2" style="scrollbar-width: thin" role="log" aria-live="polite" aria-label="规划时间线">
      <transition-group name="timeline" tag="div">
        <div v-for="(item, idx) in visibleTimeline" :key="`${item.time}-${idx}`" class="timeline-item">
          <n-timeline :icon-size="14">
            <n-timeline-item
              :type="item.type === 'success' ? 'success' : item.type === 'error' ? 'error' : item.type === 'warning' ? 'warning' : 'default'"
              :title="item.title"
              :content="item.content"
              :time="item.time"
            />
          </n-timeline>
        </div>
      </transition-group>
      <div v-if="timeline.length > 20" class="text-[11px] tracking-wide text-muted text-center py-2" aria-label="已压缩条数">
        已压 {{ timeline.length - visibleTimeline.length }} 条 (compaction · 最多200)
      </div>
      <div v-if="reconnecting" class="text-[11px] text-muted text-center py-2" role="status">重连中… lastEventId={{ lastEventId ?? '0' }}</div>
    </div>

    <div v-if="approval" class="rounded-[16px] bg-[#fffbeb] border border-[#fde68a] p-4">
      <div class="text-[12px] font-medium text-ink">任务需确认（{{ approval.tasks_preview.length }} 个）</div>
      <div class="mt-2 space-y-1.5 max-h-[160px] overflow-auto">
        <div v-for="(t, i) in approval.tasks_preview" :key="`${t.title}-${i}`" class="flex justify-between text-[13px] bg-[var(--c-bg)] rounded-[8px] px-2.5 py-1.5">
          <span class="text-ink truncate">{{ t.title }}</span>
          <span class="text-muted text-[12px] shrink-0">{{ fmtDate(String(t.planned_start ?? '')) }}</span>
        </div>
      </div>
      <div class="mt-3 flex items-center gap-2">
        <n-button size="small" type="primary" style="border-radius: 20px" :loading="approving" :disabled="approvalDone" @click="decideApproval(true)">批准</n-button>
        <n-button size="small" style="border-radius: 20px" :loading="rejecting" :disabled="approvalDone" @click="decideApproval(false)">拒绝</n-button>
        <span v-if="approvalDone" class="text-[11px] text-muted">{{ approvalResult }}</span>
      </div>
    </div>

    <div v-if="tasks.length" class="rounded-[16px] bg-[var(--c-surface)] p-4">
      <div class="flex items-center justify-between">
        <div class="text-[11px] tracking-widest font-medium text-muted">任务预览 · {{ tasks.length }}</div>
        <div class="flex items-center gap-2">
          <n-button size="tiny" secondary style="border-radius: 20px" :disabled="!hasCitations" @click="showArtifacts = true" aria-label="预览引用证据">Artifacts {{ citations.length || '' }}</n-button>
          <n-button size="tiny" style="border-radius: 20px" @click="copyTasks" aria-label="复制任务清单">复制</n-button>
        </div>
      </div>
      <div class="mt-3 space-y-2 max-h-[160px] overflow-auto">
        <div v-for="t in tasks" :key="String(t.title)" class="flex justify-between text-[13px] group">
          <span class="text-ink font-medium tracking-[-0.01em] flex items-center gap-1">
            <button class="opacity-0 group-hover:opacity-100 text-[11px] px-1.5 py-0.5 rounded-full bg-[var(--c-bg)] border border-[var(--c-border)] text-muted hover:text-ink" @click="applyInline(t)" aria-label="行内应用该任务">Apply</button>
            {{ t.title }}
          </span>
          <span class="text-muted text-[12px]">{{ fmtDate(String(t.planned_start)) }}</span>
        </div>
      </div>
    </div>

    <n-drawer v-model:show="showArtifacts" :width="420" placement="right" aria-label="Artifacts 抽屉">
      <n-drawer-content title="Artifacts · 引用证据" closable>
        <div class="space-y-3">
          <div class="text-[11px] tracking-wide text-muted">点击引用可在 RAG 中溯源 · 共 {{ citations.length }} 条</div>
          <div v-if="!citations.length" class="py-8 text-center text-[13px] text-muted">暂无引用（LLM 直出或早期任务）</div>
          <div v-for="(c, idx) in citations" :key="idx" class="rounded-[12px] bg-[var(--c-surface)] p-3">
            <div class="text-[12px] font-medium text-ink truncate">chunk {{ String((c as Record<string, unknown>).chunk_id ?? idx) }}</div>
            <div class="text-[11px] tracking-wide text-muted mt-1">score {{ String((c as Record<string, unknown>).score ?? '—') }}</div>
            <n-code v-if="(c as Record<string, unknown>).snippet" :code="String((c as Record<string, unknown>).snippet)" language="text" class="mt-2 text-[11px]" />
            <div class="mt-2 flex gap-2">
              <n-button size="tiny" style="border-radius: 20px" @click="openRag(c)">去 RAG</n-button>
              <n-button size="tiny" style="border-radius: 20px" @click="copyCitation(c)">复制</n-button>
            </div>
          </div>
          <n-code :code="JSON.stringify(citations, null, 2)" language="json" class="mt-2" />
        </div>
      </n-drawer-content>
    </n-drawer>

    <n-spin :show="loading" />
  </div>
</template>

<script setup lang="ts">
import { ref, watch, computed, onUnmounted, onDeactivated, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { NTimeline, NTimelineItem, NAlert, NSpin, NButton, NDrawer, NDrawerContent, NCode, useMessage } from 'naive-ui'
import { streamWorkbench, takeStreamTicket, getStreamErrorStatus, approvePlan } from '@/api/plans'
import type { ApprovalRequiredData } from '@/api/plans'
import { extractErrorMessage } from '@/api/client'

interface TimelineEntry {
  type: 'default' | 'success' | 'error' | 'warning' | 'info'
  title: string
  content: string
  time: string
}

interface TaskPreview {
  title: string
  planned_start: string
  planned_end?: string
  priority?: number
}

const props = defineProps<{ traceId: string | null; mentor?: string; citations?: unknown[] }>()
const emit = defineEmits<{ (e: 'done'): void }>()

const timeline = ref<TimelineEntry[]>([])
const tasks = ref<TaskPreview[]>([])
const mentor = ref(props.mentor || '')
const loading = ref(true)
const done = ref(false)
const failed = ref(false)
const failTip = ref('')
const reconnecting = ref(false)
const lastEventId = ref<string | null>(null)
const scrollRef = ref<HTMLDivElement | null>(null)
const approval = ref<ApprovalRequiredData | null>(null)
const approving = ref(false)
const rejecting = ref(false)
const approvalDone = ref(false)
const approvalResult = ref('')
let es: EventSource | null = null

const router = useRouter()
const message = useMessage()
const showArtifacts = ref(false)
const citations = computed<unknown[]>(() => (props.citations as unknown[] ?? []))
const hasCitations = computed(() => citations.value.length > 0)
function copyTasks(): void {
  const txt = tasks.value.map(t => `${t.title} @ ${t.planned_start}`).join('\n')
  try { navigator.clipboard.writeText(txt); message.success('已复制') } catch { message.warning(txt.slice(0, 80)) }
}
function applyInline(t: TaskPreview): void {
  message.info(`已应用：${t.title}（演示：行内 Apply 态）`)
}
function openRag(c: unknown): void {
  try { const id = (c as Record<string, unknown>).chunk_id; void router.push(`/rag?highlight=${String(id ?? '')}`); message.info('跳转 RAG 溯源') } catch {}
}
function copyCitation(c: unknown): void {
  try { navigator.clipboard.writeText(JSON.stringify(c, null, 2)); message.success('已复制引用') } catch {}
}
const visibleTimeline = computed<TimelineEntry[]>(() => timeline.value.slice(-20))

function fmtDate(v: string): string {
  try {
    return new Date(v).toLocaleDateString()
  } catch {
    return v.slice(0, 10)
  }
}

function pushTimeline(entry: TimelineEntry): void {
  timeline.value.push(entry)
  // 200 帽：超量则丢弃头部，保持内存克制
  if (timeline.value.length > 200) {
    timeline.value = timeline.value.slice(-200)
  }
  void nextTick(() => {
    const el = scrollRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function syncServerId(e: MessageEvent) {
  const lid = (e as MessageEvent & { lastEventId?: string }).lastEventId
  if (lid) lastEventId.value = String(lid)
}

async function decideApproval(ok: boolean): Promise<void> {
  if (!approval.value || !props.traceId) return
  if (ok) approving.value = true
  else rejecting.value = true
  try {
    await approvePlan(props.traceId, ok, approval.value.approve_token)
    approvalDone.value = true
    approvalResult.value = ok ? '已批准' : '已拒绝'
    pushTimeline({ type: ok ? 'success' : 'warning', title: '审批', content: ok ? '已批准' : '已拒绝', time: new Date().toLocaleTimeString() })
    message.success(ok ? '已批准' : '已拒绝')
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
  } finally {
    approving.value = false
    rejecting.value = false
  }
}

function cleanup(): void {
  if (es) {
    try {
      es.close()
    } catch {}
    es = null
  }
}

onUnmounted(() => {
  cleanup()
})
// keep-alive 缓存切后台不断流会越积越多：失活即关流，重开弹窗由 traceId watcher 重建
onDeactivated(() => {
  cleanup()
})

watch(
  () => props.traceId,
  (id) => {
    if (!id) return
    timeline.value = []
    tasks.value = []
    done.value = false
    failed.value = false
    failTip.value = ''
    loading.value = true
    reconnecting.value = false
    lastEventId.value = null
    approval.value = null
    approvalDone.value = false
    approvalResult.value = ''
    cleanup()
    // 首连一次性 ticket：仿 workbench 链路，创建计划返回的 stream_ticket 只首连一次，重连走 Bearer+lastId
    // 收敛复用 streamWorkbench 别名
    const ticket = takeStreamTicket(id) ?? undefined
    // 订阅 — 注入 Last-Event-ID 重连（指数退避由 api/plans 内部处理），支援旧9事件 + approval_required
    es = streamWorkbench(
      id,
      {
        onThought: (d) => {
          pushTimeline({ type: 'default', title: String(d.agent ?? '思考'), content: String(d.text ?? ''), time: new Date().toLocaleTimeString() })
        },
        onTool: (d) => {
          const label = d.tool === 'researcher' ? 'Researcher' : String(d.tool)
          const argsStr = (() => {
            try {
              return JSON.stringify(d.args).slice(0, 160)
            } catch {
              return String(d.args)
            }
          })()
          pushTimeline({ type: 'default', title: label, content: argsStr, time: new Date().toLocaleTimeString() })
        },
        onToolStart: (d) => {
          const label = `${String(d.tool)} 开始调用`
          const argsStr = (() => {
            try { return JSON.stringify(d.args).slice(0, 120) } catch { return String(d.args) }
          })()
          pushTimeline({ type: 'info', title: label, content: argsStr, time: new Date().toLocaleTimeString() })
        },
        onToolEnd: (d) => {
          const label = `${String(d.tool)} 调用结束`
          const resStr = (() => {
            try { return JSON.stringify(d.result).slice(0, 120) } catch { return String(d.result) }
          })()
          pushTimeline({ type: 'success', title: label, content: resStr, time: new Date().toLocaleTimeString() })
        },
        onTask: (d) => {
          const t = d.task as unknown as TaskPreview
          tasks.value.push({ title: String(t.title), planned_start: String(t.planned_start), planned_end: String(t.planned_end ?? ''), priority: Number(t.priority ?? 3) })
          pushTimeline({ type: 'success', title: '任务', content: String(t.title), time: new Date().toLocaleTimeString() })
        },
        onCritic: (d) => {
          const fb = String(d.feedback ?? '')
          pushTimeline({ type: fb ? 'warning' : 'success', title: 'Critic', content: fb || '通过', time: new Date().toLocaleTimeString() })
        },
        onMentor: (d) => {
          mentor.value = String(d.text ?? '')
          pushTimeline({ type: 'default', title: 'Mentor', content: String(d.text ?? ''), time: new Date().toLocaleTimeString() })
        },
        onReflector: (d) => {
          const patchStr = (() => {
            try {
              return JSON.stringify(d.patch).slice(0, 160)
            } catch {
              return String(d.patch)
            }
          })()
          pushTimeline({ type: 'info', title: 'Reflector', content: patchStr, time: new Date().toLocaleTimeString() })
        },
        onApproval: (d) => {
          approval.value = d as ApprovalRequiredData
          approvalDone.value = false
          pushTimeline({ type: 'warning', title: '待审批', content: `需确认 ${approval.value.tasks_preview.length} 个任务`, time: new Date().toLocaleTimeString() })
        },
        onDone: (d) => {
          done.value = true
          loading.value = false
          reconnecting.value = false
          failed.value = false
          if (d.source) mentor.value += ` [${String(d.source)} rewrites=${String(d.rewrites ?? 0)}]`
          emit('done')
          cleanup()
        },
        onError: (e: unknown) => {
          const st = getStreamErrorStatus(e)
          const msg = e instanceof Error ? e.message : String(e ?? '')
          const terminal = Boolean((e as { terminal?: boolean })?.terminal)
          // 401 已由 plans.ts 跳登录；404/耗尽停止重连并转空态/失败态，不再无缝重连
          if (st === 401) {
            loading.value = false
            reconnecting.value = false
            return
          }
          if (st === 404 || /404/.test(msg) || terminal) {
            loading.value = false
            reconnecting.value = false
            failed.value = true
            failTip.value = st === 404 || /404/.test(msg) ? '规划会话不存在，请重新发起' : '连接中断，已停止重连'
            pushTimeline({ type: 'error', title: '失败', content: failTip.value, time: new Date().toLocaleTimeString() })
            return
          }
          // 触发重连态 — api/plans 内部会以 lastEventId 重建
          reconnecting.value = true
          loading.value = false
        },
      },
      { lastEventId: lastEventId.value ?? undefined, retryMs: 1200, maxRetries: 5, ticket },
    )
    try {
      es.addEventListener('message', syncServerId as unknown as EventListener)
      const names = ['thought','tool_call','tool_call_start','tool_call_end','task_created','critic_feedback','critic','mentor_msg','mentor','reflector_patch','approval_required','done']
      for (const n of names) es.addEventListener(n, syncServerId as unknown as EventListener)
    } catch {}
  },
  { immediate: true },
)
</script>
