import { promises as fs } from "node:fs";
import path from "node:path";

export const STORAGE_ROOT = path.resolve(process.cwd(), "storage");
/** Assembled two-minute camera recordings, named per `videoFile` in pipeline/config/cameras.json. */
export const VIDEOS_DIR = path.join(STORAGE_ROOT, "videos");
/** Short candidate clips cut by pipeline/verify.py, named `<incidentId>.mp4`. */
export const CLIPS_DIR = path.join(STORAGE_ROOT, "clips");
export const REELS_DIR = path.join(STORAGE_ROOT, "reels");
/** Pipeline intermediates: `<cameraId>.tracks.json`, `eval.json`. */
export const PIPELINE_DIR = path.join(STORAGE_ROOT, "pipeline");
export const DB_DIR = path.join(STORAGE_ROOT, "db");

const REQUIRED_DIRS = [STORAGE_ROOT, VIDEOS_DIR, CLIPS_DIR, REELS_DIR, PIPELINE_DIR, DB_DIR];

async function ensureDirs(): Promise<void> {
  await Promise.all(REQUIRED_DIRS.map((dir) => fs.mkdir(dir, { recursive: true })));
}

const initPromise = ensureDirs().catch((err) => {
  console.error("[storage] failed to init storage dirs", err);
});

class Mutex {
  private chain: Promise<void> = Promise.resolve();
  async run<T>(fn: () => Promise<T>): Promise<T> {
    let release!: () => void;
    const next = new Promise<void>((resolve) => {
      release = resolve;
    });
    const prev = this.chain;
    this.chain = prev.then(() => next);
    await prev;
    try {
      return await fn();
    } finally {
      release();
    }
  }
}

const mutex = new Mutex();

export type TableName = "incidents" | "reels";

function tablePath(name: TableName): string {
  return path.join(DB_DIR, `${name}.json`);
}

async function readRaw<T>(name: TableName): Promise<T[]> {
  const file = tablePath(name);
  try {
    const data = await fs.readFile(file, "utf8");
    if (!data.trim()) return [];
    return JSON.parse(data) as T[];
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw err;
  }
}

async function writeRaw<T>(name: TableName, rows: T[]): Promise<void> {
  const file = tablePath(name);
  const tmp = `${file}.tmp`;
  await fs.writeFile(tmp, JSON.stringify(rows, null, 2), "utf8");
  await fs.rename(tmp, file);
}

export async function readTable<T>(name: TableName): Promise<T[]> {
  await initPromise;
  return mutex.run(() => readRaw<T>(name));
}

export async function writeTable<T>(name: TableName, rows: T[]): Promise<void> {
  await initPromise;
  await mutex.run(() => writeRaw<T>(name, rows));
}

export async function insert<T extends { id: string }>(name: TableName, row: T): Promise<T> {
  await initPromise;
  return mutex.run(async () => {
    const rows = await readRaw<T>(name);
    rows.push(row);
    await writeRaw(name, rows);
    return row;
  });
}

export async function update<T extends { id: string }>(
  name: TableName,
  id: string,
  patch: Partial<T>,
): Promise<T> {
  await initPromise;
  return mutex.run(async () => {
    const rows = await readRaw<T>(name);
    const idx = rows.findIndex((r) => r.id === id);
    if (idx === -1) throw new Error(`[storage] ${name} row not found: ${id}`);
    const next = { ...rows[idx], ...patch } as T;
    rows[idx] = next;
    await writeRaw(name, rows);
    return next;
  });
}

export async function remove(name: TableName, id: string): Promise<void> {
  await initPromise;
  await mutex.run(async () => {
    const rows = await readRaw<{ id: string }>(name);
    const next = rows.filter((r) => r.id !== id);
    await writeRaw(name, next);
  });
}
