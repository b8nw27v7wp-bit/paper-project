<template>
  <header role="banner" aria-label="顶部导航" class="sticky top-0 z-20 bg-[var(--c-bg)] backdrop-blur-xl border-b border-hairline">
    <!-- 展开态：Logo + 分组导航 + 状态区 -->
    <div v-if="!collapsed" class="px-4 h-12 flex items-center gap-3">
      <div class="electron-drag flex items-center gap-2 shrink-0" aria-hidden="false">
        <button
          class="w-7 h-7 rounded-[8px] bg-ink flex items-center justify-center text-white text-[12px] font-semibold shrink-0"
          aria-label="智能体工作台"
          @click="go('/agent')"
        >L</button>
      </div>
      <nav aria-label="主导航" class="flex-1 min-w-0 flex items-center gap-4 overflow-x-auto scrollbar-none">
        <div v-for="section in sections" :key="section.key" class="flex items-center gap-1 shrink-0">
          <button
            v-for="item in section.items"
            :key="item.to"
            :aria-label="item.label"
            :aria-current="isActive(item.to) ? 'page' : undefined"
            :class="[
              'px-2.5 py-1 text-[12px] rounded-full transition-colors whitespace-nowrap',
              isActive(item.to) ? 'bg-ink text-white font-medium' : 'text-muted hover:text-ink hover:bg-surface',
            ]"
            @click="go(item.to)"
          >{{ item.label }}</button>
        </div>
      </nav>
      <div class="flex items-center gap-1.5 shrink-0">
        <slot name="status" />
        <button
          class="px-2.5 h-7 rounded-full hidden sm:flex items-center justify-center text-[11px] font-medium text-muted hover:text-ink hover:bg-surface transition-colors"
          aria-label="打开命令面板"
          @click="emit('open-command')"
        >命令</button>
        <button
          class="px-2.5 h-7 rounded-full flex items-center justify-center text-[11px] text-muted hover:text-ink hover:bg-surface transition-colors"
          aria-label="收起顶栏"
          @click="setCollapsed(true)"
        >收起</button>
      </div>
    </div>
    <!-- 收起态：细条（Logo + 汉堡 + 当前标题 + 状态点） -->
    <div v-else class="px-4 h-9 flex items-center gap-2">
      <div class="electron-drag flex items-center gap-2">
        <button
          class="w-6 h-6 rounded-[7px] bg-ink flex items-center justify-center text-white text-[11px] font-semibold shrink-0"
          aria-label="智能体工作台"
          @click="go('/agent')"
        >L</button>
      </div>
      <button
          class="px-2.5 h-7 rounded-full flex items-center justify-center text-[11px] text-muted hover:text-ink hover:bg-surface transition-colors"
          aria-label="展开顶栏"
          @click="setCollapsed(false)"
      >菜单</button>
      <span class="text-[12px] text-ink font-medium truncate" aria-current="page">{{ currentTitle }}</span>
      <span class="flex-1" />
      <slot name="status" />
      <button
        class="px-2.5 h-7 rounded-full hidden sm:flex items-center justify-center text-[11px] font-medium text-muted hover:text-ink hover:bg-surface transition-colors"
        aria-label="打开命令面板"
        @click="emit('open-command')"
      >命令</button>
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { TOPNAV_SECTIONS } from './nav'
import { useTopNav } from './index'

const props = withDefaults(defineProps<{ currentTitle?: string }>(), { currentTitle: '' })
const emit = defineEmits<{ (e: 'open-command'): void }>()

const route = useRoute()
const router = useRouter()
const { collapsed, setCollapsed } = useTopNav()

const sections = TOPNAV_SECTIONS

function isActive(to: string): boolean {
  return route.path === to
}

function go(to: string): void {
  if (route.path !== to) void router.push(to)
}

const currentTitle = computed(() => {
  if (props.currentTitle) return props.currentTitle
  const matched = route.matched.filter((r) => r.meta && (r.meta as Record<string, unknown>).title)
  const last = matched[matched.length - 1]
  return String((last?.meta as Record<string, unknown> | undefined)?.title ?? '智能体工作台')
})
</script>
