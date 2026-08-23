<template>
  <n-form ref="formRef" :model="model" :rules="rules" label-placement="left" label-width="88" class="space-y-2">
    <n-form-item label="标题" path="title">
      <n-input v-model:value="model.title" placeholder="如: 30天过六级" maxlength="200" show-count class="rounded-xl" />
    </n-form-item>
    <n-form-item label="描述" path="description">
      <n-input v-model:value="model.description" type="textarea" placeholder="可选 0-2000" :autosize="{ minRows: 3, maxRows: 5 }" maxlength="2000" show-count />
    </n-form-item>
    <n-form-item label="截止" path="deadline">
      <n-date-picker v-model:value="model.deadline" type="datetime" clearable class="w-full" placeholder="需大于当前+1天" />
    </n-form-item>
    <n-form-item label="科目" path="subject">
      <n-input v-model:value="model.subject" placeholder="如: 英语 / 数据结构" />
    </n-form-item>
    <n-form-item label="状态" path="status">
      <n-select v-model:value="model.status" :options="[{ label: '进行中', value: 'active' }, { label: '已归档', value: 'archived' }]" />
    </n-form-item>
  </n-form>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { NForm, NFormItem, NInput, NDatePicker, NSelect } from 'naive-ui'

const props = defineProps<{ value: any }>()
const emit = defineEmits<{ (e: 'update:value', v: any): void }>()

const formRef = ref<any>(null)
const model = ref<any>({
  title: '',
  description: '',
  deadline: null,
  subject: '',
  status: 'active',
  ...props.value,
})

watch(() => props.value, (v) => { if (v) model.value = { ...model.value, ...v } }, { deep: true })
watch(model, (v) => emit('update:value', v), { deep: true })

const rules = {
  title: [{ required: true, message: '标题必填', trigger: 'blur' }],
  deadline: [{ required: true, message: '截止必填且>now+1天', trigger: 'change' }],
}

function validate() {
  return formRef.value?.validate()
}
defineExpose({ validate, model })
</script>
