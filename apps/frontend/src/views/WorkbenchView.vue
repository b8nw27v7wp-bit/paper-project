<template>
  <div class="flex gap-4 min-h-[calc(100vh-220px)]">
    <!-- 左 260 会话列表，可收起 -->
    <aside v-if="!leftCollapsed" class="w-[260px] shrink-0 flex flex-col gap-3" aria-label="会话列表">
      <n-card class="apple-card" content-style="padding: 16px;">
        <n-button type="primary" block style="border-radius: 20px" @click="newSession" aria-label="新建会话">＋ 新建会话</n-button>
        <div class="mt-3">
          <n-input v-model:value="sessionSearch" placeholder="搜索会话…" clearable size="small" aria-label="搜索会话" />
        </div>
      </n-card>
      <n-card class="apple-card flex-1 flex flex-col" content-style="padding: 12px; display:flex; flex-direction:column; height: 100%;">
        <div class="text-[11px] tracking-widest font-medium text-muted px-2 py-1 flex items-center justify-between">
          <span>会话 ({{ filteredSessions.length }})</span>
          <n-button text size="tiny" @click="leftCollapsed = true" aria-label="收起会话">‹</n-button>
        </div>
        <div class="mt-1 space-y-1 overflow-auto flex-1 pr-1" role="listbox" aria-label="会话">
          <button
            v-for="s in filteredSessions"
            :key="s.traceId || s.id"
            role="option"
            :aria-selected="activeTrace === (s.traceId || s.id)"
            :class="['w-full text-left px-3 py-2.5 rounded-[12px] transition-colors', activeTrace === (s.traceId || s.id) ? 'bg-[#1d1d1f] text-white' : 'hover:bg-[#f5f5f7] text-ink']"
            @click="selectSession(s)"
          >
            <div class="text-[13px] font-medium tracking-[-0.01em] truncate">{{ s.title }}</div>
            <div :class="['text-[11px] truncate', activeTrace === (s.traceId || s.id) ? 'text-white/70' : 'text-muted']">{{ s.preview }}</div>
            <div :class="['text-[10px] mt-1 font-mono', activeTrace === (s.traceId || s.id) ? 'text-white/50' : 'text-muted']">{{ (s.traceId || s.id).slice(0, 8) }}</div>
          </button>
          <div v-if="!filteredSessions.length" class="py-8 text-center text-[13px] text-muted">
            <div>暂无会话</div>
            <div class="mt-3 flex flex-col gap-2">
              <n-button size="small" block style="border-radius: 20px" @click="applyExample('30天过六级，每天2小时，英语')">30天过六级</n-button>
              <n-button size="small" block style="border-radius: 20px" @click="applyExample('两周学完数据结构，图与树，每天3小时')">两周数据结构</n-button>
              <n-button size="small" block style="border-radius: 20px" @click="applyExample('考研数学60天，高等数学，每天2小时')">考研数学60天</n-button>
            </div>
            <div v-if="memoryEmpty" class="mt-3 text-[11px] text-muted">
              先导入课表/PDF
              <a class="ml-1 text-[#0071e3] cursor-pointer hover:underline" @click="goRag">去导入 →</a>
              <router-link to="/rag" class="ml-1 text-[#0071e3] hover:underline">/rag</router-link>
            </div>
          </div>
        </div>
        <div class="mt-3 pt-3 border-t border-[#f5f5f7] text-[11px] tracking-wide text-muted flex items-center justify-between">
          <span>共 {{ sessions.length }} 会话</span>
          <button class="hover:text-ink" @click="goGoals">去目标 →</button>
        </div>
      </n-card>
    </aside>
    <div v-else class="w-[36px] shrink-0 flex flex-col items-center gap-2 pt-2">
      <n-button size="small" style="border-radius: 20px" @click="leftCollapsed = false" aria-label="展开会话">›</n-button>
      <div class="text-[10px] tracking-widest text-muted" style="writing-mode: vertical-rl">会话</div>
    </div>

    <!-- 中 Chat 流 -->
    <div class="flex-1 min-w-0 flex flex-col gap-4">
      <div class="flex items-center justify-between">
        <div>
          <div class="flex items-center gap-2">
            <h1 class="text-[18px] font-semibold tracking-[-0.02em] text-ink">Agent 工作台</h1>
            <n-tag size="small" type="info">SystemAgent studying-planner</n-tag>
            <n-button size="small" style="border-radius: 20px" @click="showManifest = true">Manifest</n-button>
          </div>
          <p class="text-[11px] tracking-wide text-muted">Chat + Graph + Inspector · 6节点DAG · trace_id 贯穿 · SSE 8事件</p>
        </div>
        <div class="flex items-center gap-2">
          <n-tag v-if="wb.status === 'running'" type="warning" size="small">运行中</n-tag>
          <n-tag v-else-if="wb.status === 'completed'" type="success" size="small">已完成</n-tag>
          <n-tag v-else size="small">空闲</n-tag>
          <n-button size="small" style="border-radius: 20px" @click="wb.unsubscribe()" :disabled="wb.status !== 'running'">停止</n-button>
          <n-button size="small" style="border-radius: 20px" @click="refreshAll" :disabled="!wb.traceId">刷新</n-button>
        </div>
      </div>

      <n-modal v-model:show="showManifest" preset="card" title="SystemAgent Manifest" style="width: 520px" :bordered="false" segmented>
        <div class="space-y-3">
          <div class="flex items-center gap-2">
            <n-tag type="info" size="small">{{ wb.manifest?.name || 'studying-planner' }}</n-tag>
            <span class="text-[12px] text-muted">{{ wb.manifest?.version ? `v${wb.manifest.version}` : 'v0.3.0' }}</span>
          </div>
          <div class="text-[12px] text-ink">{{ wb.manifest?.description || '多智能体协作的学习规划智能体' }}</div>
          <div class="text-[12px]">tools 数量：<span class="font-semibold">{{ wb.manifest?.tools?.length ?? 0 }}</span></div>
          <div v-if="wb.manifest?.tools?.length" class="space-y-2">
            <div class="text-[11px] text-muted">按 sub_agents 分组（6组）：</div>
            <n-collapse>
              <n-collapse-item v-for="g in groupedTools" :key="g.agent" :title="`${g.agent} (${g.tools.length})`" :name="g.agent">
                <div class="flex flex-wrap gap-2">
                  <n-tag v-for="t in g.tools" :key="t.name" size="small" :title="t.description || t.label || t.name">{{ t.label || t.name }}</n-tag>
                  <span v-if="!g.tools.length" class="text-[11px] text-muted">暂无工具</span>
                </div>
                <div class="mt-2 space-y-1">
                  <div v-for="t in g.tools" :key="t.name + '-schema'" class="text-[11px] text-muted break-all">
                    <span class="font-medium text-ink">{{ t.label || t.name }}</span>
                    <span v-if="t.schema"> · schema: {{ JSON.stringify(t.schema).slice(0, 160) }}</span>
                    <span v-if="t.description"> — {{ t.description }}</span>
                  </div>
                </div>
              </n-collapse-item>
            </n-collapse>
            <div class="flex flex-wrap gap-2 mt-2">
              <n-tag v-for="sa in wb.manifest?.sub_agents || []" :key="sa" size="small" type="success">{{ sa }}</n-tag>
              <n-tag type="info" size="small">sub_agents 6</n-tag>
            </div>
          </div>
          <div v-else class="text-[11px] text-muted">暂无工具数据</div>
        </div>
      </n-modal>

      <!-- Graph 区域 -->
      <n-card class="apple-card" content-style="padding: 16px;">
        <div class="flex items-center justify-between mb-2">
          <div class="text-[11px] tracking-widest font-medium text-muted">6节点 DAG · ECharts Graph · 点击穿透 Inspector</div>
          <div class="text-[11px] text-muted">rewrites 回边 <span class="text-[#ef4444]">replan</span> 高亮</div>
        </div>
        <GraphCanvas :nodes="wb.graph.nodes" :edges="wb.graph.edges" :status="wb.graph.status" @select="onSelectNode" />
        <div class="mt-2 flex flex-wrap gap-2">
          <span v-for="n in wb.graph.nodes" :key="n.id" :class="['text-[11px] px-2 py-1 rounded-full border', colorFor(n.status)]">{{ n.name }}:{{ n.status }}</span>
        </div>
      </n-card>

      <!-- 项目规划：展示 reflector patch 中的周/日负荷 — 三端统一 PLANNER_API 反馈闭环可见 -->
      <n-card class="apple-card" content-style="padding: 12px;">
        <div class="flex items-center justify-between">
          <div class="text-[11px] tracking-widest font-medium text-muted">项目规划</div>
          <div class="flex items-center gap-2">
            <n-tag v-if="weekLoadEntries.length" size="small" type="info">周负荷 {{ weekLoadEntries.length }} 段</n-tag>
            <n-button size="tiny" style="border-radius: 12px" @click="router.push('/reflection')">去反思 →</n-button>
          </div>
        </div>
        <div v-if="weekLoadEntries.length" class="mt-2 flex flex-wrap gap-2">
          <n-tag v-for="[k, v] in weekLoadEntries" :key="k" size="small" type="success">{{ k }}: {{ v }}h</n-tag>
        </div>
        <div v-else class="mt-2 text-[11px] text-muted">暂无周负荷数据（等待 reflector patch.week_load）</div>
        <div v-if="dailyLoadEntries.length" class="mt-3">
          <div class="text-[11px] tracking-wide text-muted mb-1">日负荷</div>
          <div class="flex flex-wrap gap-2">
            <n-tag v-for="[k, v] in dailyLoadEntries" :key="k" size="small">{{ k }}: {{ v }}h</n-tag>
          </div>
        </div>
        <div v-if="reallocateInfo" class="mt-2 text-[11px] text-muted">重分配：{{ reallocateInfo }}</div>
      </n-card>

      <!-- Chat 气泡 + 可折叠子调用树 -->
      <n-card class="apple-card flex-1 flex flex-col" content-style="padding: 0; display:flex; flex-direction:column; height: 100%;">
        <div ref="scrollRef" class="flex-1 overflow-auto p-6 space-y-3" role="log" aria-live="polite" aria-label="对话">
          <div v-if="!wb.messages.length" class="py-8 text-center">
            <div class="mx-auto w-10 h-10 rounded-[12px] bg-[#1d1d1f] text-white flex items-center justify-center text-[14px] font-semibold">WB</div>
            <div class="mt-3 text-[14px] font-semibold text-ink">双轨工作台就绪</div>
            <p class="mt-1 text-[12px] text-muted">选择左侧会话或下方输入目标一键生成计划，6节点协作流将在此展示</p>
            <div class="mt-4 flex gap-2 justify-center flex-wrap">
              <n-button size="small" style="border-radius: 20px" @click="applyExample('30天过六级，每天2小时，英语')">30天过六级</n-button>
              <n-button size="small" style="border-radius: 20px" @click="applyExample('两周学完数据结构，图与树，每天3小时')">两周数据结构</n-button>
              <n-button size="small" style="border-radius: 20px" @click="applyExample('考研数学60天，高等数学，每天2小时')">考研数学60天</n-button>
              <n-button size="small" style="border-radius: 20px" @click="goGoals">去创建目标</n-button>
            </div>
            <div v-if="memoryEmpty" class="mt-3 text-[11px] text-muted">
              先导入课表/PDF
              <a class="ml-1 text-[#0071e3] cursor-pointer hover:underline" @click="goRag">去导入 →</a>
              <router-link to="/rag" class="ml-1 text-[#0071e3] hover:underline">/rag</router-link>
            </div>
          </div>

          <div v-for="m in wb.messages" :key="m.id" :class="['flex gap-2', m.role === 'user' ? 'justify-end' : 'justify-start']">
            <div :class="['max-w-[78%] rounded-[16px] px-4 py-3', m.role === 'user' ? 'bg-[#1d1d1f] text-white' : m.role === 'system' ? 'bg-[#fef3c7] text-ink border border-amber-200' : 'bg-[#f5f5f7] text-ink']">
              <div class="flex items-center gap-2 mb-1">
                <span v-if="m.agent" class="text-[10px] tracking-widest px-1.5 py-0.5 rounded-full bg-white/80 text-muted border">{{ m.agent }}</span>
                <span class="text-[10px] text-muted">{{ m.time }}</span>
              </div>
              <div class="text-[13px] leading-5 whitespace-pre-wrap break-words">{{ m.content }}</div>
              <!-- 可折叠子调用树 tool_call_start/end -->
              <div v-if="m.toolCalls?.length" class="mt-2">
                <button class="text-[11px] tracking-wide text-muted hover:text-ink flex items-center gap-1" @click="m.collapsed = !m.collapsed" :aria-expanded="!m.collapsed">
                  <span>{{ m.collapsed ? '▸' : '▾' }}</span> tool 调用树 ({{ m.toolCalls.length }})
                </button>
                <div v-if="!m.collapsed" class="mt-2 rounded-[12px] bg-white border border-[#e8e8ed] p-2 space-y-1">
                  <div v-for="(tc, idx) in m.toolCalls" :key="idx" class="rounded-[8px] bg-[#f5f5f7] px-2 py-1.5">
                    <div class="text-[11px] font-medium text-ink flex items-center justify-between">
                      <span>🔧 {{ tc.tool }}</span>
                      <n-button size="tiny" style="border-radius: 12px" @click="copyJson(tc)">复制</n-button>
                    </div>
                    <div v-if="tc.args" class="text-[11px] text-muted mt-1 break-all">args: {{ jsonStr(tc.args) }}</div>
                    <div v-if="tc.result !== undefined" class="text-[11px] text-muted mt-1 break-all">result: {{ jsonStr(tc.result) }}</div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div v-if="wb.status === 'running'" class="flex gap-3 justify-start">
            <div class="bg-[#f5f5f7] rounded-[16px] px-4 py-3 text-[13px] text-muted flex items-center gap-2">
              <n-spin size="small" /> 6节点协作中… 首字节 &lt;2s
            </div>
          </div>
        </div>

        <!-- 输入区：支持从目标一键规划 -->
        <div class="border-t border-[#f5f5f7] p-4 bg-white rounded-b-[16px]">
          <div class="flex gap-2">
            <n-select v-model:value="selectedGoal" :options="goalOpts" placeholder="选择目标一键规划" clearable style="flex: 1" aria-label="选择目标" />
            <n-button type="primary" style="border-radius: 20px" :loading="creating" @click="createFromGoal" :disabled="!selectedGoal">生成规划</n-button>
          </div>
          <div class="mt-2 flex gap-2">
            <n-input v-model:value="chatInput" type="textarea" :autosize="{ minRows: 1, maxRows: 3 }" placeholder="或直接描述目标… 如：两周学完数据结构 图与树" clearable aria-label="对话输入" @keydown.enter.exact.prevent="sendChat" />
            <n-button style="border-radius: 20px" :loading="creating" :disabled="!chatInput.trim()" @click="sendChat">发送</n-button>
          </div>
          <div class="mt-2 text-[11px] tracking-wide text-muted">trace_id: <span class="font-mono">{{ wb.traceId || '—' }}</span> · Last-Event-ID: {{ wb.lastEventId || '0' }} · 双轨与日历/甘特同后端</div>
        </div>
      </n-card>
    </div>

    <!-- 右 360 Inspector，可收起 -->
    <aside v-if="!rightCollapsed" class="w-[360px] shrink-0 flex flex-col gap-3" aria-label="Inspector">
      <n-card class="apple-card" content-style="padding: 12px;">
        <div class="flex items-center justify-between">
          <div class="text-[11px] tracking-widest font-medium text-muted">Inspector</div>
          <div class="flex items-center gap-1">
            <n-button text size="tiny" @click="rightCollapsed = true" aria-label="收起 Inspector">›</n-button>
          </div>
        </div>
        <div class="text-[10px] text-muted">点击 Graph 节点穿透 · JsonViewer + 复制 · 首绘 &lt;300ms</div>
      </n-card>

      <n-card class="apple-card flex-1 flex flex-col overflow-hidden" content-style="padding: 0; display:flex; flex-direction:column; height: 100%;">
        <n-tabs type="line" animated style="--n-tab-padding: 12px;">
          <n-tab-pane name="state" tab="State">
            <div class="p-3 space-y-2 max-h-[32vh] overflow-auto">
              <div class="flex items-center justify-between">
                <span class="text-[11px] tracking-wide text-muted">当前 state 快照</span>
                <n-button size="tiny" style="border-radius: 12px" @click="copyJson(wb.inspector.state)">复制</n-button>
              </div>
              <n-code :code="pretty(wb.inspector.state)" language="json" class="text-[11px]" />
            </div>
          </n-tab-pane>
          <n-tab-pane name="logs" tab="Logs">
            <div class="p-3 space-y-2 max-h-[42vh] overflow-auto">
              <div class="flex items-center justify-between">
                <span class="text-[11px] tracking-wide text-muted">agent_run_log ({{ wb.inspector.logs.length }}) 按 trace_id 聚合</span>
                <n-button size="tiny" style="border-radius: 12px" @click="copyJson(wb.inspector.logs)">复制</n-button>
              </div>
              <div v-for="lg in wb.inspector.logs" :key="lg.id" class="rounded-[12px] bg-[#f5f5f7] p-2">
                <div class="text-[11px] font-medium text-ink">{{ lg.agent_name }} <span class="text-muted font-normal">{{ lg.created_at?.slice(11, 19) }}</span></div>
                <div class="text-[11px] text-muted mt-1">input: {{ jsonStr(lg.input) }}</div>
                <div class="text-[11px] text-muted">output: {{ jsonStr(lg.output) }}</div>
                <div v-if="lg.tool_calls?.length" class="text-[11px] text-muted">tools: {{ jsonStr(lg.tool_calls) }}</div>
              </div>
              <div v-if="!wb.inspector.logs.length" class="text-[12px] text-muted text-center py-6">暂无日志，选择会话后加载</div>
            </div>
          </n-tab-pane>
          <n-tab-pane name="patch" tab="Patch">
            <div class="p-3 space-y-2 max-h-[32vh] overflow-auto">
              <div class="flex items-center justify-between">
                <span class="text-[11px] tracking-wide text-muted">reflector patch · 前后对比</span>
                <n-button size="tiny" style="border-radius: 12px" @click="copyJson(wb.inspector.patch)">复制</n-button>
              </div>
              <n-code :code="pretty(wb.inspector.patch)" language="json" class="text-[11px]" />
              <div v-if="!Object.keys(wb.inspector.patch || {}).length" class="text-[11px] text-muted">暂无 patch（critic 通过）</div>
            </div>
          </n-tab-pane>
        </n-tabs>
      </n-card>
      <div class="text-[11px] tracking-wide text-muted text-center">与 DB 一致 · cache:graph 5m 优先</div>
    </aside>
    <div v-else class="w-[36px] shrink-0 flex flex-col items-center gap-2 pt-2">
      <n-button size="small" style="border-radius: 20px" @click="rightCollapsed = false" aria-label="展开 Inspector">‹</n-button>
      <div class="text-[10px] tracking-widest text-muted" style="writing-mode: vertical-rl">Inspector</div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'WorkbenchView' })
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { NCard, NButton, NInput, NSelect, NTag, NSpin, NTabs, NTabPane, NCode, NModal, NCollapse, NCollapseItem, useMessage } from 'naive-ui'
import { useWorkbenchStore } from '@/stores/workbench'
import GraphCanvas from '@/components/GraphCanvas.vue'
import { createPlan } from '@/api/plans'
import { listGoals } from '@/api/goals'
import { createGoal } from '@/api/goals'
import { extractErrorMessage } from '@/api/client'
import type { WorkbenchGraphNode } from '@/api/plans'
import { listChunks } from '@/api/rag'

