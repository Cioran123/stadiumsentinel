"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { fetchWithToast } from "@/app/lib/fetchWithToast";
import { formatSpan, formatTime } from "@/app/lib/format";
import type { Reel } from "@/app/lib/reel";
import { EVENT_LABEL } from "@/app/lib/types";

export default function ReelView({ initialReels, keptCount }: { initialReels: Reel[]; keptCount: number }) {
  const [reels, setReels] = useState(initialReels);
  const [current, setCurrent] = useState<Reel | null>(initialReels[0] ?? null);
  const [query, setQuery] = useState("");
  const [building, setBuilding] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);

  async function build() {
    setBuilding(true);
    try {
      const res = await fetchWithToast("/api/reel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      }, { errorMessage: "Reel build failed" });
      if (!res.ok) return;
      const reel = (await res.json()) as Reel;
      setCurrent(reel);
      if (reel.videoUrl) setReels((r) => [reel, ...r]);
    } catch {
      // toast already shown
    } finally {
      setBuilding(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-6xl px-6 py-6">
      <div className="mb-4">
        <h1 className="text-lg font-semibold text-white">Review reel</h1>
        <p className="text-sm text-slate-400">
          Assembled only from verifier-kept spans ({keptCount} available). Each segment carries its camera, zone,
          source timestamp, event type, and inclusion reason.
        </p>
      </div>
      <form
        className="mb-6 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void build();
        }}
      >
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Optional filter, e.g. “restricted-zone entries” (blank = all kept incidents)"
          className="flex-1 rounded-xl border border-white/10 bg-[#0c0c12] px-4 py-3 text-sm text-white placeholder:text-slate-600 focus:border-white/30 focus:outline-none"
        />
        <button
          type="submit"
          disabled={building}
          className="rounded-xl bg-white/10 px-5 text-sm font-medium text-white hover:bg-white/20 disabled:opacity-50"
        >
          {building ? "Building…" : "Create reel"}
        </button>
      </form>

      {current?.message && (
        <div className="mb-4 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3 text-sm text-slate-300">
          {current.message}
        </div>
      )}

      {current?.videoUrl && (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
          <div>
            <video
              ref={videoRef}
              key={current.id}
              src={current.videoUrl}
              controls
              muted
              className="aspect-video w-full rounded-xl border border-white/10 bg-black"
            />
            <p className="mt-2 text-[11px] text-slate-500">
              {current.id} · {formatTime(current.durationSec)} · {current.segments.length} segments
              {current.query ? ` · filter “${current.query}”` : ""}
              {current.labeled ? "" : " · lower-third labels unavailable (python/OpenCV not found)"}
            </p>
          </div>
          <ol className="flex flex-col gap-2">
            {current.segments.map((s, n) => (
              <li key={s.incidentId} className="rounded-xl border border-white/10 bg-[#0c0c12] p-3">
                <button
                  type="button"
                  onClick={() => {
                    const v = videoRef.current;
                    if (v) v.currentTime = s.reelOffsetSec;
                  }}
                  className="text-left"
                >
                  <div className="text-xs font-semibold text-white">
                    {n + 1}. {EVENT_LABEL[s.eventType]}
                  </div>
                  <div className="font-mono text-[11px] text-slate-400">
                    {s.cameraId} · {s.zone} · source {formatSpan(s.startSec, s.endSec)} · reel @{formatTime(s.reelOffsetSec)}
                  </div>
                </button>
                <p className="mt-1 text-[12px] text-slate-300">{s.reason}</p>
                <Link href={`/incident/${s.incidentId}`} className="mt-1 inline-block text-[11px] text-sky-400 hover:text-sky-300">
                  Open source at {formatTime(s.startSec)} →
                </Link>
              </li>
            ))}
          </ol>
        </div>
      )}

      {reels.length > 1 && (
        <div className="mt-8">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Previous reels</h2>
          <div className="flex flex-wrap gap-2">
            {reels.map((r) => (
              <button
                key={r.id}
                type="button"
                onClick={() => setCurrent(r)}
                className="rounded-lg border border-white/10 px-3 py-1.5 text-[11px] text-slate-300 hover:border-white/30"
              >
                {new Date(r.createdAt).toLocaleTimeString()} · {r.segments.length} seg{r.query ? ` · ${r.query}` : ""}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
