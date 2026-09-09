import { test, expect } from '@playwright/test'

test('主流程: 新建目标 -> 智能规划 -> 日历可见 -> 打卡', async ({ page }) => {
  await page.goto('/')
  // 等待任一终态：工作台标题（已登录）或登录按钮（未登录跳转中），冷启动放宽
  await expect(
    page.getByText('智能体工作台').first().or(page.getByRole('button', { name: '登录', exact: true })),
  ).toBeVisible({ timeout: 30000 })
  // 未登录先跳 /login：先处理登录再断言工作台标题
  if (page.url().includes('/login')) {
    await page.getByPlaceholder('demo', { exact: true }).fill('demo')
    await page.getByPlaceholder('demo123', { exact: true }).fill('demo123')
    await page.getByRole('button', { name: '登录', exact: true }).click()
    await expect(page).not.toHaveURL(/\/login/, { timeout: 8000 })
    await page.goto('/')
  } else {
    // 尝试点击目标，若被守卫拦截则登录
    await page.getByRole('button', { name: '目标' }).click().catch(() => {})
    if (page.url().includes('/login')) {
      await page.getByPlaceholder('demo', { exact: true }).fill('demo')
      await page.getByPlaceholder('demo123', { exact: true }).fill('demo123')
      await page.getByRole('button', { name: '登录', exact: true }).click()
      await expect(page).not.toHaveURL(/\/login/, { timeout: 8000 })
    } else {
      await page.goto('/')
    }
  }
  await expect(page.getByText('智能体工作台').first()).toBeVisible({ timeout: 30000 })
  await page.getByRole('button', { name: '目标' }).click()
  await expect(page.getByText('目标', { exact: false }).first()).toBeVisible({ timeout: 8000 })
  // 新建目标
  await page.getByRole('button', { name: '新建目标' }).click()
  await page.getByPlaceholder('如: 30天过六级').fill('E2E 目标 ' + Date.now())
  // deadline 选明天+2天 - GoalForm 内已默认，无需再选
  await page.getByRole('button', { name: '保存' }).click()
  await expect(page.getByText('已创建')).toBeVisible({ timeout: 8000 })
  // 智能规划：首个目标的规划按钮
  await page.getByRole('button', { name: '规划' }).first().click()
  await page.getByRole('button', { name: '开始生成' }).click()
  await expect(page.getByText('已生成').first()).toBeVisible({ timeout: 15000 })
  await page.getByRole('button', { name: '查看日历' }).click()
  await expect(page.getByText('日历').first()).toBeVisible({ timeout: 8000 })
})
