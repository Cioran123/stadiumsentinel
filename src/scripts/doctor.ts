/**
 * Demo readiness check.
 *
 * Verifies the things that are easy to forget right before a hackathon
 * demo: ffmpeg/ffprobe on PATH, the camera corpus, the prepared incident
 * ledger, storage directories, and optional sponsor credentials. Prints a green check or red X per item
 * and exits with code 1 if any check fails.
 *
 * Run with: npm run doctor (uses tsx to execute this TypeScript file).
 */

import { execFile } from "node:child_process";
import { promises as fs } from "node:fs";
import path from "node:path";
import { promisify } from "node:util";

const execFileP = promisify(execFile);

const GREEN = "\x1b[32m";
const RED = "\x1b[31m";
const DIM = "\x1b[2m";
const RESET = "\x1b[0m";

interface CheckResult {
  label: string;
  ok: boolean;
  detail?: string;
}

function pass(label: string, detail?: string): CheckResult {
  return { label, ok: true, detail };
}

function fail(label: string, detail?: string): CheckResult {
  return { label, ok: false, detail };
}

async function loadEnvFile(file: string): Promise<void> {
  try {
    const raw = await fs.readFile(file, "utf8");
    for (const line of raw.split(/\r?\n/)) {
      const m = /^\s*(?:export\s+)?([A-Z0-9_]+)\s*=\s*(.*)\s*$/.exec(line);
      if (!m || m[0].trimStart().startsWith("#")) continue;
      const [, key, valueRaw] = m;
      if (process.env[key] !== undefined) continue;
      process.env[key] = valueRaw.replace(/^['"]|['"]$/g, "");
    }
  } catch {
    // file may not exist; that's fine
  }
}

async function loadEnv(): Promise<void> {
  // Best-effort: load .env.local and the Builders Challenge team file so
  // people who only set keys there don't get a false negative.
  const root = process.cwd();
  await loadEnvFile(path.join(root, ".env.local"));
  await loadEnvFile(path.join(root, ".env"));
  if (process.env.BUILDERS_CONFIG) await loadEnvFile(process.env.BUILDERS_CONFIG);
  try {
    const configs = (await fs.readdir("/config")).filter((name) => name.endsWith(".config"));
    if (configs.length === 1) await loadEnvFile(path.join("/config", configs[0]));
  } catch {
    // /config exists only on the workshop VM
  }
}

async function checkEnv(name: string): Promise<CheckResult> {
  await loadEnv();

  const value = process.env[name];
  if (!value || value.trim().length === 0) {
    return fail(`${name} is set`, "missing or empty");
  }
  return pass(`${name} is set`, `${value.length} chars`);
}

async function checkBinary(bin: string): Promise<CheckResult> {
  try {
    const { stdout } = await execFileP(bin, ["-version"]);
    const firstLine = stdout.split(/\r?\n/)[0]?.trim();
    return pass(`${bin} on PATH`, firstLine);
  } catch (err) {
    return fail(`${bin} on PATH`, err instanceof Error ? err.message : String(err));
  }
}

async function checkFile(label: string, p: string): Promise<CheckResult> {
  try {
    const stat = await fs.stat(p);
    if (!stat.isFile()) return fail(label, `${p} is not a file`);
    return pass(label, `${(stat.size / 1024 / 1024).toFixed(2)} MB`);
  } catch {
    return fail(label, `not found at ${p}`);
  }
}

async function checkDir(label: string, p: string): Promise<CheckResult> {
  try {
    const stat = await fs.stat(p);
    if (!stat.isDirectory()) return fail(label, `${p} exists but is not a directory`);
    return pass(label, p);
  } catch {
    // Try to create it; missing storage dirs are fine to create on demand.
    try {
      await fs.mkdir(p, { recursive: true });
      return pass(label, `${p} (created)`);
    } catch (err) {
      return fail(label, `could not create ${p}: ${err instanceof Error ? err.message : String(err)}`);
    }
  }
}

function render(results: CheckResult[]): boolean {
  console.log("");
  console.log("Demo readiness check");
  console.log("--------------------");
  let allOk = true;
  for (const r of results) {
    if (!r.ok) allOk = false;
    const mark = r.ok ? `${GREEN}✓${RESET}` : `${RED}✗${RESET}`;
    const detail = r.detail ? ` ${DIM}— ${r.detail}${RESET}` : "";
    console.log(`  ${mark} ${r.label}${detail}`);
  }
  console.log("");
  console.log(
    allOk
      ? `${GREEN}All checks passed. You're good to go.${RESET}`
      : `${RED}One or more checks failed. Fix the items above before demoing.${RESET}`,
  );
  console.log("");
  return allOk;
}

async function checkOptionalAny(names: string[], label: string, fallback: string): Promise<CheckResult> {
  await loadEnv();
  const hit = names.find((name) => process.env[name]?.trim());
  if (hit) return pass(label, hit);
  return pass(`${label} not set`, `using fallback: ${fallback}`);
}

/** Sponsor credentials are optional: each adapter falls back to a local stand-in. */
async function checkOptionalEnv(name: string, fallback: string): Promise<CheckResult> {
  const result = await checkEnv(name);
  if (result.ok) return result;
  return pass(`${name} not set`, `using fallback: ${fallback}`);
}

async function main(): Promise<void> {
  const root = process.cwd();
  const configPath = path.join(root, "pipeline", "config", "cameras.json");

  const results: CheckResult[] = [];
  results.push(await checkBinary("ffmpeg"));
  results.push(await checkBinary("ffprobe"));
  results.push(await checkFile("pipeline/config/cameras.json exists", configPath));

  try {
    const config = JSON.parse(await fs.readFile(configPath, "utf8")) as {
      cameras: { id: string; videoFile: string }[];
    };
    for (const cam of config.cameras) {
      results.push(
        await checkFile(`${cam.id} video`, path.join(root, "storage", "videos", cam.videoFile)),
      );
    }
  } catch {
    // reported by the cameras.json check above
  }

  results.push(
    await checkFile(
      "storage/db/incidents.json exists (run pipeline/run_all.py)",
      path.join(root, "storage", "db", "incidents.json"),
    ),
  );
  results.push(await checkDir("storage/db directory", path.join(root, "storage", "db")));
  results.push(await checkDir("storage/reels directory", path.join(root, "storage", "reels")));
  results.push(await checkOptionalEnv("ANTHROPIC_API_KEY", "keyword search parsing"));
  results.push(await checkOptionalEnv("WANDB_API_KEY", "no Weave tracing"));
  results.push(await checkOptionalAny(
    ["NVIDIA_API_KEY", "GPU_BEARER_TOKEN", "COSMOS3_REASON_URL", "COSMOS_BASE_URL"],
    "Cosmos Reason configured",
    "verifier stays on Claude or unverified candidates",
  ));
  results.push(await checkOptionalAny(
    ["VAST_S3_ENDPOINT", "S3_ENDPOINT"],
    "VAST endpoint configured",
    "search stays on the local ledger",
  ));

  const ok = render(results);
  process.exit(ok ? 0 : 1);
}

main().catch((err) => {
  console.error(`${RED}doctor crashed:${RESET}`, err);
  process.exit(1);
});
