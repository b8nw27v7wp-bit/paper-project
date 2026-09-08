<template>
  <div class="rounded-[16px] bg-[var(--c-surface)] p-4 space-y-3" aria-label="番茄倒计时">
    <div class="flex items-center justify-between">
      <span class="text-[13px] font-semibold tracking-[-0.01em] text-ink">番茄倒计时</span>
      <span class="text-[20px] font-semibold tracking-[-0.02em] text-ink font-mono" aria-live="polite">{{ display }}</span>
    </div>
    <div class="flex items-center gap-2" role="radiogroup" aria-label="时长预设">
      <button
        v-for="p in presets"
        :key="p.secs"
        role="radio"
        :aria-checked="totalSecs === p.secs"
        :class="['px-3 py-1 text-[12px] rounded-full border transition-colors', totalSecs === p.secs ? 'bg-ink text-white border-transparent' : 'border-hairline text-muted hover:text-ink bg-[var(--c-bg)]']"
        :disabled="running"
        @click="selectPreset(p.secs)"
      >{{ p.label }}</button>
      <span v-if="status === 'running'" class="ml-auto text-[11px] tracking-wide text-muted">专注中</span>
      <span v-else-if="status === 'paused'" class="ml-auto text-[11px] tracking-wide text-muted">已暂停</span>
      <span v-else-if="status === 'done'" class="ml-auto text-[11px] tracking-wide text-muted">已完成</span>
    </div>
    <n-space :size="8">
      <n-button v-if="!running" type="primary" size="small" style="border-radius: 20px" :loading="reporting" :disabled="!canStart" @click="start">开始</n-button>
      <n-button v-if="running" size="small" style="border-radius: 20px" @click="pause">暂停</n-button>
      <n-button size="small" style="border-radius: 20px" :disabled="reporting" @click="reset">重置</n-button>
    </n-space>
    <div class="text-[11px] tracking-wide text-muted">超 10 分钟分段上报：25 分钟按 600＋600＋300 秒分 3 次上报，专注度按 0.8 记</div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { NSpace, NButton, useMessage } from 'naive-ui'
import { reportPomodoro } from '@/api/tasks'
import { extractErrorMessage } from '@/api/client'

defineOptions({ name: 'PomodoroTimer' })

const props = defineProps<{ taskId: number }>()
const emit = defineEmits<{ (e: 'reported'): void }>()

const message = useMessage()

const presets = [
  { label: '5分钟', secs: 300 },
  { label: '10分钟', secs: 600 },
  { label: '25分钟', secs: 1500 },
] as const

const totalSecs = ref<number>(300)
const remaining = ref<number>(300)
const status = ref<'idle' | 'running' | 'paused' | 'done'>('idle')
const reporting = ref(false)

let timer: ReturnType<typeof setInterval> | null = null
let savedTitle = ''

const running = computed(() => status.value === 'running')
const canStart = computed(() => !reporting.value && props.taskId > 0 && (status.value === 'idle' || status.value === 'paused' || status.value === 'done'))

const display = computed(() => {
  const s = Math.max(0, Math.floor(remaining.value))
  const m = Math.floor(s / 60)
  const r = s % 60
  return `${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`
})

function clearTimer(): void {
  if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
}

function restoreTitle(): void {
  try {
    if (savedTitle) document.title = savedTitle
  } catch {}
  savedTitle = ''
}

function paintTitle(): void {
  try {
    if (!savedTitle) savedTitle = document.title
    document.title = `番茄 ${display.value} - 专注中`
  } catch {}
}

function selectPreset(secs: number): void {
  if (running.value) return
  clearTimer()
  restoreTitle()
  totalSecs.value = secs
  remaining.value = secs
  status.value = 'idle'
}

function start(): void {
  if (reporting.value || !(props.taskId > 0)) return
  if (status.value === 'done' || remaining.value <= 0) {
    remaining.value = totalSecs.value
  }
  status.value = 'running'
  paintTitle()
  clearTimer()
  timer = setInterval(() => {
    remaining.value = Math.max(0, remaining.value - 1)
    paintTitle()
    if (remaining.value <= 0) {
      void complete()
    }
  }, 1000)
}

function pause(): void {
  clearTimer()
  if (status.value === 'running') status.value = 'paused'
  restoreTitle()
}

function reset(): void {
  clearTimer()
  restoreTitle()
  remaining.value = totalSecs.value
  status.value = 'idle'
}

async function complete(): Promise<void> {
  clearTimer()
  restoreTitle()
  status.value = 'done'
  remaining.value = 0
  await report()
}

async function report(): Promise<void> {
  if (!(props.taskId > 0)) return
  reporting.value = true
  try {
    let left = Math.max(1, Math.floor(totalSecs.value))
    while (left > 0) {
      const chunk = Math.min(600, left)
      await reportPomodoro(props.taskId, { duration_seconds: chunk, focus_score: 0.8 })
      left -= chunk
    }
    message.success(`已记录专注 ${totalSecs.value} 秒`)
    emit('reported')
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
  } finally {
    reporting.value = false
  }
}

watch(
  () => props.taskId,
  () => {
    clearTimer()
    restoreTitle()
    remaining.value = totalSecs.value
    status.value = 'idle'
  },
)

onBeforeUnmount(() => {
  clearTimer()
  restoreTitle()
})
</script>
