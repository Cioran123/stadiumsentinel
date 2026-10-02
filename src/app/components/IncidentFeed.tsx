"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { formatSpan } from "@/app/lib/format";
import { EVENT_LABEL, PRIORITY_COLOR, type Incident } from "@/app/lib/types";
import { PriorityBadge, VerificationBadge } from "./Badges";

export interface FeedItem {
  incident: Incident;
  /** Wall-clock time the incident popped into the feed. */
  seenAt: number;
}

function Since({ at }: { at: number }) {
  const [now, setNow] = useState(at);
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 15_000);
    return () => clearInterval(id);
  }, []);
  const mins = Math.max(0, Math.floor((now - at) / 60_000));
  return (
    <div className="flex-shrink-0 text-right">
      <div className="text-[9px] uppercase tracking-widest text-slate-500">Waiting</div>
      <div className="text-sm font-bold text-slate-300">{mins}m</div>
    </div>
  );
}

function FeedCard({ item, onDismiss }: { item: FeedItem; onDismiss: (id: string) => void }) {
  const i = item.incident;
  const color = PRIORITY_COLOR[i.priority];
  const notes = (i.observations.length ? i.observations : i.signalNotes ?? []).slice(0, 3);
  return (
    <div
      className="feed-pop flex flex-col gap-2 rounded-2xl p-3.5"
      style={{ background: `${color}0d`, border: `1px solid ${color}55`, borderLeft: `3px solid ${color}` }}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="rounded-md bg-black/40 px-1.5 py-0.5 font-mono text-[10px] text-slate-200">{i.cameraId}</span>
        <PriorityBadge priority={i.priority} />
        <VerificationBadge status={i.verificationStatus} />
      </div>
      <div>
        <p className="text-[13px] font-semibold text-white">{EVENT_LABEL[i.eventType]}</p>
        <p className="font-mono text-[11px] text-slate-400">
          {i.zone} · {formatSpan(i.startSec, i.endSec)}
        </p>
      </div>
      {notes.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-4 text-[12px] text-slate-300">
          {notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
      <div className="flex items-end justify-between">
        <div className="flex gap-2">
          <Link
            href={`/incident/${i.id}`}
            className="rounded-lg border border-slate-600 px-3 py-1.5 text-[11px] text-slate-200 transition-colors hover:border-slate-400 hover:text-white"
          >
            Review
          </Link>
          <button
            type="button"
            onClick={() => onDismiss(i.id)}
            className="rounded-lg border border-slate-700 px-3 py-1.5 text-[11px] text-slate-400 transition-colors hover:border-slate-500 hover:text-white"
          >
            Mark reviewed
          </button>
        </div>
        <Since at={item.seenAt} />
      </div>
    </div>
  );
}

interface Props {
  items: FeedItem[];
  onDismiss: (id: string) => void;
  onReset: () => void;
}

export default function IncidentFeed({ items, onDismiss, onReset }: Props) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-400">Incident feed</h2>
        <button type="button" onClick={onReset} className="text-[11px] text-slate-500 hover:text-slate-300">
          Replay
        </button>
      </div>
      {items.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 py-24 text-center text-slate-600">
          <span className="text-sm">No incidents yet.</span>
          <span className="text-xs">Candidates appear here as playback reaches them.</span>
        </div>
      ) : (
        items.map((item) => <FeedCard key={item.incident.id} item={item} onDismiss={onDismiss} />)
      )}
    </div>
  );
}
