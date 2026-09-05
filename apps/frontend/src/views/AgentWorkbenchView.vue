<template>
  <div class="flex flex-col h-[calc(100vh-72px)] -mt-2">
    <div class="electron-drag h-5 shrink-0" aria-hidden="true" />
    <div class="flex items-center justify-between gap-3 px-1 pb-3">
      <div class="min-w-0">
        <h1 class="text-[20px] font-semibold tracking-[-0.02em] text-ink truncate">智能体工作台</h1>
        <p class="text-[11px] tracking-wide text-muted">规划 · 转录 · 洞察 · trace 可追溯 · SSE 8事件</p>
      </div>
      <div class="flex items-center gap-2 shrink-0">
        <n-tag v-if="wb.status === 'running'" type="warning" size="small">运行中</n-tag>
        <n-tag v-else-if="wb.status === 'completed'" type="success" size="small">已完成</n-tag>
        <n-tag v-else size="small">空闲</n-tag>
        <span class="hidden sm:inline text-[10px] tracking-wide px-2 py-1 rounded-full bg-surface text-muted font-mono" aria-label="当前 trace">trace_id: {{ wb.traceId ? wb.traceId.slice(0, 8) : '—' }}</span>
        <button class="px-3.5 py-1.5 text-[12px] font-medium rounded-full bg-ink text-white hover:bg-[#2c2c2e] transition-colors" aria-label="新会话" @click="newSession">＋ 新会话</button>
      </div>
    </div>

    <div class="flex-1 min-h-0 flex gap-4">
      <aside aria-label="会话列表" class="hidden md:flex w-[260px] shrink-0 flex-col rounded-[16px] bg-surface/60 border border-hairline p-3">
        <div class="flex items-center justify-between px-2 py-1">
          <span class="text-[11px] tracking-widest font-medium text-muted">会话</span>
          <span class="text-[10px] text-muted">{{ sessionsStore.total }}</span>
        </div>
        <div class="mt-2 flex-1 min-h-0 overflow-auto space-y-1 pr-1" role="listbox" aria-label="历史会话">
          <button
            v-for="s in sessionsStore.items"
            :key="s.trace_id"
            role="option"
            :aria-selected="wb.traceId === s.trace_id"
            :class="['w-full text-left px-3 py-2.5 rounded-[12px] transition-colors', wb.traceId === s.trace_id ? 'bg-ink text-white' : 'hover:bg-white text-ink']"
            @click="replaySession(s)"
          >
            <div class="flex items-center justify-between gap-2">
              <span class="text-[13px] font-medium tracking-[-0.01em] truncate">{{ s.goal_title }}</span>
              <span :class="['text-[9px] px-1.5 py-0.5 rounded-full border shrink-0', statusClass(s.status)]">{{ statusLabel(s.status) }}</span>
            </div>
            <div class="mt-1 flex items-center gap-2">
              <span :class="['text-[9px] px-1.5 py-0.5 rounded-full border', modeClass(s.mode)]">{{ s.mode }}</span>
              <span :class="['text-[10px]', wb.traceId === s.trace_id ? 'text-white/60' : 'text-muted']">{{ relativeTime(s.last_event_at) }}</span>
              <span :class="['text-[10px] font-mono', wb.traceId === s.trace_id ? 'text-white/60' : 'text-muted']">{{ s.event_count }} 事件</span>
            </div>
          </button>
          <div v-if="!sessionsStore.items.length && !sessionsStore.loading" class="py-8 text-center">
            <div class="mx-auto w-9 h-9 rounded-[12px] bg-white border border-hairline flex items-center justify-center text-[13px] text-muted">◌</div>
            <div class="mt-2 text-[12px] text-muted">暂无历史会话</div>
            <div class="mt-1 text-[11px] text-muted/70">创建目标并生成计划后展示</div>
          </div>
        </div>
        <div class="mt-2 pt-2 border-t border-hairline flex items-center justify-between">
          <button class="text-[11px] text-muted hover:text-ink disabled:opacity-40" :disabled="sessionsStore.page <= 1 || sessionsStore.loading" @click="prevPage">‹ 上一页</button>
          <span class="text-[10px] text-muted font-mono">{{ sessionsStore.page }}/{{ Math.max(1, Math.ceil(sessionsStore.total / sessionsStore.size)) }}</span>
          <button class="text-[11px] text-muted hover:text-ink disabled:opacity-40" :disabled="!sessionsStore.hasMore || sessionsStore.loading" @click="loadMore">下一页 ›</button>
        </div>
      </aside>

      <main class="flex-1 min-w-0 flex flex-col rounded-[16px] bg-white border border-hairline overflow-hidden">
        <TranscriptView
          v-if="wb.transcript.length || wb.status === 'running'"
          :items="wb.transcript"
          :reconnecting="wb.reconnecting"
          :selected-node-id="wb.selectedNodeId"
          :last-event-id="wb.lastEventId"
          :status="wb.status"
          :trace-id="wb.traceId"
        />
        <div v-else class="flex-1 overflow-auto p-6 flex items-center justify-center" aria-label="空态">
          <div class="text-center max-w-[420px]">
            <div class="mx-auto w-10 h-10 rounded-[12px] bg-ink text-white flex items-center justify-center text-[14px] font-semibold">AI</div>
            <div class="mt-3 text-[15px] font-semibold tracking-[-0.01em] text-ink">开始一次新的规划对话</div>
            <p class="mt-1 text-[13px] leading-5 text-muted">选择目标或直接描述，智能体将拆解任务、生成计划并在右侧展示执行轨迹。</p>
          </div>
        </div>

        <div class="border-t border-hairline p-4">
          <div class="flex items-center gap-2 mb-2">
            <n-select
              v-model:value="selectedGoal"
              :options="goalOpts"
              placeholder="选择学习目标（或直接输入自由文本）"
              clearable
              size="small"
              class="flex-1"
              aria-label="选择目标"
            />
            <div class="flex rounded-full border border-hairline bg-surface/50 p-0.5" role="radiogroup" aria-label="规划模式">
              <button
                :class="['px-3 py-1 text-[11px] rounded-full transition-colors', mode === 'single' ? 'bg-ink text-white' : 'text-muted hover:text-ink']"
                role="radio"
                :aria-checked="mode === 'single'"
                @click="mode = 'single'"
              >single</button>
              <button
                :class="['px-3 py-1 text-[11px] rounded-full transition-colors', mode === 'multi' ? 'bg-ink text-white' : 'text-muted hover:text-ink']"
                role="radio"
                :aria-checked="mode === 'multi'"
                @click="mode = 'multi'"
              >multi</button>
            </div>
          </div>
          <div class="flex items-end gap-2">
            <textarea
              ref="inputRef"
              v-model="composer"
              rows="1"
              class="flex-1 resize-none rounded-[12px] border border-hairline bg-surface/50 px-3 py-2.5 text-[13px] text-ink placeholder:text-muted focus:outline-none focus:border-[#0071e3]/40"
              placeholder="描述目标… 如：30天过六级，每天2小时"
              aria-label="目标输入"
              @keydown.enter.exact.prevent="send"
            />
            <button
              class="px-4 py-2.5 rounded-full bg-ink text-white text-[13px] hover:bg-[#2c2c2e] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              :disabled="creating || !composer.trim()"
              aria-label="发送"
              @click="send"
            >{{ creating ? '生成中…' : '发送' }}</button>
          </div>
          <div class="mt-2 flex items-center justify-between text-[11px] tracking-wide text-muted">
            <span>Enter 发送 · Shift+Enter 换行 · 模式 {{ mode }}</span>
            <span v-if="wb.traceId" class="font-mono">trace {{ wb.traceId.slice(0, 8) }} · 续传 last_event_id={{ wb.lastEventId || '0' }}</span>
            <span v-else>转录流 · 工具折叠块 · 任务卡</span>
          </div>
        </div>
      </main>

      <aside v-if="!rightCollapsed" aria-label="Inspector" class="hidden xl:flex w-[300px] shrink-0 flex-col rounded-[16px] bg-surface/60 border border-hairline p-3">
        <div class="flex items-center justify-between px-2 py-1">
          <span class="text-[11px] tracking-widest font-medium text-muted">INSPECTOR</span>
          <button class="text-[11px] text-muted hover:text-ink" aria-label="收起 Inspector" @click="rightCollapsed = true">»</button>
        </div>
        <div class="mt-2 flex-1 min-h-0 flex flex-col bg-white rounded-[12px] border border-hairline overflow-hidden">
          <n-tabs type="line" animated style="--n-tab-padding: 10px;" class="flex-1 min-h-0 flex flex-col">
            <n-tab-pane name="dag" tab="DAG" class="h-full">
              <div class="p-2 overflow-auto h-full">
                <GraphCanvas
                  v-if="wb.graph.nodes.length"
                  :nodes="wb.graph.nodes"
                  :edges="wb.graph.edges"
                  :status="wb.graph.status"
                  @select="onSelectNode"
                />
                <div v-else class="text-[12px] text-muted text-center py-10">无运行中的智能体<br /><span class="text-[11px]">生成计划后展示 6节点 DAG</span></div>
                <div v-if="wb.graph.nodes.length" class="mt-2 flex flex-wrap gap-1.5">
                  <span v-for="n in wb.graph.nodes" :key="n.id" :class="['text-[10px] px-2 py-0.5 rounded-full border', nodeClass(n.status)]">{{ n.name }}:{{ n.status }}</span>
                </div>
              </div>
            </n-tab-pane>
            <n-tab-pane name="state" tab="State">
              <div class="p-3 space-y-2">
                <div class="flex items-center justify-between">
                  <span class="text-[11px] text-muted">state 快照</span>
                  <button class="text-[11px] text-muted hover:text-ink" @click="copyJson(wb.inspector.state)">复制</button>
                </div>
                <n-code :code="pretty(wb.inspector.state)" language="json" class="text-[11px]" />
              </div>
            </n-tab-pane>
            <n-tab-pane name="logs" tab="Logs">
              <div class="p-3 space-y-2">
                <div class="flex items-center justify-between">
                  <span class="text-[11px] text-muted">agent_run_log ({{ wb.inspector.logs.length }})</span>
                  <button class="text-[11px] text-muted hover:text-ink" @click="copyJson(wb.inspector.logs)">复制</button>
                </div>
                <div v-for="lg in wb.inspector.logs" :key="lg.id" :class="['rounded-[10px] p-2', lg.agent_name === wb.selectedNodeId ? 'bg-[#eff6ff] border border-[#bfdbfe]' : 'bg-[#f5f5f7]']">
                  <div class="text-[11px] font-medium text-ink">{{ lg.agent_name }} <span class="text-muted font-normal">{{ lg.created_at?.slice(11, 19) }}</span></div>
                  <div class="text-[10px] text-muted mt-1 break-all">input: {{ jsonStr(lg.input) }}</div>
                  <div class="text-[10px] text-muted break-all">output: {{ jsonStr(lg.output) }}</div>
                </div>
                <div v-if="!wb.inspector.logs.length" class="text-[12px] text-muted text-center py-6">暂无日志，选择会话后加载</div>
              </div>
            </n-tab-pane>
            <n-tab-pane name="patch" tab="Patch">
              <div class="p-3 space-y-2">
                <div class="flex items-center justify-between">
                  <span class="text-[11px] text-muted">reflector patch</span>
                  <button class="text-[11px] text-muted hover:text-ink" @click="copyJson(wb.inspector.patch)">复制</button>
                </div>
                <n-code :code="pretty(wb.inspector.patch)" language="json" class="text-[11px]" />
                <div v-if="wb.weekLoadEntries.length" class="flex flex-wrap gap-1.5">
                  <span v-for="[k, v] in wb.weekLoadEntries" :key="k" class="text-[10px] px-2 py-0.5 rounded-full bg-[#ecfdf5] text-[#065f46] border border-[#a7f3d0]">{{ k }}: {{ v }}h</span>
                </div>
                <div v-if="wb.reallocateInfo" class="text-[11px] text-muted">重分配：{{ wb.reallocateInfo }}</div>
                <div v-if="!Object.keys(wb.inspector.patch || {}).length" class="text-[11px] text-muted">暂无 patch（critic 通过）</div>
              </div>
            </n-tab-pane>
          </n-tabs>
        </div>
      </aside>
      <div v-else class="hidden xl:flex w-[36px] shrink-0 flex-col items-center rounded-[16px] bg-surface/60 border border-hairline py-2 gap-2">
        <button class="text-[11px] text-muted hover:text-ink" aria-label="展开 Inspector" @click="rightCollapsed = false">«</button>
        <div class="text-[10px] tracking-widest text-muted" style="writing-mode: vertical-rl">INSPECTOR</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { NSelect, NTag, NTabs, NTabPane, NCode, useMessage } from 'naive-ui'
