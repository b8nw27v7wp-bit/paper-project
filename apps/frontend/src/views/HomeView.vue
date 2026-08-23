<template>
  <div class="space-y-10">
    <div class="space-y-3">
      <h1 class="text-[32px] font-semibold tracking-[-0.03em] text-ink leading-none">智能学习规划</h1>
      <p class="text-[14px] leading-6 text-muted max-w-[640px]">Apple 系统字体 · #1d1d1f · 白底无框 · 大留白 · 克制高级。Monorepo 已就绪，前后端与桌面最小闭环已打通。</p>
    </div>

    <div class="grid md:grid-cols-3 gap-6">
      <n-card class="apple-card">
        <div class="text-[11px] tracking-widest text-muted font-medium">FASTAPI</div>
        <div class="mt-2 text-[15px] font-semibold tracking-[-0.02em] text-ink">后端 8000</div>
        <div class="mt-1 text-[13px] leading-5 text-muted">健康检查 · SSE · 多Agent</div>
        <div class="mt-4"><span class="text-[11px] px-2.5 py-1 rounded-full bg-[#f5f5f7] text-muted">:8000</span></div>
      </n-card>
      <n-card class="apple-card">
        <div class="text-[11px] tracking-widest text-muted font-medium">FRONTEND</div>
        <div class="mt-2 text-[15px] font-semibold tracking-[-0.02em] text-ink">前端 5173</div>
        <div class="mt-1 text-[13px] leading-5 text-muted">Vite · Naive UI · 日历</div>
        <div class="mt-4"><span class="text-[11px] px-2.5 py-1 rounded-full bg-[#f5f5f7] text-muted">:5173</span></div>
      </n-card>
      <n-card class="apple-card">
        <div class="text-[11px] tracking-widest text-muted font-medium">DESKTOP</div>
        <div class="mt-2 text-[15px] font-semibold tracking-[-0.02em] text-ink">桌面 Electron</div>
        <div class="mt-1 text-[13px] leading-5 text-muted">Main · Preload · IPC</div>
        <div class="mt-4"><span class="text-[11px] px-2.5 py-1 rounded-full bg-[#f5f5f7] text-muted">electron</span></div>
      </n-card>
    </div>

    <div class="flex gap-3">
      <n-button type="primary" @click="$router.push('/health')">查看健康检查</n-button>
      <n-button strong secondary @click="checkHealth">快速探测</n-button>
      <span v-if="quick" class="text-[13px] self-center" :class="quick.ok ? 'text-ink' : 'text-red-500'">{{ quick.msg }}</span>
    </div>

    <n-card class="apple-card">
      <div class="text-[13px] font-semibold tracking-[-0.01em] text-ink">阶段</div>
      <n-steps :current="3" size="small" class="mt-6">
        <n-step title="P0 地基" description="W1-8" />
        <n-step title="P1 核心" description="W9-16" />
        <n-step title="P2 三端" description="W17-22" />
        <n-step title="P3 评估" description="W23-26" />
      </n-steps>
    </n-card>

    <n-card class="apple-card">
      <div class="text-[13px] font-semibold text-ink">技术栈</div>
      <div class="mt-4 grid grid-cols-2 gap-6 text-[13px] leading-5">
        <div><span class="text-muted">前端</span><span class="ml-2 text-ink">Vue3 · Vite · Tailwind · FullCalendar · ECharts</span></div>
        <div><span class="text-muted">桌面</span><span class="ml-2 text-ink">Electron 40 · better-sqlite3</span></div>
        <div><span class="text-muted">后端</span><span class="ml-2 text-ink">FastAPI · LangGraph · MCP · SQLModel</span></div>
        <div><span class="text-muted">存储</span><span class="ml-2 text-ink">PG · pgvector · Neo4j · Redis · MinIO</span></div>
      </div>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { NCard, NButton, NSteps, NStep } from 'naive-ui'
import { fetchHealth } from '@/api/health'

const quick = ref<{ ok: boolean; msg: string } | null>(null)
async function checkHealth() {
  try {
    const data = await fetchHealth()
    quick.value = { ok: true, msg: `后端正常 v${data.data?.version ?? 'unknown'}` }
  } catch (e: any) {
    quick.value = { ok: false, msg: e?.message ?? '后端未启动' }
  }
}
</script>
