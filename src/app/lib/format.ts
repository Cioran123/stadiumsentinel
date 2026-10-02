export function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

export function formatSpan(startSec: number, endSec: number): string {
  return `${formatTime(startSec)}–${formatTime(endSec)}`;
}
