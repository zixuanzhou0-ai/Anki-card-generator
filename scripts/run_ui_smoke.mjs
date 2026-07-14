/* global process, console, window, document */
import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'
import { chromium } from '@playwright/test'
import { startUiSmokeServer } from './serve_ui_smoke.mjs'

const outputDir = resolve('test-results', 'ui-smoke-direct')
await mkdir(outputDir, { recursive: true })

const chromeExecutable = [
  process.env.PLAYWRIGHT_CHROME_EXECUTABLE,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
].find((candidate) => candidate && existsSync(candidate))

const bundledChromium = chromium.executablePath()
const executablePath = chromeExecutable || (existsSync(bundledChromium) ? bundledChromium : undefined)
if (!executablePath) {
  throw new Error('No Playwright Chromium or system Chrome executable is available.')
}

const server = await startUiSmokeServer(0)
const address = server.address()
if (!address || typeof address === 'string') throw new Error('UI smoke server did not expose a TCP port.')
const baseURL = `http://127.0.0.1:${address.port}`
const browser = await chromium.launch({ executablePath, headless: true })
const failures = []

async function closeServer() {
  await new Promise((resolvePromise) => server.close(() => resolvePromise()))
}

async function gotoApp(page) {
  await page.goto(baseURL, { waitUntil: 'commit', timeout: 120_000 })
  await page.locator('.app-shell').waitFor({ state: 'visible', timeout: 120_000 })
}

async function expectVisible(locator, label, timeout = 30_000) {
  await locator.waitFor({ state: 'visible', timeout })
  assert.equal(await locator.isVisible(), true, `${label} should be visible`)
}

