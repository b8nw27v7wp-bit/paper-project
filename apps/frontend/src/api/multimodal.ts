import { apiClient, isApiEnvelope } from './client'
import type { ApiEnvelope } from '@/types'

export interface OcrCourse { course: string; time?: string; location?: string; confidence?: number; teacher?: string }
export interface OcrData { courses: OcrCourse[]; text?: string; confidence?: number }
export interface AsrData { text: string; confidence?: number }
export interface Capabilities { modalities: string[]; ocr: Record<string, unknown>; asr: Record<string, unknown>; has_key: boolean; precision: { ocr: number; asr?: number } }

export async function ocrImage(file: File): Promise<ApiEnvelope<OcrData>> {
  const fd = new FormData()
  fd.append('file', file)
  const { data } = await apiClient.post('/multimodal/ocr', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
  if (!isApiEnvelope<OcrData>(data)) throw new TypeError('ocr envelope invalid')
  return data
}

export async function asrAudio(file: File): Promise<ApiEnvelope<AsrData>> {
  const fd = new FormData()
  fd.append('file', file)
  const { data } = await apiClient.post('/multimodal/asr', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
  if (!isApiEnvelope<AsrData>(data)) throw new TypeError('asr envelope invalid')
  return data
}

export async function fetchCapabilities(): Promise<ApiEnvelope<Capabilities>> {
  const { data } = await apiClient.get('/multimodal/capabilities')
  if (!isApiEnvelope<Capabilities>(data)) throw new TypeError('capabilities envelope invalid')
  return data
}
