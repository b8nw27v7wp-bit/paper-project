<template>
  <n-drawer v-model:show="show" :width="440" placement="right" :trap-focus="false">
    <n-drawer-content
      :title="task?.title || '任务详情'"
      closable
      :header-style="{ fontWeight: 600, letterSpacing: '-0.01em', color: 'var(--c-ink)' }"
      :body-style="{ background: 'var(--c-bg)', padding: '24px' }"
    >
      <div v-if="task" class="space-y-6">
        <div class="rounded-[16px] bg-[var(--c-surface)] p-4 space-y-2">
          <div class="flex justify-between text-[13px]"><span class="text-muted">目标</span><span class="text-ink font-medium">#{{ task.goal_id }}</span></div>
          <div class="flex justify-between text-[13px]"><span class="text-muted">时间</span><span class="text-ink">{{ fmtRange(task.planned_start, task.planned_end) }}</span></div>
          <div class="flex justify-between text-[13px]"><span class="text-muted">优先级</span><span class="text-ink">{{ task.priority }}</span></div>
          <div class="flex justify-between text-[13px]"><span class="text-muted">状态</span><n-tag :type="statusType" size="small" style="border-radius: 20px">{{ task.status }}</n-tag></div>
          <div v-if="task.source_agent" class="flex justify-between text-[13px]"><span class="text-muted">来源</span><span class="text-ink">{{ task.source_agent }}</span></div>
        </div>

        <div>
          <div class="text-[11px] tracking-widest font-medium text-muted mb-3">打卡 · 克制</div>
          <n-form :model="form" label-placement="left" label-width="88" class="space-y-1">
            <n-form-item label="时长(分)">
              <n-input-number v-model:value="form.actual_duration" :min="0" :max="600" class="w-full" placeholder="0-600" />
            </n-form-item>
            <n-form-item label="完成率">
              <n-input-number v-model:value="form.completion_rate" :min="0" :max="1" :step="0.1" class="w-full" />
            </n-form-item>
            <n-form-item label="拖延原因">
              <n-input v-model:value="form.delay_reason" type="textarea" placeholder="可选，最多500字" :autosize="{ minRows: 2 }" maxlength="500" />
            </n-form-item>
            <n-space class="pt-2" :size="8">
              <n-button type="primary" :loading="loading" style="border-radius: 20px" @click="submit">提交打卡</n-button>
              <n-button strong secondary style="border-radius: 20px" @click="doStatus('doing')">开始</n-button>
              <n-button strong secondary style="border-radius: 20px" @click="doStatus('done')">完成</n-button>
            </n-space>
          </n-form>
        </div>

        <div>
          <div class="text-[11px] tracking-widest font-medium text-muted mb-3">番茄专注 · 只记时长不改状态</div>
          <PomodoroTimer v-if="task" :task-id="task.id" class="mb-3" @reported="emit('refresh')" />
          <div class="flex items-center gap-2">
            <n-input-number v-model:value="pomodoro.secs" :min="60" :max="600" :step="60" class="flex-1" placeholder="秒 60-600" />
            <n-button strong secondary :loading="pomodoroLoading" style="border-radius: 20px" @click="submitPomodoro">上报专注</n-button>
          </div>
          <div class="mt-1 text-[11px] tracking-wide text-muted">5分钟=300秒 · 10分钟=600秒 · 专注度按 0.8 记</div>
        </div>
      </div>

      <template #footer>
        <n-space justify="space-between" class="w-full" :size="8">
          <n-button strong secondary style="border-radius: 20px" @click="handleDelete">删除</n-button>
          <n-button style="border-radius: 20px" @click="show = false">关闭</n-button>
        </n-space>
      </template>
    </n-drawer-content>
  </n-drawer>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { NDrawer, NDrawerContent, NTag, NForm, NFormItem, NInput, NInputNumber, NButton, NSpace, useMessage } from 'naive-ui'
import { completeTask, updateTask, reportPomodoro } from '@/api/tasks'
import PomodoroTimer from '@/components/PomodoroTimer.vue'
import type { TaskItem, TaskStatus } from '@/types'
import { extractErrorMessage } from '@/api/client'

const props = defineProps<{ modelValue: boolean; task: TaskItem | null }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void; (e: 'refresh'): void; (e: 'delete', id: number): void }>()

const show = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

const form = ref({ actual_duration: 60, completion_rate: 1, delay_reason: '' })
const loading = ref(false)
const pomodoro = ref({ secs: 300 })
const pomodoroLoading = ref(false)
const message = useMessage()

const statusType = computed(() => {
  const s = props.task?.status
  if (s === 'done') return 'success'
  if (s === 'doing') return 'warning'
  if (s === 'delayed') return 'error'
  return 'default'
})

function fmtRange(s: string, e: string): string {
  try {
    return `${new Date(s).toLocaleString()} → ${new Date(e).toLocaleTimeString()}`
  } catch {
    return `${s} → ${e}`
  }
}

function handleDelete(): void {
  if (!props.task) return
  emit('delete', props.task.id)
}

watch(
  () => props.task,
  () => {
    form.value = { actual_duration: 60, completion_rate: 1, delay_reason: '' }
  },
)

async function submit(): Promise<void> {
  if (!props.task) return
  loading.value = true
  try {
    await completeTask(props.task.id, form.value)
    message.success('打卡成功')
    emit('refresh')
    show.value = false
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
  } finally {
    loading.value = false
  }
}

async function submitPomodoro(): Promise<void> {
  if (!props.task) return
  pomodoroLoading.value = true
  try {
    await reportPomodoro(props.task.id, { duration_seconds: pomodoro.value.secs, focus_score: 0.8 })
    message.success(`已记录专注 ${pomodoro.value.secs} 秒`)
    emit('refresh')
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
  } finally {
    pomodoroLoading.value = false
  }
}

async function doStatus(s: TaskStatus): Promise<void> {
  if (!props.task) return
  try {
    await updateTask(props.task.id, { status: s })
    message.success(`已置为 ${s}`)
    emit('refresh')
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
  }
}
</script>
