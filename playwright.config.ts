import { existsSync } from 'node:fs'
import { chromium, defineConfig, devices } from '@playwright/test'

const uiSmokePort = Number(process.env.UI_SMOKE_PORT || 6021)
const uiSmokeUrl = `http://127.0.0.1:${uiSmokePort}`
const systemChromeExecutable = [
  process.env.PLAYWRIGHT_CHROME_EXECUTABLE,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
].find((candidate): candidate is string => Boolean(candidate && existsSync(candidate)))
const chromiumExecutable = existsSync(chromium.executablePath())
  ? undefined
  : systemChromeExecutable
const useExternalUiServer = process.env.UI_SMOKE_EXTERNAL_SERVER === '1'

export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  expect: {
    timeout: 8_000,
  },
  use: {
    baseURL: uiSmokeUrl,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    launchOptions: chromiumExecutable ? { executablePath: chromiumExecutable } : undefined,
  },
  webServer: useExternalUiServer ? undefined : {
    command: `node scripts/serve_ui_smoke.mjs ${uiSmokePort}`,
    url: uiSmokeUrl,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 1000 },
      },
    },
  ],
})
