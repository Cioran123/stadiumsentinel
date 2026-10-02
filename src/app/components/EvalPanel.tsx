import type { EvalSummary } from "@/app/lib/types";

const METRIC_LABEL: Record<string, string> = {
  detected_rate: "Scenarios surfaced",
  kept_rate: "Scenarios kept by verifier",
  mean_iou: "Mean temporal IoU",
  type_match_rate: "Event-type match",
  normal_false_positive_rate: "False positives on normal segments",
  evidence_rate: "Kept results with evidence",
};

function fmt(v: number): string {
  return v <= 1 ? `${Math.round(v * 100)}%` : String(v);
}

export default function EvalPanel({ summary }: { summary: EvalSummary | null }) {
  return (
    <section className="rounded-xl border border-white/10 bg-[#0c0c12] p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-white">Evaluation vs. ground truth</h2>
        {summary?.weaveUrl && (
          <a
            href={summary.weaveUrl}
            target="_blank"
            rel="noreferrer"
            className="text-[11px] text-amber-300 hover:text-amber-200"
          >
            Open W&B Weave run ↗
          </a>
        )}
      </div>
      {!summary ? (
        <p className="text-xs text-slate-500">
          No evaluation yet. Run <code className="text-slate-300">npm run eval</code> after the pipeline.
        </p>
      ) : (
        <>
          <p className="mb-3 text-[11px] text-slate-500">
            Prompt {summary.promptVersion} · verifier {summary.verifier} ·{" "}
            {new Date(summary.createdAt).toLocaleString()}
          </p>
          <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
            {Object.entries(summary.metrics).map(([k, v]) => (
              <div key={k} className="rounded-lg bg-white/[0.03] p-2">
                <div className="text-lg font-semibold text-white">{fmt(v)}</div>
                <div className="text-[10px] uppercase tracking-wider text-slate-500">
                  {METRIC_LABEL[k] ?? k}
                </div>
              </div>
            ))}
          </div>
          <table className="w-full text-left text-xs">
            <thead className="text-[10px] uppercase tracking-wider text-slate-500">
              <tr>
                <th className="py-1">Camera</th>
                <th>Expected</th>
                <th>Best match</th>
                <th>IoU</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody className="font-mono text-slate-300">
              {summary.rows.map((r, i) => (
                <tr key={`${r.cameraId}-${i}`} className="border-t border-white/5">
                  <td className="py-1">{r.cameraId}</td>
                  <td>{r.expected}</td>
                  <td>{r.predicted}</td>
                  <td>{r.iou.toFixed(2)}</td>
                  <td>{r.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
