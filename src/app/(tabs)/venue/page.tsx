import Link from "next/link";
import VenueMap from "@/app/components/VenueMap";
import { countByZone } from "@/app/lib/search";
import { EVENT_LABEL } from "@/app/lib/types";
import { listIncidents, loadVenue } from "@/app/lib/venue";

export const dynamic = "force-dynamic";

export default async function VenuePage() {
  const [venue, incidents] = await Promise.all([loadVenue(), listIncidents()]);
  const visible = incidents.filter((i) => i.verificationStatus !== "rejected");
  const zones = countByZone(visible, venue.cameras);
  const rejected = incidents.length - visible.length;

  return (
    <div className="mx-auto grid w-full max-w-7xl gap-6 px-6 py-6 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div>
        <h1 className="text-lg font-semibold text-white">{venue.venueName}</h1>
        <p className="mb-3 text-sm text-slate-400">
          Kept and unverified incidents by venue zone ({rejected} rejected candidate{rejected === 1 ? "" : "s"} hidden).
          Click a zone to search it.
        </p>
        <VenueMap zones={zones} />
      </div>
      <aside className="flex flex-col gap-2">
        {zones.map((z) => {
          const cam = venue.cameras.find((c) => c.zoneId === z.zoneId);
          return (
            <Link
              key={z.zoneId}
              href={`/search?q=${encodeURIComponent(`Show all incidents in ${z.zone}`)}`}
              className="rounded-xl border border-white/10 bg-[#0c0c12] p-3 transition-colors hover:border-white/25"
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-white">{z.zone}</span>
                <span className="font-mono text-xs text-slate-400">{cam?.id}</span>
              </div>
              <div className="mt-1 text-[12px] text-slate-400">
                {z.total} incident{z.total === 1 ? "" : "s"} · {z.kept} kept
              </div>
              {z.eventTypes.length > 0 && (
                <div className="mt-1 text-[11px] text-slate-500">{z.eventTypes.map((t) => EVENT_LABEL[t]).join(", ")}</div>
              )}
            </Link>
          );
        })}
      </aside>
    </div>
  );
}
