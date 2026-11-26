import { AppSettings, Customer, Delivery, DeliveryEvent, Operator } from './types';
import { validateStateTransition } from './state-machine';

const STORAGE_KEYS = {
  DELIVERIES: 'postcodelink_deliveries_v1',
  OPERATORS: 'postcodelink_operators_v1',
  CUSTOMERS: 'postcodelink_customers_v1',
  SETTINGS: 'postcodelink_settings_v1',
};

export const INITIAL_OPERATORS: Operator[] = [
  {
    id: 'op-1',
    businessName: 'SwiftMove Logistics',
    contactPerson: 'Babajide Fashola',
    phone: '+234 803 451 9021',
    vehicleType: 'Motorcycle',
    serviceAreas: ['Lekki Phase 1', 'Victoria Island (VI)', 'Ikoyi / Banana Island', 'Chevron'],
    isAvailable: true,
    rating: 4.9,
    completedDeliveries: 342,
    activeDeliveriesCount: 1,
    currentZone: 'Lekki Phase 1',
    coordinates: { lat: 6.4474, lng: 3.4723 },
  },
  {
    id: 'op-2',
    businessName: 'CityRoute NG',
    contactPerson: 'Emeka Nwosu',
    phone: '+234 812 770 4492',
    vehicleType: 'Delivery Van',
    serviceAreas: ['Ikeja Central / Alausa', 'Ikeja GRA', 'Maryland / Anthony', 'Magodo'],
    isAvailable: true,
    rating: 4.8,
    completedDeliveries: 512,
    activeDeliveriesCount: 0,
    currentZone: 'Ikeja GRA',
    coordinates: { lat: 6.5885, lng: 3.3556 },
  },
  {
    id: 'op-3',
    businessName: 'Apex Capital Express',
    contactPerson: 'Aliyu Danladi',
    phone: '+234 809 112 8834',
    vehicleType: 'Motorcycle',
    serviceAreas: ['Garki Area 1 - 11', 'Wuse 2', 'Maitama District', 'Central Business District (CBD)'],
    isAvailable: true,
    rating: 4.95,
    completedDeliveries: 188,
    activeDeliveriesCount: 0,
    currentZone: 'Wuse 2, Abuja',
    coordinates: { lat: 9.0765, lng: 7.4722 },
  },
  {
    id: 'op-4',
    businessName: 'Kwik Express Couriers',
    contactPerson: 'Chidinma Eze',
    phone: '+234 705 993 1102',
    vehicleType: 'Tricycle (Keke)',
    serviceAreas: ['Yaba / Sabo (Tech Hub)', 'Surulere', 'Gbagada / Ifako'],
    isAvailable: false,
    rating: 4.6,
    completedDeliveries: 94,
    activeDeliveriesCount: 0,
    currentZone: 'Yaba, Lagos',
    coordinates: { lat: 6.5095, lng: 3.3711 },
  },
  {
    id: 'op-5',
    businessName: 'Delta-Rivers FastCargo',
    contactPerson: 'Tariere Briggs',
    phone: '+234 818 439 7712',
    vehicleType: 'Delivery Van',
    serviceAreas: ['Old GRA / Forces Avenue', 'Trans-Amadi', 'D-Line', 'Rumuola'],
    isAvailable: true,
    rating: 4.7,
    completedDeliveries: 230,
    activeDeliveriesCount: 0,
    currentZone: 'Old GRA, Port Harcourt',
    coordinates: { lat: 4.8156, lng: 7.0498 },
  }
];

