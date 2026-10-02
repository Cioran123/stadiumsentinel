import Link from "next/link";
import type { ZoneCount } from "@/app/lib/search";
import { EVENT_LABEL } from "@/app/lib/types";

/** Hand-drawn zone shapes on a 1000x640 canvas: field in the middle, stands around it. */
const ZONE_SHAPES: Record<string, { d: string; label: [number, number] }> = {
  north_gate: { d: "M420 18 h160 v58 h-160 z", label: [500, 52] },
  exit_plaza: { d: "M150 30 h220 v60 h-220 z", label: [260, 64] },
  east_concourse: { d: "M870 150 h96 v340 h-96 z", label: [918, 320] },
  field_perimeter: { d: "M300 200 h400 v240 h-400 z M330 228 v184 h340 v-184 z", label: [500, 222] },
  section_114: { d: "M120 470 L300 440 L330 560 L150 590 z", label: [225, 520] },
  staff_tunnel: { d: "M470 440 h60 v170 h-60 z", label: [500, 585] },
};

function shade(total: number, max: number): string {
  if (total === 0) return "rgba(148,163,184,0.08)";
  const a = 0.25 + 0.6 * (total / Math.max(1, max));
  return `rgba(239,68,68,${a.toFixed(2)})`;
}

export default function VenueMap({ zones }: { zones: ZoneCount[] }) {
  const max = Math.max(1, ...zones.map((z) => z.total));
  return (
    <svg viewBox="0 0 1000 640" className="w-full rounded-xl border border-white/10 bg-[#0c0c12]">
      {/* stands + pitch for orientation */}
      <ellipse cx="500" cy="320" rx="420" ry="250" fill="none" stroke="#334155" strokeWidth="2" />
      <ellipse cx="500" cy="320" rx="300" ry="160" fill="none" stroke="#1e293b" strokeWidth="40" />
      <rect x="330" y="228" width="340" height="184" fill="#14532d" fillOpacity="0.35" stroke="#166534" />
      <line x1="500" y1="228" x2="500" y2="412" stroke="#166534" />
      <circle cx="500" cy="320" r="34" fill="none" stroke="#166534" />
      <text x="500" y="632" textAnchor="middle" className="fill-slate-600 text-[12px]">South</text>
      <text x="500" y="12" textAnchor="middle" className="fill-slate-600 text-[12px]">North</text>

      {zones.map((z) => {
        const shape = ZONE_SHAPES[z.zoneId];
        if (!shape) return null;
        const title = `${z.zone}: ${z.total} incident${z.total === 1 ? "" : "s"} (${z.kept} kept)${
          z.eventTypes.length ? ` · ${z.eventTypes.map((t) => EVENT_LABEL[t]).join(", ")}` : ""
        }`;
        return (
          <Link key={z.zoneId} href={`/search?q=${encodeURIComponent(`Show all incidents in ${z.zone}`)}`}>
            <g className="cursor-pointer">
              <path
                d={shape.d}
                fill={shade(z.total, max)}
                fillRule="evenodd"
                stroke={z.total ? "#f87171" : "#475569"}
                strokeWidth="2"
                className="transition-opacity hover:opacity-80"
              >
                <title>{title}</title>
              </path>
              <text x={shape.label[0]} y={shape.label[1] - 8} textAnchor="middle" className="pointer-events-none fill-white text-[13px] font-semibold">
                {z.zone}
              </text>
              <text x={shape.label[0]} y={shape.label[1] + 10} textAnchor="middle" className="pointer-events-none fill-slate-300 text-[12px]">
                {z.total} · {z.kept} kept
              </text>
            </g>
          </Link>
        );
      })}
    </svg>
  );
}
