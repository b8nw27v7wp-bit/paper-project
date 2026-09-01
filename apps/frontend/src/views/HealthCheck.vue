<template>
  <div class="space-y-10">
    <div>
      <h2 class="text-[24px] font-semibold tracking-[-0.02em] text-ink">健康</h2>
      <p class="mt-1 text-[13px] tracking-[-0.01em] text-muted">探针 · 白底无框 · 克制 — 含 MCP 状态</p>
    </div>
    <n-card class="apple-card" content-style="padding: 32px;">
      <template #header-extra>
        <n-space :size="8">
          <n-button size="small" style="border-radius: 20px" :loading="loading" @click="load">刷新</n-button>
          <n-button size="small" type="primary" style="border-radius: 20px" :loading="loadingV1" @click="loadV1">/api/v1/health</n-button>
          <n-button size="small" style="border-radius: 20px" :loading="loadingMcp" @click="loadMCP">MCP 状态</n-button>
        </n-space>
      </template>

      <n-spin :show="loading || loadingV1">
        <n-grid :cols="2" :x-gap="24" :y-gap="16">
          <n-gi>
            <n-card size="small" title="GET /health (Root Probe)" style="border-radius: 16px">
              <n-code :code="JSON.stringify(root, null, 2)" language="json" />
              <template #footer>
                <n-tag :type="root?.data?.status === 'ok' ? 'success' : 'error'" style="border-radius: 20px">{{ root?.data?.status ?? 'unknown' }}</n-tag>
                <span class="ml-2 text-[11px] tracking-wide text-muted">{{ rootUrl }}</span>
              </template>
            </n-card>
          </n-gi>
          <n-gi>
            <n-card size="small" title="GET /api/v1/health" style="border-radius: 16px">
              <n-code :code="JSON.stringify(v1, null, 2)" language="json" />
              <template #footer>
                <n-tag :type="v1?.data?.status === 'ok' ? 'success' : 'warning'" style="border-radius: 20px">{{ v1?.data?.status ?? 'unknown' }}</n-tag>
                <span class="ml-2 text-[11px] tracking-wide text-muted">{{ v1Url }}</span>
              </template>
            </n-card>
          </n-gi>
        </n-grid>

        <n-alert v-if="error" type="error" class="mt-4" :title="error" />
        <n-alert v-if="!error && root && v1" type="success" class="mt-4" title="P0 地基后端联通" />
      </n-spin>
    </n-card>

    <n-card class="apple-card" title="MCP 服务状态 (P1C)" content-style="padding: 32px;">
      <template #header-extra>
        <n-space :size="8">
          <n-button size="small" style="border-radius: 20px" :loading="loadingMcp" @click="loadMCP">刷新 MCP</n-button>
          <n-button size="small" style="border-radius: 20px" :loading="loadingTools" @click="loadTools">工具列表</n-button>
        </n-space>
      </template>
      <n-spin :show="loadingMcp">
        <n-grid :cols="3" :x-gap="16" :y-gap="16" v-if="mcpServers.length">
          <n-gi v-for="srv in mcpServers" :key="srv.name">
            <n-card size="small" :title="srv.name" style="border-radius: 12px">
              <div class="space-y-2 text-[13px]">
                <div class="flex items-center gap-2">
                  <n-tag :type="srv.status === 'running' ? 'success' : 'error'" size="small" style="border-radius: 20px">{{ srv.status }}</n-tag>
                  <span class="text-[11px] tracking-wide text-muted">{{ srv.command || 'mock' }}</span>
                </div>
                <div class="text-[11px] tracking-wide text-muted">工具: {{ (srv.tools || []).join(', ') || '—' }}</div>
              </div>
            </n-card>
          </n-gi>
        </n-grid>
        <n-empty v-else description="暂无 MCP 服务" />
        <div class="mt-6" v-if="mcpTools.length">
          <div class="text-[13px] font-semibold tracking-[-0.01em] text-ink mb-2">可用工具</div>
          <n-table :bordered="false" size="small">
            <thead><tr><th>Server</th><th>Tool</th><th>Full Name</th></tr></thead>
            <tbody>
              <tr v-for="t in mcpTools" :key="t.full_name"><td>{{ t.server }}</td><td>{{ t.tool }}</td><td>{{ t.full_name }}</td></tr>
            </tbody>
          </n-table>
        </div>
        <n-code v-if="mcpRaw" :code="JSON.stringify(mcpRaw, null, 2)" language="json" class="mt-4" />
        <n-alert v-if="mcpError" type="error" class="mt-4" :title="mcpError" />
      </n-spin>
    </n-card>

    <n-card title="接口清单 (P0 已实现)" size="small" style="border-radius: 16px">
      <n-table :bordered="false" :single-line="false" size="small">
        <thead>
          <tr><th>方法</th><th>路径</th><th>说明</th><th>状态</th></tr>
        </thead>
        <tbody>
          <tr><td>GET</td><td>/health</td><td>根探针 (K8s/Docker)</td><td><n-tag size="small" type="success" style="border-radius: 20px">已实现</n-tag></td></tr>
          <tr><td>GET</td><td>/api/v1/health</td><td>v1 健康 (含 services)</td><td><n-tag size="small" type="success" style="border-radius: 20px">已实现</n-tag></td></tr>
          <tr><td>GET</td><td>/api/v1/mcp/servers</td><td>MCP 服务列表</td><td><n-tag size="small" type="success" style="border-radius: 20px">已实现</n-tag></td></tr>
          <tr><td>GET</td><td>/api/v1/mcp/tools</td><td>MCP 工具列表</td><td><n-tag size="small" type="success" style="border-radius: 20px">已实现</n-tag></td></tr>
          <tr><td>POST</td><td>/api/v1/mcp/call</td><td>MCP 工具调用</td><td><n-tag size="small" type="success" style="border-radius: 20px">已实现</n-tag></td></tr>
          <tr><td>GET</td><td>/docs</td><td>Swagger</td><td><n-tag size="small" type="success" style="border-radius: 20px">已实现</n-tag></td></tr>
          <tr><td>GET</td><td>/api/v1/plans/stream</td><td>SSE 含 Last-Event-ID</td><td><n-tag size="small" type="success" style="border-radius: 20px">已实现</n-tag></td></tr>
          <tr><td>POST</td><td>/api/v1/goals</td><td>目标 CRUD</td><td><n-tag size="small" style="border-radius: 20px">已实现</n-tag></td></tr>
        </tbody>
      </n-table>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { NCard, NButton, NSpin, NAlert, NCode, NTag, NGrid, NGi, NSpace, NTable, NEmpty } from 'naive-ui'