import { useWorkbenchStore } from '@/stores/workbench'
import { useSessionsStore } from '@/stores/sessions'
import { createPlan } from '@/api/plans'
import { listGoals, createGoal } from '@/api/goals'
import { extractErrorMessage } from '@/api/client'
import GraphCanvas from '@/components/GraphCanvas.vue'
import TranscriptView from '@/components/TranscriptView.vue'
import type { WorkbenchGraphNode } from '@/api/plans'
import type { PlanSessionItem } from '@/api/plans'

defineOptions({ name: 'AgentWorkbenchView' })

const route = useRoute()
const message = useMessage()
const wb = useWorkbenchStore()
const sessionsStore = useSessionsStore()

const rightCollapsed = ref(false)
const composer = ref('')
const selectedGoal = ref<number | null>(null)
const creating = ref(false)
const mode = ref<'single' | 'multi'>('multi')
const goalOpts = ref<Array<{ label: string; value: number }>>([])
const inputRef = ref<HTMLTextAreaElement | null>(null)

function statusClass(s: PlanSessionItem['status']): string {
  if (s === 'completed') return 'bg-[#ecfdf5] text-[#065f46] border-[#a7f3d0]'
  if (s === 'replan') return 'bg-[#fffbeb] text-[#92400e] border-[#fde68a]'
  return 'bg-[#eff6ff] text-[#1e40af] border-[#bfdbfe]'
}

