import { getAnthropic } from "@/app/lib/anthropic";
import {
  EVENT_LABEL,
  EVENT_TYPES,
  type Camera,
  type EventType,
  type Incident,
  type Priority,
  type VerificationStatus,
} from "@/app/lib/types";
import { listIncidents, loadVenue } from "@/app/lib/venue";
import { traced } from "@/app/lib/weave";

export type SearchIntent = "list" | "zone_counts";

export interface SearchFilters {
  eventTypes: EventType[];
  zoneIds: string[];
  priorities: Priority[];
  statuses: VerificationStatus[];
  intent: SearchIntent;
  /** Set when the query asks for something the system does not detect. */
  unsupported?: string;
}

export interface ZoneCount {
  zoneId: string;
  zone: string;
  total: number;
  kept: number;
  eventTypes: EventType[];
}

export interface SearchResponse {
  query: string;
  filters: SearchFilters;
  parser: "claude" | "rules";
  backend?: IndexBackend;
  results: Incident[];
  zoneCounts?: ZoneCount[];
  message?: string;
}

const PRIORITIES: Priority[] = ["low", "medium", "high"];
const STATUSES: VerificationStatus[] = ["candidate", "kept", "rejected"];
const DEFAULT_STATUSES: VerificationStatus[] = ["kept", "candidate"];
const SPECTATOR_ZONES = ["north_gate", "exit_plaza", "east_concourse", "section_114"];

const EVENT_KEYWORDS: Record<EventType, RegExp> = {
  crowd_flow_anomaly: /\b(crowd|flow|rush|surge|bottleneck|congest\w*|crush|stampede|reversal|converg\w*)\b/,
  restricted_zone_entry: /\b(restricted|staff[- ]only|trespass\w*|unauthori[sz]ed|breach\w*|zone entr\w*|entries|intru\w*)\b/,
  possible_altercation: /\b(altercation\w*|fight\w*|argu\w*|confront\w*|scuffle\w*|dispute\w*)\b/,
  person_down_or_inactivity: /\b(down|fall\w*|fell|fallen|inactiv\w*|motionless|collaps\w*|unresponsive|lying|still)\b/,
};

const ZONE_KEYWORDS: Record<string, RegExp> = {
  north_gate: /\b(north gate|gate|queue|entrance)\b/,
  exit_plaza: /\b(exit|plaza)\b/,
  east_concourse: /\b(east|concourse)\b/,
  field_perimeter: /\b(field|perimeter|pitch)\b/,
  section_114: /\b(section|114|seating|aisle|seats?)\b/,
  staff_tunnel: /\b(tunnel|service corridor)\b/,
};

const UNSUPPORTED =
  /\b(weapon|gun|knife|face|identify|identity|who is|name of|stole|steal|theft|drunk|intoxicat\w*|drug|criminal|race|ethnic\w*|age of|diagnos\w*|heart attack|seizure)\b/;

const GENERAL = /\b(all|every|any|incidents?|everything|anything|show|list|attention|review)\b/;

export function parseWithRules(query: string): SearchFilters {
  const q = query.toLowerCase();
  const unsupportedMatch = UNSUPPORTED.exec(q);

  const eventTypes = EVENT_TYPES.filter((t) => EVENT_KEYWORDS[t].test(q));
  let zoneIds = Object.keys(ZONE_KEYWORDS).filter((z) => ZONE_KEYWORDS[z].test(q));
  if (/\bspectator/.test(q)) zoneIds = Array.from(new Set([...zoneIds, ...SPECTATOR_ZONES]));
  // "staff-only" names an event type, not the staff tunnel zone.
  if (/staff[- ]only/.test(q) && !/tunnel/.test(q)) zoneIds = zoneIds.filter((z) => z !== "staff_tunnel");

  const priorities: Priority[] = /\bhigh[- ]priority|urgent|critical\b/.test(q)
    ? ["high"]
    : /\bmedium\b/.test(q)
      ? ["medium"]
      : [];

  let statuses = DEFAULT_STATUSES;
  if (/\b(rejected|dropped|false positives?)\b/.test(q)) statuses = ["rejected"];
  else if (/\b(verified|kept|confirmed|requiring attention|need\w* attention)\b/.test(q)) statuses = ["kept"];
  else if (/\b(unverified|candidates?)\b/.test(q)) statuses = ["candidate"];
  else if (/\bincluding rejected|everything\b/.test(q)) statuses = STATUSES;

  const intent: SearchIntent = /\b(which zones?|by zone|repeated|per zone|most incidents|hotspots?)\b/.test(q)
    ? "zone_counts"
    : "list";

  const matchedSomething =
    eventTypes.length > 0 || zoneIds.length > 0 || priorities.length > 0 || intent !== "list" || GENERAL.test(q);

  return {
    eventTypes,
    zoneIds,
    priorities,
    statuses,
    intent,
    unsupported: unsupportedMatch
      ? `"${unsupportedMatch[0]}" is not something Stadium Sentinel detects`
      : matchedSomething
        ? undefined
        : "the query did not mention a supported event type, zone, or status",
  };
}

