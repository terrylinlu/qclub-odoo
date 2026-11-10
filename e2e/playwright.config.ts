import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  // The demo Odoo server is a single process; more browsers at once causes spurious timeouts.
  // Multi-customer flows share one single-process demo server.
  timeout: 60000,
  workers: 2,
  // First back-office login builds a large asset bundle and briefly stalls the single-process demo.
  expect: { timeout: 15000 },
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://qclub.localhost:8069',
    trace: 'retain-on-failure',
    // Pages wait for Google Fonts before running their scripts, and connections to it can
    // stall for 10+ seconds. Fail those requests at once so tests do not depend on the internet.
    launchOptions: { args: ['--host-resolver-rules=MAP fonts.googleapis.com ~NOTFOUND, MAP fonts.gstatic.com ~NOTFOUND'] },
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } } },
    { name: 'mobile-chromium', use: { ...devices['Pixel 7'], browserName: 'chromium' } },
  ],
});
