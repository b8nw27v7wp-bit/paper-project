import { apiClient, isApiEnvelope } from './client'
import type { ApiEnvelope } from '@/types'

export interface WindowState { x?: number; y?: number; width?: number; height?: number; isMaximized?: boolean; is_maximized?: boolean }
export interface NotifyPayload { title: string; body: string; tag?: string }

function normalizeWindowState(v: unknown): WindowState {
  const r = v as Record<string, unknown>
  if (r && typeof r.is_maximized === 'boolean' && r.isMaximized === undefined) {
    return { ...r, isMaximized: r.is_maximized as boolean } as WindowState
  }
  return v as WindowState
}
export async function fetchWindowState(): Promise<ApiEnvelope<WindowState>> {
  const { data } = await apiClient.get('/desktop/window-state')
  if (!isApiEnvelope<WindowState>(data)) throw new TypeError('desktop window-state envelope invalid')
  // 兼容后端 is_maximized 蛇形
  const d = data as ApiEnvelope<WindowState & Record<string, unknown>>
  if (d.data && typeof (d.data as Record<string, unknown>).is_maximized !== 'undefined') {
    (d.data as WindowState).isMaximized = (d.data as Record<string, unknown>).is_maximized as boolean
  }
  return data
}
export async function saveWindowState(state: WindowState): Promise<ApiEnvelope<WindowState>> {
  const payload: Record<string, unknown> = { ...state }
  // 兼容后端蛇形
  if (payload.isMaximized !== undefined && payload.is_maximized === undefined) {
    payload.is_maximized = payload.isMaximized
  }
  const { data } = await apiClient.put('/desktop/window-state', payload)
  if (!isApiEnvelope<WindowState>(data)) throw new TypeError('desktop save envelope invalid')
  return data
}
export async function sendNotify(payload: NotifyPayload): Promise<ApiEnvelope<{ delivered: boolean; entry: NotifyPayload & { id: number; created_at: string }; unread: number }>> {
  const { data } = await apiClient.post('/desktop/notify', payload)
  // 后端返回 {delivered, entry, unread}，兼容旧 {ok}
  if (isApiEnvelope<{ delivered: boolean; entry: unknown; unread: number }>(data)) return data as ApiEnvelope<{ delivered: boolean; entry: NotifyPayload & { id: number; created_at: string }; unread: number }>
  if (isApiEnvelope<{ ok: boolean }>(data)) {
    // 兼容旧前端 {ok}
    const ok = (data.data as { ok?: boolean }).ok ?? (data.data as { delivered?: boolean }).delivered ?? true
    return { code: 200, msg: 'ok', data: { delivered: !!ok, entry: { ...payload, id: Date.now(), created_at: new Date().toISOString() }, unread: 1 } } as ApiEnvelope<{ delivered: boolean; entry: NotifyPayload & { id: number; created_at: string }; unread: number }>
  }
  throw new TypeError('desktop notify envelope invalid')
}
export async function fetchNotifications(): Promise<ApiEnvelope<{ items: NotifyPayload[]; unread: number }>> {
  const { data } = await apiClient.get('/desktop/notifications')
  if (isApiEnvelope<{ items: NotifyPayload[]; unread: number }>(data)) return data as ApiEnvelope<{ items: NotifyPayload[]; unread: number }>
  // 兼容旧裸数组
  if (isApiEnvelope<NotifyPayload[]>(data) && Array.isArray((data as ApiEnvelope<NotifyPayload[]>).data)) {
    const arr = (data as ApiEnvelope<NotifyPayload[]>).data
    return { code: 200, msg: 'ok', data: { items: arr, unread: arr.length } } as ApiEnvelope<{ items: NotifyPayload[]; unread: number }>
  }
  throw new TypeError('desktop notifications envelope invalid')
}
export async function fetchDesktopConfig(): Promise<ApiEnvelope<Record<string, unknown>>> {
  const { data } = await apiClient.get('/desktop/config')
  if (!isApiEnvelope<Record<string, unknown>>(data)) throw new TypeError('desktop config envelope invalid')
  return data
}
export async function syncDesktop(payload: Record<string, unknown>): Promise<ApiEnvelope<Record<string, unknown>>> {
  const { data } = await apiClient.post('/desktop/sync', payload)
  if (!isApiEnvelope<Record<string, unknown>>(data)) throw new TypeError('desktop sync envelope invalid')
  return data
}
