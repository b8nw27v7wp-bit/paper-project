<template>
  <div :class="['w-full max-w-[92%] rounded-[12px] border p-3', shellClass]">
    <div class="flex items-center gap-2">
      <span :class="['text-[10px] tracking-widest px-1.5 py-0.5 rounded-full font-medium', badgeClass]">{{ label }}</span>
      <span v-if="rewrites" class="text-[10px] text-muted">rewrites ×{{ rewrites }}</span>
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
    <div v-else class="mt-1.5 text-[12px] leading-5 text-ink whitespace-pre-wrap break-words">{{ text || '校验通过' }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import Markdown from '@/components/Markdown.vue'

const props = defineProps<{ kind: 'critic' | 'mentor' | 'reflector'; text?: string; patch?: Record<string, unknown>; rewrites?: number }>()

const label = computed(() => (props.kind === 'critic' ? 'Critic' : props.kind === 'mentor' ? 'Mentor' : 'Reflector'))
const shellClass = computed(() => {
  if (props.kind === 'critic') return props.text ? 'bg-[#fffbeb] border-[#fde68a]' : 'bg-[#f5f5f7] border-hairline'
  if (props.kind === 'mentor') return 'bg-[#eff6ff] border-[#bfdbfe]'
  return 'bg-[#faf5ff] border-[#e9d5ff]'
})
const badgeClass = computed(() => {
  if (props.kind === 'critic') return props.text ? 'bg-[#fef3c7] text-[#92400e]' : 'bg-white text-muted border border-hairline'
  if (props.kind === 'mentor') return 'bg-[#dbeafe] text-[#1e40af]'
  return 'bg-[#f3e8ff] text-[#6b21a8]'
})

function codeBlock(v: Record<string, unknown>): string {
  try { return '```json\n' + JSON.stringify(v, null, 2) + '\n```' } catch { return '```\n' + String(v) + '\n```' }
}
</script>