function statusLabel(s: PlanSessionItem['status']): string {
  if (s === 'completed') return 'completed'
  if (s === 'replan') return 'replan'
  return 'running'
}

function modeClass(m: PlanSessionItem['mode']): string {
  return m === 'multi' ? 'bg-white text-ink border-hairline' : 'bg-[#f5f5f7] text-muted border-hairline'
}

function nodeClass(status: string): string {
  if (status === 'success') return 'bg-[#ecfdf5] text-[#065f46] border-[#a7f3d0]'
  if (status === 'running') return 'bg-[#fffbeb] text-[#92400e] border-[#fde68a]'
  if (status === 'error') return 'bg-[#fef2f2] text-[#991b1b] border-[#fecaca]'
  return 'bg-[#f5f5f7] text-muted border-[#e8e8ed]'
}

function relativeTime(v: string | null): string {
  if (!v) return '—'
  try {
    const t = new Date(v).getTime()
    if (Number.isNaN(t)) return v.slice(0, 10)
    const diff = Date.now() - t
    const m = Math.floor(diff / 60000)
    if (m < 1) return '刚刚'
    if (m < 60) return `${m} 分钟前`
    const h = Math.floor(m / 60)
    if (h < 24) return `${h} 小时前`
    const d = Math.floor(h / 24)
    if (d < 30) return `${d} 天前`
    return new Date(t).toLocaleDateString()
  } catch { return v.slice(0, 10) }
}

