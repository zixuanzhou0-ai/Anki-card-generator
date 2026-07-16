import type { Locator, Page } from '@playwright/test'
import { expect, test } from '@playwright/test'

async function gotoApp(page: Page) {
  await page.goto('/', { waitUntil: 'commit', timeout: 120_000 })
  await expect(page.locator('.app-shell')).toBeVisible({ timeout: 120_000 })
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
      inViewport:
        rect.left >= 0 && rect.top >= 0 && rect.right <= window.innerWidth && rect.bottom <= window.innerHeight,
      hitTarget: hit === element || element.contains(hit),
    }
  })

  expect(reachability.hasBox).toBe(true)
  expect(reachability.inViewport).toBe(true)
  expect(reachability.hitTarget).toBe(true)
}

test('public source selector exposes only video paths from current dev app', async ({ page }) => {
  test.setTimeout(120_000)

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
  test.setTimeout(120_000)

  await page.setViewportSize({ width: 1180, height: 780 })
  await page.addInitScript(() => window.localStorage.clear())
  await gotoApp(page)

  await expect(page.locator('.desktop-workspace')).toHaveAttribute('data-responsive-mode', 'compact')
  await expect(page.locator('.control-column')).toBeHidden()

  const inspectorToggle = page.getByRole('button', { name: '流程', exact: true })
  await inspectorToggle.click()
  await expect(page.locator('.desktop-workspace.inspector-sheet .workflow-rail')).toBeVisible()
  await expect(page.getByRole('navigation', { name: '三步制卡流程' })).toBeVisible()

  await page.keyboard.press('Escape')
  await expect(page.locator('.desktop-workspace.inspector-sheet')).toHaveCount(0)
  await expect(inspectorToggle).toBeFocused()

  await page.getByRole('button', { name: '批量 / 文件夹' }).click()
  await expectReachableInViewport(page.getByRole('button', { name: '选择视频文件夹批量添加' }))
  await expectReachableInViewport(page.getByRole('button', { name: /选择素材后继续|分析素材/ }))

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  )
  expect(overflow).toBe(false)
})

