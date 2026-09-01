<template>
  <div class="py-20 text-center space-y-4" role="main" aria-label="404 未找到">
    <div class="text-[48px] font-semibold tracking-[-0.03em] text-ink">404</div>
    <p class="text-[14px] tracking-[-0.01em] text-muted" aria-live="polite">页面不存在或已迁移 — {{ route.fullPath }}</p>
    <div class="flex justify-center gap-3 pt-4">
      <n-button type="primary" style="border-radius: 20px" @click="router.push('/')">返回首页</n-button>
      <n-button style="border-radius: 20px" @click="router.back()">返回上页</n-button>
      <n-button strong secondary style="border-radius: 20px" @click="showCommand = true">⌘K 搜索</n-button>
    </div>
    <n-card class="apple-card mt-8 text-left max-w-[560px] mx-auto" content-style="padding: 24px;">
      <div class="text-[11px] tracking-widest font-medium text-muted">快捷</div>
      <div class="mt-2 text-[13px] leading-6 text-muted">G 目标 · C 日历 · R 知识库 · H 首页 · ? 快捷表</div>
    </n-card>
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'NotFoundView' })
import { useRoute, useRouter } from 'vue-router'
import { ref } from 'vue'
import { NCard, NButton } from 'naive-ui'
const route = useRoute()
const router = useRouter()
const showCommand = ref(false)
</script>