const router = useRouter()
const message = useMessage()
const wb = useWorkbenchStore()

const leftCollapsed = ref(false)
const rightCollapsed = ref(false)
const sessionSearch = ref('')
const chatInput = ref('')
const selectedGoal = ref<number | null>(null)
const creating = ref(false)
const goalOpts = ref<Array<{ label: string; value: number }>>([])
const scrollRef = ref<HTMLDivElement | null>(null)
const showManifest = ref(false)

interface SessionItem { id: string; traceId: string; title: string; preview: string }
const sessions = ref<SessionItem[]>([
  { id: 's1', traceId: '', title: '新会话', preview: '选择目标生成规划' },
])

const activeTrace = computed(() => wb.traceId || '')

const filteredSessions = computed(() => {
  const q = sessionSearch.value.trim().toLowerCase()
  if (!q) return sessions.value
  return sessions.value.filter((s) => `${s.title} ${s.preview} ${s.traceId}`.toLowerCase().includes(q))
})

const weekLoadEntries = computed<[string, number][]>(() => {
  const patch = (wb.inspector.patch || {}) as Record<string, unknown>
  const wl = patch.week_load as Record<string, number> | undefined
  if (wl && typeof wl === 'object' && !Array.isArray(wl)) {
    return Object.entries(wl).filter(([, v]) => typeof v === 'number') as [string, number][]
  }
  return []
})

