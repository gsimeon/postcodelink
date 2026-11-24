/**
 * PostcodeLink Nigeria - FastAPI Client SDK
 * Direct, authenticated interface to the FastAPI backend running on localhost:8000 (or NEXT_PUBLIC_FASTAPI_URL).
 * Strict security: NO hardcoded credentials. Explicit user authentication only.
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
  tracking_token: string;
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
  status: string;
  channel: string;
  message_preview: string;
}

export interface FastAPIDeliveryCreateResult {
  delivery: FastAPIDelivery;
  notification_dispatch: NotificationDispatchPayload;
}

export interface PublicTrackingEvent {
  status: string;
  occurred_at: string;
}

export interface FastAPIPublicTracking {
  tracking_token: string;
  recipient_name_masked: string;
  recipient_phone_masked: string;
  destination_general_location: string;
  postcode_status: 'verified' | 'unverified' | 'estimated' | 'invalid';
  verified_postcode?: string;
  status: string;
  requires_pin_confirmation: boolean;
  is_locked: boolean;
  lockout_remaining_minutes?: number;
  pod_verified: boolean;
  created_at: string;
  updated_at: string;
  assigned_operator_name?: string;
  timeline: PublicTrackingEvent[];
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
  merchant_id: string;
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

export type PostcodeRecord = PostcodeDirectoryEntry;

export interface PostcodeDirectoryEntry {
  code: string;
  area: string | null;
  state: string | null;
  lga?: string;
  lat?: number;
  lng?: number;
  postcode_type: string;
  postcode_category?: string;
  building_reference?: string;
  verification_status?: string;
  provenance?: string;
  dataset_version?: string;
  verified_at?: string;
  valid_until?: string;
  evidence_id?: string;
  verification_method?: string;
  address_metadata_source?: string;
  source_owner?: string;
  source_type?: string;
  national_components?: Record<string, string>;
}

export interface PostcodeLookupResult {
  source: string;
  count: number;
  matches: PostcodeDirectoryEntry[];
  is_live_nipost: boolean;
  upstream_contacted?: boolean;
  postcode_exists?: boolean | null;
  is_partial_verification?: boolean;
  service_type?: string;
  dataset_version?: string;
  api_integration_version: string;
  provenance: string;
  lookup_status: string;
  verification_source: string;
  verification_status: string;
  fallback_used: boolean;
  fallback_reason?: string;
  upstream_status?: string;
  upstream_error?: string;
  evidence_id?: string;
  verification_method?: string;
  address_metadata_source?: string;
  valid_until?: string;
}

export type VerificationMode = "local_standardization" | "nipost_validate" | "nipost_strict";

export interface CleanseResult {
  original_address: string;
  formatted_address: string;
  area: string | null;
  state: string | null;
  lga?: string;
  postcode: string;
  postcode_type: string;
  postcode_category?: string;
  resolution_level: string;
  postcode_status: string;
  verification_status?: string;
  verification_mode?: string;
  confidence: number;
  match_quality_score?: number;
  postcode_exists?: boolean | null;
  upstream_contacted?: boolean;
  postcode_valid: boolean;
  address_consistent: boolean;
  dispatch_confidence: number;
  source: string;
  matched_record?: PostcodeDirectoryEntry;
  changes_made: string[];
  provenance?: string;
  source_owner?: string;
  source_type?: string;
  national_components?: Record<string, string>;
  checked_against_nipost: boolean;
  is_live_nipost: boolean;
  verification_source: string;
  fallback_used: boolean;
  upstream_status?: string;
  upstream_error?: string;
  is_partial_verification?: boolean;
  evidence_id?: string;
  verification_method?: string;
  address_metadata_source?: string;
  dataset_version?: string;
  api_integration_version?: string;
  valid_until?: string;
}

export interface CoverageReport {
  edition: string;
  version: string;
  scope_states_count: number;
  states_covered: string[];
  states_in_dataset_metadata?: string[];
  states_with_active_records?: string[];
  states_with_verified_records?: string[];
  states_with_only_demo_records?: string[];
  total_reference_records: number;
  records_per_state: Record<string, number>;
  records_with_coordinates: number;
  records_with_verified_provenance: number;
  records_with_valid_evidence?: number;
  records_with_expired_evidence?: number;
  records_with_rejected_evidence?: number;
  records_with_incomplete_evidence?: number;
  records_with_invalid_evidence?: number;
  records_with_complete_metadata?: number;
  legacy_six_digit_records?: number;
  national_digital_postcode_records?: number;
  format_valid_digital_references?: number;
  nipost_confirmed_postcodes?: number;
  nipost_confirmed_address_metadata?: number;
  local_demonstration_fixtures?: number;
  digital_building_level_records: number;
  dataset_source?: string;
  source?: string;
  upstream_integration: {
    adapter_installed: boolean;
    configuration_complete: boolean;
    base_url_set: boolean;
    credentials_set: boolean;
    auth_scheme: string;
    connectivity_healthy?: boolean;
    authentication_verified?: boolean;
    contract_verified?: boolean;
    production_authorized?: boolean;
    last_checked_at?: string | null;
    status: string;
    display_status: string;
  };
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

  logout() {
    this.setToken(null);
  },

  isAuthenticated(): boolean {
    return !!this.getToken();
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

  async register(payload: {
    full_name: string;
    email: string;
    password: string;
    phone?: string;
    business_name?: string;
  }): Promise<{ access_token: string; profile: FastAPIProfile }> {
    const res = await fetch(`${API_V1}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Registration failed');
    }
    const data = await res.json();
    this.setToken(data.access_token);
    return data;
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
    const res = await fetch(`${API_V1}/deliveries/${encodeURIComponent(id)}`, {
      headers: getHeaders(),
      cache: 'no-store',
    });
    if (!res.ok) throw new Error(`Delivery not found: ${res.statusText}`);
    return await res.json();
  },

  async getPublicTracking(identifier: string): Promise<FastAPIPublicTracking> {
    const res = await fetch(`${API_V1}/deliveries/${encodeURIComponent(identifier)}/tracking`, {
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

  async bulkCreateDeliveries(items: Array<{
    recipient_name: string;
    recipient_phone: string;
    destination_address: string;
    destination_landmark?: string;
    destination_area: string;
    destination_state: string;
    postcode_input: string;
    package_description: string;
    fee?: number;
  }>): Promise<FastAPIDelivery[]> {
    const res = await fetch(`${API_V1}/deliveries/bulk`, {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify(items),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Bulk import failed');
    }
    return await res.json();
  },

  async deleteDelivery(deliveryId: string): Promise<void> {
    const res = await fetch(`${API_V1}/deliveries/${encodeURIComponent(deliveryId)}`, {
      method: 'DELETE',
      headers: getHeaders(),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to delete delivery');
    }
  },

  async assignOperator(deliveryId: string, operatorId: string): Promise<FastAPIDelivery> {
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
    const res = await fetch(`${API_V1}/operators/`, {
      headers: getHeaders(),
      cache: 'no-store',
    });
    if (!res.ok) throw new Error('Failed to fetch operators');
    return await res.json();
  },

  async listCustomers(search?: string): Promise<FastAPICustomer[]> {
    const url = search ? `${API_V1}/customers/?search=${encodeURIComponent(search)}` : `${API_V1}/customers/`;
    const res = await fetch(url, {
      headers: getHeaders(),
      cache: 'no-store',
    });
    if (!res.ok) throw new Error('Failed to fetch customers');
    return await res.json();
  },

  async createCustomer(payload: {
    full_name: string;
    phone: string;
    email?: string;
    default_address: string;
    area: string;
    state: string;
    postcode?: string;
  }): Promise<FastAPICustomer> {
    const res = await fetch(`${API_V1}/customers/`, {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to create customer');
    }
    return await res.json();
  },

  async getAnalytics(): Promise<FastAPIAnalytics> {
    const res = await fetch(`${API_V1}/analytics/overview`, {
      headers: getHeaders(),
      cache: 'no-store',
    });
    if (!res.ok) throw new Error('Failed to fetch analytics');
    return await res.json();
  },

  async getProfile(): Promise<FastAPIProfile> {
    const res = await fetch(`${API_V1}/auth/me`, {
      headers: getHeaders(),
      cache: 'no-store',
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to fetch current profile');
    }
    return await res.json();
  },

  async lookupPostcodes(params: {
    code?: string;
    state?: string;
    area?: string;
    strict?: boolean;
  } = {}): Promise<PostcodeLookupResult> {
    const q = new URLSearchParams();
    if (params.code && params.code.trim()) q.append('code', params.code.trim());
    if (params.state && params.state !== 'All') q.append('state', params.state);
    if (params.area && params.area.trim()) q.append('area', params.area.trim());
    if (params.strict) q.append('strict', 'true');

    const res = await fetch(`${API_V1}/postcodes/lookup?${q.toString()}`, {
      headers: getHeaders(),
      cache: 'no-store',
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to lookup postcodes');
    }
    return await res.json();
  },

  async cleanseAddress(
    addressOrPayload:
      | string
      | {
          address: string;
          state?: string;
          area?: string;
          postcode?: string;
          strict?: boolean;
          live_verify?: boolean;
          verification_mode?: "local_standardization" | "nipost_validate" | "nipost_strict";
        },
    state?: string,
    area?: string,
    postcode?: string,
    strict?: boolean,
    live_verify?: boolean,
    verification_mode?: "local_standardization" | "nipost_validate" | "nipost_strict"
  ): Promise<CleanseResult> {
    const payload =
      typeof addressOrPayload === 'string'
        ? {
            address: addressOrPayload,
            state: state || undefined,
            area: area || undefined,
            postcode: postcode || undefined,
            strict: !!strict,
            live_verify: !!live_verify,
            verification_mode: verification_mode || undefined,
          }
        : addressOrPayload;

    const res = await fetch(`${API_V1}/postcodes/cleanse`, {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to cleanse address');
    }
    return await res.json();
  },

  async getCoverageReport(): Promise<CoverageReport> {
    const res = await fetch(`${API_V1}/postcodes/coverage`, {
      headers: getHeaders(),
      cache: 'no-store',
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to fetch coverage report');
    }
    return await res.json();
  },

  async getTracking(trackingToken: string): Promise<FastAPIPublicTracking> {
    const res = await fetch(`${API_V1}/deliveries/track/${encodeURIComponent(trackingToken)}`, {
      cache: 'no-store',
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Tracking record not found');
    }
    return await res.json();
  },

  async verifyRecipientChallenge(trackingToken: string, phoneLast4: string): Promise<{ success: boolean; verified: boolean; message: string; tracking_token: string; challenge_token: string; expires_in_seconds: number; status: string }> {
    const res = await fetch(`${API_V1}/deliveries/track/${encodeURIComponent(trackingToken)}/verify-recipient`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phone_last_4: phoneLast4 }),
      cache: 'no-store',
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Identity challenge failed');
    }
    return await res.json();
  },

  async publicConfirmDelivery(
    trackingToken: string,
    otp: string,
    challengeToken: string,
    phoneLast4?: string
  ): Promise<{ success: boolean; message: string; status: string; pod_verified: boolean }> {
    const res = await fetch(`${API_V1}/deliveries/track/${encodeURIComponent(trackingToken)}/confirm-delivery`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ otp, challenge_token: challengeToken, phone_last_4: phoneLast4 }),
      cache: 'no-store',
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'PIN verification failed');
    }
    return await res.json();
  },

  async regenerateTrackingToken(deliveryId: string): Promise<FastAPIDelivery> {
    const res = await fetch(`${API_V1}/deliveries/${encodeURIComponent(deliveryId)}/regenerate-token`, {
      method: 'POST',
      headers: getHeaders(),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to regenerate tracking token');
    }
    return await res.json();
  },
};