export const INITIAL_CUSTOMERS: Customer[] = [
  {
    id: 'cust-1',
    fullName: 'Adaeze Okafor',
    phone: '+234 802 334 9102',
    email: 'adaeze.okafor@gmail.com',
    defaultAddress: '14 Admiralty Way, Opp. Ebeano Supermarket',
    area: 'Lekki Phase 1',
    state: 'Lagos',
    postcode: '105102',
    totalOrders: 12,
  },
  {
    id: 'cust-2',
    fullName: 'Tunde Bello',
    phone: '+234 814 559 0021',
    email: 'tunde.bello@outlook.com',
    defaultAddress: 'Plot 412, Aminu Kano Crescent, Near Access Bank',
    area: 'Wuse 2',
    state: 'Abuja (FCT)',
    postcode: '900288',
    totalOrders: 5,
  },
  {
    id: 'cust-3',
    fullName: 'Mariam Yusuf',
    phone: '+234 805 120 7843',
    email: 'mariam.yusuf@konga.com',
    defaultAddress: '28 Isaac John Street, Beside Radisson Blu',
    area: 'Ikeja GRA',
    state: 'Lagos',
    postcode: '100271',
    totalOrders: 8,
  },
  {
    id: 'cust-4',
    fullName: 'Ken Saro Briggs',
    phone: '+234 803 771 9901',
    email: 'ken.briggs@phc-energy.com',
    defaultAddress: '8 Forces Avenue, Old GRA',
    area: 'Old GRA / Forces Avenue',
    state: 'Rivers',
    postcode: '500001',
    totalOrders: 4,
  }
];

