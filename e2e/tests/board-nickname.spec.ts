import { test, expect } from '@playwright/test';

test('test_brd_001_brd_002_brd_026_login_set_nickname_mobile', async ({ page }, testInfo) => {
  await page.goto('/billiard/board/nickname');
  await expect(page).toHaveURL(/\/web\/login\?redirect=/);
  await page.locator('input[name="login"]').fill(testInfo.project.name.startsWith('mobile') ? 'demo-customer-b' : 'demo-customer-c');
  await page.locator('input[name="password"]').fill('demo');
  await page.getByRole('button', { name: 'Log in', exact: true }).click();
  await expect(page).toHaveURL(/\/billiard\/board\/nickname$/);
  await page.getByLabel('Nickname', { exact: true }).fill('a@b.com');
  await page.getByRole('button', { name: 'Save nickname' }).click();
  await expect(page.getByRole('alert')).toContainText('Nickname cannot be an email address or phone number.');
  // A fresh name on every run; no assumptions about the saved nickname.
  const nickname = `Cue${testInfo.project.name.startsWith('mobile') ? 'M' : 'D'}${Date.now().toString(36).replace(/[0-9]/g, d => String.fromCharCode(97 + Number(d)))}`;
  await page.getByLabel('Nickname', { exact: true }).fill(nickname);
  await expect(page.getByRole('button', { name: 'Save nickname' })).toBeInViewport();
  await page.getByRole('button', { name: 'Save nickname' }).click();
  await expect(page).toHaveURL(/\/billiard\/board$/);
  await expect(page.locator('.o_qclub_board')).toContainText(nickname);
  await expect(page.locator('.o_qclub_board')).toContainText('Player posts are coming soon.');
});