function buildParsePrompt(query: string, cameras: Camera[]): string {
  return `You convert an operator's question about stadium camera footage into search filters.
Supported event types: ${EVENT_TYPES.map((t) => `${t} (${EVENT_LABEL[t]})`).join("; ")}.
Zones: ${cameras.map((c) => `${c.zoneId} (${c.zone}, ${c.id})`).join("; ")}. "Spectator areas" means ${SPECTATOR_ZONES.join(", ")}.
Verification statuses: kept (verifier kept it), candidate (unverified), rejected (verifier dropped it).
Default statuses when the question does not say: ["kept","candidate"]. "Requiring attention" means ["kept"].
The system does NOT detect weapons, identities, faces, intent, crimes, intoxication, or medical conditions.
If the question asks for any of those, set "unsupported" to a short reason.

Question: ${JSON.stringify(query)}

Return ONLY JSON:
{"eventTypes": [], "zoneIds": [], "priorities": [], "statuses": ["kept","candidate"], "intent": "list" | "zone_counts", "unsupported": null}`;
}

function sanitize(raw: unknown, cameras: Camera[]): SearchFilters | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const zoneSet = new Set(cameras.map((c) => c.zoneId));
  const pick = <T extends string>(v: unknown, allowed: readonly T[] | Set<string>): T[] =>
    Array.isArray(v)
      ? (v.filter((x) => typeof x === "string" && (Array.isArray(allowed) ? allowed.includes(x as T) : (allowed as Set<string>).has(x))) as T[])
      : [];
  const statuses = pick<VerificationStatus>(r.statuses, STATUSES);
  return {
    eventTypes: pick<EventType>(r.eventTypes, EVENT_TYPES),
    zoneIds: pick<string>(r.zoneIds, zoneSet),
    priorities: pick<Priority>(r.priorities, PRIORITIES),
    statuses: statuses.length ? statuses : DEFAULT_STATUSES,
    intent: r.intent === "zone_counts" ? "zone_counts" : "list",
    unsupported: typeof r.unsupported === "string" && r.unsupported.trim() ? r.unsupported.trim() : undefined,
  };
}

async function parseWithClaude(query: string, cameras: Camera[]): Promise<SearchFilters | null> {
  if (!process.env.ANTHROPIC_API_KEY) return null;
  try {
    const res = await getAnthropic().messages.create({
      model: process.env.CLAUDE_MODEL ?? "claude-haiku-4-5",
      max_tokens: 300,
      temperature: 0,
      messages: [{ role: "user", content: buildParsePrompt(query, cameras) }],
    });
    const block = res.content[0];
    const text = block && block.type === "text" ? block.text : "";
    const json = /\{[\s\S]*\}/.exec(text)?.[0];
    return json ? sanitize(JSON.parse(json), cameras) : null;
  } catch (err) {
    console.warn("[search] Claude parse failed, using rules:", err instanceof Error ? err.message : err);
    return null;
  }
}

async function parseQueryImpl(
  query: string,
): Promise<{ filters: SearchFilters; parser: "claude" | "rules" }> {
  const venue = await loadVenue();
  const viaClaude = await parseWithClaude(query, venue.cameras);
  if (viaClaude) return { filters: viaClaude, parser: "claude" };
  return { filters: parseWithRules(query), parser: "rules" };
}

export function parseQuery(query: string) {
  return traced("sentinel.parse_query", parseQueryImpl, query);
}

export type IndexBackend = "local" | "vast" | "local (vast unreachable)";