export const INITIAL_DELIVERIES: Delivery[] = [
  {
    id: 'PL-2048',
    recipientName: 'Adaeze Okafor',
    recipientPhone: '+234 802 334 9102',
    recipientEmail: 'adaeze.okafor@gmail.com',
    destinationAddress: '14 Admiralty Way, Opp. Ebeano Supermarket',
    landmark: 'Opposite Ebeano Supermarket',
    destinationArea: 'Lekki Phase 1',
    destinationCity: 'Lagos',
    destinationState: 'Lagos',
    postcodeInput: '105102',
    postcodeStatus: 'verified',
    verifiedPostcode: '105102',
    packageDescription: 'Designer Handbag & Cosmetic Set (Fragile)',
    fee: 4500,
    operatorId: 'op-1',
    operatorName: 'SwiftMove Logistics',
    status: 'in_transit',
    createdAt: 'Today, 10:42 AM',
    updatedAt: 'Today, 11:15 AM',
    otp: '4821',
    podVerified: false,
    coordinates: { lat: 6.4474, lng: 3.4723 },
    estimatedDeliveryTime: 'Within 45 mins (ETA 12:00 PM)',
    events: [
      {
        id: 'ev-1',
        deliveryId: 'PL-2048',
        status: 'draft',
        actor: 'Peak Stores Admin',
        actorRole: 'merchant',
        note: 'Order imported from checkout with verified postcode 105102',
        timestamp: 'Today, 10:42 AM',
      },
      {
        id: 'ev-2',
        deliveryId: 'PL-2048',
        status: 'assigned',
        actor: 'Auto Dispatch Engine',
        actorRole: 'system',
        note: 'Assigned to SwiftMove Logistics based on Lekki zone coverage',
        timestamp: 'Today, 10:50 AM',
      },
      {
        id: 'ev-3',
        deliveryId: 'PL-2048',
        status: 'in_transit',
        actor: 'Babajide Fashola (SwiftMove)',
        actorRole: 'rider',
        note: 'Package picked up from Lekki hub, heading along Admiralty Way',
        timestamp: 'Today, 11:15 AM',
      }
    ]
  },
  {
    id: 'PL-2047',
    recipientName: 'Tunde Bello',
    recipientPhone: '+234 814 559 0021',
    recipientEmail: 'tunde.bello@outlook.com',
    destinationAddress: 'Plot 412, Aminu Kano Crescent',
    landmark: 'Beside Access Bank',
    destinationArea: 'Wuse 2',
    destinationCity: 'Abuja',
    destinationState: 'Abuja (FCT)',
    postcodeInput: '900288',
    postcodeStatus: 'verified',
    verifiedPostcode: '900288',
    packageDescription: 'MacBook Air 15" M3 (Sealed electronics)',
    fee: 7500,
    operatorId: undefined,
    operatorName: 'Not assigned',
    status: 'pending_assignment',
    createdAt: 'Today, 09:18 AM',
    updatedAt: 'Today, 09:18 AM',
    otp: '9104',
    podVerified: false,
    coordinates: { lat: 9.0765, lng: 7.4722 },
    estimatedDeliveryTime: 'Awaiting courier assignment',
    events: [
      {
        id: 'ev-4',
        deliveryId: 'PL-2047',
        status: 'draft',
        actor: 'Peak Stores Admin',
        actorRole: 'merchant',
        note: 'Delivery request initiated. Awaiting operator dispatch.',
        timestamp: 'Today, 09:18 AM',
      }
    ]
  },
  {
    id: 'PL-2046',
    recipientName: 'Mariam Yusuf',
    recipientPhone: '+234 805 120 7843',
    recipientEmail: 'mariam.yusuf@konga.com',
    destinationAddress: '28 Isaac John Street',
    landmark: 'Beside Radisson Blu Hotel',
    destinationArea: 'Ikeja GRA',
    destinationCity: 'Ikeja',
    destinationState: 'Lagos',
    postcodeInput: '100271',
    postcodeStatus: 'verified',
    verifiedPostcode: '100271',
    packageDescription: 'Fashion Apparel (3 items)',
    fee: 3800,
    operatorId: 'op-2',
    operatorName: 'CityRoute NG',
    status: 'delivered',
    createdAt: 'Yesterday, 02:15 PM',
    updatedAt: 'Yesterday, 04:06 PM',
    otp: '3318',
    podVerified: true,
    podNote: 'Confirmed via 4-digit Recipient OTP and front desk security stamp.',
    coordinates: { lat: 6.5885, lng: 3.3556 },
    estimatedDeliveryTime: 'Delivered',
    events: [
      {
        id: 'ev-5',
        deliveryId: 'PL-2046',
        status: 'draft',
        actor: 'Peak Stores Admin',
        actorRole: 'merchant',
        note: 'Created delivery order',
        timestamp: 'Yesterday, 02:15 PM',
      },
      {
        id: 'ev-6',
        deliveryId: 'PL-2046',
        status: 'assigned',
        actor: 'Peak Stores Dispatch',
        actorRole: 'merchant',
        note: 'Assigned to CityRoute NG',
        timestamp: 'Yesterday, 02:30 PM',
      },
      {
        id: 'ev-7',
        deliveryId: 'PL-2046',
        status: 'in_transit',
        actor: 'Emeka Nwosu (CityRoute)',
        actorRole: 'rider',
        note: 'Out for delivery in Ikeja GRA',
        timestamp: 'Yesterday, 03:20 PM',
      },
      {
        id: 'ev-8',
        deliveryId: 'PL-2046',
        status: 'delivered',
        actor: 'Emeka Nwosu (CityRoute)',
        actorRole: 'rider',
        note: 'Delivered to recipient at Isaac John reception. Recipient OTP confirmed.',
        timestamp: 'Yesterday, 04:06 PM',
      }
    ]
  },
  {
    id: 'PL-2045',
    recipientName: 'Ken Saro Briggs',
    recipientPhone: '+234 803 771 9901',
    recipientEmail: 'ken.briggs@phc-energy.com',
    destinationAddress: '8 Forces Avenue, Old GRA',
    landmark: 'Near Shell Residential Camp',
    destinationArea: 'Old GRA / Forces Avenue',
    destinationCity: 'Port Harcourt',
    destinationState: 'Rivers',
    postcodeInput: '500001',
    postcodeStatus: 'verified',
    verifiedPostcode: '500001',
    packageDescription: 'Technical Documents & Field Gear',
    fee: 6000,
    operatorId: 'op-5',
    operatorName: 'Delta-Rivers FastCargo',
    status: 'assigned',
    createdAt: 'Yesterday, 11:30 AM',
    updatedAt: 'Yesterday, 01:00 PM',
    otp: '7729',
    podVerified: false,
    coordinates: { lat: 4.8156, lng: 7.0498 },
    estimatedDeliveryTime: 'Scheduled for afternoon transit',
    events: [
      {
        id: 'ev-9',
        deliveryId: 'PL-2045',
        status: 'draft',
        actor: 'Peak Stores Admin',
        actorRole: 'merchant',
        note: 'Created delivery request',
        timestamp: 'Yesterday, 11:30 AM',
      },
      {
        id: 'ev-10',
        deliveryId: 'PL-2045',
        status: 'assigned',
        actor: 'System',
        actorRole: 'system',
        note: 'Assigned to Delta-Rivers FastCargo for Port Harcourt Old GRA route',
        timestamp: 'Yesterday, 01:00 PM',
      }
    ]
  },
  {
    id: 'PL-2044',
    recipientName: 'Chiamaka Nwachukwu',
    recipientPhone: '+234 806 883 2199',
    destinationAddress: 'Opposite Yellow Gate after Transformer, off Agric Road',
    landmark: 'Yellow Gate after Transformer',
    destinationArea: 'Ikorodu',
    destinationCity: 'Ikorodu',
    destinationState: 'Lagos',
    postcodeInput: '',
    postcodeStatus: 'unverified',
    packageDescription: 'Kitchenware Set',
    fee: 4000,
    operatorId: undefined,
    operatorName: 'Not assigned',
    status: 'draft',
    createdAt: '2 days ago',
    updatedAt: '2 days ago',
    otp: '1290',
    podVerified: false,
    coordinates: { lat: 6.6194, lng: 3.5105 },
    estimatedDeliveryTime: 'Pending address validation',
    events: [
      {
        id: 'ev-11',
        deliveryId: 'PL-2044',
        status: 'draft',
        actor: 'Peak Stores Admin',
        actorRole: 'merchant',
        note: 'Manual landmark address saved without postcode verification. Requires address resolution.',
        timestamp: '2 days ago',
      }
    ]
  }
];

