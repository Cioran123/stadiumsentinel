import { execFile } from "node:child_process";
import { promises as fs } from "node:fs";
import path from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

async function ensureBinary(bin: "ffmpeg" | "ffprobe"): Promise<void> {
  try {
    await execFileAsync(bin, ["-version"]);
  } catch {
    throw new Error(
      `${bin} not found on PATH. Install it (e.g. \`brew install ffmpeg\`) and retry.`,
    );
  }
}

export async function getDuration(videoPath: string): Promise<number> {
  await ensureBinary("ffprobe");
  const { stdout } = await execFileAsync("ffprobe", [
    "-v",
    "error",
    "-show_entries",
    "format=duration",
    "-of",
    "default=noprint_wrappers=1:nokey=1",
    videoPath,
  ]);
  const seconds = parseFloat(stdout.trim());
  if (!Number.isFinite(seconds)) {
    throw new Error(`ffprobe could not parse duration for ${videoPath}`);
  }
  return seconds;
}

export async function extractFrames(
  videoPath: string,
  outDir: string,
  fps: number,
): Promise<string[]> {
  await ensureBinary("ffmpeg");
  await fs.mkdir(outDir, { recursive: true });
  const pattern = path.join(outDir, "frame-%05d.jpg");
  await execFileAsync("ffmpeg", [
    "-y",
    "-i",
    videoPath,
    "-vf",
    `fps=${fps}`,
    "-q:v",
    "3",
    pattern,
  ]);
  const entries = await fs.readdir(outDir);
  return entries
    .filter((f) => /^frame-\d{5}\.jpg$/.test(f))
    .sort()
    .map((f) => path.join(outDir, f));
}

/**
 * Re-encode [startSec, endSec] of `src` to 1280x720 @ 30fps. When `labelPng` is given it is
 * composited along the bottom edge (a lower third).
 */
export async function cutClip(
  src: string,
  startSec: number,
  endSec: number,
  out: string,
  labelPng?: string,
): Promise<void> {
  await ensureBinary("ffmpeg");
  await fs.mkdir(path.dirname(out), { recursive: true });
  const norm = "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30";
  const args = ["-y", "-ss", startSec.toFixed(2), "-i", src];
  if (labelPng) args.push("-i", labelPng);
  args.push("-t", Math.max(0.5, endSec - startSec).toFixed(2));
  if (labelPng) {
    args.push("-filter_complex", `[0:v]${norm}[v];[v][1:v]overlay=0:H-h[out]`, "-map", "[out]");
  } else {
    args.push("-vf", norm);
  }
  args.push("-an", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", out);
  await execFileAsync("ffmpeg", args);
}

/** Concatenate clips that share codec settings (as produced by `cutClip`) without re-encoding. */
export async function concatClips(clips: string[], out: string): Promise<void> {
  await ensureBinary("ffmpeg");
  await fs.mkdir(path.dirname(out), { recursive: true });
  const listFile = `${out}.txt`;
  await fs.writeFile(listFile, clips.map((c) => `file '${c.replace(/'/g, "'\\''")}'`).join("\n"));
  try {
    await execFileAsync("ffmpeg", [
      "-y", "-f", "concat", "-safe", "0", "-i", listFile, "-c", "copy", "-movflags", "+faststart", out,
    ]);
  } finally {
    await fs.rm(listFile, { force: true });
  }
}

export async function extractThumbnail(
  videoPath: string,
  outPath: string,
  atSeconds = 1,
): Promise<void> {
  await ensureBinary("ffmpeg");
  await fs.mkdir(path.dirname(outPath), { recursive: true });
  await execFileAsync("ffmpeg", [
    "-y",
    "-ss",
    String(atSeconds),
    "-i",
    videoPath,
    "-frames:v",
    "1",
    "-q:v",
    "3",
    outPath,
  ]);
}
