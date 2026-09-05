<template>
  <div class="w-full max-w-[92%] rounded-[12px] bg-[#f5f5f7] border border-hairline p-3">
    <div class="flex items-center justify-between">
      <span class="text-[11px] tracking-widest font-medium text-muted">计划 · {{ tasks.length }} 任务</span>
      <span class="text-[10px] text-muted font-mono">#{{ traceShort }}</span>
    </div>
    <div class="mt-2 space-y-1.5 max-h-[220px] overflow-auto">
      <div v-for="(t, i) in tasks" :key="`${t.title}-${i}`" class="flex items-center justify-between gap-2 bg-white rounded-[8px] px-2.5 py-1.5">
        <span class="flex items-center gap-2 min-w-0">
          <span :class="['text-[9px] px-1.5 py-0.5 rounded-full border shrink-0', priorityClass(t.priority)]">P{{ t.priority ?? 3 }}</span>
          <span class="text-[12px] text-ink truncate">{{ t.title }}</span>
        </span>
        <span class="text-[10px] text-muted shrink-0 font-mono">{{ fmtTime(t.planned_start) }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { TranscriptTask } from '@/stores/workbench'

const props = defineProps<{ tasks: TranscriptTask[]; traceId?: string | null }>()

const traceShort = computed(() => (props.traceId || '').slice(0, 8) || '—')

function priorityClass(p?: number): string {
  if (p === 1) return 'bg-[#fef2f2] text-[#991b1b] border-[#fecaca]'
  if (p === 2) return 'bg-[#fffbeb] text-[#92400e] border-[#fde68a]'
  return 'bg-[#f5f5f7] text-muted border-[#e8e8ed]'
}

function fmtTime(v?: string): string {
  if (!v) return '—'
  try {
    const d = new Date(v)
    if (Number.isNaN(d.getTime())) return v.slice(0, 10)
    return d.toLocaleDateString()
  } catch { return v.slice(0, 10) }
}
</script>
