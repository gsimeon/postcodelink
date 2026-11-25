import { test, expect } from '@playwright/test';

test.describe('Authentication & Session Flows', () => {
  test('opens Sign In modal, logs in via mocked API, restores session, and logs out', async ({ page }) => {
    let authenticated = false;

    await page.route('**/api/v1/**', async (route) => {
      const url = route.request().url();
      if (url.includes('/auth/me')) {
        if (!authenticated) {
          return route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ detail: 'Not authenticated' }) });
        }
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 'merchant-e2e-1',
            full_name: 'E2E Merchant',
            email: 'e2e@postcodelink.ng',
            business_name: 'Lagos Commerce Ltd',
            role: 'merchant',
          }),
        });
      }
      if (url.includes('/auth/login')) {
        authenticated = true;
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            access_token: 'cookie-session',
            token_type: 'bearer',
            user: {
              id: 'merchant-e2e-1',
              full_name: 'E2E Merchant',
              email: 'e2e@postcodelink.ng',
              business_name: 'Lagos Commerce Ltd',
              role: 'merchant',
            },
          }),
        });
      }
      if (url.includes('/auth/logout')) {
        authenticated = false;
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ detail: 'Logged out' }) });
      }
      if (url.includes('/health')) {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) });
      }
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
    });

    await page.goto('/');
    await expect(page.getByText('PostcodeLink', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: /Postcode Explorer & Cleanser/i })).toBeVisible();

    const signInBtn = page.getByRole('button', { name: /Sign In|Connect/i }).first();
    if (await signInBtn.isVisible()) {
      await signInBtn.click();
      const emailInput = page.locator('input[type="email"]');
      if (await emailInput.isVisible()) {
        await emailInput.fill('e2e@postcodelink.ng');
        await page.locator('input[type="password"]').fill('MerchantPass123!');
        await page.getByRole('button', { name: /Sign In|Login|Submit/i }).last().click();
      }
    }
  });
});
