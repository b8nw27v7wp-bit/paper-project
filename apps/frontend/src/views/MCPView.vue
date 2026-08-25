<template>
  <div class="space-y-8">
    <div class="flex items-end justify-between">
      <div>
        <h2 class="text-[24px] font-semibold tracking-[-0.02em] text-ink">MCP 工具</h2>
        <p class="mt-1 text-[13px] text-muted">Model Context Protocol · 3 servers · mock 联调</p>
      </div>
      <n-space>
        <n-button strong secondary @click="load" :loading="loading">刷新</n-button>
        <n-button type="primary" @click="showCall=true">调用工具</n-button>
      </n-space>
    </div>

    <n-grid :cols="3" :x-gap="16" :y-gap="16">
      <n-gi v-for="srv in servers" :key="srv.name">
        <n-card class="apple-card" :title="srv.name">
          <div class="space-y-2">
            <n-tag :type="srv.status==='running'?'success':'error'" size="small">{{ srv.status }}</n-tag>
            <div class="text-xs text-muted">command: {{ srv.command }}</div>
            <div class="text-xs text-muted">tools: {{ (srv.tools||[]).join(', ') }}</div>
          </div>
        </n-card>
      </n-gi>
    </n-grid>

    <n-card title="可用工具" class="apple-card">
      <n-table :bordered="true" size="small">
        <thead><tr><th>Server</th><th>Tool</th><th>Full Name</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="t in tools" :key="t.full_name"><td>{{ t.server }}</td><td>{{ t.tool }}</td><td>{{ t.full_name }}</td><td><n-button size="small" @click="prefill(t)">调用</n-button></td></tr>
        </tbody>
      </n-table>
    </n-card>

    <n-card v-if="lastResult" title="最近调用结果" class="apple-card">
      <n-code :code="JSON.stringify(lastResult, null, 2)" language="json" />
    </n-card>

    <n-modal v-model:show="showCall" preset="card" title="调用 MCP 工具" style="width:640px">
      <n-form label-placement="left" label-width="80">
        <n-form-item label="Server"><n-select v-model:value="form.server" :options="serverOpts" placeholder="选择 server" /></n-form-item>
        <n-form-item label="Tool"><n-input v-model:value="form.tool" placeholder="create_event / web_search" /></n-form-item>
        <n-form-item label="Args (JSON)"><n-input v-model:value="form.argsJson" type="textarea" :autosize="{minRows:4}" placeholder='{"title":"Test","query":"AI"}' /></n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end"><n-button @click="showCall=false">取消</n-button><n-button type="primary" :loading="calling" @click="doCall">调用</n-button></n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { NCard, NSpace, NButton, NGrid, NGi, NTag, NTable, NCode, NModal, NForm, NFormItem, NSelect, NInput, useMessage } from 'naive-ui'
import { listMCPServers, listMCPTools, callMCPTool } from '@/api/mcp'

const message = useMessage()
const servers = ref<any[]>([])
const tools = ref<any[]>([])
const loading = ref(false)
const lastResult = ref<any>(null)
const showCall = ref(false)
const calling = ref(false)
const form = ref({ server: 'calendar', tool: 'create_event', argsJson: '{"title":"Test","start":"2026-08-25T09:00:00Z","end":"2026-08-25T10:00:00Z"}' })
const serverOpts = computed(()=> servers.value.map(s=>({ label: s.name, value: s.name })))

function prefill(t:any){
  form.value.server = t.server
  form.value.tool = t.tool
  if(t.server==='search') form.value.argsJson='{"query":"AI"}'
  else if(t.server==='calendar') form.value.argsJson='{"title":"Test","start":"2026-08-25T09:00:00Z","end":"2026-08-25T10:00:00Z"}'
  else form.value.argsJson='{"title":"待办任务"}'
  showCall.value=true
}

async function load(){
  loading.value=true
  try {
    const s = await listMCPServers()
    servers.value = s.data || []
    const t = await listMCPTools()
    tools.value = t.data || []
  } catch(e:any){ message.error(e?.response?.data?.msg||e.message) }
  finally { loading.value=false }
}
async function doCall(){
  calling.value=true
  try {
    let args:any={}
    try { args = JSON.parse(form.value.argsJson) } catch { throw new Error('Args 不是合法 JSON') }
    const res = await callMCPTool(form.value.server, form.value.tool, args)
    lastResult.value = res.data
    message.success('调用成功')
    showCall.value=false
  } catch(e:any){ message.error(e?.response?.data?.msg||e.message) }
  finally { calling.value=false }
}
onMounted(load)
</script>
