import { NextRequest, NextResponse } from "next/server";
import { serverLookupPostcode } from "@/lib/postcode-adapter";

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const code = searchParams.get("code");

  if (!code || code.trim().length !== 6 || !/^\d{6}$/.test(code.trim())) {
    return NextResponse.json(
      {
        success: false,
        message: "A valid 6-digit Nigerian numeric postcode is required.",
      },
      { status: 400 }
    );
  }

  const result = await serverLookupPostcode(code);
  return NextResponse.json(result, { status: result.success ? 200 : 404 });
}