import { fetchRootHealth, fetchHealth } from '@/api/health'
import { listMCPServers, listMCPTools } from '@/api/mcp'
import type { ApiEnvelope, HealthStatus, MCPServer, MCPTool } from '@/types'
import { extractErrorMessage } from '@/api/client'

const root = ref<ApiEnvelope<HealthStatus> | null>(null)
const v1 = ref<ApiEnvelope<HealthStatus> | null>(null)
const loading = ref(false)
const loadingV1 = ref(false)
const error = ref('')

const rootUrl = computed(() => '/health')
const v1Url = computed(() => '/api/v1/health')

const mcpServers = ref<MCPServer[]>([])
const mcpTools = ref<MCPTool[]>([])
const mcpRaw = ref<ApiEnvelope<MCPServer[]> | null>(null)
const loadingMcp = ref(false)
const loadingTools = ref(false)
const mcpError = ref('')

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    root.value = await fetchRootHealth()
  } catch (e: unknown) {
    error.value = extractErrorMessage(e)
  } finally {
    loading.value = false
  }
}
async function loadV1(): Promise<void> {
  loadingV1.value = true
  try {
    v1.value = await fetchHealth()
  } catch (e: unknown) {
    error.value = extractErrorMessage(e)
  } finally {
    loadingV1.value = false
  }
}
async function loadMCP(): Promise<void> {
  loadingMcp.value = true
  mcpError.value = ''
  try {
    const res = await listMCPServers()
    mcpServers.value = res.data || []
    mcpRaw.value = res
  } catch (e: unknown) {
    mcpError.value = extractErrorMessage(e)
  } finally {
    loadingMcp.value = false
  }
}
async function loadTools(): Promise<void> {
  loadingTools.value = true
  try {
    const res = await listMCPTools()
    mcpTools.value = res.data || []
  } catch (e: unknown) {
    mcpError.value = extractErrorMessage(e)
  } finally {
    loadingTools.value = false
  }
}
onMounted(() => {
  void Promise.all([load(), loadV1(), loadMCP(), loadTools()])
})
</script>
