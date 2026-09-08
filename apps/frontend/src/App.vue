<template>
  <n-config-provider :theme="naiveTheme" :theme-overrides="mergedOverrides">
    <n-message-provider>
      <n-notification-provider>
        <div class="min-h-screen bg-white font-apple text-ink selection:bg-[#f5f5f7]">
          <div v-if="isNavigating" class="fixed top-0 left-0 h-[2px] bg-ink z-[100] transition-all duration-120" :style="{ width: progress + '%' }" role="progressbar" aria-label="页面加载" />
          <a href="#main-content" class="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 bg-ink text-white px-3 py-1 rounded-full text-[12px] z-50">跳至主内容</a>

          <TopNav v-if="showNav" @open-command="showCommand = true">
            <template #status>
              <template v-if="!isLogin">
                <span class="hidden md:inline text-[11px] tracking-wide text-muted" aria-live="polite" aria-label="健康状态">{{ healthDot }} {{ versionLabel }}</span>
                <button class="px-2.5 py-1 text-[12px] font-medium rounded-full bg-surface text-muted hover:text-ink transition-colors" :aria-label="theme === 'dark' ? '切换到浅色主题' : '切换到暗色主题'" @click="onToggleTheme">{{ theme === 'dark' ? '浅色' : '深色' }}</button>
                <button v-if="hasToken" class="px-2.5 py-1 text-[12px] font-medium rounded-full bg-surface text-muted hover:text-ink transition-colors" aria-label="退出登录" @click="handleLogout">退出</button>
              </template>
            </template>
          </TopNav>

          <div class="min-w-0">
            <main class="px-6 py-6" id="main-content" role="main" aria-label="主内容" :aria-busy="isNavigating ? 'true' : 'false'">
              <router-view v-slot="{ Component, route: r }">
                <transition name="page-fade" mode="out-in" :duration="120">
                  <suspense>
                    <template #default>
                      <keep-alive :include="cachedViews">
                        <component :is="Component" :key="r.path" />
                      </keep-alive>
                    </template>
                    <template #fallback>
                      <div class="py-20 text-center text-[13px] text-muted" role="status" aria-live="polite">加载中…</div>
                    </template>
                  </suspense>
                </transition>
              </router-view>
            </main>
          </div>

          <CommandPalette v-model:show="showCommand" />
          <ShortcutsPanel v-model:show="showShortcuts" />
          <AppContextMenu />
        </div>
      </n-notification-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { NConfigProvider, NMessageProvider, NNotificationProvider, darkTheme } from 'naive-ui'
