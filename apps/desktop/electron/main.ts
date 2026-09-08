import { app, BrowserWindow, ipcMain, shell, Notification, Tray, Menu, nativeImage, nativeTheme, screen } from 'electron'
import { join } from 'path'
import { spawn, ChildProcess } from 'child_process'
import { existsSync, appendFileSync } from 'fs'
import Store from 'electron-store'
import { registerIpcHandlers } from './ipc/handlers'

const isDev = !app.isPackaged
const FRONTEND_URL = process.env.FRONTEND_URL || 'http://localhost:5173'
const SIDECAR_BASE = process.env.PLANNER_API || 'http://127.0.0.1:8000'

let mainWindow: BrowserWindow | null = null
let sidecar: ChildProcess | null = null
let tray: Tray | null = null
let isQuitting = false
// P0 sidecar 自愈状态：指数退避重启，最多5次后置 tray 告警
let sidecarRestartAttempts = 0
let sidecarFailed = false
let sidecarHealthTimer: ReturnType<typeof setInterval> | null = null
let sidecarBackoffTimer: ReturnType<typeof setTimeout> | null = null
const SIDECAR_MAX_RESTARTS = 5
// P0 托盘未读数（由 desktop/notifications 轮询更新）
let trayUnread = 0

type WindowBounds = { x?: number; y?: number; width: number; height: number; isMaximized?: boolean; display_id?: string | null }
const fallbackStore = new Store<{ windowBounds?: WindowBounds }>({ name: 'planner-window-state' })

function logFallback(msg: string): void {
  try {
    const logPath = join(app.getPath('userData'), 'fallback.log')
    appendFileSync(logPath, `[${new Date().toISOString()}] ${msg}\n`)
  } catch {}
  console.log(msg)
}

function getWindowBounds(): WindowBounds | null {
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const Database = require('better-sqlite3')
    const dbPath = join(app.getPath('userData'), 'planner.db')
    if (existsSync(dbPath)) {
      const db = new Database(dbPath, { readonly: true })
      const row = db.prepare('SELECT x,y,width,height,is_maximized FROM window_state WHERE id=?').get('main') as
        | { x: number | null; y: number | null; width: number; height: number; is_maximized: number | null }
        | undefined
      db.close()
      if (row) return { x: row.x ?? undefined, y: row.y ?? undefined, width: row.width, height: row.height, isMaximized: !!row.is_maximized }
    }
  } catch (e) {
    logFallback(`[store] getWindowBounds fallback: ${(e as Error).message}`)
  }
  return (fallbackStore.get('windowBounds') as WindowBounds | undefined) || null
}

function saveWindowBounds(bounds: WindowBounds): void {
  const now = new Date().toISOString()
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const Database = require('better-sqlite3')
    const dbPath = join(app.getPath('userData'), 'planner.db')
    const db = new Database(dbPath)
    db.prepare(
      `INSERT INTO window_state(id,x,y,width,height,is_maximized,updated_at) VALUES('main',?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET x=excluded.x, y=excluded.y, width=excluded.width, height=excluded.height, is_maximized=excluded.is_maximized, updated_at=excluded.updated_at`,
    ).run(bounds.x ?? null, bounds.y ?? null, bounds.width, bounds.height, bounds.isMaximized ? 1 : 0, now)
    db.close()
    return
  } catch (e) {
    logFallback(`[store] saveWindowBounds fallback: ${(e as Error).message}`)
  }
  fallbackStore.set('windowBounds', bounds as never)
}

function showNotification(title: string, body: string, extra?: { tag?: string; trace_id?: string }): void {
  if (!Notification.isSupported()) {
    console.log('[notify] not supported', title, body)
    return
  }
  const n = new Notification({ title, body, silent: false, urgency: 'normal' })
  n.on('click', () => {
    const w = mainWindow ?? BrowserWindow.getAllWindows()[0]
    if (w) {
      if (w.isMinimized()) w.restore()
      w.show()
      w.focus()
      // P1 通知深链：聚焦后经 IPC 通知渲染层跳转（tag/trace_id 透传，消费与否由前端决定）
      try {
        w.webContents.send('notification:click', { title, tag: extra?.tag, trace_id: extra?.trace_id })
      } catch (e) {
        logFallback(`[notify] send notification:click failed ${(e as Error).message}`)
      }
    }
  })
  n.show()
}