const dailyLoadEntries = computed<[string, number][]>(() => {
  const patch = (wb.inspector.patch || {}) as Record<string, unknown>
  const dl = patch.daily_load as Record<string, number> | undefined
  if (dl && typeof dl === 'object' && !Array.isArray(dl)) {
    return Object.entries(dl).filter(([, v]) => typeof v === 'number') as [string, number][]
  }
  return []
})

const reallocateInfo = computed<string>(() => {
  const patch = (wb.inspector.patch || {}) as Record<string, unknown>
  const ra = patch.reallocate as Record<string, unknown> | undefined
  if (ra && typeof ra === 'object' && ra.from && ra.to) return `${String(ra.from)} → ${String(ra.to)} ${String((ra as Record<string, unknown>).hours ?? '')}h`
  const instr = patch.instructions as unknown
  if (Array.isArray(instr) && instr.length) return String(instr[0])
  return ''
})

const memoryEmpty = ref(false)
const SUB_AGENTS = ['planner', 'researcher', 'executor', 'critic', 'mentor', 'reflector'] as const
const groupedTools = computed(() => {
  const tools = (wb.manifest?.tools ?? []) as Array<{ name: string; label?: string; description?: string; schema?: unknown }>
  return (SUB_AGENTS as readonly string[]).map((agent) => {
    const lower = agent.toLowerCase()
    let matched = tools.filter((t) => {
      const hay = `${t.name} ${t.label ?? ''} ${t.description ?? ''}`.toLowerCase()
      return hay.includes(lower)
    })
    if (!matched.length && tools.length) {
      const idx = (SUB_AGENTS as readonly string[]).indexOf(agent)
      if (idx >= 0 && idx < tools.length) matched = [tools[idx]!]
    }
    return { agent, tools: matched, label: agent }
  })
})