import { useRoute, useRouter } from 'vue-router'
import { computed, ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { useAppStore } from '@/stores/app'
import { useWorkbenchStore } from '@/stores/workbench'
import { themeOverrides, tokens, getTheme, setTheme, type AppTheme } from '@/theme'
import TopNav from '@/plugins/topnav/TopNav.vue'
import CommandPalette from '@/components/CommandPalette.vue'
import ShortcutsPanel from '@/components/ShortcutsPanel.vue'
import AppContextMenu from '@/components/AppContextMenu.vue'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()
const workbench = useWorkbenchStore()

// 运行状态进标题栏：running 加（规划中）前缀，completed/failed/idle 重算当前路由 title 恢复
function getBaseTitle(): string {
  try {
    const meta = route.meta as Record<string, unknown> | undefined
    const t = meta?.title as string | undefined
    if (t) return `${t} - 智能学习规划系统`
  } catch {}
  try {
    return document.title.replace(/^（规划中）/, '') || '智能学习规划系统'
  } catch {
    return '智能学习规划系统'
  }
}
function syncDocumentTitle(s: string): void {
  try {
    if (s === 'running') {
      const base = getBaseTitle().replace(/^（规划中）/, '')
      const next = `（规划中）${base}`
      if (document.title !== next) document.title = next
    } else {
      const clean = getBaseTitle().replace(/^（规划中）/, '')
      if (document.title !== clean) document.title = clean
    }
  } catch {}
}
// 草稿守护降级：composer 为 view 局部 ref（AgentWorkbenchView 禁区，不可跨组件读取），
// 此处仅守护 localStorage workbench:draft 非空场景；view 未写该 key 时静默无打扰
function onBeforeUnload(e: BeforeUnloadEvent): void {
  try {
    const raw = localStorage.getItem('workbench:draft')
    if (raw && raw.trim()) {
      e.preventDefault()
      e.returnValue = ''
    }
  } catch {}
}
const isLogin = computed(() => route.path === '/login')
const showNav = computed(() => !isLogin.value)
const versionLabel = computed(() => appStore.version !== 'unknown' ? `v${appStore.version}` : 'v0.1.0')
const healthDot = computed(() => appStore.isHealthy ? '在线' : '离线')
const hasToken = ref(false)
function refreshAuth(): void {
  try {
    const token = localStorage.getItem('token')
    hasToken.value = Boolean(token)
  } catch {}
}
function handleLogout(): void {
  try { localStorage.removeItem('token'); localStorage.removeItem('user_id') } catch {}
  refreshAuth()
  void router.push('/login')
}

const isNavigating = ref(false)
const progress = ref(30)
let progressTimer: ReturnType<typeof setInterval> | null = null
function startProgress(): void {
  isNavigating.value = true
  progress.value = 30
  if (progressTimer) clearInterval(progressTimer)
  progressTimer = setInterval(() => { progress.value = Math.min(92, progress.value + Math.random() * 12) }, 120)
}
function doneProgress(): void {
  if (progressTimer) { clearInterval(progressTimer); progressTimer = null }
  progress.value = 100
  setTimeout(() => { isNavigating.value = false; progress.value = 30 }, 220)
}
const prefetchCache = new Set<string>()
function prefetch(to: string): void {
  if (prefetchCache.has(to)) return
  prefetchCache.add(to)
  const map: Record<string, () => Promise<unknown>> = {
    '/agent': () => import('@/views/AgentWorkbenchView.vue'),
    '/goals': () => import('@/views/GoalsView.vue'),
    '/calendar': () => import('@/views/CalendarView.vue'),
    '/week': () => import('@/views/WeekView.vue'),
    '/gantt': () => import('@/views/GanttView.vue'),
    '/tasks/batch': () => import('@/views/TaskBatchView.vue'),
    '/graph': () => import('@/views/KnowledgeGraphView.vue'),
    '/rag': () => import('@/views/RAGView.vue'),
    '/reflection': () => import('@/views/ReflectionView.vue'),
    '/dashboard': () => import('@/views/DashboardView.vue'),
    '/large-screen': () => import('@/views/LargeScreenView.vue'),
    '/experiments': () => import('@/views/ExperimentsView.vue'),
    '/health': () => import('@/views/HealthCheck.vue'),
    '/mcp': () => import('@/views/MCPView.vue'),
  }
  const loader = map[to]
  if (loader) void loader().catch(() => {})
}
const viewNameByRoute: Record<string, string> = {
  AgentWorkbench: 'AgentWorkbenchView',
  Goals: 'GoalsView',
  Calendar: 'CalendarView',
  Week: 'WeekView',
  Gantt: 'GanttView',
  TaskBatch: 'TaskBatchView',
  Graph: 'KnowledgeGraphView',
  Dashboard: 'DashboardView',
  MCP: 'MCPView',
  Experiments: 'ExperimentsView',
  LargeScreen: 'LargeScreenView',
  RAG: 'RAGView',
  Reflection: 'ReflectionView',
  Health: 'HealthCheck',
  Settings: 'SettingsView',
  Notifications: 'NotificationsView',
}
const cachedViews = ref<string[]>(['AgentWorkbenchView', 'GoalsView', 'CalendarView', 'WeekView', 'KnowledgeGraphView'])
// 图表重型视图不缓存：ECharts/动画在 keep-alive 下切后台仍跑 rAF，越逛越卡；
// 切走即 unmount，vue-echarts 自动 dispose，杜绝累积。query 切页已改 key=r.path，不再整页重挂。
const NO_CACHE_VIEWS = new Set(['DashboardView', 'LargeScreenView', 'ExperimentsView', 'KnowledgeGraphView'])
function touchCache(routeName: string | undefined): void {
  if (!routeName || routeName === 'Login' || routeName === 'NotFound') return
  const name = viewNameByRoute[routeName] ?? (routeName as string)
  if (NO_CACHE_VIEWS.has(name)) {
    const i = cachedViews.value.indexOf(name)
    if (i !== -1) cachedViews.value.splice(i, 1)
    return
  }
  const idx = cachedViews.value.indexOf(name)
  if (idx !== -1) cachedViews.value.splice(idx, 1)
  cachedViews.value.unshift(name)
  if (cachedViews.value.length > 8) cachedViews.value.pop()
}
const showCommand = ref(false)
const showShortcuts = ref(false)
const theme = ref<AppTheme>('light')
// 暗色时 naive darkTheme 接管控件底色/文字；浅色自定义 themeOverrides 全量保留，
// 暗色下仅保留圆角/字体覆盖，避免浅色 ink/白底覆盖 dark 语义
const naiveTheme = computed(() => (theme.value === 'dark' ? darkTheme : null))
const mergedOverrides = computed(() =>
  theme.value === 'dark'
    ? {
        common: { borderRadius: tokens.radius, fontFamily: tokens.fontFamily },
        Card: { borderRadius: tokens.radiusCard },
        Button: { borderRadiusMedium: tokens.radiusButton },
      }
    : themeOverrides,
)
function onToggleTheme(): void {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
  setTheme(theme.value)
  try {
    appStore.setTheme(theme.value)
  } catch {}
}
function onKeydown(e: KeyboardEvent): void {
  const isK = e.key.toLowerCase() === 'k'
  const mod = e.metaKey || e.ctrlKey
  if (mod && isK) { e.preventDefault(); showCommand.value = !showCommand.value; return }
  if (e.key === '?' && !mod) {
    const tag = (e.target as HTMLElement)?.tagName
    if (tag === 'INPUT' || tag === 'TEXTAREA') return
    e.preventDefault(); showShortcuts.value = !showShortcuts.value
  }
}
type ElectronBridge = {
  onAgentCommand?: (cb: (cmd: string) => void) => () => void
  onNotificationClick?: (cb: (p: { title?: string; tag?: string; trace_id?: string }) => void) => () => void
}
let offBridge: Array<() => void> = []
function bindDesktopBridge(): void {
  try {
    const bridge = (window as unknown as { electronBridge?: ElectronBridge }).electronBridge
    if (!bridge) return
    // 快捷键/托盘命令：转交 window 事件，由 AgentWorkbenchView 消费
    if (bridge.onAgentCommand) {
      const off = bridge.onAgentCommand((cmd: string) => {
        try { window.dispatchEvent(new CustomEvent<string>('agent:command', { detail: cmd })) } catch {}
      })
      if (typeof off === 'function') offBridge.push(off)
    }
    // 通知深链：带 trace_id 则进工作台回放，否则进工作台
    if (bridge.onNotificationClick) {
      const off = bridge.onNotificationClick((p) => {
        try {
          const tid = p?.trace_id
          if (tid) void router.push(`/agent?trace=${encodeURIComponent(tid)}`)
          else void router.push('/agent')
        } catch {}
      })
      if (typeof off === 'function') offBridge.push(off)
    }
  } catch {}
}
onMounted(() => {
  theme.value = getTheme()
  setTheme(theme.value)
  try {
    appStore.setTheme(theme.value)
  } catch {}
  // 工作台经 appStore 切主题时同步顶栏本地态，保证 NConfigProvider 实时跟随
  try {
    appStore.$subscribe((_m, s) => {
      const next = (s as unknown as { theme?: AppTheme }).theme
      if ((next === 'dark' || next === 'light') && next !== theme.value) theme.value = next
    })
  } catch {}
  try { void appStore.health } catch {}
  refreshAuth()
  bindDesktopBridge()
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('beforeunload', onBeforeUnload)
  try {
    watch(
      () => workbench.status,
      (s) => {
        syncDocumentTitle(s)
      },
    )
  } catch {}
  try {
    watch(
      () => route.fullPath,
      () => {
        try { syncDocumentTitle(workbench.status) } catch {}
      },
    )
  } catch {}
  let navStart = 0
  router.beforeEach(() => { navStart = performance.now(); startProgress(); return true })
  router.afterEach((to) => {
    doneProgress(); refreshAuth(); touchCache(to.name as string | undefined); try { syncDocumentTitle(workbench.status) } catch {}
    // 导航耗时自测：general 报告“点多了变慢”后加的度量，看 console 或 window.__lastNavMs
    try {
      const ms = Math.round(performance.now() - navStart)
      ;(window as unknown as { __lastNavMs?: number }).__lastNavMs = ms
      if (ms > 800) console.warn(`[nav] ${String(to.path)} ${ms}ms（偏慢）`)
      else console.debug(`[nav] ${String(to.path)} ${ms}ms`)
    } catch {}
  })
  router.onError(() => doneProgress())
  touchCache(route.name as string | undefined)
  const idle = (window as unknown as { requestIdleCallback?: (cb: () => void) => number }).requestIdleCallback
  const idlePrefetch = () => { ['/agent', '/goals', '/calendar', '/graph', '/rag'].forEach(prefetch) }
  if (idle) idle(idlePrefetch); else setTimeout(idlePrefetch, 1800)
})
onBeforeUnmount(() => { try { window.removeEventListener('keydown', onKeydown) } catch {}; try { window.removeEventListener('beforeunload', onBeforeUnload) } catch {}; try { offBridge.forEach((off) => off()); offBridge = [] } catch {}; if (progressTimer) clearInterval(progressTimer) })
</script>