let notificationPoll: ReturnType<typeof setInterval> | null = null
const notifiedIds = new Set<string | number>()

function getAuthToken(): string | null {
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const Database = require('better-sqlite3')
    const dbPath = join(app.getPath('userData'), 'planner.db')
    if (existsSync(dbPath)) {
      const db = new Database(dbPath, { readonly: true })
      const row = db.prepare('SELECT value FROM global_state WHERE key=?').get('auth:token') as { value: string } | undefined
      db.close()
      if (row) {
        try {
          const parsed = JSON.parse(row.value) as unknown
          if (typeof parsed === 'string') return parsed
          return row.value
        } catch {
          return row.value
        }
      }
    }
  } catch {}
  try {
    const s = new Store({ name: 'planner-ui-state' })
    const t = s.get('auth:token' as never) as unknown as string | undefined
    if (t) return t
  } catch {}
  try {
    return (fallbackStore.get('auth:token' as never) as unknown as string) || null
  } catch {
    return null
  }
}

function notifyFromPayload(p: Record<string, unknown>): void {
  try {
    const title = (p['title'] as string) || (p['tag'] as string) || '学习提醒'
    const body = (p['body'] as string) || (p['message'] as string) || (p['content'] as string) || ''
    const tag = p['tag'] as string | undefined
    const traceId = (p['trace_id'] as string | undefined) || (p['traceId'] as string | undefined)
    if (title || body) showNotification(String(title), String(body), { tag, trace_id: traceId })
  } catch {}
}

async function fetchAndNotify(): Promise<void> {
  try {
    const token = getAuthToken()
    const headers: Record<string, string> = {}
    if (token) headers['Authorization'] = `Bearer ${token}`
    const res: Response = await (globalThis as unknown as { fetch: typeof fetch }).fetch(
      'http://127.0.0.1:8000/api/v1/desktop/notifications?limit=10',
      { headers } as RequestInit,
    )
    if (!res || !res.ok) return
    const json = (await res.json()) as { data?: { items?: unknown[]; unread?: number }; items?: unknown[] }
    const items = (json?.data?.items ?? (json as unknown as { items?: unknown[] })?.items ?? []) as Record<string, unknown>[]
    // P0 托盘未读数：优先后端 unread，否则用本次 items 长度
    try {
      const unread = (json?.data as { unread?: number } | undefined)?.unread
      trayUnread = typeof unread === 'number' ? unread : items.length
      refreshTrayMenu()
    } catch {}
    for (const it of items) {
      const id = (it['id'] as string | number) ?? `${String(it['title'] ?? '')}-${String(it['created_at'] ?? '')}`
      if (notifiedIds.has(id)) continue
      notifiedIds.add(id)
      if (notifiedIds.size > 100) {
        const first = notifiedIds.values().next().value as string | number | undefined
        if (first !== undefined) notifiedIds.delete(first)
      }
      notifyFromPayload(it)
    }
  } catch {}
}

function startNotificationPolling(): void {
  try {
    if (notificationPoll) clearInterval(notificationPoll)
  } catch {}
  // 立即一次，之后每30s（P0 托盘轮询）
  void fetchAndNotify()
  notificationPoll = setInterval(() => {
    void fetchAndNotify()
  }, 30_000)
  console.log('[poll] notification polling started every 30s -> /api/v1/desktop/notifications')
}

