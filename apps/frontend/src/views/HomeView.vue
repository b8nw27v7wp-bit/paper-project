<template>
  <div class="space-y-6">
    <n-card title="P0 地基验证" class="shadow-sm">
      <n-alert type="success" title="Monorepo 已就绪" class="mb-4">
        前端 (Vue3 + Naive UI + Tailwind) + 后端 (FastAPI) + 桌面 (Electron 40) 最小闭环已打通。
      </n-alert>
      <div class="grid md:grid-cols-3 gap-4">
        <n-card size="small" class="bg-blue-50 border-blue-200">
          <template #header>FastAPI</template>
          <div class="text-sm text-gray-600">健康检查 + SSE 预留</div>
          <div class="mt-2"><n-tag type="info">:8000</n-tag></div>
        </n-card>
        <n-card size="small" class="bg-green-50 border-green-200">
          <template #header>Vue 前端</template>
          <div class="text-sm text-gray-600">Vite 5173 + Naive UI</div>
          <div class="mt-2"><n-tag type="success">:5173</n-tag></div>
        </n-card>
        <n-card size="small" class="bg-purple-50 border-purple-200">
          <template #header>Electron</template>
          <div class="text-sm text-gray-600">Main + Preload + IPC</div>
          <div class="mt-2"><n-tag type="warning">:electron</n-tag></div>
        </n-card>
      </div>
      <div class="mt-6 flex gap-3">
        <n-button type="primary" @click="$router.push('/health')">查看健康检查</n-button>
        <n-button @click="checkHealth">快速探测后端</n-button>
        <span v-if="quick" class="text-sm self-center" :class="quick.ok ? 'text-green-600' : 'text-red-600'">{{ quick.msg }}</span>
      </div>
    </n-card>

    <n-card title="后续阶段预告" size="small">
      <n-steps :current="1" size="small" class="mt-2">
        <n-step title="P0 地基" description="W1-8 CRUD+单Agent" />
        <n-step title="P1 核心" description="W9-16 多Agent+记忆+图谱" />
        <n-step title="P2 三端" description="W17-22 Electron+MCP+多模态" />
        <n-step title="P3 评估" description="W23-26 实验+大屏" />
      </n-steps>
    </n-card>

    <n-card title="技术栈快照" size="small">
      <n-descriptions :column="2" bordered size="small">
        <n-descriptions-item label="前端">Vue3 + Vite + TS + Tailwind + Naive UI + FullCalendar + ECharts</n-descriptions-item>
        <n-descriptions-item label="桌面">Electron 40 + better-sqlite3 + node-pty</n-descriptions-item>
        <n-descriptions-item label="后端">FastAPI + LangGraph + MCP + SQLModel</n-descriptions-item>
        <n-descriptions-item label="存储">PG16+pgvector + Neo4j5 + Redis7 + MinIO</n-descriptions-item>
        <n-descriptions-item label="模型">DeepSeek-V3 / Qwen2.5 + Qwen-VL + Whisper</n-descriptions-item>
        <n-descriptions-item label="工程">pnpm + turbo + Docker Compose</n-descriptions-item>
      </n-descriptions>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { NCard, NAlert, NButton, NTag, NSteps, NStep, NDescriptions, NDescriptionsItem } from 'naive-ui'
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
