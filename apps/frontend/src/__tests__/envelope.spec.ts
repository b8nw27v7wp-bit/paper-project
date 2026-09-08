import { describe, it, expect, vi, beforeEach } from 'vitest'

// 信封解析：覆盖 api/client + types 守卫 + api/plans 纯函数
// 不依赖真实后端/PG，全部本地语义断言
import {
  isApiEnvelope,
  unwrapEnvelope,
  extractErrorMessage,
  parseLastEventId,
  isRecord,
} from '@/api/client'
import { isPaginated, isTaskArray, isApiEnvelope as isEnvelopeTypes } from '@/types'
import {
  cacheStreamTicket,
  takeStreamTicket,
  peekStreamTicket,
  makeStreamError,
  getStreamErrorStatus,
  isPlanLogArray,
} from '@/api/plans'

describe('api 信封解析（envelope）', () => {
  it('isApiEnvelope 识别标准信封', () => {
    expect(isApiEnvelope({ code: 200, msg: 'ok', data: { a: 1 } })).toBe(true)
    expect(isApiEnvelope({ code: 200, data: {} })).toBe(false)
    expect(isApiEnvelope(null)).toBe(false)
    expect(isApiEnvelope([])).toBe(false)
    expect(isEnvelopeTypes({ code: 200, msg: 'ok', data: [] })).toBe(true)
  })

  it('unwrapEnvelope 信封解包与回退', () => {
    expect(unwrapEnvelope({ code: 200, msg: 'ok', data: { x: 1 } }, { x: 0 })).toEqual({ x: 1 })
    expect(unwrapEnvelope({ data: { y: 2 } }, { y: 0 })).toEqual({ y: 2 })
    expect(unwrapEnvelope(null, 'fb')).toBe('fb')
  })

  it('isRecord / isPaginated / isTaskArray 守卫', () => {
    expect(isRecord({})).toBe(true)
    expect(isRecord([])).toBe(false)
    expect(isPaginated({ items: [], total: 0 })).toBe(true)
    expect(isPaginated({ items: 'x', total: 0 })).toBe(false)
    expect(
      isTaskArray([
        { title: '背单词', planned_start: '2026-09-01T09:00:00Z', planned_end: '2026-09-01T10:00:00Z' },
      ]),
    ).toBe(true)
    expect(isTaskArray([{ title: 1 }])).toBe(false)
  })

  it('extractErrorMessage 统一提炼中文可读信息', () => {
    expect(extractErrorMessage(new Error('boom'))).toBe('boom')
    expect(extractErrorMessage('raw')).toBe('raw')
    // axios 风格：优先取 response.data.msg
    const axiosLike = {
      isAxiosError: true,
      message: 'fallback',
      response: { data: { msg: '截止时间需 > 当前时间+1天' } },
    }
    // axios.isAxiosError 通过 isAxiosError 标记识别，此处直接走 Error 分支兜底仍可读
    expect(extractErrorMessage(axiosLike as unknown as Error)).toContain('截止时间需')
  })

  it('parseLastEventId 纯函数边界', () => {
    expect(parseLastEventId(null)).toBeNull()
    expect(parseLastEventId('')).toBeNull()
    expect(parseLastEventId('12')).toBe(12)
    expect(parseLastEventId('0')).toBe(0)
    expect(parseLastEventId('-1')).toBeNull()
    expect(parseLastEventId('abc')).toBeNull()
  })

  it('stream_ticket 一次性缓存语义', () => {
    const tid = `trace-${Date.now()}`
    expect(peekStreamTicket(tid)).toBeUndefined()
    cacheStreamTicket(tid, 'ticket-123')
    expect(peekStreamTicket(tid)).toBe('ticket-123')
    // take 消费后清空，peek 不可见
    expect(takeStreamTicket(tid)).toBe('ticket-123')
    expect(peekStreamTicket(tid)).toBeUndefined()
    expect(takeStreamTicket(tid)).toBeUndefined()
  })

  it('stream 错误状态提炼与 terminal 标记', () => {
    expect(getStreamErrorStatus(makeStreamError('stream 404', 404, true))).toBe(404)
    expect(getStreamErrorStatus(makeStreamError('stream 401', 401, true))).toBe(401)
    expect(getStreamErrorStatus(new Error('stream 404 not found'))).toBe(404)
    expect(getStreamErrorStatus(new Error('ok'))).toBeUndefined()
    const term = makeStreamError('gone', 404, true)
    expect(term.terminal).toBe(true)
    expect(term.status).toBe(404)
  })

  it('isPlanLogArray 校验 trace_id 必备', () => {
    expect(isPlanLogArray([{ trace_id: 'a', agent_name: 'planner', created_at: '' }])).toBe(true)
    expect(isPlanLogArray([{ agent_name: 'planner' }])).toBe(false)
    expect(isPlanLogArray('x')).toBe(false)
  })
})

describe('api/plans 信封回退（mock apiClient）', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.unmock('@/api/client')
  })

  it('getPlanGraph 非信封 data 回退仍可用', async () => {
    vi.doMock('@/api/client', () => ({
      apiClient: { get: vi.fn().mockResolvedValue({ data: { data: { nodes: [{ id: 'planner' }], edges: [] } } }) },
      isApiEnvelope: (v: unknown) => {
        const o = v as Record<string, unknown>
        return !!o && typeof o === 'object' && typeof o.code === 'number' && typeof o.msg === 'string' && 'data' in o
      },
      isElectronEnv: () => false,
    }))
    const mod = await import('@/api/plans')
    const res = await mod.getPlanGraph('trace-mock')
    expect(Array.isArray(res.data.nodes)).toBe(true)
    vi.doUnmock('@/api/client')
  })

  it('getPlanInspector 空回退不抛错', async () => {
    vi.doMock('@/api/client', () => ({
      apiClient: { get: vi.fn().mockResolvedValue({ data: { code: 200, msg: 'ok', data: { state: {}, logs: [], patch: {}, trace_id: 't' } } }) },
      isApiEnvelope: (v: unknown) => {
        const o = v as Record<string, unknown>
        return !!o && typeof o === 'object' && typeof o.code === 'number' && typeof o.msg === 'string' && 'data' in o
      },
      isElectronEnv: () => false,
    }))
    const mod2 = await import('@/api/plans')
    const res = await mod2.getPlanInspector('t')
    expect(res.data.trace_id).toBe('t')
    vi.doUnmock('@/api/client')
  })
})
