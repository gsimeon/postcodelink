export type DeliveryStatus =
  | 'draft'
  | 'pending_assignment'
  | 'assigned'
  | 'in_transit'
  | 'delivered'
  | 'failed'
  | 'cancelled';

export type PostcodeStatus = 'verified' | 'unverified' | 'unavailable' | 'invalid';

export interface DeliveryEvent {
  id: string;
  deliveryId: string;
  status: DeliveryStatus;
  actor: string;
  actorRole: 'merchant' | 'operator' | 'system' | 'rider';
  note?: string;
  timestamp: string;
}

export interface Coordinates {
  lat: number;
  lng: number;
}

export interface Delivery {
  id: string; // e.g. PL-2048
  recipientName: string;
  recipientPhone: string;
  recipientEmail?: string;
  destinationAddress: string;
  landmark?: string;
  destinationArea: string;
  destinationCity: string;
  destinationState: string;
  postcodeInput: string;
  postcodeStatus: PostcodeStatus;
  verifiedPostcode?: string;
  packageDescription?: string;
  fee?: number; // In Naira (NGN)
  operatorId?: string;
  operatorName?: string;
  status: DeliveryStatus;
  createdAt: string;
  updatedAt: string;
  events: DeliveryEvent[];
  otp?: string; // 4-digit Proof of Delivery confirmation code
  otpAttempts?: number; // Failed verification attempt counter
  otpMaxAttempts?: number; // Default 3 attempts before lockout
  otpLockedUntil?: string; // ISO lockout timestamp
  otpExpiresAt?: string; // Expiration timestamp
  podVerified?: boolean;
  podNote?: string;
  coordinates?: Coordinates;
  estimatedDeliveryTime?: string;
}

export interface Operator {
  id: string;
  businessName: string;
  contactPerson: string;
  phone: string;
  vehicleType: 'Motorcycle' | 'Delivery Van' | 'Tricycle (Keke)' | 'Truck' | 'Bicycle';
  serviceAreas: string[];
  isAvailable: boolean;
  rating: number;
  completedDeliveries: number;
  activeDeliveriesCount: number;
  currentZone?: string;
  coordinates?: Coordinates;
}

export interface Customer {
  id: string;
  fullName: string;
  phone: string;
  email?: string;
  defaultAddress: string;
  area: string;
  state: string;
  postcode: string;
  totalOrders: number;
}

export interface PostcodeEntry {
  state: string;
  lga: string;
  districtOrArea: string;
  postcode: string;
  zone: string;
  notes?: string;
  coordinates?: Coordinates;
}

export interface AppSettings {
  merchantName: string;
  merchantPhone: string;
  merchantAddress: string;
  merchantState: string;
  merchantLga: string;
  merchantCoordinates?: Coordinates;
  nipostApiKey?: string;
  nipostApiBaseUrl?: string;
  nipostMode: 'mock' | 'live';
  supabaseUrl?: string;
  supabaseAnonKey?: string;
  autoVerifyPostcode: boolean;
  enableWhatsAppNotifications: boolean;
  requirePodOtp: boolean;
}
