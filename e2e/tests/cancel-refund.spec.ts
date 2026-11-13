import { test, expect } from '@playwright/test';

test('test_rf_001_rf_003_demo_paid_cancel_from_my_bookings', async ({ page }, testInfo) => {
  // Reuse the existing dedicated per-project payment accounts; identify only our new booking.
  const login = testInfo.project.name === 'mobile-chromium'
    ? 'demo-customer-pay-mobile' : 'demo-customer-pay';
  await page.goto('/web/login?redirect=/billiard/booking');
  await page.locator('input[name="login"]').fill(login);
  await page.locator('input[name="password"]').fill('demo');
  await page.getByRole('button', { name: 'Log in', exact: true }).click();
  await expect(page.locator('.o_qclub_grid_table')).toBeVisible();
  const picker = page.locator('.o_qclub_booking_date');
  const day = new Date(`${await picker.getAttribute('min')}T12:00:00Z`);
  day.setUTCDate(day.getUTCDate() + 3); // All hours on this business date are >24h ahead.
  const maximum = (await picker.getAttribute('max'))!;
  let booked = false;
  while (day.toISOString().slice(0, 10) <= maximum) {
    const loaded = page.waitForResponse(r => r.url().endsWith('/billiard/booking/occupancy'));
    await picker.fill(day.toISOString().slice(0, 10));
    await picker.dispatchEvent('change');
    await loaded;
    await expect(page.locator('.o_qclub_grid_table')).toBeVisible();
    const slot = page.locator('.o_qclub_slot_free').first();
    if (await slot.count()) {
      await slot.click();
      await page.getByRole('button', { name: 'Book', exact: true }).click();
      await expect(page).toHaveURL(/\/billiard\/booking\/confirmation\/QB/);
      booked = true;
      break;
    }
    day.setUTCDate(day.getUTCDate() + 1);
  }
  expect(booked, 'A free future slot must exist').toBeTruthy();
  const confirmation = page.url();
  const number = confirmation.split('/').pop()!;
  const form = page.locator('#o_payment_form');
  const demo = form.locator('input[name="o_payment_radio"][data-provider-code="demo"][data-payment-option-type="payment_method"]');
  await demo.check();
  const providerId = await demo.getAttribute('data-provider-id');
  const inline = form.locator(`#demo-container-${providerId}`);
  await inline.locator('select#simulated_payment_state').selectOption('done');
  await inline.locator('input#customer_input').fill('Offline cancellation demo');
  await form.getByRole('button', { name: 'Pay deposit', exact: true }).click();
  await expect(page).toHaveURL(confirmation);
  await expect(page.locator('.o_qclub_confirmation')).toContainText('Confirmed', { timeout: 30000 });
  await page.goto('/my/billiard');
  const row = page.locator('#qclub_my_bookings article').filter({ hasText: number });
  await row.getByRole('button', { name: 'Cancel booking', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Cancel booking' });
  await expect(dialog).toContainText(/You will receive a full refund of .*\d+\.\d{2}/);
  await dialog.getByRole('button', { name: 'Confirm cancellation', exact: true }).click();
  await expect(row).toContainText('Cancelled');
  await expect(row.getByRole('button', { name: 'Cancel booking', exact: true })).toHaveCount(0);
});