function scheduleSidecarRestart(reason: string): void {
  if (isQuitting) return
  if (sidecarFailed) return
  sidecarRestartAttempts += 1
  if (sidecarRestartAttempts > SIDECAR_MAX_RESTARTS) {
    sidecarFailed = true
    logFallback(`[sidecar] restart exhausted after ${SIDECAR_MAX_RESTARTS} attempts reason=${reason}, tray alert`)
    try { refreshTrayMenu() } catch {}
    try { showNotification('Sidecar 异常', '后端服务多次重启失败，请手动重启 sidecar') } catch {}
    return
  }
  const delay = Math.min(30_000, 1000 * 2 ** (sidecarRestartAttempts - 1))
  logFallback(`[sidecar] schedule restart #${sidecarRestartAttempts} in ${delay}ms reason=${reason}`)
  try { if (sidecarBackoffTimer) clearTimeout(sidecarBackoffTimer) } catch {}
  sidecarBackoffTimer = setTimeout(() => {
    if (isQuitting || sidecarFailed) return
    try { sidecar?.kill() } catch {}
    sidecar = null
    startSidecar()
  }, delay)
}

function restartSidecar(): void {
  // 托盘手动重启：清零退避计数，立即拉起
  try { if (sidecarBackoffTimer) clearTimeout(sidecarBackoffTimer) } catch {}
  sidecarRestartAttempts = 0
  sidecarFailed = false
  try { sidecar?.kill() } catch {}
  sidecar = null
  logFallback('[sidecar] manual restart from tray')
  startSidecar()
  try { refreshTrayMenu() } catch {}
}

async function checkSidecarHealth(): Promise<void> {
  try {
    const ctrl = new AbortController()
    const t = setTimeout(() => { try { ctrl.abort() } catch {} }, 5000)
    const res = await (globalThis as unknown as { fetch: typeof fetch }).fetch(`${SIDECAR_BASE}/health`, { signal: ctrl.signal } as RequestInit)
    clearTimeout(t)
    if (res && res.ok) {
      // 健康即清零连续失败（不断开正常运行的 sidecar）
      if (sidecarRestartAttempts !== 0 && !sidecarFailed) sidecarRestartAttempts = 0
      return
    }
    logFallback(`[sidecar] health bad status=${res?.status}`)
  } catch (e) {
    logFallback(`[sidecar] health check failed ${(e as Error).message}`)
  }
}

function startSidecarHealthPoll(): void {
  try { if (sidecarHealthTimer) clearInterval(sidecarHealthTimer) } catch {}
  void checkSidecarHealth()
  sidecarHealthTimer = setInterval(() => { void checkSidecarHealth() }, 30_000)
  console.log('[sidecar] health poll every 30s -> /health')
}

function startSidecar() {
  // P2 sidecar：随App启动FastAPI，生产用 extraResources/server + externalBin/resources/server 双探针
  // extraResources/server -> process.resourcesPath/server (python 源码)，externalBin/bin -> resourcesPath/bin/server(.exe)
  const prodCandidates = [
    join(process.resourcesPath, 'bin', 'server'), // externalBin 优先（打包的二进制，需 externalBin 构建）
    join(process.resourcesPath, 'server'), // extraResources/server 兜底（源码+venv，过滤 __pycache__/.pyc/data/*.db/tests/.venv）
  ]
  const serverPath = isDev ? join(__dirname, '../../server') : prodCandidates[0]
  const trySpawn = (cwd: string, useBinary: boolean) => {
    try {
      if (useBinary) {
        const bin = process.platform === 'win32' ? join(cwd, 'server.exe') : join(cwd, 'server')
        if (!existsSync(bin)) {
          console.log(`[sidecar] binary not found ${bin}, fallback to python`)
          return false
        }
        sidecar = spawn(bin, ['--host', '127.0.0.1', '--port', '8000'], { stdio: 'ignore', shell: false })
        console.log(`[sidecar] spawn binary ${bin}`)
      } else {
        // 开发 python -m uvicorn + 生产 extraResources/server 双探针（shell:false 防注入）
        const py = process.platform === 'win32' ? 'python' : 'python3'
        sidecar = spawn(py, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'], {
          cwd,
          stdio: 'ignore',
          shell: false,
          windowsHide: true,
        })
        console.log(`[sidecar] spawn python uvicorn cwd=${cwd} shell:false`)
      }
      sidecar.on('error', (e) => {
        console.error('[sidecar] failed', e)
        logFallback(`[sidecar] error ${String((e as Error).message)}`)
        scheduleSidecarRestart(`error:${String((e as Error).message).slice(0, 80)}`)
      })
      sidecar.on('exit', (code) => {
        console.log(`[sidecar] exit code=${code}`)
        if (!isQuitting && code !== 0 && code !== null) {
          scheduleSidecarRestart(`exit:${String(code)}`)
        }
      })
      return true
    } catch (e) {
      console.error('[sidecar] spawn error', e)
      return false
    }
  }
  if (isDev) {
    trySpawn(serverPath, false)
  } else {
    // 生产双探针：优先 externalBin/bin/server，二进制不存在则回退 extraResources/server python
    try {
      const binPath = process.platform === 'win32' ? join(prodCandidates[0], 'server.exe') : join(prodCandidates[0], 'server')
      if (existsSync(binPath)) {
        if (trySpawn(prodCandidates[0], true)) return
      }
      console.log('[sidecar] externalBin missing, fallback to extraResources/server')
      trySpawn(prodCandidates[1], false)
    } catch {
      trySpawn(prodCandidates[1], false)
    }
  }
}

