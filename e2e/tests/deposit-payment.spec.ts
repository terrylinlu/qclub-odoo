import { test, expect, Page } from '@playwright/test';

test.describe.configure({ mode: 'serial' });

async function bookFreeSlot(page: Page, login: string) {
  await page.goto('/web/login?redirect=/billiard/booking');
  await page.locator('input[name="login"]').fill(login);
  await page.locator('input[name="password"]').fill('demo');
  await page.getByRole('button', { name: 'Log in', exact: true }).click();
  await expect(page.locator('.o_qclub_grid_table')).toBeVisible();
  const picker = page.locator('.o_qclub_booking_date');
  const maximum = (await picker.getAttribute('max'))!;
  const day = new Date(`${await picker.getAttribute('min')}T12:00:00Z`);
  while (day.toISOString().slice(0, 10) <= maximum) {
    const date = day.toISOString().slice(0, 10);
    if (await picker.inputValue() !== date) {
      const loaded = page.waitForResponse(r => r.url().endsWith('/billiard/booking/occupancy'));
      await picker.fill(date);
      await picker.dispatchEvent('change');
      await loaded;
      await expect(page.locator('.o_qclub_grid_table')).toBeVisible();
    }
    const slots = page.locator('.o_qclub_slot_free');
    if (await slots.count()) {
      await slots.first().click();
      await expect(page.locator('.o_qclub_summary')).toContainText('Deposit:');
      await page.getByRole('button', { name: 'Book', exact: true }).click();
      await expect(page).toHaveURL(/\/billiard\/booking\/confirmation\/QB/);
      return;
    }
    day.setUTCDate(day.getUTCDate() + 1);
  }
  throw new Error('No free slot within the booking window');
}

for (const outcome of ['done', 'error']) {
  test(`test_pay_003_pay_007_demo_${outcome}`, async ({ page }, testInfo) => {
    // Dedicated accounts prevent unpaid holds from affecting other specs/projects.
    const customer = testInfo.project.name === 'mobile-chromium'
      ? 'demo-customer-pay-mobile' : 'demo-customer-pay';
    await bookFreeSlot(page, customer);
    const confirmation = page.url();
    const form = page.locator('#o_payment_form');
    await expect(form).toBeVisible();
    const demo = form.locator(
      'input[name="o_payment_radio"][data-provider-code="demo"][data-payment-option-type="payment_method"]',
    );
    await expect(demo).toHaveCount(1);
    await demo.check();
    // payment_demo.inline_form renders a provider-specific container. Scope here
    // to avoid selecting a hidden express-checkout or saved-token form.
    const providerId = await demo.getAttribute('data-provider-id');
    const inline = form.locator(`#demo-container-${providerId}`);
    await expect(inline).toBeVisible();
    await inline.locator('select#simulated_payment_state').selectOption(outcome);
    await inline.locator('input#customer_input').fill('Offline demo payment');
    await form.getByRole('button', { name: 'Pay deposit', exact: true }).click();
    if (outcome === 'done') {
      await expect(page).toHaveURL(confirmation);
      await expect(page.locator('.o_qclub_confirmation')).toContainText('Confirmed', { timeout: 30000 });
      await expect(page.locator('#o_payment_form')).toHaveCount(0);
    } else {
      // The status page redirects to the confirmation page on its own; wait for that
      // instead of navigating while the redirect is still in flight.
      await page.waitForURL(confirmation, { timeout: 30000 });
      await page.waitForLoadState('load');
      await page.reload();
      await expect(page.locator('.o_qclub_confirmation')).toContainText('Awaiting Deposit');
      await expect(page.locator('#o_payment_form')).toBeVisible();
    }
  });
}
