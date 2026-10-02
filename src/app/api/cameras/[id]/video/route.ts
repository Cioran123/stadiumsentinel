import { NextResponse } from "next/server";
import { cameraVideoPath, getCamera } from "@/app/lib/venue";
import { streamVideo } from "@/app/lib/videoStream";

export const runtime = "nodejs";

export async function GET(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const camera = await getCamera(id);
  if (!camera) return NextResponse.json({ error: "Camera not found" }, { status: 404 });
  return streamVideo(req, cameraVideoPath(camera));
}
