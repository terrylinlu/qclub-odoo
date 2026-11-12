import { test, expect, Page } from '@playwright/test';

// Late in the day today has no bookable slot left, so walk forward to the first day that has one.
async function showDayWithFreeSlot(page: Page) {
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
    if (await page.locator('.o_qclub_slot_free').count()) return;
    day.setUTCDate(day.getUTCDate() + 1);
  }
  throw new Error('No free slot in the booking window; run make demo-reset');
}

test('test_web_006_web_008_web_004_select_login_restore_submit_confirmation', async ({ page }, testInfo) => {
  await page.goto('/billiard/booking');
  await expect(page.locator('.o_qclub_grid_table')).toBeVisible();
  const picker = page.locator('.o_qclub_booking_date');
  const minimum = await picker.getAttribute('min');
  const date = new Date(`${minimum}T12:00:00Z`);
  // Distinct dates/customer accounts keep the desktop and mobile projects independent.
  const mobile = testInfo.project.name === 'mobile-chromium';
  date.setUTCDate(date.getUTCDate() + (mobile ? 3 : 2));
  const response = page.waitForResponse(r => r.url().endsWith('/billiard/booking/occupancy'));
  await picker.fill(date.toISOString().slice(0, 10));
  await picker.dispatchEvent('change');
  await response;
  await expect(page.locator('.o_qclub_grid_table')).toBeVisible();
  const row = page.locator('.o_qclub_table_row').first();
  const first = row.locator('.o_qclub_slot_free').first();
  const index = Number(await first.getAttribute('data-slot-index'));
  await first.click();
  await row.locator(`.o_qclub_slot_free[data-slot-index="${index + 1}"]`).click();
  await expect(row.locator('[aria-pressed="true"]')).toHaveCount(2);
  const summary = page.locator('.o_qclub_summary');
  await expect(summary).toContainText('Table fee: $40.00 | Deposit: $20.00');
  const selectedSummary = await summary.textContent();
  await page.getByRole('button', { name: 'Log in to book', exact: true }).click();
  await expect(page).toHaveURL(/\/web\/login\?redirect=/);
  await page.locator('input[name="login"]').fill(mobile ? 'demo-customer-b' : 'demo-customer-a');
  await page.locator('input[name="password"]').fill('demo');
  await page.getByRole('button', { name: 'Log in', exact: true }).click();
  await expect(page).toHaveURL(/\/billiard\/booking\?/);
  await expect(page.locator('[aria-pressed="true"]')).toHaveCount(2);
  await expect(summary).toHaveText(selectedSummary!);
  await page.getByRole('button', { name: 'Book', exact: true }).click();
  await expect(page).toHaveURL(/\/billiard\/booking\/confirmation\/QB/);
  await expect(page.locator('.o_qclub_confirmation')).toContainText('Awaiting Deposit');
  await expect(page.locator('.o_qclub_hold')).toHaveText(/Held for \d+:\d{2}/);
  await expect(page.locator('.o_qclub_deposit_payment #o_payment_form')).toBeVisible();
});

