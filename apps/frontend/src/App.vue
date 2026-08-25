<template>
  <n-config-provider :theme-overrides="theme">
    <n-message-provider>
      <n-notification-provider>
        <div class="min-h-screen bg-white font-apple text-ink selection:bg-[#f5f5f7]">
          <header class="sticky top-0 z-10 bg-white/80 backdrop-blur-xl">
            <div class="max-w-[1280px] mx-auto px-10 py-6 flex items-center justify-between">
              <div class="flex items-center gap-4">
                <div class="w-7 h-7 rounded-lg bg-[#1d1d1f] flex items-center justify-center text-white text-[11px] font-semibold tracking-widest">L</div>
                <span class="text-[15px] font-semibold tracking-[-0.02em] text-ink">学习规划</span>
                <span class="hidden sm:inline text-[11px] tracking-wide text-muted font-medium">LearningPlanner</span>
              </div>
              <nav class="flex items-center gap-1">
                <router-link v-for="item in nav" :key="item.to" :to="item.to" custom v-slot="{ navigate, isActive }">
                  <button
                    @click="navigate"
                    :class="[
                      'px-3.5 py-1.5 text-[13px] font-medium rounded-full transition-colors',
                      isActive ? 'bg-[#1d1d1f] text-white' : 'text-muted hover:text-ink hover:bg-[#f5f5f7]'
                    ]"
                  >
                    {{ item.label }}
                  </button>
                </router-link>
              </nav>
            </div>
            <div class="h-px bg-[#f5f5f7] mx-10" />
          </header>
          <main class="max-w-[1280px] mx-auto px-10 py-12">
            <router-view />
          </main>
          <footer class="max-w-[1280px] mx-auto px-10 py-10 text-center">
            <div class="h-px bg-[#f5f5f7] mb-6" />
            <p class="text-[11px] tracking-wide text-muted">© 2026 LearningPlanner · Apple 字体 · 浅色极简 · 克制</p>
          </footer>
        </div>
      </n-notification-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { NConfigProvider, NMessageProvider, NNotificationProvider } from 'naive-ui'

const nav = [
  { to: '/', label: '首页' },
  { to: '/goals', label: '目标' },
  { to: '/calendar', label: '日历' },
  { to: '/dashboard', label: '大屏' },
  { to: '/health', label: '健康' },
  { to: '/mcp', label: 'MCP' },
]

const theme = {
  common: {
    primaryColor: '#1d1d1f',
    primaryColorHover: '#2c2c2e',
    borderRadius: '12px',
    fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Helvetica Neue", Helvetica, Arial, sans-serif',
    textColorBase: '#1d1d1f',
  },
  Card: {
    borderRadius: '16px',
    color: '#ffffff',
    borderColor: 'transparent',
  },
  Button: {
    borderRadiusMedium: '20px',
  },
}
</script>
