import { computed, onBeforeUnmount, onMounted, ref, type ComputedRef, type Ref } from 'vue'
import { useAppStore } from '@/stores/app'
import { getTheme } from '@/theme'

// ECharts 暗色适配：浅色沿用纯白极简，深色切换文字/轴线/tooltip
// 规范：dark 文字 #f5f5f7、轴线 #38383a、tooltip 深底 #1d1d1f
export const CHART_LIGHT = {
  text: '#1d1d1f',
  muted: '#86868b',
  axis: '#f5f5f7',
  split: '#f5f5f7',
  tooltipBg: '#1d1d1f',
  tooltipText: '#ffffff',
  seriesInk: '#1d1d1f',
  seriesMuted: '#a1a1a6',
  area: 'rgba(29,29,31,0.06)',
} as const

export const CHART_DARK = {
  text: '#f5f5f7',
  muted: '#a1a1a6',
  axis: '#38383a',
  split: '#2c2c2e',
  tooltipBg: '#1d1d1f',
  tooltipText: '#f5f5f7',
  seriesInk: '#f5f5f7',
  seriesMuted: '#86868b',
  area: 'rgba(245,245,247,0.08)',
} as const

export function isDarkTheme(): boolean {
  try {
    if (typeof document !== 'undefined' && document.documentElement) {
      const ds = document.documentElement.dataset.theme
      if (ds === 'dark' || ds === 'light') return ds === 'dark'
    }
  } catch {}
  try {
    return getTheme() === 'dark'
  } catch {
    return false
  }
}

export function chartPalette(dark: boolean): typeof CHART_LIGHT {
  return dark ? (CHART_DARK as unknown as typeof CHART_LIGHT) : CHART_LIGHT
}

// 跟随主题重渲染：同时监听 theme store 与 document.documentElement dataset.theme
// 返回响应式 isDark + palette，供各 ECharts option computed 消费；
// 调用方在 v-chart 上加 :key="isDark ? 'dark' : 'light'" 即可强制重渲染
export function useDarkChart(): { isDark: Ref<boolean>; palette: ComputedRef<typeof CHART_LIGHT> } {
  const isDark = ref<boolean>(isDarkTheme())
  let observer: MutationObserver | null = null

  function sync(): void {
    try {
      const next = isDarkTheme()
      if (isDark.value !== next) isDark.value = next
    } catch {}
  }

  // theme store 订阅：store 变化即同步（store 内已写 dataset.theme/localStorage）
  let stopWatch: (() => void) | null = null
  onMounted(() => {
    try {
      const appStore = useAppStore()
      // 轻量轮询兜底 + MutationObserver 主路径，避免引入 watch 循环依赖
      stopWatch = appStore.$subscribe(() => {
        sync()
      })
    } catch {}
    try {
      if (typeof MutationObserver !== 'undefined' && typeof document !== 'undefined') {
        observer = new MutationObserver(() => sync())
        observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
      }
    } catch {}
    // 挂载即同步一次，避免首屏主题漂移
    sync()
    // storage 跨 Tab 切换兜底
    try {
      window.addEventListener('storage', sync)
    } catch {}
  })
  onBeforeUnmount(() => {
    try {
      stopWatch?.()
    } catch {}
    try {
      observer?.disconnect()
    } catch {}
    observer = null
    try {
      window.removeEventListener('storage', sync)
    } catch {}
  })

  const palette = computed(() => chartPalette(isDark.value))
  return { isDark, palette }
}
