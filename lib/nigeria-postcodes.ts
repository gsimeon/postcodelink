import { PostcodeEntry, Coordinates } from './types';
export type { PostcodeEntry };

export const NIGERIA_POSTCODES: PostcodeEntry[] = [
  // Lagos State
  { state: 'Lagos', lga: 'Ikeja', districtOrArea: 'Ikeja Central / Alausa', postcode: '100001', zone: 'South-West', notes: 'State Capital & Secretariat', coordinates: { lat: 6.6186, lng: 3.3570 } },
  { state: 'Lagos', lga: 'Ikeja', districtOrArea: 'Ikeja GRA', postcode: '100271', zone: 'South-West', notes: 'Residential & Commercial Hub', coordinates: { lat: 6.5885, lng: 3.3556 } },
  { state: 'Lagos', lga: 'Ikeja', districtOrArea: 'Maryland / Anthony', postcode: '100211', zone: 'South-West', coordinates: { lat: 6.5683, lng: 3.3712 } },
  { state: 'Lagos', lga: 'Ikeja', districtOrArea: 'Opebi / Allen Avenue', postcode: '100281', zone: 'South-West', coordinates: { lat: 6.5982, lng: 3.3538 } },
  { state: 'Lagos', lga: 'Eti-Osa', districtOrArea: 'Lekki Phase 1', postcode: '105102', zone: 'South-West', notes: 'High delivery density corridor', coordinates: { lat: 6.4474, lng: 3.4723 } },
  { state: 'Lagos', lga: 'Eti-Osa', districtOrArea: 'Victoria Island (VI)', postcode: '101241', zone: 'South-West', notes: 'Commercial financial centre', coordinates: { lat: 6.4281, lng: 3.4219 } },
  { state: 'Lagos', lga: 'Eti-Osa', districtOrArea: 'Ikoyi / Banana Island', postcode: '101233', zone: 'South-West', coordinates: { lat: 6.4549, lng: 3.4357 } },
  { state: 'Lagos', lga: 'Eti-Osa', districtOrArea: 'Chevron / Lekki Phase 2', postcode: '105101', zone: 'South-West', coordinates: { lat: 6.4382, lng: 3.5321 } },
  { state: 'Lagos', lga: 'Ibeju-Lekki', districtOrArea: 'Ajah / Sangotedo', postcode: '105101', zone: 'South-West', coordinates: { lat: 6.4673, lng: 3.5681 } },
  { state: 'Lagos', lga: 'Mainland', districtOrArea: 'Yaba / Sabo (Tech Hub)', postcode: '101212', zone: 'South-West', coordinates: { lat: 6.5095, lng: 3.3711 } },
  { state: 'Lagos', lga: 'Surulere', districtOrArea: 'Surulere / Stadium / Bode Thomas', postcode: '101283', zone: 'South-West', coordinates: { lat: 6.4969, lng: 3.3533 } },
  { state: 'Lagos', lga: 'Kosofe', districtOrArea: 'Magodo Phase 1 & 2 / Shangisha', postcode: '100248', zone: 'South-West', coordinates: { lat: 6.6212, lng: 3.3854 } },
  { state: 'Lagos', lga: 'Kosofe', districtOrArea: 'Gbagada / Ifako', postcode: '100234', zone: 'South-West', coordinates: { lat: 6.5562, lng: 3.3872 } },
  { state: 'Lagos', lga: 'Amuwo-Odofin', districtOrArea: 'Festac Town / Mile 2', postcode: '102102', zone: 'South-West', coordinates: { lat: 6.4698, lng: 3.2833 } },
  { state: 'Lagos', lga: 'Agege', districtOrArea: 'Agege / Pen Cinema', postcode: '100283', zone: 'South-West', coordinates: { lat: 6.6190, lng: 3.3230 } },
  { state: 'Lagos', lga: 'Oshodi-Isolo', districtOrArea: 'Oshodi / Airport Road', postcode: '100261', zone: 'South-West', coordinates: { lat: 6.5540, lng: 3.3411 } },
  { state: 'Lagos', lga: 'Apapa', districtOrArea: 'Apapa Port / Wharf', postcode: '101251', zone: 'South-West', coordinates: { lat: 6.4442, lng: 3.3642 } },
  { state: 'Lagos', lga: 'Ikorodu', districtOrArea: 'Ikorodu Central / Ogolonto', postcode: '104101', zone: 'South-West', coordinates: { lat: 6.6194, lng: 3.5105 } },

  // Abuja (Federal Capital Territory)
  { state: 'Abuja (FCT)', lga: 'Municipal (AMAC)', districtOrArea: 'Garki Area 1 - 11', postcode: '900001', zone: 'North-Central', notes: 'FCT Central Delivery Office', coordinates: { lat: 9.0345, lng: 7.4891 } },
  { state: 'Abuja (FCT)', lga: 'Municipal (AMAC)', districtOrArea: 'Wuse 2 (Adetokunbo Ademola / Aminu Kano)', postcode: '900288', zone: 'North-Central', notes: 'Prime Commercial District', coordinates: { lat: 9.0765, lng: 7.4722 } },
  { state: 'Abuja (FCT)', lga: 'Municipal (AMAC)', districtOrArea: 'Wuse Zone 1 - 7', postcode: '900281', zone: 'North-Central', coordinates: { lat: 9.0621, lng: 7.4612 } },
  { state: 'Abuja (FCT)', lga: 'Municipal (AMAC)', districtOrArea: 'Maitama District', postcode: '900271', zone: 'North-Central', notes: 'Diplomatic & High-Value Zone', coordinates: { lat: 9.0882, lng: 7.4984 } },
  { state: 'Abuja (FCT)', lga: 'Municipal (AMAC)', districtOrArea: 'Asokoro District', postcode: '900231', zone: 'North-Central', coordinates: { lat: 9.0512, lng: 7.5244 } },
  { state: 'Abuja (FCT)', lga: 'Municipal (AMAC)', districtOrArea: 'Central Business District (CBD)', postcode: '900211', zone: 'North-Central', coordinates: { lat: 9.0579, lng: 7.4951 } },
  { state: 'Abuja (FCT)', lga: 'Municipal (AMAC)', districtOrArea: 'Gwarinpa Estate', postcode: '900108', zone: 'North-Central', notes: 'Largest residential estate in West Africa', coordinates: { lat: 9.1088, lng: 7.3982 } },
  { state: 'Abuja (FCT)', lga: 'Municipal (AMAC)', districtOrArea: 'Utako / Jabi', postcode: '900104', zone: 'North-Central', coordinates: { lat: 9.0673, lng: 7.4328 } },
  { state: 'Abuja (FCT)', lga: 'Municipal (AMAC)', districtOrArea: 'Lugbe / Airport Express Corridor', postcode: '900107', zone: 'North-Central', coordinates: { lat: 8.9741, lng: 7.3719 } },
  { state: 'Abuja (FCT)', lga: 'Bwari', districtOrArea: 'Kubwa / Dutse', postcode: '901101', zone: 'North-Central', coordinates: { lat: 9.1539, lng: 7.3341 } },
  { state: 'Abuja (FCT)', lga: 'Municipal (AMAC)', districtOrArea: 'Nyanya / Mararaba Corridor', postcode: '900103', zone: 'North-Central', coordinates: { lat: 9.0312, lng: 7.5794 } },

  // Rivers State
  { state: 'Rivers', lga: 'Port Harcourt', districtOrArea: 'Old GRA / Forces Avenue', postcode: '500001', zone: 'South-South', notes: 'Port Harcourt General Post Office', coordinates: { lat: 4.8156, lng: 7.0498 } },
  { state: 'Rivers', lga: 'Port Harcourt', districtOrArea: 'D-Line / Aba Road', postcode: '500261', zone: 'South-South', coordinates: { lat: 4.8089, lng: 7.0092 } },
  { state: 'Rivers', lga: 'Port Harcourt', districtOrArea: 'Trans-Amadi Industrial Layout', postcode: '500211', zone: 'South-South', coordinates: { lat: 4.8234, lng: 7.0392 } },
  { state: 'Rivers', lga: 'Obio-Akpor', districtOrArea: 'Rumuola / Rumuokwuta', postcode: '500272', zone: 'South-South', coordinates: { lat: 4.8389, lng: 6.9972 } },
  { state: 'Rivers', lga: 'Obio-Akpor', districtOrArea: 'Choba (Uniport Corridor)', postcode: '500102', zone: 'South-South', coordinates: { lat: 4.9012, lng: 6.9123 } },
  { state: 'Rivers', lga: 'Eleme', districtOrArea: 'Eleme / Petrochemical Zone', postcode: '501101', zone: 'South-South', coordinates: { lat: 4.7891, lng: 7.1234 } },

  // Oyo State
  { state: 'Oyo', lga: 'Ibadan North', districtOrArea: 'Bodija / Old Bodija', postcode: '200213', zone: 'South-West', coordinates: { lat: 7.4325, lng: 3.9056 } },
  { state: 'Oyo', lga: 'Ibadan North', districtOrArea: 'University of Ibadan / Samonda', postcode: '200281', zone: 'South-West', coordinates: { lat: 7.4452, lng: 3.9011 } },
  { state: 'Oyo', lga: 'Ibadan North-West', districtOrArea: 'Dugbe Commercial District', postcode: '200263', zone: 'South-West', notes: 'Ibadan GPO', coordinates: { lat: 7.3889, lng: 3.8791 } },
  { state: 'Oyo', lga: 'Ibadan South-West', districtOrArea: 'Ring Road / Challenge', postcode: '200255', zone: 'South-West', coordinates: { lat: 7.3621, lng: 3.8642 } },
  { state: 'Oyo', lga: 'Ibadan South-West', districtOrArea: 'Oluyole Estate', postcode: '200273', zone: 'South-West', coordinates: { lat: 7.3510, lng: 3.8710 } },

  // Ogun State
  { state: 'Ogun', lga: 'Abeokuta South', districtOrArea: 'Abeokuta Central / Ake', postcode: '110001', zone: 'South-West', coordinates: { lat: 7.1557, lng: 3.3486 } },
  { state: 'Ogun', lga: 'Abeokuta South', districtOrArea: 'Ibara GRA / Oke-Mosan', postcode: '110252', zone: 'South-West', coordinates: { lat: 7.1421, lng: 3.3245 } },
  { state: 'Ogun', lga: 'Ado-Odo/Ota', districtOrArea: 'Ota Industrial Zone / Sango', postcode: '112212', zone: 'South-West', coordinates: { lat: 6.6912, lng: 3.2341 } },
  { state: 'Ogun', lga: 'Obafemi Owode', districtOrArea: 'Mowe / Ibafo (Lagos Border)', postcode: '110115', zone: 'South-West', coordinates: { lat: 6.8123, lng: 3.4412 } },

  // Kano State
  { state: 'Kano', lga: 'Kano Municipal', districtOrArea: 'Kano Central / Post Office Rd', postcode: '700001', zone: 'North-West', notes: 'Kano GPO', coordinates: { lat: 12.0022, lng: 8.5920 } },
  { state: 'Kano', lga: 'Fagge', districtOrArea: 'Fagge / Cantonment', postcode: '700211', zone: 'North-West', coordinates: { lat: 12.0145, lng: 8.5321 } },
  { state: 'Kano', lga: 'Nassarawa', districtOrArea: 'Bompai Industrial Area / GRA', postcode: '700282', zone: 'North-West', coordinates: { lat: 12.0234, lng: 8.5671 } },
  { state: 'Kano', lga: 'Fagge', districtOrArea: 'Sabon Gari Market', postcode: '700221', zone: 'North-West', coordinates: { lat: 12.0089, lng: 8.5412 } },

  // Kaduna State
  { state: 'Kaduna', lga: 'Kaduna North', districtOrArea: 'Kaduna Central / Ahmadu Bello Way', postcode: '800001', zone: 'North-West', coordinates: { lat: 10.5105, lng: 7.4165 } },
  { state: 'Kaduna', lga: 'Kaduna North', districtOrArea: 'Malali GRA', postcode: '800271', zone: 'North-West', coordinates: { lat: 10.5512, lng: 7.4521 } },
  { state: 'Kaduna', lga: 'Kaduna South', districtOrArea: 'Barnawa / Narayi', postcode: '800242', zone: 'North-West', coordinates: { lat: 10.4821, lng: 7.4312 } },

  // Enugu State
  { state: 'Enugu', lga: 'Enugu North', districtOrArea: 'Independence Layout / Government House', postcode: '400001', zone: 'South-East', notes: 'Enugu GPO', coordinates: { lat: 6.4413, lng: 7.5190 } },
  { state: 'Enugu', lga: 'Enugu North', districtOrArea: 'New Haven / Ogui', postcode: '400102', zone: 'South-East', coordinates: { lat: 6.4491, lng: 7.5021 } },
  { state: 'Enugu', lga: 'Enugu North', districtOrArea: 'GRA Enugu', postcode: '400271', zone: 'South-East', coordinates: { lat: 6.4589, lng: 7.4912 } },

  // Delta State
  { state: 'Delta', lga: 'Oshimili South', districtOrArea: 'Asaba Central / Nnebisi Rd', postcode: '320001', zone: 'South-South', coordinates: { lat: 6.1984, lng: 6.7321 } },
  { state: 'Delta', lga: 'Warri South', districtOrArea: 'Warri Central / Airport Rd', postcode: '332001', zone: 'South-South', coordinates: { lat: 5.5174, lng: 5.7501 } },
  { state: 'Delta', lga: 'Uvwie', districtOrArea: 'Effurun / PTI Road', postcode: '330102', zone: 'South-South', coordinates: { lat: 5.5612, lng: 5.7891 } },

  // Edo State
  { state: 'Edo', lga: 'Oredo', districtOrArea: 'Benin City Central / Ring Road', postcode: '300001', zone: 'South-South', coordinates: { lat: 6.3350, lng: 5.6037 } },
  { state: 'Edo', lga: 'Oredo', districtOrArea: 'GRA Benin City', postcode: '300251', zone: 'South-South', coordinates: { lat: 6.3121, lng: 5.6212 } },

  // Anambra State
  { state: 'Anambra', lga: 'Awka South', districtOrArea: 'Awka Central / Zik Avenue', postcode: '420001', zone: 'South-East', coordinates: { lat: 6.2209, lng: 7.0718 } },
  { state: 'Anambra', lga: 'Onitsha North', districtOrArea: 'Onitsha Main Market / Old Market Rd', postcode: '430001', zone: 'South-East', coordinates: { lat: 6.1512, lng: 6.7821 } }
];

