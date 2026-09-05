<template>
  <div class="w-full max-w-[92%]">
    <div :class="['rounded-[12px] border bg-white overflow-hidden', running ? 'border-[#e8e8ed]' : error ? 'border-[#fecaca]' : 'border-hairline']">
      <button class="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-[#fafafa] transition-colors" :aria-expanded="open" @click="open = !open">
        <span class="w-5 h-5 shrink-0 rounded-[6px] bg-[#f5f5f7] flex items-center justify-center text-[11px] text-ink" aria-hidden="true">{{ glyph }}</span>
        <span class="text-[12px] font-medium text-ink truncate">{{ entry.tool }}</span>
        <span v-if="entry.agent" class="text-[10px] px-1.5 py-0.5 rounded-full bg-[#f5f5f7] text-muted border border-hairline shrink-0">{{ entry.agent }}</span>
        <span class="flex-1 min-w-0 text-[11px] text-muted truncate text-left">{{ argsSummary }}</span>
        <span v-if="running" class="shrink-0 w-3 h-3 rounded-full border-2 border-[#d4d4d8] border-t-[#86868b] animate-spin" aria-label="运行中" />
        <span v-else-if="error" class="shrink-0 text-[12px] text-[#ef4444]" aria-label="失败">✗</span>
        <span v-else class="shrink-0 text-[12px] text-[#10b981]" aria-label="完成">✓</span>
        <span v-if="duration" class="shrink-0 text-[10px] text-muted font-mono">{{ duration }}</span>
        <span class="shrink-0 text-[10px] text-muted" aria-hidden="true">{{ open ? '▾' : '▸' }}</span>
      </button>
      <div v-if="open" class="border-t border-hairline px-3 py-2 space-y-2 bg-[#fafafa]">
        <div v-if="entry.args && Object.keys(entry.args).length">
          <div class="text-[10px] tracking-widest text-muted mb-1">入参</div>
          <Markdown :source="codeBlock(entry.args)" />
        </div>
        <div v-if="entry.result !== undefined || entry.error">
          <div class="text-[10px] tracking-widest text-muted mb-1">{{ entry.error ? '错误' : '结果' }}</div>
          <Markdown :source="entry.error ? codeBlockText(entry.error) : codeBlock(entry.result)" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import Markdown from '@/components/Markdown.vue'
import type { TranscriptTool } from '@/stores/workbench'

const props = defineProps<{ entry: TranscriptTool }>()

const open = ref(false)

const running = computed(() => props.entry.status === 'running')
const error = computed(() => props.entry.status === 'error')

const glyph = computed(() => {
  const t = props.entry.tool.toLowerCase()
  if (t.includes('memory')) return '◈'
  if (t.includes('rag') || t.includes('search') || t.includes('vec')) return '▤'
  if (t.includes('graph')) return '⬡'
  if (t.includes('write') || t.includes('task')) return '✎'
  if (t.includes('mcp')) return '⛒'
  return '◆'
})

const argsSummary = computed(() => {
  try {
    const s = JSON.stringify(props.entry.args ?? {})
    return s === '{}' ? '' : s.slice(0, 120)
  } catch { return '' }
})

const duration = computed(() => {
  if (!props.entry.startAt || !props.entry.endAt) return ''
  const ms = new Date(props.entry.endAt).getTime() - new Date(props.entry.startAt).getTime()
  if (Number.isNaN(ms) || ms < 0) return ''
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`
})

function codeBlock(v: unknown): string {
  try { return '```json\n' + JSON.stringify(v, null, 2) + '\n```' } catch { return '```\n' + String(v) + '\n```' }
}
function codeBlockText(v: string): string {
  return '```\n' + v + '\n```'
}
</script>
