import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'Home', component: () => import('@/views/HomeView.vue') },
  { path: '/health', name: 'Health', component: () => import('@/views/HealthCheck.vue') },
  { path: '/goals', name: 'Goals', component: () => import('@/views/GoalsView.vue') },
  { path: '/calendar', name: 'Calendar', component: () => import('@/views/CalendarView.vue') },
  { path: '/dashboard', name: 'Dashboard', component: () => import('@/views/DashboardView.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
