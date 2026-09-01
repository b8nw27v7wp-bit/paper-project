<template>
  <div class="flex gap-6 min-h-[calc(100vh-240px)]">
    <!-- 会话侧栏 260px -->
    <aside class="hidden md:flex w-[260px] shrink-0 flex-col gap-3" aria-label="会话列表">
      <n-card class="apple-card" content-style="padding: 16px;">
        <n-button type="primary" block style="border-radius: 20px" @click="newSession" aria-label="新建会话">
          ＋ 新建会话
        </n-button>
        <div class="mt-3 flex gap-2">
          <n-input v-model:value="sessionSearch" placeholder="搜索会话…" clearable size="small" aria-label="搜索会话" />
        </div>
      </n-card>

      <n-card class="apple-card flex-1 flex flex-col" content-style="padding: 12px; display:flex; flex-direction:column; height: 100%;">
        <div class="text-[11px] tracking-widest font-medium text-muted px-2 py-1 flex items-center justify-between">
          <span>会话</span><span class="text-muted">{{ filteredSessions.length }}</span>
        </div>
        <div class="mt-1 space-y-1 overflow-auto flex-1 pr-1" role="listbox" aria-label="会话">
          <button
            v-for="s in filteredSessions"
            :key="s.id"
            role="option"
            :aria-selected="s.id === activeId"
            :class="['w-full text-left px-3 py-2.5 rounded-[12px] transition-colors', s.id === activeId ? 'bg-[#1d1d1f] text-white' : 'hover:bg-[#f5f5f7] text-ink']"
            @click="activeId = s.id"
          >
            <div class="text-[13px] font-medium tracking-[-0.01em] truncate">{{ s.title }}</div>
            <div :class="['text-[11px] truncate', s.id === activeId ? 'text-white/70' : 'text-muted']">{{ s.preview }}</div>
            <div :class="['text-[10px] mt-1', s.id === activeId ? 'text-white/50' : 'text-muted']">{{ s.time }}</div>
          </button>
          <div v-if="!filteredSessions.length" class="py-10 text-center">
            <div class="text-[13px] text-muted">暂无会话</div>
            <n-button size="small" style="border-radius: 20px" class="mt-2" @click="newSession">创建第一个</n-button>
          </div>
        </div>
        <div class="mt-3 pt-3 border-t border-[#f5f5f7] flex items-center justify-between text-[11px] tracking-wide text-muted">
          <span>⌘K 搜索</span><button class="hover:text-ink" @click="router.push('/goals')">去目标 →</button>
        </div>
      </n-card>
    </aside>

    <!-- 聊天主区 -->
    <div class="flex-1 min-w-0 flex flex-col">
      <!-- 顶部会话标题 -->
      <div class="flex items-center justify-between gap-3 mb-4">
        <div class="min-w-0">
          <h1 class="text-[20px] font-semibold tracking-[-0.02em] text-ink truncate">{{ activeSession?.title ?? '新会话' }}</h1>
          <p class="text-[11px] tracking-wide text-muted">与规划助手对话 · 输入目标一键生成计划 · 支持 / 指令</p>
        </div>
        <div class="flex items-center gap-2 shrink-0">
          <n-button size="small" style="border-radius: 20px" @click="newSession">新会话</n-button>
          <n-button size="small" strong secondary style="border-radius: 20px" @click="clearChat" :disabled="!messages.length">清空</n-button>
        </div>
      </div>

      <!-- 消息区 -->
      <n-card class="apple-card flex-1 flex flex-col" content-style="padding: 0; display:flex; flex-direction:column; height: 100%;">
        <div ref="scrollRef" class="flex-1 overflow-auto p-6 space-y-4" role="log" aria-live="polite" aria-label="对话">
          <div v-if="!messages.length" class="py-10 space-y-6">
            <div class="text-center">
              <div class="mx-auto w-10 h-10 rounded-[12px] bg-[#1d1d1f] text-white flex items-center justify-center text-[14px] font-semibold">AI</div>
              <div class="mt-3 text-[15px] font-semibold tracking-[-0.01em] text-ink">你好，我是学习规划助手</div>
              <p class="mt-1 text-[13px] leading-5 text-muted max-w-[480px] mx-auto">描述你的学习目标，我会为你拆解任务、排日历、关联知识图谱。试试下方示例。</p>
            </div>
            <div class="grid sm:grid-cols-2 gap-3 max-w-[640px] mx-auto">
              <button v-for="p in prompts" :key="p" class="text-left p-3 rounded-[16px] bg-[#f5f5f7] hover:bg-[#e8e8ed] transition-colors" @click="fillPrompt(p)">
                <div class="text-[13px] font-medium tracking-[-0.01em] text-ink">{{ p }}</div>
                <div class="text-[11px] tracking-wide text-muted mt-1">点击填入 → 发送</div>
              </button>
            </div>
          </div>

          <transition-group name="timeline">
            <div v-for="m in messages" :key="m.id" :class="['flex gap-3', m.role === 'user' ? 'justify-end' : 'justify-start']">
              <div :class="['max-w-[72%] rounded-[16px] px-4 py-3', m.role === 'user' ? 'bg-[#1d1d1f] text-white' : 'bg-[#f5f5f7] text-ink']">
                <div class="text-[13px] leading-5 whitespace-pre-wrap break-words">{{ m.content }}</div>
                <div :class="['mt-1 text-[10px] tracking-wide', m.role === 'user' ? 'text-white/60' : 'text-muted']">{{ m.time }} · {{ m.role === 'user' ? '你' : '助手' }}</div>
                <div v-if="m.citations?.length" class="mt-2 flex flex-wrap gap-1">
                  <span v-for="(c,i) in m.citations" :key="i" class="text-[10px] px-2 py-1 rounded-full bg-white/80 text-muted border border-black/5">引用 {{ i+1 }}</span>
                </div>
                <div v-if="m.role === 'assistant' && m.actions?.length" class="mt-2 flex gap-2">
                  <n-button v-for="a in m.actions" :key="a.label" size="tiny" :type="a.primary ? 'primary' : 'default'" style="border-radius: 20px" @click="a.onClick()">{{ a.label }}</n-button>
                </div>
              </div>
            </div>
          </transition-group>

          <div v-if="sending" class="flex gap-3 justify-start">
            <div class="bg-[#f5f5f7] rounded-[16px] px-4 py-3 text-[13px] text-muted flex items-center gap-2">
              <n-spin size="small" /> 正在规划…
            </div>
          </div>
        </div>

        <!-- 输入区 -->
        <div class="border-t border-[#f5f5f7] p-4 bg-white rounded-b-[16px]">
          <div class="flex items-end gap-2">
            <n-input
              v-model:value="input"
              type="textarea"
              :autosize="{ minRows: 1, maxRows: 4 }"
              placeholder="描述目标… 如：30天过六级，每天2小时 / 或输入 / 查看指令"
              clearable
              :disabled="sending"
              aria-label="对话输入"
              @keydown.enter.exact.prevent="send"
              @keydown.enter.meta.exact.prevent="send"
              class="flex-1"
            />
            <n-button type="primary" style="border-radius: 20px" :loading="sending" :disabled="!input.trim()" @click="send" aria-label="发送">发送</n-button>
          </div>
          <div class="mt-2 flex items-center justify-between text-[11px] tracking-wide text-muted">
            <span>Enter 发送 · Shift+Enter 换行 · / 指令 · ⌘K 命令</span>
            <span class="hidden sm:inline">已选会话 {{ activeId ? '1' : '0' }} · 共 {{ messages.length }} 条</span>
          </div>
        </div>
      </n-card>
    </div>
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'HomeView' })
import { ref, computed, nextTick, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { NCard, NButton, NInput, NSpin, useMessage } from 'naive-ui'
import { createGoal } from '@/api/goals'
import { createPlan } from '@/api/plans'
import { extractErrorMessage } from '@/api/client'

interface Session {
  id: string
  title: string
  preview: string
  time: string
  goalId?: number
}
interface ChatMsg {
  id: string
  role: 'user' | 'assistant'
  content: string
  time: string
  citations?: unknown[]
  actions?: Array<{ label: string; primary?: boolean; onClick: () => void }>
}

const router = useRouter()
const message = useMessage()
const sessionSearch = ref('')
const activeId = ref<string>('s1')
const sessions = ref<Session[]>([
  { id: 's1', title: '新会话', preview: '开始你的第一个目标', time: new Date().toLocaleDateString() },
  { id: 's2', title: '六级冲刺 30天', preview: '每天2小时 · 已生成12任务', time: '昨天' },
  { id: 's3', title: '数据结构刷题', preview: '图与树 · 7天', time: '3天前' },
])
const filteredSessions = computed(() => {
  const q = sessionSearch.value.trim().toLowerCase()
  if (!q) return sessions.value
  return sessions.value.filter(s => `${s.title} ${s.preview}`.toLowerCase().includes(q))
})
const activeSession = computed(() => sessions.value.find(s => s.id === activeId.value) ?? sessions.value[0])

const prompts = [
  '30天过六级，每天2小时，英语',
  '两周学完数据结构 图与树',
  '考研数学 60天冲刺，高等数学',
  '帮我把“背单词”拆成7天任务',
]

const messageMap = ref<Record<string, ChatMsg[]>>({ s1: [], s2: [], s3: [] })
const messages = computed<ChatMsg[]>({
  get: () => messageMap.value[activeId.value] ?? [],
  set: (v) => { messageMap.value[activeId.value] = v },
})
const input = ref('')
const sending = ref(false)
const scrollRef = ref<HTMLDivElement | null>(null)

function nowTime(): string { return new Date().toLocaleTimeString() }

function newSession(): void {
  const id = `s${Date.now()}`
  sessions.value.unshift({ id, title: '新会话', preview: '等待输入目标…', time: '刚刚' })
  messageMap.value[id] = []
  activeId.value = id
}

function clearChat(): void { messageMap.value[activeId.value] = []; messages.value = [] }

function fillPrompt(p: string): void { input.value = p }

function pushUser(text: string): void {
  const arr = messageMap.value[activeId.value] ?? []
  arr.push({ id: `m${Date.now()}-${Math.random().toString(36).slice(2,6)}`, role: 'user', content: text, time: nowTime() })
  messageMap.value[activeId.value] = arr
  const s = sessions.value.find(x => x.id === activeId.value)
  if (s) { s.title = text.slice(0, 16) || '新会话'; s.preview = text.slice(0, 24); s.time = '刚刚' }
  void nextTick(scrollToBottom)
}

function pushAssistant(text: string, opts?: Partial<ChatMsg>): void {
  const arr = messageMap.value[activeId.value] ?? []
  arr.push({ id: `a${Date.now()}-${Math.random().toString(36).slice(2,6)}`, role: 'assistant', content: text, time: nowTime(), ...opts })
  messageMap.value[activeId.value] = arr
  void nextTick(scrollToBottom)
}

function scrollToBottom(): void {
  const el = scrollRef.value
  if (el) el.scrollTop = el.scrollHeight
}

async function send(): Promise<void> {
  const text = input.value.trim()
  if (!text) return
  if (text.startsWith('/')) { handleSlash(text); return }
  pushUser(text)
  input.value = ''
  sending.value = true
  try {
    // 尝试解析为目标创建：若包含“天”或“过”则走真实规划链路
    const isGoalLike = /过|天|学习|刷题|冲刺/.test(text)
    if (isGoalLike) {
      // 提取科目与天数（简易）
      const subject = text.includes('英语') ? '英语' : text.includes('数据结构') ? '数据结构' : undefined
      const daysMatch = text.match(/(\d+)\s*天/)
      const days = daysMatch ? Number(daysMatch[1]) : 7
      const deadline = new Date(Date.now() + days * 86400000).toISOString()
      try {
        const g = await createGoal({ title: text.slice(0, 30), description: text, deadline, subject, status: 'active' })
        const goalId = (g.data as unknown as { id: number }).id
        const s = sessions.value.find(x => x.id === activeId.value)
        if (s) s.goalId = goalId
        pushAssistant(`已创建目标「${text.slice(0, 20)}」· 截止 ${deadline.slice(0,10)}，正在生成计划…`)
        const plan = await createPlan(goalId, { hours_per_day: 2 })
        const tasks = (plan.data.tasks as unknown as Array<{ title: string }>) ?? []
        pushAssistant(`已生成 ${tasks.length} 个任务，已写入日历。`, {
          citations: (plan.data.citations as unknown[] ?? []) as unknown[],
          actions: [
            { label: '查看日历', primary: true, onClick: () => router.push(`/calendar?goal_id=${goalId}`) },
            { label: '去目标', onClick: () => router.push('/goals') },
          ],
        })
        // 更新会话预览
        const sess = sessions.value.find(x => x.id === activeId.value)
        if (sess) sess.preview = `已生成 ${tasks.length} 任务`
        return
      } catch (e: unknown) {
        // 回退为普通对话
        pushAssistant(`创建目标失败：${extractErrorMessage(e)}，已作为普通对话记录。`)
        return
      }
    }
    // 普通对话回退（可接 LLM）
    await new Promise(r => setTimeout(r, 600))
    pushAssistant(`收到：「${text}」\n我可以帮你拆解为每日任务并排入日历。试试输入“30天过六级，每天2小时”。`, {
      actions: [{ label: '一键规划示例', primary: true, onClick: () => { input.value = '30天过六级，每天2小时'; void send() } }],
    })
  } finally {
    sending.value = false
  }
}

function handleSlash(text: string): void {
  const cmd = text.slice(1).trim().toLowerCase()
  if (cmd === 'clear' || cmd === '清空') { clearChat(); input.value = ''; return }
  if (cmd === 'help' || cmd === '帮助') {
    pushUser(text)
    input.value = ''
    pushAssistant('可用指令：\n/clear 清空\n/help 帮助\n/go 目标页\n/calendar 日历')
    return
  }
  if (cmd.startsWith('go')) { const to = cmd.split(' ')[1] ?? 'goals'; void router.push(`/${to}`); input.value = ''; return }
  pushUser(text)
  input.value = ''
  pushAssistant(`未知指令：${text}，输入 /help 查看`)
}

watch(activeId, () => { void nextTick(scrollToBottom) })

onMounted(() => {
  try {
    const raw = localStorage.getItem('planner:sessions')
    if (raw) sessions.value = JSON.parse(raw) as Session[]
    const rawMap = localStorage.getItem('planner:messages')
    if (rawMap) messageMap.value = JSON.parse(rawMap) as Record<string, ChatMsg[]>
  } catch {}
  watch(sessions, (v) => { try { localStorage.setItem('planner:sessions', JSON.stringify(v.slice(0, 20))) } catch {} }, { deep: true })
  watch(messageMap, (v) => { try { localStorage.setItem('planner:messages', JSON.stringify(v)) } catch {} }, { deep: true })
})
</script>
