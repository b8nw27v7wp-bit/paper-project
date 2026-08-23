import { app, BrowserWindow, ipcMain, shell, Notification, Tray, Menu, nativeImage } from 'electron'
import { join } from 'path'
import { spawn, ChildProcess } from 'child_process'
import { registerIpcHandlers } from './ipc/handlers'

const isDev = !app.isPackaged
const FRONTEND_URL = process.env.FRONTEND_URL || 'http://localhost:5173'

let mainWindow: BrowserWindow | null = null
let sidecar: ChildProcess | null = null
let tray: Tray | null = null

function startSidecar() {
  // P2 sidecar：随App启动FastAPI，生产用 extraResources/server，开发用本地
  const serverPath = isDev
    ? join(__dirname, '../../server')
    : join(process.resourcesPath, 'server')
  try {
    sidecar = spawn('python', ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'], {
      cwd: serverPath,
      stdio: 'ignore',
      shell: true,
    })
    sidecar.on('error', (e) => console.error('[sidecar] failed', e))
  } catch (e) {
    console.error('[sidecar] spawn error', e)
  }
}

function createTray() {
  try {
    const icon = nativeImage.createEmpty()
    tray = new Tray(icon)
    tray.setToolTip('LearningPlanner')
    const menu = Menu.buildFromTemplate([
      { label: '显示', click: () => mainWindow?.show() },
      { label: '通知测试', click: () => new Notification({ title: '学习提醒', body: '该学习了！' }).show() },
      { type: 'separator' },
      { label: '退出', click: () => app.quit() },
    ])
    tray.setContextMenu(menu)
    tray.on('double-click', () => mainWindow?.show())
  } catch (e) {
    console.error('[tray] failed', e)
  }
}

// 初始化 better-sqlite3 状态库（失败回退 electron-store，已在 handlers 中）
function initStore() {
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const Database = require('better-sqlite3')
    const dbPath = join(app.getPath('userData'), 'planner.db')
    const db = new Database(dbPath)
    db.exec(`CREATE TABLE IF NOT EXISTS global_state(key TEXT PRIMARY KEY, value TEXT);
             CREATE TABLE IF NOT EXISTS automations(id TEXT PRIMARY KEY, cron TEXT, status TEXT, last_run TEXT);
             CREATE TABLE IF NOT EXISTS inbox_items(id TEXT PRIMARY KEY, title TEXT, read INT, created_at TEXT)`)
    db.close()
    console.log('[store] better-sqlite3 ok', dbPath)
  } catch (e) {
    console.log('[store] better-sqlite3 fallback to electron-store', (e as Error).message)
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 1024,
    minHeight: 640,
    show: false,
    backgroundColor: '#f8fafc',
    webPreferences: {
      preload: join(__dirname, 'preload.js'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
    },
    title: '智能学习规划系统',
  })

  // IPC
  registerIpcHandlers(ipcMain, () => mainWindow)

  const url = isDev ? FRONTEND_URL : `file://${join(__dirname, '../frontend/dist/index.html')}`

  if (isDev) {
    mainWindow.loadURL(url)
    mainWindow.webContents.openDevTools({ mode: 'detach' })
  } else {
    mainWindow.loadFile(join(__dirname, '../../frontend/dist/index.html'))
  }

  mainWindow.on('ready-to-show', () => mainWindow?.show())

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  // Tray/notification placeholder for P2
  if (Notification.isSupported()) {
    // silent check
  }
}

app.whenReady().then(() => {
  initStore()
  startSidecar()
  createWindow()
  createTray()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => {
  try { sidecar?.kill() } catch {}
  tray?.destroy()
})

// Graceful
process.on('uncaughtException', (err) => console.error('[main] uncaught', err))
