import { promises as fs } from "node:fs";
import path from "node:path";
import { NextResponse } from "next/server";
import { PIPELINE_DIR } from "@/app/lib/storage";
import type { CameraTracks } from "@/app/lib/types";
import { getCamera } from "@/app/lib/venue";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (!(await getCamera(id))) return NextResponse.json({ error: "Camera not found" }, { status: 404 });
  try {
    const raw = JSON.parse(await fs.readFile(path.join(PIPELINE_DIR, `${id}.tracks.json`), "utf8")) as CameraTracks;
    const body: CameraTracks = {
      cameraId: raw.cameraId,
      fps: raw.fps,
      roi: raw.roi,
      synthetic: raw.synthetic,
      frames: raw.frames.map((f) => ({ t: f.t, boxes: f.boxes.map(({ id: tid, box, kp }) => ({ id: tid, box, kp })), flow: f.flow ?? null })),
    };
    return NextResponse.json(body);
  } catch {
    return NextResponse.json({ error: "No tracks for this camera; run pipeline/detect.py" }, { status: 404 });
  }
}
