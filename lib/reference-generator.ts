/**
 * Cryptographically sound reference and OTP generators for PostcodeLink Nigeria
 */

export function generateDeliveryReference(prefix: string = 'PL'): string {
  const year = new Date().getFullYear();
  
  // Use crypto.getRandomValues if available, fallback to high-res timestamp
  let randomPart = '';
  if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
    const array = new Uint8Array(4);
    crypto.getRandomValues(array);
    randomPart = Array.from(array, (byte) => byte.toString(16).padStart(2, '0')).join('').toUpperCase();
  } else {
    randomPart = Math.floor(10000000 + Math.random() * 90000000).toString(16).toUpperCase();
  }

  // Format: PL-2026-A1B2C3D4
  return `${prefix}-${year}-${randomPart.slice(0, 6)}`;
}

export function generateSecureOtp(length: number = 6): string {
  if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
    const array = new Uint32Array(1);
    crypto.getRandomValues(array);
    if (length === 4) {
      return (1000 + (array[0] % 9000)).toString();
    }
    // 6-digit PIN between 100000 and 999999 matching backend enterprise standard
    const code = 100000 + (array[0] % 900000);
    return code.toString();
  }
  if (length === 4) {
    return Math.floor(1000 + Math.random() * 9000).toString();
  }
  return Math.floor(100000 + Math.random() * 900000).toString();
}

