<template>
  <n-drawer v-model:show="show" :width="440" placement="right" :trap-focus="false">
    <n-drawer-content :title="task?.title || '任务详情'" closable :header-style="{ fontWeight: 600, letterSpacing: '-0.01em', color: '#1d1d1f' }" :body-style="{ background: '#ffffff', padding: '24px' }">
      <div v-if="task" class="space-y-6">
        <div class="rounded-2xl bg-[#f5f5f7] p-4 space-y-2">
          <div class="flex justify-between text-[13px]"><span class="text-muted">目标</span><span class="text-ink font-medium">#{{ task.goal_id }}</span></div>
          <div class="flex justify-between text-[13px]"><span class="text-muted">时间</span><span class="text-ink">{{ new Date(task.planned_start).toLocaleString() }} → {{ new Date(task.planned_end).toLocaleTimeString() }}</span></div>
          <div class="flex justify-between text-[13px]"><span class="text-muted">优先级</span><span class="text-ink">{{ task.priority }}</span></div>
          <div class="flex justify-between text-[13px]"><span class="text-muted">状态</span><n-tag :type="statusType" size="small" style="border-radius: 20px">{{ task.status }}</n-tag></div>
        </div>

        <div>
          <div class="text-[11px] tracking-widest text-muted font-medium mb-3">打卡</div>
          <n-form :model="form" label-placement="left" label-width="88" class="space-y-1">
            <n-form-item label="时长(分)">
              <n-input-number v-model:value="form.actual_duration" :min="0" :max="600" class="w-full" placeholder="0-600" />
            </n-form-item>
            <n-form-item label="完成率">
              <n-input-number v-model:value="form.completion_rate" :min="0" :max="1" :step="0.1" class="w-full" />
            </n-form-item>
            <n-form-item label="拖延原因">
              <n-input v-model:value="form.delay_reason" type="textarea" placeholder="可选" :autosize="{ minRows: 2 }" />
            </n-form-item>
            <n-space class="pt-2">
              <n-button type="primary" :loading="loading" @click="submit" style="border-radius: 20px">提交打卡</n-button>
              <n-button strong secondary @click="doStatus('doing')" style="border-radius: 20px">开始</n-button>
              <n-button strong secondary @click="doStatus('done')" style="border-radius: 20px">完成</n-button>
            </n-space>
          </n-form>
        </div>
      </div>

      <template #footer>
        <n-space justify="space-between" class="w-full">
          <n-button strong secondary @click="$emit('delete', task.id)" style="border-radius: 20px">删除</n-button>
          <n-button @click="show = false" style="border-radius: 20px">关闭</n-button>
        </n-space>
      </template>
    </n-drawer-content>
  </n-drawer>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { NDrawer, NDrawerContent, NTag, NForm, NFormItem, NInput, NInputNumber, NButton, NSpace, useMessage } from 'naive-ui'
import { completeTask, updateTask } from '@/api/tasks'

const props = defineProps<{ modelValue: boolean; task: any | null }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void; (e: 'refresh'): void; (e: 'delete', id: number): void }>()

const show = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const form = ref({ actual_duration: 60, completion_rate: 1, delay_reason: '' })
const loading = ref(false)
const message = useMessage()

const statusType = computed(() => {
  const s = props.task?.status
  if (s === 'done') return 'success'
  if (s === 'doing') return 'warning'
  if (s === 'delayed') return 'error'
  return 'default'
})

watch(() => props.task, () => { form.value = { actual_duration: 60, completion_rate: 1, delay_reason: '' } })

async function submit() {
  if (!props.task) return
  loading.value = true
  try {
    await completeTask(props.task.id, form.value)
    message.success('打卡成功')
    emit('refresh')
    show.value = false
  } catch (e: any) {
    message.error(e?.response?.data?.msg || e.message)
  } finally { loading.value = false }
}

async function doStatus(s: string) {
  if (!props.task) return
  try {
    await updateTask(props.task.id, { status: s })
    message.success(`已置为 ${s}`)
    emit('refresh')
  } catch (e: any) {
    message.error(e?.response?.data?.msg || e.message)
  }
}
</script>
