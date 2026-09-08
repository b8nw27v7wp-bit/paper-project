<template>
  <n-modal :show="show" preset="card" title="命令面板" style="width: 560px; border-radius: 16px" :closable="true" @update:show="v => emit('update:show', v)">
    <div role="dialog" aria-modal="true" aria-label="命令面板" class="space-y-3">
      <div class="flex items-center gap-2">
        <n-input v-model:value="query" placeholder="输入命令或搜索…（上下选择，回车执行，Esc 关闭）" clearable autofocus aria-label="命令搜索输入" @keydown="onKey" />
        <span class="text-[11px] tracking-wide text-muted hidden sm:inline">Ctrl+K</span>
      </div>
      <div v-if="hasQuery" class="space-y-3" aria-label="数据搜索结果">
        <div v-if="searching" class="py-4 text-center text-[13px] text-muted" role="status">搜索中…</div>
        <div v-else>
          <div v-if="searchError" class="py-2 text-center text-[12px] text-muted" role="alert">{{ searchError }}</div>
          <div v-if="!hasData && !searchError" class="py-4 text-center text-[13px] text-muted" role="status">无匹配数据</div>
          <div v-if="goalHits.length" class="space-y-1">
            <div class="px-3 pt-1 text-[11px] tracking-widest font-medium text-muted">目标</div>
            <button
              v-for="g in goalHits"
              :key="'goal-' + g.id"
              class="w-full text-left px-3 py-2 rounded-[12px] hover:bg-[var(--c-surface)] text-ink transition-colors"
              @click="goGoal(g.id)"
            >
              <span class="text-[12px] font-medium tracking-[-0.01em]">#{{ g.id }} {{ g.title }}</span>
              <span class="ml-2 text-[11px] tracking-wide text-muted">去目标</span>
            </button>
          </div>
          <div v-if="taskHits.length" class="space-y-1">
            <div class="px-3 pt-1 text-[11px] tracking-widest font-medium text-muted">任务</div>
            <button
              v-for="t in taskHits"
              :key="'task-' + t.id"
              class="w-full text-left px-3 py-2 rounded-[12px] hover:bg-[var(--c-surface)] text-ink transition-colors"
              @click="goTask()"
            >
              <span class="text-[12px] font-medium tracking-[-0.01em]">#{{ t.id }} {{ t.title }}</span>
              <span class="ml-2 text-[11px] tracking-wide text-muted">去日历</span>
            </button>
          </div>
          <div v-if="memHits.length" class="space-y-1">
            <div class="px-3 pt-1 text-[11px] tracking-widest font-medium text-muted">记忆</div>
            <button
              v-for="m in memHits"
              :key="'mem-' + m.id"
              class="w-full text-left px-3 py-2 rounded-[12px] hover:bg-[var(--c-surface)] text-ink transition-colors"
              @click="goMemory()"
            >
              <span class="text-[12px] tracking-[-0.01em] text-ink line-clamp-1">{{ m.content }}</span>
              <span class="ml-2 text-[11px] tracking-wide text-muted">去知识库</span>
            </button>
          </div>
        </div>
      </div>
      <div class="max-h-[320px] overflow-auto" role="listbox" aria-label="命令列表">
        <div v-if="!filtered.length" class="py-8 text-center text-[13px] text-muted" role="status">无匹配</div>
        <button
          v-for="(cmd, idx) in filtered"
          :key="cmd.key"
          role="option"
          :aria-selected="idx === activeIdx"
          :class="['w-full text-left px-3 py-2.5 rounded-[12px] flex items-center justify-between gap-3 transition-colors', idx === activeIdx ? 'bg-[var(--c-ink)] text-white' : 'hover:bg-[var(--c-surface)] text-ink']"
          @click="run(cmd)"
          @mouseenter="activeIdx = idx"
        >
          <span class="flex items-center gap-2">
            <span class="text-[12px] font-medium tracking-[-0.01em]">{{ cmd.label }}</span>
            <span v-if="cmd.desc" :class="['text-[11px] tracking-wide', idx === activeIdx ? 'text-white/70' : 'text-muted']">{{ cmd.desc }}</span>
          </span>
          <span v-if="cmd.shortcut" :class="['text-[11px] tracking-widest px-1.5 py-0.5 rounded-full', idx === activeIdx ? 'bg-white/20 text-white' : 'bg-[var(--c-surface)] text-muted']">{{ cmd.shortcut }}</span>
        </button>
      </div>
      <div class="text-[11px] tracking-wide text-muted flex items-center gap-3 pt-2 border-t border-[var(--c-hairline)]">
        <span>↵ 执行</span><span>↑↓ 移动</span><span>Esc 关闭</span>
      </div>
    </div>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { NModal, NInput, useMessage } from 'naive-ui'
