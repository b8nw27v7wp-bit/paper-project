<template>
  <div class="space-y-10">
    <div class="flex items-end justify-between">
      <div>
        <h2 class="text-[20px] font-semibold tracking-[-0.02em] text-ink">MCP 工具</h2>
        <p class="mt-1 text-[11px] tracking-wide text-muted">{{ mcpSubtitle }}</p>
      </div>
      <n-space :size="8" align="center">
        <n-button strong secondary style="border-radius: 20px" :loading="loading" @click="load">刷新</n-button>
        <n-button type="primary" style="border-radius: 20px" @click="showCall = true">调用工具</n-button>
      </n-space>
    </div>

    <n-skeleton v-if="loading && !servers.length && !loadError" text :repeat="3" :sharp="false" />
    <n-alert v-else-if="loadError" title="加载失败，请重试" type="error" :show-icon="false" class="rounded-[12px]">
      <span class="text-[13px] tracking-[-0.01em]">MCP 加载失败：{{ loadError }}</span>
      <div class="mt-2">
        <n-button size="small" style="border-radius: 20px" :loading="loading" @click="load">重试</n-button>
      </div>
    </n-alert>
    <template v-else>
    <n-grid v-if="servers.length" :cols="3" :x-gap="24" :y-gap="16">
      <n-gi v-for="srv in servers" :key="srv.name">
        <n-card class="apple-card" :bordered="false" content-style="padding: 24px;">
          <template #header><span class="text-[13px] font-semibold tracking-[-0.01em] text-ink">{{ srv.name }}</span></template>
          <div class="space-y-2">
            <n-tag :type="srv.status === 'running' ? 'success' : 'error'" size="small" style="border-radius: 20px">{{ srv.status }}</n-tag>
            <div class="text-[11px] tracking-wide text-muted">command: {{ srv.command }}</div>
            <div class="text-[11px] tracking-wide text-muted">tools: {{ (srv.tools || []).join(', ') }}</div>
          </div>
        </n-card>
      </n-gi>
    </n-grid>
    <n-empty v-else description="暂无 MCP 服务，点击刷新重试" class="py-10">
      <template #extra>
        <n-button size="small" style="border-radius: 20px" :loading="loading" @click="load">刷新</n-button>
      </template>
    </n-empty>

    <n-card class="apple-card" :bordered="false" content-style="padding: 0 24px 24px 24px;">
      <template #header><span class="text-[13px] font-semibold tracking-[-0.01em] text-ink">可用工具</span><span v-if="detailedCount" class="ml-2 text-[11px] tracking-wide text-muted">详情 {{ detailedCount }} 个 · description+schema</span></template>
      <div v-if="tools.length" class="table-scroll table-scroll--narrow">
        <n-table :bordered="false" size="small">
        <thead><tr><th class="text-[11px] font-medium tracking-widest text-muted">Server</th><th class="text-[11px] font-medium tracking-widest text-muted">Tool</th><th class="text-[11px] font-medium tracking-widest text-muted">Full Name</th><th v-if="hasDetailed" class="text-[11px] font-medium tracking-widest text-muted">详情</th><th class="text-[11px] font-medium tracking-widest text-muted">操作</th></tr></thead>
        <tbody>
          <tr v-for="t in tools" :key="t.full_name">
            <td class="text-[13px] text-ink">{{ t.server }}</td>
            <td class="text-[13px] text-ink">{{ t.tool }}</td>
            <td class="text-[13px] text-ink">{{ t.full_name }}</td>
            <td v-if="hasDetailed" class="text-[12px] text-muted">
              <template v-if="detailOf(t)">
                <div class="max-w-[280px] truncate" :title="detailOf(t)?.description || ''">{{ detailOf(t)?.description || '—' }}</div>
                <n-button v-if="detailOf(t)?.schema != null" size="tiny" style="border-radius: 20px" class="mt-1" @click="toggleSchema(t.full_name)">{{ isSchemaOpen(t.full_name) ? '收起 schema' : '展开 schema' }}</n-button>
                <n-code v-if="detailOf(t)?.schema != null && isSchemaOpen(t.full_name)" :code="prettySchema(detailOf(t)?.schema)" language="json" class="mt-1" />
              </template>
              <span v-else class="text-[11px]">—</span>
            </td>
            <td><n-button size="small" style="border-radius: 20px" @click="prefill(t)">调用</n-button></td>
          </tr>
        </tbody>
      </n-table>
      </div>
      <n-empty v-else description="暂无可用工具，先刷新服务" class="py-10">
        <template #extra>
          <n-button size="small" style="border-radius: 20px" :loading="loading" @click="load">刷新</n-button>
        </template>
      </n-empty>
    </n-card>

    <n-card v-if="lastResult" class="apple-card" :bordered="false" content-style="padding: 24px;">
      <template #header><span class="text-[13px] font-semibold tracking-[-0.01em] text-ink">最近调用结果</span></template>
      <n-code :code="JSON.stringify(lastResult, null, 2)" language="json" />
    </n-card>
    </template>

    <n-modal v-model:show="showCall" preset="card" title="调用 MCP 工具" style="width: 640px; border-radius: 16px">
      <div class="space-y-4 py-2">
      <n-form label-placement="left" label-width="80">
        <n-form-item label="Server"><n-select v-model:value="form.server" :options="serverOpts" placeholder="选择 server" /></n-form-item>
        <n-form-item label="Tool"><n-input v-model:value="form.tool" placeholder="create_event / web_search" /></n-form-item>
        <n-form-item label="Args (JSON)"><n-input v-model:value="form.argsJson" type="textarea" :autosize="{ minRows: 4 }" placeholder='{"title":"Test","query":"AI"}' /></n-form-item>
      </n-form>
      </div>
      <template #footer>
        <n-space justify="end" :size="8"><n-button style="border-radius: 20px" @click="showCall = false">取消</n-button><n-button type="primary" style="border-radius: 20px" :loading="calling" @click="doCall">调用</n-button></n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
