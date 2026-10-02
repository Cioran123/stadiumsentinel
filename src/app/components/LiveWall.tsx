"use client";

import { useCallback, useRef, useState } from "react";
import type { CameraStatus } from "@/app/lib/cameraStatus";
import type { Incident } from "@/app/lib/types";
import CameraTile from "./CameraTile";
import IncidentFeed, { type FeedItem } from "./IncidentFeed";
import WebcamTile from "./WebcamTile";

interface Props {
  statuses: CameraStatus[];
  /** Non-rejected incidents; they pop into the feed as each camera's playback reaches them. */
  incidents: Incident[];
  children?: React.ReactNode;
}

const PRIORITY_RANK = { high: 0, medium: 1, low: 2 } as const;

export default function LiveWall({ statuses, incidents, children }: Props) {
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [active, setActive] = useState<Record<string, Incident[]>>({});
  const [showOverlay, setShowOverlay] = useState(true);
  const seen = useRef(new Set<string>());
  const dismissed = useRef(new Set<string>());
  const activeKey = useRef<Record<string, string>>({});

  const onTime = useCallback(
    (cameraId: string, t: number) => {
      const own = incidents.filter((i) => i.cameraId === cameraId);
      const fresh = own.filter((i) => t >= i.startSec && !seen.current.has(i.id) && !dismissed.current.has(i.id));
      if (fresh.length) {
        fresh.forEach((i) => seen.current.add(i.id));
        const at = Date.now();
        setFeed((f) => [...fresh.map((incident) => ({ incident, seenAt: at })), ...f]);
      }
      const now = own
        .filter((i) => t >= i.startSec && t <= i.endSec + 0.5 && !dismissed.current.has(i.id))
        .sort((a, b) => PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority]);
      const key = now.map((i) => i.id).join(",");
      if (activeKey.current[cameraId] !== key) {
        activeKey.current[cameraId] = key;
        setActive((a) => ({ ...a, [cameraId]: now }));
      }
    },
    [incidents],
  );

  const dismiss = (id: string) => {
    dismissed.current.add(id);
    setFeed((f) => f.filter((x) => x.incident.id !== id));
  };

  const reset = () => {
    seen.current.clear();
    dismissed.current.clear();
    setFeed([]);
  };

  const high = feed.filter((f) => f.incident.priority === "high").length;

  return (
    <div className="grid min-h-[calc(100vh-57px)] grid-cols-1 lg:grid-cols-[minmax(0,1fr)_420px]">
      <div className="flex min-w-0 flex-col gap-4 border-r border-white/[0.08] p-5">
        {high > 0 && (
          <div className="banner-pulse flex items-center gap-3 rounded-xl border border-red-900 bg-[#3d0c0c] px-5 py-3 text-sm text-[#fca5a5]">
            <span className="text-base">⚠</span>
            <span>
              Review recommended for <strong>{high}</strong> high-priority incident{high > 1 ? "s" : ""} based on
              observable signals.
            </span>
          </div>
        )}
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-slate-500">
            Replaying indexed footage · boxes = YOLO person tracks · pink arrow = optical-flow crowd motion
          </span>
          <label className="flex items-center gap-1.5 text-[11px] text-slate-400">
            <input type="checkbox" checked={showOverlay} onChange={(e) => setShowOverlay(e.target.checked)} />
            Tracking overlay
          </label>
        </div>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <WebcamTile showOverlay={showOverlay} />
          {statuses.map((s) => (
            <CameraTile
              key={s.camera.id}
              status={s}
              showOverlay={showOverlay}
              active={active[s.camera.id] ?? []}
              onTime={onTime}
            />
          ))}
        </div>
        {children}
      </div>
      <aside className="overflow-y-auto bg-[#07070e] p-5">
        <IncidentFeed items={feed} onDismiss={dismiss} onReset={reset} />
      </aside>
    </div>
  );
}
