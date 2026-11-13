import { NextRequest, NextResponse } from "next/server";
import { serverCleanseAddress } from "@/lib/postcode-adapter";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const { address } = body;

    if (!address || typeof address !== "string" || address.trim().length < 3) {
      return NextResponse.json(
        {
          success: false,
          message: "Address text parameter is required.",
        },
        { status: 400 }
      );
    }

    const analysis = serverCleanseAddress(address.trim());
    return NextResponse.json({ success: true, analysis }, { status: 200 });
  } catch (err: any) {
    return NextResponse.json(
      { success: false, message: err?.message || "Invalid request payload" },
      { status: 500 }
    );
  }
}

