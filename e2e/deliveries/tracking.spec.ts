import { test, expect } from '@playwright/test';

test.describe('Deliveries & Public Tracking Portal', () => {
  test('opens Public Tracking Portal tab', async ({ page }) => {
    await page.route('**/api/v1/**', async (route) => {
      const url = route.request().url();
      if (url.includes('/health')) {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) });
      }
      return route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ detail: 'Unauthorized' }) });
    });

    await page.goto('/');
    await page.getByRole('button', { name: /Public Tracking Portal/i }).click();
    await expect(page.getByText(/Tracking/i).first()).toBeVisible();
  });
});