export const INITIAL_SETTINGS: AppSettings = {
  merchantName: 'Peak Stores Nigeria',
  merchantPhone: '+234 800 732 5786',
  merchantAddress: 'Plot 12, Commercial Avenue, Sabo-Yaba',
  merchantState: 'Lagos',
  merchantLga: 'Mainland',
  merchantCoordinates: { lat: 6.5095, lng: 3.3711 },
  nipostApiKey: '',
  nipostApiBaseUrl: 'https://api.nipost.gov.ng/v1',
  nipostMode: 'mock',
  supabaseUrl: '',
  supabaseAnonKey: '',
  autoVerifyPostcode: true,
  enableWhatsAppNotifications: true,
  requirePodOtp: true,
};

// Storage Helpers
function isClient(): boolean {
  return typeof window !== 'undefined';
}

function notifyDataUpdated() {
  if (isClient()) {
    window.dispatchEvent(new Event('postcodelink-data-updated'));
  }
}

export function getStoredDeliveries(): Delivery[] {
  if (!isClient()) return INITIAL_DELIVERIES;
  const raw = localStorage.getItem(STORAGE_KEYS.DELIVERIES);
  if (!raw) {
    localStorage.setItem(STORAGE_KEYS.DELIVERIES, JSON.stringify(INITIAL_DELIVERIES));
    return INITIAL_DELIVERIES;
  }
  try {
    return JSON.parse(raw);
  } catch {
    return INITIAL_DELIVERIES;
  }
}

export function saveDeliveries(deliveries: Delivery[]): void {
  if (!isClient()) return;
  localStorage.setItem(STORAGE_KEYS.DELIVERIES, JSON.stringify(deliveries));
  notifyDataUpdated();
}

export function addDelivery(delivery: Delivery): void {
  const current = getStoredDeliveries();
  saveDeliveries([delivery, ...current]);
}

