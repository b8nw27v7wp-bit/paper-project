import { createRouter, createWebHistory, type RouteLocationGeneric } from 'vue-router'

export type RouteMetaExtra = { public?: boolean; title?: string; group?: 'main' | 'core' | 'know' | 'analyse' | 'system'; keepAlive?: boolean; prefetch?: boolean }
const routes = [
  { path: '/', redirect: '/agent' },
  { path: '/agent', name: 'AgentWorkbench', component: () => import('@/views/AgentWorkbenchView.vue'), meta: { title: '智能体工作台', group: 'main', keepAlive: true } as RouteMetaExtra },
  { path: '/login', name: 'Login', component: () => import('@/views/LoginView.vue'), meta: { public: true, title: '登录' } as RouteMetaExtra },
  { path: '/health', name: 'Health', component: () => import('@/views/HealthCheck.vue'), meta: { public: true, title: '健康', group: 'system' } as RouteMetaExtra },
  { path: '/goals', name: 'Goals', component: () => import('@/views/GoalsView.vue'), meta: { title: '目标', group: 'core', keepAlive: true, prefetch: true } as RouteMetaExtra },
  { path: '/calendar', name: 'Calendar', component: () => import('@/views/CalendarView.vue'), meta: { title: '日历', group: 'core', keepAlive: true, prefetch: true } as RouteMetaExtra },
  { path: '/week', name: 'Week', component: () => import('@/views/WeekView.vue'), meta: { title: '周视图', group: 'core', keepAlive: true } as RouteMetaExtra },
  { path: '/gantt', name: 'Gantt', component: () => import('@/views/GanttView.vue'), meta: { title: '甘特', group: 'core' } as RouteMetaExtra },
  { path: '/tasks/batch', name: 'TaskBatch', component: () => import('@/views/TaskBatchView.vue'), meta: { title: '批量', group: 'core' } as RouteMetaExtra },
  { path: '/graph', name: 'Graph', component: () => import('@/views/KnowledgeGraphView.vue'), meta: { title: '图谱', group: 'know', keepAlive: true, prefetch: true } as RouteMetaExtra },
  { path: '/dashboard', name: 'Dashboard', component: () => import('@/views/DashboardView.vue'), meta: { title: '大屏', group: 'system' } as RouteMetaExtra },
  { path: '/mcp', name: 'MCP', component: () => import('@/views/MCPView.vue'), meta: { title: 'MCP', group: 'system' } as RouteMetaExtra },
  { path: '/experiments', name: 'Experiments', component: () => import('@/views/ExperimentsView.vue'), meta: { title: '实验', group: 'analyse' } as RouteMetaExtra },
  { path: '/large-screen', name: 'LargeScreen', component: () => import('@/views/LargeScreenView.vue'), meta: { title: '驾驶舱', group: 'system' } as RouteMetaExtra },
  { path: '/rag', name: 'RAG', component: () => import('@/views/RAGView.vue'), meta: { title: '知识库', group: 'know', prefetch: true } as RouteMetaExtra },
  { path: '/reflection', name: 'Reflection', component: () => import('@/views/ReflectionView.vue'), meta: { title: '反思', group: 'analyse' } as RouteMetaExtra },
  { path: '/settings', name: 'Settings', component: () => import('@/views/SettingsView.vue'), meta: { title: '设置', group: 'system' } as RouteMetaExtra },
  { path: '/notifications', name: 'Notifications', component: () => import('@/views/NotificationsView.vue'), meta: { title: '通知', group: 'system' } as RouteMetaExtra },
  { path: '/workbench', redirect: (to: RouteLocationGeneric) => ({ path: '/agent', query: to.query }) },
  { path: '/:pathMatch(.*)*', name: 'NotFound', component: () => import('@/views/NotFoundView.vue'), meta: { public: true, title: '404' } as RouteMetaExtra },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior() {
    return { top: 0 }
  },
})

// 守卫：鉴权 + title + 进度由 App.vue 统一处理，这里仅鉴权与 404 keepAlive 标记
router.beforeEach((to) => {
  const isPublic = Boolean((to.meta as Record<string, unknown>)?.public)
  if (isPublic) return true
  try {
    const token = typeof localStorage !== 'undefined' ? localStorage.getItem('token') : null
    if (!token) {
      return { path: '/login', query: { redirect: to.fullPath } }
    }
  } catch {}
  return true
})
router.afterEach((to) => {
  const title = (to.meta as Record<string, unknown>)?.title as string | undefined
  if (title) document.title = `${title} - 智能学习规划系统`
})

export default router