function pretty(v: unknown) {
  try { return JSON.stringify(v, null, 2) } catch { return String(v) }
}

function jsonStr(v: unknown) {
  try {
    const s = JSON.stringify(v)
    return s.length > 160 ? s.slice(0, 160) + '…' : s
  } catch { return String(v) }
}

function copyJson(v: unknown) {
  try { navigator.clipboard.writeText(JSON.stringify(v, null, 2)); message.success('已复制') } catch { message.warning('复制失败') }
}

function onSelectNode(node: WorkbenchGraphNode) {
  wb.selectNode(node)
}

function newSession() {
  wb.setTraceId('')
  composer.value = ''
  selectedGoal.value = null
  inputRef.value?.focus()
}

function replayTrace(trace: string) {
  wb.setTraceId(trace)
  wb.subscribe()
  void wb.fetchGraph()
  void wb.fetchInspector()
}

function replaySession(s: PlanSessionItem) {
  if (!s.trace_id) return
  replayTrace(s.trace_id)
}

function prevPage() {
  if (sessionsStore.page > 1) void sessionsStore.fetchPage(sessionsStore.page - 1)
}

function loadMore() {
  void sessionsStore.loadMore()
}

async function loadGoalOpts() {
  try {
    const res = await listGoals({ page: 1, size: 20 })
    goalOpts.value = res.data.items.map((g) => ({ label: `#${g.id} ${g.title}`, value: g.id }))
  } catch {}
}

async function send() {
  const text = composer.value.trim()
  if (!text || creating.value) return
  creating.value = true
  try {
    let gid = selectedGoal.value
    let display = goalOpts.value.find((o) => o.value === gid)?.label?.replace(/^#\d+\s*/, '') || text.slice(0, 30)
    if (gid == null) {
      const daysMatch = text.match(/(\d+)\s*天/)
      const days = daysMatch ? Number(daysMatch[1]) : 7
      const subject = text.includes('英语') ? '英语' : text.includes('数据结构') ? '数据结构' : undefined
      const deadline = new Date(Date.now() + days * 86400000).toISOString()
      const g = await createGoal({ title: text.slice(0, 30), description: text, deadline, subject, status: 'active' })
      gid = g.data.id
      display = text.slice(0, 30)
    }
    wb.pushUser(display)
    composer.value = ''
    const plan = await createPlan(gid, { hours_per_day: 2 }, mode.value)
    wb.setTraceId(plan.data.trace_id)
    wb.subscribe()
    void wb.fetchGraph()
    void loadGoalOpts()
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
  } finally {
    creating.value = false
  }
}

watch(() => wb.status, (s) => {
  if (s === 'completed' || s === 'failed') void sessionsStore.refresh()
})

onMounted(() => {
  void sessionsStore.fetchPage(1)
  void loadGoalOpts()
  const qTrace = route.query.trace
  if (typeof qTrace === 'string' && qTrace) replayTrace(qTrace)
  try {
    const raw = sessionStorage.getItem('agent:prefill')
    if (raw) {
      const p = JSON.parse(raw) as { text?: string; goal_id?: number; source?: string }
      if (p.text) composer.value = p.text
      if (typeof p.goal_id === 'number') selectedGoal.value = p.goal_id
      sessionStorage.removeItem('agent:prefill')
    }
  } catch {}
})
</script>
