import { NextResponse } from "next/server";
import { getCameraStatuses } from "@/app/lib/cameraStatus";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json({ cameras: await getCameraStatuses() });
}
