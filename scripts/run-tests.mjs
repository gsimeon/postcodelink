import test from 'node:test';
import assert from 'node:assert/strict';

// 1. Test State Machine
const ALLOWED_TRANSITIONS = {
  draft: ['pending_assignment', 'cancelled'],
  pending_assignment: ['assigned', 'cancelled'],
  assigned: ['in_transit', 'pending_assignment', 'cancelled'],
  in_transit: ['delivered', 'failed'],
  failed: ['pending_assignment', 'in_transit', 'cancelled'],
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

test('State Machine: allows valid status progressions', () => {
  assert.equal(validateStateTransition('draft', 'pending_assignment').valid, true);
  assert.equal(validateStateTransition('pending_assignment', 'assigned').valid, true);
  assert.equal(validateStateTransition('assigned', 'in_transit').valid, true);
  assert.equal(validateStateTransition('in_transit', 'delivered').valid, true);
  assert.equal(validateStateTransition('in_transit', 'failed').valid, true);
  assert.equal(validateStateTransition('failed', 'pending_assignment').valid, true);
});

test('State Machine: blocks invalid or illegal status progressions', () => {
  // Terminal state: delivered cannot transition to anything
  const fromDelivered = validateStateTransition('delivered', 'in_transit');
  assert.equal(fromDelivered.valid, false);
  assert.match(fromDelivered.message, /terminal state/i);

  // Terminal state: cancelled cannot transition to anything
  const fromCancelled = validateStateTransition('cancelled', 'assigned');
  assert.equal(fromCancelled.valid, false);

  // Jump from draft directly to delivered is invalid
  const jumpDraft = validateStateTransition('draft', 'delivered');
  assert.equal(jumpDraft.valid, false);
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

function generateSecureOtp() {
  if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
    const array = new Uint32Array(1);
    crypto.getRandomValues(array);
    const code = 1000 + (array[0] % 9000);
    return code.toString();
  }
  return Math.floor(1000 + Math.random() * 9000).toString();
}

test('Reference Generator: generates collision-resistant formatted IDs', () => {
  const ref1 = generateDeliveryReference();
  const ref2 = generateDeliveryReference();
  assert.notEqual(ref1, ref2);
  assert.match(ref1, /^PL-\d{4}-[A-F0-9]{6}$/);
});

test('OTP Generator: generates 4-digit numeric pins with sufficient entropy', () => {
  const pins = new Set();
  for (let i = 0; i < 50; i++) {
    const pin = generateSecureOtp();
    assert.equal(pin.length, 4);
    assert.match(pin, /^\d{4}$/);
    pins.add(pin);
  }
  // Check high distinct ratio
  assert.ok(pins.size > 40);
});

// 3. Test OTP Attempt Limiting & Lockout Logic
function simulateOtpVerification(delivery, enteredOtp) {
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

test('OTP Security: enforces 3 failed attempts lockout', () => {
  const mockDelivery = {
    id: 'PL-2026-TEST01',
    status: 'in_transit',
    otp: '5812',
    otpAttempts: 0,
    otpMaxAttempts: 3,
  };

  // Attempt 1: fail
  const r1 = simulateOtpVerification(mockDelivery, '0000');
  assert.equal(r1.success, false);
  assert.equal(r1.remainingAttempts, 2);

  // Attempt 2: fail
  const r2 = simulateOtpVerification(mockDelivery, '1111');
  assert.equal(r2.success, false);
  assert.equal(r2.remainingAttempts, 1);

  // Attempt 3: fail -> trigger lockout
  const r3 = simulateOtpVerification(mockDelivery, '2222');
  assert.equal(r3.success, false);
  assert.equal(r3.locked, true);
  assert.equal(r3.remainingAttempts, 0);

  // Attempt 4: locked out even if correct
  const r4 = simulateOtpVerification(mockDelivery, '5812');
  assert.equal(r4.success, false);
  assert.equal(r4.locked, true);
});

test('OTP Security: completes delivery when correct PIN provided', () => {
  const mockDelivery = {
    id: 'PL-2026-TEST02',
    status: 'in_transit',
    otp: '9341',
    otpAttempts: 0,
    otpMaxAttempts: 3,
  };

  const r = simulateOtpVerification(mockDelivery, '9341');
  assert.equal(r.success, true);
  assert.equal(mockDelivery.status, 'delivered');
  assert.equal(mockDelivery.podVerified, true);
});
