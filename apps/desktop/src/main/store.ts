/**
 * @deprecated 以 electron/main.ts（initStore/getWindowBounds/saveWindowBounds）为准，本文件为死代码保留（防外部引用）。
 * 保留理由：tsconfig.electron.json 仅编译 electron/**，本文件不参与构建；electron/ 已内联 better-sqlite3+electron-store 双写，此处不再维护。
 */
import { app } from 'electron'
import { join } from 'path'
import Store from 'electron-store'

type WindowBounds = { x?: number; y?: number; width: number; height: number; isMaximized?: boolean }
type GlobalState = Record<string, unknown>

/**
 * P2 WindowState 存储：better-sqlite3 优先，失败回退 electron-store
 * 表结构：window_state(id PK, x,y,width,height,is_maximized) / global_state(key PK, value TEXT) / automations + inbox_items（对齐 02-数据库设计 §5，窗口三表）
 * 复用 00-管理/28周计划 W17-18: externalBin + better-sqlite3 存储窗口状态，失败记录 fallback.log
 */
let sqliteDb: any = null
let fallbackStore: Store<GlobalState> | null = null

function getFallback(): Store<GlobalState> {
  if (!fallbackStore) fallbackStore = new Store<GlobalState>({ name: 'planner-window-state' })
  return fallbackStore
}

export function initWindowStore(): void {
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const Database = require('better-sqlite3')
    const dbPath = join(app.getPath('userData'), 'planner.db')
    sqliteDb = new Database(dbPath)
    // WAL 优化：降低并发锁，与后端 database.py 一致
    try { sqliteDb.exec(`PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=5000;`) } catch {}
    sqliteDb.exec(`
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
    // 插入占位防止空库
    sqliteDb.exec(`INSERT OR IGNORE INTO window_state(id,width,height) VALUES('main',1280,860)`)
    console.log('[store] better-sqlite3 WAL ready', dbPath)
  } catch (e) {
    console.log('[store] fallback to electron-store', (e as Error).message)
    try {
      const { appendFileSync } = require('fs')
      appendFileSync(join(app.getPath('userData'), 'fallback.log'), `[${new Date().toISOString()}] better-sqlite3 fallback ${(e as Error).message}\n`)
    } catch {}
    sqliteDb = null
    getFallback()
  }
}

export function getWindowBounds(): WindowBounds | null {
  if (sqliteDb) {
    try {
      const row = sqliteDb.prepare('SELECT x,y,width,height,is_maximized FROM window_state WHERE id=?').get('main')
      if (row) return { x: row.x ?? undefined, y: row.y ?? undefined, width: row.width, height: row.height, isMaximized: !!row.is_maximized }
    } catch {}
  }
  const fb = getFallback().get('windowBounds') as WindowBounds | undefined
  return fb || null
}

export function saveWindowBounds(bounds: WindowBounds): void {
  const now = new Date().toISOString()
  if (sqliteDb) {
    try {
      sqliteDb
        .prepare(`INSERT INTO window_state(id,x,y,width,height,is_maximized,updated_at) VALUES('main',?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET x=excluded.x, y=excluded.y, width=excluded.width, height=excluded.height, is_maximized=excluded.is_maximized, updated_at=excluded.updated_at`)
        .run(bounds.x ?? null, bounds.y ?? null, bounds.width, bounds.height, bounds.isMaximized ? 1 : 0, now)
      return
    } catch {}
  }
  getFallback().set('windowBounds', bounds as never)
}

export function getGlobal(key: string): unknown {
  if (sqliteDb) {
    try {
      const row = sqliteDb.prepare('SELECT value FROM global_state WHERE key=?').get(key)
      if (row) return JSON.parse(row.value)
    } catch {}
  }
  return getFallback().get(key)
}

export function setGlobal(key: string, value: unknown): void {
  if (sqliteDb) {
    try {
      sqliteDb.prepare('INSERT INTO global_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value').run(key, JSON.stringify(value))
      return
    } catch {}
  }
  getFallback().set(key, value as never)
}

export function deleteGlobal(key: string): void {
  if (sqliteDb) {
    try { sqliteDb.prepare('DELETE FROM global_state WHERE key=?').run(key) } catch {}
  }
  getFallback().delete(key as never)
}

export function closeStore(): void {
  try { sqliteDb?.close() } catch {}
}