export const STATES_LIST = Array.from(new Set(NIGERIA_POSTCODES.map(p => p.state))).sort();

export function searchPostcodes(query: string): PostcodeEntry[] {
  const clean = query.trim().toLowerCase();
  if (!clean) return NIGERIA_POSTCODES.slice(0, 15);
  
  return NIGERIA_POSTCODES.filter(item => 
    item.postcode.includes(clean) ||
    item.districtOrArea.toLowerCase().includes(clean) ||
    item.lga.toLowerCase().includes(clean) ||
    item.state.toLowerCase().includes(clean) ||
    (item.notes && item.notes.toLowerCase().includes(clean))
  );
}

export function lookupPostcode(code: string): PostcodeEntry | undefined {
  const clean = code.trim();
  return NIGERIA_POSTCODES.find(p => p.postcode === clean);
}

export function getLgasForState(state: string): string[] {
  const lgas = NIGERIA_POSTCODES
    .filter(p => p.state.toLowerCase() === state.toLowerCase())
    .map(p => p.lga);
  return Array.from(new Set(lgas)).sort();
}

export interface AddressAnalysis {
  detectedState?: string;
  detectedLga?: string;
  detectedArea?: string;
  matchedPostcode?: string;
  confidence: 'high' | 'medium' | 'low';
  standardizedAddress: string;
  notes: string;
  coordinates?: Coordinates;
}

