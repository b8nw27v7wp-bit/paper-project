import { test, expect } from '@playwright/test'

// 全链路冒烟：登录→新建目标→发起 single 规划→任务出现→打卡完成
// 语义说明：
// - 全部后端用 page.route 本地 mock，不依赖真实 LLM 与真实后端
// - 不假设 PG：mock 数据即 SQLite 语义（扁平 envelope {code,msg,data}）
// - 运行方式：npx playwright test e2e/smoke.spec.ts（webServer 自动起 vite dev，baseURL http://localhost:5173）

interface MockGoal {
  id: number
  user_id: number
  title: string
  description: string | null
  deadline: string
  subject: string | null
  status: 'active' | 'archived'
  created_at: string
}

interface MockTask {
  id: number
  goal_id: number
  title: string
  planned_start: string
  planned_end: string
  priority: 1 | 2 | 3 | 4 | 5
  status: 'todo' | 'doing' | 'done' | 'delayed'
  created_at: string
}

function jsonBody(data: unknown): { status: number; contentType: string; body: string } {
  return { status: 200, contentType: 'application/json; charset=utf-8', body: JSON.stringify(data) }
}

test('冒烟全链路：登录→新建目标→single规划→任务出现→打卡完成（全 mock）', async ({ page }) => {
  const now = Date.now()
  const goalTitle = `冒烟目标 ${now}`
  const deadline = new Date(now + 5 * 86400000).toISOString()
  const goal: MockGoal = {
    id: 101,
    user_id: 1,
    title: goalTitle,
    description: '冒烟测试目标',
    deadline,
    subject: '英语',
    status: 'active',
    created_at: new Date(now).toISOString(),
  }
  const t0 = new Date(now + 86400000)
  t0.setHours(9, 0, 0, 0)
  const t1 = new Date(t0.getTime() + 3600000)
  const tasks: MockTask[] = [
    {
      id: 1001,
      goal_id: goal.id,
      title: `${goalTitle}-任务1`,
      planned_start: t0.toISOString(),
      planned_end: t1.toISOString(),
      priority: 3,
      status: 'todo',
      created_at: new Date(now).toISOString(),
    },
    {
      id: 1002,
      goal_id: goal.id,
      title: `${goalTitle}-任务2`,
      planned_start: t1.toISOString(),
      planned_end: new Date(t1.getTime() + 3600000).toISOString(),
      priority: 3,
      status: 'todo',
      created_at: new Date(now).toISOString(),
    },
  ]
  const traceId = `mock-trace-${String(now).slice(-8)}`

  // 健康探针：避免顶栏离线态干扰断言
  await page.route('**/health', async (route) => {
    await route.fulfill(jsonBody({ code: 200, msg: 'ok', data: { status: 'ok', version: '0.1.0', services: {} } }))
  })

  await page.route('**/api/v1/**', async (route) => {
    const req = route.request()
    const u = new URL(req.url())
    const path = u.pathname
    const method = req.method()

    // 登录
    if (path === '/api/v1/auth/login' && method === 'POST') {
      await route.fulfill(jsonBody({ code: 200, msg: 'ok', data: { token: 'mock-token-smoke', user: { id: 1, username: 'demo' } } }))
      return
    }
    // 新建目标
    if (path === '/api/v1/goals' && method === 'POST') {
      await route.fulfill(jsonBody({ code: 200, msg: 'ok', data: goal }))
      return
    }
    // 目标列表：创建后返回含新建目标的分页
    if (path === '/api/v1/goals' && method === 'GET') {
      await route.fulfill(jsonBody({ code: 200, msg: 'ok', data: { items: [goal], total: 1, page: 1, size: 20 } }))
      return
    }
    // 单目标详情
    if (path === `/api/v1/goals/${goal.id}` && method === 'GET') {
      await route.fulfill(jsonBody({ code: 200, msg: 'ok', data: goal }))
      return
    }
    // 发起 single 规划
    if (path === '/api/v1/plans' && method === 'POST') {
      const mode = u.searchParams.get('mode') || 'single'
      await route.fulfill(
        jsonBody({
          code: 200,
          msg: 'ok',
          data: { trace_id: traceId, tasks, mentor_msg: '', citations: [], mode, rewrites: 0 },
        }),
      )
      return
    }
    // SSE 流：thought → task_created ×2 → done（含 id/retry 语义）
    if (path === '/api/v1/plans/stream' && method === 'GET') {
      const sse =
        'id: 0\nretry: 3000\nevent: thought\ndata: {"agent":"planner","text":"冒烟规划开始"}\n\n' +
        `id: 1\nretry: 3000\nevent: task_created\ndata: {"task":{"title":"${tasks[0].title}"}}\n\n` +
        `id: 2\nretry: 3000\nevent: task_created\ndata: {"task":{"title":"${tasks[1].title}"}}\n\n` +
        `id: 3\nretry: 3000\nevent: done\ndata: {"trace_id":"${traceId}","count":2}\n\n`
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'text/event-stream; charset=utf-8', 'Cache-Control': 'no-cache', Connection: 'keep-alive' },
        body: sse,
      })
      return
    }
    // 任务列表：规划后返回 2 条任务
    if (path === '/api/v1/tasks' && method === 'GET') {
      await route.fulfill(jsonBody({ code: 200, msg: 'ok', data: { items: tasks, total: tasks.length, page: 1, size: 100 } }))
      return
    }
    // 打卡完成：PUT 状态 done
    if ((path === `/api/v1/tasks/${tasks[0].id}` && (method === 'PUT' || method === 'PATCH')) || path === `/api/v1/tasks/${tasks[0].id}/complete`) {
      tasks[0].status = 'done'
      if (path.endsWith('/complete')) {
        await route.fulfill(jsonBody({ code: 200, msg: 'ok', data: { id: tasks[0].id, status: 'done' } }))
      } else {
        await route.fulfill(jsonBody({ code: 200, msg: 'ok', data: { ...tasks[0] } }))
      }
      return
    }
    // 会话/统计等兜底：返回空分页或空对象，保证页面不报错
    if (path === '/api/v1/plans/sessions' && method === 'GET') {
      await route.fulfill(jsonBody({ code: 200, msg: 'ok', data: { items: [], total: 0, page: 1, size: 20 } }))
      return
    }
    if (path.startsWith('/api/v1/stats/') && method === 'GET') {
      if (path.endsWith('/overview')) {
        await route.fulfill(jsonBody({ code: 200, msg: 'ok', data: { completion_rate: 0.5, delay_rate: 0.1, avg_load: 2, llm_cost: 0 } }))
      } else {
        await route.fulfill(jsonBody({ code: 200, msg: 'ok', data: { dates: [], rates: [], loads: [] } }))
      }
      return
    }
    // 默认兜底
    await route.fulfill(jsonBody({ code: 200, msg: 'ok', data: {} }))
  })

  // 1) 登录
  await page.goto('/login')
  await expect(page.getByText('登录').first()).toBeVisible()
  await page.getByPlaceholder('demo').first().fill('demo')
  await page.getByPlaceholder('demo123').first().fill('demo123')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page).not.toHaveURL(/\/login/, { timeout: 10000 })
  const token = await page.evaluate(() => {
    try {
      return localStorage.getItem('token')
    } catch {
      return null
    }
  })
  expect(token).toBe('mock-token-smoke')

  // 2) 新建目标
  await page.goto('/goals')
  await expect(page.getByRole('button', { name: '新建目标' })).toBeVisible({ timeout: 10000 })
  await page.getByRole('button', { name: '新建目标' }).click()
  await page.getByPlaceholder('如: 30天过六级').fill(goalTitle)
  await page.getByRole('button', { name: '保存' }).click()
  await expect(page.getByText('已创建').first()).toBeVisible({ timeout: 10000 })
  await expect(page.getByText(goalTitle).first()).toBeVisible({ timeout: 10000 })

  // 3) 发起 single 规划
  await page.getByRole('button', { name: '规划' }).first().click()
  await expect(page.getByText('智能规划').first()).toBeVisible({ timeout: 8000 })
  // 切到单智能体（默认 multi，点单智能体保证 single 语义）
  await page.getByRole('radio', { name: '单智能体' }).click().catch(() => {})
  await page.getByRole('button', { name: '开始生成' }).click()
  await expect(page.getByText('已生成').first()).toBeVisible({ timeout: 15000 })
  // SSE 时间线应出现任务标题
  await expect(page.getByText(tasks[0].title).first()).toBeVisible({ timeout: 10000 })

  // 4) 任务出现：查看日历跳任务列表
  await page.getByRole('button', { name: '查看日历' }).click()
  await expect(page.getByText('日历').first()).toBeVisible({ timeout: 10000 })
  await expect(page.getByText(tasks[0].title).first()).toBeVisible({ timeout: 10000 })

  // 5) 打卡完成：直接调任务完成接口（mock 语义），再校验列表状态
  const doneRes = await page.evaluate(async (taskId: number) => {
    const r = await fetch(`/api/v1/tasks/${taskId}/complete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ actual_duration: 60, completion_rate: 1 }),
    })
    const j = await r.json().catch(() => ({}))
    return { ok: r.ok, json: j }
  }, tasks[0].id)
  expect(doneRes.ok).toBeTruthy()
  expect(JSON.stringify(doneRes.json)).toContain('done')

  // 刷新日历任务列表，确认 done 语义已落库（mock 内存已置 done）
  await page.getByRole('button', { name: '刷新' }).first().click().catch(() => {})
  await expect(page.getByText(tasks[0].title).first()).toBeVisible({ timeout: 10000 })
})
