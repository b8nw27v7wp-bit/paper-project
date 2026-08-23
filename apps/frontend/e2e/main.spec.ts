import { test, expect } from '@playwright/test'

test('主流程: 新建目标 -> 智能规划 -> 日历可见 -> 打卡', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText('智能学习规划系统')).toBeVisible()
  await page.getByRole('button', { name: '目标' }).click()
  await expect(page.getByText('目标管理')).toBeVisible()
  // 新建目标
  await page.getByRole('button', { name: '新建目标' }).click()
  await page.getByPlaceholder('如: 30天过六级').fill('E2E 目标 ' + Date.now())
  // deadline 选明天+2天
  await page.getByRole('button', { name: '保存' }).click()
  await expect(page.getByText('已创建')).toBeVisible({ timeout: 5000 })
  // 智能规划
  await page.getByRole('button', { name: '智能规划' }).first().click()
  await page.getByRole('button', { name: '开始生成' }).click()
  await expect(page.getByText('已生成')).toBeVisible({ timeout: 15000 })
  await page.getByRole('button', { name: '查看日历' }).click()
  await expect(page.getByText('任务日历')).toBeVisible()
})
