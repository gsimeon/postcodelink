import { NextResponse } from "next/server";

/**
 * Legacy Next.js OTP route intentionally disabled (fail-closed HTTP 503).
 * Proof-of-Delivery OTP verification is handled exclusively by the authenticated
 * FastAPI backend (/api/v1/deliveries/{delivery_id}/verify-otp or
 * /api/v1/deliveries/track/{tracking_token}/confirm-delivery).
 */
export async function POST() {
  return NextResponse.json(
    {
      success: false,
      detail:
        "Legacy Next.js OTP route is disabled. Use the authenticated FastAPI proof-of-delivery endpoint.",
    },
    { status: 503 }
  );
}
