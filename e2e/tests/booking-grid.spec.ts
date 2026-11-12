import { test, expect } from '@playwright/test';

test('anonymous grid renders table rows and hourly columns', async ({ page }) => {
  await page.goto('/billiard/booking');
  await expect(page.locator('.o_qclub_grid_table')).toBeVisible();
  await expect(page.locator('.o_qclub_table_row').first()).toBeVisible();
  // A demo database has default opening hours every day.
  await expect(page.locator('thead th[data-slot-index]').first()).toBeVisible();
  await expect(page.locator('.o_qclub_slot').first()).toHaveAttribute('data-state', /free|occupied|past/);
});

test('demo occupied cells are disabled and have no click action', async ({ page }) => {
  await page.goto('/billiard/booking');
  const picker = page.locator('.o_qclub_booking_date');
  await expect(page.locator('.o_qclub_grid_table')).toBeVisible();
  const minimum = await picker.getAttribute('min');
  const maximum = await picker.getAttribute('max');
  expect(minimum).toBeTruthy();
  expect(maximum).toBeTruthy();
  // Demo bookings may belong to tomorrow or the next open business day.
  const day = new Date(`${minimum}T12:00:00Z`);
  let found = false;
  while (day.toISOString().slice(0, 10) <= maximum!) {
    const value = day.toISOString().slice(0, 10);
    if (await picker.inputValue() !== value) {
      const response = page.waitForResponse(r => r.url().endsWith('/billiard/booking/occupancy'));
      await picker.fill(value);
      await picker.dispatchEvent('change');
      await response;
      await expect(page.locator('.o_qclub_grid_table')).toBeVisible();
    }
    if (await page.locator('.o_qclub_slot[data-state="occupied"]').count()) {
      found = true;
      break;
    }
    day.setUTCDate(day.getUTCDate() + 1);
  }
  expect(found, 'Run make demo-reset to refresh future demo bookings').toBe(true);
  const occupied = page.locator('.o_qclub_slot[data-state="occupied"]').first();
  await expect(occupied).toHaveAttribute('aria-disabled', 'true');
  await expect(occupied).toHaveCSS('pointer-events', 'none');
  await expect(occupied.locator('button, a, input, [tabindex]')).toHaveCount(0);
});

test('mobile grid scrolls horizontally and keeps table names sticky', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile-chromium', 'Mobile viewport check');
  await page.goto('/billiard/booking');
  await expect(page.locator('.o_qclub_grid_table')).toBeVisible();
  const scroll = page.locator('.o_qclub_grid_scroll');
  expect(await scroll.evaluate(el => el.scrollWidth > el.clientWidth)).toBe(true);
  await scroll.evaluate(el => { el.scrollLeft = 150; });
  expect(await scroll.evaluate(el => el.scrollLeft)).toBeGreaterThan(0);
  await expect(page.locator('tbody .o_qclub_table_heading').first()).toHaveCSS('position', 'sticky');
});

test('AUSHARE booking page is 404', async ({ request, baseURL }) => {
  const url = new URL(baseURL!);
  const host = `aushare.localhost${url.port ? `:${url.port}` : ''}`;
  url.hostname = '127.0.0.1';
  url.pathname = '/billiard/booking';
  const response = await request.get(url.toString(), { headers: { Host: host } });
  expect(response.status()).toBe(404);
});

test('test_web_003_tbl_006_desktop_friday_fits_viewport', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium', 'Desktop viewport check');
  await page.goto('/billiard/booking');
  await expect(page.locator('.o_qclub_grid_table')).toBeVisible();
  const picker = page.locator('.o_qclub_booking_date');
  const minimum = await picker.getAttribute('min');
  const maximum = await picker.getAttribute('max');
  expect(minimum).toBeTruthy();
  expect(maximum).toBeTruthy();
  const friday = new Date(`${minimum}T12:00:00Z`);
  friday.setUTCDate(friday.getUTCDate() + (5 - friday.getUTCDay() + 7) % 7);
  const value = friday.toISOString().slice(0, 10);
  expect(value <= maximum!, 'Next Friday must be in the demo booking range').toBe(true);
  if (await picker.inputValue() !== value) {
    const response = page.waitForResponse(r => r.url().endsWith('/billiard/booking/occupancy'));
    await picker.fill(value);
    await picker.dispatchEvent('change');
    await response;
    await expect(page.locator('.o_qclub_grid_table')).toBeVisible();
  }
  await expect(page.locator('thead th[data-slot-index]')).toHaveCount(12);
  await expect(page.locator('.o_qclub_table_row')).toHaveCount(12);
  await expect(page.locator('thead th[data-slot-index]').last()).toHaveText('1:00 AM (next day)');
  const scroll = page.locator('.o_qclub_grid_scroll');
  expect(await scroll.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
  const bounds = await scroll.boundingBox();
  expect(bounds).not.toBeNull();
  expect(bounds!.y).toBeGreaterThanOrEqual(0);
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(800);
});
