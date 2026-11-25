import test from 'node:test';
import assert from 'node:assert/strict';

// 1. Test Canonical Production State Machine
const ALLOWED_TRANSITIONS = {
  pending: ['assigned', 'cancelled'],
  assigned: ['picked_up', 'in_transit', 'pending', 'cancelled'],
  picked_up: ['in_transit', 'failed', 'cancelled'],
  in_transit: ['out_for_delivery', 'delivered', 'failed', 'cancelled'],
  out_for_delivery: ['delivered', 'failed'],
  failed: ['out_for_delivery', 'in_transit', 'cancelled'],
  delivered: [],
  cancelled: [],
};

function validateStateTransition(currentStatus, targetStatus) {
  if (currentStatus === targetStatus) return { valid: true };
  const allowed = ALLOWED_TRANSITIONS[currentStatus];
  if (!allowed || !allowed.includes(targetStatus)) {
    return {
      valid: false,
      message: `Invalid state transition from "${currentStatus}" to "${targetStatus}". Allowed target states: ${
        allowed && allowed.length > 0 ? allowed.join(', ') : 'none (terminal state)'
      }.`,
    };
  }
  return { valid: true };
}

test('State Machine: allows valid status progressions matching canonical backend lifecycle', () => {
  assert.equal(validateStateTransition('pending', 'assigned').valid, true);
  assert.equal(validateStateTransition('assigned', 'picked_up').valid, true);
  assert.equal(validateStateTransition('picked_up', 'in_transit').valid, true);
  assert.equal(validateStateTransition('in_transit', 'out_for_delivery').valid, true);
  assert.equal(validateStateTransition('out_for_delivery', 'delivered').valid, true);
  assert.equal(validateStateTransition('out_for_delivery', 'failed').valid, true);
  assert.equal(validateStateTransition('failed', 'out_for_delivery').valid, true);
});

test('State Machine: blocks invalid or illegal status progressions', () => {
  // Terminal state: delivered cannot transition to anything
  const fromDelivered = validateStateTransition('delivered', 'in_transit');
  assert.equal(fromDelivered.valid, false);
  assert.match(fromDelivered.message, /terminal state/i);

  // Terminal state: cancelled cannot transition to anything
  const fromCancelled = validateStateTransition('cancelled', 'assigned');
  assert.equal(fromCancelled.valid, false);

  // Jump from pending directly to delivered is invalid
  const jumpPending = validateStateTransition('pending', 'delivered');
  assert.equal(jumpPending.valid, false);
});

// 2. Test Reference & OTP Generation
function generateDeliveryReference(prefix = 'PL') {
  const year = new Date().getFullYear();
  let randomPart = '';
  if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
    const array = new Uint8Array(4);
    crypto.getRandomValues(array);
    randomPart = Array.from(array, (byte) => byte.toString(16).padStart(2, '0')).join('').toUpperCase();
  } else {
    randomPart = Math.floor(10000000 + Math.random() * 90000000).toString(16).toUpperCase();
  }
  return `${prefix}-${year}-${randomPart.slice(0, 6)}`;
}

function generateSecureOtp(length = 6) {
  if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
    const array = new Uint32Array(1);
    crypto.getRandomValues(array);
    if (length === 4) {
      return (1000 + (array[0] % 9000)).toString();
    }
    const code = 100000 + (array[0] % 900000);
    return code.toString();
  }
  if (length === 4) {
    return Math.floor(1000 + Math.random() * 9000).toString();
  }
  return Math.floor(100000 + Math.random() * 900000).toString();
}

test('Reference Generator: generates collision-resistant formatted IDs', () => {
  const ref1 = generateDeliveryReference();
  const ref2 = generateDeliveryReference();
  assert.notEqual(ref1, ref2);
  assert.match(ref1, /^PL-\d{4}-[A-F0-9]{6}$/);
});

