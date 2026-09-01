import { apiClient, isApiEnvelope, extractErrorMessage } from './client'
import type { ApiEnvelope } from '@/types'

export interface LoginPayload { username: string; password: string }
export interface RegisterPayload { username: string; password: string; major?: string }
export interface AuthUser { id: number; username: string; major?: string | null }
export interface LoginData { token: string; user: AuthUser }

export async function login(payload: LoginPayload): Promise<ApiEnvelope<LoginData>> {
  const { data } = await apiClient.post('/auth/login', payload)
  if (!isApiEnvelope<LoginData>(data)) throw new TypeError('login envelope invalid')
  try { localStorage.setItem('token', (data.data as LoginData).token); localStorage.setItem('user_id', String((data.data as LoginData).user.id)) } catch {}
  return data
}
export async function register(payload: RegisterPayload): Promise<ApiEnvelope<AuthUser>> {
  const { data } = await apiClient.post('/auth/register', payload)
  if (!isApiEnvelope<AuthUser>(data)) throw new TypeError('register envelope invalid')
  return data
}
export async function fetchMe(): Promise<ApiEnvelope<{ user_id: number }>> {
  const { data } = await apiClient.get('/auth/me')
  if (!isApiEnvelope<{ user_id: number }>(data)) throw new TypeError('me envelope invalid')
  return data
}
export async function verifyToken(): Promise<ApiEnvelope<{ user_id: number }>> {
  const { data } = await apiClient.get('/auth/verify')
  if (!isApiEnvelope<{ user_id: number }>(data)) throw new TypeError('verify envelope invalid')
  return data
}
export function logout(): void {
  try { localStorage.removeItem('token'); localStorage.removeItem('user_id') } catch {}
}
export function getToken(): string | null {
  try { return localStorage.getItem('token') } catch { return null }
}
