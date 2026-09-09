import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

// Wave-2 FE 缺口补齐回归：mock apiClient（保留真实 helper）+ mock plans 流
// 覆盖 reviewer 渲染分支 / cancelled 优先 / 删除回退 / 429 倒计时读取 / settings 收敛读写
vi.mock('@/api/client', async (importOriginal) => {
  const mod = await importOriginal<typeof import('@/api/client')>()
  return {
    ...mod,
    apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn(), put: vi.fn() },
  }
})

vi.mock('@/api/plans', async (importOriginal) => {
  const mod = await importOriginal<typeof import('@/api/plans')>()
  return {
    ...mod,
    streamWorkbench: vi.fn(),
    getPlanGraph: vi.fn().mockResolvedValue({ code: 200, msg: 'ok', data: { nodes: [], edges: [], status: 'pending', trace_id: '' } }),
    getPlanInspector: vi.fn().mockResolvedValue({ code: 200, msg: 'ok', data: { state: {}, logs: [], patch: {}, trace_id: '' } }),
    getAgentManifest: vi.fn().mockResolvedValue({ code: 200, msg: 'ok', data: { name: 'm', description: '', version: '1', tools: [], entry: '', stream: '', graph: '', inspector: '', cli: '', sub_agents: [] } }),
  }
})

import { apiClient, getRetryAfterSeconds, isTooManyRequests, isServerErrorRetryable, formatRetryCountdown } from '@/api/client'
import { useWorkbenchStore } from '@/stores/workbench'
import { useSessionsStore } from '@/stores/sessions'
import { streamWorkbench } from '@/api/plans'
import { formatDoneLabel, isReviewerKind, highlightReviewScore } from '@/utils/transcript'
import type { PlanSessionItem } from '@/api/plans'
import {
  getPins, setPins, getNames, setNames, getModel, setModel,
  getDraft, setDraft, clearDraft, getHours, setHours,
  getRequireApproval, setRequireApproval,
} from '@/stores/settings'

function mockedClient() {
  return apiClient as unknown as { get: ReturnType<typeof vi.fn>; post: ReturnType<typeof vi.fn>; delete: ReturnType<typeof vi.fn> }
}

function sessionItem(trace_id: string, status: PlanSessionItem['status'] = 'running'): PlanSessionItem {
  return {
    trace_id, mode: 'multi', goal_id: 1, goal_title: '六级',
    started_at: '2026-09-01T00:00:00Z', last_event_at: '2026-09-02T00:00:00Z',
    event_count: 3, node_summary: {}, status,
  }
}

describe('Wave-2 P0 转录分支', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    try { localStorage.clear() } catch {}
  })

  it('reviewer 分支判定 + 评分高亮（thought 样式复用，不改 kind）', () => {
    expect(isReviewerKind('reviewer')).toBe(true)
    expect(isReviewerKind('thought')).toBe(false)
    expect(highlightReviewScore('复核评分 85')).toBe('**复核评分 85**')
    expect(highlightReviewScore('复核通过')).toBe('复核通过')
  })

  it('workbench thought(agent=reviewer) 产出 reviewer kind（非丢弃）', () => {
    setActivePinia(createPinia())
    const wb = useWorkbenchStore()
    wb.setTraceId('t-rev')
    const mocked = vi.mocked(streamWorkbench)
    mocked.mockImplementation((_trace, handlers) => {
      try { handlers.onThought?.({ agent: 'reviewer', text: '复核评分 90' }) } catch {}
      return { close: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), readyState: 2 } as unknown as EventSource
    })
    wb.subscribe()
    const item = wb.transcript.find((x) => x.kind === 'reviewer')
    expect(item).toBeTruthy()
    expect(item?.agent).toBe('reviewer')
    wb.unsubscribe()
  })

  it('done cancelled 优先于 approved 显示已取消', () => {
    expect(formatDoneLabel({ cancelled: true, approved: false })).toBe('已取消')
    expect(formatDoneLabel({ cancelled: true })).toBe('已取消')
  })

  it('done approved=false 非取消显示已拒绝，正常显示完成', () => {
    expect(formatDoneLabel({ approved: false })).toBe('已拒绝')
    expect(formatDoneLabel({})).toBe('完成')
    expect(formatDoneLabel({ approved: true })).toBe('完成')
  })
})

