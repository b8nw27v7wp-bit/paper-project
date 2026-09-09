<template>
  <div class="space-y-10">
    <div class="flex items-end justify-between">
      <div>
        <h2 class="text-[20px] font-semibold tracking-[-0.02em] text-ink">设置</h2>
        <p class="mt-1 text-[11px] tracking-wide text-muted">主题 · 工作偏好 · 顶栏 · 审批 · 仅存本地</p>
      </div>
    </div>

    <n-card class="apple-card" :bordered="false" content-style="padding: 24px;" aria-label="外观主题">
      <template #header><span class="text-[13px] font-semibold tracking-[-0.01em] text-ink">外观主题</span></template>
      <div class="flex items-center gap-2" role="radiogroup" aria-label="主题选择">
        <button
          :class="['px-3.5 py-1.5 text-[12px] rounded-full border transition-colors', theme === 'light' ? 'bg-ink text-white border-transparent' : 'border-hairline text-muted hover:text-ink']"
          role="radio"
          :aria-checked="theme === 'light'"
          @click="setLight"
        >浅色</button>
        <button
          :class="['px-3.5 py-1.5 text-[12px] rounded-full border transition-colors', theme === 'dark' ? 'bg-ink text-white border-transparent' : 'border-hairline text-muted hover:text-ink']"
          role="radio"
          :aria-checked="theme === 'dark'"
          @click="setDark"
        >深色</button>
      </div>
      <div class="mt-2 text-[11px] tracking-wide text-muted">跟随系统偏好请选浅色，当前：{{ theme === 'dark' ? '深色' : '浅色' }}</div>
    </n-card>

    <n-card class="apple-card" :bordered="false" content-style="padding: 24px;" aria-label="工作偏好">
      <template #header><span class="text-[13px] font-semibold tracking-[-0.01em] text-ink">工作偏好</span></template>
      <n-form label-placement="left" label-width="120">
        <n-form-item label="默认每天小时">
          <n-input-number v-model:value="hours" :min="1" :max="8" :step="1" style="width: 160px" aria-label="默认每天小时" @update:value="saveHours" />
        </n-form-item>
      </n-form>
      <div class="text-[11px] tracking-wide text-muted">用于工作台规划默认时长，范围 1-8 小时</div>
    </n-card>

    <n-card class="apple-card" :bordered="false" content-style="padding: 24px;" aria-label="顶栏显示">
      <template #header><span class="text-[13px] font-semibold tracking-[-0.01em] text-ink">顶栏显示</span></template>
      <div class="flex items-center gap-3">
        <n-switch v-model:value="collapsed" aria-label="顶栏默认折叠" @update:value="saveCollapsed" />
        <span class="text-[13px] tracking-[-0.01em] text-ink">顶栏默认折叠</span>
      </div>
      <div class="mt-2 text-[11px] tracking-wide text-muted">开启后下次进入默认收起顶栏导航</div>
    </n-card>

    <n-card class="apple-card" :bordered="false" content-style="padding: 24px;" aria-label="审批偏好">
      <template #header><span class="text-[13px] font-semibold tracking-[-0.01em] text-ink">审批偏好</span></template>
      <div class="flex items-center gap-3">
        <n-switch v-model:value="requireApproval" aria-label="写库审批默认开启" @update:value="saveApproval" />
        <span class="text-[13px] tracking-[-0.01em] text-ink">写库审批默认开启</span>
      </div>
      <div class="mt-2 text-[11px] tracking-wide text-muted">开启后工作台多智能体默认勾选审批开</div>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { NCard, NForm, NFormItem, NInputNumber, NSwitch, useMessage } from 'naive-ui'
import { getTheme, setTheme, type AppTheme } from '@/theme'
import { useTopNav } from '@/plugins/topnav'
import { useAppStore } from '@/stores/app'
import { useSettingsStore } from '@/stores/settings'

defineOptions({ name: 'SettingsView' })

const message = useMessage()
const appStore = useAppStore()
const settings = useSettingsStore()
const { collapsed, setCollapsed } = useTopNav()

const theme = ref<AppTheme>('light')
const hours = ref<number>(2)
const requireApproval = ref<boolean>(false)

function setLight(): void {
  theme.value = 'light'
  try { setTheme('light') } catch {}
  try { appStore.setTheme('light') } catch {}
}

function setDark(): void {
  theme.value = 'dark'
  try { setTheme('dark') } catch {}
  try { appStore.setTheme('dark') } catch {}
}

function saveHours(v: number | null): void {
  // 收敛到 useSettings：钳制 1-8 与持久化由 store 内聚，行为不变
  const n = Math.floor(Number(v))
  if (!Number.isFinite(n) || n < 1 || n > 8) return
  settings.saveHours(n)
  hours.value = n
}

function saveCollapsed(v: boolean): void {
  try { setCollapsed(v) } catch {}
}

function saveApproval(v: boolean): void {
  settings.saveApproval(v)
  requireApproval.value = v
  message.success(v ? '审批默认已开启' : '审批默认已关闭')
}

onMounted(() => {
  try { theme.value = getTheme() } catch {}
  try { settings.refresh() } catch {}
  hours.value = settings.hours
  requireApproval.value = settings.requireApproval
})
</script>
