import { test, expect } from '@playwright/test';

test.use({ baseURL: 'http://localhost:8069' });

test('test_adm_003_backoffice_conflict_dialog', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === 'mobile-chromium', 'Back-office desktop form');
  await page.goto('/web/login?redirect=%2Fodoo');
  await page.locator('input[name="login"]').fill('demo-staff');
  await page.locator('input[name="password"]').fill('demo');
  await page.getByRole('button', { name: 'Log in', exact: true }).click();
  await expect(page.locator('.o_web_client')).toBeVisible();

  // Fetch through the authenticated browser and let the real form perform web_save.
  const booking = await page.evaluate(async () => {
    const response = await fetch('/web/dataset/call_kw/qclub.booking/search_read', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jsonrpc: '2.0', method: 'call', id: 1, params: {
        model: 'qclub.booking', method: 'search_read',
        args: [[['state', 'in', ['confirmed', 'arrived']],
          ['start', '>', new Date().toISOString().slice(0, 19).replace('T', ' ')]],
        ['table_id', 'partner_id', 'start', 'start_date', 'start_hour']],
        kwargs: { limit: 1, order: 'start' },
      } }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const body = await response.json();
    if (body.error) throw new Error(JSON.stringify(body.error));
    return body.result[0];
  });
  expect(booking, 'Demo needs an existing future active booking').toBeTruthy();

  // Defaults enter the existing slot without date-picker locale assumptions.
  await page.evaluate(async booking => {
    const env = (window as any).odoo.__WOWL_DEBUG__.root.env;
    await env.services.action.doAction({
      type: 'ir.actions.act_window', res_model: 'qclub.booking',
      views: [[false, 'form']], target: 'current', context: {
        default_table_id: booking.table_id[0], default_partner_id: booking.partner_id[0],
        default_start: booking.start, default_start_date: booking.start_date,
        default_start_hour: booking.start_hour, default_duration_hours: 1,
      },
    });
  }, booking);
  const form = page.locator('.o_form_view');
  try {
    await expect(form.getByRole('combobox', { name: 'Table', exact: true })).toHaveValue(booking.table_id[1]);
    await expect(form.getByRole('combobox', { name: 'Customer', exact: true })).toHaveValue(booking.partner_id[1]);
    await expect(form.getByRole('button', { name: 'Business Date', exact: true })).toBeVisible();
    const hour = Number(booking.start_hour);
    const timeLabel = `${hour % 12 || 12}:00 ${hour < 12 ? 'AM' : 'PM'}`;
    const startTime = form.getByRole('textbox', { name: 'Start Time', exact: true });
    await startTime.click();
    await page.getByRole('menuitem', { name: new RegExp(`^${timeLabel}(?: [(]next day[)])?$`) }).click();
    await expect(startTime).toHaveValue(new RegExp(`^${timeLabel}(?: [(]next day[)])?$`));
    await form.getByRole('textbox', { name: 'Number of Hours', exact: true }).fill('1');
    await form.getByRole('textbox', { name: 'Number of Hours', exact: true }).press('Tab');
    await page.getByRole('button', { name: 'Save manually', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toContainText('This table is already booked for the selected time');
    await expect(dialog.locator('.modal-title')).toHaveText('Validation Error');
    await expect(dialog).not.toContainText('Oops');
  } finally {
    const dialog = page.getByRole('dialog');
    if (await dialog.isVisible()) {
      await dialog.getByRole('button', { name: 'Close', exact: true }).first().click();
    }
    await page.getByRole('button', { name: 'Discard all changes', exact: true }).click();
  }
});
