import { test, expect } from '@playwright/test';

const API_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || 'http://127.0.0.1:8000';

test.describe('Full-Stack Browser-to-FastAPI (PostgreSQL) E2E', () => {
  test('real auth cookie lifecycle, postcode lookup/cleanse, API key create/revoke, and tracking privacy', async ({ page, context }) => {
    const uniq = `${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
    const email = `e2e_${uniq}@postcodelink.ng`;
    const password = 'E2eStrongPassword123!';

    // 1. Register a real merchant account in PostgreSQL via FastAPI
    const regRes = await page.request.post(`${API_URL}/api/v1/auth/register`, {
      data: {
        full_name: 'E2E Fullstack Merchant',
        email,
        password,
        business_name: 'E2E Logistics Ltd',
        phone: `+23480${String(Date.now()).slice(-8)}`,
      },
    });
    expect(regRes.status()).toBe(201);

    // 2. Open app, switch to Address Cleanser sub-tab, verify sample data badge is visible
    await page.goto('/');
    await page.getByRole('button', { name: /Address Cleanser & Normaliser/i }).click();
    await expect(page.getByTestId('sample-data-badge')).toBeVisible();

    // 3. Log in via real FastAPI /auth/login (issues HttpOnly postcodelink_session cookie to browser context)
    const loginRes = await page.request.post(`${API_URL}/api/v1/auth/login`, {
      data: { email, password },
    });
    expect(loginRes.status()).toBe(200);

    // Verify HttpOnly session cookie was issued by FastAPI and survives page reload
    await expect.poll(async () => {
      const cookies = await context.cookies();
      return cookies.some((c) => c.name === 'postcodelink_session' && c.httpOnly);
    }).toBe(true);

    await page.reload();
    const meRes = await page.request.get(`${API_URL}/api/v1/auth/me`);
    expect(meRes.status()).toBe(200);
    const meBody = await meRes.json();
    expect(meBody.email).toBe(email);

    // 4. Real Postcode Lookup & Address Cleanse against FastAPI + PostgreSQL
    const lookupRes = await page.request.get(`${API_URL}/api/v1/postcodes/lookup?code=100001`);
    expect(lookupRes.status()).toBe(200);
    const lookupBody = await lookupRes.json();
    expect(lookupBody.count).toBeGreaterThan(0);
    expect(lookupBody.matches[0].code).toBe('100001');
    expect(lookupBody.verification_status).toBe('local_reference');

    await page.getByRole('button', { name: /Address Cleanser & Normaliser/i }).click();
    await page.getByRole('button', { name: /Cleanse & Standardise Address/i }).click();
    await expect(page.getByText(/Local Reference/i).first()).toBeVisible({ timeout: 10000 });

    // 4. Real API key creation, authentication, and revocation
    const createKeyRes = await page.request.post(`${API_URL}/api/v1/api-keys/`, {
      headers: { 'X-Requested-With': 'XMLHttpRequest', Origin: 'http://127.0.0.1:3000' },
      data: { name: 'E2E Test Key', monthly_quota: 50, environment: 'test' },
    });
    expect(createKeyRes.status()).toBe(201);
    const keyData = await createKeyRes.json();
    expect(keyData.api_key).toMatch(/^pl_test_/);

    const commercialRes = await page.request.get(`${API_URL}/api/v1/postcodes/commercial/lookup?state=Lagos`, {
      headers: { 'x-api-key': keyData.api_key },
    });
    expect(commercialRes.status()).toBe(200);
    const commercialBody = await commercialRes.json();
    expect(commercialBody.is_live_nipost).toBe(false);

    const revokeRes = await page.request.delete(`${API_URL}/api/v1/api-keys/${keyData.id}`, {
      headers: { 'X-Requested-With': 'XMLHttpRequest', Origin: 'http://127.0.0.1:3000' },
    });
    expect(revokeRes.status()).toBe(200);

    const revokedLookup = await page.request.get(`${API_URL}/api/v1/postcodes/commercial/lookup?state=Lagos`, {
      headers: { 'x-api-key': keyData.api_key },
    });
    expect(revokedLookup.status()).toBe(401);

    // 5. Real Delivery creation & public tracking privacy check
    const delRes = await page.request.post(`${API_URL}/api/v1/deliveries/`, {
      headers: { 'X-Requested-With': 'XMLHttpRequest', Origin: 'http://127.0.0.1:3000' },
      data: {
        recipient_name: 'Chinedu Okafor',
        recipient_phone: '+2348031234567',
        destination_address: '10 Obafemi Awolowo Way, Ikeja, Lagos',
        destination_area: 'Ikeja',
        destination_state: 'Lagos',
        postcode_input: '100001',
        package_description: 'E2E Test Parcel',
      },
    });
    expect(delRes.status()).toBe(201);
    const delBody = await delRes.json();
    expect(delBody.tracking_token).toBeTruthy();

    const trackRes = await page.request.get(`${API_URL}/api/v1/deliveries/track/${delBody.tracking_token}`);
    expect(trackRes.status()).toBe(200);
    const trackBody = await trackRes.json();
    expect(trackBody.recipient_name_masked).not.toBe('Chinedu Okafor');
    expect(trackBody.otp_hash).toBeUndefined();

    // 6. Logout clears session cookie
    const logoutRes = await page.request.post(`${API_URL}/api/v1/auth/logout`, {
      headers: { 'X-Requested-With': 'XMLHttpRequest', Origin: 'http://127.0.0.1:3000' },
    });
    expect(logoutRes.status()).toBe(200);
    const meAfterLogout = await page.request.get(`${API_URL}/api/v1/auth/me`);
    expect(meAfterLogout.status()).toBe(401);
  });
});
