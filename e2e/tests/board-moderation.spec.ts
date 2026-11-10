import { test, expect, Page } from '@playwright/test';

// All requests run in the browser: Node cannot resolve *.localhost.
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
async function login(page: Page, user: string, password = 'demo') {
  await page.goto('/web/login?redirect=%2Fbilliard%2Fbooking');
  await page.locator('input[name="login"]').fill(user);
  await page.locator('input[name="password"]').fill(password);
  await page.getByRole('button', { name: 'Log in', exact: true }).click();
  await expect(page.locator('.o_qclub_grid_table')).toBeVisible();
}
async function action(page: Page, xmlid: string) {
  const result = await rpc(page, '/web/action/load', { action_id: `qclub_billiard.${xmlid}` });
  await page.goto(`/odoo/action-${result.id}`);
}

test('test_brd_020_brd_021_brd_022_brd_023_report_hide_ban_real_clicks', async ({ page, browser }, info) => {
  test.setTimeout(120000); // Longest flow: four sessions, including the back office.
  const customerOptions = { ...info.project.use, baseURL: info.project.use.baseURL };
  // Back-office work happens on a desktop browser, whichever project runs the customer side.
  const backOfficeOptions = { baseURL: info.project.use.baseURL, viewport: { width: 1280, height: 800 } };
  const staffContext = await browser.newContext(backOfficeOptions);
  const adminContext = await browser.newContext(backOfficeOptions);
  const customerContext = await browser.newContext(customerOptions);
  const staff = await staffContext.newPage();
  const admin = await adminContext.newPage();
  const customer = await customerContext.newPage();
  const unique = `moderation-${info.project.name}-${Date.now()}`;
  let booking: number | undefined;
  let user: number | undefined;
  let partner: number | undefined;
  let website: number | undefined;
  try {
    await login(admin, 'admin', 'admin');
    const groups = await orm(admin, 'ir.model.data', 'search_read', [
      [['module', '=', 'base'], ['name', '=', 'group_portal']], ['res_id'],
    ]);
    user = await orm(admin, 'res.users', 'create', [{
      login: unique, name: unique, password: 'demo', group_ids: [[6, 0, [groups[0].res_id]]],
    }]);
    partner = (await orm(admin, 'res.users', 'read', [[user], ['partner_id']]))[0].partner_id[0];
    website = (await orm(admin, 'website', 'search_read', [[['name', '=', 'Q Club']], ['id']]))[0].id;
    await login(page, info.project.name === 'mobile-chromium' ? 'demo-customer-c' : 'demo-customer-a');
    await login(customer, unique);
    await login(staff, 'demo-staff');
    const owner = (await rpc(page, '/web/session/get_session_info', {})).partner_id;
    const minimum = await page.locator('.o_qclub_booking_date').getAttribute('min');
    let chosen: { date: string; table: number; start: string } | undefined;
    for (let offset = info.project.name === 'mobile-chromium' ? 12 : 11; offset <= 14 && !chosen; offset++) {
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
    await panel.getByLabel(/Message/).fill('Moderation post');
    const terms = panel.getByRole('checkbox');
    if (await terms.count()) await terms.check();
    await panel.getByRole('button', { name: 'Find players', exact: true }).click();
    await expect(panel.locator('.o_qclub_post_message')).toHaveText('Moderation post');
    const summary = await rpc(page, '/billiard/booking/board', { date: slot.date });
    const post = summary.own_bookings.find((item: any) => item.booking_id === booking).post_id;
    const target = `/billiard/booking?date=${slot.date}&post=${post}`;
    await customer.goto(target);
    const cp = customer.locator('.o_qclub_post_panel');
    const replyForm = cp.locator('form').filter({ has: customer.getByRole('button', { name: 'Reply', exact: true }) });
    await replyForm.getByLabel(/Reply/).fill(`Original ${unique}`);
    const replyTerms = replyForm.getByRole('checkbox');
    if (await replyTerms.count()) await replyTerms.check();
    await replyForm.getByRole('button', { name: 'Reply', exact: true }).click();
    await expect(cp.locator('.o_qclub_reply_message')).toHaveText(`Original ${unique}`);
    await page.reload();
    const row = panel.locator('div').filter({ has: page.locator('.o_qclub_reply_message') }).last();
    await row.getByRole('button', { name: 'Report', exact: true }).click();
    const report = row.locator('.o_qclub_report_form');
    await report.getByLabel('Abuse', { exact: true }).check();
    await report.getByLabel(/Report note/).fill(`<script>${unique}</script>`);
    await report.getByRole('button', { name: 'Submit report' }).click();
    await expect(report.getByRole('status')).toHaveText('Report submitted.');
    await report.getByRole('button', { name: 'Submit report' }).click();
    await expect(report.getByRole('status')).toHaveText('You have already reported this content.');
    await action(staff, 'qclub_board_report_action');
    // Reports default to New; identify this run by its reply author via the original content's post.
    const reports = await orm(admin, 'qclub.board.report', 'search_read', [
      [['reply_id.partner_id', '=', partner]], ['id'],
    ]);
    const loaded = await rpc(staff, '/web/action/load', { action_id: 'qclub_billiard.qclub_board_report_action' });
    await staff.goto(`/odoo/action-${loaded.id}/${reports[0].id}`);
    await expect(staff.locator('.o_field_widget[name="note"]')).toContainText(`<script>${unique}</script>`);
    await expect(staff.locator('.o_field_widget[name="note"] script')).toHaveCount(0);
    await staff.getByRole('button', { name: 'Hide and resolve', exact: true }).click();
    await expect(staff.locator('.o_notification')).toContainText('Content hidden and report resolved.');
    await expect(staff.locator('.ribbon')).toContainText('Hidden');
    await expect(staff.locator('.o_notification')).not.toContainText('cannot be found');
    // Staff get visible feedback: the action disappears once the content is hidden.
    await expect(staff.getByRole('button', { name: 'Hide and resolve', exact: true })).toHaveCount(0);
    await expect(staff.getByRole('button', { name: 'Dismiss report', exact: true })).toHaveCount(0);
    await customer.reload();
    await expect(cp.locator('.o_qclub_reply_message')).toHaveText('This reply was removed.');
    await expect(cp).not.toContainText(`Original ${unique}`);
    await expect(cp).not.toContainText(unique); // hidden author's name is also absent
    // Ban through the actual manager form; cleanup searches by the fresh customer even if save times out.
    await action(admin, 'qclub_board_ban_action');
    await admin.getByRole('button', { name: 'New', exact: true }).click();
    await admin.locator('.o_field_widget[name="partner_id"] input').fill(unique);
    await admin.getByRole('option', { name: unique, exact: true }).click();
    await admin.locator('.o_field_widget[name="website_id"] input').fill('Q Club');
    await admin.getByRole('option', { name: 'Q Club', exact: true }).click();
    await admin.locator('.o_field_widget[name="reason"] textarea').fill(`Private ${unique}`);
    await admin.locator('.o_form_button_save').click();
    await expect(admin.locator('.o_form_button_save')).not.toBeVisible();
    await replyForm.getByLabel(/Reply/).fill('Blocked attempt');
    await replyForm.getByRole('button', { name: 'Reply', exact: true }).click();
    await expect(cp.getByRole('alert')).toHaveText("Your account can't post on the board. Please contact Q Club.");
    await expect(customer.locator('.o_qclub_grid_table')).toBeVisible();
  } finally {
    try {
      if (partner && website) {
        const bans = await orm(admin, 'qclub.board.ban', 'search', [
          [['partner_id', '=', partner], ['website_id', '=', website], ['active', '=', true]],
        ]);
        if (bans.length) await orm(admin, 'qclub.board.ban', 'write', [bans, { active: false }]);
      }
      if (booking) await orm(admin, 'qclub.booking', 'action_cancel', [[booking]]);
      if (user) await orm(admin, 'res.users', 'write', [[user], { active: false }]);
    } finally {
      await staffContext.close();
      await adminContext.close();
      await customerContext.close();
    }
  }
});