function createAppMenu(): void {
  // 原生菜单：File/Edit/View/Window/Help，对齐 mac hiddenInset 体验
  try {
    const template: Electron.MenuItemConstructorOptions[] = [
      ...(process.platform === 'darwin' ? [{ role: 'appMenu' as const }] : []),
      { role: 'fileMenu' as const, submenu: [{ role: 'quit' as const }] },
      {
        label: 'Agent',
        submenu: [
          {
            label: '新会话',
            accelerator: 'CmdOrCtrl+N',
            click: () => mainWindow?.webContents.send('agent:new-session'),
          },
          {
            label: '聚焦输入框',
            accelerator: 'CmdOrCtrl+I',
            click: () => mainWindow?.webContents.send('agent:focus-composer'),
          },
          {
            label: '切换 Inspector',
            accelerator: 'CmdOrCtrl+"',
            click: () => mainWindow?.webContents.send('agent:toggle-inspector'),
          },
        ],
      },
      { role: 'editMenu' as const },
      {
        role: 'viewMenu' as const,
        submenu: [
          { role: 'reload' as const },
          { role: 'forceReload' as const },
          { role: 'toggleDevTools' as const },
          { type: 'separator' as const },
          { role: 'resetZoom' as const },
          { role: 'zoomIn' as const },
          { role: 'zoomOut' as const },
          { type: 'separator' as const },
          { role: 'togglefullscreen' as const },
        ],
      },
      { role: 'windowMenu' as const },
      {
        role: 'help' as const,
        submenu: [
          { label: '健康检查', click: () => mainWindow?.loadURL(isDev ? FRONTEND_URL + '/health' : `file://${join(__dirname, '../frontend/dist/index.html')}#/health`) },
          { label: '快捷键 ?', accelerator: '?', click: () => mainWindow?.webContents.send('show-shortcuts') },
          { type: 'separator' as const },
          { label: '关于 LearningPlanner', click: () => showNotification('LearningPlanner', `v${app.getVersion()} · Apple 极简 · vibrancy sidebar`) },
        ],
      },
    ]
    const menu = Menu.buildFromTemplate(template)
    Menu.setApplicationMenu(menu)
    console.log('[menu] application menu set (hiddenInset+vibrancy)')
  } catch (e) {
    logFallback(`[menu] failed ${(e as Error).message}`)
  }
}

function getTrayIcon(): Electron.NativeImage {
  // P0 托盘真实化：优先 build/icon.ico，缺失则保持空图标不崩
  const candidates = [
    join(__dirname, '../build/icon.ico'),
    join(__dirname, '../../build/icon.ico'),
    join(process.resourcesPath || '', 'build/icon.ico'),
  ]
  for (const p of candidates) {
    try {
      if (p && existsSync(p)) {
        const img = nativeImage.createFromPath(p)
        if (!img.isEmpty()) return img
      }
    } catch {}
  }
  return nativeImage.createEmpty()
}

