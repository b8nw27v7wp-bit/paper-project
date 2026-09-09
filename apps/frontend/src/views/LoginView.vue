<template>
  <div class="max-w-[420px] mx-auto space-y-8">
    <div class="space-y-3">
      <h1 class="text-[28px] font-semibold tracking-[-0.03em] text-ink leading-none">登录</h1>
      <p class="text-[13px] leading-5 tracking-[-0.01em] text-muted">使用用户名与密码登录 · Token 存 localStorage · 401 自动回此页</p>
    </div>

    <n-card class="apple-card" :bordered="false" content-style="padding: 24px;">
      <n-form ref="formRef" :model="form" :rules="rules" label-placement="top" size="medium">
        <n-form-item label="用户名" path="username">
          <n-input v-model:value="form.username" placeholder="demo" clearable @keydown.enter="onSubmit" />
        </n-form-item>
        <n-form-item label="密码" path="password">
          <n-input v-model:value="form.password" type="password" placeholder="demo123" show-password-on="click" @keydown.enter="onSubmit" />
        </n-form-item>
      </n-form>

      <n-space vertical :size="12" class="mt-2">
        <n-button type="primary" block style="border-radius: 20px" :loading="loading" @click="onSubmit">登录</n-button>
        <n-button block style="border-radius: 20px" :loading="loadingReg" @click="onRegister">注册并登录</n-button>
        <div class="text-[11px] tracking-wide text-muted text-center">默认账号 demo / demo123 · 注册后自动登录</div>
      </n-space>

      <n-alert v-if="errorMsg" type="error" :show-icon="false" class="mt-4 text-[12px]" style="border-radius: 12px">{{ errorMsg }}</n-alert>
      <n-alert v-if="infoMsg" type="success" :show-icon="false" class="mt-4 text-[12px]" style="border-radius: 12px">{{ infoMsg }}</n-alert>
    </n-card>

    <div class="text-center">
      <n-button text style="font-size: 12px; color: var(--c-muted)" @click="goHome">返回首页</n-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
defineOptions({ name: 'LoginView' })
import { useRouter, useRoute } from 'vue-router'
import { NCard, NSpace, NButton, NInput, NForm, NFormItem, NAlert, useMessage, type FormInst, type FormRules } from 'naive-ui'
import { login, register } from '@/api/auth'
import { extractErrorMessage } from '@/api/client'

const router = useRouter()
const route = useRoute()
const message = useMessage()

const form = ref({ username: 'demo', password: 'demo123' })
const formRef = ref<FormInst | null>(null)
const loading = ref(false)
const loadingReg = ref(false)
const errorMsg = ref('')
const infoMsg = ref('')

const rules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: ['input', 'blur'] },
    { min: 3, max: 64, message: '用户名需 3-64 字符（与后端一致）', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: ['input', 'blur'] },
    { min: 6, max: 64, message: '密码需 6-64 字符（与后端一致）', trigger: 'blur' },
  ],
}

function getRedirect(): string {
  const r = route.query.redirect as string | undefined
  // 仅允许站内绝对路径；拦截 //evil（协议相对 URL）与反斜杠回跳
  if (typeof r === 'string' && r.startsWith('/') && !r.startsWith('//') && !r.includes('\\')) return r
  return '/'
}

async function onSubmit(): Promise<void> {
  errorMsg.value = ''
  infoMsg.value = ''
  try { await formRef.value?.validate() } catch { return }
  loading.value = true
  try {
    await login({ username: form.value.username.trim(), password: form.value.password })
    message.success('登录成功')
    infoMsg.value = '已登录，即将跳转…'
    // 兼容 desktop: 同时写入 electron store
    try {
      const bridge = (window as unknown as { electronBridge?: { storeSet?: (k: string, v: unknown) => Promise<unknown> } }).electronBridge
      const tok = localStorage.getItem('token')
      if (bridge?.storeSet && tok) void bridge.storeSet('auth:token', tok)
    } catch {}
    const target = getRedirect()
    await router.push(target)
  } catch (e: unknown) {
    const msg = extractErrorMessage(e)
    errorMsg.value = msg
    message.error(msg)
  } finally {
    loading.value = false
  }
}

async function onRegister(): Promise<void> {
  errorMsg.value = ''
  infoMsg.value = ''
  try { await formRef.value?.validate() } catch { return }
  loadingReg.value = true
  try {
    await register({ username: form.value.username.trim(), password: form.value.password })
    message.success('注册成功，正在登录…')
    await login({ username: form.value.username.trim(), password: form.value.password })
    message.success('已注册并登录')
    const target = getRedirect()
    await router.push(target)
  } catch (e: unknown) {
    const msg = extractErrorMessage(e)
    errorMsg.value = msg
    message.error(msg)
  } finally {
    loadingReg.value = false
  }
}

function goHome(): void {
  void router.push('/')
}
</script>