import { listPendingApprovals } from '@/api/plans'
import { listGoals } from '@/api/goals'
import { listTasks } from '@/api/tasks'
import { searchMemory, type MemoryChunk } from '@/api/memory'
import type { GoalItem, TaskItem } from '@/types'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{ (e: 'update:show', v: boolean): void; (e: 'run', key: string): void }>()
const router = useRouter()
const message = useMessage()
const query = ref('')
const activeIdx = ref(0)
const searching = ref(false)
const searchError = ref('')
const goalHits = ref<GoalItem[]>([])
const taskHits = ref<TaskItem[]>([])
const memHits = ref<MemoryChunk[]>([])
let debounceTimer: ReturnType<typeof setTimeout> | null = null

const hasQuery = computed(() => query.value.trim().length > 0)
const hasData = computed(() => goalHits.value.length + taskHits.value.length + memHits.value.length > 0)

interface Cmd { key: string; label: string; desc?: string; shortcut?: string; action: () => void }

const commands = computed<Cmd[]>(() => [
  { key: 'go-agent', label: '智能体工作台', desc: '/agent', shortcut: 'A', action: () => router.push('/agent') },
  { key: 'go-home', label: '首页', desc: '/', shortcut: 'H', action: () => router.push('/') },
  { key: 'go-goals', label: '目标', desc: '/goals', shortcut: 'G', action: () => router.push('/goals') },
  { key: 'go-calendar', label: '日历', desc: '/calendar', shortcut: 'C', action: () => router.push('/calendar') },
  { key: 'go-week', label: '周视图', desc: '/week', action: () => router.push('/week') },
  { key: 'go-gantt', label: '甘特', desc: '/gantt', action: () => router.push('/gantt') },
  { key: 'go-batch', label: '批量', desc: '/tasks/batch', action: () => router.push('/tasks/batch') },
  { key: 'go-graph', label: '图谱', desc: '/graph', action: () => router.push('/graph') },
  { key: 'go-rag', label: '知识库', desc: '/rag', shortcut: 'R', action: () => router.push('/rag') },
  { key: 'go-reflection', label: '反思', desc: '/reflection', action: () => router.push('/reflection') },
  { key: 'go-dashboard', label: '大屏', desc: '/dashboard', action: () => router.push('/dashboard') },
  { key: 'go-large', label: '驾驶舱', desc: '/large-screen', action: () => router.push('/large-screen') },
  { key: 'go-experiments', label: '实验', desc: '/experiments', action: () => router.push('/experiments') },
  { key: 'go-health', label: '健康', desc: '/health', action: () => router.push('/health') },
  { key: 'go-mcp', label: 'MCP', desc: '/mcp', action: () => router.push('/mcp') },
  { key: 'go-settings', label: '设置', desc: '/settings', action: () => { try { void router.push('/settings') } catch {} } },
  { key: 'go-notifications', label: '通知中心', desc: '/notifications', action: () => { try { void router.push('/notifications') } catch {} } },
  { key: 'action-search-rag', label: '搜索知识库', desc: '聚焦 RAG 检索', action: () => { try { void router.push('/rag') } catch {} } },
  { key: 'action-logout', label: '退出登录', desc: '清除 Token', action: () => { try { localStorage.removeItem('token'); localStorage.removeItem('user_id') } catch {}; try { void router.push('/login') } catch {} } },
  { key: 'new-goal', label: '新建目标', desc: '/goals', action: () => { try { void router.push('/goals') } catch {} } },
  { key: 'new-plan', label: '新建规划', desc: '/agent', action: () => { try { void router.push('/agent') } catch {} } },
  { key: 'report-pomodoro', label: '上报番茄', desc: '/calendar', action: () => { try { void router.push('/calendar') } catch {} } },
  {
    key: 'approval-center', label: '审批中心', desc: '未决审批', action: () => {
      void (async () => {
        try {
          const res = await listPendingApprovals()
          const items = res?.data?.items ?? []
          const first = items[0]
          if (first?.trace_id) {
            try { await router.push('/agent?trace=' + encodeURIComponent(first.trace_id)) } catch {}
          } else {
            try { message.info('暂无待审批') } catch {}
          }
        } catch (e: unknown) {
          try { message.error(e instanceof Error ? e.message : '审批查询失败') } catch {}
        }
      })()
    },
  },
])

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return commands.value.slice(0, 12)
  return commands.value.filter(c => `${c.label} ${c.desc ?? ''} ${c.key}`.toLowerCase().includes(q)).slice(0, 12)
})

