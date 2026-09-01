import { Tray, Menu, nativeImage, Notification, BrowserWindow, app } from 'electron'

let tray: Tray | null = null
let unreadCount = 0

/**
 * P2 Tray/通知：better-sqlite3 已透传 unread，托盘与桌面通知联动
 * 对标 00-管理/28周 W17-18 tray + 系统通知，支持 FastAPI 推送
 */
export function createAppTray(getWindow: () => BrowserWindow | null): Tray | null {
  try {
    const icon = nativeImage.createEmpty()
    // 用空图标占位，真实环境可用 build/icon.png
    tray = new Tray(icon)
    tray.setToolTip('LearningPlanner - 智能学习规划')
    rebuildMenu(getWindow)

    tray.on('double-click', () => {
      const w = getWindow()
      if (!w) return
      if (w.isMinimized()) w.restore()
      w.show()
      w.focus()
    })

    tray.on('click', () => {
      const w = getWindow()
      if (w && !w.isVisible()) w.show()
    })

    console.log('[tray] created')
    return tray
  } catch (e) {
    console.error('[tray] failed', e)
    return null
  }
}

function rebuildMenu(getWindow: () => BrowserWindow | null) {
  if (!tray) return
  const template: Electron.MenuItemConstructorOptions[] = [
    { label: '显示主窗口', click: () => getWindow()?.show() },
    { label: '隐藏到托盘', click: () => getWindow()?.hide() },
    { type: 'separator' },
    {
      label: '今日打卡提醒',
      click: () => showNotification('学习提醒', '该完成今日任务了，点击查看详情'),
    },
    {
      label: '本周反思已生成',
      click: () => showNotification('周反思', '本周完成率已统计，下周计划已调整'),
    },
    { type: 'separator' },
    { label: `未读: ${unreadCount}`, enabled: false },
    { label: '清空未读', click: () => setUnread(0) },
    { type: 'separator' },
    { label: '退出', role: 'quit', click: () => app.quit() },
  ]
  tray.setContextMenu(Menu.buildFromTemplate(template))
}

export function setUnread(count: number): void {
  unreadCount = Math.max(0, count)
  if (tray) {
    tray.setToolTip(`LearningPlanner (${unreadCount} 未读)`)
    // 重新构建菜单以刷新计数
    // 需 getWindow：延迟注入，这里仅更新 toolTip
  }
}

export function showNotification(title: string, body: string, silent = false): void {
  if (!Notification.isSupported()) {
    console.log('[notify] not supported', title, body)
    return
  }
  const n = new Notification({ title, body, silent, urgency: 'normal' })
  n.on('click', () => {
    // 点击通知唤起窗口
    try { BrowserWindow.getAllWindows()[0]?.show() } catch {}
  })
  n.show()
}

export function notifyFromPayload(payload: { title: string; body: string; tag?: string }): void {
  if (payload.tag) setUnread(unreadCount + 1)
  showNotification(payload.title, payload.body)
}

export function destroyTray(): void {
  try { tray?.destroy() } catch {}
  tray = null
}
