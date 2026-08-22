<template>
  <n-config-provider>
    <n-message-provider>
      <n-notification-provider>
        <div class="min-h-screen bg-gray-50">
          <header class="bg-white border-b sticky top-0 z-10">
            <div class="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
              <div class="flex items-center gap-3">
                <div class="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center text-white font-bold">L</div>
                <span class="font-semibold text-gray-900">智能学习规划系统</span>
                <span class="text-xs px-2 py-0.5 bg-blue-100 text-blue-700 rounded-full">P0 地基版</span>
              </div>
              <nav class="flex gap-2">
                <router-link to="/" custom v-slot="{ navigate, isActive }">
                  <n-button :type="isActive ? 'primary' : 'default'" size="small" @click="navigate">首页</n-button>
                </router-link>
                <router-link to="/goals" custom v-slot="{ navigate, isActive }">
                  <n-button :type="isActive ? 'primary' : 'default'" size="small" @click="navigate">目标</n-button>
                </router-link>
                <router-link to="/calendar" custom v-slot="{ navigate, isActive }">
                  <n-button :type="isActive ? 'primary' : 'default'" size="small" @click="navigate">日历</n-button>
                </router-link>
                <router-link to="/health" custom v-slot="{ navigate, isActive }">
                  <n-button :type="isActive ? 'primary' : 'default'" size="small" @click="navigate">健康检查</n-button>
                </router-link>
              </nav>
            </div>
          </header>
          <main class="max-w-7xl mx-auto px-6 py-8">
            <router-view />
          </main>
          <footer class="text-center text-sm text-gray-400 py-8">
            Electron 40 + Vue3 + FastAPI | Monorepo P0 地基验证
          </footer>
        </div>
      </n-notification-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { NConfigProvider, NMessageProvider, NNotificationProvider, NButton } from 'naive-ui'
</script>