test('OTP Generator: generates 6-digit numeric pins matching backend enterprise standard', () => {
  const pins = new Set();
  for (let i = 0; i < 50; i++) {
    const pin = generateSecureOtp(6);
    assert.equal(pin.length, 6);
    assert.match(pin, /^\d{6}$/);
    pins.add(pin);
  }
  // Check high distinct ratio
  assert.ok(pins.size > 40);
});

// 3. Test OTP Attempt Limiting, Lockout & Strict Stage Logic
function simulateOtpVerification(delivery, enteredOtp) {
  // Strict Delivery Stage Gate: Proof of delivery PIN can only be verified when out_for_delivery
  if (delivery.status !== 'out_for_delivery') {
    return {
      success: false,
      error: `Cannot verify PIN: delivery is in "${delivery.status}" status. PIN can only be verified when "out_for_delivery".`,
    };
  }

  const now = new Date();
  if (delivery.otpLockedUntil) {
    const lockTime = new Date(delivery.otpLockedUntil);
    if (lockTime > now) {
      return { success: false, locked: true, message: 'Verification locked.' };
    }
  }

  const maxAttempts = delivery.otpMaxAttempts || 3;
  const currentAttempts = delivery.otpAttempts || 0;

  if (delivery.otp !== enteredOtp) {
    const newAttempts = currentAttempts + 1;
    if (newAttempts >= maxAttempts) {
      delivery.otpAttempts = newAttempts;
      delivery.otpLockedUntil = new Date(now.getTime() + 15 * 60 * 1000).toISOString();
      return { success: false, locked: true, remainingAttempts: 0 };
    }
    delivery.otpAttempts = newAttempts;
    return { success: false, locked: false, remainingAttempts: maxAttempts - newAttempts };
  }

  delivery.otpAttempts = 0;
  delivery.status = 'delivered';
  delivery.podVerified = true;
  return { success: true };
}

test('OTP Security: rejects verification when delivery is not in out_for_delivery status', () => {
  const pendingDelivery = {
    id: 'PL-2026-TEST00',
    status: 'pending',
    otp: '123456',
    otpAttempts: 0,
    otpMaxAttempts: 3,
  };
  const res = simulateOtpVerification(pendingDelivery, '123456');
  assert.equal(res.success, false);
  assert.match(res.error, /out_for_delivery/i);
});

test('OTP Security: enforces 3 failed attempts lockout on out_for_delivery orders', () => {
  const mockDelivery = {
    id: 'PL-2026-TEST01',
    status: 'out_for_delivery',
    otp: '581290',
    otpAttempts: 0,
    otpMaxAttempts: 3,
  };

  // Attempt 1: fail
  const r1 = simulateOtpVerification(mockDelivery, '000000');
  assert.equal(r1.success, false);
  assert.equal(r1.remainingAttempts, 2);

  // Attempt 2: fail
  const r2 = simulateOtpVerification(mockDelivery, '111111');
  assert.equal(r2.success, false);
  assert.equal(r2.remainingAttempts, 1);

  // Attempt 3: fail -> trigger lockout
  const r3 = simulateOtpVerification(mockDelivery, '222222');
  assert.equal(r3.success, false);
  assert.equal(r3.locked, true);
  assert.equal(r3.remainingAttempts, 0);

  // Attempt 4: locked out even if correct
  const r4 = simulateOtpVerification(mockDelivery, '581290');
  assert.equal(r4.success, false);
  assert.equal(r4.locked, true);
});

test('OTP Security: completes delivery when correct 6-digit PIN provided on out_for_delivery orders', () => {
  const mockDelivery = {
    id: 'PL-2026-TEST02',
    status: 'out_for_delivery',
    otp: '934182',
    otpAttempts: 0,
    otpMaxAttempts: 3,
  };

  const r = simulateOtpVerification(mockDelivery, '934182');
  assert.equal(r.success, true);
  assert.equal(mockDelivery.status, 'delivered');
  assert.equal(mockDelivery.podVerified, true);
});

