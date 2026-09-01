<template>
  <n-card class="apple-card" size="small" content-style="padding: 16px;">
    <div class="flex items-center justify-between">
      <span class="text-[11px] tracking-widest font-medium text-muted">{{ data.type || 'memory' }}</span>
      <span class="text-[11px] tracking-wide text-muted">{{ data.created_at ? new Date(String(data.created_at)).toLocaleDateString() : '' }}</span>
    </div>
    <div class="mt-2 text-[13px] leading-6 tracking-[-0.01em] text-ink line-clamp-3">{{ data.content }}</div>
    <div v-if="data.score !== undefined" class="mt-2 text-[11px] tracking-wide text-muted">score {{ (data.score as number).toFixed(3) }}</div>
  </n-card>
</template>
<script setup lang="ts">
import { NCard } from 'naive-ui'
import type { MemoryChunk } from '@/api/memory'

defineProps<{ data: MemoryChunk }>()
</script>
