// 顶栏导航配置（由左侧 rail 迁移而来，Codex/Qoder 式横向导航）
// 说明：导航只渲染中文文字，不用任何符号字形（生僻符号在部分 Windows 字库缺字形变方框）。
export interface TopNavItem {
  label: string
  to: string
}

export interface TopNavSection {
  key: string
  items: TopNavItem[]
}

export const TOPNAV_SECTIONS: TopNavSection[] = [
  { key: 'main', items: [{ label: '智能体工作台', to: '/agent' }] },
  {
    key: 'core',
    items: [
      { label: '目标', to: '/goals' },
      { label: '日历', to: '/calendar' },
      { label: '周视图', to: '/week' },
      { label: '甘特', to: '/gantt' },
      { label: '批量', to: '/tasks/batch' },
    ],
  },
  {
    key: 'know',
    items: [
      { label: '图谱', to: '/graph' },
      { label: '知识库', to: '/rag' },
    ],
  },
  {
    key: 'system',
    items: [
      { label: '大屏', to: '/dashboard' },
      { label: '驾驶舱', to: '/large-screen' },
      { label: '反思', to: '/reflection' },
      { label: '实验', to: '/experiments' },
      { label: 'MCP', to: '/mcp' },
      { label: '健康', to: '/health' },
    ],
  },
]

export const TOPNAV_COLLAPSE_KEY = 'topnav:collapsed'