function focusMainWindow(): void {
  const w = mainWindow ?? BrowserWindow.getAllWindows()[0]
  if (!w) return
  if (w.isMinimized()) w.restore()
  w.show()
  w.focus()
}

async function runHealthCheck(): Promise<void> {
  try {
    const res = await (globalThis as unknown as { fetch: typeof fetch }).fetch(`${SIDECAR_BASE}/health`)
    const ok = !!res?.ok
    showNotification('健康检查', ok ? 'sidecar /health 正常' : `sidecar 异常 status=${res?.status}`)
  } catch (e) {
    showNotification('健康检查', `sidecar 不可达 ${(e as Error).message.slice(0, 80)}`)
  }
}

function refreshTrayMenu(): void {
  if (!tray) return
  try {
    tray.setToolTip(trayUnread > 0 ? `LearningPlanner (${trayUnread} 未读)` : 'LearningPlanner - 智能学习规划')
    const menu = Menu.buildFromTemplate([
      { label: '显示', click: () => focusMainWindow() },
      { label: trayUnread > 0 ? `未读数: ${trayUnread}` : '未读数: 0', enabled: false },
      { label: '通知测试', click: () => showNotification('学习提醒', '该学习了！点击查看今日任务', { tag: 'demo' }) },
      ...(sidecarFailed
        ? [{ label: '⚠ sidecar 多次重启失败', enabled: false } as Electron.MenuItemConstructorOptions]
        : []),
      { type: 'separator' as const },
      { label: '健康检查', click: () => { void runHealthCheck() } },
      { label: '重启 sidecar', click: () => restartSidecar() },
      { type: 'separator' as const },
      { label: '退出', click: () => app.quit() },
    ])
    tray.setContextMenu(menu)
  } catch (e) {
    logFallback(`[tray] refresh failed ${(e as Error).message}`)
  }
}

function createTray() {
  // P0 托盘真实化：build/icon.ico + 未读数/健康检查/重启sidecar/退出
  try {
    tray = new Tray(getTrayIcon())
    tray.setToolTip('LearningPlanner - 智能学习规划')
    refreshTrayMenu()
    tray.on('double-click', () => focusMainWindow())
    // 单击：若窗口隐藏则显示，计入 W17-18 tray 交互
    tray.on('click', () => {
      if (mainWindow && !mainWindow.isVisible()) mainWindow.show()
    })
    console.log('[tray] created real (icon.ico + unread/health/restart/quit)')
  } catch (e) {
    logFallback(`[tray] failed ${(e as Error).message}`)
  }
}

// P1 窗口恢复 display_id/越界校验：坐标超出当前 displays 范围则回退居中默认尺寸
function isBoundsVisible(b: WindowBounds): boolean {
  try {
    if (b.x === undefined || b.y === undefined) return true
    const displays = screen.getAllDisplays()
    if (!displays.length) return true
    // display_id 若提供但无匹配显示器，视为不可见（回退默认）
    if (b.display_id) {
      const matchId = displays.some((d) => String(d.id) === String(b.display_id))
      if (!matchId) return false
    }
    const px = b.x
    const py = b.y
    return displays.some((d) => {
      const r = d.bounds
      return px >= r.x && px < r.x + r.width && py >= r.y && py < r.y + r.height
    })
  } catch {
    return true
  }
}

function sanitizeBounds(saved: WindowBounds | null): WindowBounds {
  const fallback: WindowBounds = { width: 1280, height: 860 }
  if (!saved) return fallback
  const width = Math.min(3840, Math.max(800, saved.width || 1280))
  const height = Math.min(2160, Math.max(600, saved.height || 860))
  if (!isBoundsVisible(saved)) {
    // 越界：丢弃 x/y 让 Electron 居中（不传 x/y），保留尺寸与最大化
    console.log('[window] bounds out of displays, fallback centered default')
    return { width, height, isMaximized: saved.isMaximized }
  }
  return { ...saved, width, height }
}

