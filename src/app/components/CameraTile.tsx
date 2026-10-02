"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { CameraStatus, IndexStatus } from "@/app/lib/cameraStatus";
import { formatSpan } from "@/app/lib/format";
import { EVENT_LABEL, PRIORITY_COLOR, type CameraTracks, type Incident } from "@/app/lib/types";
import { SourceBadge, VerificationBadge } from "./Badges";
import TrackOverlay, { nearestFrame } from "./TrackOverlay";

const INDEX_LABEL: Record<IndexStatus, { text: string; color: string }> = {
  missing_video: { text: "Awaiting footage", color: "#94a3b8" },
  not_indexed: { text: "Not indexed", color: "#94a3b8" },
  tracked: { text: "Tracked, no incidents", color: "#60a5fa" },
  indexed: { text: "Indexed", color: "#22c55e" },
};

interface Props {
  status: CameraStatus;
  showOverlay: boolean;
  /** Incidents whose span contains the current playback time. */
  active: Incident[];
  onTime: (cameraId: string, t: number) => void;
}

export default function CameraTile({ status, showOverlay, active, onTime }: Props) {
  const { camera, indexStatus, latest, incidentCount, keptCount } = status;
  const idx = INDEX_LABEL[indexStatus];
  const [tracks, setTracks] = useState<CameraTracks | null>(null);
  const [time, setTime] = useState(0);
  const hasVideo = indexStatus !== "missing_video";

  useEffect(() => {
    if (!hasVideo) return;
    let cancelled = false;
    fetch(`/api/cameras/${camera.id}/tracks`)
      .then((r) => (r.ok ? (r.json() as Promise<CameraTracks>) : null))
      .then((t) => {
        if (!cancelled) setTracks(t);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [camera.id, hasVideo]);

  const frame = tracks ? nearestFrame(tracks.frames, time) : null;
  const top = active[0];
  const pulseColor = top ? PRIORITY_COLOR[top.priority] : undefined;

  return (
    <div
      className={`flex flex-col overflow-hidden rounded-xl border bg-[#0c0c12] ${top ? "tile-alert" : "border-white/10"}`}
      style={pulseColor ? ({ "--pulse": pulseColor } as React.CSSProperties) : undefined}
    >
      <div className="relative aspect-video bg-black">
        {!hasVideo ? (
          <div className="flex h-full flex-col items-center justify-center gap-1 px-4 text-center text-xs text-slate-500">
            <span className="text-sm text-slate-400">Awaiting footage</span>
            <span>Add shots to footage/{camera.id}/ and run pipeline/assemble.py</span>
          </div>
        ) : (
          <>
            <video
              src={`/api/cameras/${camera.id}/video`}
              className="h-full w-full object-cover"
              autoPlay
              muted
              loop
              playsInline
              preload="auto"
              onTimeUpdate={(e) => {
                const t = e.currentTarget.currentTime;
                setTime(t);
                onTime(camera.id, t);
              }}
            />
            {showOverlay && frame && (
              <div className="pointer-events-none absolute inset-0">
                <TrackOverlay camera={camera} frame={frame} showIds />
              </div>
            )}
          </>
        )}
        <div className="absolute bottom-2 left-2 rounded bg-black/70 px-2 py-0.5 font-mono text-[11px] text-white">
          {camera.id} · {camera.zone.toUpperCase()}
          {frame ? ` · ${frame.boxes.length} people visible` : ""}
        </div>
        <div className="absolute right-2 top-2">
          <SourceBadge sourceType={camera.sourceType} />
        </div>
        {top && (
          <div
            className="absolute left-2 top-2 rounded px-2 py-0.5 text-[11px] font-semibold text-white"
            style={{ background: `${pulseColor}cc` }}
          >
            ● {EVENT_LABEL[top.eventType]} · review
          </div>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-2 p-3">
        <div className="flex items-center justify-between text-[11px]">
          <span className="flex items-center gap-1.5" style={{ color: idx.color }}>
            <span className="h-1.5 w-1.5 rounded-full" style={{ background: idx.color }} />
            {idx.text}
          </span>
          {hasVideo && (
            <span className="text-slate-500">
              {incidentCount} candidate{incidentCount === 1 ? "" : "s"} · {keptCount} kept
            </span>
          )}
        </div>
        {latest ? (
          <Link
            href={`/incident/${latest.id}`}
            className="rounded-lg border border-white/5 bg-white/[0.03] p-2 transition-colors hover:border-white/20"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-xs font-medium text-slate-200">{EVENT_LABEL[latest.eventType]}</span>
              <span className="font-mono text-[11px] text-slate-500">{formatSpan(latest.startSec, latest.endSec)}</span>
            </div>
            <div className="mt-1.5">
              <VerificationBadge status={latest.verificationStatus} />
            </div>
          </Link>
        ) : (
          <p className="text-xs text-slate-600">{hasVideo ? "No candidate or verified incident." : camera.scenario}</p>
        )}
      </div>
    </div>
  );
}
