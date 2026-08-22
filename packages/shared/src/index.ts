// 共享类型 - P0占位，供前后端复用
export type HealthStatus = { status: 'ok' | 'degraded'; version: string }
export type ApiEnvelope<T> = { code: number; msg: string; data: T }
