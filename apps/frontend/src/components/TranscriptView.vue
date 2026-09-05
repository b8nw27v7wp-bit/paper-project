<template>
  <div ref="scrollRef" class="flex-1 min-h-0 overflow-auto p-6 space-y-3" role="log" aria-live="polite" aria-label="转录流">
    <div v-if="compactNote > 0" class="text-center text-[11px] tracking-wide text-muted py-1" aria-label="已压缩条数">
      已压缩 {{ compactNote }} 条（窗口 20 / 上限 200）
    </div>
    <template v-for="item in visible" :key="item.id">
      <div
        :data-nodeid="item.agent || ''"
        :class="['rounded-[14px] transition-shadow', item.agent === selectedNodeId && item.kind !== 'user' ? 'ring-2 ring-[#0071e3]/50' : '']"
      >
        <div v-if="item.kind === 'user'" class="flex justify-end">
          <div class="max-w-[78%] rounded-[16px] bg-[#f5f5f7] text-ink px-4 py-2.5">
            <div class="text-[13px] leading-5 whitespace-pre-wrap break-words">{{ item.text }}</div>
            <div class="mt-1 text-[10px] text-muted text-right">{{ item.time }}</div>
          </div>
        </div>

        <div v-else-if="item.kind === 'thought'" class="max-w-[92%]">
          <div class="flex items-center gap-2 mb-1">
            <span class="text-[10px] tracking-widest px-1.5 py-0.5 rounded-full bg-white border border-hairline text-muted">{{ item.agent }}</span>
            <span class="text-[10px] text-muted">{{ item.time }}</span>
          </div>
          <div class="text-[13px] leading-5 text-ink"><Markdown :source="item.text || ''" /></div>
        </div>

        <TranscriptToolBlock v-else-if="item.kind === 'tool' && item.tools?.length" :entry="item.tools[0]" />

        <TranscriptPlanCard v-else-if="item.kind === 'plan' && item.tasks?.length" :tasks="item.tasks" :trace-id="traceId" />

        <TranscriptNotice
          v-else-if="item.kind === 'critic' || item.kind === 'mentor' || item.kind === 'reflector'"
          :kind="item.kind"
          :text="item.feedback || item.text"
          :patch="item.patch"
          :rewrites="item.rewrites"
        />

        <div v-else-if="item.kind === 'compact'" class="text-center text-[11px] tracking-wide text-muted py-1">
          已压缩 {{ item.count ?? 0 }} 条
        </div>

        <div v-else-if="item.kind === 'done'" class="flex items-center gap-3 py-2" role="status">
          <div class="flex-1 border-t border-hairline" />
          <span class="text-[11px] tracking-wide text-muted">
            完成 · {{ item.count ?? 0 }} 任务 · rewrites={{ item.rewrites ?? 0 }} · 总耗时 {{ fmtElapsed(item.elapsedMs) }}
          </span>
          <div class="flex-1 border-t border-hairline" />
        </div>
      </div>
    </template>

    <div v-if="reconnecting" class="text-center text-[11px] text-muted py-1" role="status">
      连接中断，重连中… last_event_id={{ lastEventId || '0' }}
    </div>
    <div v-if="status === 'running' && !reconnecting" class="flex justify-start">
      <div class="bg-[#f5f5f7] rounded-[16px] px-4 py-2.5 text-[12px] text-muted flex items-center gap-2">
        <span class="w-3 h-3 rounded-full border-2 border-[#d4d4d8] border-t-[#86868b] animate-spin" aria-hidden="true" /> 6节点协作中…
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import Markdown from '@/components/Markdown.vue'
import TranscriptToolBlock from '@/components/TranscriptToolBlock.vue'
import TranscriptPlanCard from '@/components/TranscriptPlanCard.vue'
import TranscriptNotice from '@/components/TranscriptNotice.vue'
import type { TranscriptItem } from '@/stores/workbench'

const props = defineProps<{
  items: TranscriptItem[]
  reconnecting: boolean
  selectedNodeId: string
  lastEventId: string
  status: string
  traceId: string | null
}>()

const scrollRef = ref<HTMLDivElement | null>(null)

const visible = computed(() => props.items.slice(-20))
const compactNote = computed(() => Math.max(0, props.items.length - visible.value.length))

function fmtElapsed(ms?: number): string {
  if (!ms || ms < 0) return '—'
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`
}

function scrollToBottom() {
  void nextTick(() => {
    const el = scrollRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

watch(() => props.items.length, scrollToBottom)
watch(() => props.status, scrollToBottom)

watch(() => props.selectedNodeId, (id) => {
  if (!id) return
  void nextTick(() => {
    const el = scrollRef.value?.querySelector(`[data-nodeid="${id}"]`)
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  })
})
</script>
