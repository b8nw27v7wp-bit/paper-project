<template>
  <n-config-provider :theme-overrides="themeOverrides">
    <n-message-provider>
      <n-notification-provider>
        <div class="min-h-screen bg-white font-apple text-ink selection:bg-[#f5f5f7]">
          <div v-if="isNavigating" class="fixed top-0 left-0 h-[2px] bg-ink z-[100] transition-all duration-120" :style="{ width: progress + '%' }" role="progressbar" aria-label="页面加载" />
          <a href="#main-content" class="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 bg-ink text-white px-3 py-1 rounded-full text-[12px] z-50">跳至主内容</a>

          <aside
            v-if="showRail"
            aria-label="侧边图标导航"
            class="fixed left-0 top-0 bottom-0 z-20 flex flex-col items-center bg-white/90 backdrop-blur-xl border-r border-hairline py-3"
            :style="{ width: railWidth + 'px' }"
          >
            <div class="electron-drag w-full flex flex-col items-center" :class="railWidth < 60 ? 'gap-1' : ''">
              <router-link to="/agent" custom v-slot="{ navigate }">
                <button @click="navigate" aria-label="智能体工作台" class="w-9 h-9 rounded-[10px] bg-ink flex items-center justify-center text-white text-[13px] font-semibold tracking-widest shrink-0">L</button>
              </router-link>
            </div>
            <nav class="flex-1 w-full overflow-y-auto scrollbar-none mt-3 space-y-1">
              <div v-for="section in sections" :key="section.key" class="rail-group">
                <div class="px-2 py-1 text-center text-[9px] tracking-widest text-muted-light select-none" aria-hidden="true">{{ section.glyph }}</div>
                <n-menu
                  :value="section.value"
                  :collapsed="true"
                  :collapsed-width="railWidth"
                  :collapsed-icon-size="18"
                  :indent="10"
                  :options="section.options"
                  :root-indent="10"
                  @update:value="onMenuSelect"
                />
              </div>
            </nav>
            <div class="mt-2 flex flex-col items-center gap-2">
              <button class="w-8 h-8 rounded-full flex items-center justify-center text-[11px] font-medium text-muted hover:text-ink hover:bg-surface transition-colors" aria-label="打开命令面板 ⌘K" @click="showCommand = true">⌘K</button>
              <template v-if="hasToken">
                <button class="w-9 h-9 rounded-full bg-surface text-ink text-[13px] font-semibold flex items-center justify-center border border-hairline" :aria-label="`用户 ${userIdLabel}`" @click="handleLogout">{{ userIdLabel }}</button>
              </template>
              <template v-else>
                <router-link to="/login" custom v-slot="{ navigate }">
                  <button @click="navigate" class="w-9 h-9 rounded-full bg-ink text-white text-[12px] font-medium flex items-center justify-center" aria-label="登录">登</button>
                </router-link>
              </template>
            </div>
          </aside>

          <div :style="{ marginLeft: showRail ? railWidth + 'px' : '0' }" class="min-w-0">
            <header role="banner" aria-label="页面顶部" class="sticky top-0 z-10 bg-white/80 backdrop-blur-xl supports-[backdrop-filter]:bg-white/70 border-b border-hairline">
              <div class="px-6 py-3 flex items-center justify-between gap-4">
                <nav v-if="breadcrumb.length" aria-label="面包屑" class="flex items-center gap-1 text-[12px] tracking-wide text-muted min-w-0">
                  <template v-for="(bc, i) in breadcrumb" :key="bc.path">
                    <span v-if="i > 0" aria-hidden="true">/</span>
                    <span v-if="i === breadcrumb.length - 1" aria-current="page" class="text-ink font-medium truncate">{{ bc.title }}</span>
                    <router-link v-else :to="bc.path" class="hover:text-ink">{{ bc.title }}</router-link>
                  </template>
                </nav>
                <span v-else class="text-[12px] text-muted" />
                <div class="flex items-center gap-2 shrink-0">
                  <template v-if="!isLogin">
                    <span class="hidden md:inline text-[11px] tracking-wide text-muted" aria-live="polite" aria-label="健康状态">{{ healthDot }} {{ versionLabel }}</span>
                    <button v-if="hasToken" class="px-3 py-1.5 text-[12px] font-medium rounded-full bg-surface text-muted hover:text-ink transition-colors" aria-label="退出登录" @click="handleLogout">退出</button>
                  </template>
                </div>
              </div>
            </header>
            <main class="px-6 py-6" id="main-content" role="main" aria-label="主内容" :aria-busy="isNavigating ? 'true' : 'false'">
              <router-view v-slot="{ Component, route: r }">
                <transition name="page-fade" mode="out-in" :duration="120">
                  <suspense>
                    <template #default>
                      <keep-alive :include="cachedViews">
                        <component :is="Component" :key="r.fullPath" />
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
import { NConfigProvider, NMessageProvider, NNotificationProvider, NMenu, type MenuOption } from 'naive-ui'
import { useRoute, useRouter } from 'vue-router'
import { computed, h, ref, onMounted, onBeforeUnmount } from 'vue'
import { useAppStore } from '@/stores/app'
import { themeOverrides } from '@/theme'
import CommandPalette from '@/components/CommandPalette.vue'
import ShortcutsPanel from '@/components/ShortcutsPanel.vue'
import AppContextMenu from '@/components/AppContextMenu.vue'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()
const isLogin = computed(() => route.path === '/login')
const showRail = computed(() => !isLogin.value)
const versionLabel = computed(() => appStore.version !== 'unknown' ? `v${appStore.version}` : 'v0.1.0')
const healthDot = computed(() => appStore.isHealthy ? '●' : '○')
const userIdLabel = ref('U')
const hasToken = ref(false)
function refreshAuth(): void {
  try {
    const token = localStorage.getItem('token')
    hasToken.value = Boolean(token)
    const uid = localStorage.getItem('user_id') ?? ''
    userIdLabel.value = uid ? uid.slice(0, 1).toUpperCase() : 'U'
  } catch {}
}
function handleLogout(): void {
  try { localStorage.removeItem('token'); localStorage.removeItem('user_id') } catch {}
  refreshAuth()
  void router.push('/login')
}

