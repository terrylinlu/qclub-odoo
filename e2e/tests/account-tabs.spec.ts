import { test, expect } from '@playwright/test';

test('test_brd_031_account_tabs_restore_and_fit_viewport', async ({ page }) => {
  await page.goto('/web/login?redirect=%2Fmy%2Fbilliard');
  await page.locator('input[name="login"]').fill('demo-customer-a');
  await page.locator('input[name="password"]').fill('demo');
  await page.getByRole('button', { name: 'Log in', exact: true }).click();
  const account = page.locator('.o_qclub_my_account');
  const panes = account.locator('[role="tabpanel"]');
  await expect(panes).toHaveCount(4);
  await expect(account.locator('[role="tabpanel"]:visible')).toHaveCount(1);
  await expect(page.locator('#qclub_my_bookings')).toBeVisible();
  for (const [label, id] of [['My posts', 'qclub_my_posts'], ['My join requests', 'qclub_my_applications'], ['Messages', 'qclub_my_messages']]) {
    await account.getByRole('tab', { name: new RegExp(`^${label}`) }).click();
    await expect(page.locator(`#${id}`)).toBeVisible();
    await expect(account.locator('[role="tabpanel"]:visible')).toHaveCount(1);
  }
  await expect(page).toHaveURL(/#messages$/);
  await page.reload();
  await expect(page.locator('#qclub_my_messages')).toBeVisible();
  await expect(account.locator('[role="tabpanel"]:visible')).toHaveCount(1);
  await page.goto('about:blank'); // A hash-only goto would not reload the page.
  await page.goto('/my/billiard#unknown');
  await expect(page.locator('#qclub_my_bookings')).toBeVisible();
  await expect(account.locator('[role="tabpanel"]:visible')).toHaveCount(1);
  const bookings = account.getByRole('tab', { name: /^My bookings/ });
  await bookings.focus();
  await bookings.press('ArrowLeft');
  await expect(account.getByRole('tab', { name: /^Messages/ })).toBeFocused();
  await expect(page.locator('#qclub_my_messages')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});
