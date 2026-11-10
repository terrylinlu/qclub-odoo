import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  // The demo Odoo server is a single process; more browsers at once causes spurious timeouts.
  workers: 2,
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://qclub.localhost:8069',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } } },
    { name: 'mobile-chromium', use: { ...devices['Pixel 7'], browserName: 'chromium' } },
  ],
});
