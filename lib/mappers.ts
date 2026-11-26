import { FastAPICustomer, FastAPIDelivery, FastAPIOperator } from './fastapi-client';
import { mapActorRole, mapBackendToFrontendStatus, mapPostcodeStatus } from './state-machine';
import { Customer, Delivery, DeliveryStatus, Operator } from './types';

export function mapFastAPIDelivery(fd: FastAPIDelivery): Delivery {
  const mappedStatus: DeliveryStatus = mapBackendToFrontendStatus(fd.status);

  return {
    id: fd.id,
    recipientName: fd.recipient_name,
    recipientPhone: fd.recipient_phone,
    destinationAddress: fd.destination_address,
    landmark: fd.destination_landmark,
    destinationArea: fd.destination_area,
    destinationCity: fd.destination_area,
    destinationState: fd.destination_state,
    postcodeInput: fd.postcode_input,
    postcodeStatus: mapPostcodeStatus(fd.postcode_status),
    verifiedPostcode: fd.verified_postcode,
    packageDescription: fd.package_description,
    fee: fd.fee,
    operatorId: fd.operator_id,
    operatorName: fd.assigned_operator?.business_name || (fd.operator_id ? 'Assigned Fleet' : 'Not assigned'),
    status: mappedStatus,
    createdAt: fd.created_at,
    updatedAt: fd.updated_at,
    events: (fd.events || []).map((e) => ({
      id: e.id,
      deliveryId: e.delivery_id,
      status: mapBackendToFrontendStatus(e.status),
      actor: e.actor_name,
      actorRole: mapActorRole(e.actor_role),
      note: e.note,
      timestamp: e.occurred_at,
    })),
    otpAttempts: fd.otp_attempts,
    otpMaxAttempts: fd.otp_max_attempts,
    podVerified: fd.pod_verified,
    podNote: fd.pod_note,
    coordinates: fd.lat && fd.lng ? { lat: fd.lat, lng: fd.lng } : undefined,
  };
}

export function mapFastAPIOperator(fo: FastAPIOperator): Operator {
  let vType: Operator['vehicleType'] = 'Motorcycle';
  if (fo.vehicle_type === 'van') vType = 'Delivery Van';
  else if (fo.vehicle_type === 'truck') vType = 'Truck';
  else if (fo.vehicle_type === 'bicycle') vType = 'Bicycle';

  return {
    id: fo.id,
    businessName: fo.business_name,
    contactPerson: fo.business_name,
    phone: fo.phone,
    vehicleType: vType,
    serviceAreas: fo.service_areas || [],
    isAvailable: fo.is_available,
    rating: fo.rating,
    completedDeliveries: fo.completed_deliveries,
    activeDeliveriesCount: fo.active_deliveries_count,
    currentZone: fo.service_areas?.[0] || 'Lagos Metro',
  };
}

export function mapFastAPICustomer(fc: FastAPICustomer): Customer {
  return {
    id: fc.id,
    fullName: fc.full_name,
    phone: fc.phone,
    email: fc.email,
    defaultAddress: fc.default_address,
    area: fc.area,
    state: fc.state,
    postcode: fc.postcode || '',
    totalOrders: fc.total_orders,
  };
}
