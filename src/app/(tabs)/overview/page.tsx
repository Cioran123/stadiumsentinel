import EvalPanel from "@/app/components/EvalPanel";
import LiveWall from "@/app/components/LiveWall";
import { getCameraStatuses } from "@/app/lib/cameraStatus";
import { listIncidents, loadEvalSummary, loadVenue } from "@/app/lib/venue";

export const dynamic = "force-dynamic";

export default async function OverviewPage() {
  const [venue, statuses, incidents, evalSummary] = await Promise.all([
    loadVenue(),
    getCameraStatuses(),
    listIncidents(),
    loadEvalSummary(),
  ]);
  const withFootage = statuses.filter((s) => s.indexStatus !== "missing_video").length;
  const kept = statuses.reduce((n, s) => n + s.keptCount, 0);

  return (
    <LiveWall statuses={statuses} incidents={incidents.filter((i) => i.verificationStatus !== "rejected")}>
      <div className="mt-2">
        <h1 className="text-base font-semibold text-white">{venue.venueName}</h1>
        <p className="mb-3 text-sm text-slate-400">
          {statuses.length} fixed cameras · {withFootage} with footage · {kept} verified incident
          {kept === 1 ? "" : "s"}
        </p>
        <EvalPanel summary={evalSummary} />
      </div>
    </LiveWall>
  );
}
