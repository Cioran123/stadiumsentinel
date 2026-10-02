import { NextResponse } from "next/server";
import { searchIncidents } from "@/app/lib/search";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  let query = "";
  try {
    const body = (await req.json()) as { query?: unknown };
    query = typeof body.query === "string" ? body.query.trim() : "";
  } catch {
    // fall through to validation
  }
  if (!query) return NextResponse.json({ error: "query is required" }, { status: 400 });
  if (query.length > 500) return NextResponse.json({ error: "query too long" }, { status: 400 });

  try {
    return NextResponse.json(await searchIncidents(query));
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    console.error("[/api/search]", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
