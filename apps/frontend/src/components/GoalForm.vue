<template>
  <n-form ref="formRef" :model="model" :rules="rules" label-placement="left" label-width="88" class="space-y-2">
    <n-form-item label="标题" path="title">
      <n-input v-model:value="model.title" placeholder="如: 30天过六级" maxlength="200" show-count class="rounded-xl" />
    </n-form-item>
    <n-form-item label="描述" path="description">
      <n-input
        v-model:value="model.description"
        type="textarea"
        placeholder="可选 0-2000"
        :autosize="{ minRows: 3, maxRows: 5 }"
        maxlength="2000"
        show-count
      />
    </n-form-item>
    <n-form-item label="截止" path="deadline">
      <n-date-picker v-model:value="model.deadline" type="datetime" clearable class="w-full" placeholder="需大于当前+1天" />
    </n-form-item>
    <n-form-item label="科目" path="subject">
      <n-input v-model:value="model.subject" placeholder="如: 英语 / 数据结构" maxlength="64" />
    </n-form-item>
    <n-form-item label="状态" path="status">
      <n-select v-model:value="model.status" :options="statusOptions" />
    </n-form-item>
  </n-form>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { NForm, NFormItem, NInput, NDatePicker, NSelect, type FormInst, type FormRules, type FormItemRule } from 'naive-ui'
import type { GoalStatus } from '@/types'

export interface GoalFormModel {
  title: string
  description: string
  deadline: number | null
  subject: string
  status: GoalStatus
}

const props = defineProps<{ value: Partial<GoalFormModel> }>()
const emit = defineEmits<{ (e: 'update:value', v: GoalFormModel): void }>()

const formRef = ref<FormInst | null>(null)
const defaults: GoalFormModel = { title: '', description: '', deadline: null, subject: '', status: 'active' }
const model = ref<GoalFormModel>(Object.assign({}, defaults, props.value as Partial<GoalFormModel>))

watch(
  () => props.value,
  (v) => {
    if (v) model.value = { ...model.value, ...v } as GoalFormModel
  },
  { deep: true },
)
watch(model, (v) => emit('update:value', v), { deep: true })

const statusOptions: Array<{ label: string; value: GoalStatus }> = [
  { label: '进行中', value: 'active' },
  { label: '已归档', value: 'archived' },
]

const rules: FormRules = {
  // 与后端 LearningGoal 对齐：title 去空后 1-200，deadline 需 > now+1天（api/goals.ts 同规则）
  title: [
    { required: true, message: '标题必填', trigger: 'blur' },
    { validator: (_rule: FormItemRule, value: string) => ((value ?? '').trim() ? true : new Error('标题不能为空')), trigger: ['input', 'blur'] },
    { max: 200, message: '标题最多 200 字符', trigger: ['input', 'blur'] },
  ],
  deadline: [
    { required: true, type: 'number', message: '截止必填且>now+1天', trigger: 'change' },
    {
      validator: (_rule: FormItemRule, value: number | null) => {
        if (value == null) return true
        return value > Date.now() + 86400000 ? true : new Error('截止需大于当前时间+1天')
      },
      trigger: 'change',
    },
  ],
}

function validate(): Promise<void> {
  return (formRef.value?.validate() as unknown as Promise<void>) ?? Promise.resolve()
}
defineExpose({ validate, model })
</script>
