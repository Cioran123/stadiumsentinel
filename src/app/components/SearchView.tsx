"use client";

import { useCallback, useState } from "react";
import { fetchWithToast } from "@/app/lib/fetchWithToast";
import type { SearchResponse } from "@/app/lib/search";
import { EVENT_LABEL } from "@/app/lib/types";
import IncidentCard from "./IncidentCard";

const EXAMPLES = [
  "Show all possible crowd-flow anomalies across the venue.",
  "Find every restricted-zone entry.",
  "Show possible altercations near spectator areas.",
  "Which zones had repeated incidents?",
  "Show rejected candidates.",
];

export default function SearchView({
  initialQuery,
  initialData,
}: {
  initialQuery: string;
  initialData: SearchResponse | null;
}) {
  const [query, setQuery] = useState(initialQuery);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<SearchResponse | null>(initialData);

  const run = useCallback(async (q: string) => {
    const trimmed = q.trim();
    if (!trimmed) return;
    setLoading(true);
    try {
      const res = await fetchWithToast("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: trimmed }),
      }, { errorMessage: "Search failed" });
      if (!res.ok) return;
      setData((await res.json()) as SearchResponse);
      const url = new URL(window.location.href);
      url.searchParams.set("q", trimmed);
      window.history.replaceState(null, "", url);
    } catch {
      // toast already shown
    } finally {
      setLoading(false);
    }
  }, []);

  return (
    <div className="mx-auto w-full max-w-5xl px-6 py-6">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void run(query);
        }}
        className="flex gap-2"
      >
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Ask about incidents across the venue…"
          className="flex-1 rounded-xl border border-white/10 bg-[#0c0c12] px-4 py-3 text-sm text-white placeholder:text-slate-600 focus:border-white/30 focus:outline-none"
        />
        <button
          type="submit"
          disabled={loading}
          className="rounded-xl bg-white/10 px-5 text-sm font-medium text-white transition-colors hover:bg-white/20 disabled:opacity-50"
        >
          {loading ? "Searching…" : "Search"}
        </button>
      </form>
      <div className="mt-3 flex flex-wrap gap-2">
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            type="button"
            onClick={() => {
              setQuery(ex);
              void run(ex);
            }}
            className="rounded-full border border-white/10 px-3 py-1 text-[11px] text-slate-400 transition-colors hover:border-white/25 hover:text-slate-200"
          >
            {ex}
          </button>
        ))}
      </div>

      {data && (
        <div className="mt-6">
          <div className="mb-3 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
            <span>Interpreted by {data.parser === "claude" ? "Claude" : "keyword rules"}:</span>
            {data.filters.eventTypes.map((t) => (
              <span key={t} className="rounded bg-white/5 px-1.5 py-0.5 text-slate-300">{EVENT_LABEL[t]}</span>
            ))}
            {data.filters.zoneIds.map((z) => (
              <span key={z} className="rounded bg-white/5 px-1.5 py-0.5 text-slate-300">zone: {z}</span>
            ))}
            {data.filters.priorities.map((p) => (
              <span key={p} className="rounded bg-white/5 px-1.5 py-0.5 text-slate-300">{p} priority</span>
            ))}
            <span className="rounded bg-white/5 px-1.5 py-0.5 text-slate-300">
              status: {data.filters.statuses.join(", ")}
            </span>
            <span>· {data.results.length} result{data.results.length === 1 ? "" : "s"}</span>
            {data.backend && <span>· index: {data.backend}</span>}
          </div>

          {data.message && (
            <div className="mb-4 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3 text-sm text-slate-300">
              {data.message}
            </div>
          )}

          {data.zoneCounts && (
            <table className="mb-5 w-full text-left text-sm">
              <thead className="text-[10px] uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="py-1">Zone</th>
                  <th>Incidents</th>
                  <th>Kept</th>
                  <th>Types</th>
                </tr>
              </thead>
              <tbody className="text-slate-300">
                {data.zoneCounts.map((z) => (
                  <tr key={z.zoneId} className="border-t border-white/5">
                    <td className="py-1.5">{z.zone}</td>
                    <td>{z.total}</td>
                    <td>{z.kept}</td>
                    <td className="text-xs text-slate-400">{z.eventTypes.map((t) => EVENT_LABEL[t]).join(", ") || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <div className="flex flex-col gap-3">
            {data.results.map((i) => (
              <IncidentCard key={i.id} incident={i} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