async function expectReachableInViewport(locator, label) {
  await locator.scrollIntoViewIfNeeded()
  const result = await locator.evaluate((element) => {
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
  assert.equal(result.hasBox, true, `${label} should have a rendered box`)
  assert.equal(result.inViewport, true, `${label} should be inside the viewport`)
  assert.equal(result.hitTarget, true, `${label} should not be covered by another element`)
}

async function assertNoHorizontalOverflow(page, label) {
  const metrics = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
  assert.ok(metrics.scrollWidth <= metrics.clientWidth, `${label} overflowed horizontally: ${JSON.stringify(metrics)}`)
}

async function expectResponsiveMode(page, expected, timeout = 5_000) {
  await page.waitForFunction(
    (mode) => document.querySelector('.desktop-workspace')?.getAttribute('data-responsive-mode') === mode,
    expected,
    { timeout },
  )
  assert.equal(await page.locator('.desktop-workspace').getAttribute('data-responsive-mode'), expected)
}

async function runCase(name, options, callback) {
  const context = await browser.newContext(options)
  const page = await context.newPage()
  const pageErrors = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  try {
    await callback(page)
    assert.deepEqual(pageErrors, [], `${name} emitted page errors`)
    console.log(`PASS ${name}`)
  } catch (error) {
    failures.push({ name, error })
    await page.screenshot({ path: resolve(outputDir, `${name.replace(/[^a-z0-9]+/gi, '-')}-failure.png`), fullPage: true }).catch(() => {})
    console.error(`FAIL ${name}:`, error)
  } finally {
    await context.close()
  }
}

await runCase('source-selector', { viewport: { width: 1440, height: 1000 } }, async (page) => {
  await page.addInitScript(() => window.localStorage.clear())
  await gotoApp(page)
  const sourceSwitch = page.locator('[aria-label="素材来源"]')
  await expectVisible(sourceSwitch, 'source selector')
  assert.equal(await sourceSwitch.getByRole('button').count(), 2)
  await expectVisible(sourceSwitch.getByRole('button', { name: /本地视频/ }), 'local video option')
  await expectVisible(sourceSwitch.getByRole('button', { name: /视频链接/ }), 'video URL option')
  assert.equal(await sourceSwitch.getByRole('button', { name: /文档资料/ }).count(), 0)
  assert.equal(await page.getByPlaceholder('选择文档资料').count(), 0)
  await assertNoHorizontalOverflow(page, '1440 source workspace')
})

await runCase('compact-workbench', { viewport: { width: 1180, height: 780 } }, async (page) => {
  await page.addInitScript(() => window.localStorage.clear())
  await gotoApp(page)
  await expectResponsiveMode(page, 'compact')
  assert.equal(await page.locator('.control-column').isVisible(), false)

  const toggle = page.getByRole('button', { name: /素材面板/ })
  await toggle.click()
  await expectVisible(page.locator('.control-column.sheet-open'), 'compact source sheet')
  await page.keyboard.press('Escape')
  assert.equal(await page.locator('.control-column.sheet-open').count(), 0)
  assert.equal(await toggle.evaluate((element) => element === document.activeElement), true, 'Escape should restore focus to the inspector toggle')
  await toggle.click()
  await page.getByRole('button', { name: '批量 / 文件夹' }).click()
  await expectReachableInViewport(page.getByRole('button', { name: '选择视频文件夹批量添加' }), 'batch folder button')
  await expectReachableInViewport(page.getByRole('button', { name: /选择素材后继续|下一步：学习设置/ }), 'compact primary action')
  await assertNoHorizontalOverflow(page, '1180 compact workspace')
  await page.screenshot({ path: resolve(outputDir, 'compact-1180x780.png'), fullPage: true })
})

await runCase('settings-and-workflow', { viewport: { width: 1540, height: 1080 } }, async (page) => {
  await page.addInitScript(() => {
    window.localStorage.clear()
    window.localStorage.setItem('anki-card-generator.ui-preferences.v1', JSON.stringify({
      onboardingVersion: 1,
      onboardingCompleted: true,
      settingsMode: 'simple',
    }))
    const hashProfile = (values) => {
      const normalized = values.join('|')
      let hash = 2166136261
      for (let index = 0; index < normalized.length; index += 1) {
        hash ^= normalized.charCodeAt(index)
        hash = Math.imul(hash, 16777619)
      }
      return (hash >>> 0).toString(36)
    }
    const profileId = (provider, baseUrl, model) =>
      `api_${hashProfile([provider, baseUrl.trim().replace(/\/+$/, ''), model.trim()])}`
    const ttsProfileId = (provider, baseUrl, model, voice) =>
      `tts_${hashProfile([provider, baseUrl.trim().replace(/\/+$/, ''), model.trim(), voice.trim()])}`
    const baseUrl = 'https://aiplatform.googleapis.com'
    window.localStorage.setItem('anki-card-generator.api-profiles.v1', JSON.stringify([
      {
        auth: 'gcloud', base_url: baseUrl, capabilities: ['structured_json', 'long_context', 'cheap_batch'],
        has_api_key: false, id: profileId('gemini-vertex', baseUrl, 'gemini-3.5-flash'),
        label: 'Gemini 3.5 Flash Vertex', last_test_ok: true, model: 'gemini-3.5-flash',
        provider: 'gemini-vertex', updated_at: '2026-06-27T00:00:00.000Z',
      },
      {
        auth: 'gcloud', base_url: baseUrl, capabilities: ['structured_json', 'long_context'],
        has_api_key: false, id: profileId('gemini-vertex', baseUrl, 'gemini-3.1-pro-preview'),
        label: 'Gemini 3.1 Pro Preview Vertex', last_test_ok: true, model: 'gemini-3.1-pro-preview',
        provider: 'gemini-vertex', updated_at: '2026-06-27T00:00:00.000Z',
      },
    ]))
    window.localStorage.setItem('anki-card-generator.tts-profiles.v1', JSON.stringify([
      {
        auth: 'gcloud', base_url: baseUrl, bit_rate: 128000, enabled: true,
        has_api_key: false,
        id: ttsProfileId('gemini-vertex', baseUrl, 'gemini-3.1-flash-tts-preview', 'Kore'),
        label: 'Gemini 3.1 Flash TTS Vertex', language: 'auto', last_test_ok: true,
        model: 'gemini-3.1-flash-tts-preview', output_volume: 0.65, provider: 'gemini-vertex',
        sample_rate: 24000, updated_at: '2026-06-27T00:00:00.000Z', voice: 'Kore',
      },
    ]))
  })
  await gotoApp(page)
  await expectVisible(page.getByRole('heading', { name: 'Anki 卡片生成器' }), 'app heading')
  await expectVisible(page.getByText('生成工作台'), 'workbench title')
  assert.equal(await page.locator('.app-rail').count(), 0)

  const settingsButton = page.getByRole('button', { name: '设置', exact: true })
  await settingsButton.click()
  const dialog = page.getByRole('dialog', { name: '设置' })
  await expectVisible(dialog, 'settings dialog')
  const simple = page.getByRole('button', { name: '简单', exact: true })
  const advanced = page.getByRole('button', { name: '高级', exact: true })
  assert.equal(await simple.getAttribute('aria-pressed'), 'true')
  await expectVisible(page.getByText('选择一个模型方案。'), 'simple model guidance')
  await expectVisible(page.getByLabel('厂商和模型目录').getByRole('button', { name: /Hermes · Grok 4.5/ }), 'Hermes model option')
  assert.equal(await page.getByRole('combobox', { name: 'Provider' }).isVisible(), false, 'Provider should be hidden in simple mode')

  await advanced.click()
  assert.equal(await advanced.getAttribute('aria-pressed'), 'true')
  await expectVisible(page.getByRole('combobox', { name: 'Provider' }), 'advanced Provider')
  await expectVisible(page.getByRole('textbox', { name: 'Base URL' }), 'advanced Base URL')
  await expectVisible(page.getByRole('combobox', { name: 'Model' }), 'advanced model id')
  await expectVisible(page.getByText('Vertex 授权'), 'Vertex OAuth explanation')
  assert.equal(await page.getByLabel('API Key').count(), 0, 'Vertex must not expose an API key field')

  const selectedModelBefore = await page.getByRole('combobox', { name: 'Model' }).inputValue()
  await simple.click()
  assert.equal(await page.getByRole('combobox', { name: 'Provider' }).isVisible(), false)
  await advanced.click()
  assert.equal(await page.getByRole('combobox', { name: 'Model' }).inputValue(), selectedModelBefore, 'simple/advanced toggling must retain model data')

  await page.getByRole('tab', { name: '语音 TTS' }).click()
  await expectVisible(page.getByRole('heading', { name: '语音 TTS' }), 'TTS settings')
  await expectVisible(page.getByLabel('语音厂商和模型目录'), 'TTS catalog')
  await page.getByRole('tab', { name: '本地环境' }).click()
  await expectVisible(page.getByRole('button', { name: /一键修复全部可修复项/ }), 'environment repair action')
  await page.getByRole('tab', { name: '关于 / 版权' }).click()
  await expectVisible(page.getByText('版权所有 © 2026 Zixuan Zhou。保留所有权利。'), 'copyright')
  await page.screenshot({ path: resolve(outputDir, 'settings-about.png'), fullPage: true })
  await page.keyboard.press('Escape')
  await dialog.waitFor({ state: 'detached', timeout: 5_000 })
  assert.equal(await dialog.count(), 0)
  assert.equal(await settingsButton.evaluate((element) => element === document.activeElement), true, 'settings focus should be restored after Escape')

  await page.getByRole('button', { name: /视频链接/ }).click()
  await page.getByPlaceholder('https://www.youtube.com/watch?v=...').fill('https://www.youtube.com/watch?v=UV1WDNe4J5w')
  await page.getByRole('button', { name: /下一步：学习设置/ }).click()
  await expectVisible(page.getByRole('heading', { name: '卡片模式' }), 'learning settings')
  await page.getByRole('button', { name: /下一步：确认抽取/ }).click()
  await expectVisible(page.getByText('设置完成后先抽取学习点'), 'extraction confirmation')

  const extractionAction = page.getByRole('button', { name: /抽取学习点/ }).last()
  await expectVisible(extractionAction, 'extraction primary action')
  assert.equal(await extractionAction.isDisabled(), false, 'browser fixture should be ready to extract')
  await extractionAction.click()
  await expectVisible(page.getByRole('heading', { name: '学习点总览' }), 'learning point overview', 120_000)
  await expectVisible(page.getByText('in the mood').first(), 'recommended learning point')
  await page.screenshot({ path: resolve(outputDir, 'learning-points.png'), fullPage: true })

  await page.getByLabel('学习点总览').getByRole('button', { name: /生成选中的 1 张/ }).click()
  const confirmation = page.getByRole('dialog', { name: '生成确认' })
  await expectVisible(confirmation, 'generation confirmation')
  await expectVisible(page.getByRole('heading', { name: '准备生成 APKG · 1 个学习点' }), 'generation confirmation heading')
  await page.keyboard.press('Escape')
  assert.equal(await confirmation.count(), 0, 'Escape should close generation confirmation')
  await page.getByLabel('学习点总览').getByRole('button', { name: /生成选中的 1 张/ }).click()
  await confirmation.getByRole('button', { name: '生成 APKG' }).click()
  await expectVisible(page.getByText('检查卡片后导出 APKG'), 'review and export workspace', 120_000)
  await expectVisible(page.getByRole('button', { name: /导出可导出的 [1-9]\d* 张/ }).first(), 'export action')
  await expectVisible(page.getByLabel('卡片概览').getByRole('button', { name: '高级诊断' }), 'advanced diagnostics')

  for (const viewport of [
    { width: 1180, height: 780 },
    { width: 1540, height: 1080 },
    { width: 1920, height: 1080 },
    { width: 2560, height: 1440 },
    { width: 3840, height: 2160 },
  ]) {
    await page.setViewportSize(viewport)
    await assertNoHorizontalOverflow(page, `${viewport.width}x${viewport.height}`)
    await page.screenshot({ path: resolve(outputDir, `review-${viewport.width}x${viewport.height}.png`), fullPage: true })
  }

  await page.setViewportSize({ width: 1180, height: 780 })
  await expectResponsiveMode(page, 'compact')
  await page.getByRole('button', { name: /素材面板/ }).click()
  await expectVisible(page.locator('.control-column.sheet-open'), 'compact review sheet')
  await expectReachableInViewport(page.getByRole('button', { name: /导出可导出的 [1-9]\d* 张/ }).first(), 'compact export action')
})

await browser.close()
await closeServer()

if (failures.length > 0) {
  const summary = failures.map(({ name, error }) => `${name}: ${error instanceof Error ? error.stack || error.message : String(error)}`).join('\n\n')
  throw new Error(`${failures.length} UI smoke case(s) failed:\n${summary}`)
}

console.log(`UI smoke completed successfully. Screenshots: ${outputDir}`)