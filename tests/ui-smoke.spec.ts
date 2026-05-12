import { expect, test } from '@playwright/test'

test('desktop workflow shell supports simplified settings, URL mode, document mode, and generation', async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear())
  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'Anki 卡片生成器' })).toBeVisible()
  await expect(page.getByText('生成工作台')).toBeVisible()
  await expect(page.getByText('Ready to build', { exact: true })).toBeVisible()
  await expect(page.getByText('把真实素材变成 Anki 复习卡')).toBeVisible()
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
  await expect(page.getByRole('button', { name: /MIMO Token Plan SGP/ })).toBeVisible()
  await expect(page.getByText('普通用户只需要选一个服务商')).toBeVisible()
  await expect(page.getByRole('button', { name: /展开更多服务商/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /MIMO Public V2.5 Pro/ })).toHaveCount(0)
  await page.getByRole('button', { name: /展开更多服务商/ }).click()
  await expect(page.getByRole('button', { name: /MIMO Public V2.5 Pro/ })).toBeVisible()
  await expect(page.getByText('测试通过代表什么？')).toBeVisible()
  await expect(page.getByRole('button', { name: /测试连接/ })).toBeVisible()
  await expect(page.getByText('记住本机模型 API Key')).toBeVisible()
  await page.getByRole('tab', { name: '语音 TTS' }).click()
  await expect(page.getByRole('heading', { name: '语音 TTS' })).toBeVisible()
  await expect(page.getByRole('button', { name: /MIMO SGP TTS/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /高级 TTS 模型和参数/ })).toBeVisible()
  await expect(page.getByText('TTS 说明与费用')).toBeVisible()
  await page.getByText('TTS 说明与费用').click()
  await expect(page.getByText('TTS 是独立配置，MIMO 语音模型也在这里选。')).toBeVisible()
  await page.getByRole('button', { name: /MIMO SGP TTS/ }).click()
  await expect(page.getByText('TTS 已开启，尚未测试')).toBeVisible()
  await expect(page.getByPlaceholder('sk-... / tp-...')).toBeVisible()
  await expect(page.getByPlaceholder('Mia / Chloe / Milo / Dean / mimo_default')).toHaveValue('Mia')
  await expect(page.getByText('记住本机 TTS API Key')).toBeVisible()
  await page.getByRole('tab', { name: '本地环境' }).click()
  await expect(page.getByText('用内置示例导出 APKG')).toBeVisible()
  await page.screenshot({ path: 'test-results/settings-tts-config.png', fullPage: true })
  await page.getByLabel('关闭设置').click()

  await page.getByRole('button', { name: /视频链接/ }).click()
  await expect(page.getByText('视频链接').first()).toBeVisible()
  await page.getByText('下载和 fallback').click()
  await expect(page.getByRole('button', { name: '只用字幕生成' })).toBeVisible()
  await expect(page.getByText('视频下载失败时自动 fallback 到字幕-only')).toBeVisible()
  await page.getByPlaceholder('https://www.youtube.com/watch?v=...').fill('https://www.youtube.com/watch?v=UV1WDNe4J5w')
  await page.getByRole('button', { name: /生成卡片/ }).click()

  await expect(page.getByText('in the mood').first()).toBeVisible()
  await expect(page.getByText("I'm not really in the mood right now.")).toBeVisible()
  await expect(page.getByText('6 张已选')).toBeVisible()
  await expect(page.getByText('演示卡片生成完成。')).toBeVisible()
  await expect(page.getByText('平均词伙评分')).toBeVisible()
  await expect(page.getByText('拒绝原因')).toBeVisible()

  await page.locator('.preference-details summary').click()
  await expect(page.getByRole('button', { name: /词典解释/ })).toBeDisabled()
  await expect(page.getByRole('button', { name: /极简复习/ })).toBeDisabled()
  await expect(page.locator('.preview-panel.template-immersive')).toBeVisible()

  await page.getByRole('button', { name: '本段停用' }).click()
  await expect(page.getByText('3 张已选')).toBeVisible()
  await page.getByRole('button', { name: '本段全选' }).click()
  await expect(page.getByText('6 张已选')).toBeVisible()

  await page.getByRole('button', { name: /文档资料/ }).click()
  await expect(page.getByText('知识点卡').first()).toBeVisible()
  await expect(page.getByText('支持 TXT、Markdown、DOCX、EPUB、PDF。扫描版 PDF 需要后续 OCR。')).toBeVisible()
  await page.getByPlaceholder('选择文档资料').fill('E:\\ANKI\\anki_live_e2e\\sample_document_notes.md')
  await page.getByRole('button', { name: /生成卡片/ }).click()
  await expect(page.getByText('spaced repetition').first()).toBeVisible()
  await expect(page.getByText('已生成浏览器演示文档卡').first()).toBeVisible()

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
  await expect(page.locator('.control-column')).toBeVisible()
  await page.setViewportSize({ width: 1440, height: 1000 })

  await page.screenshot({ path: 'test-results/ui-smoke-after-generate.png', fullPage: true })
})
