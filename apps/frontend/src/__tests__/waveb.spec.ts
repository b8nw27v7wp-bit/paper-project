import { describe, it, expect, vi, beforeEach } from 'vitest'

// Wave-B：B2 规则 / B3 追问 / B4 复刻 / B6 工具详情，全部 mock apiClient 断言调用参数与回显
vi.mock('@/api/client', () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
  isApiEnvelope: (v: unknown) => {
    const o = v as Record<string, unknown>
    return !!o && typeof o === 'object' && typeof o.code === 'number' && typeof o.msg === 'string' && 'data' in o
  },
  isElectronEnv: () => false,
}))

import { apiClient } from '@/api/client'
import {
  createApproveRule,
  listApproveRules,
  deleteApproveRule,
  getPlanLast,
  steerPlan,
  listAgentTools,
} from '@/api/plans'

function mockedClient() {
  return apiClient as unknown as { get: ReturnType<typeof vi.fn>; post: ReturnType<typeof vi.fn>; delete: ReturnType<typeof vi.fn> }
}

describe('Wave-B agent 新能力 API', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('B2 createApproveRule POST 参数与回显（含 justification）', async () => {
    const m = mockedClient()
    m.post.mockResolvedValue({ data: { code: 200, msg: 'ok', data: { trace_id: 't1', prefix: 'write_tasks', decision: 'Allow', justification: '测试' } } })
    const res = await createApproveRule('t1', { prefix: 'write_tasks', decision: 'Allow', justification: '测试' })
    expect(m.post).toHaveBeenCalledWith('/plans/t1/approve-rule', { prefix: 'write_tasks', decision: 'Allow', justification: '测试' })
    expect(res.data.prefix).toBe('write_tasks')
    expect(res.data.decision).toBe('Allow')
    expect(res.data.justification).toBe('测试')
  })

  it('B2 createApproveRule 空 justification 省略不传', async () => {
    const m = mockedClient()
    m.post.mockResolvedValue({ data: { code: 200, msg: 'ok', data: { trace_id: 't2', prefix: 'mcp', decision: 'Prompt' } } })
    await createApproveRule('t2', { prefix: 'mcp', decision: 'Prompt', justification: '   ' })
    expect(m.post).toHaveBeenCalledWith('/plans/t2/approve-rule', { prefix: 'mcp', decision: 'Prompt' })
  })

  it('B2 listApproveRules GET 回显 rules/total', async () => {
    const m = mockedClient()
    m.get.mockResolvedValue({ data: { code: 200, msg: 'ok', data: { rules: [{ prefix: 'a', decision: 'Allow', justification: null }], total: 1 } } })
    const res = await listApproveRules()
    expect(m.get).toHaveBeenCalledWith('/plans/approve-rules')
    expect(res.data.total).toBe(1)
    expect(res.data.rules[0]?.prefix).toBe('a')
  })

  it('B2 deleteApproveRule DELETE body 传 prefix 并回显 deleted', async () => {
    const m = mockedClient()
    m.delete.mockResolvedValue({ data: { code: 200, msg: 'ok', data: { deleted: true } } })
    const res = await deleteApproveRule('write_tasks')
    expect(m.delete).toHaveBeenCalledWith('/plans/approve-rules', { data: { prefix: 'write_tasks' } })
    expect(res.data.deleted).toBe(true)
  })

  it('B3 steerPlan POST message（截断 2000）并回显 queued', async () => {
    const m = mockedClient()
    m.post.mockResolvedValue({ data: { code: 200, msg: 'ok', data: { queued: 1 } } })
    const long = 'x'.repeat(2500)
    const res = await steerPlan('trace-steer', long)
    expect(m.post).toHaveBeenCalledTimes(1)
    const [url, body] = m.post.mock.calls[0] as [string, { message: string }]
    expect(url).toBe('/plans/trace-steer/steer')
    expect(body.message.length).toBe(2000)
    expect(res.data.queued).toBe(1)
  })

  it('B4 getPlanLast GET 参数与 tasks/done/count 回显', async () => {
    const m = mockedClient()
    const tasks = [{ title: '背单词 Day1', priority: 3 }]
    m.get.mockResolvedValue({ data: { code: 200, msg: 'ok', data: { trace_id: 't-last', tasks, done: { count: 1 }, count: 1 } } })
    const res = await getPlanLast('t-last')
    expect(m.get).toHaveBeenCalledWith('/plans/t-last/last')
    expect(res.data.tasks.length).toBe(1)
    expect(res.data.tasks[0]?.title).toBe('背单词 Day1')
    expect(res.data.count).toBe(1)
  })

  it('B6 listAgentTools 数组回显 description+schema', async () => {
    const m = mockedClient()
    m.get.mockResolvedValue({
      data: { code: 200, msg: 'ok', data: [{ name: 'rag_search', label: '检索', description: '向量检索', schema: { type: 'object', properties: {}, required: [] } }] },
    })
    const res = await listAgentTools()
    expect(m.get).toHaveBeenCalledWith('/agent/tools')
    expect(res.data[0]?.name).toBe('rag_search')
    expect(res.data[0]?.description).toBe('向量检索')
    expect((res.data[0]?.schema as Record<string, unknown>)?.type).toBe('object')
  })

  it('B6 listAgentTools 兼容 {tools:[...]} 包裹', async () => {
    const m = mockedClient()
    m.get.mockResolvedValue({ data: { code: 200, msg: 'ok', data: { tools: [{ name: 'memory_search', label: '记忆' }] } } })
    const res = await listAgentTools()
    expect(res.data.length).toBe(1)
    expect(res.data[0]?.name).toBe('memory_search')
  })
})