watch(() => props.show, v => {
  if (v) {
    query.value = ''
    activeIdx.value = 0
    goalHits.value = []
    taskHits.value = []
    memHits.value = []
    searchError.value = ''
    searching.value = false
  } else if (debounceTimer) {
    clearTimeout(debounceTimer)
    debounceTimer = null
  }
})
watch(filtered, () => { activeIdx.value = 0 })
watch(query, (v) => {
  if (debounceTimer) clearTimeout(debounceTimer)
  const q = v.trim()
  if (!q) {
    searching.value = false
    searchError.value = ''
    goalHits.value = []
    taskHits.value = []
    memHits.value = []
    return
  }
  searching.value = true
  debounceTimer = setTimeout(() => { void runSearch(q) }, 300)
})

async function runSearch(q: string): Promise<void> {
  const keyword = q.trim()
  if (!keyword) return
  searching.value = true
  searchError.value = ''
  try {
    const lower = keyword.toLowerCase()
    const [gRes, tRes, mRes] = await Promise.allSettled([
      listGoals({ page: 1, size: 20 }),
      listTasks({ page: 1, size: 20 }),
      searchMemory({ q: keyword, top_k: 5 }),
    ])
    if (gRes.status === 'fulfilled') {
      const items = gRes.value.data.items ?? []
      goalHits.value = items
        .filter((g) => `${g.title} ${g.description ?? ''}`.toLowerCase().includes(lower))
        .slice(0, 5)
    } else {
      goalHits.value = []
    }
    if (tRes.status === 'fulfilled') {
      const items = tRes.value.data.items ?? []
      taskHits.value = items
        .filter((t) => t.title.toLowerCase().includes(lower))
        .slice(0, 5)
    } else {
      taskHits.value = []
    }
    if (mRes.status === 'fulfilled') {
      memHits.value = (mRes.value.data ?? []).slice(0, 5)
    } else {
      memHits.value = []
    }
  } catch {
    searchError.value = '搜索失败，请重试'
  } finally {
    searching.value = false
  }
}

function close(): void {
  if (debounceTimer) clearTimeout(debounceTimer)
  emit('update:show', false)
}

function goGoal(id: number): void {
  close()
  try { void router.push('/goals') } catch {}
  void id
}

function goTask(): void {
  close()
  try { void router.push('/calendar') } catch {}
}

function goMemory(): void {
  const q = query.value.trim()
  close()
  try {
    if (q) void router.push({ path: '/rag', query: { q } })
    else void router.push('/rag')
  } catch {}
}

function run(cmd: Cmd): void {
  if (debounceTimer) clearTimeout(debounceTimer)
  emit('update:show', false)
  try { cmd.action() } catch {}
  emit('run', cmd.key)
}

function onKey(e: KeyboardEvent): void {
  if (e.key === 'ArrowDown') { e.preventDefault(); activeIdx.value = Math.min(filtered.value.length - 1, activeIdx.value + 1) }
  else if (e.key === 'ArrowUp') { e.preventDefault(); activeIdx.value = Math.max(0, activeIdx.value - 1) }
  else if (e.key === 'Enter') {
    e.preventDefault()
    if (hasQuery.value && hasData.value && !searching.value) {
      if (goalHits.value.length) { goGoal(goalHits.value[0].id); return }
      if (taskHits.value.length) { goTask(); return }
      if (memHits.value.length) { goMemory(); return }
    }
    const c = filtered.value[activeIdx.value]; if (c) run(c)
  }
  else if (e.key === 'Escape') { emit('update:show', false) }
}

onBeforeUnmount(() => {
  if (debounceTimer) clearTimeout(debounceTimer)
})
</script>
