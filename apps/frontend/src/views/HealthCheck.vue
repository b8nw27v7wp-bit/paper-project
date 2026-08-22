<template>
  <div class="space-y-6">
    <n-card title="健康检查" class="shadow-sm">
      <template #header-extra>
        <n-space>
          <n-button size="small" :loading="loading" @click="load">刷新</n-button>
          <n-button size="small" type="primary" :loading="loadingV1" @click="loadV1">/api/v1/health</n-button>
        </n-space>
      </template>

      <n-spin :show="loading || loadingV1">
        <n-grid :cols="2" :x-gap="16" :y-gap="16">
          <n-gi>
            <n-card size="small" title="GET /health (Root Probe)">
              <n-code :code="JSON.stringify(root, null, 2)" language="json" />
              <template #footer>
                <n-tag :type="root?.data?.status === 'ok' ? 'success' : 'error'">{{ root?.data?.status ?? 'unknown' }}</n-tag>
                <span class="ml-2 text-xs text-gray-500">{{ rootUrl }}</span>
              </template>
            </n-card>
          </n-gi>
          <n-gi>
            <n-card size="small" title="GET /api/v1/health">
              <n-code :code="JSON.stringify(v1, null, 2)" language="json" />
              <template #footer>
                <n-tag :type="v1?.data?.status === 'ok' ? 'success' : 'warning'">{{ v1?.data?.status ?? 'unknown' }}</n-tag>
                <span class="ml-2 text-xs text-gray-500">{{ v1Url }}</span>
              </template>
            </n-card>
          </n-gi>
        </n-grid>

        <n-alert v-if="error" type="error" class="mt-4" :title="error" />
        <n-alert v-if="!error && root && v1" type="success" class="mt-4" title="P0 地基后端联通" />
      </n-spin>
    </n-card>

    <n-card title="接口清单 (P0 已实现)" size="small">
      <n-table :bordered="true" :single-line="false" size="small">
        <thead>
          <tr><th>方法</th><th>路径</th><th>说明</th><th>状态</th></tr>
        </thead>
        <tbody>
          <tr><td>GET</td><td>/health</td><td>根探针 (K8s/Docker)</td><td><n-tag size="small" type="success">已实现</n-tag></td></tr>
          <tr><td>GET</td><td>/api/v1/health</td><td>v1 健康 (含 services)</td><td><n-tag size="small" type="success">已实现</n-tag></td></tr>
          <tr><td>GET</td><td>/docs</td><td>Swagger</td><td><n-tag size="small" type="success">已实现</n-tag></td></tr>
          <tr><td>GET</td><td>/api/v1/plans/stream</td><td>SSE 预留</td><td><n-tag size="small" type="warning">预留</n-tag></td></tr>
          <tr><td>POST</td><td>/api/v1/goals</td><td>目标 CRUD</td><td><n-tag size="small">W3-6</n-tag></td></tr>
        </tbody>
      </n-table>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { NCard, NButton, NSpin, NAlert, NCode, NTag, NGrid, NGi, NSpace, NTable } from 'naive-ui'
import { fetchRootHealth, fetchHealth } from '@/api/health'

const root = ref<any>(null)
const v1 = ref<any>(null)
const loading = ref(false)
const loadingV1 = ref(false)
const error = ref('')

const rootUrl = computed(() => '/health')
const v1Url = computed(() => '/api/v1/health')

async function load() {
  loading.value = true
  error.value = ''
  try {
    root.value = await fetchRootHealth()
  } catch (e: any) {
    error.value = e?.message ?? String(e)
  } finally {
    loading.value = false
  }
}
async function loadV1() {
  loadingV1.value = true
  try {
    v1.value = await fetchHealth()
  } catch (e: any) {
    error.value = e?.message ?? String(e)
  } finally {
    loadingV1.value = false
  }
}
onMounted(async () => {
  await Promise.all([load(), loadV1()])
})
</script>
