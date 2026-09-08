<template>
  <div class="py-20 text-center space-y-4" role="main" aria-label="404 未找到">
    <div class="text-[48px] font-semibold tracking-[-0.03em] text-ink">404</div>
    <p class="text-[14px] tracking-[-0.01em] text-muted" aria-live="polite">页面不存在或已迁移 — {{ route.fullPath }}</p>
    <div class="flex justify-center gap-3 pt-4">
      <n-button type="primary" style="border-radius: 20px" @click="router.push('/agent')">回到智能体工作台</n-button>
      <n-button strong secondary style="border-radius: 20px" @click="router.push('/')">返回首页</n-button>
      <n-button style="border-radius: 20px" @click="router.back()">返回上页</n-button>
      <n-button strong secondary style="border-radius: 20px" @click="showCommand = true">命令搜索</n-button>
    </div>
    <n-card class="apple-card mt-8 text-left max-w-[560px] mx-auto" :bordered="false" content-style="padding: 24px;">
      <div class="text-[11px] tracking-widest font-medium text-muted">快捷</div>
      <div class="mt-3 space-y-1">
        <button class="w-full text-left px-3 py-2.5 rounded-[12px] flex items-center justify-between gap-3 transition-colors hover:bg-[var(--c-surface)] text-ink" @click="router.push('/goals')">
          <span class="flex items-center gap-2"><span class="text-[12px] font-medium tracking-[-0.01em]">目标</span><span class="text-[11px] tracking-wide text-muted">/goals · 新建与规划</span></span>
          <span class="text-[11px] tracking-widest px-1.5 py-0.5 rounded-full bg-[var(--c-surface)] text-muted">G</span>
        </button>
        <button class="w-full text-left px-3 py-2.5 rounded-[12px] flex items-center justify-between gap-3 transition-colors hover:bg-[var(--c-surface)] text-ink" @click="router.push('/calendar')">
          <span class="flex items-center gap-2"><span class="text-[12px] font-medium tracking-[-0.01em]">日历</span><span class="text-[11px] tracking-wide text-muted">/calendar · 番茄上报</span></span>
          <span class="text-[11px] tracking-widest px-1.5 py-0.5 rounded-full bg-[var(--c-surface)] text-muted">C</span>
        </button>
        <button class="w-full text-left px-3 py-2.5 rounded-[12px] flex items-center justify-between gap-3 transition-colors hover:bg-[var(--c-surface)] text-ink" @click="router.push('/rag')">
          <span class="flex items-center gap-2"><span class="text-[12px] font-medium tracking-[-0.01em]">知识库</span><span class="text-[11px] tracking-wide text-muted">/rag · 检索入库</span></span>
          <span class="text-[11px] tracking-widest px-1.5 py-0.5 rounded-full bg-[var(--c-surface)] text-muted">R</span>
        </button>
        <button class="w-full text-left px-3 py-2.5 rounded-[12px] flex items-center justify-between gap-3 transition-colors hover:bg-[var(--c-surface)] text-ink" @click="router.push('/agent')">
          <span class="flex items-center gap-2"><span class="text-[12px] font-medium tracking-[-0.01em]">智能体工作台</span><span class="text-[11px] tracking-wide text-muted">/agent · 规划回放</span></span>
          <span class="text-[11px] tracking-widest px-1.5 py-0.5 rounded-full bg-[var(--c-surface)] text-muted">A</span>
        </button>
      </div>
      <div class="mt-3 text-[11px] tracking-wide text-muted">H 首页 · ? 快捷表 · Ctrl+K 搜索</div>
    </n-card>
    <CommandPalette v-model:show="showCommand" />
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'NotFoundView' })
import { useRoute, useRouter } from 'vue-router'
import { ref } from 'vue'
import { NCard, NButton } from 'naive-ui'
import CommandPalette from '@/components/CommandPalette.vue'
const route = useRoute()
const router = useRouter()
const showCommand = ref(false)
</script>
