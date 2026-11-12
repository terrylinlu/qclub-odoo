import { test, expect, Page } from '@playwright/test';

// All requests run in the browser: Node cannot resolve *.localhost.
async function orm(page: Page, model: string, method: string, args: unknown[]) {
  return page.evaluate(async ({ model, method, args }) => {
    const response = await fetch(`/web/dataset/call_kw/${model}/${method}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jsonrpc: '2.0', method: 'call', id: 1,
        params: { model, method, args, kwargs: {} } }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const body = await response.json();
    if (body.error) throw new Error(JSON.stringify(body.error));
    return body.result;
  }, { model, method, args });
}

test.describe.configure({ mode: 'serial' });

// Search the configured booking window for consecutive free cells in any table.
async function showFreePair(page: Page) {
  await expect(page.locator('.o_qclub_grid_table')).toBeVisible();
  const picker = page.locator('.o_qclub_booking_date');
  const maximum = await picker.getAttribute('max');
  const day = new Date(`${await picker.getAttribute('min')}T12:00:00Z`);
  while (day.toISOString().slice(0, 10) <= maximum!) {
    const value = day.toISOString().slice(0, 10);
    if (await picker.inputValue() !== value) {
      const response = page.waitForResponse(r => r.url().endsWith('/billiard/booking/occupancy'));
      await picker.fill(value);
      await picker.dispatchEvent('change');
      await response;
      await expect(page.locator('.o_qclub_grid_table')).toBeVisible();
    }
    const pair = page.locator('.o_qclub_slot_free + .o_qclub_slot_free').first();
    if (await pair.count()) return pair;
    day.setUTCDate(day.getUTCDate() + 1);
  }
  throw new Error('No consecutive free slots in the booking window; run make demo-reset');
}

test('test_cfg_006_hidden_prices_keep_selection_amounts', async ({ page, browser, baseURL }) => {
  const adminContext = await browser.newContext({ baseURL });
  const admin = await adminContext.newPage();
  let configId: number | undefined;
  let original: boolean | undefined;
  try {
    await admin.goto('/web/login?redirect=%2Fbilliard%2Fbooking');
    await admin.locator('input[name="login"]').fill('admin');
    await admin.locator('input[name="password"]').fill('admin');
    await admin.getByRole('button', { name: 'Log in', exact: true }).click();
    await expect(admin.locator('.o_qclub_grid_table')).toBeVisible();
    const configs = await orm(admin, 'qclub.config', 'search_read', [
      [['website_id.name', '=', 'Q Club']], ['id', 'show_grid_prices'],
    ]);
    expect(configs).toHaveLength(1);
    configId = configs[0].id;
    original = configs[0].show_grid_prices;
    expect(typeof original).toBe('boolean');
    expect(await orm(admin, 'qclub.config', 'write', [[configId], { show_grid_prices: false }])).toBe(true);
    await page.goto('/billiard/booking');
    await expect(page.locator('.o_qclub_booking_grid')).toHaveAttribute('data-show-grid-prices', '0');
    const second = await showFreePair(page);
    const cells = page.locator('.o_qclub_slot_free');
    for (const text of await cells.allTextContents()) {
      expect(text).toBe('Available');
      expect(text).not.toContain('$');
    }
    for (const heading of await page.locator('tbody .o_qclub_table_heading').all()) {
      await expect(heading).not.toHaveAttribute('title', /\$|\/ hour/);
    }
    const index = Number(await second.getAttribute('data-slot-index'));
    const table = await second.getAttribute('data-table-id');
    // Fix both cells before clicking: `second` is re-evaluated after the first click.
    const firstCell = page.locator(`.o_qclub_slot[data-table-id="${table}"][data-slot-index="${index - 1}"]`);
    const secondCell = page.locator(`.o_qclub_slot[data-table-id="${table}"][data-slot-index="${index}"]`);
    await firstCell.click();
    await secondCell.click();
    await expect(page.locator('.o_qclub_slot_free[aria-pressed="true"]')).toHaveCount(2);
    const summary = page.locator('.o_qclub_summary');
    await expect(summary).toContainText(/Table fee: \$[\d,]+\.\d{2}/);
    await expect(summary).toContainText(/Deposit: \$[\d,]+\.\d{2}/);
  } finally {
    try {
      if (configId !== undefined && original !== undefined) {
        expect(await orm(admin, 'qclub.config', 'write', [[configId], { show_grid_prices: original }])).toBe(true);
      }
    } finally {
      await adminContext.close();
    }
  }
});

test('test_cfg_006_default_prices_visible', async ({ page, browser, baseURL }) => {
  const adminContext = await browser.newContext({ baseURL });
  const admin = await adminContext.newPage();
  let configId: number | undefined;
  let original: boolean | undefined;
  try {
    await admin.goto('/web/login?redirect=%2Fbilliard%2Fbooking');
    await admin.locator('input[name="login"]').fill('admin');
    await admin.locator('input[name="password"]').fill('admin');
    await admin.getByRole('button', { name: 'Log in', exact: true }).click();
    await expect(admin.locator('.o_qclub_grid_table')).toBeVisible();
    const configs = await orm(admin, 'qclub.config', 'search_read', [
      [['website_id.name', '=', 'Q Club']], ['id', 'show_grid_prices'],
    ]);
    expect(configs).toHaveLength(1);
    configId = configs[0].id;
    original = configs[0].show_grid_prices;
    expect(typeof original).toBe('boolean');
    expect(await orm(admin, 'qclub.config', 'write', [[configId], { show_grid_prices: true }])).toBe(true);
    await page.goto('/billiard/booking');
    await expect(page.locator('.o_qclub_booking_grid')).toHaveAttribute('data-show-grid-prices', '1');
    await showFreePair(page);
    for (const text of await page.locator('.o_qclub_slot_free').allTextContents()) {
      expect(text).toMatch(/\$\d/);
    }
    await expect(page.locator('tbody .o_qclub_table_heading').first()).toHaveAttribute('title', /\$/);
  } finally {
    try {
      if (configId !== undefined && original !== undefined) {
        expect(await orm(admin, 'qclub.config', 'write', [[configId], { show_grid_prices: original }])).toBe(true);
      }
    } finally {
      await adminContext.close();
    }
  }
});
