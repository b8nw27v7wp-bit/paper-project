<template>
  <div class="space-y-3">
    <n-alert v-if="done" type="success" :title="`已生成 ${tasks.length} 个任务`">{{ mentor }}</n-alert>
    <n-timeline>
      <n-timeline-item v-for="(item, idx) in timeline" :key="idx" :type="item.type" :title="item.title" :content="item.content" :time="item.time" />
    </n-timeline>
    <div v-if="tasks.length">
      <n-divider>任务预览</n-divider>
      <n-list bordered size="small">
        <n-list-item v-for="t in tasks" :key="t.title">{{ t.title }} — {{ new Date(t.planned_start).toLocaleString() }}</n-list-item>
      </n-list>
    </div>
    <n-spin :show="loading" />
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { NTimeline, NTimelineItem, NAlert, NDivider, NList, NListItem, NSpin } from 'naive-ui'
import { subscribePlanStream } from '@/api/plans'

const props = defineProps<{ traceId: string | null; mentor?: string }>()
const emit = defineEmits<{ (e: 'done'): void }>()

const timeline = ref<any[]>([])
const tasks = ref<any[]>([])
const mentor = ref(props.mentor || '')
const loading = ref(true)
const done = ref(false)
let es: EventSource | null = null

watch(() => props.traceId, (id) => {
  if (!id) return
  timeline.value = []
  tasks.value = []
  done.value = false
  loading.value = true
  if (es) es.close()
  es = subscribePlanStream(id, {
    onThought: (d) => timeline.value.push({ type: 'info', title: '思考', content: d.text, time: new Date().toLocaleTimeString() }),
    onTool: (d) => timeline.value.push({ type: 'warning', title: '工具', content: `${d.tool} ${JSON.stringify(d.args)}`, time: new Date().toLocaleTimeString() }),
    onTask: (d) => { tasks.value.push(d.task); timeline.value.push({ type: 'success', title: '任务', content: d.task.title, time: new Date().toLocaleTimeString() }) },
    onDone: (d) => { done.value = true; loading.value = false; mentor.value = `共 ${d.count} 条 (${d.source})`; emit('done') },
    onError: () => { loading.value = false },
  })
}, { immediate: true })
</script>
