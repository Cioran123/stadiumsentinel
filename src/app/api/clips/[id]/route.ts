import path from "node:path";
import { NextResponse } from "next/server";
import { CLIPS_DIR } from "@/app/lib/storage";
import { streamVideo } from "@/app/lib/videoStream";

export const runtime = "nodejs";

export async function GET(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (!/^[\w-]+$/.test(id)) return NextResponse.json({ error: "Bad clip id" }, { status: 400 });
  return streamVideo(req, path.join(CLIPS_DIR, `${id}.mp4`));
}
