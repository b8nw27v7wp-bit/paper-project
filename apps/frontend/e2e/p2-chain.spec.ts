import { test, expect } from '@playwright/test'

// P2-FE 关键链：登录→建目标→建计划→转录出现 task_created（全 mock，不依赖真实后端/LLM）
// 风格对齐 e2e/smoke.spec.ts：page.route 本地 mock + 信封 {code,msg,data}
// 运行：npx playwright test e2e/p2-chain.spec.ts（需 vite dev 在 5173，reuseExistingServer=true）
// 环境跑不通则只写用例不强制过（见文件尾注释）。

function jsonBody(data: unknown): { status: number; contentType: string; body: string } {
  return { status: 200, contentType: 'application/json; charset=utf-8', body: JSON.stringify(data) }
}

test('P2 关键链：登录→建目标→建计划→转录 task_created（全 mock）', async ({ page }) => {
  const now = Date.now()
  const goalTitle = `P2目标 ${now}`
  const taskTitle = `P2任务-${String(now).slice(-6)}`
  const traceId = `p2-trace-${String(now).slice(-8)}`
  const goal = {
    id: 201,
    user_id: 1,
    title: goalTitle,
    description: goalTitle,
    deadline: new Date(now + 5 * 86400000).toISOString(),
    subject: '英语',
    status: 'active',
    created_at: new Date(now).toISOString(),
  }

  await page.route('**/health', async (route) => {
    await route.fulfill(jsonBody({ code: 200, msg: 'ok', data: { status: 'ok', version: '0.1.0', services: {} } }))
  })

  await page.route('**/api/v1/**', async (route) => {
    const req = route.request()
    const u = new URL(req.url())
    const path = u.pathname
    const method = req.method()

    if (path === '/api/v1/auth/login' && method === 'POST') {
      await route.fulfill(jsonBody({ code: 200, msg: 'ok', data: { token: 'mock-token-p2', user: { id: 1, username: 'demo' } } }))
      return
    }
    if (path === '/api/v1/goals' && method === 'POST') {
      await route.fulfill(jsonBody({ code: 200, msg: 'ok', data: goal }))
      return
    }
    if (path === '/api/v1/goals' && method === 'GET') {
      await route.fulfill(jsonBody({ code: 200, msg: 'ok', data: { items: [goal], total: 1, page: 1, size: 20 } }))
      return
    }
    if (path === '/api/v1/plans' && method === 'POST') {
      await route.fulfill(
        jsonBody({
          code: 200,
          msg: 'ok',
          data: { trace_id: traceId, tasks: [{ title: taskTitle }], mentor_msg: '', citations: [], mode: 'multi', rewrites: 0 },
        }),
      )
      return
    }
    if (path === '/api/v1/plans/stream' && method === 'GET') {
      const sse =
        'id: 0\nretry: 3000\nevent: thought\ndata: {"agent":"planner","text":"P2规划开始"}\n\n' +
        `id: 1\nretry: 3000\nevent: task_created\ndata: {"task":{"title":"${taskTitle}","priority":3}}\n\n` +
        `id: 2\nretry: 3000\nevent: done\ndata: {"trace_id":"${traceId}","count":1}\n\n`
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'text/event-stream; charset=utf-8', 'Cache-Control': 'no-cache', Connection: 'keep-alive' },
        body: sse,
      })
      return
    }
    if (path === `/api/v1/plans/${traceId}/graph` && method === 'GET') {
      await route.fulfill(jsonBody({ code: 200, msg: 'ok', data: { nodes: [{ id: 'planner', name: 'planner', status: 'success', started_at: null, finished_at: null }], edges: [], status: 'completed', trace_id: traceId } }))
      return
    }
    if (path === `/api/v1/plans/${traceId}/inspector` && method === 'GET') {
      await route.fulfill(jsonBody({ code: 200, msg: 'ok', data: { state: {}, logs: [{ trace_id: traceId, agent_name: 'planner', created_at: new Date(now).toISOString() }], patch: {}, trace_id: traceId } }))
      return
    }
    if (path === '/api/v1/plans/sessions' && method === 'GET') {
      await route.fulfill(jsonBody({ code: 200, msg: 'ok', data: { items: [], total: 0, page: 1, size: 20 } }))
      return
    }
    if (path === '/api/v1/agent/tools' && method === 'GET') {
      await route.fulfill(jsonBody({ code: 200, msg: 'ok', data: [] }))
      return
    }
    if (path === '/api/v1/plans/pending-approvals' && method === 'GET') {
      await route.fulfill(jsonBody({ code: 200, msg: 'ok', data: { items: [], total: 0 } }))
      return
    }
    if (path === '/api/v1/desktop/config' && method === 'GET') {
      await route.fulfill(jsonBody({ code: 200, msg: 'ok', data: {} }))
      return
    }
    if (path.startsWith('/api/v1/stats/') && method === 'GET') {
      await route.fulfill(jsonBody({ code: 200, msg: 'ok', data: {} }))
      return
    }
    if (path === '/api/v1/llm/models' && method === 'GET') {
      await route.fulfill(jsonBody({ code: 200, msg: 'ok', data: [{ label: 'auto', value: 'auto' }] }))
      return
    }
    if (path === '/api/v1/agent/manifest' && method === 'GET') {
      await route.fulfill(jsonBody({ code: 200, msg: 'ok', data: { name: 'm', description: '', version: '1', tools: [], entry: '', stream: '', graph: '', inspector: '', cli: '', sub_agents: [] } }))
      return
    }
    await route.fulfill(jsonBody({ code: 200, msg: 'ok', data: {} }))
  })

  // 1) 登录（冷启动 vite transform 慢，首屏放宽到 30s）
  await page.goto('/login')
  await expect(page.getByText('登录').first()).toBeVisible({ timeout: 30000 })
  await page.getByPlaceholder('demo').first().fill('demo')
  await page.getByPlaceholder('demo123').first().fill('demo123')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page).not.toHaveURL(/\/login/, { timeout: 10000 })

  // 2-4) 建目标+建计划+转录 task_created：经工作台 composer 一键链
  await page.goto('/agent')
  await expect(page.getByLabel('目标输入')).toBeVisible({ timeout: 30000 })
  await page.getByLabel('目标输入').fill(`30天过六级 ${goalTitle}，每天2小时`)
  await page.getByRole('button', { name: '发送', exact: true }).click()
  // 转录出现 task_created 任务卡标题
  await expect(page.getByText(taskTitle).first()).toBeVisible({ timeout: 15000 })
})

// 注：若本地无后端/5173 端口被占，playwright webServer reuseExistingServer 会复用现存 dev；
// CI 无 dev 时 webServer 自动起 vite dev。若仍跑不通，仅保留本用例不强制过（P2-FE 打折项见回执）。
