import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { HealthStatus, ServiceHealth } from '@/types'
import { deriveOverall } from '@/api/health'
import { getTheme as readTheme, setTheme as writeTheme, type AppTheme } from '@/theme'

export const useAppStore = defineStore('app', () => {
  const health = ref<HealthStatus | null>(null)
  const setHealth = (v: HealthStatus | null) => {
    health.value = v
  }

  const isHealthy = computed<boolean>(() => health.value?.status === 'ok')
  const version = computed<string>(() => health.value?.version ?? 'unknown')
  const services = computed<Record<string, ServiceHealth>>(() => health.value?.services ?? {})
  const overall = computed<ServiceHealth>(() => {
    if (!health.value) return 'unknown'
    return deriveOverall(health.value.services)
  })

  // 便捷：更新局部 service 状态（用于 MCP 健康合并）
  const patchServices = (patch: Record<string, ServiceHealth>) => {
    if (!health.value) {
      health.value = { status: 'unknown', version: 'unknown', services: { ...patch } }
      return
    }
    health.value = {
      ...health.value,
      services: { ...(health.value.services ?? {}), ...patch },
      status: deriveOverall({ ...(health.value.services ?? {}), ...patch }),
    }
  }

  const reset = () => {
    health.value = null
  }

  const theme = ref<AppTheme>(readTheme())
  const setTheme = (v: AppTheme): void => {
    const next: AppTheme = v === 'dark' ? 'dark' : 'light'
    theme.value = next
    writeTheme(next)
  }
  const toggleTheme = (): void => {
    setTheme(theme.value === 'dark' ? 'light' : 'dark')
  }

  return { health, setHealth, isHealthy, version, services, overall, patchServices, reset, theme, setTheme, toggleTheme }
})