function icon(glyph: string): () => ReturnType<typeof h> {
  return () => h('span', { style: 'font-size:15px;line-height:1;' }, glyph)
}
type RailItem = { label: string; to: string; glyph: string }
type RailSection = { key: string; glyph: string; items: RailItem[] }
const railSections: RailSection[] = [
  { key: 'main', glyph: '主', items: [{ label: '智能体工作台', to: '/agent', glyph: '◆' }] },
  { key: 'core', glyph: '业', items: [
    { label: '目标', to: '/goals', glyph: '◎' },
    { label: '日历', to: '/calendar', glyph: '▦' },
    { label: '周视图', to: '/week', glyph: '▤' },
    { label: '甘特', to: '/gantt', glyph: '▥' },
    { label: '批量', to: '/tasks/batch', glyph: '☰' },
  ] },
  { key: 'know', glyph: '知', items: [
    { label: '图谱', to: '/graph', glyph: '✳' },
    { label: '知识库', to: '/rag', glyph: '❏' },
  ] },
  { key: 'system', glyph: '系', items: [
    { label: '大屏', to: '/dashboard', glyph: '◫' },
    { label: '驾驶舱', to: '/large-screen', glyph: '▣' },
    { label: '反思', to: '/reflection', glyph: '↺' },
    { label: '实验', to: '/experiments', glyph: '±' },
    { label: 'MCP', to: '/mcp', glyph: '⚙' },
    { label: '健康', to: '/health', glyph: '●' },
  ] },
]
const railWidth = ref(60)
function syncRail(): void { railWidth.value = window.innerWidth < 1024 ? 48 : 60 }
const sections = computed(() => railSections.map(section => ({
  ...section,
  value: section.items.some(i => i.to === route.path) ? route.path : null,
  options: section.items.map((i): MenuOption => ({ label: i.label, key: i.to, icon: icon(i.glyph) })),
})))
function onMenuSelect(key: string): void { void router.push(key) }

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
  Graph: 'KnowledgeGraphView',
}
const cachedViews = ref<string[]>(['AgentWorkbenchView', 'GoalsView', 'CalendarView', 'WeekView', 'KnowledgeGraphView'])
function touchCache(routeName: string | undefined): void {
  if (!routeName || routeName === 'Login' || routeName === 'NotFound') return
  const name = viewNameByRoute[routeName] ?? (routeName as string)
  const idx = cachedViews.value.indexOf(name)
  if (idx !== -1) cachedViews.value.splice(idx, 1)
  cachedViews.value.unshift(name)
  if (cachedViews.value.length > 8) cachedViews.value.pop()
}
const breadcrumb = computed(() => {
  const matched = route.matched.filter(r => r.meta && (r.meta as Record<string, unknown>).title)
  return matched.map(r => ({ title: (r.meta as Record<string, unknown>).title as string, path: r.path }))
})
const showCommand = ref(false)
const showShortcuts = ref(false)
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
onMounted(() => {
  try { void appStore.health } catch {}
  refreshAuth()
  syncRail()
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('resize', syncRail)
  router.beforeEach(() => { startProgress(); return true })
  router.afterEach((to) => { doneProgress(); refreshAuth(); touchCache(to.name as string | undefined) })
  router.onError(() => doneProgress())
  touchCache(route.name as string | undefined)
  const idle = (window as unknown as { requestIdleCallback?: (cb: () => void) => number }).requestIdleCallback
  const idlePrefetch = () => { ['/agent', '/goals', '/calendar', '/graph', '/rag'].forEach(prefetch) }
  if (idle) idle(idlePrefetch); else setTimeout(idlePrefetch, 1800)
})
onBeforeUnmount(() => { try { window.removeEventListener('keydown', onKeydown); window.removeEventListener('resize', syncRail) } catch {}; if (progressTimer) clearInterval(progressTimer) })
</script>