// P1 开机自启：默认关，与后端 GET /desktop/config 的 autoLaunch 语义对齐（只读联动不强制）
async function syncAutoLaunch(): Promise<void> {
  try {
    const token = getAuthToken()
    const headers: Record<string, string> = {}
    if (token) headers['Authorization'] = `Bearer ${token}`
    const ctrl = new AbortController()
    const t = setTimeout(() => { try { ctrl.abort() } catch {} }, 5000)
    const res = await (globalThis as unknown as { fetch: typeof fetch }).fetch(
      `${SIDECAR_BASE}/api/v1/desktop/config`,
      { headers, signal: ctrl.signal } as RequestInit,
    )
    clearTimeout(t)
    if (!res?.ok) {
      console.log('[autolaunch] config unreachable, keep default off')
      return
    }
    const json = (await res.json()) as { data?: { features?: { autoLaunch?: boolean } } }
    const want = json?.data?.features?.autoLaunch === true
    try {
      app.setLoginItemSettings({ openAtLogin: want, openAsHidden: false })
      console.log(`[autolaunch] backend autoLaunch=${want} applied openAtLogin=${want}`)
    } catch (e) {
      logFallback(`[autolaunch] setLoginItemSettings failed ${(e as Error).message}`)
    }
  } catch (e) {
    console.log(`[autolaunch] sync skipped ${(e as Error).message}, keep default off`)
  }
}

// 初始化 better-sqlite3 状态库：窗口三表 + 全局状态，失败回退 electron-store 并记录回退日志
function initStore() {
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const Database = require('better-sqlite3')
    const dbPath = join(app.getPath('userData'), 'planner.db')
    const db = new Database(dbPath)
    // WAL 并发优化：WAL + NORMAL + 5s 超时，与后端 database.py WAL 对齐
    try {
      db.exec(`PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=5000;`)
    } catch {}
    // 窗口三表：window_state + global_state + inbox_items/automations（对齐 02-数据库设计 §5 + W17-18 窗口记忆）
    db.exec(`
      CREATE TABLE IF NOT EXISTS window_state(
        id TEXT PRIMARY KEY,
        x INTEGER, y INTEGER,
        width INTEGER NOT NULL,
        height INTEGER NOT NULL,
        is_maximized INTEGER DEFAULT 0,
        updated_at TEXT
      );
      CREATE TABLE IF NOT EXISTS global_state(key TEXT PRIMARY KEY, value TEXT);
      CREATE TABLE IF NOT EXISTS automations(id TEXT PRIMARY KEY, cron TEXT, status TEXT, last_run TEXT);
      CREATE TABLE IF NOT EXISTS inbox_items(id TEXT PRIMARY KEY, title TEXT, read INT, created_at TEXT);
      CREATE TABLE IF NOT EXISTS workbench_state(trace_id TEXT PRIMARY KEY, graph TEXT, inspector TEXT, events TEXT, updated_at TEXT);
    `)
    db.exec(`INSERT OR IGNORE INTO window_state(id,width,height) VALUES('main',1280,860)`)
    db.close()
    console.log('[store] better-sqlite3 WAL ok', dbPath)
  } catch (e) {
    logFallback(`[store] better-sqlite3 fallback to electron-store ${(e as Error).message}`)
  }
}

