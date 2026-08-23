<template>
  <div class="space-y-6">
    <n-alert v-if="done" type="success" :show-icon="false" style="border-radius: 16px; background: #f5f5f7; border: none">
      <span class="text-[13px] font-medium text-ink">已生成 {{ tasks.length }} 个任务</span>
      <span class="ml-2 text-[13px] text-muted">{{ mentor }}</span>
    </n-alert>
    <n-timeline :icon-size="14">
      <n-timeline-item v-for="(item, idx) in timeline" :key="idx" :type="item.type === 'success' ? 'success' : item.type === 'error' ? 'error' : 'default'" :title="item.title" :content="item.content" :time="item.time" />
    </n-timeline>
    <div v-if="tasks.length" class="rounded-2xl bg-[#f5f5f7] p-4">
      <div class="text-[11px] tracking-widest text-muted font-medium">任务预览 · {{ tasks.length }}</div>
      <div class="mt-3 space-y-2">
        <div v-for="t in tasks" :key="t.title" class="flex justify-between text-[13px]"><span class="text-ink">{{ t.title }}</span><span class="text-muted">{{ new Date(t.planned_start).toLocaleDateString() }}</span></div>
      </div>
    </div>
    <n-spin :show="loading" />
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { NTimeline, NTimelineItem, NAlert, NSpin } from 'naive-ui'
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
    onThought: (d) => timeline.value.push({ type: 'default', title: d.agent || '思考', content: d.text, time: new Date().toLocaleTimeString() }),
    onTool: (d) => {
      const label = d.tool === 'researcher' ? 'Researcher' : d.tool
      timeline.value.push({ type: 'default', title: label, content: JSON.stringify(d.args), time: new Date().toLocaleTimeString() })
    },
    onTask: (d) => { tasks.value.push(d.task); timeline.value.push({ type: 'success', title: '任务', content: d.task.title, time: new Date().toLocaleTimeString() }) },
    onCritic: (d) => timeline.value.push({ type: d.feedback ? 'error' : 'success', title: 'Critic', content: d.feedback || '通过', time: new Date().toLocaleTimeString() }),
    onMentor: (d) => { mentor.value = d.text; timeline.value.push({ type: 'default', title: 'Mentor', content: d.text, time: new Date().toLocaleTimeString() }) },
    onReflector: (d) => timeline.value.push({ type: 'info', title: 'Reflector', content: JSON.stringify(d.patch), time: new Date().toLocaleTimeString() }),
    onDone: (d) => { done.value = true; loading.value = false; if (d.source) mentor.value += ` [${d.source} rewrites=${d.rewrites||0}]`; emit('done') },
    onError: () => { loading.value = false },
  })
}, { immediate: true })
</script>
