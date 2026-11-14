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
