import { test, expect, Page } from '@playwright/test';

async function rpc(page: Page, route: string, params: object) {
  return page.evaluate(async ({ route, params }) => {
    const response = await fetch(route, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jsonrpc: '2.0', method: 'call', id: 1, params }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const body = await response.json();
    if (body.error) throw new Error(JSON.stringify(body.error));
    return body.result;
  }, { route, params });
}
async function orm(page: Page, model: string, method: string, args: unknown[]) {
  return rpc(page, `/web/dataset/call_kw/${model}/${method}`, { model, method, args, kwargs: {} });
}
async function login(page: Page, user: string) {
  await page.goto('/web/login?redirect=%2Fbilliard%2Fbooking');
  await page.locator('input[name="login"]').fill(user);
  await page.locator('input[name="password"]').fill('demo');
  await page.getByRole('button', { name: 'Log in', exact: true }).click();
  await expect(page.locator('.o_qclub_grid_table')).toBeVisible();
}

test('test_brd_030_brd_031_brd_032_brd_033_brd_034_account_links_date_click_and_reminders', async ({ page, browser }, info) => {
  test.setTimeout(60000); // Longest flow: several customers and page visits.
  const staffContext = await browser.newContext({ baseURL: info.project.use.baseURL });
  const staff = await staffContext.newPage();
  const applicantContext = await browser.newContext({ ...info.project.use, baseURL: info.project.use.baseURL });
  const applicant = await applicantContext.newPage();
  let booking: number | undefined;
  try {
    await login(page, info.project.name === 'mobile-chromium' ? 'demo-customer-c' : 'demo-customer-a');
    await login(staff, 'demo-staff');
    const partner = (await rpc(page, '/web/session/get_session_info', {})).partner_id;
    const input = page.locator('.o_qclub_booking_date');
    const minimum = (await input.getAttribute('min'))!;
    const maximum = (await input.getAttribute('max'))!;
    const count = (Date.parse(maximum) - Date.parse(minimum)) / 86400000 + 1;
    await expect(page.locator('.o_qclub_date_button')).toHaveCount(count);
    let selected: { date: string; table: number; start: string } | undefined;
    for (let offset = count - 1; offset >= 1 && !selected; offset--) {
      const day = new Date(`${minimum}T12:00:00Z`);
      day.setUTCDate(day.getUTCDate() + offset);
      const date = day.toISOString().slice(0, 10);
      const data = await rpc(page, '/billiard/booking/occupancy', { date });
      for (const table of data.tables) {
        const index = table.slots.findIndex((state: string) => state === 'free');
        if (index >= 0) { selected = { date, table: table.id, start: data.slots[index].start }; break; }
      }
    }
    expect(selected, 'A free future slot in the booking window is required').toBeTruthy();
    const slot = selected!;
    booking = await orm(staff, 'qclub.booking', 'create', [{
      table_id: slot.table, partner_id: partner, duration_hours: 1,
      start: slot.start.replace('T', ' ').replace('Z', ''),
    }]);
    await orm(staff, 'qclub.booking', 'action_confirm', [[booking]]);
    const [record] = await orm(staff, 'qclub.booking', 'read', [[booking], ['name']]);
    await page.goto('/my');
    await page.getByRole('link', { name: /My Bookings & Players/ }).click();
    const own = page.locator('#qclub_my_bookings article').filter({ hasText: record.name });
    await expect(own).toContainText('Confirmed');
    await own.getByRole('link', { name: 'Find players', exact: true }).click();
    const panel = page.locator('.o_qclub_post_panel');
    const message = `Account link ${booking}`;
    await panel.getByLabel(/Message/).fill(message);
    const terms = panel.getByRole('checkbox');
    if (await terms.count()) await terms.check();
    await panel.getByRole('button', { name: 'Find players', exact: true }).click();
    await expect(panel.locator('.o_qclub_post_message')).toHaveText(message);
    const data = await rpc(page, '/billiard/booking/board', { date: slot.date });
    const post = data.own_bookings.find((item: any) => item.booking_id === booking).post_id;
    await login(applicant, 'demo-customer-b');
    await applicant.goto(`/billiard/booking?date=${slot.date}&post=${post}`);
    const applicantPanel = applicant.locator('.o_qclub_post_panel');
    const payload = `<script>window.accountXss=true</script> Account reply ${booking}`;
    const replyForm = applicantPanel.locator('form').filter({
      has: applicant.getByRole('button', { name: 'Reply', exact: true }),
    });
    await replyForm.getByLabel(/Reply/).fill(payload);
    const replyTerms = replyForm.getByRole('checkbox');
    if (await replyTerms.count()) await replyTerms.check();
    await replyForm.getByRole('button', { name: 'Reply', exact: true }).click();
    await expect(applicantPanel.locator('.o_qclub_reply_message')).toHaveText(payload);
    await applicantPanel.getByRole('button', { name: 'Apply to join', exact: true }).click();
    await expect(applicantPanel).toContainText('Waiting');
    await applicant.goto('/my/billiard');
    await applicant.getByRole('tab', { name: /^My join requests/ }).click();
    const request = applicant.locator('#qclub_my_applications article').filter({
      has: applicant.locator(`a[href$="post=${post}"]`),
    });
    await expect(request).toContainText('Waiting');
    await request.getByRole('link').click();
    await expect(applicantPanel.locator('.o_qclub_post_message')).toHaveText(message);
    await page.goto('/my/billiard');
    await page.getByRole('tab', { name: /^Messages/ }).click();
    const reply = page.locator('#qclub_my_messages article').filter({ hasText: payload });
    await expect(reply).toHaveCount(1);
    await expect(reply.locator('script')).toHaveCount(0);
    expect(await page.evaluate(() => (window as any).accountXss)).toBeUndefined();
    await reply.getByRole('link').click();
    await expect(panel.locator('.o_qclub_post_message')).toHaveText(message);
    await page.goto('/my/billiard');
    await page.getByRole('tab', { name: /^My posts/ }).click();
    await page.locator(`#qclub_my_posts a[href$="post=${post}"]`).click();
    await expect(panel.locator('.o_qclub_post_message')).toHaveText(message);
    const button = page.locator(`.o_qclub_date_button[data-date="${slot.date}"]`);
    await expect(button.locator('.o_qclub_date_dot')).toBeVisible();
    await input.fill(minimum);
    await input.dispatchEvent('change');
    await expect(page.locator(`.o_qclub_date_button[data-date="${minimum}"]`)).toHaveAttribute('aria-current', 'date');
    await button.click();
    await expect(input).toHaveValue(slot.date);
    await expect(button).toHaveAttribute('aria-current', 'date');
    await expect(page.locator('.o_qclub_grid_table')).toBeVisible();
    // Failure of optional reminders must still allow a real date click.
    await page.route('**/billiard/booking/reminders', route => route.abort());
    await page.reload();
    await page.locator(`.o_qclub_date_button[data-date="${minimum}"]`).click();
    await expect(input).toHaveValue(minimum);
    await expect(page.locator('.o_qclub_grid_table')).toBeVisible();
  } finally {
    if (booking) await orm(staff, 'qclub.booking', 'action_cancel', [[booking]]);
    await applicantContext.close();
    await staffContext.close();
  }
});

