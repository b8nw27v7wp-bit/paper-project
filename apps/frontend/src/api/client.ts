import axios, { type AxiosResponse, type AxiosError, type InternalAxiosRequestConfig } from 'axios'
import type { ApiEnvelope } from '@/types'

/**
 * 统一 API 客户端 — 保留 axios 兼容，叠加类型守卫与拦截
 * - baseURL 指向 /api/v1（由 vite.config.ts proxy 转发至 http://localhost:8000）
 * - 前端所有业务 API 通过此 client 访问，保证联调一致
 * - 新增：响应信封守卫、错误归一、请求去重 header
 * - 修复 Electron file:// 乱码/404：打包后 file 协议无 host，需显式指向 127.0.0.1:8000
 */
function resolveBaseUrl(viteBase: string): string {
  try {
    // Electron 环境：window.electronBridge 存在 或 protocol 为 file:
    const isFile = typeof window !== 'undefined' && window.location.protocol === 'file:'
    const isElectron = typeof window !== 'undefined' && !!(window as unknown as { electronBridge?: unknown }).electronBridge
    if (isFile || isElectron) {
      const fromEnv = (import.meta as unknown as { env?: Record<string, string> }).env?.VITE_API_BASE as string | undefined
      if (fromEnv) return fromEnv.replace(/\/$/, '')
      // 三端统一 PLANNER_API — Electron 回退 127.0.0.1:8000
      return 'http://127.0.0.1:8000/api/v1'
    }
  } catch {}
  return viteBase
}

function resolveRootBase(): string {
  try {
    const isFile = typeof window !== 'undefined' && window.location.protocol === 'file:'
    const isElectron = typeof window !== 'undefined' && !!(window as unknown as { electronBridge?: unknown }).electronBridge
    // 三端统一 PLANNER_API — Electron 回退 127.0.0.1:8000
    if (isFile || isElectron) return 'http://127.0.0.1:8000'
  } catch {}
  return '/'
}

export const apiClient = axios.create({
  baseURL: resolveBaseUrl('/api/v1'),
  timeout: 15000,
  headers: { 'Content-Type': 'application/json; charset=utf-8', Accept: 'application/json; charset=utf-8' },
})

// 根探针单独 client（/health 不在 /api/v1 下）
export const rootClient = axios.create({
  baseURL: resolveRootBase(),
  timeout: 8000,
  headers: { 'Content-Type': 'application/json; charset=utf-8' },
})

// 请求拦截 — 注入追踪头 + 鉴权，保持与 deps.py 的 Bearer 优先一致
apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const headers = config.headers as Record<string, unknown>
  if (!headers['X-Requested-With']) {
    ;(headers as Record<string, string>)['X-Requested-With'] = 'XMLHttpRequest'
  }
  // 优先 Bearer Token，兼容 X-User-Id 兜底（debug/PYTEST）
  try {
    const token = typeof localStorage !== 'undefined' ? localStorage.getItem('token') : null
    if (token && !headers['Authorization']) {
      ;(headers as Record<string, string>)['Authorization'] = `Bearer ${token}`
    }
    // 兼容旧后端 X-User-Id（仅当无 Bearer 时）
    const uid = typeof localStorage !== 'undefined' ? localStorage.getItem('user_id') : null
    if (uid && !headers['Authorization'] && !headers['X-User-Id']) {
      ;(headers as Record<string, string>)['X-User-Id'] = uid
    }
  } catch {
    // ignore storage access in non-browser
  }
  return config
})

// 响应拦截 — 信封校验，错误归一，401 统一跳转登录（避免中文错误体被吞）
apiClient.interceptors.response.use(
  (res: AxiosResponse) => {
    return res
  },
  (err: AxiosError) => {
    const status = err.response?.status
    if (status === 401) {
      try {
        const cur = typeof window !== 'undefined' ? window.location.pathname : ''
        if (cur !== '/login' && typeof window !== 'undefined') {
          // 回跳保留：登录后可回到原页；仅站内 path+search，不引入外部 URL
          const back = window.location.pathname + window.location.search
          // 动态 import 避免循环依赖，延迟跳转
          import('@/router').then((m) => {
            const router = (m as unknown as { default: { push: (p: unknown) => void } }).default
            try { router.push({ path: '/login', query: { redirect: back } }) } catch {}
          }).catch(() => {
            try { window.location.href = '/login?redirect=' + encodeURIComponent(back) } catch {}
          })
        }
      } catch {}
    }
    return Promise.reject(err)
  },
)

// —— 类型守卫 ——
export function isApiEnvelope<T>(v: unknown): v is ApiEnvelope<T> {
  if (!v || typeof v !== 'object') return false
  const o = v as Record<string, unknown>
  return typeof o.code === 'number' && typeof o.msg === 'string' && 'data' in o
}

export function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

export function assertEnvelope<T>(v: unknown): asserts v is ApiEnvelope<T> {
  if (!isApiEnvelope<T>(v)) throw new TypeError('Invalid ApiEnvelope')
}

// 信封解包辅助 — 若后端已包 code/msg/data，则返回 data；否则原样
export function unwrapEnvelope<T>(payload: unknown, fallback: T): T {
  if (isApiEnvelope<T>(payload)) return payload.data
  if (isRecord(payload) && 'data' in payload) {
    const inner = (payload as Record<string, unknown>).data
    if (inner !== undefined) return inner as T
  }
  return fallback
}

// 兼容：axios 兼容的 typed get 封装（可选使用，保证既有代码不破坏）
export async function typedGet<T>(url: string, params?: Record<string, unknown>): Promise<ApiEnvelope<T>> {
  const { data } = await apiClient.get<ApiEnvelope<T>>(url, { params })
  if (!isApiEnvelope<T>(data)) throw new TypeError(`GET ${url} envelope invalid`)
  return data
}

export async function typedPost<T, B = Record<string, unknown>>(url: string, body: B, params?: Record<string, unknown>): Promise<ApiEnvelope<T>> {
  const { data } = await apiClient.post<ApiEnvelope<T>>(url, body, { params })
  if (!isApiEnvelope<T>(data)) throw new TypeError(`POST ${url} envelope invalid`)
  return data
}

// 错误提炼 — 统一 msg 提取，供 UI 提升可读性
export function extractErrorMessage(e: unknown): string {
  if (axios.isAxiosError(e)) {
    const d = e.response?.data as Record<string, unknown> | undefined
    if (d && typeof d.msg === 'string') return d.msg
    if (d && typeof (d as Record<string, unknown>).message === 'string') return String((d as Record<string, unknown>).message)
    return e.message
  }
  if (e instanceof Error) return e.message
  return String(e)
}

// SSE last-event-id 解析 — 纯函数，便于单测
export function parseLastEventId(v: string | null | undefined): number | null {
  if (!v) return null
  const n = Number(v)
  return Number.isFinite(n) && n >= 0 ? n : null
}

// Electron/打包检测 — 供 plans.ts SSE 绝对 URL 使用
export function isElectronEnv(): boolean {
  try {
    const isFile = typeof window !== 'undefined' && window.location.protocol === 'file:'
    const hasBridge = typeof window !== 'undefined' && !!(window as unknown as { electronBridge?: unknown }).electronBridge
    return isFile || hasBridge
  } catch { return false }
}
export function getApiBase(): string {
  return resolveBaseUrl('/api/v1')
}

export default apiClient
