"use client";

import { useRef } from "react";
import { formatTime } from "@/app/lib/format";

export interface TimelineBand {
  id: string;
  startSec: number;
  endSec: number;
  color: string;
  label: string;
  /** 0 = top row (ground truth), 1 = detections. */
  row: 0 | 1;
  outlined?: boolean;
  active?: boolean;
}

interface Props {
  bands: TimelineBand[];
  currentTime: number;
  duration: number;
  onSeek: (seconds: number) => void;
  onSelect?: (id: string) => void;
}

const ROW_Y = [5, 25];
const ROW_H = 16;

export default function EventTimeline({ bands, currentTime, duration, onSeek, onSelect }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const safeDuration = duration > 0 ? duration : 1;
  const playheadPct = Math.max(0, Math.min(100, (currentTime / safeDuration) * 100));

  const handleSeek = (clientX: number) => {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    onSeek(ratio * safeDuration);
  };

  return (
    <div>
      <div className="flex items-center justify-between px-1 pb-1 font-mono text-[10px] text-slate-500">
        <span>{formatTime(currentTime)}</span>
        <span>{formatTime(duration)}</span>
      </div>
      <div className="relative h-[46px] w-full overflow-hidden rounded-lg border border-white/10 bg-[#0c0c12]">
        <svg
          ref={svgRef}
          width="100%"
          height="46"
          className="block cursor-pointer"
          onClick={(e) => handleSeek(e.clientX)}
          role="slider"
          aria-label="Incident timeline"
          aria-valuemin={0}
          aria-valuemax={duration}
          aria-valuenow={currentTime}
        >
          {bands.map((b) => {
            const xPct = (b.startSec / safeDuration) * 100;
            const wPct = Math.max(0.6, ((b.endSec - b.startSec) / safeDuration) * 100);
            return (
              <rect
                key={b.id}
                x={`${xPct}%`}
                y={ROW_Y[b.row]}
                width={`${wPct}%`}
                height={ROW_H}
                rx={2}
                fill={b.outlined ? "transparent" : b.color}
                fillOpacity={b.active ? 1 : 0.6}
                stroke={b.outlined || b.active ? b.color : "none"}
                strokeWidth={b.active ? 2 : 1.5}
                strokeDasharray={b.outlined ? "4 3" : undefined}
                onClick={(e) => {
                  if (!onSelect || b.outlined) return;
                  e.stopPropagation();
                  onSelect(b.id);
                }}
              >
                <title>{`${b.label} · ${formatTime(b.startSec)}–${formatTime(b.endSec)}`}</title>
              </rect>
            );
          })}
          <line
            x1={`${playheadPct}%`}
            x2={`${playheadPct}%`}
            y1={0}
            y2={46}
            stroke="#ffffff"
            strokeWidth={2}
            pointerEvents="none"
          />
        </svg>
      </div>
      <div className="mt-2 flex flex-wrap gap-4 text-[10px] uppercase tracking-wider text-slate-400">
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-4 rounded-sm border border-dashed border-slate-300" />
          Scripted scenario window (ground truth)
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-4 rounded-sm bg-emerald-500" /> kept
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-4 rounded-sm bg-slate-400" /> candidate
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-4 rounded-sm bg-slate-600" /> rejected
        </span>
      </div>
    </div>
  );
}