export function bulkAddDeliveries(newDeliveries: Delivery[]): void {
  const current = getStoredDeliveries();
  saveDeliveries([...newDeliveries, ...current]);
}

export function updateDelivery(id: string, updates: Partial<Delivery>): { delivery?: Delivery; error?: string } {
  const current = getStoredDeliveries();
  const existing = current.find(item => item.id === id);
  if (!existing) return { error: `Delivery with ID ${id} not found.` };

  // Validate state machine transition if status is being updated
  if (updates.status && updates.status !== existing.status) {
    const check = validateStateTransition(existing.status, updates.status);
    if (!check.valid) {
      return { error: check.message };
    }
  }

  let updatedDelivery: Delivery | undefined;
  const updated = current.map(item => {
    if (item.id === id) {
      updatedDelivery = {
        ...item,
        ...updates,
        updatedAt: 'Just now'
      };
      return updatedDelivery;
    }
    return item;
  });
  saveDeliveries(updated);
  return { delivery: updatedDelivery };
}

export function verifyDeliveryOtp(
  deliveryId: string,
  enteredOtp: string,
  note?: string
): { success: boolean; message: string; remainingAttempts?: number } {
  const current = getStoredDeliveries();
  const delivery = current.find(d => d.id === deliveryId);
  if (!delivery) return { success: false, message: 'Delivery record not found.' };

  // Check terminal state
  if (delivery.status === 'delivered') {
    return { success: false, message: 'This delivery is already marked as delivered.' };
  }
  if (delivery.status === 'cancelled') {
    return { success: false, message: 'Cannot verify OTP on a cancelled delivery.' };
  }

  // Check rate limiting / lockout
  const now = new Date();
  if (delivery.otpLockedUntil) {
    const lockTime = new Date(delivery.otpLockedUntil);
    if (lockTime > now) {
      const minutesRemaining = Math.ceil((lockTime.getTime() - now.getTime()) / (60 * 1000));
      return {
        success: false,
        message: `Verification locked due to multiple failed attempts. Try again in ${minutesRemaining} minute(s).`
      };
    }
  }

  const maxAttempts = delivery.otpMaxAttempts || 3;
  const currentAttempts = delivery.otpAttempts || 0;

  // Validate OTP code
  const targetOtp = delivery.otp ? delivery.otp.trim() : '';
  if (!targetOtp || targetOtp !== enteredOtp.trim()) {
    const newAttempts = currentAttempts + 1;
    if (newAttempts >= maxAttempts) {
      const lockUntil = new Date(now.getTime() + 15 * 60 * 1000).toISOString(); // 15 min lock
      updateDelivery(deliveryId, {
        otpAttempts: newAttempts,
        otpLockedUntil: lockUntil,
      });
      return {
        success: false,
        remainingAttempts: 0,
        message: `Invalid 4-digit PIN. Maximum attempts exceeded. Verification locked for 15 minutes.`
      };
    } else {
      updateDelivery(deliveryId, {
        otpAttempts: newAttempts,
      });
      const remaining = maxAttempts - newAttempts;
      return {
        success: false,
        remainingAttempts: remaining,
        message: `Invalid 4-digit PIN. ${remaining} attempt(s) remaining before lockout.`
      };
    }
  }

  // Successful verification
  addDeliveryEvent(deliveryId, {
    status: 'delivered',
    actor: 'Courier Rider (OTP Verified)',
    actorRole: 'rider',
    note: note || "Confirmed via demo recipient OTP. Proof of delivery authenticated."
  });

  updateDelivery(deliveryId, {
    status: 'delivered',
    podVerified: true,
    podNote: note || "OTP Verified Delivery (Demo Mode)",
    otpAttempts: 0,
    otpLockedUntil: undefined,
  });

  return { success: true, message: 'Proof of Delivery verified! Order marked completed.' };
}

