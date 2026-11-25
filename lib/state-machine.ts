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
  draft: ['pending', 'pending_assignment', 'cancelled'],
  pending_assignment: ['assigned', 'cancelled', 'pending'],
  pending: ['assigned', 'cancelled'],
  assigned: ['picked_up', 'in_transit', 'pending', 'pending_assignment', 'cancelled'],
  picked_up: ['in_transit', 'failed', 'cancelled'],
  in_transit: ['out_for_delivery', 'delivered', 'failed', 'cancelled'],
  out_for_delivery: ['delivered', 'failed'],
  failed: ['out_for_delivery', 'in_transit', 'pending', 'cancelled'],
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

export function mapFrontendToBackendStatus(status: DeliveryStatus): string {
  switch (status) {
    case 'pending':
    case 'pending_assignment':
    case 'draft':
      return 'pending';
    case 'assigned':
      return 'assigned';
    case 'picked_up':
      return 'picked_up';
    case 'in_transit':
      return 'in_transit';
    case 'out_for_delivery':
      return 'out_for_delivery';
    case 'delivered':
      return 'delivered';
    case 'cancelled':
      return 'cancelled';
    case 'failed':
      return 'failed';
    default:
      throw new Error(`Unsupported delivery status: ${status}`);
  }
}

export function mapBackendToFrontendStatus(apiStatus: string): DeliveryStatus {
  switch (apiStatus) {
    case 'pending':
      return 'pending_assignment';
    case 'assigned':
      return 'assigned';
    case 'picked_up':
      return 'picked_up';
    case 'in_transit':
      return 'in_transit';
    case 'out_for_delivery':
      return 'out_for_delivery';
    case 'delivered':
      return 'delivered';
    case 'cancelled':
      return 'cancelled';
    case 'failed':
      return 'failed';
    default:
      throw new Error(`Unsupported backend delivery status: ${apiStatus}`);
  }
}


