<template>
  <div class="space-y-10">
    <div class="flex items-end justify-between">
      <div>
        <h2 class="text-[20px] font-semibold tracking-[-0.02em] text-ink">知识库</h2>
        <p class="mt-1 text-[11px] tracking-wide text-muted">F05 知识库 · 上传入库 · 500字切块 · Top10 证据式检索</p>
      </div>
      <n-space :size="8" align="center">
        <n-input v-model:value="subject" placeholder="学科 如: 英语" style="width: 144px" clearable />
        <n-input v-model:value="query" placeholder="检索关键词" style="width: 168px" clearable @keydown.enter="onSearch" />
        <n-button strong secondary style="border-radius: 20px" :loading="searching" @click="onSearch">检索</n-button>
        <n-button style="border-radius: 20px" :loading="loading" @click="load" aria-label="刷新切片">刷新</n-button>
      </n-space>
    </div>

    <n-grid :cols="3" :x-gap="16">
      <n-gi><n-card class="stat-card" :bordered="false" aria-label="知识切片统计"><div class="text-[11px] tracking-widest font-medium text-muted">知识切片</div><div class="mt-2 text-[22px] font-semibold tracking-[-0.03em] text-ink">{{ total }}</div><div class="mt-1 text-[11px] tracking-wide text-muted">pgvector · 500字/50重叠 · HNSW</div></n-card></n-gi>
      <n-gi><n-card class="stat-card" :bordered="false" aria-label="已入库统计"><div class="text-[11px] tracking-widest font-medium text-muted">已入库</div><div class="mt-2 text-[22px] font-semibold tracking-[-0.03em] text-ink">{{ chunks.length }}</div><div class="mt-1 text-[11px] tracking-wide text-muted">当前页 · subject {{ subject || '全部' }}</div></n-card></n-gi>
      <n-gi><n-card class="stat-card" :bordered="false" aria-label="检索统计"><div class="text-[11px] tracking-widest font-medium text-muted">检索</div><div class="mt-2 text-[14px] font-medium tracking-[-0.01em] text-ink">{{ searchHits.length }} 条 Top10</div><div class="mt-1 text-[11px] tracking-wide text-muted">向量 + 图谱 PREREQ</div></n-card></n-gi>
    </n-grid>

    <n-card class="apple-card" :bordered="false" content-style="padding: 24px;" aria-label="上传入库">
      <template #header><span class="text-[13px] font-semibold tracking-[-0.01em] text-ink">上传入库 · 20M 限制 · 自动切块+图谱抽取</span><span class="ml-2 text-[11px] tracking-wide text-muted">拖拽至此</span></template>
      <div class="flex items-center gap-4 rounded-[16px] border border-dashed border-[var(--c-border)] bg-[#f5f5f7]/50 p-4 hover:bg-[var(--c-surface)] transition-colors" role="region" aria-label="文件上传拖拽区">
        <n-upload :max="1" :show-file-list="false" :custom-request="onUpload" accept=".pdf,.jpg,.jpeg,.png,.txt,.md">
          <n-button type="primary" style="border-radius: 20px" :loading="uploading" aria-label="选择文件上传">选择文件上传</n-button>
        </n-upload>
        <div class="text-[11px] leading-5 tracking-wide text-muted">支持 PDF/JPG/PNG/TXT/MD · MinIO 落盘 + uuid 重命名 · 同步抽取 PREREQ 入 Neo4j · GBK 智能解码</div>
      </div>
      <n-alert v-if="uploadResult" type="success" :show-icon="false" class="mt-4" style="border-radius: 12px; background: var(--c-surface); border: none">
        <span class="text-[13px] font-medium tracking-[-0.01em] text-ink">已入库 {{ uploadResult.chunks }} 切片 · {{ uploadResult.knowledges }} 知识点</span>
        <span class="ml-2 text-[11px] tracking-wide text-muted">{{ uploadResult.triples.length }} triples</span>
      </n-alert>
      <div class="mt-4 flex items-center gap-2">
        <n-input v-model:value="ingestSubject" placeholder="学科标签 可选" style="width: 168px" />
        <span class="text-[11px] tracking-wide text-muted">学科将注入 Memory.vectorHints + Graph 节点 subject</span>
      </div>
    </n-card>

    <n-card v-if="searchHits.length" class="apple-card" :bordered="false" content-style="padding: 24px;" aria-label="检索结果">
      <template #header><span class="text-[13px] font-semibold tracking-[-0.01em] text-ink">检索结果 · Top10 + 图谱</span></template>
      <div class="space-y-3">
        <div v-for="c in searchHits" :key="String(c.id)" class="rounded-[16px] bg-[var(--c-surface)] p-4">
          <div class="text-[13px] leading-5 tracking-[-0.01em] text-ink line-clamp-2">{{ c.content }}</div>
          <div class="mt-1 text-[11px] tracking-wide text-muted">score {{ (c.score ?? 0).toFixed(3) }} · {{ c.type || 'knowledge' }}</div>
        </div>
        <div v-if="graphHits.length" class="text-[11px] tracking-wide text-muted">图谱命中 {{ graphHits.length }} 条 PREREQ</div>
      </div>
    </n-card>

    <n-card class="apple-card" :bordered="false" content-style="padding: 0 24px 24px 24px;" aria-label="知识切片列表">
      <template #header>
        <div class="flex items-center justify-between w-full">
          <span class="text-[13px] font-semibold tracking-[-0.01em] text-ink">知识切片 · 分页</span>
          <n-button size="small" style="border-radius: 20px" :loading="loading" @click="load" aria-label="刷新切片">刷新</n-button>
        </div>
      </template>
      <n-skeleton v-if="loading && !chunks.length && !loadError" text :repeat="3" :sharp="false" class="mt-4" />
      <n-alert v-else-if="loadError" title="加载失败，请重试" type="error" :show-icon="false" class="mt-4" style="border-radius: 12px">
        <span class="text-[13px] tracking-[-0.01em]">切片加载失败：{{ loadError }}</span>
        <div class="mt-2">
          <n-button size="small" style="border-radius: 20px" :loading="loading" @click="load">重试</n-button>
        </div>
      </n-alert>
      <n-alert v-if="highlightId" type="info" :show-icon="false" class="mb-3 rounded-[12px]">
        <span class="text-[12px]">来自规划溯源，高亮切片 #{{ highlightId }}</span>
        <n-button size="tiny" secondary style="border-radius: 20px; margin-left: 8px" @click="highlightId = ''">清除</n-button>
      </n-alert>
      <div v-if="chunks.length && !loadError" class="table-scroll">
        <n-data-table
          :columns="cols"
          :data="chunks"
          :pagination="false"
          :loading="loading"
          :row-key="(r: RagChunk) => r.id"
          :row-props="rowProps"
          :bordered="false"
          size="small"
        />
      </div>
      <n-empty v-else-if="!loading && !loadError && !chunks.length" description="暂无切片，去上传" class="py-10">
        <template #extra>
          <span class="text-[11px] tracking-wide text-muted">在上方上传卡选择文件入库</span>
        </template>
      </n-empty>
      <div v-if="chunks.length && !loadError" class="flex justify-end items-center mt-8 pt-4">
        <span class="text-[11px] tracking-wide text-muted mr-4">{{ total }} 条 · 第 {{ page }} 页</span>
        <n-pagination
          v-model:page="page"
          :page-size="size"
          :item-count="total"
          :page-sizes="[10, 20, 50]"
          show-size-picker
          @update:page="load"
          @update:page-size="onSize"
        />
      </div>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref, h, onMounted, watch } from 'vue'