describe('Wave-2 P0 会话删除回退', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    try { localStorage.clear() } catch {}
  })

  it('删除成功调 DELETE /plans/sessions/{trace_id} 并本地过滤', async () => {
    setActivePinia(createPinia())
    const st = useSessionsStore()
    st.items = [sessionItem('t-del'), sessionItem('t-keep')]
    st.total = 2
    mockedClient().delete.mockResolvedValue({ data: { code: 200, msg: 'ok', data: { deleted: true } } })
    await st.deleteSession('t-del')
    expect(mockedClient().delete).toHaveBeenCalledWith('/plans/sessions/t-del')
    expect(st.items.map((s) => s.trace_id)).toEqual(['t-keep'])
  })

  it('后端未就绪（DELETE 抛错）回退本地 filter 照样可用', async () => {
    setActivePinia(createPinia())
    const st = useSessionsStore()
    st.items = [sessionItem('t-gone'), sessionItem('t-keep')]
    st.total = 2
    mockedClient().delete.mockRejectedValue(new Error('404'))
    await st.deleteSession('t-gone')
    expect(st.items.map((s) => s.trace_id)).toEqual(['t-keep'])
    expect(st.total).toBe(1)
  })
})

describe('Wave-2 P1-13 429/5xx', () => {
  it('429 读 Retry-After 秒数头', () => {
    const err = { response: { status: 429, headers: { 'retry-after': '120' } } }
    expect(isTooManyRequests(err)).toBe(true)
    expect(getRetryAfterSeconds(err)).toBe(120)
  })

  it('429 缺失头回退默认值 + 倒计时文案', () => {
    const err = { response: { status: 429, headers: {} } }
    expect(getRetryAfterSeconds(err, 60)).toBe(60)
    expect(formatRetryCountdown(75)).toBe('75s 后重试')
    expect(formatRetryCountdown(0)).toBe('稍后重试')
  })

  it('5xx 可重试判定（503 true / 200 false）', () => {
    expect(isServerErrorRetryable({ response: { status: 503 } })).toBe(true)
    expect(isServerErrorRetryable({ response: { status: 500 } })).toBe(true)
    expect(isServerErrorRetryable({ response: { status: 200 } })).toBe(false)
    expect(isServerErrorRetryable({ response: { status: 429 } })).toBe(false)
  })
})

describe('Wave-2 P1-15 settings 收敛读写', () => {
  beforeEach(() => {
    try { localStorage.clear() } catch {}
  })

  it('pins/names 读写（截断 500/60 语义）', () => {
    setPins(['a', 'b', ''])
    expect(getPins()).toEqual(['a', 'b'])
    setNames({ t1: ' six chars 六级冲刺 ', t2: { name: '自动名', auto: true } })
    const names = getNames()
    expect(names['t1']).toBe('six chars 六级冲刺')
    expect(names['t2']).toEqual({ name: '自动名', auto: true })
  })

  it('model/draft/hours/approval 读写（行为不变）', () => {
    expect(getModel()).toBe('auto')
    setModel('deepseek-chat')
    expect(getModel()).toBe('deepseek-chat')
    setDraft('  hello draft  ')
    expect(getDraft()).toContain('hello draft')
    clearDraft()
    setDraft('   ')
    expect(getDraft()).toBe('')
    expect(getHours()).toBeNull()
    expect(setHours(3)).toBe(3)
    expect(getHours()).toBe(3)
    expect(setHours(99)).toBeNull()
    expect(getHours()).toBe(3)
    expect(getRequireApproval()).toBe(false)
    setRequireApproval(true)
    expect(getRequireApproval()).toBe(true)
  })
})
