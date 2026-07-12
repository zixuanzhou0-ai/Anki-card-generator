import { chromium } from 'playwright'
import path from 'node:path'

const reportRoot = path.resolve('E:/ANKI/docs/reports/2026-06-24-cross-platform-verification')
const screenshotPath = path.join(reportRoot, 'assets', 'installed-v094-compact-ui.png')

function assert(condition, message) {
  if (!condition) {
    throw new Error(message)
  }
}

async function reachableInViewport(locator, label) {
  await locator.scrollIntoViewIfNeeded()
  const result = await locator.evaluate((element) => {
    const rect = element.getBoundingClientRect()
    const centerX = rect.left + rect.width / 2
    const centerY = rect.top + rect.height / 2
    const hit = document.elementFromPoint(centerX, centerY)

    return {
      hasBox: rect.width > 0 && rect.height > 0,
      inViewport:
        rect.left >= 0 &&
        rect.top >= 0 &&
        rect.right <= window.innerWidth &&
        rect.bottom <= window.innerHeight,
      hitTarget: hit === element || element.contains(hit),
      rect: {
        left: rect.left,
        top: rect.top,
        right: rect.right,
        bottom: rect.bottom,
        width: rect.width,
        height: rect.height,
      },
    }
  })

  assert(result.hasBox, `${label} has no bounding box`)
  assert(result.inViewport, `${label} is outside viewport: ${JSON.stringify(result.rect)}`)
  assert(result.hitTarget, `${label} center point is covered`)
  return result
}

const browser = await chromium.connectOverCDP('http://127.0.0.1:9333')
const context = browser.contexts()[0]
assert(context, 'No WebView2 browser context found on CDP port 9333')

const page = context.pages()[0]
assert(page, 'No WebView2 page found on CDP port 9333')

await page.evaluate(() => window.localStorage.clear())
await page.reload({ waitUntil: 'domcontentloaded' })
await page.locator('.app-shell').waitFor({ state: 'visible', timeout: 60_000 })
await page.setViewportSize({ width: 1180, height: 780 })

const titleVisible = await page.getByRole('heading', { name: 'Anki 卡片生成器' }).isVisible()
assert(titleVisible, 'Main product title is not visible')

const responsiveMode = await page.locator('.desktop-workspace').getAttribute('data-responsive-mode')
assert(responsiveMode === 'compact', `Expected compact responsive mode, got ${responsiveMode}`)

await page.getByRole('button', { name: /素材面板/ }).click()
await page.locator('.control-column.sheet-open').waitFor({ state: 'visible', timeout: 10_000 })

await reachableInViewport(page.getByRole('button', { name: /选择素材后继续|下一步：学习设置/ }), 'main CTA')
await page.getByRole('button', { name: '批量 / 文件夹' }).click()
await reachableInViewport(page.getByRole('button', { name: '选择视频文件夹批量添加' }), 'batch folder picker')
await reachableInViewport(page.getByRole('button', { name: /选择素材后继续|下一步：学习设置/ }), 'main CTA after batch mode')

const metrics = await page.evaluate(() => ({
  horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  viewport: { width: window.innerWidth, height: window.innerHeight },
  scrollWidth: document.documentElement.scrollWidth,
  clientWidth: document.documentElement.clientWidth,
}))
assert(!metrics.horizontalOverflow, `Horizontal overflow detected: ${JSON.stringify(metrics)}`)

await page.screenshot({ path: screenshotPath, fullPage: true })
await browser.close()

console.log(
  JSON.stringify(
    {
      status: 'pass',
      screenshotPath,
      responsiveMode,
      metrics,
    },
    null,
    2,
  ),
)