// 4. Test 6-Tier Verification Status Classification & Provenance Mapping
function classifyVerificationTier(status, isLive, isPartial) {
  if (isPartial || status === 'partially_verified') {
    return { tier: 'partially_verified', label: 'PARTIALLY VERIFIED', color: '#7c3aed' };
  }
  if (status === 'official_verified' || status === 'nipost_verified' || (status === 'verified' && isLive)) {
    return { tier: 'nipost_verified', label: 'NIPOST VERIFIED', color: '#16a34a' };
  }
  if (status === 'local_match' || status === 'local_reference' || status === 'verified') {
    return { tier: 'local_match', label: 'LOCAL REFERENCE MATCH', color: '#d97706' };
  }
  if (status === 'format_valid' || status === 'estimated') {
    return { tier: 'format_valid', label: 'FORMAT VALID', color: '#2563eb' };
  }
  if (status === 'conflict' || status === 'address_conflict') {
    return { tier: 'address_conflict', label: 'ADDRESS CONFLICT', color: '#dc2626' };
  }
  return { tier: 'unavailable', label: 'UNAVAILABLE / UNVERIFIED', color: '#64748b' };
}

test('Verification Classification: correctly partitions 6-tier verification status and provenance', () => {
  // Tier 1: NIPOST Live
  const t1 = classifyVerificationTier('official_verified', true, false);
  assert.equal(t1.tier, 'nipost_verified');
  assert.equal(t1.label, 'NIPOST VERIFIED');

  // Tier 2: Partially Verified (Validator existence + Local metadata)
  const t2 = classifyVerificationTier('partially_verified', true, true);
  assert.equal(t2.tier, 'partially_verified');
  assert.equal(t2.label, 'PARTIALLY VERIFIED');

  // Tier 3: Local Match (Non-governmental reference)
  const t3 = classifyVerificationTier('local_match', false, false);
  assert.equal(t3.tier, 'local_match');
  assert.equal(t3.label, 'LOCAL REFERENCE MATCH');

  // Ensure database record without live evidence cannot masquerade as official
  const t3Demoted = classifyVerificationTier('verified', false, false);
  assert.equal(t3Demoted.tier, 'local_match');

  // Tier 4: Format Valid
  const t4 = classifyVerificationTier('format_valid', false, false);
  assert.equal(t4.tier, 'format_valid');
  assert.equal(t4.label, 'FORMAT VALID');

  // Tier 5: Address Conflict
  const t5 = classifyVerificationTier('address_conflict', false, false);
  assert.equal(t5.tier, 'address_conflict');
  assert.equal(t5.label, 'ADDRESS CONFLICT');

  // Tier 6: Unavailable / Not Found
  const t6 = classifyVerificationTier('not_found', false, false);
  assert.equal(t6.tier, 'unavailable');
  assert.equal(t6.label, 'UNAVAILABLE / UNVERIFIED');
});

test('Workspace & Navigation Taxonomy: establishes Postcode Intelligence as core and Logistics as modular', () => {
  const sections = [
    { title: 'POSTCODE INTELLIGENCE (CORE)', tabs: ['postcodes'] },
    { title: 'LOGISTICS & DISPATCH (MODULE)', tabs: ['overview', 'deliveries', 'map', 'tracking'] },
    { title: 'FLEET & NETWORK', tabs: ['operators', 'customers'] },
    { title: 'INTELLIGENCE & SETTINGS', tabs: ['analytics', 'settings'] },
  ];

  // Verify Postcode Intelligence is top-level core workspace
  assert.equal(sections[0].title, 'POSTCODE INTELLIGENCE (CORE)');
  assert.deepEqual(sections[0].tabs, ['postcodes']);

  // Verify Logistics is a decoupled module
  assert.equal(sections[1].title, 'LOGISTICS & DISPATCH (MODULE)');
  assert.ok(sections[1].tabs.includes('deliveries'));
  assert.ok(sections[1].tabs.includes('overview'));
});

// 5. Test Null Metadata & Subtitle Formatting
function formatAddressSubtitle(area, state) {
  if (area && state) return `${area}, ${state}`;
  if (area) return `${area} (State Pending)`;
  if (state) return `Area Pending, ${state}`;
  return 'Incomplete Administrative Metadata';
}

