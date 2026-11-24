import { NextRequest, NextResponse } from "next/server";
import { serverLookupPostcode, isWellFormedPostcode } from "@/lib/postcode-adapter";

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const code = searchParams.get("code");
  const strict = searchParams.get("strict") === "true";
  const state = searchParams.get("state") || undefined;
  const lga = searchParams.get("lga") || undefined;

  if (!code || !isWellFormedPostcode(code)) {
    return NextResponse.json(
      {
        success: false,
        message: "A valid 6-digit Nigerian numeric postcode or 15-character National Digital Postcode is required.",
      },
      { status: 400 }
    );
  }

  const result = await serverLookupPostcode(code, strict, { state, lga });
  const httpStatus = result.success ? 200 : result.status === 'unavailable' ? 503 : 404;
  return NextResponse.json(result, { status: httpStatus });
}


