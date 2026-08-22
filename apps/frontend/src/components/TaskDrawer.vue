<template>
  <n-drawer v-model:show="show" :width="420" placement="right">
    <n-drawer-content :title="task?.title || '任务详情'" closable>
      <n-descriptions v-if="task" :column="1" bordered size="small">
        <n-descriptions-item label="ID">{{ task.id }}</n-descriptions-item>
        <n-descriptions-item label="目标">{{ task.goal_id }}</n-descriptions-item>
        <n-descriptions-item label="时间">{{ task.planned_start }} → {{ task.planned_end }}</n-descriptions-item>
        <n-descriptions-item label="优先级">{{ task.priority }}</n-descriptions-item>
        <n-descriptions-item label="状态"><n-tag :type="statusType">{{ task.status }}</n-tag></n-descriptions-item>
      </n-descriptions>

      <n-divider>打卡</n-divider>
      <n-form :model="form" label-placement="left" label-width="90">
        <n-form-item label="时长(分)">
          <n-input-number v-model:value="form.actual_duration" :min="0" :max="600" class="w-full" placeholder="0-600" />
        </n-form-item>
        <n-form-item label="完成率">
          <n-input-number v-model:value="form.completion_rate" :min="0" :max="1" :step="0.1" class="w-full" />
        </n-form-item>
        <n-form-item label="拖延原因">
          <n-input v-model:value="form.delay_reason" type="textarea" placeholder="可选 0-500" />
        </n-form-item>
        <n-space>
          <n-button type="primary" :loading="loading" @click="submit">提交打卡</n-button>
          <n-button @click="doStatus('doing')">开始</n-button>
          <n-button @click="doStatus('done')">完成</n-button>
        </n-space>
      </n-form>

      <template #footer>
        <n-space>
          <n-button type="error" @click="$emit('delete', task.id)">删除</n-button>
          <n-button @click="show = false">关闭</n-button>
        </n-space>
      </template>
    </n-drawer-content>
  </n-drawer>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { NDrawer, NDrawerContent, NDescriptions, NDescriptionsItem, NTag, NDivider, NForm, NFormItem, NInput, NInputNumber, NButton, NSpace, useMessage } from 'naive-ui'
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
