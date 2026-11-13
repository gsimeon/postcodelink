import { NextRequest, NextResponse } from "next/server";
import { verifyDeliveryOtp } from "@/lib/storage";

/**
 * Server-side endpoint for Proof of Delivery (POD) OTP verification
 * Enforces rate limiting, attempt limits (max 3), and audit logging.
 */
export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const { deliveryId, otp, note } = body;

    if (!deliveryId || !otp) {
      return NextResponse.json(
        { success: false, message: "deliveryId and otp are required parameters." },
        { status: 400 }
      );
    }

    const cleanOtp = String(otp).trim();
    if (cleanOtp.length !== 4 || !/^\d{4}$/.test(cleanOtp)) {
      return NextResponse.json(
        { success: false, message: "OTP must be exactly 4 numeric digits." },
        { status: 400 }
      );
    }

    const result = verifyDeliveryOtp(deliveryId, cleanOtp, note);

    if (!result.success) {
      return NextResponse.json(result, { status: 401 });
    }

    return NextResponse.json(result, { status: 200 });
  } catch (error: any) {
    return NextResponse.json(
      { success: false, message: error?.message || "Internal server error" },
      { status: 500 }
    );
  }
}