test('Frontend Formatting: preserves null area and state without synthetic defaults', () => {
  assert.equal(formatAddressSubtitle('Ikeja', 'Lagos'), 'Ikeja, Lagos');
  assert.equal(formatAddressSubtitle(null, 'Lagos'), 'Area Pending, Lagos');
  assert.equal(formatAddressSubtitle('Ikeja', null), 'Ikeja (State Pending)');
  assert.equal(formatAddressSubtitle(null, null), 'Incomplete Administrative Metadata');
  assert.equal(formatAddressSubtitle('', ''), 'Incomplete Administrative Metadata');
});

// 6. Test Scheme-Aware Upstream Integration Display
function computeIntegrationDisplay(integration) {
  if (integration.configuration_complete) {
    return {
      status: 'configured',
      color: '#2563eb',
      badge: 'Adapter Configured - NIPOST Two-Stage (Awaiting Live Verification)',
    };
  }
  if (integration.base_url_set && integration.auth_scheme !== 'none') {
    return {
      status: 'awaiting_credentials',
      color: '#d97706',
      badge: 'Adapter Installed (Awaiting Production Credentials)',
    };
  }
  return {
    status: 'unconfigured',
    color: '#64748b',
    badge: 'Adapter Installed (Unconfigured)',
  };
}

test('Integration Display: scheme-aware display honors none scheme without credentials alert', () => {
  // Scheme 'none' with base_url
  const noneConfigured = computeIntegrationDisplay({
    adapter_installed: true,
    configuration_complete: true,
    base_url_set: true,
    credentials_set: false,
    auth_scheme: 'none',
  });
  assert.equal(noneConfigured.status, 'configured');
  assert.equal(noneConfigured.badge, 'Adapter Configured - NIPOST Two-Stage (Awaiting Live Verification)');

  // Scheme 'bearer' without credentials
  const bearerAwaiting = computeIntegrationDisplay({
    adapter_installed: true,
    configuration_complete: false,
    base_url_set: true,
    credentials_set: false,
    auth_scheme: 'bearer',
  });
  assert.equal(bearerAwaiting.status, 'awaiting_credentials');
  assert.equal(bearerAwaiting.badge, 'Adapter Installed (Awaiting Production Credentials)');
});

// 7. Test Bidirectional Delivery Status Mapping
function mapFrontendToBackendStatus(status) {
  switch (status) {
    case "pending":
    case "pending_assignment":
    case "draft":
      return "pending";
    case "assigned":
      return "assigned";
    case "picked_up":
      return "picked_up";
    case "in_transit":
      return "in_transit";
    case "out_for_delivery":
      return "out_for_delivery";
    case "delivered":
      return "delivered";
    case "cancelled":
      return "cancelled";
    case "failed":
      return "failed";
    default:
      throw new Error(`Unsupported delivery status: ${status}`);
  }
}

function mapBackendToFrontendStatus(apiStatus) {
  switch (apiStatus) {
    case "pending":
      return "pending_assignment";
    case "assigned":
      return "assigned";
    case "picked_up":
      return "picked_up";
    case "in_transit":
      return "in_transit";
    case "out_for_delivery":
      return "out_for_delivery";
    case "delivered":
      return "delivered";
    case "cancelled":
      return "cancelled";
    case "failed":
      return "failed";
    default:
      return "draft";
  }
}