test('desktop workflow shell supports simplified settings, video URL mode, and generation', async ({ page }) => {
  test.setTimeout(120_000)

  await page.addInitScript(() => {
    window.localStorage.clear()

    const hashProfile = (values: string[]) => {
      const normalized = values.join('|')
      let hash = 2166136261
      for (let index = 0; index < normalized.length; index += 1) {
        hash ^= normalized.charCodeAt(index)
        hash = Math.imul(hash, 16777619)
      }
      return (hash >>> 0).toString(36)
    }
    const normalizeEndpoint = (value: string) => {
      const parsed = new URL(value.trim())
      parsed.username = ''
      parsed.password = ''
      parsed.search = ''
      parsed.hash = ''
      return parsed.toString().replace(/\/+$/, '')
    }
    const hash32 = (value: string, seed: number) => {
      let hash = seed >>> 0
      for (let index = 0; index < value.length; index += 1) {
        hash ^= value.charCodeAt(index)
        hash = Math.imul(hash, 16777619)
        hash ^= hash >>> 13
      }
      return (hash >>> 0).toString(36).padStart(7, '0')
    }
    const stableFingerprint = (kind: 'model' | 'tts', fields: readonly unknown[]) => {
      const serialized = JSON.stringify(fields)
      return `${kind}:v1:${hash32(serialized, 2166136261)}${hash32(serialized, 2654435769)}`
    }
    const verified = (verificationFingerprint: string) => ({
      verification_schema_version: 1,
      credential_revision: 0,
      verification_records: [
        { status: 'passed', verificationFingerprint, credentialRevision: 0, checkedAt: Date.now(), latencyMs: 1 },
      ],
    })
    const profileId = (provider: string, baseUrl: string, model: string) =>
      `api_${hashProfile([provider, baseUrl.trim().replace(/\/+$/, ''), model.trim()])}`
    const ttsProfileId = (provider: string, baseUrl: string, model: string, voice: string) =>
      `tts_${hashProfile([provider, baseUrl.trim().replace(/\/+$/, ''), model.trim(), voice.trim()])}`
    const modelFingerprint = (provider: string, baseUrl: string, model: string, auth: string) =>
      stableFingerprint('model', [provider.trim().toLowerCase(), normalizeEndpoint(baseUrl), model.trim(), auth])
    const ttsFingerprint = (
      provider: string,
      baseUrl: string,
      model: string,
      voice: string,
      language: string,
      sampleRate: number,
      bitRate: number,
      credentialSource: string,
    ) =>
      stableFingerprint('tts', [
        true,
        provider.trim().toLowerCase(),
        normalizeEndpoint(baseUrl),
        model.trim(),
        voice.trim(),
        language,
        sampleRate,
        bitRate,
        credentialSource,
      ])

    const baseUrl = 'https://aiplatform.googleapis.com'
    window.localStorage.setItem(
      'anki-card-generator.api-profiles.v2',
      JSON.stringify([
        {
          auth: 'gcloud',
          base_url: baseUrl,
          capabilities: ['structured_json', 'long_context', 'cheap_batch'],
          has_api_key: false,
          id: profileId('gemini-vertex', baseUrl, 'gemini-3.5-flash'),
          label: 'Gemini 3.5 Flash Vertex',
          ...verified(modelFingerprint('gemini-vertex', baseUrl, 'gemini-3.5-flash', 'gcloud')),
          model: 'gemini-3.5-flash',
          provider: 'gemini-vertex',
          updated_at: '2026-06-27T00:00:00.000Z',
        },
        {
          auth: 'gcloud',
          base_url: baseUrl,
          capabilities: ['structured_json', 'long_context'],
          has_api_key: false,
          id: profileId('gemini-vertex', baseUrl, 'gemini-3.1-pro-preview'),
          label: 'Gemini 3.1 Pro Preview Vertex',
          ...verified(modelFingerprint('gemini-vertex', baseUrl, 'gemini-3.1-pro-preview', 'gcloud')),
          model: 'gemini-3.1-pro-preview',
          provider: 'gemini-vertex',
          updated_at: '2026-06-27T00:00:00.000Z',
        },
      ]),
    )
    window.localStorage.setItem(
      'anki-card-generator.tts-profiles.v2',
      JSON.stringify([
        {
          auth: 'gcloud',
          base_url: baseUrl,
          bit_rate: 128000,
          enabled: true,
          has_api_key: false,
          id: ttsProfileId('gemini-vertex', baseUrl, 'gemini-3.1-flash-tts-preview', 'Kore'),
          label: 'Gemini 3.1 Flash TTS Vertex',
          language: 'auto',
          ...verified(
            ttsFingerprint(
              'gemini-vertex',
              baseUrl,
              'gemini-3.1-flash-tts-preview',
              'Kore',
              'auto',
              24000,
              128000,
              'gcloud',
            ),
          ),
          model: 'gemini-3.1-flash-tts-preview',
          output_volume: 0.65,
          provider: 'gemini-vertex',
          sample_rate: 24000,
          updated_at: '2026-06-27T00:00:00.000Z',
          voice: 'Kore',
        },
      ]),
    )
  })
  await gotoApp(page)

  await expect(page.getByRole('heading', { name: 'Anki 卡片生成器' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '添加学习素材' })).toBeVisible()
  await expect(page.locator('.app-rail')).toHaveCount(0)
  await expect(page.getByRole('navigation', { name: '三步制卡流程' })).toBeVisible()
  await expect(page.locator('.workflow-rail-step')).toHaveCount(3)
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
  await expect(page.getByRole('button', { name: '简单', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByText('选择一个模型方案。')).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'Provider' })).toBeHidden()
  await page.getByRole('button', { name: '高级', exact: true }).click()
  await expect(page.getByText('选择厂商，也可以直接手动填写。')).toBeVisible()
  await expect(page.getByLabel('厂商和模型目录')).toBeVisible()
  await expect(page.getByLabel('厂商和模型目录').getByRole('button', { name: /OpenAI-compatible 模型/ })).toBeVisible()
  await expect(page.getByLabel('厂商和模型目录').getByRole('button', { name: /DeepSeek V4 Pro/ })).toBeVisible()
  await expect(
    page
      .getByLabel('厂商和模型目录')
      .getByRole('button', { name: /Gemini 3.5 Flash/ })
      .first(),
  ).toBeVisible()
  const savedModelCards = page.locator('.settings-catalog-item.saved')
  await expect(savedModelCards).toHaveCount(2)
  const activeSavedModel = savedModelCards.filter({ hasText: 'Gemini 3.5 Flash Vertex' }).first()
  const inactiveSavedModel = savedModelCards.filter({ hasText: 'Gemini 3.1 Pro Preview Vertex' }).first()
  await expect(activeSavedModel).toHaveClass(/selected/)
  await expect(page.getByLabel('厂商和模型目录').locator('.settings-catalog-item.selected')).toHaveCount(1)
  await expect(inactiveSavedModel).not.toHaveClass(/selected/)

  const savedModelVisuals = await inactiveSavedModel.evaluate((element) => {
    const styles = window.getComputedStyle(element)
    return { backgroundColor: styles.backgroundColor, boxShadow: styles.boxShadow }
  })
  const activeModelVisuals = await activeSavedModel.evaluate((element) => {
    const styles = window.getComputedStyle(element)
    return { backgroundColor: styles.backgroundColor, boxShadow: styles.boxShadow }
  })
  expect(savedModelVisuals.backgroundColor).not.toMatch(/52,\s*199,\s*89/)
  expect(savedModelVisuals.boxShadow).not.toMatch(/0,\s*102,\s*204/)
  expect(activeModelVisuals.backgroundColor).toMatch(/245,\s*249,\s*255/)
  expect(activeModelVisuals.boxShadow).toMatch(/0,\s*102,\s*204/)
  await expect(page.getByRole('combobox', { name: 'Provider' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Base URL' })).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'Model' })).toBeVisible()
  await expect(page.getByRole('button', { name: /保存模型方案/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /测试连接/ })).toBeVisible()
  await expect(page.getByText('Vertex 授权')).toBeVisible()
  await expect(page.getByText('使用本机 gcloud OAuth', { exact: true })).toBeVisible()
  await expect(page.getByLabel('API Key')).toHaveCount(0)
  await page.screenshot({ path: 'test-results/settings-api-directory.png', fullPage: true })
  await page.screenshot({ path: 'test-results/settings-model-api-v096.png', fullPage: true })
  await page.getByRole('tab', { name: '语音 TTS' }).click()
  await expect(page.getByRole('heading', { name: '语音 TTS' })).toBeVisible()
  await expect(page.getByText('选择 TTS 厂商，也可以手动接入 Speech 接口。')).toBeVisible()
  await expect(page.getByLabel('语音厂商和模型目录')).toBeVisible()
  await expect(
    page.getByLabel('语音厂商和模型目录').getByRole('button', { name: /^手动添加 OpenAI-compatible Speech/ }),
  ).toBeVisible()
  await page
    .getByLabel('语音厂商和模型目录')
    .getByRole('button', { name: /MIMO SGP TTS/ })
    .click()
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
  await page
    .getByLabel('语音厂商和模型目录')
    .getByRole('button', { name: /Gemini 3.1 Flash TTS Vertex/ })
    .click()
  await page.getByRole('tab', { name: '本地环境' }).click()
  await expect(page.getByRole('button', { name: /一键修复全部可修复项/ })).toBeVisible()
  await expect(page.getByLabel('普通用户 5 步安装').getByText('用示例导出 APKG')).toBeVisible()
  await page.getByRole('tab', { name: '关于 / 版权' }).click()
  await expect(page.getByText('版权所有 © 2026 Zixuan Zhou。保留所有权利。')).toBeVisible()
  await expect(page.getByRole('button', { name: /GitHub 仓库/ })).toBeVisible()
  await page.screenshot({ path: 'test-results/settings-about-copyright.png', fullPage: true })
  page.once('dialog', (confirmDialog) => confirmDialog.accept())
  await page.getByLabel('关闭设置').click()

  await page.getByRole('button', { name: /视频链接/ }).click()
  await expect(page.getByText('视频链接').first()).toBeVisible()
  await expect(page.getByRole('button', { name: /文档资料/ })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '只用字幕生成' })).toHaveCount(0)
  await expect(page.getByText('当前发布版会按视频制卡处理')).toBeVisible()
  await page.getByPlaceholder('https://www.youtube.com/watch?v=...').fill('https://www.youtube.com/watch?v=UV1WDNe4J5w')
  const environmentPreparation = page.getByRole('button', { name: /还需完成 \d+ 项准备/ })
  if (await environmentPreparation.isVisible()) {
    await environmentPreparation.click()
  }
  await page.getByRole('button', { name: '分析素材', exact: true }).click()

  await expect(page.getByRole('heading', { name: '选择值得复习的内容' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '学习点总览' })).toBeVisible()
  await expect(page.getByText('AI 已扫描 1/1 句字幕')).toBeVisible()
  await expect(page.getByText(/发现 1 个；推荐 1 个，候选 0 个/)).toBeVisible()
  await expect(page.getByText('in the mood').first()).toBeVisible()
  await expect(page.getByText("I'm not really in the mood right now.")).toBeVisible()
  await page.screenshot({ path: 'test-results/learning-points-layout.png', fullPage: true })
  await page
    .getByLabel('学习点总览')
    .getByRole('button', { name: /生成选中的 1 张/ })
    .click()

  await expect(page.getByRole('heading', { name: '生成并导入' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '审核导出' })).toBeVisible()
  const exportButton = page.getByRole('button', { name: /导出可用的 [1-9]\d* 张/ }).first()
  await expect(exportButton).toBeVisible()
  await expect(page.getByLabel('卡片概览')).toContainText('已选卡片')
  await expect(page.getByLabel('卡片概览')).toContainText('可导出')
  await expect(page.getByLabel('卡片概览')).toContainText('生成总数')
  await expect(page.getByText(/演示卡片生成完成/).first()).toBeVisible()
  await expect(page.getByLabel('卡片概览').getByRole('button', { name: '高级诊断' })).toBeVisible()
  await expect(page.getByRole('button', { name: /in the mood/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /figure out/ })).toBeVisible()
  await page.screenshot({ path: 'test-results/review-export-layout.png', fullPage: true })

  await page.getByRole('button', { name: /添加素材/ }).click()
  await page.getByLabel('学习偏好设置').locator('summary').click()
  await expect(page.getByRole('heading', { name: '卡片模式' })).toBeVisible()
  await expect(page.getByRole('radio', { name: /完整复读/ })).toBeVisible()
  await expect(page.getByRole('radio', { name: /快速复读/ })).toBeVisible()
  await expect(page.getByRole('radio', { name: /词典解释/ })).toHaveCount(0)
  await expect(page.getByRole('radio', { name: /极简复习/ })).toHaveCount(0)
  await page.screenshot({ path: 'test-results/learning-settings-layout.png', fullPage: true })

  await page.getByRole('button', { name: /生成并导入/ }).click()

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
  ]) {
    await page.setViewportSize(viewport)
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    )
    expect(overflow).toBe(false)
  }

  await page.setViewportSize({ width: 1180, height: 780 })
  await expect(page.locator('.window-controls')).toBeVisible()
  await expect(page.locator('.desktop-workspace')).toHaveAttribute('data-responsive-mode', 'compact')
  const workflowToggle = page.getByRole('button', { name: '流程', exact: true })
  await workflowToggle.click()
  await expect(page.locator('.desktop-workspace.inspector-sheet .workflow-rail')).toBeVisible()
  await page.keyboard.press('Escape')
  await expectReachableInViewport(page.getByRole('button', { name: /导出可用的 [1-9]\d* 张/ }).first())
  await page.setViewportSize({ width: 1440, height: 1000 })

  await page.screenshot({ path: 'test-results/ui-smoke-after-generate.png', fullPage: true })
})
