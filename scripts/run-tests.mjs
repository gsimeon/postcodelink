import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

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


test('POD API fails closed instead of attempting browser localStorage on the server', () => {
  const route = readFileSync(join(process.cwd(), 'app/api/deliveries/verify-otp/route.ts'), 'utf8');
  assert.match(route, /POD_VERIFICATION_NOT_CONFIGURED/);
  assert.match(route, /503/);
  assert.doesNotMatch(route, /verifyDeliveryOtp|localStorage/);
});

test('Public tracking view never reveals or validates a recipient OTP', () => {
  const tracking = readFileSync(join(process.cwd(), 'components/TrackingPortalTab.tsx'), 'utf8');
  assert.doesNotMatch(tracking, /delivery\.otp|recipientPhone\.replace|lastFour|handleRevealPin/);
  assert.match(tracking, /No PIN is displayed or verified/);
});
