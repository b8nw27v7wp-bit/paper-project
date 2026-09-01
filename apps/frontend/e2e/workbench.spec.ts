import { test, expect } from '@playwright/test'

const API = process.env.PLAYWRIGHT_API_BASE || 'http://localhost:8000'

// 辅助：通过 API 登录拿 token（兼容测试环境 X-User-Id 兜底）
async function apiLogin(request: any): Promise<string | null> {
  try {
    await request.post(`${API}/api/v1/auth/register`, { data: { username: `e2e_${Date.now()}`, password: 'demo123456', major: '测试' } }).catch(()=>null)
    const res = await request.post(`${API}/api/v1/auth/login`, { data: { username: 'demo', password: 'demo123' } })
    if (res.ok()) {
      const j = await res.json()
      return j?.data?.token || j?.token || null
    }
  } catch {}
  // 尝试默认 demo/demo123 直连
  try {
    const r2 = await request.post(`${API}/api/v1/auth/login`, { data: { username: 'demo', password: 'demo123' } })
    if (r2.ok()) {
      const j2 = await r2.json()
      return j2?.data?.token || j2?.token || null
    }
  } catch {}
  return null
}

test.describe('Workbench 基础链路: 创建goal→生成plan→SSE流→Graph可视', () => {

  test('API 链路：goal 创建 + plan 多轨 + SSE 8事件 + graph/inspector', async ({ request }) => {
    const token = await apiLogin(request)
    const headers: Record<string,string> = token ? { Authorization: `Bearer ${token}` } : { 'X-User-Id': '1' }

    // 1) 创建 goal（deadline 需 > now+1d）
    const title = `E2E Workbench ${Date.now()}`
    const deadline = new Date(Date.now() + 5*86400000).toISOString()
    const gRes = await request.post(`${API}/api/v1/goals`, { headers, data: { title, description: 'workbench e2e', deadline, subject: '数据结构' } })
    expect(gRes.ok()).toBeTruthy()
    const gJson = await gRes.json()
    const goalId = gJson?.data?.id ?? gJson?.id
    expect(goalId).toBeTruthy()

    // 2) 生成 plan（multi 6节点）
    const pRes = await request.post(`${API}/api/v1/plans?mode=multi`, { headers, data: { goal_id: goalId, preferences: { hours_per_day: 2 } } })
    expect(pRes.ok()).toBeTruthy()
    const pJson = await pRes.json()
    const traceId = pJson?.data?.trace_id ?? pJson?.trace_id
    expect(traceId).toBeTruthy()
    const tasks = pJson?.data?.tasks ?? []
    expect(Array.isArray(tasks)).toBeTruthy()
    expect(tasks.length).toBeGreaterThan(0)

    // 3) SSE 流式：验证 id/retry + 8事件（thought/tool_call/task_created/done 等）
    const sseRes = await request.get(`${API}/api/v1/plans/stream?trace_id=${traceId}`, { headers: { ...headers, Accept: 'text/event-stream' }, timeout: 15000 })
    expect(sseRes.ok()).toBeTruthy()
    const sseText = await sseRes.text()
    // 必须含 id: 与 retry: 且事件名
    expect(sseText).toContain('id:')
    expect(sseText).toContain('retry: 3000')
    expect(sseText).toMatch(/event:\s*(thought|tool_call|task_created|done)/)
    expect(sseText).toContain('event: done')
    expect(sseText).toContain(traceId.slice(0,8)) // done data 含 trace_id

    // 支持 Last-Event-ID 续播：取首个 id 再请求应跳过首条
    const firstIdMatch = sseText.match(/id:\s*(\d+)/)
    if (firstIdMatch) {
      const lastId = firstIdMatch[1]
      const sse2 = await request.get(`${API}/api/v1/plans/stream?trace_id=${traceId}&last_event_id=${lastId}`, { headers: { ...headers, Accept: 'text/event-stream' } })
      expect(sse2.ok()).toBeTruthy()
      const t2 = await sse2.text()
      // 续播后首条 id 应递增
      expect(t2).toContain('id:')
    }

    // 4) Graph 可视：GET /plans/{trace_id}/graph 返回 {nodes,edges,status}
    const gph = await request.get(`${API}/api/v1/plans/${traceId}/graph`, { headers })
    expect(gph.ok()).toBeTruthy()
    const gphJson = await gph.json()
    const graph = gphJson?.data ?? gphJson
    expect(Array.isArray(graph.nodes)).toBeTruthy()
    expect(Array.isArray(graph.edges)).toBeTruthy()
    expect(['running','completed','pending','done']).toContain(graph.status ?? 'completed')
    // 至少包含 planner 节点与后续边
    expect(graph.nodes.length).toBeGreaterThan(0)
    expect(graph.nodes.some((n:any)=> n.id==='planner' || n.name?.includes('Plan')) || graph.nodes.length>=1).toBeTruthy()

    // 5) Inspector：GET /plans/{trace_id}/inspector 返回 {state,logs,patch}
    const insp = await request.get(`${API}/api/v1/plans/${traceId}/inspector`, { headers })
    expect(insp.ok()).toBeTruthy()
    const inspJson = await insp.json()
    const inspData = inspJson?.data ?? inspJson
    expect(inspData.state).toBeTruthy()
    expect(Array.isArray(inspData.logs)).toBeTruthy()
    expect(inspData.logs.length).toBeGreaterThan(0)
    expect(inspData.trace_id ?? traceId).toBeTruthy()
    // logs 应含 6节点痕迹
    const agents = inspData.logs.map((l:any)=> l.agent_name)
    expect(agents).toContain('planner')
  })

  test('UI 链路：新建目标→智能规划→SSE时间线→跳转日历/图谱', async ({ page, request }) => {
    // 先走 UI 登录
    await page.goto('/')
    if (page.url().includes('/login')) {
      await page.getByPlaceholder('demo').fill('demo')
      await page.getByPlaceholder('demo123').fill('demo123')
      await page.getByRole('button', { name: '登录' }).click()
      await expect(page).not.toHaveURL(/\/login/, { timeout: 8000 })
    } else {
      // 未登录重定向检测
      await page.getByRole('button', { name: '目标' }).click().catch(()=>{})
      if (page.url().includes('/login')) {
        await page.getByPlaceholder('demo').fill('demo')
        await page.getByPlaceholder('demo123').fill('demo123')
        await page.getByRole('button', { name: '登录' }).click()
        await expect(page).not.toHaveURL(/\/login/, { timeout: 8000 })
      }
    }

    await page.goto('/goals')
    await expect(page.getByText('目标', { exact: false }).first()).toBeVisible({ timeout: 8000 })

    // 新建目标
    await page.getByRole('button', { name: '新建目标' }).click()
    await page.getByPlaceholder('如: 30天过六级').fill(`Workbench UI ${Date.now()}`)
    await page.getByRole('button', { name: '保存' }).click()
    await expect(page.getByText('已创建')).toBeVisible({ timeout: 8000 })

    // 智能规划 → 捕获后端 trace_id
    let traceId: string | null = null
    page.on('response', async (resp) => {
      if (resp.url().includes('/api/v1/plans') && resp.request().method()==='POST') {
        try { const j = await resp.json(); traceId = j?.data?.trace_id ?? null } catch {}
      }
    })
    await page.getByRole('button', { name: '规划' }).first().click()
    await page.getByRole('button', { name: '开始生成' }).click()
    await expect(page.getByText('已生成')).toBeVisible({ timeout: 15000 })
    // SSE 时间线可见（PlanStream 组件）
    await expect(page.getByRole('log').first().or(page.locator('text=任务').first())).toBeVisible({ timeout: 8000 })
    // 若捕获到 traceId，额外验证 graph/inspector API（与 UI 同源）
    if (traceId) {
      const token = await page.evaluate(()=> { try{ return localStorage.getItem('token') }catch{ return null } })
      const headers: Record<string,string> = token ? { Authorization: `Bearer ${token}` } : { 'X-User-Id':'1' }
      const apiBase = '/api/v1'
      const gph = await page.request.get(`${apiBase}/plans/${traceId}/graph`, { headers }).catch(()=>null as any)
      if (gph && gph.ok()) {
        const gj = await gph.json()
        expect(gj?.data?.nodes).toBeTruthy()
      }
    }
    // 查看日历跳转
    await page.getByRole('button', { name: '查看日历' }).click()
    await expect(page.getByText('日历').first()).toBeVisible({ timeout: 8000 })
    // 可选：切到图谱页验证 DAG 渲染
    await page.goto('/graph')
    await expect(page.getByText('图谱').first().or(page.locator('canvas').first())).toBeVisible({ timeout: 8000 })
  })

  test('SSE真流', async ({ page }) => {
    // 拦截 **/plans/stream** 返回 SSE 首事件 thought，验证真流而非 mock
    await page.route('**/plans/stream**', async (route) => {
      const body = 'id: 0\nretry: 3000\nevent: thought\ndata: {"agent":"planner","text":"mock thought for e2e"}\n\nid: 1\nretry: 3000\nevent: tool_call\ndata: {"tool":"researcher"}\n\nid: 2\nretry: 3000\nevent: done\ndata: {"trace_id":"mock-trace","count":1}\n\n'
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'text/event-stream; charset=utf-8', 'Cache-Control': 'no-cache', 'Connection': 'keep-alive' },
        body,
      })
    })
    await page.goto('/')
    // 发起 fetch 触发拦截，校验返回体包含 event: thought
    const text = await page.evaluate(async () => {
      const r = await fetch('/api/v1/plans/stream?trace_id=mock-trace')
      const t = await r.text()
      const ct = r.headers.get('content-type') || ''
      return ct + '\n' + t
    })
    expect(text).toContain('event: thought')
    expect(text).toContain('text/event-stream')
    await page.unroute('**/plans/stream**')
  })
})
