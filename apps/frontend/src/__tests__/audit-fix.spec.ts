import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

// 审计修复回归：M1/M2/M4/L5，全部 mock，不断言后端契约
vi.mock('@/api/client', async (importOriginal) => {
  const mod = await importOriginal<typeof import('@/api/client')>()
  return {
    ...mod,
    apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn(), put: vi.fn() },
  }
})

import { apiClient, getRetryAfterSeconds } from '@/api/client'
import { normIssues } from '@/utils/transcript'
import { useSessionsStore } from '@/stores/sessions'
import { ensureForkTasks } from '@/api/plans'
import type { PlanSessionItem } from '@/api/plans'

function mockedClient() {
  return apiClient as unknown as { get: ReturnType<typeof vi.fn>; post: ReturnType<typeof vi.fn>; delete: ReturnType<typeof vi.fn> }
}

function sessionItem(trace_id: string, status: PlanSessionItem['status'] = 'running'): PlanSessionItem {
  return {
    trace_id, mode: 'multi', goal_id: 1, goal_title: 't',
    started_at: '2026-09-01T00:00:00Z', last_event_at: '2026-09-02T00:00:00Z',
    event_count: 3, node_summary: {}, status,
  }
}

describe('M1 AxiosHeaders 取值', () => {
  it('AxiosHeaders 形 {get:fn} 读 retry-after 秒数', () => {
    const err = {
      response: {
        status: 429,
        headers: { get: (k: string) => (String(k).toLowerCase() === 'retry-after' ? '45' : null) },
      },
    }
    expect(getRetryAfterSeconds(err, 60)).toBe(45)
  })

  it('纯对象括号取值兼容大小写', () => {
    expect(getRetryAfterSeconds({ response: { headers: { 'retry-after': '120' } } }, 60)).toBe(120)
    expect(getRetryAfterSeconds({ response: { headers: { 'Retry-After': '30' } } }, 60)).toBe(30)
  })

  it('AxiosHeaders 缺失头回退 fallback', () => {
    const err = { response: { status: 429, headers: { get: () => null } } }
    expect(getRetryAfterSeconds(err, 60)).toBe(60)
  })
})

describe('M2 issues 归一化', () => {
  it('string 归一化为空数组（防逐字渲染）', () => {
    expect(normIssues('oops')).toEqual([])
  })

  it('数组原样返回，缺失回空', () => {
    expect(normIssues(['a', 'b'])).toEqual(['a', 'b'])
    expect(normIssues(undefined)).toEqual([])
    expect(normIssues(null)).toEqual([])
  })
})

describe('M4 删除计数与鉴权错', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    try { localStorage.clear() } catch {}
  })

  it('删除非当页 trace 不减 total', () => {
    setActivePinia(createPinia())
    const st = useSessionsStore()
    st.items = [sessionItem('t1'), sessionItem('t2')]
    st.total = 2
    st.removeTrace('t-missing')
    expect(st.items.map((s) => s.trace_id)).toEqual(['t1', 't2'])
    expect(st.total).toBe(2)
  })

  it('403 不本地删（抛错由视图 toast）', async () => {
    setActivePinia(createPinia())
    const st = useSessionsStore()
    st.items = [sessionItem('t-del'), sessionItem('t-keep')]
    st.total = 2
    mockedClient().delete.mockRejectedValue({ response: { status: 403 }, message: 'Forbidden' })
    await expect(st.deleteSession('t-del')).rejects.toBeTruthy()
    expect(st.items.map((s) => s.trace_id)).toEqual(['t-del', 't-keep'])
    expect(st.total).toBe(2)
  })

  it('404 不本地删', async () => {
    setActivePinia(createPinia())
    const st = useSessionsStore()
    st.items = [sessionItem('t-del'), sessionItem('t-keep')]
    st.total = 5
    mockedClient().delete.mockRejectedValue({ response: { status: 404 }, message: 'Not Found' })
    await expect(st.deleteSession('t-del')).rejects.toBeTruthy()
    expect(st.items.length).toBe(2)
    expect(st.total).toBe(5)
  })

  it('网络错（无 status）回退本地删', async () => {
    setActivePinia(createPinia())
    const st = useSessionsStore()
    st.items = [sessionItem('t-gone'), sessionItem('t-keep')]
    st.total = 2
    mockedClient().delete.mockRejectedValue(new Error('Network Error'))
    await st.deleteSession('t-gone')
    expect(st.items.map((s) => s.trace_id)).toEqual(['t-keep'])
    expect(st.total).toBe(1)
  })
})

describe('L5 fork 空阻断', () => {
  it('空 tasks 抛错阻断', () => {
    expect(() => ensureForkTasks([])).toThrow('源会话暂无任务')
    expect(() => ensureForkTasks(undefined)).toThrow()
  })

  it('非空 tasks 通过', () => {
    expect(() => ensureForkTasks([{ title: '背单词' }])).not.toThrow()
  })
})
