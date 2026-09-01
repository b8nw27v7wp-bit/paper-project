<template>
  <n-card class="apple-card" content-style="padding: 32px;">
    <div class="flex items-center justify-between">
      <span class="text-[13px] font-semibold tracking-[-0.01em] text-ink">{{ data.week }}</span>
      <span class="text-[11px] tracking-wide text-muted">{{ data.created_at ? new Date(String(data.created_at)).toLocaleString() : '' }}</span>
    </div>
    <div class="mt-3 grid grid-cols-3 gap-3">
      <div class="rounded-[16px] bg-[#f5f5f7] p-3 text-center"><div class="text-[11px] tracking-wide text-muted">完成率</div><div class="text-[14px] font-semibold tracking-[-0.02em] text-ink">{{ (data.completion_rate * 100).toFixed(1) }}%</div></div>
      <div class="rounded-[16px] bg-[#f5f5f7] p-3 text-center"><div class="text-[11px] tracking-wide text-muted">拖延率</div><div class="text-[14px] font-semibold tracking-[-0.02em] text-ink">{{ (data.delay_rate * 100).toFixed(1) }}%</div></div>
      <div class="rounded-[16px] bg-[#f5f5f7] p-3 text-center"><div class="text-[11px] tracking-wide text-muted">负荷</div><div class="text-[14px] font-semibold tracking-[-0.02em] text-ink">{{ data.avg_load.toFixed(1) }}h</div></div>
    </div>
    <div class="mt-4 rounded-[16px] bg-[#f5f5f7] p-4">
      <div class="text-[11px] tracking-widest font-medium text-muted">ANALYSIS</div>
      <div class="mt-2 text-[13px] leading-6 tracking-[-0.01em] text-ink whitespace-pre-wrap">{{ data.analysis }}</div>
    </div>
    <n-code :code="JSON.stringify(data.next_plan_patch ?? {}, null, 2)" language="json" class="mt-3" />
  </n-card>
</template>
<script setup lang="ts">
import { NCard, NCode } from 'naive-ui'
import type { ReflectionReport } from '@/api/reflection'

defineProps<{ data: ReflectionReport }>()
</script>
