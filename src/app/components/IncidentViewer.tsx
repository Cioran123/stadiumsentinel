"use client";

import Link from "next/link";
import { useMemo, useRef, useState } from "react";
import { formatSpan, formatTime } from "@/app/lib/format";
import {
  EVENT_LABEL,
  STATUS_COLOR,
  type Camera,
  type Incident,
  type TrackFrame,
} from "@/app/lib/types";
import { PriorityBadge, SourceBadge, VerificationBadge } from "./Badges";
import EventTimeline, { type TimelineBand } from "./EventTimeline";
import TrackOverlay, { nearestFrame } from "./TrackOverlay";
import VideoPlayer, { type VideoPlayerHandle } from "./VideoPlayer";

interface Props {
  incident: Incident;
  camera: Camera;
  venueName: string;
  cameraIncidents: Incident[];
  tracks: TrackFrame[];
  syntheticTracks: boolean;
}

export default function IncidentViewer({ incident, camera, venueName, cameraIncidents, tracks, syntheticTracks }: Props) {
  const playerRef = useRef<VideoPlayerHandle>(null);
  const [time, setTime] = useState(Math.max(0, incident.startSec - 5));
  const [duration, setDuration] = useState(camera.durationSec);
  const [showOverlay, setShowOverlay] = useState(true);
  const highlight = useMemo(() => new Set(incident.trackIds ?? []), [incident.trackIds]);
  const frame = nearestFrame(tracks, time);
  const hasVerifierEvidence =
    incident.observations.length > 0 &&
    incident.observations.join("\n") !== (incident.signalNotes ?? []).join("\n");

  const bands: TimelineBand[] = [
    {
      id: "gt",
      startSec: camera.groundTruth.startSec,
      endSec: camera.groundTruth.endSec,
      color: "#e2e8f0",
      label: `Ground truth: ${EVENT_LABEL[camera.groundTruth.eventType]}`,
      row: 0,
      outlined: true,
    },
    ...cameraIncidents.map((i) => ({
      id: i.id,
      startSec: i.startSec,
      endSec: i.endSec,
      color: STATUS_COLOR[i.verificationStatus],
      label: `${EVENT_LABEL[i.eventType]} (${i.verificationStatus})`,
      row: 1 as const,
      active: i.id === incident.id,
    })),
  ];

  const jumps: [string, number][] = [
    ["−10s context", incident.startSec - 10],
    ["Start", incident.startSec],
    ["End", incident.endSec],
    ["+10s after", incident.endSec + 10],
  ];

  return (
    <div className="mx-auto grid w-full max-w-7xl gap-6 px-6 py-6 lg:grid-cols-[minmax(0,1fr)_380px]">
      <div className="flex min-w-0 flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Link href="/search" className="text-xs text-slate-500 hover:text-slate-300">← Search</Link>
          <h1 className="text-lg font-semibold text-white">{EVENT_LABEL[incident.eventType]}</h1>
          <PriorityBadge priority={incident.priority} />
          <VerificationBadge status={incident.verificationStatus} />
          <SourceBadge sourceType={incident.sourceType} />
        </div>
        <p className="font-mono text-xs text-slate-400">
          {camera.id} · {camera.zone} · {formatSpan(incident.startSec, incident.endSec)}
        </p>

        {incident.requiresHumanReview && (
          <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-2.5 text-sm text-amber-200">
            Human review recommended. This is an observable-signal match, not a determination of intent,
            identity, or medical condition.
          </div>
        )}

        <VideoPlayer
          ref={playerRef}
          src={`/api/cameras/${camera.id}/video`}
          initialTime={Math.max(0, incident.startSec - 5)}
          onTimeChange={setTime}
          onDurationChange={setDuration}
          overlay={showOverlay ? <TrackOverlay camera={camera} frame={frame} highlight={highlight} /> : null}
        />

        <div className="flex flex-wrap items-center gap-2">
          {jumps.map(([label, t]) => (
            <button
              key={label}
              type="button"
              onClick={() => playerRef.current?.seekTo(Math.max(0, t))}
              className="rounded-lg border border-white/10 px-3 py-1.5 text-[11px] text-slate-300 hover:border-white/30"
            >
              {label} ({formatTime(Math.max(0, t))})
            </button>
          ))}
          <label className="ml-auto flex items-center gap-1.5 text-[11px] text-slate-400">
            <input type="checkbox" checked={showOverlay} onChange={(e) => setShowOverlay(e.target.checked)} />
            YOLO tracks + pose + flow{camera.restrictedPolygons?.length ? " + restricted polygon" : ""}
            {syntheticTracks ? " (synthetic seed tracks)" : ""}
          </label>
        </div>

        <EventTimeline
          bands={bands}
          currentTime={time}
          duration={duration}
          onSeek={(s) => playerRef.current?.seekTo(s)}
          onSelect={(id) => {
            if (id !== incident.id) window.location.href = `/incident/${id}`;
          }}
        />
      </div>

      <aside className="flex flex-col gap-4">
        <section className="rounded-xl border border-white/10 bg-[#0c0c12] p-4">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">Verifier result</h2>
          <div className="mb-2 flex items-center gap-2">
            <VerificationBadge status={incident.verificationStatus} />
          </div>
          <p className="text-sm text-slate-200">{incident.cosmosExplanation ?? "No explanation recorded."}</p>
          <p className="mt-2 text-[11px] text-slate-500">
            {incident.verifier ?? "unverified"} · prompt {incident.promptVersion ?? "—"}
          </p>
          <h3 className="mb-1 mt-4 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Observable evidence</h3>
          {hasVerifierEvidence ? (
            <ul className="list-disc space-y-1 pl-4 text-[13px] text-slate-300">
              {incident.observations.map((o) => (
                <li key={o}>{o}</li>
              ))}
            </ul>
          ) : (
            <p className="text-[12px] text-slate-500">No verifier evidence yet; see the candidate signals below.</p>
          )}
        </section>

        <section className="rounded-xl border border-white/10 bg-[#0c0c12] p-4">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">Candidate signals (YOLO)</h2>
          <ul className="list-disc space-y-1 pl-4 text-[13px] text-slate-300">
            {(incident.signalNotes ?? []).map((o) => (
              <li key={o}>{o}</li>
            ))}
          </ul>
          {incident.signals && Object.keys(incident.signals).length > 0 && (
            <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 font-mono text-[11px]">
              {Object.entries(incident.signals).map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="text-slate-500">{k}</dt>
                  <dd className="text-right text-slate-300">{v}</dd>
                </div>
              ))}
            </dl>
          )}
        </section>

        {incident.evidenceClipUrl && (
          <section className="rounded-xl border border-white/10 bg-[#0c0c12] p-4">
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">Clip sent to verifier</h2>
            <video src={incident.evidenceClipUrl} controls muted preload="metadata" className="w-full rounded-lg" />
          </section>
        )}

        <section className="rounded-xl border border-white/10 bg-[#0c0c12] p-4">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">Source</h2>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px]">
            <dt className="text-slate-500">Venue</dt><dd className="text-slate-300">{venueName}</dd>
            <dt className="text-slate-500">Camera</dt><dd className="text-slate-300">{camera.id} · {camera.zone}</dd>
            <dt className="text-slate-500">File</dt><dd className="font-mono text-slate-300">{incident.videoId}</dd>
            <dt className="text-slate-500">Span</dt><dd className="font-mono text-slate-300">{formatSpan(incident.startSec, incident.endSec)}</dd>
            <dt className="text-slate-500">Source</dt><dd className="text-slate-300">{incident.sourceType}</dd>
            <dt className="text-slate-500">Scenario</dt><dd className="text-slate-300">{camera.scenario}</dd>
            <dt className="text-slate-500">Tracks</dt><dd className="font-mono text-slate-300">{incident.trackIds?.length ? incident.trackIds.map((t) => `#${t}`).join(", ") : "—"}</dd>
          </dl>
        </section>
      </aside>
    </div>
  );
}