function createWindow() {
  // 窗口记忆：优先 better-sqlite3 window_state，回退 electron-store windowBounds（越界回退居中）
  const saved = getWindowBounds()
  const bounds = sanitizeBounds(saved)
  mainWindow = new BrowserWindow({
    x: bounds.x,
    y: bounds.y,
    width: bounds.width,
    height: bounds.height,
    minWidth: 1120,
    minHeight: 680,
    show: false,
    backgroundColor: '#f8fafc',
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'hidden',
    trafficLightPosition: process.platform === 'darwin' ? { x: 12, y: 12 } : undefined,
    vibrancy: process.platform === 'darwin' ? 'sidebar' : undefined,
    visualEffectState: process.platform === 'darwin' ? 'active' : undefined,
    transparent: false,
    webPreferences: {
      preload: join(__dirname, 'preload.js'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      defaultEncoding: 'utf-8',
      backgroundThrottling: false,
    },
    title: '智能学习规划系统',
  })
  if (saved?.isMaximized) mainWindow.maximize()

  // IPC 全量：app:health/window:*/store:*/notify/desktop:sync（preload contextBridge 对齐）
  registerIpcHandlers(ipcMain, () => mainWindow)

  const url = isDev ? FRONTEND_URL : `file://${join(__dirname, '../frontend/dist/index.html')}`

  if (isDev) {
    mainWindow.loadURL(url)
    mainWindow.webContents.openDevTools({ mode: 'detach' })
  } else {
    mainWindow.loadFile(join(__dirname, '../../frontend/dist/index.html'))
  }

  // 强制设置 charset 与 Accept-Language，避免 Win GBK 误判中文
  try {
    mainWindow.webContents.setZoomFactor(1)
    mainWindow.webContents.on('did-finish-load', () => {
      void mainWindow?.webContents.executeJavaScript(`
        (function(){
          try{
            if(!document.querySelector('meta[charset]')){
              var m=document.createElement('meta'); m.setAttribute('charset','UTF-8'); document.head.prepend(m);
            }
            document.documentElement.setAttribute('lang','zh-CN');
          }catch(e){}
        })();
      `)
    })
  } catch {}

  mainWindow.on('ready-to-show', () => mainWindow?.show())

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    // 与 shell:openExternal 同白名单：仅 https（本地允许 http），未知域 deny
    try {
      const u = new URL(url)
      const isLocal = u.hostname === 'localhost' || u.hostname === '127.0.0.1'
      const protoOk = u.protocol === 'https:' || (u.protocol === 'http:' && isLocal)
      if (!protoOk) return { action: 'deny' }
    } catch {
      return { action: 'deny' }
    }
    void shell.openExternal(url)
    return { action: 'deny' }
  })

  // 窗口记忆：close/hide 时保存 bounds，支持打包后重启恢复
  const saveBounds = () => {
    if (!mainWindow) return
    try {
      const b = mainWindow.getBounds()
      const isMax = mainWindow.isMaximized()
      saveWindowBounds({ ...b, isMaximized: isMax })
    } catch {}
  }
  mainWindow.on('close', saveBounds)
  mainWindow.on('resize', saveBounds)
  mainWindow.on('move', saveBounds)
  mainWindow.on('maximize', saveBounds)
  mainWindow.on('unmaximize', saveBounds)

  // 托盘化行为由 window-all-closed 统一处理；保存 bounds 已由 close/resize/move 覆盖

  if (Notification.isSupported()) {
    // 占位：Notification 封装已在 showNotification 中
  }
}

app.whenReady().then(() => {
  nativeTheme.themeSource = 'light'
  initStore()
  createAppMenu()
  startSidecar()
  startSidecarHealthPoll()
  createWindow()
  createTray()
  startNotificationPolling()
  void syncAutoLaunch()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => {
  isQuitting = true
  try { if (notificationPoll) clearInterval(notificationPoll) } catch {}
  try { if (sidecarHealthTimer) clearInterval(sidecarHealthTimer) } catch {}
  try { if (sidecarBackoffTimer) clearTimeout(sidecarBackoffTimer) } catch {}
  try { sidecar?.kill() } catch {}
  try { tray?.destroy() } catch {}
  try {
    if (mainWindow) {
      const b = mainWindow.getBounds()
      saveWindowBounds({ ...b, isMaximized: mainWindow.isMaximized() })
    }
  } catch {}
})

// Graceful
process.on('uncaughtException', (err) => console.error('[main] uncaught', err))