function goGoals() { void router.push('/goals') }
function goRag() { void router.push('/rag') }
function applyExample(text: string) { chatInput.value = text; void sendChat() }
async function checkMemoryEmpty() {
  try {
    const res = await listChunks({ page: 1, size: 1 })
    memoryEmpty.value = (res.data.total ?? 0) === 0
  } catch { memoryEmpty.value = false }
}

function newSession() {
  const id = `s${Date.now()}`
  sessions.value.unshift({ id, traceId: '', title: '新会话', preview: '等待输入目标…' })
  wb.reset()
  wb.setTraceId('')
}

function selectSession(s: SessionItem) {
  if (s.traceId) {
    wb.setTraceId(s.traceId)
    void wb.fetchGraph()
    void wb.fetchInspector()
    wb.subscribe()
  } else {
    wb.reset()
  }
}

function colorFor(status: string) {
  if (status === 'success') return 'bg-[#ecfdf5] text-[#065f46] border-[#a7f3d0]'
  if (status === 'running') return 'bg-[#fffbeb] text-[#92400e] border-[#fde68a]'
  if (status === 'error') return 'bg-[#fef2f2] text-[#991b1b] border-[#fecaca]'
  return 'bg-[#f5f5f7] text-muted border-[#e8e8ed]'
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
  const t0 = performance.now()
  wb.selectNode(node)
  const elapsed = performance.now() - t0
  if (elapsed > 100) console.warn(`selectNode ${elapsed.toFixed(1)}ms >100ms`)
  message.info(`已选中 ${node.name} · 穿透至 Inspector`)
}

