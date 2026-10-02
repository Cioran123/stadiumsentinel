import { promises as fs } from "node:fs";
import path from "node:path";
import { PIPELINE_DIR, VIDEOS_DIR, readTable } from "@/app/lib/storage";
import type { Camera, EvalSummary, Incident, TrackFrame, VenueConfig } from "@/app/lib/types";

const CONFIG_PATH = path.resolve(process.cwd(), "pipeline", "config", "cameras.json");

export async function loadVenue(): Promise<VenueConfig> {
  return JSON.parse(await fs.readFile(CONFIG_PATH, "utf8")) as VenueConfig;
}

export async function getCamera(id: string): Promise<Camera | undefined> {
  const venue = await loadVenue();
  return venue.cameras.find((c) => c.id === id);
}

export function cameraVideoPath(camera: Camera): string {
  return path.join(VIDEOS_DIR, camera.videoFile);
}

export async function fileExists(p: string): Promise<boolean> {
  try {
    return (await fs.stat(p)).isFile();
  } catch {
    return false;
  }
}

export async function listIncidents(): Promise<Incident[]> {
  const rows = await readTable<Incident>("incidents");
  return rows.sort((a, b) => a.cameraId.localeCompare(b.cameraId) || a.startSec - b.startSec);
}

export async function getIncident(id: string): Promise<Incident | undefined> {
  return (await readTable<Incident>("incidents")).find((i) => i.id === id);
}

async function readJson<T>(p: string): Promise<T | null> {
  try {
    return JSON.parse(await fs.readFile(p, "utf8")) as T;
  } catch {
    return null;
  }
}

/** Track frames from pipeline/detect.py, limited to [startSec, endSec]. */
export async function loadTracks(cameraId: string, startSec: number, endSec: number): Promise<TrackFrame[]> {
  const data = await readJson<{ frames: TrackFrame[] }>(path.join(PIPELINE_DIR, `${cameraId}.tracks.json`));
  if (!data) return [];
  return data.frames.filter((f) => f.t >= startSec && f.t <= endSec);
}

export async function loadEvalSummary(): Promise<EvalSummary | null> {
  return readJson<EvalSummary>(path.join(PIPELINE_DIR, "eval.json"));
}
