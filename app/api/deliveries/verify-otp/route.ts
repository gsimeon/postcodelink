import { NextResponse } from "next/server";

/**
 * Fail-closed until OTPs are persisted and verified against an authenticated,
 * server-side data store. The previous implementation used browser localStorage,
 * which is unavailable to this route and is not a security boundary.
 */
export async function POST() {
  return NextResponse.json(
    {
      success: false,
      code: "POD_VERIFICATION_NOT_CONFIGURED",
      message: "Proof-of-delivery verification is temporarily unavailable. Server-side OTP storage and authenticated rider access must be configured first.",
    },
    { status: 503 }
  );
}
