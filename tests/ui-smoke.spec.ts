import type { Locator, Page } from '@playwright/test'
import { expect, test } from '@playwright/test'

async function gotoApp(page: Page) {
  await page.goto('/', { waitUntil: 'commit' })
  await expect(page.locator('.app-shell')).toBeVisible({ timeout: 60_000 })
}

async function expectReachableInViewport(locator: Locator) {
  await locator.scrollIntoViewIfNeeded()
  const reachability = await locator.evaluate((element) => {
    const rect = element.getBoundingClientRect()
    const centerX = rect.left + rect.width / 2
    const centerY = rect.top + rect.height / 2
    const hit = document.elementFromPoint(centerX, centerY)

    return {
      hasBox: rect.width > 0 && rect.height > 0,
      inViewport: rect.left >= 0 && rect.top >= 0 && rect.right <= window.innerWidth && rect.bottom <= window.innerHeight,
      hitTarget: hit === element || element.contains(hit),
    }
  })

  expect(reachability.hasBox).toBe(true)
  expect(reachability.inViewport).toBe(true)
  expect(reachability.hitTarget).toBe(true)
}

test('public source selector exposes only video paths from current dev app', async ({ page }) => {
  test.setTimeout(60_000)

  await page.addInitScript(() => window.localStorage.clear())
  await gotoApp(page)

  const sourceSwitch = page.locator('[aria-label="素材来源"]')
  await expect(sourceSwitch).toBeVisible()
  await expect(sourceSwitch.getByRole('button')).toHaveCount(2)
  await expect(sourceSwitch.getByRole('button', { name: /本地视频/ })).toBeVisible()
  await expect(sourceSwitch.getByRole('button', { name: /视频链接/ })).toBeVisible()
  await expect(sourceSwitch.getByRole('button', { name: /文档资料/ })).toHaveCount(0)
  await expect(page.getByPlaceholder('选择文档资料')).toHaveCount(0)
})

test('compact inspector keeps source and batch controls reachable at minimum desktop size', async ({ page }) => {
  test.setTimeout(60_000)

  await page.setViewportSize({ width: 1180, height: 780 })
  await page.addInitScript(() => window.localStorage.clear())
  await gotoApp(page)

  await expect(page.locator('.desktop-workspace')).toHaveAttribute('data-responsive-mode', 'compact')
  await expect(page.locator('.control-column')).toBeHidden()

  await page.getByRole('button', { name: /素材面板/ }).click()
  await expect(page.locator('.control-column.sheet-open')).toBeVisible()

  await expectReachableInViewport(page.getByRole('button', { name: /选择素材后继续|下一步：学习设置/ }))
  await page.getByRole('button', { name: '批量 / 文件夹' }).click()
  await expectReachableInViewport(page.getByRole('button', { name: '选择视频文件夹批量添加' }))
  await expectReachableInViewport(page.getByRole('button', { name: /选择素材后继续|下一步：学习设置/ }))

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
  expect(overflow).toBe(false)
})

