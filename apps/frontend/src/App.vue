<template>
  <n-config-provider :theme-overrides="theme">
    <n-message-provider>
      <n-notification-provider>
        <div class="min-h-screen bg-white font-apple text-ink selection:bg-[#f5f5f7]">
          <!-- 顶部导航进度 120ms 内完成，prefers-reduced-motion 时禁用 -->
          <div v-if="isNavigating" class="fixed top-0 left-0 h-[2px] bg-[#1d1d1f] z-[100] transition-all duration-120" :style="{ width: progress + '%' }" role="progressbar" aria-label="页面加载" />
          <a href="#main-content" class="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 bg-[#1d1d1f] text-white px-3 py-1 rounded-full text-[12px] z-50">跳至主内容</a>
          <header role="banner" aria-label="站点头部" class="sticky top-0 z-10 bg-white/80 backdrop-blur-xl border-b border-transparent supports-[backdrop-filter]:bg-white/70">
            <div class="max-w-[1440px] mx-auto px-10 py-4 flex items-center gap-6">
              <!-- Brand 200px -->
              <div class="flex items-center gap-3 shrink-0 w-[200px]" aria-label="品牌">
                <div aria-hidden="true" class="w-7 h-7 rounded-lg bg-[#1d1d1f] flex items-center justify-center text-white text-[11px] font-semibold tracking-widest">L</div>
                <span class="text-[15px] font-semibold tracking-[-0.02em] text-ink">学习规划</span>
                <span class="hidden xl:inline text-[11px] tracking-wide text-muted font-medium">LearningPlanner</span>
                <span class="hidden lg:inline ml-1 text-[10px] tracking-widest px-2 py-0.5 rounded-full bg-[#f5f5f7] text-muted" aria-label="版本">P3</span>
              </div>
              <!-- 分组导航：核心 / 知识 / 分析 / 系统 -->
              <nav role="navigation" aria-label="主导航" class="flex-1 flex items-center gap-2 min-w-0 overflow-x-auto scrollbar-none">
                <template v-if="!isLogin">
                  <template v-for="group in navGroups" :key="group.key">
                    <div class="flex items-center gap-1 shrink-0">
                      <span class="hidden lg:inline text-[10px] tracking-widest text-[#a1a1a6] font-medium mr-1">{{ group.label }}</span>
                      <router-link v-for="item in group.items" :key="item.to" :to="item.to" custom v-slot="{ navigate, isActive }">
                        <button
                          @click="navigate"
                          @mouseenter="prefetch(item.to)"
                          :data-prefetch="item.to"
                          :aria-label="`导航到${item.label}`"
                          :aria-current="isActive ? 'page' : undefined"
                          :class="[
                            'px-3 py-1.5 text-[13px] font-medium rounded-full transition-colors whitespace-nowrap',
                            isActive ? 'bg-[#1d1d1f] text-white' : 'text-muted hover:text-ink hover:bg-[#f5f5f7]'
                          ]"
                        >
                          {{ item.label }}
                        </button>
                      </router-link>
                    </div>
                    <div v-if="group.key !== 'system'" class="w-px h-4 bg-[#f5f5f7] mx-1 shrink-0 hidden sm:block" />
                  </template>
                  <!-- 溢出“更多”： >1024 显示前8，余下进下拉 -->
                  <n-dropdown v-if="overflowNav.length" :options="overflowOptions" trigger="hover" @select="onOverflowSelect">
                    <button aria-label="更多导航" aria-haspopup="menu" class="ml-1 px-3 py-1.5 text-[13px] font-medium rounded-full text-muted hover:text-ink hover:bg-[#f5f5f7] whitespace-nowrap">更多 ▾</button>
                  </n-dropdown>
                </template>
                <template v-else>
                  <router-link to="/health" custom v-slot="{ navigate }"><button @click="navigate" class="px-3 py-1.5 text-[13px] font-medium rounded-full text-muted hover:text-ink">健康</button></router-link>
                </template>
              </nav>
              <!-- 右侧状态 -->
              <div class="flex items-center gap-2 shrink-0">
                <template v-if="!isLogin">
                  <span class="hidden md:inline text-[11px] tracking-wide text-muted" aria-live="polite" aria-label="健康状态">{{ healthDot }} {{ versionLabel }}</span>
                  <button class="px-2.5 py-1.5 text-[12px] font-medium rounded-full bg-white border border-[#e8e8ed] text-muted hover:text-ink transition-colors" aria-label="打开命令面板 ⌘K" @click="showCommand = true">⌘K</button>
                  <button class="px-3.5 py-1.5 text-[12px] font-medium rounded-full bg-[#f5f5f7] text-muted hover:text-ink transition-colors" aria-label="退出登录" @click="handleLogout">退出</button>
                </template>
              </div>
            </div>
            <div class="h-px bg-[#f5f5f7] mx-10" />
          </header>
          <div class="max-w-[1440px] mx-auto px-10 py-8 flex gap-8 items-start">
              <!-- 侧边栏 220px：仅 ≥1024 且非首页/登录显示 -->
            <aside v-if="showSidebar" aria-label="侧边导航" class="hidden lg:block w-[220px] shrink-0 sticky top-[72px] self-start">
              <div class="rounded-[16px] bg-[#f5f5f7] p-3">
                <div class="flex items-center justify-between px-2 py-2">
                  <span class="text-[11px] tracking-widest font-medium text-muted">导航</span>
                  <button class="text-[10px] tracking-wide text-muted hover:text-ink" aria-label="清空搜索" @click="sessionQuery=''">清空</button>
                </div>
                <div class="px-2 pb-2">
                  <n-input v-model:value="sessionQuery" placeholder="搜索会话…" clearable size="small" aria-label="会话搜索" style="--n-border-radius: 12px" />
                </div>
                <nav class="space-y-1 max-h-[32vh] overflow-auto pr-1" aria-label="侧边导航列表">
                  <div v-for="item in filteredSideNav" :key="item.to" class="flex items-center gap-1">
                    <router-link :to="item.to" custom v-slot="{ navigate, isActive }" class="flex-1">
                      <button @click="navigate" :aria-label="`侧边导航到${item.label}`" :aria-current="isActive ? 'page' : undefined" :class="['w-full text-left px-3 py-2 rounded-[12px] text-[13px] font-medium transition-colors', isActive ? 'bg-white text-ink shadow-sm' : 'text-muted hover:text-ink hover:bg-white/60']">{{ item.label }}</button>
                    </router-link>
                    <button :aria-label="isFav(item.to) ? `取消收藏${item.label}` : `收藏${item.label}`" :class="['w-7 h-7 rounded-full flex items-center justify-center text-[12px] shrink-0', isFav(item.to) ? 'bg-[#1d1d1f] text-white' : 'bg-white text-muted hover:text-ink']" @click="toggleFav(item.to)">{{ isFav(item.to) ? '★' : '☆' }}</button>
                  </div>
                  <div v-if="!filteredSideNav.length" class="px-3 py-4 text-center text-[12px] text-muted">无匹配</div>
                </nav>
                <div v-if="favNav.length" class="mt-3 pt-3 border-t border-white">
                  <div class="text-[11px] tracking-widest font-medium text-muted px-2">收藏</div>
                  <nav class="mt-1 space-y-1">
                    <router-link v-for="item in favNav" :key="`fav-${item.to}`" :to="item.to" custom v-slot="{ navigate, isActive }">
                      <button @click="navigate" :aria-current="isActive ? 'page' : undefined" :class="['w-full text-left px-3 py-1.5 rounded-[12px] text-[12px] font-medium', isActive ? 'bg-white text-ink' : 'text-muted hover:text-ink hover:bg-white/60']">★ {{ item.label }}</button>
                    </router-link>
                  </nav>
                </div>
                <div class="mt-3 pt-3 border-t border-white">
                  <div class="text-[11px] tracking-wide text-muted px-2">快捷</div>
                  <div class="mt-2 flex gap-2">
                    <button class="flex-1 py-1.5 text-[12px] rounded-full bg-[#1d1d1f] text-white" aria-label="快捷新建目标" @click="router.push('/goals')">新建</button>
                    <button class="flex-1 py-1.5 text-[12px] rounded-full bg-white text-ink border border-[#e8e8ed]" aria-label="快捷查看日历" @click="router.push('/calendar')">日历</button>
                  </div>
                  <div class="mt-2 text-[11px] tracking-wide text-muted px-2 flex items-center justify-between">
                    <span>会话</span><span class="text-ink">{{ sideNav.length }} 项 · {{ favNav.length }} 收藏</span>
                  </div>
                </div>
              </div>
              <div class="mt-3 rounded-[16px] bg-white border border-[#f5f5f7] p-3">
                <div class="text-[11px] tracking-widest font-medium text-muted">状态</div>
                <div class="mt-2 text-[12px] leading-5 text-muted"><span :class="healthDot==='●' ? 'text-[#10b981]' : 'text-[#86868b]'">{{ healthDot }}</span> {{ versionLabel }} · {{ isDesktop ? '桌面' : '网页' }}</div>
                <div class="mt-2 flex gap-1 flex-wrap">
                  <span class="text-[10px] tracking-wide px-2 py-1 rounded-full bg-[#f5f5f7] text-muted">⌘K</span>
                  <span class="text-[10px] tracking-wide px-2 py-1 rounded-full bg-[#f5f5f7] text-muted">?</span>
                </div>
              </div>
            </aside>
            <main class="flex-1 min-w-0" id="main-content" role="main" aria-label="主内容" :aria-busy="isNavigating ? 'true' : 'false'">
              <nav v-if="breadcrumb.length > 1" aria-label="面包屑" class="mb-4 flex items-center gap-1 text-[11px] tracking-wide text-muted">
                <router-link to="/" class="hover:text-ink">首页</router-link>
                <template v-for="(bc, i) in breadcrumb" :key="bc.path">
                  <span aria-hidden="true">/</span>
                  <span v-if="i === breadcrumb.length - 1" aria-current="page" class="text-ink">{{ bc.title }}</span>
                  <router-link v-else :to="bc.path" class="hover:text-ink">{{ bc.title }}</router-link>
                </template>
              </nav>
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
          <footer role="contentinfo" aria-label="页脚" class="max-w-[1440px] mx-auto px-10 py-8 flex items-center justify-between gap-4 flex-wrap border-t border-[#f5f5f7] mt-4">
            <p class="text-[11px] tracking-wide text-muted">© 2026 LearningPlanner · Apple 字体 · 浅色极简 · 克制 · <span class="text-ink">{{ versionLabel }}</span></p>
            <div class="flex items-center gap-2 text-[11px] tracking-wide text-muted"><span :class="healthDot==='●' ? 'text-[#10b981]' : 'text-amber-500'" aria-label="健康状态">{{ healthDot }}</span><span>健康</span><span class="w-px h-3 bg-[#f5f5f7] mx-1" /><button class="hover:text-ink transition-colors" aria-label="打开命令面板" @click="showCommand = true">⌘K 快捷</button><span class="w-px h-3 bg-[#f5f5f7] mx-1" /><button class="hover:text-ink transition-colors" aria-label="快捷键表" @click="showShortcuts = true">?</button></div>
          </footer>
          <CommandPalette v-model:show="showCommand" />
          <ShortcutsPanel v-model:show="showShortcuts" />
          <AppContextMenu />
        </div>
      </n-notification-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { NConfigProvider, NMessageProvider, NNotificationProvider, NDropdown, NInput } from 'naive-ui'
