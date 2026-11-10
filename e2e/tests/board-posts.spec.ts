import { test, expect, Page } from '@playwright/test';

// All RPCs run in the browser: Node cannot reliably resolve *.localhost.
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

async function login(page: Page, user: string, target = '/billiard/booking') {
  await page.goto('/web/login?redirect=' + encodeURIComponent(target));
  await page.locator('input[name="login"]').fill(user);
  await page.locator('input[name="password"]').fill('demo');
  await page.getByRole('button', { name: 'Log in', exact: true }).click();
  await expect(page.locator('.o_qclub_booking_grid')).toBeVisible();
}

async function orm(page: Page, model: string, method: string, args: unknown[]) {
  return rpc(page, `/web/dataset/call_kw/${model}/${method}`, { model, method, args, kwargs: {} });
}

test('test_brd_004_brd_006_brd_007_brd_008_brd_009_brd_025_brd_029_posts_in_booking_grid', async ({ page, browser }, info) => {
  const mobile = info.project.name === 'mobile-chromium';
  const customer = mobile ? 'demo-customer-c' : 'demo-customer-a';
  const staffContext = await browser.newContext({ baseURL: info.project.use.baseURL });
  const visitorContext = await browser.newContext({ baseURL: info.project.use.baseURL });
  const staff = await staffContext.newPage();
  const visitor = await visitorContext.newPage();
  const bookingIds: number[] = [];
  try {
    await login(page, customer);
    await expect(page.locator('.o_qclub_grid_table')).toBeVisible();
    const session = await rpc(page, '/web/session/get_session_info', {});
    const partnerId = session.partner_id;
    expect(partnerId).toBeTruthy();
    await login(staff, 'demo-staff');
    const minimum = await page.locator('.o_qclub_booking_date').getAttribute('min');
    const day = new Date(`${minimum}T12:00:00Z`);
    // Desktop and mobile use separate future days. Find fresh slots on EVERY run.
    day.setUTCDate(day.getUTCDate() + (mobile ? 11 : 10));
    const date = day.toISOString().slice(0, 10);
    const availability = await rpc(page, '/billiard/booking/occupancy', { date });
    let chosen: { table: number; start: string; index: number } | undefined;
    for (const table of availability.tables) {
      const index = table.slots.findIndex((state: string, i: number) => state === 'free' &&
        table.slots[i + 1] === 'free' && table.slots[i + 2] === 'free' &&
        Date.parse(availability.slots[i + 2].start) - Date.parse(availability.slots[i].start) === 7200000);
      if (index >= 0) { chosen = { table: table.id, start: availability.slots[index].start, index }; break; }
    }
    expect(chosen, 'Need three fresh consecutive future slots; reset demo if full').toBeTruthy();
    const slot = chosen!;
    // Create as staff in the back office, then confirm as staff. This avoids existing
    // customer unpaid holds and never relies on earlier test runs.
    const booking = await orm(staff, 'qclub.booking', 'create', [{
      table_id: slot.table, partner_id: partnerId,
      start: slot.start.replace('T', ' ').replace('Z', ''), duration_hours: 2,
    }]);
    bookingIds.push(booking);
    await orm(staff, 'qclub.booking', 'action_confirm', [[booking]]);
    const pending = await orm(staff, 'qclub.booking', 'create', [{
      table_id: slot.table, partner_id: partnerId,
      start: availability.slots[slot.index + 2].start.replace('T', ' ').replace('Z', ''), duration_hours: 1,
    }]);
    bookingIds.push(pending);
    const records = await orm(staff, 'qclub.booking', 'read', [[booking], ['name']]);
    await page.goto('/billiard/booking/confirmation/' + records[0].name);
    await page.getByRole('link', { name: 'Find players', exact: true }).click();
    const panel = page.locator('.o_qclub_post_panel');
    await expect(panel.getByRole('heading', { name: 'Find players' })).toBeVisible();
    await expect(page.locator('.o_qclub_selection')).toBeHidden();
    const ownPending = page.locator(`.o_qclub_board_marker[data-table-id="${slot.table}"][data-slot-index="${slot.index + 2}"]`);
    await ownPending.press('Enter');
    await expect(panel).toContainText('Your booking must be confirmed before you can find players.');
    const ownFirst = page.locator(`.o_qclub_board_marker[data-table-id="${slot.table}"][data-slot-index="${slot.index}"]`);
    // Mouse / touch: occupied cells disable pointer events unless they carry a marker.
    await ownFirst.click();
    const message = '<script>window.boardXss = true</script> https://example.invalid';
    await panel.getByLabel(/Message/).fill(message);
    await panel.locator('label', { hasText: 'Intermediate' }).click();
    await panel.getByLabel('Players wanted', { exact: true }).fill('2');
    const terms = panel.getByRole('checkbox', { name: 'I agree to the Community Guidelines' });
    if (await terms.count()) await terms.check();
    await panel.getByRole('button', { name: 'Find players', exact: true }).click();
    await expect(panel.locator('.o_qclub_post_message')).toHaveText(message);
    await expect(panel.locator('script, .o_qclub_post_message a')).toHaveCount(0);
    expect(await page.evaluate(() => (window as any).boardXss)).toBeUndefined();
    const summary = await rpc(page, '/billiard/booking/board', { date });
    const own = summary.own_bookings.find((item: any) => item.booking_id === booking);
    const postId = own.post_id;
    expect(postId).toBeTruthy();
    const markers = page.locator(`.o_qclub_board_marker[data-table-id="${slot.table}"]`);
    await expect(markers).toHaveCount(3);
    await expect(page.locator('.o_qclub_board_list')).toContainText('Join · 2');
    await visitor.goto(`/billiard/booking?date=${date}&post=${postId}`);
    const visitorPanel = visitor.locator('.o_qclub_post_panel');
    await expect(visitorPanel.getByRole('heading', { name: 'Q Club Player' })).toBeVisible();
    await expect(visitor.locator(`.o_qclub_board_marker[data-table-id="${slot.table}"]`)).toHaveCount(2);
    const plain = visitor.locator(`.o_qclub_slot_occupied[data-table-id="${slot.table}"][data-slot-index="${slot.index + 2}"]`);
    await expect(plain).toHaveAttribute('aria-disabled', 'true');
    await expect(plain).not.toHaveAttribute('role', 'button');
    await visitorPanel.getByRole('link', { name: 'Apply to join' }).click();
    await visitor.locator('input[name="login"]').fill(mobile ? 'demo-customer-b' : 'demo-customer-c');
    await visitor.locator('input[name="password"]').fill('demo');
    await visitor.getByRole('button', { name: 'Log in', exact: true }).click();
    await expect(visitor).toHaveURL(new RegExp(`post=${postId}`));
    await expect(visitorPanel.locator('.o_qclub_post_message')).toHaveText(message);
    await expect(visitorPanel.getByRole('heading')).not.toHaveText('Q Club Player');
    // Selecting free time closes the post panel and preserves the original quote flow.
    await page.locator('.o_qclub_slot_free').first().click();
    await expect(panel).toBeHidden();
    await expect(page.locator('.o_qclub_selection')).toBeVisible();
    await page.route('**/billiard/booking/board', route => route.abort());
    await page.reload();
    await expect(page.locator('.o_qclub_grid_table')).toBeVisible();
    await page.locator('.o_qclub_slot_free').first().click();
    await expect(page.locator('.o_qclub_summary')).toContainText('Table fee:');
  } finally {
    for (const id of bookingIds) await orm(staff, 'qclub.booking', 'action_cancel', [[id]]);
    await staffContext.close();
    await visitorContext.close();
  }
});
