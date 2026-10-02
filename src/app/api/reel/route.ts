import { NextResponse } from "next/server";
import { buildReel, listReels } from "@/app/lib/reel";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json({ reels: await listReels() });
}

export async function POST(req: Request) {
  let query: string | undefined;
  try {
    const body = (await req.json()) as { query?: unknown };
    if (typeof body.query === "string" && body.query.trim()) query = body.query.trim().slice(0, 500);
  } catch {
    // empty body: reel of every kept incident
  }
  try {
    return NextResponse.json(await buildReel(query));
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    console.error("[/api/reel]", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
