/**
 * PostcodeLink Nigeria - FastAPI Client SDK
 * Direct, authenticated interface to the FastAPI backend running on localhost:8000 (or NEXT_PUBLIC_FASTAPI_URL).
 */

const FASTAPI_BASE_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || 'http://127.0.0.1:8000';
const API_V1 = `${FASTAPI_BASE_URL}/api/v1`;

let authToken: string | null = null;

if (typeof window !== 'undefined') {
  authToken = localStorage.getItem('postcodelink_auth_token');
}

export interface FastAPIProfile {
  id: string;
  full_name: string;
  email: string;
  role: 'merchant' | 'operator' | 'admin';
  phone?: string;
  business_name?: string;
  created_at: string;
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
  otp_attempts: number;
  otp_max_attempts: number;
  pod_verified: boolean;
  pod_note?: string;
  created_at: string;
  updated_at: string;
  assigned_operator?: FastAPIOperator;
  events: FastAPIDeliveryEvent[];
}

export interface NotificationDispatchPayload {
  recipient_phone: string;
  delivery_pin: string;
  channel: string;
  message_preview: string;
}

export interface FastAPIDeliveryCreateResult {
  delivery: FastAPIDelivery;
  notification_dispatch: NotificationDispatchPayload;
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
  requires_pin_confirmation: boolean;
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
  profile_id?: string;
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
  tenant_id: string;
  tenant_role: string;
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

function getHeaders(extraHeaders: Record<string, string> = {}): Record<string, string> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...extraHeaders,
  };
  const token = fastApiClient.getToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

export const fastApiClient = {
  setToken(token: string | null) {
    authToken = token;
    if (typeof window !== 'undefined') {
      if (token) {
        localStorage.setItem('postcodelink_auth_token', token);
      } else {
        localStorage.removeItem('postcodelink_auth_token');
      }
    }
  },

  getToken(): string | null {
    if (!authToken && typeof window !== 'undefined') {
      authToken = localStorage.getItem('postcodelink_auth_token');
    }
    return authToken;
  },

  async login(email: string, password: string): Promise<{ access_token: string; profile: FastAPIProfile }> {
    const res = await fetch(`${API_V1}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Login failed');
    }
    const data = await res.json();
    this.setToken(data.access_token);
    return data;
  },

  async ensureAuthenticated(): Promise<string> {
    const existing = this.getToken();
    if (existing) return existing;
    // Auto-authenticate default merchant session for seamless local experience
    try {
      const data = await this.login('dispatch@postcodelink.ng', 'MerchantPass123!');
      return data.access_token;
    } catch {
      return '';
    }
  },

  async getHealth() {
    try {
      const res = await fetch(`${FASTAPI_BASE_URL}/health`, { cache: 'no-store' });
      if (!res.ok) return null;
      return await res.json();
    } catch {
      return null;
    }
  },

  async listDeliveries(status?: string, search?: string): Promise<FastAPIDelivery[]> {
    await this.ensureAuthenticated();
    const params = new URLSearchParams();
    if (status) params.append('status', status);
    if (search) params.append('search', search);

    const res = await fetch(`${API_V1}/deliveries/?${params.toString()}`, {
      headers: getHeaders(),
      cache: 'no-store',
    });
    if (!res.ok) throw new Error(`FastAPI listDeliveries error: ${res.statusText}`);
    return await res.json();
  },

  async getDelivery(id: string): Promise<FastAPIDelivery> {
    await this.ensureAuthenticated();
    const res = await fetch(`${API_V1}/deliveries/${encodeURIComponent(id)}`, {
      headers: getHeaders(),
      cache: 'no-store',
    });
    if (!res.ok) throw new Error(`Delivery not found: ${res.statusText}`);
    return await res.json();
  },

  async getPublicTracking(id: string): Promise<FastAPIPublicTracking> {
    const res = await fetch(`${API_V1}/deliveries/${encodeURIComponent(id)}/tracking`, {
      cache: 'no-store',
    });
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
  }): Promise<FastAPIDeliveryCreateResult> {
    await this.ensureAuthenticated();
    const res = await fetch(`${API_V1}/deliveries/`, {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to create delivery');
    }
    return await res.json();
  },

  async assignOperator(deliveryId: string, operatorId: string): Promise<FastAPIDelivery> {
    await this.ensureAuthenticated();
    const res = await fetch(`${API_V1}/deliveries/${encodeURIComponent(deliveryId)}/assign`, {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify({ operator_id: operatorId }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to assign operator');
    }
    return await res.json();
  },

  async updateStatus(deliveryId: string, newStatus: string, note?: string): Promise<FastAPIDelivery> {
    await this.ensureAuthenticated();
    const res = await fetch(`${API_V1}/deliveries/${encodeURIComponent(deliveryId)}/status`, {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify({ new_status: newStatus, note }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to update delivery status');
    }
    return await res.json();
  },

  async verifyOTP(deliveryId: string, otp: string, note?: string): Promise<FastAPIDelivery> {
    await this.ensureAuthenticated();
    const res = await fetch(`${API_V1}/deliveries/${encodeURIComponent(deliveryId)}/verify-otp`, {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify({ otp, note }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to verify PIN');
    }
    return await res.json();
  },

  async listOperators(): Promise<FastAPIOperator[]> {
    await this.ensureAuthenticated();
    const res = await fetch(`${API_V1}/operators/`, {
      headers: getHeaders(),
      cache: 'no-store',
    });
    if (!res.ok) throw new Error('Failed to fetch operators');
    return await res.json();
  },

  async listCustomers(search?: string): Promise<FastAPICustomer[]> {
    await this.ensureAuthenticated();
    const url = search ? `${API_V1}/customers/?search=${encodeURIComponent(search)}` : `${API_V1}/customers/`;
    const res = await fetch(url, {
      headers: getHeaders(),
      cache: 'no-store',
    });
    if (!res.ok) throw new Error('Failed to fetch customers');
    return await res.json();
  },

  async getAnalytics(): Promise<FastAPIAnalytics> {
    await this.ensureAuthenticated();
    const res = await fetch(`${API_V1}/analytics/overview`, {
      headers: getHeaders(),
      cache: 'no-store',
    });
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
