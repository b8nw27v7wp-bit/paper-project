<template>
  <n-card size="small" :title="title" style="border-radius: 16px; border: none; box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 8px 24px rgba(0,0,0,0.02)">
    <n-code :code="formatted" language="json" />
  </n-card>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { NCard, NCode } from 'naive-ui'
import type { HealthStatus } from '@/types'

const props = defineProps<{ title: string; data: HealthStatus | Record<string, unknown> | null }>()

const formatted = computed<string>(() => {
  try {
    return JSON.stringify(props.data, null, 2)
  } catch {
    return String(props.data)
  }
})
</script>