async function refreshAll() {
  await Promise.all([wb.fetchGraph(), wb.fetchInspector()])
  message.success('已刷新 Graph/Inspector')
}

async function loadGoalOpts() {
  try {
    const res = await listGoals({ page: 1, size: 20 })
    goalOpts.value = res.data.items.map((g) => ({ label: `#${g.id} ${g.title}`, value: g.id }))
  } catch {}
}

async function createFromGoal() {
  if (!selectedGoal.value) return
  creating.value = true
  try {
    const t0 = performance.now()
    const res = await createPlan(selectedGoal.value, { hours_per_day: 2 })
    const trace = res.data.trace_id
    wb.setTraceId(trace)
    // 更新会话列表
    const title = goalOpts.value.find((o) => o.value === selectedGoal.value)?.label || `目标 ${selectedGoal.value}`
    sessions.value[0] = { id: `s${Date.now()}`, traceId: trace, title, preview: `已生成 ${res.data.tasks?.length || 0} 任务` }
    // 订阅 SSE（首字节 <2s 由后端保障）
    wb.subscribe()
    void wb.fetchGraph()
    const elapsed = performance.now() - t0
    if (elapsed > 300) console.warn(`Inspector首绘 ${elapsed.toFixed(1)}ms`)
    message.success(`已生成规划 trace=${trace.slice(0, 8)}`)
    void nextTick(() => { const el = scrollRef.value; if (el) el.scrollTop = el.scrollHeight })
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
  } finally { creating.value = false }
}