async function retrieveFromVast(filters: SearchFilters): Promise<Incident[]> {
  const url = process.env.VAST_SEARCH_URL ?? "http://127.0.0.1:8765/search";
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(filters),
    signal: AbortSignal.timeout(8000),
  });
  if (!res.ok) throw new Error(`VAST search ${res.status}`);
  return ((await res.json()) as { incidents: Incident[] }).incidents;
}

async function retrieveImpl(filters: SearchFilters): Promise<{ incidents: Incident[]; backend: IndexBackend }> {
  const [venue, local] = await Promise.all([loadVenue(), listIncidents()]);
  if (process.env.INDEX_BACKEND === "vast") {
    try {
      // VAST applies the filters server-side; re-applying locally only sorts.
      return { incidents: applyFilters(await retrieveFromVast(filters), filters, venue.cameras), backend: "vast" };
    } catch (err) {
      console.warn("[search] VAST retrieval failed, using local ledger:", err instanceof Error ? err.message : err);
      return { incidents: applyFilters(local, filters, venue.cameras), backend: "local (vast unreachable)" };
    }
  }
  return { incidents: applyFilters(local, filters, venue.cameras), backend: "local" };
}

export function applyFilters(incidents: Incident[], f: SearchFilters, cameras: Camera[]): Incident[] {
  const zoneOf = new Map(cameras.map((c) => [c.id, c.zoneId]));
  const rank = { high: 0, medium: 1, low: 2 };
  return incidents
    .filter((i) => f.eventTypes.length === 0 || f.eventTypes.includes(i.eventType))
    .filter((i) => f.zoneIds.length === 0 || f.zoneIds.includes(zoneOf.get(i.cameraId) ?? ""))
    .filter((i) => f.priorities.length === 0 || f.priorities.includes(i.priority))
    .filter((i) => f.statuses.includes(i.verificationStatus))
    .sort((a, b) => rank[a.priority] - rank[b.priority] || a.cameraId.localeCompare(b.cameraId) || a.startSec - b.startSec);
}

export function countByZone(incidents: Incident[], cameras: Camera[]): ZoneCount[] {
  return cameras
    .map((c) => {
      const own = incidents.filter((i) => i.cameraId === c.id);
      return {
        zoneId: c.zoneId,
        zone: c.zone,
        total: own.length,
        kept: own.filter((i) => i.verificationStatus === "kept").length,
        eventTypes: Array.from(new Set(own.map((i) => i.eventType))),
      };
    })
    .sort((a, b) => b.total - a.total);
}

export function describeFilters(f: SearchFilters, cameras: Camera[]): string {
  const parts: string[] = [];
  parts.push(f.eventTypes.length ? f.eventTypes.map((t) => EVENT_LABEL[t]).join(" or ") : "any event type");
  if (f.zoneIds.length) {
    parts.push(`in ${f.zoneIds.map((z) => cameras.find((c) => c.zoneId === z)?.zone ?? z).join(", ")}`);
  }
  if (f.priorities.length) parts.push(`${f.priorities.join("/")} priority`);
  parts.push(`status ${f.statuses.join("/")}`);
  return parts.join(", ");
}

export function searchIncidents(query: string): Promise<SearchResponse> {
  return traced("sentinel.search", searchImpl, query);
}

async function searchImpl(query: string): Promise<SearchResponse> {
  const [venue, parsed] = await Promise.all([loadVenue(), parseQuery(query)]);
  const { filters, parser } = parsed;

  if (filters.unsupported) {
    return {
      query,
      filters,
      parser,
      results: [],
      message: `No supported incident found: ${filters.unsupported}. Stadium Sentinel only surfaces ${EVENT_TYPES.map((t) => EVENT_LABEL[t].toLowerCase()).join(", ")}.`,
    };
  }

  const { incidents: results, backend } = await traced("sentinel.retrieve", retrieveImpl, filters);
  const response: SearchResponse = { query, filters, parser, backend, results };
  if (filters.intent === "zone_counts") {
    response.zoneCounts = countByZone(results, venue.cameras);
    const repeated = response.zoneCounts.filter((z) => z.total > 1);
    response.message = repeated.length
      ? `Zones with repeated incidents: ${repeated.map((z) => `${z.zone} (${z.total})`).join(", ")}.`
      : "No zone had more than one matching incident.";
  } else if (results.length === 0) {
    response.message = `No supported incident found for ${describeFilters(filters, venue.cameras)}.`;
  }
  return response;
}