defineOptions({ name: 'RAGView' })
import { NCard, NSpace, NButton, NInput, NGrid, NGi, NDataTable, NPagination, NUpload, NAlert, NEmpty, NSkeleton, useMessage, type DataTableColumns } from 'naive-ui'
import { ingestRag, searchRag, listChunks, type RagChunk } from '@/api/rag'
import { extractErrorMessage } from '@/api/client'
import { useRoute } from 'vue-router'

const message = useMessage()
const route = useRoute()
// 溯源高亮：PlanStream 跳转 /rag?highlight=<chunk_id>，命中行高亮
const highlightId = ref<string>('')
function rowProps(r: RagChunk) {
  if (highlightId.value && String(r.id) === highlightId.value) {
    return { style: 'background: #eff6ff; box-shadow: inset 3px 0 0 #0071e3;' }
  }
  return {}
}
const subject = ref<string>('')
const query = ref<string>('')
const ingestSubject = ref<string>('')
const page = ref<number>(1)
const size = ref<number>(20)
const total = ref<number>(0)
const chunks = ref<RagChunk[]>([])
const loading = ref<boolean>(false)
const loadError = ref<string>('')
const searching = ref<boolean>(false)
const uploading = ref<boolean>(false)
const searchHits = ref<RagChunk[]>([])
const graphHits = ref<unknown[]>([])
const uploadResult = ref<{ chunks: number; knowledges: number; triples: unknown[] } | null>(null)

