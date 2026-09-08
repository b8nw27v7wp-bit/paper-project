// TopNav 插件：可伸缩顶栏导航（app.use(TopNavPlugin) 即插即用）
// - 全局注册 <TopNav> 组件，提供 TOPNAV_SECTIONS 配置
// - useTopNav() 暴露 collapsed 可伸缩状态（localStorage topnav:collapsed 持久化）
import { ref } from 'vue'
import type { App, Plugin } from 'vue'
import TopNav from './TopNav.vue'
import { TOPNAV_SECTIONS, TOPNAV_COLLAPSE_KEY } from './nav'

export { TopNav, TOPNAV_SECTIONS, TOPNAV_COLLAPSE_KEY }

const collapsed = ref(false)

try {
  collapsed.value = localStorage.getItem(TOPNAV_COLLAPSE_KEY) === '1'
} catch {}

export function useTopNav() {
  function setCollapsed(v: boolean): void {
    collapsed.value = v
    try {
      localStorage.setItem(TOPNAV_COLLAPSE_KEY, v ? '1' : '0')
    } catch {}
  }
  function toggleCollapsed(): void {
    setCollapsed(!collapsed.value)
  }
  return { collapsed, setCollapsed, toggleCollapsed, sections: TOPNAV_SECTIONS }
}

export const TopNavPlugin: Plugin = {
  install(app: App) {
    app.component('TopNav', TopNav)
    app.provide('topnav:sections', TOPNAV_SECTIONS)
  },
}