defineOptions({ name: 'MCPView' })
import {
  NCard,
  NSpace,
  NButton,
  NGrid,
  NGi,
  NTag,
  NTable,
  NCode,
  NModal,
  NForm,
  NFormItem,
  NSelect,
  NInput,
  NEmpty,
  NSkeleton,
  NAlert,
  useMessage,
} from 'naive-ui'
import { listMCPServers, listMCPTools, callMCPTool } from '@/api/mcp'
import { listAgentTools, type AgentToolDetailed } from '@/api/plans'
import type { MCPServer, MCPTool } from '@/types'
import { extractErrorMessage } from '@/api/client'
import { buildMcpSubtitle } from '@/utils/inspector'

const message = useMessage()
const servers = ref<MCPServer[]>([])
const tools = ref<MCPTool[]>([])
// Wave-2 P1-12：工具详情（GET /agent/tools，description+schema 折叠；失败回退现有三列）
const detailed = ref<AgentToolDetailed[]>([])
const openSchemas = ref<Set<string>>(new Set())
const hasDetailed = computed(() => detailed.value.length > 0)
const detailedCount = computed(() => detailed.value.length)
function detailOf(t: MCPTool): AgentToolDetailed | undefined {
  const full = String(t.full_name || '')
  const name = String(t.tool || '')
  return detailed.value.find((d) => d.name === full || d.name === name || full.endsWith(`/${d.name}`) || full.endsWith(`:${d.name}`))
}
function isSchemaOpen(key: string): boolean {
  return openSchemas.value.has(key)
}
function toggleSchema(key: string): void {
  const next = new Set(openSchemas.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  openSchemas.value = next
}
function prettySchema(v: unknown): string {
  try { return JSON.stringify(v, null, 2) } catch { return String(v) }
}
const loading = ref(false)
const loadError = ref('')
const lastResult = ref<Record<string, unknown> | null>(null)
const showCall = ref(false)
const calling = ref(false)
const form = ref({ server: 'calendar', tool: 'create_event', argsJson: '{"title":"Test","start":"2026-08-25T09:00:00Z","end":"2026-08-25T10:00:00Z"}' })
const serverOpts = computed(() => servers.value.map((s) => ({ label: s.name, value: s.name })))
// 动态副标题：serverOpts 计数 + 真实连接态（替代“3 servers·mock联调”写死）
const runningCount = computed(() => servers.value.filter((s) => s.status === 'running').length)
const mcpSubtitle = computed(() =>
  buildMcpSubtitle({ total: servers.value.length, running: runningCount.value, loading: loading.value, hasError: !!loadError.value }),
)

function prefill(t: MCPTool): void {
  form.value.server = t.server
  form.value.tool = t.tool
  if (t.server === 'search') form.value.argsJson = '{"query":"AI"}'
  else if (t.server === 'calendar') form.value.argsJson = '{"title":"Test","start":"2026-08-25T09:00:00Z","end":"2026-08-25T10:00:00Z"}'
  else form.value.argsJson = '{"title":"待办任务"}'
  showCall.value = true
}

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const s = await listMCPServers()
    servers.value = s.data || []
    const t = await listMCPTools()
    tools.value = t.data || []
    // 详情增强：失败静默回退现有三列，不阻断主列表
    try {
      const d = await listAgentTools()
      detailed.value = Array.isArray(d.data) ? d.data.filter((x) => x && typeof x.name === 'string') : []
    } catch {
      detailed.value = []
    }
  } catch (e: unknown) {
    const msg = extractErrorMessage(e)
    loadError.value = msg
    message.error(msg)
  } finally {
    loading.value = false
  }
}
async function doCall(): Promise<void> {
  calling.value = true
  try {
    let args: Record<string, unknown> = {}
    try {
      args = JSON.parse(form.value.argsJson) as Record<string, unknown>
    } catch {
      throw new Error('Args 不是合法 JSON')
    }
    const res = await callMCPTool(form.value.server, form.value.tool, args)
    lastResult.value = res.data as Record<string, unknown>
    message.success('调用成功')
    showCall.value = false
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
  } finally {
    calling.value = false
  }
}
onMounted(() => {
  void load()
})
</script>
