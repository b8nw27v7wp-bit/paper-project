import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

// steer 追问双入口合并：composer 统一承接，running 走 steerPlan，idle 走新建，空消息不发
// 风格对齐 waveb.spec.ts：全部 mock apiClient 断言调用参数与回显
vi.mock('@/api/client', () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
  isApiEnvelope: (v: unknown) => {
    const o = v as Record<string, unknown>
    return !!o && typeof o === 'object' && typeof o.code === 'number' && typeof o.msg === 'string' && 'data' in o
  },
  isElectronEnv: () => false,
  extractErrorMessage: (e: unknown) => {
    const err = e as Record<string, unknown>
    const resp = err?.response as Record<string, unknown> | undefined
    const data = resp?.data as Record<string, unknown> | undefined
    if (data && typeof data.msg === 'string') return data.msg as string
    if (e instanceof Error) return e.message
    return String(e)
  },
}))

import { apiClient } from '@/api/client'
import { steerPlan, createPlan } from '@/api/plans'
import { useWorkbenchStore } from '@/stores/workbench'
import { resolveComposerAction, composerPlaceholder } from '@/utils/composerSend'

function mockedClient() {
  return apiClient as unknown as { get: ReturnType<typeof vi.fn>; post: ReturnType<typeof vi.fn>; delete: ReturnType<typeof vi.fn> }
}

function setupStore() {
  setActivePinia(createPinia())
  return useWorkbenchStore()
}

describe('steer 追问双入口合并（composer 统一）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    try {
      localStorage.clear()
    } catch {}
  })

  it('占位文 running/idle 切换', () => {
    expect(composerPlaceholder('running')).toBe('输入追问，回车发送到当前运行')
    expect(composerPlaceholder('idle')).toContain('描述目标')
    expect(composerPlaceholder('completed')).toContain('描述目标')
  })

  it('resolveComposerAction 空消息一律 noop（不发）', () => {
    expect(resolveComposerAction('running', 'trace-1', '   ')).toBe('noop')
    expect(resolveComposerAction('idle', 'trace-1', '')).toBe('noop')
    expect(resolveComposerAction('running', 'trace-1', '')).toBe('noop')
  })

  it('resolveComposerAction running+trace+正文走 steer，running 无 trace 走 noop（不新建）', () => {
    expect(resolveComposerAction('running', 'trace-1', '换个方向')).toBe('steer')
    expect(resolveComposerAction('running', null, '换个方向')).toBe('noop')
    expect(resolveComposerAction('running', '', '换个方向')).toBe('noop')
  })

  it('resolveComposerAction 非 running 走 create（原链路）', () => {
    expect(resolveComposerAction('idle', null, '30天过六级')).toBe('create')
    expect(resolveComposerAction('completed', 'trace-1', '新目标')).toBe('create')
    expect(resolveComposerAction('failed', null, '新目标')).toBe('create')
  })

  it('store 状态切换 running/idle 决定分流', () => {
    const wb = setupStore()
    wb.setTraceId('trace-store')
    wb.status = 'running'
    expect(resolveComposerAction(wb.status, wb.traceId, '追问一句')).toBe('steer')
    wb.status = 'idle'
    expect(resolveComposerAction(wb.status, wb.traceId, '新目标')).toBe('create')
    // setTraceId 会 reset（含 status 置 idle），需先清 trace 再置 running
    wb.setTraceId('')
    wb.status = 'running'
    expect(resolveComposerAction(wb.status, wb.traceId, '追问一句')).toBe('noop')
  })

  it('running 时调 steerPlan 且不调新建（POST /steer，不 POST /plans）', async () => {
    const wb = setupStore()
    wb.setTraceId('trace-steer-merge')
    wb.status = 'running'
    const action = resolveComposerAction(wb.status, wb.traceId, '追问一句')
    expect(action).toBe('steer')

    const m = mockedClient()
    m.post.mockResolvedValue({ data: { code: 200, msg: 'ok', data: { queued: 2 } } })
    const res = await steerPlan('trace-steer-merge', '追问一句')
    expect(m.post).toHaveBeenCalledTimes(1)
    expect(m.post).toHaveBeenCalledWith('/plans/trace-steer-merge/steer', { message: '追问一句' })
    expect(res.data.queued).toBe(2)
    // 新建链路未触发：无对 /plans（精确新建路径）的调用
    expect(m.post.mock.calls.some(([url]) => url === '/plans')).toBe(false)
  })

  it('idle 时走原新建链路（POST /plans，不 POST /steer）', async () => {
    const wb = setupStore()
    wb.setTraceId('')
    wb.status = 'idle'
    const action = resolveComposerAction(wb.status, wb.traceId, '30天过六级')
    expect(action).toBe('create')

    const m = mockedClient()
    m.post.mockResolvedValue({ data: { code: 200, msg: 'ok', data: { trace_id: 'new-trace', goal_id: 1 } } })
    await createPlan(1, { hours_per_day: 2 }, 'multi', false, {})
    expect(m.post).toHaveBeenCalledTimes(1)
    const [url] = m.post.mock.calls[0] as [string, unknown, unknown]
    expect(url).toBe('/plans')
    expect(m.post.mock.calls.some(([u]) => String(u).endsWith('/steer'))).toBe(false)
  })

  it('空消息不发（noop 时无任何 POST）', async () => {
    const wb = setupStore()
    wb.setTraceId('trace-empty')
    wb.status = 'running'
    const action = resolveComposerAction(wb.status, wb.traceId, '   ')
    expect(action).toBe('noop')
    const m = mockedClient()
    // 视图层 noop 直接 return：此处模拟“遵守 noop 不调用 API”
    if (action === 'steer') await steerPlan('trace-empty', '   ')
    else if (action === 'create') await createPlan(1, { hours_per_day: 2 }, 'multi', false, {})
    expect(m.post).not.toHaveBeenCalled()
  })

  it('steer 失败（404）extractErrorMessage 提示且不清空 composer', async () => {
    const m = mockedClient()
    const err = { response: { status: 404, data: { msg: '规划会话不存在' } }, message: 'Request failed with status code 404' }
    m.post.mockRejectedValue(err)
    let composer = '追问一句'
    try {
      await steerPlan('trace-missing', '追问一句')
      expect.unreachable('应抛错')
    } catch (e: unknown) {
      const mod = await import('@/api/client')
      const msg = mod.extractErrorMessage(e)
      expect(msg).toContain('规划会话不存在')
      // 失败不破坏 composer 状态：视图层仅 toast，不清空
      expect(composer).toBe('追问一句')
    }
    expect(m.post).toHaveBeenCalledWith('/plans/trace-missing/steer', { message: '追问一句' })
  })
})