export function addDeliveryEvent(deliveryId: string, event: Omit<DeliveryEvent, 'id' | 'deliveryId' | 'timestamp'>): void {
  const current = getStoredDeliveries();
  const updated = current.map(item => {
    if (item.id === deliveryId) {
      const newEvent: DeliveryEvent = {
        id: `ev-${Date.now()}`,
        deliveryId,
        status: event.status,
        actor: event.actor,
        actorRole: event.actorRole,
        note: event.note,
        timestamp: 'Just now'
      };
      return {
        ...item,
        status: event.status,
        updatedAt: 'Just now',
        events: [...item.events, newEvent]
      };
    }
    return item;
  });
  saveDeliveries(updated);
}

export function deleteDelivery(id: string): void {
  const current = getStoredDeliveries();
  saveDeliveries(current.filter(item => item.id !== id));
}

export function getStoredOperators(): Operator[] {
  if (!isClient()) return INITIAL_OPERATORS;
  const raw = localStorage.getItem(STORAGE_KEYS.OPERATORS);
  if (!raw) {
    localStorage.setItem(STORAGE_KEYS.OPERATORS, JSON.stringify(INITIAL_OPERATORS));
    return INITIAL_OPERATORS;
  }
  try {
    return JSON.parse(raw);
  } catch {
    return INITIAL_OPERATORS;
  }
}

export function saveOperators(operators: Operator[]): void {
  if (!isClient()) return;
  localStorage.setItem(STORAGE_KEYS.OPERATORS, JSON.stringify(operators));
  notifyDataUpdated();
}

export function updateOperator(id: string, updates: Partial<Operator>): void {
  const current = getStoredOperators();
  saveOperators(current.map(op => op.id === id ? { ...op, ...updates } : op));
}

export function addOperator(op: Operator): void {
  const current = getStoredOperators();
  saveOperators([op, ...current]);
}

export function getStoredCustomers(): Customer[] {
  if (!isClient()) return INITIAL_CUSTOMERS;
  const raw = localStorage.getItem(STORAGE_KEYS.CUSTOMERS);
  if (!raw) {
    localStorage.setItem(STORAGE_KEYS.CUSTOMERS, JSON.stringify(INITIAL_CUSTOMERS));
    return INITIAL_CUSTOMERS;
  }
  try {
    return JSON.parse(raw);
  } catch {
    return INITIAL_CUSTOMERS;
  }
}

export function saveCustomers(customers: Customer[]): void {
  if (!isClient()) return;
  localStorage.setItem(STORAGE_KEYS.CUSTOMERS, JSON.stringify(customers));
  notifyDataUpdated();
}

export function addCustomer(customer: Customer): void {
  const current = getStoredCustomers();
  saveCustomers([customer, ...current]);
}

export function getStoredSettings(): AppSettings {
  if (!isClient()) return INITIAL_SETTINGS;
  const raw = localStorage.getItem(STORAGE_KEYS.SETTINGS);
  if (!raw) {
    localStorage.setItem(STORAGE_KEYS.SETTINGS, JSON.stringify(INITIAL_SETTINGS));
    return INITIAL_SETTINGS;
  }
  try {
    return { ...INITIAL_SETTINGS, ...JSON.parse(raw) };
  } catch {
    return INITIAL_SETTINGS;
  }
}

export function saveSettings(settings: AppSettings): void {
  if (!isClient()) return;
  localStorage.setItem(STORAGE_KEYS.SETTINGS, JSON.stringify(settings));
  notifyDataUpdated();
}

export function resetAllData(): void {
  if (!isClient()) return;
  localStorage.setItem(STORAGE_KEYS.DELIVERIES, JSON.stringify(INITIAL_DELIVERIES));
  localStorage.setItem(STORAGE_KEYS.OPERATORS, JSON.stringify(INITIAL_OPERATORS));
  localStorage.setItem(STORAGE_KEYS.CUSTOMERS, JSON.stringify(INITIAL_CUSTOMERS));
  localStorage.setItem(STORAGE_KEYS.SETTINGS, JSON.stringify(INITIAL_SETTINGS));
  notifyDataUpdated();
}
