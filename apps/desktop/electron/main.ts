import { app, BrowserWindow, ipcMain, shell, Notification, Tray, Menu, nativeImage } from 'electron'
import { join } from 'path'
import { spawn, ChildProcess } from 'child_process'
import { existsSync, appendFileSync } from 'fs'
import Store from 'electron-store'
import { registerIpcHandlers } from './ipc/handlers'

const isDev = !app.isPackaged
const FRONTEND_URL = process.env.FRONTEND_URL || 'http://localhost:5173'

let mainWindow: BrowserWindow | null = null
let sidecar: ChildProcess | null = null
let tray: Tray | null = null
let isQuitting = false

type WindowBounds = { x?: number; y?: number; width: number; height: number; isMaximized?: boolean }
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

function showNotification(title: string, body: string): void {
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
    if (title || body) showNotification(String(title), String(body))
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
    const json = (await res.json()) as { data?: { items?: unknown[] }; items?: unknown[] }
    const items = (json?.data?.items ?? (json as unknown as { items?: unknown[] })?.items ?? []) as Record<string, unknown>[]
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
      sidecar.on('error', (e) => console.error('[sidecar] failed', e))
      sidecar.on('exit', (code) => console.log(`[sidecar] exit code=${code}`))
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

function createTray() {
  // P2 托盘：Menu(显示/通知测试/退出) + double-click + Notification 封装，复用 src/main/tray.ts 设计
  try {
    const icon = nativeImage.createEmpty()
    tray = new Tray(icon)
    tray.setToolTip('LearningPlanner - 智能学习规划')
    const menu = Menu.buildFromTemplate([
      {
        label: '显示',
        click: () => {
          if (mainWindow) {
            if (mainWindow.isMinimized()) mainWindow.restore()
            mainWindow.show()
            mainWindow.focus()
          }
        },
      },
      { label: '通知测试', click: () => showNotification('学习提醒', '该学习了！点击查看今日任务') },
      { type: 'separator' },
      { label: '退出', click: () => app.quit() },
    ])
    tray.setContextMenu(menu)
    tray.on('double-click', () => {
      if (mainWindow) {
        if (mainWindow.isMinimized()) mainWindow.restore()
        mainWindow.show()
        mainWindow.focus()
      }
    })
    // 单击：若窗口隐藏则显示，计入 W17-18 tray 交互
    tray.on('click', () => {
      if (mainWindow && !mainWindow.isVisible()) mainWindow.show()
    })
    console.log('[tray] created with Menu(显示/通知测试/退出) + double-click')
  } catch (e) {
    logFallback(`[tray] failed ${(e as Error).message}`)
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
  // 窗口记忆：优先 better-sqlite3 window_state，回退 electron-store windowBounds
  const saved = getWindowBounds()
  const bounds = saved || { width: 1280, height: 860 }
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
    shell.openExternal(url)
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
  initStore()
  createAppMenu()
  startSidecar()
  createWindow()
  createTray()
  startNotificationPolling()

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
