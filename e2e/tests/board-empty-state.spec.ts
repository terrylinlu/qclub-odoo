import { test, expect, Page } from '@playwright/test';

const emptyBoard = {
  posts: [],
  own_bookings: [],
  terms: 'Be respectful and do not share personal contact details.',
  terms_accepted: false,
  max_players: 3,
  date_label: 'Sat 14 Nov',
};

async function showBoard(page: Page, result: object) {
  await page.route('**/billiard/booking/board', async route => {
    const { id } = route.request().postDataJSON();
    await route.fulfill({ json: { jsonrpc: '2.0', id, result } });
  });
  await page.goto('/billiard/booking');
}

test('test_brd_022_empty_day_shows_message', async ({ page }) => {
  await showBoard(page, emptyBoard);
  const list = page.locator('.o_qclub_board_list');
  const message = list.locator('p.o_qclub_board_empty');
  await expect(message).toHaveCount(1);
  await expect(message).toBeVisible();
  expect(await message.textContent()).toBe('No one is looking for players on Sat 14 Nov yet.');
  await expect(message).toHaveClass('text-muted mb-0 small o_qclub_board_empty');
  await expect(list.locator('h2')).toHaveCount(0);
});

test('test_brd_022_day_with_posts_has_no_empty_message', async ({ page }) => {
  await showBoard(page, {
    ...emptyBoard,
    posts: [{
      id: 1,
      // A synthetic table ID keeps mark() harmless regardless of grid occupancy.
      table_id: 2147483647,
      start: '2026-11-14T08:30:00Z',
      hours: 1,
      time_label: '19:00–20:00',
      table_name: 'Test table',
      display_name: 'Q Club Player',
      level: 'any',
      remaining: 2,
    }],
  });
  const list = page.locator('.o_qclub_board_list');
  await expect(list.locator('h2')).toHaveText('Players wanted on Sat 14 Nov');
  await expect(list.getByRole('button')).toHaveText('19:00–20:00 · Test table · Q Club Player · Join · 2');
  await expect(page.locator('.o_qclub_board_empty')).toHaveCount(0);
});

test('test_brd_022_login_required_has_no_empty_message', async ({ page }) => {
  await showBoard(page, { error: 'login_required' });
  const link = page.locator('.o_qclub_board_list').getByRole('link', {
    name: 'Log in to view players wanted', exact: true,
  });
  await expect(link).toBeVisible();
  await expect(link).toHaveAttribute('href', /^\/web\/login\?redirect=/);
  await expect(page.locator('.o_qclub_board_empty')).toHaveCount(0);
});