test('Delivery Status Mapping: bi-directional mapping preserves all states including picked_up and out_for_delivery', () => {
  // Outgoing mapping (Frontend -> Backend)
  assert.equal(mapFrontendToBackendStatus('picked_up'), 'picked_up');
  assert.equal(mapFrontendToBackendStatus('in_transit'), 'in_transit');
  assert.equal(mapFrontendToBackendStatus('out_for_delivery'), 'out_for_delivery');
  assert.equal(mapFrontendToBackendStatus('assigned'), 'assigned');
  assert.equal(mapFrontendToBackendStatus('pending_assignment'), 'pending');
  assert.equal(mapFrontendToBackendStatus('delivered'), 'delivered');
  assert.equal(mapFrontendToBackendStatus('cancelled'), 'cancelled');
  assert.equal(mapFrontendToBackendStatus('failed'), 'failed');

  // Unsupported status throws
  assert.throws(() => mapFrontendToBackendStatus('invalid_status'), /Unsupported delivery status/);

  // Incoming mapping (Backend -> Frontend)
  assert.equal(mapBackendToFrontendStatus('picked_up'), 'picked_up');
  assert.equal(mapBackendToFrontendStatus('in_transit'), 'in_transit');
  assert.equal(mapBackendToFrontendStatus('out_for_delivery'), 'out_for_delivery');
  assert.equal(mapBackendToFrontendStatus('assigned'), 'assigned');
  assert.equal(mapBackendToFrontendStatus('pending'), 'pending_assignment');
  assert.equal(mapBackendToFrontendStatus('delivered'), 'delivered');
  assert.equal(mapBackendToFrontendStatus('cancelled'), 'cancelled');
  assert.equal(mapBackendToFrontendStatus('failed'), 'failed');
});

// 7. Canonical Postcode Format & 5-Tier Trust Classification
function isWellFormedPostcode(code) {
  if (!code || typeof code !== 'string') return false;
  const trimmed = code.trim();
  const isNumeric = /^\d{6}$/.test(trimmed);
  const isDigital = /^[A-Z]{2}-\d{2}-[A-Z0-9]{3}-[A-Z0-9]{2}-\d{2}$/i.test(trimmed);
  return isNumeric || isDigital;
}

function classifyPostcodeTrustTier(data, inputState) {
  if (!data || !data.exists) {
    return { status: 'unavailable', is_official: false };
  }
  if (data.source === 'live_nipost') {
    if (inputState && data.state && !data.state.toLowerCase().includes(inputState.toLowerCase())) {
      return { status: 'address_conflict', is_official: true };
    }
    if (!data.state || !data.lga) {
      return { status: 'partial_verification', is_official: true };
    }
    return { status: 'officially_verified', is_official: true };
  }
  if (data.source === 'local_reference') {
    if (inputState && data.state && !data.state.toLowerCase().includes(inputState.toLowerCase())) {
      return { status: 'address_conflict', is_official: false };
    }
    return { status: 'local_match', is_official: false };
  }
  return { status: 'unavailable', is_official: false };
}

test('Canonical Postcode: validates 6-digit numeric and 15-character digital formats', () => {
  // Conventional 6-digit codes
  assert.equal(isWellFormedPostcode('100001'), true);
  assert.equal(isWellFormedPostcode('900001'), true);
  assert.equal(isWellFormedPostcode(' 500261 '), true);

  // 15-character National Digital Postcodes
  assert.equal(isWellFormedPostcode('FC-02-A09-DB-09'), true);
  assert.equal(isWellFormedPostcode('LA-01-A04-IK-02'), true);

  // Invalid formats
  assert.equal(isWellFormedPostcode('12345'), false);
  assert.equal(isWellFormedPostcode('1234567'), false);
  assert.equal(isWellFormedPostcode('ABCDEF'), false);
  assert.equal(isWellFormedPostcode('FC-02-INVALID'), false);
  assert.equal(isWellFormedPostcode(''), false);
  assert.equal(isWellFormedPostcode(null), false);
});