import { useRoute, useRouter } from 'vue-router'
import { computed, ref, onMounted, onBeforeUnmount } from 'vue'
import { useAppStore } from '@/stores/app'
import CommandPalette from '@/components/CommandPalette.vue'
import ShortcutsPanel from '@/components/ShortcutsPanel.vue'
import AppContextMenu from '@/components/AppContextMenu.vue'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()
const isLogin = computed(() => route.path === '/login')
const isDesktop = computed(() => typeof window !== 'undefined' && !!(window as unknown as { electronBridge?: unknown }).electronBridge)
const showSidebar = computed(() => !isLogin.value && route.path !== '/' && route.path !== '/health' && route.path !== '/login')
const versionLabel = computed(() => appStore.version !== 'unknown' ? `v${appStore.version}` : 'v0.1.0')
const healthDot = computed(() => appStore.isHealthy ? '●' : '○')
function handleLogout(): void {
  try { localStorage.removeItem('token'); localStorage.removeItem('user_id') } catch {}
  void router.push('/login')
}

// 核心/知识/分析/系统 四组（总 14 项），头部按组渲染+溢出
type NavItem = { to: string; label: string }
type NavGroup = { key: string; label: string; items: NavItem[] }
const navGroups: NavGroup[] = [
  { key: 'core', label: '核心', items: [{ to: '/', label: '首页' }, { to: '/workbench', label: '工作台' }, { to: '/goals', label: '目标' }, { to: '/calendar', label: '日历' }, { to: '/week', label: '周视图' }, { to: '/gantt', label: '甘特' }, { to: '/tasks/batch', label: '批量' }] },
  { key: 'know', label: '知识', items: [{ to: '/graph', label: '图谱' }, { to: '/rag', label: '知识库' }] },
  { key: 'analyse', label: '分析', items: [{ to: '/reflection', label: '反思' }, { to: '/dashboard', label: '大屏' }, { to: '/large-screen', label: '驾驶舱' }, { to: '/experiments', label: '实验' }] },
  { key: 'system', label: '系统', items: [{ to: '/health', label: '健康' }, { to: '/mcp', label: 'MCP' }] },
]
const nav: NavItem[] = navGroups.flatMap(g => g.items)
const sideNav = computed<NavItem[]>(() => {
  const cur = route.path
  const group = navGroups.find(g => g.items.some((i: NavItem) => cur === i.to || (i.to !== '/' && cur.startsWith(i.to)))) ?? navGroups[0]
  return group.items as NavItem[]
})
// 头部溢出：>1024 时隐藏 último 2 项进“更多”
const overflowNav = computed<NavItem[]>(() => nav.slice(8))
const overflowOptions = computed(() => overflowNav.value.map((i: NavItem) => ({ label: i.label, key: i.to })))
function onOverflowSelect(key: string): void { void router.push(key) }
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
    '/workbench': () => import('@/views/WorkbenchView.vue'),
  }
  const loader = map[to]
  if (loader) void loader().catch(() => {})
}
// keep-alive LRU 8 + 面包屑
const cachedViews = ref<string[]>(['Home', 'Workbench', 'Goals', 'Calendar', 'Week', 'Graph'])
function touchCache(name: string | undefined): void {
  if (!name || name === 'Login' || name === 'NotFound') return
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
const sessionQuery = ref('')
const favKey = 'planner:favNav'
function loadFavs(): Set<string> {
  try { const raw = localStorage.getItem(favKey); if (raw) return new Set(JSON.parse(raw) as string[]) } catch {}
  return new Set<string>()
}
const favSet = ref<Set<string>>(loadFavs())
function saveFavs(): void { try { localStorage.setItem(favKey, JSON.stringify(Array.from(favSet.value))) } catch {} }
function isFav(to: string): boolean { return favSet.value.has(to) }
function toggleFav(to: string): void { if (favSet.value.has(to)) favSet.value.delete(to); else favSet.value.add(to); favSet.value = new Set(favSet.value); saveFavs() }
const filteredSideNav = computed<NavItem[]>(() => {
  const q = sessionQuery.value.trim().toLowerCase()
  if (!q) return sideNav.value
  return sideNav.value.filter(i => `${i.label} ${i.to}`.toLowerCase().includes(q))
})
const favNav = computed<NavItem[]>(() => nav.filter(i => favSet.value.has(i.to)))
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
  window.addEventListener('keydown', onKeydown)
  // 路由级进度 120ms 内完成 + 面包屑/缓存触摸
  router.beforeEach(() => { startProgress(); return true })
  router.afterEach((to) => { doneProgress(); touchCache(to.name as string | undefined) })
  router.onError(() => doneProgress())
  // 初次触摸
  touchCache(route.name as string | undefined)
  // 空闲预取前 4 个核心
  const idle = (window as unknown as { requestIdleCallback?: (cb: () => void) => number }).requestIdleCallback
  const idlePrefetch = () => { ['/goals','/calendar','/graph','/rag'].forEach(prefetch) }
  if (idle) idle(idlePrefetch); else setTimeout(idlePrefetch, 1800)
  // 视口预取：观察主导航链接
  try {
    const obs = new IntersectionObserver((entries) => {
      entries.forEach(e => { if (e.isIntersecting) { const to = (e.target as HTMLElement).getAttribute('data-prefetch'); if (to) prefetch(to) } })
    }, { rootMargin: '200px' })
    document.querySelectorAll('nav [data-prefetch]').forEach(el => obs.observe(el))
  } catch {}
})
onBeforeUnmount(() => { try { window.removeEventListener('keydown', onKeydown) } catch {}; if (progressTimer) clearInterval(progressTimer) })

const theme = {
  common: {
    primaryColor: '#1d1d1f',
    primaryColorHover: '#2c2c2e',
    borderRadius: '12px',
    fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Helvetica Neue", Helvetica, Arial, sans-serif',
    textColorBase: '#1d1d1f',
  },
  Card: {
    borderRadius: '16px',
    color: '#ffffff',
    borderColor: 'transparent',
  },
  Button: {
    borderRadiusMedium: '20px',
  },
}
</script>
