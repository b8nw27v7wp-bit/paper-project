<template>
  <n-card size="small" :title="title">
    <n-code :code="JSON.stringify(data, null, 2)" language="json" />
  </n-card>
</template>
<script setup lang="ts">
import { NCard, NCode } from 'naive-ui'
defineProps<{ title: string; data: any }>()
</script>
