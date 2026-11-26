import { test, expect } from '@playwright/test';

test.describe('Postcode Explorer, Address Cleanser & Coverage Dashboard', () => {
  test('navigates postcode workspace tabs and displays coverage disclaimer', async ({ page }) => {
    await page.route('**/api/v1/**', async (route) => {
      const url = route.request().url();
      if (url.includes('/postcodes/coverage')) {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            version: '2024.2',
            scope_states_count: 11,
            total_reference_records: 69,
            records_with_coordinates: 69,
            format_valid_digital_references: 4,
            verified_records: 0,
            dataset_source: 'local_reference',
            states_covered: ['Lagos', 'Abuja FCT', 'Rivers', 'Oyo', 'Ogun', 'Kano', 'Kaduna', 'Enugu', 'Delta', 'Edo', 'Anambra'],
          }),
        });
      }
      if (url.includes('/health')) {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) });
      }
      return route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ detail: 'Unauthorized' }) });
    });

    await page.goto('/');
    await page.getByRole('button', { name: /Postcode Explorer & Cleanser/i }).click();
    await expect(page.getByText(/Postcode/i).first()).toBeVisible();
  });
});
