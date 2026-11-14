/**
 * PostcodeLink Nigeria - FastAPI Client SDK
 * Direct interface to the FastAPI backend running on localhost:8000 (or NEXT_PUBLIC_FASTAPI_URL).
 */

const FASTAPI_BASE_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || 'http://127.0.0.1:8000';
const API_V1 = `${FASTAPI_BASE_URL}/api/v1`;

export interface FastAPIHealth {
  status: string;
  database: string;
  engine: string;
}

export interface FastAPIDelivery {
  id: string;
  merchant_id?: string;
  operator_id?: string;
  recipient_name: string;
  recipient_phone: string;
  destination_address: string;
  destination_landmark?: string;
  destination_area: string;
  destination_state: string;
  postcode_input: string;
  postcode_status: 'verified' | 'unverified' | 'estimated' | 'invalid';
  verified_postcode?: string;
  package_description: string;
  fee: number;
  pickup_address?: string;
  status: 'pending' | 'assigned' | 'picked_up' | 'in_transit' | 'out_for_delivery' | 'delivered' | 'cancelled' | 'failed';
  lat?: number;
  lng?: number;
  otp: string;
  otp_attempts: number;
  otp_max_attempts: number;
  pod_verified: boolean;
  pod_note?: string;
  created_at: string;
  updated_at: string;
  assigned_operator?: FastAPIOperator;
  events: FastAPIDeliveryEvent[];
}

export interface FastAPIPublicTracking {
  id: string;
  recipient_name: string;
  recipient_phone_masked: string;
  destination_address: string;
  destination_landmark?: string;
  destination_area: string;
  destination_state: string;
  postcode_status: 'verified' | 'unverified' | 'estimated' | 'invalid';
  verified_postcode?: string;
  package_description: string;
  fee: number;
  status: string;
  lat?: number;
  lng?: number;
  otp_masked: string;
  otp_attempts: number;
  otp_max_attempts: number;
  is_locked: boolean;
  lockout_remaining_minutes?: number;
  pod_verified: boolean;
  created_at: string;
  updated_at: string;
  assigned_operator_name?: string;
  events: FastAPIDeliveryEvent[];
}

export interface FastAPIDeliveryEvent {
  id: string;
  delivery_id: string;
  status: string;
  actor_name: string;
  actor_role: string;
  note?: string;
  occurred_at: string;
}

export interface FastAPIOperator {
  id: string;
  business_name: string;
  phone: string;
  vehicle_type: 'motorcycle' | 'van' | 'truck' | 'bicycle';
  service_areas: string[];
  is_available: boolean;
  rating: number;
  completed_deliveries: number;
  active_deliveries_count: number;
}

export interface FastAPICustomer {
  id: string;
  full_name: string;
  phone: string;
  email?: string;
  default_address: string;
  area: string;
  state: string;
  postcode?: string;
  total_orders: number;
}

export interface FastAPIAnalytics {
  total_deliveries: number;
  delivered: number;
  in_transit: number;
  pending: number;
  cancelled: number;
  verified_postcodes_count: number;
  verification_rate_percent: number;
  total_revenue_ngn: number;
  active_operators: number;
  total_customers: number;
}

export const fastApiClient = {
  async getHealth(): Promise<FastAPIHealth | null> {
    try {
      const res = await fetch(`${FASTAPI_BASE_URL}/health`, { cache: 'no-store' });
      if (!res.ok) return null;
      return await res.json();
    } catch {
      return null;
    }
  },

  async listDeliveries(status?: string, search?: string): Promise<FastAPIDelivery[]> {
    const params = new URLSearchParams();
    if (status) params.append('status', status);
    if (search) params.append('search', search);

    const res = await fetch(`${API_V1}/deliveries/?${params.toString()}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`FastAPI Error: ${res.statusText}`);
    return await res.json();
  },

  async getDelivery(id: string): Promise<FastAPIDelivery> {
    const res = await fetch(`${API_V1}/deliveries/${encodeURIComponent(id)}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`Delivery not found: ${res.statusText}`);
    return await res.json();
  },

  async getPublicTracking(id: string): Promise<FastAPIPublicTracking> {
    const res = await fetch(`${API_V1}/deliveries/${encodeURIComponent(id)}/tracking`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`Tracking record not found: ${res.statusText}`);
    return await res.json();
  },

  async createDelivery(payload: {
    recipient_name: string;
    recipient_phone: string;
    destination_address: string;
    destination_landmark?: string;
    destination_area: string;
    destination_state: string;
    postcode_input: string;
    package_description: string;
    fee?: number;
    pickup_address?: string;
  }): Promise<FastAPIDelivery> {
    const res = await fetch(`${API_V1}/deliveries/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to create delivery');
    }
    return await res.json();
  },

  async assignOperator(deliveryId: string, operatorId: string, actorName = 'Dispatcher'): Promise<FastAPIDelivery> {
    const res = await fetch(`${API_V1}/deliveries/${encodeURIComponent(deliveryId)}/assign`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ operator_id: operatorId, actor_name: actorName }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to assign operator');
    }
    return await res.json();
  },

  async updateStatus(deliveryId: string, newStatus: string, note?: string): Promise<FastAPIDelivery> {
    const res = await fetch(`${API_V1}/deliveries/${encodeURIComponent(deliveryId)}/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_status: newStatus, note }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to update delivery status');
    }
    return await res.json();
  },

  async verifyOTP(deliveryId: string, otp: string, recipientPhone?: string, note?: string): Promise<FastAPIDelivery> {
    const res = await fetch(`${API_V1}/deliveries/${encodeURIComponent(deliveryId)}/verify-otp`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ otp, recipient_phone: recipientPhone, note }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to verify PIN');
    }
    return await res.json();
  },

  async listOperators(): Promise<FastAPIOperator[]> {
    const res = await fetch(`${API_V1}/operators/`, { cache: 'no-store' });
    if (!res.ok) throw new Error('Failed to fetch operators');
    return await res.json();
  },

  async listCustomers(search?: string): Promise<FastAPICustomer[]> {
    const url = search ? `${API_V1}/customers/?search=${encodeURIComponent(search)}` : `${API_V1}/customers/`;
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) throw new Error('Failed to fetch customers');
    return await res.json();
  },

  async getAnalytics(): Promise<FastAPIAnalytics> {
    const res = await fetch(`${API_V1}/analytics/overview`, { cache: 'no-store' });
    if (!res.ok) throw new Error('Failed to fetch analytics');
    return await res.json();
  },

  async cleanseAddress(address: string, state?: string, postcode?: string) {
    const res = await fetch(`${API_V1}/postcodes/cleanse`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ address, state, postcode }),
    });
    if (!res.ok) throw new Error('Failed to cleanse address');
    return await res.json();
  },
};