const cols: DataTableColumns<RagChunk> = [
  { title: 'ID', key: 'id', width: 72 },
  { title: '内容', key: 'content', ellipsis: { tooltip: true } as const, render: (r: RagChunk) => h('span', { class: 'text-[13px] tracking-[-0.01em] text-ink' }, String(r.content).slice(0, 120)) },
  { title: '类型', key: 'type', width: 96, render: (r: RagChunk) => h('span', { class: 'text-[11px] tracking-wide text-muted' }, r.type || 'knowledge') },
  { title: '创建时间', key: 'created_at', width: 172, render: (r: RagChunk) => new Date(String(r.created_at ?? '')).toLocaleString() },
]

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const res = await listChunks({ subject: subject.value || undefined, page: page.value, size: size.value })
    chunks.value = res.data.items as RagChunk[]
    total.value = res.data.total
  } catch (e: unknown) {
    loadError.value = extractErrorMessage(e)
    message.error(loadError.value)
  } finally {
    loading.value = false
  }
}
function onSize(v: number): void {
  size.value = v
  page.value = 1
  void load()
}
let searchTimer: ReturnType<typeof setTimeout> | null = null
async function onSearch(): Promise<void> {
  if (!query.value.trim()) { message.warning('请输入关键词'); return }
  if (searchTimer) clearTimeout(searchTimer)
  searching.value = true
  try {
    const res = await searchRag({ q: query.value.trim(), top_k: 10, subject: subject.value || undefined })
    const d = res.data as { chunks: RagChunk[]; graph: unknown[] }
    searchHits.value = d.chunks || []
    graphHits.value = d.graph || []
    if (!searchHits.value.length) message.warning('无匹配切片')
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
  } finally {
    searching.value = false
  }
}
watch(query, (v) => {
  if (!v.trim()) { searchHits.value = []; graphHits.value = []; return }
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { void onSearch() }, 400)
})
interface UploadCustom { file: { file: File | null } }
async function onUpload(opts: UploadCustom): Promise<void> {
  const f = opts.file?.file
  if (!f) return
  if (f.size > 20 * 1024 * 1024) { message.error('文件>20M'); return }
  uploading.value = true
  try {
    const res = await ingestRag(f, ingestSubject.value || undefined)
    uploadResult.value = res.data as { chunks: number; knowledges: number; triples: unknown[] }
    message.success(`入库 ${uploadResult.value.chunks} 切片`)
    void load()
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
  } finally {
    uploading.value = false
  }
}
// key=r.path 后溯源跳转（同页切 ?highlight=）不重挂，监听补高亮
watch(() => route.query.highlight, (v) => {
  try { highlightId.value = typeof v === 'string' ? v : '' } catch {}
})
onMounted(() => {
  try {
    const h = route.query.highlight
    if (typeof h === 'string' && h) highlightId.value = h
  } catch {}
  void load()
})
</script>

<style scoped>
:deep(.n-data-table-thead th) { background: var(--c-bg) !important; font-size: 11px; letter-spacing: 0.08em; color: var(--c-muted); font-weight: 510; border-bottom: 1px solid var(--c-hairline) !important; }
:deep(.n-data-table-td) { border-bottom: 1px solid var(--c-hairline) !important; font-size: 13px; }
</style>
