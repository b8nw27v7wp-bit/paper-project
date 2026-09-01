<template>
  <n-modal :show="show" preset="card" title="⌘K 命令" style="width: 560px; border-radius: 16px" :closable="true" @update:show="v => emit('update:show', v)">
    <div role="dialog" aria-modal="true" aria-label="命令面板" class="space-y-3">
      <div class="flex items-center gap-2">
        <n-input v-model:value="query" placeholder="输入命令或搜索…（↑↓ 选择，回车执行，Esc 关闭）" clearable autofocus aria-label="命令搜索输入" @keydown="onKey" />
        <span class="text-[11px] tracking-wide text-muted hidden sm:inline">⌘K</span>
      </div>
      <div class="max-h-[320px] overflow-auto" role="listbox" aria-label="命令列表">
        <div v-if="!filtered.length" class="py-8 text-center text-[13px] text-muted" role="status">无匹配</div>
        <button
          v-for="(cmd, idx) in filtered"
          :key="cmd.key"
          role="option"
          :aria-selected="idx === activeIdx"
          :class="['w-full text-left px-3 py-2.5 rounded-[12px] flex items-center justify-between gap-3 transition-colors', idx === activeIdx ? 'bg-[#1d1d1f] text-white' : 'hover:bg-[#f5f5f7] text-ink']"
          @click="run(cmd)"
          @mouseenter="activeIdx = idx"
        >
          <span class="flex items-center gap-2">
            <span class="text-[12px] font-medium tracking-[-0.01em]">{{ cmd.label }}</span>
            <span v-if="cmd.desc" :class="['text-[11px] tracking-wide', idx === activeIdx ? 'text-white/70' : 'text-muted']">{{ cmd.desc }}</span>
          </span>
          <span v-if="cmd.shortcut" :class="['text-[10px] tracking-widest px-1.5 py-0.5 rounded-full', idx === activeIdx ? 'bg-white/20 text-white' : 'bg-[#f5f5f7] text-muted']">{{ cmd.shortcut }}</span>
        </button>
      </div>
      <div class="text-[11px] tracking-wide text-muted flex items-center gap-3 pt-2 border-t border-[#f5f5f7]">
        <span>↵ 执行</span><span>↑↓ 移动</span><span>Esc 关闭</span>
      </div>
    </div>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { NModal, NInput } from 'naive-ui'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{ (e: 'update:show', v: boolean): void; (e: 'run', key: string): void }>()
const router = useRouter()
const query = ref('')
const activeIdx = ref(0)

interface Cmd { key: string; label: string; desc?: string; shortcut?: string; action: () => void }

const commands = computed<Cmd[]>(() => [
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
  { key: 'action-search-rag', label: '搜索知识库', desc: '聚焦 RAG 检索', action: () => router.push('/rag') },
  { key: 'action-logout', label: '退出登录', desc: '清除 Token', action: () => { try { localStorage.removeItem('token'); localStorage.removeItem('user_id') } catch {}; void router.push('/login') } },
])

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return commands.value.slice(0, 12)
  return commands.value.filter(c => `${c.label} ${c.desc ?? ''} ${c.key}`.toLowerCase().includes(q)).slice(0, 12)
})

watch(() => props.show, v => { if (v) { query.value = ''; activeIdx.value = 0 } })
watch(filtered, () => { activeIdx.value = 0 })

function run(cmd: Cmd): void {
  emit('update:show', false)
  try { cmd.action() } catch {}
  emit('run', cmd.key)
}

function onKey(e: KeyboardEvent): void {
  if (e.key === 'ArrowDown') { e.preventDefault(); activeIdx.value = Math.min(filtered.value.length - 1, activeIdx.value + 1) }
  else if (e.key === 'ArrowUp') { e.preventDefault(); activeIdx.value = Math.max(0, activeIdx.value - 1) }
  else if (e.key === 'Enter') { e.preventDefault(); const c = filtered.value[activeIdx.value]; if (c) run(c) }
  else if (e.key === 'Escape') { emit('update:show', false) }
}
</script>