async function sendChat() {
  const text = chatInput.value.trim()
  if (!text) return
  // 将聊天输入作为目标标题快速创建 Goal + Plan（演示用）
  creating.value = true
  try {
    // 解析天数与科目
    const subject = text.includes('英语') ? '英语' : text.includes('数据结构') ? '数据结构' : undefined
    const daysMatch = text.match(/(\d+)\s*天/)
    const days = daysMatch ? Number(daysMatch[1]) : 7
    const deadline = new Date(Date.now() + days * 86400000).toISOString()
    wb.pushAssistant(text, { agent: 'user' } as unknown as { agent: string })
    chatInput.value = ''
    const g = await createGoal({ title: text.slice(0, 30), description: text, deadline, subject, status: 'active' })
    const goalId = (g.data as unknown as { id: number }).id
    const plan = await createPlan(goalId, { hours_per_day: 2 })
    const trace = plan.data.trace_id
    wb.setTraceId(trace)
    const title = text.slice(0, 16)
    sessions.value.unshift({ id: `s${Date.now()}`, traceId: trace, title, preview: `已生成 ${plan.data.tasks?.length || 0} 任务` })
    wb.subscribe()
    void wb.fetchGraph()
    void loadGoalOpts()
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
  } finally { creating.value = false }
}

async function quickDemo() {
  chatInput.value = '30天过六级，每天2小时，英语'
  await sendChat()
}

watch(() => wb.messages.length, () => {
  void nextTick(() => { const el = scrollRef.value; if (el) el.scrollTop = el.scrollHeight })
})

watch(() => wb.traceId, (id) => {
  if (id) {
    try { localStorage.setItem('workbench:traceId', id) } catch {}
  }
})

onMounted(() => {
  void loadGoalOpts()
  void wb.fetchManifest()
  void checkMemoryEmpty()
  try {
    const saved = localStorage.getItem('workbench:traceId')
    if (saved) {
      wb.setTraceId(saved)
      // 若本地有会话，加入列表便于回放
      sessions.value.unshift({ id: 'saved', traceId: saved, title: '上次会话', preview: `trace ${saved.slice(0, 8)}` })
      void wb.fetchGraph()
      void wb.fetchInspector()
      wb.subscribe()
    }
  } catch {}
  // 性能埋点：Graph 渲染应 <500ms，Inspector首绘<300ms，已在子组件内校验
})
</script>

<style scoped>
.apple-card { border-radius: 16px; }
</style>