/**
 * Intelligent Nigerian Address Parser and Postcode Resolver
 * Handles common Nigerian address structures (e.g., "Opposite Yellow Gate, Admiralty Way, Lekki Phase 1, Lagos")
 */
export function cleanseAndStandardizeAddress(raw: string): AddressAnalysis {
  const lower = raw.toLowerCase();
  
  // 1. Check for explicit 6-digit postcode pattern
  const codeMatch = raw.match(/\b\d{6}\b/);
  if (codeMatch) {
    const entry = lookupPostcode(codeMatch[0]);
    if (entry) {
      return {
        detectedState: entry.state,
        detectedLga: entry.lga,
        detectedArea: entry.districtOrArea,
        matchedPostcode: entry.postcode,
        confidence: 'high',
        standardizedAddress: `${raw.replace(/\b\d{6}\b/, '').replace(/,\s*,/g, ',').trim()} [Postcode: ${entry.postcode}]`,
        notes: `Matched official NIPOST code ${entry.postcode} for ${entry.districtOrArea}, ${entry.state}`,
        coordinates: entry.coordinates
      };
    }
  }

  // 2. Scan for matching areas/districts
  for (const entry of NIGERIA_POSTCODES) {
    const areaTokens = entry.districtOrArea.toLowerCase().split(/[\/,()]+/).map(s => s.trim()).filter(Boolean);
    for (const token of areaTokens) {
      if (token.length > 3 && lower.includes(token)) {
        return {
          detectedState: entry.state,
          detectedLga: entry.lga,
          detectedArea: entry.districtOrArea,
          matchedPostcode: entry.postcode,
          confidence: 'high',
          standardizedAddress: `${raw} — ${entry.lga}, ${entry.state} (NG-${entry.postcode})`,
          notes: `Identified area "${token}" matched to ${entry.districtOrArea} with postcode ${entry.postcode}`,
          coordinates: entry.coordinates
        };
      }
    }
  }

  // 3. Scan for State & LGA
  for (const entry of NIGERIA_POSTCODES) {
    if (lower.includes(entry.lga.toLowerCase()) && lower.includes(entry.state.toLowerCase())) {
      return {
        detectedState: entry.state,
        detectedLga: entry.lga,
        detectedArea: entry.districtOrArea,
        matchedPostcode: entry.postcode,
        confidence: 'medium',
        standardizedAddress: `${raw} — ${entry.state} (Zone: ${entry.postcode})`,
        notes: `Resolved to LGA ${entry.lga}, ${entry.state}. Recommended dispatch hub: ${entry.postcode}`,
        coordinates: entry.coordinates
      };
    }
  }

  // Fallback
  return {
    confidence: 'low',
    standardizedAddress: raw,
    notes: 'Could not automatically match an official postcode. Manual verification recommended.'
  };
}
