import { DeliveryStatus } from './types';

/**
 * Valid state transitions for PostcodeLink delivery lifecycle:
 * 
 * draft -> pending_assignment, cancelled
 * pending_assignment -> assigned, cancelled
 * assigned -> in_transit, pending_assignment, cancelled
 * in_transit -> delivered, failed
 * failed -> pending_assignment, in_transit, cancelled
 * delivered -> (terminal state, immutable)
 * cancelled -> (terminal state, immutable)
 */
export const ALLOWED_TRANSITIONS: Record<DeliveryStatus, DeliveryStatus[]> = {
  draft: ['pending_assignment', 'cancelled'],
  pending_assignment: ['assigned', 'cancelled'],
  assigned: ['in_transit', 'pending_assignment', 'cancelled'],
  in_transit: ['delivered', 'failed'],
  failed: ['pending_assignment', 'in_transit', 'cancelled'],
  delivered: [],
  cancelled: [],
};

export interface StateTransitionResult {
  valid: boolean;
  message?: string;
}

export function validateStateTransition(
  currentStatus: DeliveryStatus,
  targetStatus: DeliveryStatus
): StateTransitionResult {
  if (currentStatus === targetStatus) {
    return { valid: true };
  }

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

