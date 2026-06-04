import { defineConfig, devices } from '@playwright/test'

const uiSmokePort = Number(process.env.UI_SMOKE_PORT || 6021)
const uiSmokeUrl = `http://127.0.0.1:${uiSmokePort}`

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
  },
  webServer: {
    command: `npm run dev -- --port ${uiSmokePort}`,
    url: uiSmokeUrl,
    reuseExistingServer: false,
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