test('test_brd_030_brd_034_anonymous_login_return_and_public_date_dots', async ({ page }) => {
  await page.goto('/my/billiard');
  await expect(page).toHaveURL(/\/web\/login\?redirect=/);
  await page.goto('/billiard/booking');
  const input = page.locator('.o_qclub_booking_date');
  const minimum = (await input.getAttribute('min'))!;
  const maximum = (await input.getAttribute('max'))!;
  await expect(page.locator('.o_qclub_date_button')).toHaveCount(
    (Date.parse(maximum) - Date.parse(minimum)) / 86400000 + 1,
  );
  const reminders = await rpc(page, '/billiard/booking/reminders', {});
  expect(Object.keys(reminders)).toEqual(['dates']);
  expect(reminders.dates.length, 'Demo data has bookings; run make demo-reset').toBeGreaterThan(0);
  expect(reminders.dates.every((day: string) => /^\d{4}-\d{2}-\d{2}$/.test(day))).toBe(true);
  // Earliest date is a demo booking, not one a parallel test may cancel.
  await expect(page.locator(`.o_qclub_date_button[data-date="${reminders.dates[0]}"] .o_qclub_date_dot`)).toBeVisible();
  await page.locator(`.o_qclub_date_button[data-date="${maximum}"]`).click();
  await expect(input).toHaveValue(maximum);
  await expect(page.locator(`.o_qclub_date_button[data-date="${maximum}"]`)).toHaveAttribute('aria-current', 'date');
});
