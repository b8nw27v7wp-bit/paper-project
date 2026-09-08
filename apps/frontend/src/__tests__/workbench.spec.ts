import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

// 工作台核心逻辑：transcript/工具/审批/负荷派生，不依赖真实 LLM/SSE
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

import { useWorkbenchStore } from '@/stores/workbench'
import { streamWorkbench } from '@/api/plans'

function setupStore() {
  setActivePinia(createPinia())
  return useWorkbenchStore()
}

describe('workbench store 核心逻辑', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    try {
      localStorage.clear()
    } catch {}
  })

  it('setTraceId 切换 trace 自动 reset，ticket 拾取与清空', () => {
    const wb = setupStore()
    wb.setTraceId('trace-1')
    wb.pushUser('你好')
    expect(wb.transcript.length).toBe(1)
    expect(wb.traceId).toBe('trace-1')
    // 同 trace 不 reset
    wb.setTraceId('trace-1')
    expect(wb.transcript.length).toBe(1)
    // 切 trace 自动 reset
    wb.setTraceId('trace-2')
    expect(wb.traceId).toBe('trace-2')
    expect(wb.transcript.length).toBe(0)
    // 显式 ticket 透传
    wb.setTraceId('trace-3', 'ticket-xyz')
    expect(wb.streamTicket).toBe('ticket-xyz')
  })

  it('pushUser 追加用户消息且截断 200 条', () => {
    const wb = setupStore()
    wb.setTraceId('t-cap')
    for (let i = 0; i < 205; i++) wb.pushUser(`msg-${i}`)
    expect(wb.transcript.length).toBe(200)
    expect(wb.transcript[199].text).toBe('msg-204')
    expect(wb.transcript[199].kind).toBe('user')
  })

  it('weekLoad/dailyLoad/reallocate 派生与 inspector 过滤', () => {
    const wb = setupStore()
    wb.setTraceId('t-patch')
    wb.inspector.patch = {
      week_load: { mon: 2, tue: 3, bad: 'x' },
      daily_load: { '2026-09-01': 1.5 },
      reallocate: { from: '周一', to: '周三', hours: 2 },
    } as unknown as Record<string, unknown>
    expect(wb.weekLoadEntries).toEqual([
      ['mon', 2],
      ['tue', 3],
    ])
    expect(wb.dailyLoadEntries).toEqual([['2026-09-01', 1.5]])
    expect(wb.reallocateInfo).toContain('周一')

    wb.inspector.logs = [
      { trace_id: 't', agent_name: 'planner', created_at: '' },
      { trace_id: 't', agent_name: 'critic', created_at: '' },
    ]
    expect(wb.agentNameOptions).toEqual(['critic', 'planner'])
    wb.logAgentFilter = 'planner'
    expect(wb.filteredLogs.length).toBe(1)
    wb.logAgentFilter = ''
    expect(wb.filteredLogs.length).toBe(2)
  })

  it('审批 resolve 与待审批派生', () => {
    const wb = setupStore()
    wb.setTraceId('t-approval')
    // 直接构造审批卡（handleApproval 为内部实现，此处测派生与 resolve 契约）
    wb.transcript.push({
      id: 'a1',
      kind: 'approval',
      agent: 'planner',
      tasks: [{ title: '背单词' }],
      time: new Date().toLocaleTimeString(),
      approval: { traceId: 't-approval', tasksPreview: [{ title: '背单词' }], approveToken: 'tok-1', expiresIn: 300, status: 'pending' },
    })
    expect(wb.hasPendingApproval).toBe(true)
    expect(wb.pendingApproval?.approveToken).toBe('tok-1')
    wb.resolveApproval('tok-1', true)
    expect(wb.hasPendingApproval).toBe(false)
    expect(wb.transcript[0].approval?.status).toBe('approved')
  })

  it('selectNodeById 联动 inspector 选中态', () => {
    const wb = setupStore()
    wb.setTraceId('t-sel')
    wb.inspector.logs = [{ trace_id: 't-sel', agent_name: 'planner', input: { a: 1 }, output: { b: 2 }, created_at: '' }]
    wb.selectNodeById('planner')
    expect(wb.selectedNodeId).toBe('planner')
    expect((wb.inspector.state as Record<string, unknown>)._selectedAgent).toBe('planner')
    wb.selectNodeById('')
    expect(wb.selectedNodeId).toBe('planner')
  })

  it('subscribe 首连消费 ticket 并走 done 完成链路', async () => {
    const wb = setupStore()
    wb.setTraceId('t-sub', 'once-ticket')
    const mocked = vi.mocked(streamWorkbench)
    mocked.mockImplementation((_trace, handlers, _opts) => {
      // 模拟服务端：thought 后直接 done
      try {
        handlers.onThought?.({ agent: 'planner', text: '你好' })
        handlers.onTask?.({ task: { title: '背单词 Day1', priority: 3 } })
        handlers.onDone?.({ trace_id: 't-sub', count: 1 })
      } catch {}
      return { close: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), readyState: 2 } as unknown as EventSource
    })
    wb.subscribe()
    expect(mocked).toHaveBeenCalledTimes(1)
    expect(wb.status).toBe('completed')
    expect(wb.transcript.some((x) => x.kind === 'thought')).toBe(true)
    expect(wb.transcript.some((x) => x.kind === 'plan')).toBe(true)
    expect(wb.transcript.some((x) => x.kind === 'done')).toBe(true)
    // ticket 一次性已清空
    expect(wb.streamTicket).toBe('')
    wb.unsubscribe()
  })

  it('subscribe 404 置 failed 并给出中文提示', () => {
    const wb = setupStore()
    wb.setTraceId('t-404')
    const mocked = vi.mocked(streamWorkbench)
    mocked.mockImplementation((_trace, handlers) => {
      const err = new Error('stream 404') as Error & { status?: number; terminal?: boolean }
      err.status = 404
      err.terminal = true
      try {
        handlers.onError?.(err)
      } catch {}
      return { close: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), readyState: 2 } as unknown as EventSource
    })
    wb.subscribe()
    expect(wb.status).toBe('failed')
    expect(wb.failMessage).toContain('404')
    expect(wb.transcript.some((x) => x.kind === 'thought' && (x.text ?? '').includes('404'))).toBe(true)
  })
})