test('desktop workflow shell supports simplified settings, video URL mode, and generation', async ({ page }) => {
  test.setTimeout(90_000)

  await page.addInitScript(() => window.localStorage.clear())
  await gotoApp(page)

  await expect(page.getByRole('heading', { name: 'Anki 卡片生成器' })).toBeVisible()
  await expect(page.getByText('生成工作台')).toBeVisible()
  await expect(page.getByText('等待生成结果', { exact: true })).toBeVisible()
  await expect(page.getByText('审核区会在生成后展开')).toBeVisible()
  await expect(page.locator('.app-rail')).toHaveCount(0)
  const topbarBox = await page.locator('.topbar').boundingBox()
  const windowControlsBox = await page.locator('.window-controls').boundingBox()
  expect(topbarBox).not.toBeNull()
  expect(windowControlsBox).not.toBeNull()
  expect(windowControlsBox!.y).toBeGreaterThanOrEqual(topbarBox!.y)
  expect(windowControlsBox!.y + windowControlsBox!.height).toBeLessThanOrEqual(topbarBox!.y + topbarBox!.height + 1)

  await page.getByRole('button', { name: '设置', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '设置' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: '设置' })).toHaveCount(0)
  await page.getByRole('button', { name: '设置', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '设置' })).toBeVisible()
  await expect(page.getByText('选择厂商，也可以直接手动填写。')).toBeVisible()
  await expect(page.getByLabel('厂商和模型目录')).toBeVisible()
  await expect(page.getByLabel('厂商和模型目录').getByRole('button', { name: /OpenAI-compatible 模型/ })).toBeVisible()
  await expect(page.getByLabel('厂商和模型目录').getByRole('button', { name: /DeepSeek V4 Pro/ })).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'Provider' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Base URL' })).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'Model' })).toBeVisible()
  await expect(page.getByRole('button', { name: /保存模型方案/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /测试连接/ })).toBeVisible()
  await expect(page.getByLabel('API Key')).toBeVisible()
  await page.screenshot({ path: 'test-results/settings-api-directory.png', fullPage: true })
  await page.getByRole('tab', { name: '语音 TTS' }).click()
  await expect(page.getByRole('heading', { name: '语音 TTS' })).toBeVisible()
  await expect(page.getByText('选择 TTS 厂商，也可以手动接入 Speech 接口。')).toBeVisible()
  await expect(page.getByLabel('语音厂商和模型目录')).toBeVisible()
  await expect(page.getByLabel('语音厂商和模型目录').getByRole('button', { name: /^手动添加 OpenAI-compatible Speech/ })).toBeVisible()
  await page.getByLabel('语音厂商和模型目录').getByRole('button', { name: /MIMO SGP TTS/ }).click()
  await expect(page.getByText('MIMO SGP TTS').first()).toBeVisible()
  await expect(page.getByRole('combobox', { name: '语音服务' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: '语音 Base URL' })).toBeVisible()
  await expect(page.getByRole('combobox', { name: '语音模型' })).toBeVisible()
  await expect(page.getByRole('combobox', { name: '声音 / voice_id' })).toHaveValue('Mia')
  await expect(page.getByPlaceholder('可留空复用 MIMO 文本 Key')).toBeVisible()
  await expect(page.getByRole('button', { name: /保存语音方案/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /测试 TTS/ })).toBeVisible()
  await page.getByRole('button', { name: /高级：语言、采样率、码率、音量/ }).click()
  await expect(page.getByText('导出 TTS 音量：65%')).toBeVisible()
  await page.screenshot({ path: 'test-results/settings-tts-directory.png', fullPage: true })
  await page.getByRole('tab', { name: '本地环境' }).click()
  await expect(page.getByRole('button', { name: /一键修复全部可修复项/ })).toBeVisible()
  await expect(page.getByLabel('普通用户 5 步安装').getByText('用示例导出 APKG')).toBeVisible()
  await page.getByLabel('关闭设置').click()

  await page.getByRole('button', { name: /视频链接/ }).click()
  await expect(page.getByText('视频链接').first()).toBeVisible()
  await expect(page.getByRole('button', { name: /文档资料/ })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '只用字幕生成' })).toHaveCount(0)
  await expect(page.getByText('当前发布版会按视频制卡处理')).toBeVisible()
  await page.getByPlaceholder('https://www.youtube.com/watch?v=...').fill('https://www.youtube.com/watch?v=UV1WDNe4J5w')
  await page.getByRole('button', { name: '抽取学习点', exact: true }).click()

  await expect(page.getByRole('heading', { name: '学习点总览' })).toBeVisible()
  await expect(page.getByText('AI 已扫描 1/1 句字幕')).toBeVisible()
  await expect(page.getByText(/发现 1 个；推荐 1 个，候选 0 个/)).toBeVisible()
  await expect(page.getByText('in the mood').first()).toBeVisible()
  await expect(page.getByText("I'm not really in the mood right now.")).toBeVisible()
  await page.screenshot({ path: 'test-results/learning-points-layout.png', fullPage: true })
  await page.getByLabel('学习点总览').getByRole('button', { name: '生成 APKG · 1 张' }).click()
  await expect(page.getByRole('heading', { name: '准备生成 APKG · 1 张' })).toBeVisible()
  await page.screenshot({ path: 'test-results/generation-confirm-layout.png', fullPage: true })
  await page.getByRole('region', { name: '生成确认' }).getByRole('button', { name: '生成 APKG' }).click()

  await expect(page.getByText('检查卡片后导出 APKG')).toBeVisible()
  await expect(page.getByRole('button', { name: /导出可用的 6 张/ })).toBeVisible()
  await expect(page.getByLabel('卡片概览')).toContainText('已选卡片')
  await expect(page.getByLabel('卡片概览')).toContainText('可导出')
  await expect(page.getByLabel('卡片概览')).toContainText('生成总数')
  await expect(page.getByText(/演示卡片生成完成/).first()).toBeVisible()
  await expect(page.getByLabel('卡片概览').getByRole('button', { name: '高级诊断' })).toBeVisible()
  await expect(page.getByRole('button', { name: /in the mood/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /figure out/ })).toBeVisible()
  await page.screenshot({ path: 'test-results/review-export-layout.png', fullPage: true })

  await page.getByRole('button', { name: /2 学习设置/ }).click()
  await expect(page.getByRole('heading', { name: '卡片模式' })).toBeVisible()
  await expect(page.getByRole('radio', { name: /完整复读/ })).toBeVisible()
  await expect(page.getByRole('radio', { name: /快速复读/ })).toBeVisible()
  await expect(page.getByRole('radio', { name: /词典解释/ })).toHaveCount(0)
  await expect(page.getByRole('radio', { name: /极简复习/ })).toHaveCount(0)
  await page.screenshot({ path: 'test-results/learning-settings-layout.png', fullPage: true })

  await page.getByRole('button', { name: /3 审核导出/ }).click()

  const metrics = await page.evaluate(() => ({
    horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    bodyHeight: document.body.getBoundingClientRect().height,
    viewportHeight: window.innerHeight,
  }))
  expect(metrics.horizontalOverflow).toBe(false)
  expect(metrics.bodyHeight).toBeGreaterThanOrEqual(metrics.viewportHeight)

  for (const viewport of [
    { width: 1440, height: 1000 },
    { width: 1280, height: 900 },
    { width: 1180, height: 780 },
    { width: 1080, height: 720 },
  ]) {
    await page.setViewportSize(viewport)
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
    expect(overflow).toBe(false)
  }

  await page.setViewportSize({ width: 1180, height: 780 })
  await expect(page.locator('.window-controls')).toBeVisible()
  await expect(page.locator('.desktop-workspace')).toHaveAttribute('data-responsive-mode', 'compact')
  await page.getByRole('button', { name: /素材面板/ }).click()
  await expect(page.locator('.control-column.sheet-open')).toBeVisible()
  await expectReachableInViewport(page.getByRole('button', { name: /导出可用的 6 张/ }))
  await page.getByRole('button', { name: /关闭面板/ }).click()
  await page.setViewportSize({ width: 1440, height: 1000 })

  await page.screenshot({ path: 'test-results/ui-smoke-after-generate.png', fullPage: true })
})
