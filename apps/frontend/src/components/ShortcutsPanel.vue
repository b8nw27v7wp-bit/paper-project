<template>
  <n-modal :show="show" preset="card" title="快捷键" style="width: 520px; border-radius: 16px" @update:show="v => emit('update:show', v)">
    <div class="space-y-4" role="dialog" aria-label="快捷键表">
      <div class="grid grid-cols-2 gap-3 text-[13px]">
        <div class="rounded-[12px] bg-[var(--c-surface)] p-3"><div class="text-[11px] tracking-widest text-muted">全局</div><div class="mt-1 leading-6 text-ink">Ctrl+K 打开命令面板<br/>? 打开本表<br/>Esc 关闭弹窗</div></div>
        <div class="rounded-[12px] bg-[var(--c-surface)] p-3"><div class="text-[11px] tracking-widest text-muted">导航</div><div class="mt-1 leading-6 text-ink">G 目标 · C 日历 · R 知识库<br/>H 首页 · / 搜索</div></div>
        <div class="rounded-[12px] bg-[var(--c-bg)] border border-[var(--c-hairline)] p-3"><div class="text-[11px] tracking-widest text-muted">PlanStream</div><div class="mt-1 leading-6 text-ink">Apply 行内应用<br/>Artifacts 预览引用</div></div>
        <div class="rounded-[12px] bg-[var(--c-bg)] border border-[var(--c-hairline)] p-3"><div class="text-[11px] tracking-widest text-muted">辅助</div><div class="mt-1 leading-6 text-ink">Tab 跳链 · 屏幕朗读 aria-live</div></div>
      </div>
      <div class="text-[11px] tracking-wide text-muted">提示：vibrancy 已开启（mac sidebar），桌面端右键可唤起上下文菜单</div>
    </div>
  </n-modal>
</template>

<script setup lang="ts">
import { NModal } from 'naive-ui'
defineProps<{ show: boolean }>()
const emit = defineEmits<{ (e: 'update:show', v: boolean): void }>()
</script>