test('test_web_006_mobile_selection_clear_and_shorten', async ({ page }) => {
  await page.setViewportSize({ width: 393, height: 851 });
  await page.goto('/billiard/booking');
  await expect(page.locator('.o_qclub_grid_table')).toBeVisible();
  const picker = page.locator('.o_qclub_booking_date');
  const date = new Date(`${await picker.getAttribute('min')}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + 4);
  const response = page.waitForResponse(r => r.url().endsWith('/billiard/booking/occupancy'));
  await picker.fill(date.toISOString().slice(0, 10));
  await picker.dispatchEvent('change');
  await response;
  await expect(page.locator('.o_qclub_grid_table')).toBeVisible();
  const row = page.locator('.o_qclub_table_row').last();
  const first = row.locator('.o_qclub_slot_free').first();
  const index = Number(await first.getAttribute('data-slot-index'));
  await first.click();
  const second = row.locator(`.o_qclub_slot_free[data-slot-index="${index + 1}"]`);
  await second.click();
  await expect(row.locator('[aria-pressed="true"]')).toHaveCount(2);
  await second.click();
  await expect(row.locator('[aria-pressed="true"]')).toHaveCount(1);
  await page.getByRole('button', { name: 'Clear', exact: true }).click();
  await expect(row.locator('[aria-pressed="true"]')).toHaveCount(0);
  await expect(page.locator('.o_qclub_selection')).toBeHidden();
});

test('test_web_005_stale_quote_refreshes_grid_and_clears_loading', async ({ page, browser }, testInfo) => {
  await page.goto('/billiard/booking');
  const picker = page.locator('.o_qclub_booking_date');
  await expect(page.locator('.o_qclub_grid_table')).toBeVisible();
  const day = new Date(`${await picker.getAttribute('min')}T12:00:00Z`);
  const mobile = testInfo.project.name === 'mobile-chromium';
  day.setUTCDate(day.getUTCDate() + (mobile ? 7 : 6));
  const date = day.toISOString().slice(0, 10);
  const occupancyResponse = page.waitForResponse(r => r.url().endsWith('/billiard/booking/occupancy'));
  await picker.fill(date);
  await picker.dispatchEvent('change');
  const occupancy = (await (await occupancyResponse).json()).result;
  await expect(page.locator('.o_qclub_grid_table')).toBeVisible();
  const cell = page.locator('.o_qclub_table_row').last().locator('.o_qclub_slot_free').first();
  const table = Number(await cell.getAttribute('data-table-id'));
  const index = Number(await cell.getAttribute('data-slot-index'));
  const context = await browser.newContext({ baseURL: testInfo.project.use.baseURL });
  try {
    const holder = await context.newPage();
    await holder.goto('/web/login?redirect=/billiard/booking');
    await holder.locator('input[name="login"]').fill(mobile ? 'demo-customer-a' : 'demo-customer-b');
    await holder.locator('input[name="password"]').fill('demo');
    await holder.getByRole('button', { name: 'Log in', exact: true }).click();
    await expect(holder.locator('.o_qclub_booking_grid')).toBeVisible();
    const csrf = await holder.locator('.o_qclub_booking_grid').getAttribute('data-csrf-token');
    // Submit from the browser page: Node's resolver cannot resolve *.localhost.
    const held = await holder.evaluate(async (params) => {
      const response = await fetch('/billiard/booking/submit', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', method: 'call', id: 1, params }),
      });
      return response.json();
    }, { table, start: occupancy.slots[index].start, hours: 1, date, csrf_token: csrf });
    expect(held.result.confirmation_url).toMatch(/confirmation\/QB/);
    await cell.click();
    const alert = page.locator('.o_qclub_alert');
    await expect(alert).toBeVisible();
    await expect(alert).toBeInViewport();
    await expect(alert).toContainText('This time slot has just been taken. Please choose another.');
    await expect(alert).toContainText('Slots awaiting a deposit are released automatically');
    await expect(page.locator(`.o_qclub_slot_occupied[data-table-id="${table}"][data-slot-index="${index}"]`)).toBeVisible();
    await expect(page.locator('[aria-pressed="true"]')).toHaveCount(0);
    await expect(page.locator('.o_qclub_selection')).toBeHidden();
    await expect(page.locator('.o_qclub_summary')).not.toContainText('Loading quote…');
  } finally {
    await context.close();
  }
});

test('test_web_005_bfcache_restore_clears_selection_and_messages', async ({ page }) => {
  await page.goto('/billiard/booking');
  await showDayWithFreeSlot(page);
  await page.locator('.o_qclub_slot_free').first().click();
  await expect(page.locator('.o_qclub_summary')).toContainText('Table fee:');
  const refreshed = page.waitForResponse(r => r.url().endsWith('/billiard/booking/occupancy'));
  await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true })));
  await refreshed;
  await expect(page.locator('.o_qclub_grid_table')).toBeVisible();
  await expect(page.locator('[aria-pressed="true"]')).toHaveCount(0);
  await expect(page.locator('.o_qclub_selection')).toBeHidden();
  await expect(page.locator('.o_qclub_grid_message')).toBeEmpty();
});

for (const failure of ['validation', 'network']) {
  test(`test_web_005_quote_${failure}_leaves_booking_usable`, async ({ page }) => {
    await page.goto('/billiard/booking');
    await showDayWithFreeSlot(page);
    await page.route('**/billiard/booking/quote', route => failure === 'network' ? route.abort() :
      route.fulfill({ json: { jsonrpc: '2.0', id: 1, result: { error: 'validation', message: 'Please try again.' } } }));
    await page.locator('.o_qclub_slot_free').first().click();
    await expect(page.locator('.o_qclub_selection_error')).not.toBeEmpty();
    await expect(page.locator('.o_qclub_summary')).not.toContainText('Loading quote…');
    await expect(page.locator('.o_qclub_book')).toBeEnabled();
    await page.unroute('**/billiard/booking/quote');
    await page.locator('.o_qclub_slot_free').first().click();
    await page.locator('.o_qclub_slot_free').first().click();
    await expect(page.locator('.o_qclub_summary')).toContainText('Table fee:');
  });
}

for (const routeName of ['quote', 'submit']) {
  test(`test_web_005_${routeName}_own_hold_alert_has_safe_booking_link`, async ({ page }) => {
    if (routeName === 'submit') {
      await page.goto('/web/login?redirect=/billiard/booking');
      await page.locator('input[name="login"]').fill('demo-customer-a');
      await page.locator('input[name="password"]').fill('demo');
      await page.getByRole('button', { name: 'Log in', exact: true }).click();
    } else {
      await page.goto('/billiard/booking');
    }
    await showDayWithFreeSlot(page);
    const message = 'You already hold this time slot (QB<img src=x>, awaiting deposit).';
    const confirmation = '/billiard/booking/confirmation/QB-test';
    await page.route(`**/billiard/booking/${routeName}`, route => route.fulfill({ json: {
      jsonrpc: '2.0', id: 1, result: { error: 'own_hold', message, confirmation_url: confirmation },
    } }));
    await page.locator('.o_qclub_slot_free').first().click();
    if (routeName === 'submit') {
      await expect(page.locator('.o_qclub_summary')).toContainText('Table fee:');
      await page.getByRole('button', { name: 'Book', exact: true }).click();
    }
    const alert = page.locator('.o_qclub_alert');
    await expect(alert).toBeVisible();
    await expect(alert).toContainText(message);
    await expect(alert.locator('img')).toHaveCount(0);
    await expect(alert.getByRole('link', { name: 'View booking' })).toHaveAttribute('href', confirmation);
    await expect(page).toHaveURL(/\/billiard\/booking$/);
    await expect(page.locator('.o_qclub_selection')).toBeHidden();
    const refreshed = page.waitForResponse(r => r.url().endsWith('/billiard/booking/occupancy'));
    await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true })));
    await refreshed;
    await expect(page.locator('.o_qclub_grid_table')).toBeVisible();
    await expect(page.locator('.o_qclub_grid_message')).toBeEmpty();
    await expect(page.getByRole('link', { name: 'View booking' })).toHaveCount(0);
  });
}
