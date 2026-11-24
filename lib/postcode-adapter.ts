import { lookupPostcode, cleanseAndStandardizeAddress, PostcodeEntry, AddressAnalysis } from './nigeria-postcodes';

/**
 * Server-Side NIPOST / FMCIDE Digital Postcode Gateway Adapter
 * Reads credentials strictly from process.env on the server.
 * Never exposes private API credentials to client-side bundles.
 */

const NIPOST_API_BASE_URL = process.env.NIPOST_API_BASE_URL || 'https://api.nipost.gov.ng/v1';
const NIPOST_API_KEY = process.env.NIPOST_API_KEY || '';

export type VerificationTrustStatus =
  | 'officially_verified'
  | 'local_match'
  | 'partial_verification'
  | 'address_conflict'
  | 'unavailable';

export interface PostcodeLookupResponse {
  success: boolean;
  code: string;
  source: 'live_nipost_fmcide_api' | 'local_reference';
  status: VerificationTrustStatus;
  entry?: PostcodeEntry;
  latencyMs: number;
  message: string;
  provenance: string;
  dataset_version?: string;
  is_official: boolean;
}

export function isWellFormedPostcode(code: string): boolean {
  const trimmed = code.trim();
  const isNumeric = /^\d{6}$/.test(trimmed);
  const isDigitalHyphen = /^[A-Z]{2}-\d{2}-[A-Z0-9]{3}-[A-Z]{2}-\d{2}$/i.test(trimmed);
  const isDigitalSpace = /^[A-Z]{2} \d{2} [A-Z0-9]{3} [A-Z]{2} \d{2}$/i.test(trimmed);
  const isDigitalCompact = /^[A-Z]{2}\d{2}[A-Z0-9]{3}[A-Z]{2}\d{2}$/i.test(trimmed);
  return isNumeric || isDigitalHyphen || isDigitalSpace || isDigitalCompact;
}

export async function serverLookupPostcode(
  code: string,
  strict: boolean = false,
  inputAddress?: { state?: string; lga?: string; area?: string }
): Promise<PostcodeLookupResponse> {
  const startTime = Date.now();
  const cleanCode = code.trim().toUpperCase();

  // 1. Format validation: check 6-digit conventional or 11-char compact / 15-char display digital format
  if (!isWellFormedPostcode(cleanCode)) {
    return {
      success: false,
      code: cleanCode,
      source: 'local_reference',
      status: 'unavailable',
      latencyMs: 0,
      message: 'Invalid postcode format. Must be a 6-digit numeric postal code or 11-character compact / 15-character display National Digital Postcode format.',
      provenance: 'PostcodeLink Format Validator',
      is_official: false,
    };
  }

  // 2. If official NIPOST credentials are configured, attempt upstream API call
  if (NIPOST_API_KEY && NIPOST_API_KEY.length > 5 && NIPOST_API_BASE_URL.startsWith('http')) {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 4000); // 4s timeout

      const res = await fetch(`${NIPOST_API_BASE_URL}/postcodes/${encodeURIComponent(cleanCode)}`, {
        headers: {
          'Authorization': `Bearer ${NIPOST_API_KEY}`,
          'Accept': 'application/json',
          'User-Agent': 'PostcodeLink-Nigeria/1.0',
        },
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      if (res.ok) {
        const data = await res.json();
        // Preserve upstream data without synthetic defaults
        const rawEntry = data.entry || data;
        const entry: PostcodeEntry = {
          postcode: cleanCode,
          state: rawEntry.state || undefined,
          lga: rawEntry.lga || undefined,
          districtOrArea: rawEntry.area || rawEntry.districtOrArea || undefined,
          zone: rawEntry.zone || undefined,
          coordinates: rawEntry.lat && rawEntry.lng ? { lat: rawEntry.lat, lng: rawEntry.lng } : undefined,
        };

        // Determine verification trust tier
        let trustStatus: VerificationTrustStatus = 'officially_verified';
        let statusMessage = 'Verified against live NIPOST / FMCIDE National Postcode API.';

        if (inputAddress?.state && entry.state && !entry.state.toLowerCase().includes(inputAddress.state.toLowerCase())) {
          trustStatus = 'address_conflict';
          statusMessage = `Address conflict: Postcode ${cleanCode} belongs to ${entry.state}, but ${inputAddress.state} was supplied.`;
        } else if (!entry.state || !entry.lga) {
          trustStatus = 'partial_verification';
          statusMessage = 'Postcode confirmed in NIPOST registry, but administrative address metadata is incomplete.';
        }

        return {
          success: true,
          code: cleanCode,
          source: 'live_nipost_fmcide_api',
          status: trustStatus,
          entry,
          latencyMs: Date.now() - startTime,
          message: statusMessage,
          provenance: 'NIPOST Live FMCIDE Gateway',
          dataset_version: data.dataset_version || 'NIPOST-LIVE-2026',
          is_official: true,
        };
      } else if (strict) {
        return {
          success: false,
          code: cleanCode,
          source: 'live_nipost_fmcide_api',
          status: 'unavailable',
          latencyMs: Date.now() - startTime,
          message: `NIPOST upstream returned status ${res.status}. Strict mode active: local fallback rejected.`,
          provenance: 'NIPOST Live FMCIDE Gateway',
          is_official: false,
        };
      }
    } catch (err: any) {
      if (strict) {
        return {
          success: false,
          code: cleanCode,
          source: 'live_nipost_fmcide_api',
          status: 'unavailable',
          latencyMs: Date.now() - startTime,
          message: `NIPOST upstream unreachable: ${err.message}. Strict mode active: local fallback rejected.`,
          provenance: 'NIPOST Live FMCIDE Gateway',
          is_official: false,
        };
      }
      console.warn('NIPOST upstream API unavailable, falling back to local reference dataset:', err.message);
    }
  }

  // 3. Local Reference Dataset Fallback
  const localMatch = lookupPostcode(cleanCode);
  const latency = Date.now() - startTime;

  if (localMatch) {
    let trustStatus: VerificationTrustStatus = 'local_match';
    let statusMessage = 'Matched against PostcodeLink local reference dataset (2024.2). Not an official government verification.';

    if (inputAddress?.state && localMatch.state && !localMatch.state.toLowerCase().includes(inputAddress.state.toLowerCase())) {
      trustStatus = 'address_conflict';
      statusMessage = `Address conflict: Local reference ${cleanCode} maps to ${localMatch.state}, but ${inputAddress.state} was supplied.`;
    }

    return {
      success: true,
      code: cleanCode,
      source: 'local_reference',
      status: trustStatus,
      entry: localMatch,
      latencyMs: latency,
      message: statusMessage,
      provenance: 'PostcodeLink Local Reference Dataset (2024.2)',
      dataset_version: '2024.2',
      is_official: false,
    };
  }

  return {
    success: false,
    code: cleanCode,
    source: 'local_reference',
    status: 'unavailable',
    latencyMs: latency,
    message: `Postcode ${cleanCode} not found in official registry or local reference dataset.`,
    provenance: 'PostcodeLink Local Reference Dataset (2024.2)',
    is_official: false,
  };
}

export function serverCleanseAddress(rawAddress: string): AddressAnalysis {
  return cleanseAndStandardizeAddress(rawAddress);
}


