import { test, expect, Page } from '@playwright/test';

// Use browser fetch, including back-office setup: Node cannot resolve *.localhost.
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

test('test_brd_010_brd_011_brd_012_brd_013_brd_025_brd_029_join_accept_and_login_return', async ({ page, browser }, info) => {
  const mobile = info.project.name === 'mobile-chromium';
  // Explicitly propagate device options to the second customer's UI as well.
  const options = { ...info.project.use, baseURL: info.project.use.baseURL };
  const staffContext = await browser.newContext({ baseURL: info.project.use.baseURL });
  const applicantContext = await browser.newContext(options);
  const visitorContext = await browser.newContext(options);
  const staff = await staffContext.newPage();
  const applicant = await applicantContext.newPage();
  const visitor = await visitorContext.newPage();
  let booking: number | undefined;
  try {
    await login(page, mobile ? 'demo-customer-c' : 'demo-customer-a');
    await login(staff, 'demo-staff');
    const owner = (await rpc(page, '/web/session/get_session_info', {})).partner_id;
    const minimum = await page.locator('.o_qclub_booking_date').getAttribute('min');
    let chosen: { date: string; table: number; start: string } | undefined;
    // Search future days anew on every run; no dependency on today's free slots.
    for (let offset = mobile ? 8 : 5; offset <= (mobile ? 10 : 7) && !chosen; offset++) {
      const day = new Date(`${minimum}T12:00:00Z`);
      day.setUTCDate(day.getUTCDate() + offset);
      const date = day.toISOString().slice(0, 10);
      const data = await rpc(page, '/billiard/booking/occupancy', { date });
      for (const table of data.tables) {
        const index = table.slots.findIndex((state: string) => state === 'free');
        if (index >= 0) { chosen = { date, table: table.id, start: data.slots[index].start }; break; }
      }
    }
    expect(chosen, 'Need a fresh future slot').toBeTruthy();
    const slot = chosen!;
    booking = await orm(staff, 'qclub.booking', 'create', [{
      table_id: slot.table, partner_id: owner,
      start: slot.start.replace('T', ' ').replace('Z', ''), duration_hours: 1,
    }]);
    await orm(staff, 'qclub.booking', 'action_confirm', [[booking]]);
    await page.goto(`/billiard/booking?date=${slot.date}&booking=${booking}`);
    const panel = page.locator('.o_qclub_post_panel');
    await panel.getByLabel(/Message/).fill('Join test');
    const terms = panel.getByRole('checkbox');
    if (await terms.count()) await terms.check();
    await panel.getByRole('button', { name: 'Find players', exact: true }).click();
    await expect(panel.locator('.o_qclub_post_message')).toHaveText('Join test');
    const summary = await rpc(page, '/billiard/booking/board', { date: slot.date });
    const post = summary.own_bookings.find((item: any) => item.booking_id === booking).post_id;
    const target = `/billiard/booking?date=${slot.date}&post=${post}`;
    await applicant.goto(target);
    const ap = applicant.locator('.o_qclub_post_panel');
    await ap.getByRole('link', { name: 'Apply to join', exact: true }).click();
    await applicant.locator('input[name="login"]').fill('demo-customer-b');
    await applicant.locator('input[name="password"]').fill('demo');
    await applicant.getByRole('button', { name: 'Log in', exact: true }).click();
    await expect(applicant).toHaveURL(new RegExp(`post=${post}`));
    const payload = '<script>window.boardJoinXss = true</script> https://example.invalid';
    const replyForm = ap.locator('form').filter({ has: applicant.getByRole('button', { name: 'Reply', exact: true }) });
    await replyForm.getByLabel(/Reply/).fill(payload);
    const replyTerms = replyForm.getByRole('checkbox');
    if (await replyTerms.count()) await replyTerms.check();
    await replyForm.getByRole('button', { name: 'Reply', exact: true }).click();
    await expect(ap.locator('.o_qclub_reply_message')).toHaveText(payload);
    await ap.getByLabel(/Application message/).fill(payload);
    await ap.getByRole('button', { name: 'Apply to join', exact: true }).click();
    await expect(ap).toContainText('Waiting');
    await page.reload();
    await expect(panel.locator('.o_qclub_application_message')).toHaveText(payload);
    await panel.getByRole('button', { name: 'Accept', exact: true }).click();
    await expect(panel).toContainText('Accepted');
    await expect(page.locator(`.o_qclub_board_marker[data-table-id="${slot.table}"]`)).toHaveText('Full');
    await applicant.reload();
    await expect(ap).toContainText('Accepted');
    await expect(ap.getByRole('button', { name: 'Withdraw', exact: true })).toBeVisible();
    await visitor.goto(target);
    const vp = visitor.locator('.o_qclub_post_panel');
    await expect(vp.locator('.o_qclub_application_message')).toHaveCount(0);
    const detail = await rpc(visitor, '/billiard/booking/post', { post });
    expect(detail.accepted).toEqual([{ display_name: 'Q Club Player' }]);
    expect(detail.application).toBeNull();
    expect(detail.applications).toBeUndefined();
    for (const view of [page, applicant, visitor]) {
      await expect(view.locator('.o_qclub_post_panel script, .o_qclub_reply_message a, .o_qclub_application_message a')).toHaveCount(0);
      expect(await view.evaluate(() => (window as any).boardJoinXss)).toBeUndefined();
    }
    await ap.getByRole('button', { name: 'Withdraw', exact: true }).click();
    await expect(ap).toContainText('Withdrawn');
    await page.reload();
    await expect(page.locator(`.o_qclub_board_marker[data-table-id="${slot.table}"]`)).toHaveText('Join · 1');
  } finally {
    if (booking) await orm(staff, 'qclub.booking', 'action_cancel', [[booking]]);
    await staffContext.close();
    await applicantContext.close();
    await visitorContext.close();
  }
});
