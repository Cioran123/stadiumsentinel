import { execFile } from "node:child_process";
import { existsSync, promises as fs } from "node:fs";
import path from "node:path";
import { promisify } from "node:util";
import { concatClips, cutClip } from "@/app/lib/ffmpeg";
import { formatSpan } from "@/app/lib/format";
import { searchIncidents } from "@/app/lib/search";
import { REELS_DIR, STORAGE_ROOT, insert, readTable } from "@/app/lib/storage";
import { EVENT_LABEL, type Incident } from "@/app/lib/types";
import { cameraVideoPath, listIncidents, loadVenue } from "@/app/lib/venue";

const execFileAsync = promisify(execFile);

export interface ReelSegment {
  incidentId: string;
  cameraId: string;
  zone: string;
  eventType: Incident["eventType"];
  startSec: number;
  endSec: number;
  /** Where this segment starts inside the reel. */
  reelOffsetSec: number;
  reason: string;
}

export interface Reel {
  id: string;
  createdAt: string;
  query?: string;
  segments: ReelSegment[];
  durationSec: number;
  videoUrl?: string;
  labeled: boolean;
  message?: string;
}

function pythonBin(): string {
  if (process.env.SENTINEL_PYTHON) return process.env.SENTINEL_PYTHON;
  const venv = path.resolve(process.cwd(), ".venv", "bin", "python");
  return existsSync(venv) ? venv : "python3";
}

function inclusionReason(i: Incident): string {
  const why = i.cosmosExplanation || i.observations[0] || "verifier kept this span";
  return `Kept by ${i.verifier ?? "verifier"}: ${why}`;
}

async function renderLabel(i: Incident, out: string): Promise<boolean> {
  const lines = [
    `${i.cameraId} | ${i.zone.toUpperCase()} | ${formatSpan(i.startSec, i.endSec)}`,
    `${EVENT_LABEL[i.eventType]} (${i.priority} priority) - review recommended`,
    inclusionReason(i).slice(0, 110),
  ];
  try {
    await execFileAsync(pythonBin(), [path.resolve(process.cwd(), "pipeline", "label_card.py"), out, ...lines]);
    return true;
  } catch (err) {
    console.warn("[reel] label render failed; cutting without lower third:", err instanceof Error ? err.message : err);
    return false;
  }
}

/** Build a reel from verifier-kept incidents only, optionally narrowed by a search query. */
export async function buildReel(query?: string): Promise<Reel> {
  const id = `reel-${new Date().toISOString().replace(/[-:T.Z]/g, "").slice(0, 14)}`;
  const createdAt = new Date().toISOString();
  const pool = query?.trim() ? (await searchIncidents(query)).results : await listIncidents();
  const kept = pool
    .filter((i) => i.verificationStatus === "kept")
    .sort((a, b) => a.cameraId.localeCompare(b.cameraId) || a.startSec - b.startSec);

  if (kept.length === 0) {
    return {
      id,
      createdAt,
      query,
      segments: [],
      durationSec: 0,
      labeled: false,
      message: "No verified (kept) incidents match, so no reel was created. Unverified candidates are never included.",
    };
  }

  const venue = await loadVenue();
  const work = path.join(STORAGE_ROOT, "tmp", id);
  await fs.mkdir(work, { recursive: true });
  const segments: ReelSegment[] = [];
  const clips: string[] = [];
  let offset = 0;
  let labeled = true;

  try {
    for (const [n, inc] of kept.entries()) {
      const camera = venue.cameras.find((c) => c.id === inc.cameraId);
      if (!camera) continue;
      const label = path.join(work, `label-${n}.png`);
      const hasLabel = await renderLabel(inc, label);
      labeled &&= hasLabel;
      const clip = path.join(work, `seg-${n}.mp4`);
      await cutClip(cameraVideoPath(camera), inc.startSec, inc.endSec, clip, hasLabel ? label : undefined);
      clips.push(clip);
      segments.push({
        incidentId: inc.id,
        cameraId: inc.cameraId,
        zone: inc.zone,
        eventType: inc.eventType,
        startSec: inc.startSec,
        endSec: inc.endSec,
        reelOffsetSec: +offset.toFixed(2),
        reason: inclusionReason(inc),
      });
      offset += inc.endSec - inc.startSec;
    }
    await concatClips(clips, path.join(REELS_DIR, `${id}.mp4`));
  } finally {
    await fs.rm(work, { recursive: true, force: true });
  }

  const reel: Reel = {
    id,
    createdAt,
    query,
    segments,
    durationSec: +offset.toFixed(2),
    videoUrl: `/api/reels/${id}/video`,
    labeled,
  };
  await insert<Reel>("reels", reel);
  return reel;
}

export async function listReels(): Promise<Reel[]> {
  return (await readTable<Reel>("reels")).sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}
