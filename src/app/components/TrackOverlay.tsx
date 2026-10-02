import type { Camera, Point, TrackFrame } from "@/app/lib/types";

/** Binary search for the sampled frame nearest `t` (within half a second). */
export function nearestFrame(frames: TrackFrame[], t: number): TrackFrame | null {
  if (frames.length === 0) return null;
  let lo = 0;
  let hi = frames.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (frames[mid].t < t) lo = mid + 1;
    else hi = mid;
  }
  const best = lo > 0 && Math.abs(frames[lo - 1].t - t) < Math.abs(frames[lo].t - t) ? frames[lo - 1] : frames[lo];
  return Math.abs(best.t - t) <= 0.5 ? best : null;
}

// 16:9 user space so text and arrows are not stretched; inputs are normalized 0..1.
const W = 160;
const H = 90;
const DEFAULT_ROI: Point[] = [[0, 0.06], [1, 0.06], [1, 1], [0, 1]];
const FLOW_MIN_MOVING = 0.15;

const pts = (poly: Point[]) => poly.map(([x, y]) => `${x * W},${y * H}`).join(" ");

// COCO-17 limbs: head to shoulders, arms, torso, legs.
const SKELETON: [number, number][] = [
  [0, 5], [0, 6], [5, 6],
  [5, 7], [7, 9], [6, 8], [8, 10],
  [5, 11], [6, 12], [11, 12],
  [11, 13], [13, 15], [12, 14], [14, 16],
];
// Occluded joints in a crowd come back with low confidence and a wrong position; hide them.
const KP_MIN_CONF = 0.4;

function Skeleton({ kp, color }: { kp: [number, number, number][]; color: string }) {
  const ok = (i: number) => kp[i] && kp[i][2] >= KP_MIN_CONF;
  return (
    <g stroke={color} strokeWidth={0.35} strokeLinecap="round">
      {SKELETON.map(([a, b]) =>
        ok(a) && ok(b) ? (
          <line key={`${a}-${b}`} x1={kp[a][0] * W} y1={kp[a][1] * H} x2={kp[b][0] * W} y2={kp[b][1] * H} />
        ) : null,
      )}
      {kp.map(([x, y], i) => (ok(i) ? <circle key={i} cx={x * W} cy={y * H} r={0.35} fill={color} stroke="none" /> : null))}
    </g>
  );
}

function FlowArrow({ frame, roi }: { frame: TrackFrame; roi: Point[] }) {
  const flow = frame.flow;
  if (!flow || flow.movingFrac < FLOW_MIN_MOVING) return null;
  const cx = (roi.reduce((s, p) => s + p[0], 0) / roi.length) * W;
  const cy = (roi.reduce((s, p) => s + p[1], 0) / roi.length) * H;
  // 0.15 frame-widths/s (a fast rush) maps to an arrow ~1/4 of the frame width
  const len = Math.min(45, 8 + (flow.mag / 0.15) * 32);
  // flow vectors are normalized by frame width on both axes, so the angle is pixel-true
  const rad = (flow.dir * Math.PI) / 180;
  const x2 = cx + Math.cos(rad) * len;
  const y2 = cy + Math.sin(rad) * len;
  return (
    <g opacity={0.35 + 0.65 * flow.align}>
      <defs>
        <marker id="flow-head" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="3" markerHeight="3" orient="auto">
          <path d="M0,0 L10,5 L0,10 z" fill="#f472b6" />
        </marker>
      </defs>
      <line x1={cx} y1={cy} x2={x2} y2={y2} stroke="#f472b6" strokeWidth={1.6} strokeLinecap="round" markerEnd="url(#flow-head)" />
      <text x={cx} y={cy + 6} fill="#f9a8d4" fontSize={3.2} textAnchor="middle" fontFamily="ui-monospace, monospace"
        style={{ paintOrder: "stroke", stroke: "#000", strokeWidth: 0.6 }}>
        crowd flow {Math.round(flow.movingFrac * 100)}% moving
      </text>
    </g>
  );
}

interface Props {
  camera: Camera;
  frame: TrackFrame | null;
  highlight?: Set<number>;
  showIds?: boolean;
}

/** Live YOLO boxes, pose skeletons, track IDs, ROI, restricted polygons, and the optical-flow direction. */
export default function TrackOverlay({ camera, frame, highlight, showIds = true }: Props) {
  const roi = camera.roi ?? DEFAULT_ROI;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-full w-full">
      {camera.roi && (
        <polygon points={pts(camera.roi)} fill="none" stroke="#94a3b8" strokeOpacity={0.5} strokeWidth={0.4} strokeDasharray="2 1.5" />
      )}
      {(camera.restrictedPolygons ?? []).map((poly, i) => (
        <polygon key={i} points={pts(poly)} fill="#ef4444" fillOpacity={0.12} stroke="#ef4444" strokeWidth={0.5} strokeDasharray="2 1.5" />
      ))}
      {frame?.boxes.map((b) => {
        const [x1, y1, x2, y2] = b.box;
        const hot = highlight?.has(b.id);
        const color = hot ? "#facc15" : "#38bdf8";
        return (
          <g key={b.id}>
            <rect x={x1 * W} y={y1 * H} width={(x2 - x1) * W} height={(y2 - y1) * H} fill="none" stroke={color} strokeWidth={hot ? 0.8 : 0.45} />
            {b.kp && <Skeleton kp={b.kp} color={hot ? "#fde047" : "#a3e635"} />}
            {showIds && (
              <text x={x1 * W + 0.5} y={y1 * H - 0.8} fill={color} fontSize={2.6} fontFamily="ui-monospace, monospace"
                style={{ paintOrder: "stroke", stroke: "#000", strokeWidth: 0.5 }}>
                #{b.id}
              </text>
            )}
          </g>
        );
      })}
      {frame && <FlowArrow frame={frame} roi={roi} />}
    </svg>
  );
}