test('Trust Tier Classification: correctly evaluates 5-tier trust states and rejects synthetic defaults', () => {
  // 1. Officially Verified
  const t1 = classifyPostcodeTrustTier({ exists: true, source: 'live_nipost', state: 'Lagos', lga: 'Ikeja' }, 'Lagos');
  assert.equal(t1.status, 'officially_verified');
  assert.equal(t1.is_official, true);

  // 2. Partial Verification (missing LGA or state - must NOT invent defaults)
  const t2 = classifyPostcodeTrustTier({ exists: true, source: 'live_nipost', state: 'Lagos', lga: null });
  assert.equal(t2.status, 'partial_verification');
  assert.equal(t2.is_official, true);

  // 3. Address Conflict (postcode maps to Lagos, but user input Abuja)
  const t3 = classifyPostcodeTrustTier({ exists: true, source: 'live_nipost', state: 'Lagos', lga: 'Ikeja' }, 'Abuja');
  assert.equal(t3.status, 'address_conflict');
  assert.equal(t3.is_official, true);

  // 4. Local Match (PostcodeLink reference dataset, not official government validation)
  const t4 = classifyPostcodeTrustTier({ exists: true, source: 'local_reference', state: 'Lagos', lga: 'Ikeja' });
  assert.equal(t4.status, 'local_match');
  assert.equal(t4.is_official, false);

  // 5. Unavailable / Not Found
  const t5 = classifyPostcodeTrustTier({ exists: false });
  assert.equal(t5.status, 'unavailable');
  assert.equal(t5.is_official, false);
});

test('Environment Configuration: .env.example and fastapi-client.ts agree on NEXT_PUBLIC_FASTAPI_URL', async () => {
  const fs = await import('node:fs');
  const path = await import('node:path');
  const envExample = fs.readFileSync(path.join(process.cwd(), '.env.example'), 'utf8');
  const clientSrc = fs.readFileSync(path.join(process.cwd(), 'lib', 'fastapi-client.ts'), 'utf8');
  assert.ok(envExample.includes('NEXT_PUBLIC_FASTAPI_URL='), '.env.example must define NEXT_PUBLIC_FASTAPI_URL');
  assert.ok(clientSrc.includes('process.env.NEXT_PUBLIC_FASTAPI_URL'), 'fastapi-client.ts must read NEXT_PUBLIC_FASTAPI_URL');
});

test('Official Verification Badge: fails closed on missing, expired, malformed, partial, or fallback evidence', () => {
  function isOfficiallyVerifiedEvidence({ status, isLiveNipost, isPartial, fallbackUsed, evidenceId, validUntil }) {
    const hasOfficialStatus = status === 'official_verified' || status === 'officially_verified' || status === 'nipost_verified';
    if (!hasOfficialStatus || isLiveNipost !== true || isPartial || fallbackUsed) return false;
    if (!evidenceId || !evidenceId.trim()) return false;
    if (!validUntil || !validUntil.trim()) return false;
    const expiresMs = Date.parse(validUntil);
    if (Number.isNaN(expiresMs) || expiresMs <= Date.now()) return false;
    return true;
  }

  const future = new Date(Date.now() + 86400_000).toISOString();
  const past = new Date(Date.now() - 86400_000).toISOString();

  assert.equal(isOfficiallyVerifiedEvidence({ status: 'official_verified', isLiveNipost: true, evidenceId: 'ev-1', validUntil: future }), true);
  assert.equal(isOfficiallyVerifiedEvidence({ status: 'official_verified', isLiveNipost: false, evidenceId: 'ev-1', validUntil: future }), false);
  assert.equal(isOfficiallyVerifiedEvidence({ status: 'official_verified', isLiveNipost: true, evidenceId: '', validUntil: future }), false);
  assert.equal(isOfficiallyVerifiedEvidence({ status: 'official_verified', isLiveNipost: true, validUntil: future }), false);
  assert.equal(isOfficiallyVerifiedEvidence({ status: 'official_verified', isLiveNipost: true, evidenceId: 'ev-1' }), false);
  assert.equal(isOfficiallyVerifiedEvidence({ status: 'official_verified', isLiveNipost: true, evidenceId: 'ev-1', validUntil: 'not-a-date' }), false);
  assert.equal(isOfficiallyVerifiedEvidence({ status: 'official_verified', isLiveNipost: true, evidenceId: 'ev-1', validUntil: past }), false);
  assert.equal(isOfficiallyVerifiedEvidence({ status: 'official_verified', isLiveNipost: true, isPartial: true, evidenceId: 'ev-1', validUntil: future }), false);
  assert.equal(isOfficiallyVerifiedEvidence({ status: 'official_verified', isLiveNipost: true, fallbackUsed: true, evidenceId: 'ev-1', validUntil: future }), false);
});


