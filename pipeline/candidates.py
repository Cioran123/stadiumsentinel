"""Candidate-generation checks over YOLO tracks.

These checks do not decide that an incident occurred. They select short windows of
footage for the verifier (Cosmos) to review. Every check runs on every camera (the zone
check only where restricted polygons are configured), so normal footage gets a chance
to produce false positives that the verifier must reject.

Per-camera overrides go in cameras.json under "thresholds", keyed by the names in
DEFAULTS below.

Usage:
    python pipeline/candidates.py [--camera CAM_01]
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from dataclasses import asdict

import numpy as np
from shapely.geometry import Point, Polygon

from schema import Candidate, candidates_path, load_config, tracks_path
from tracing import op

DEFAULTS = {
    # restricted zone
    "zone_min_inside_sec": 0.6,
    # crowd flow: a score over independent signals, because in dense video one of them
    # (usually the person count) fails even when the crowd clearly changes behavior.
    "flow_baseline_end_sec": 40.0,
    # Short clips use their first third as the baseline instead.
    "flow_baseline_max_frac": 0.33,
    "flow_window_sec": 5.0,
    "flow_min_score": 2,
    "flow_occupancy_ratio": 1.4,
    "flow_speed_z": 1.0,
    "flow_alignment": 0.65,
    "flow_alignment_z": 1.0,
    "flow_direction_change_deg": 60.0,
    "flow_magnitude_z": 2.0,
    "flow_magnitude_ratio": 2.0,
    # Track speeds are in body-heights per second, so far (small) people's detection jitter
    # does not count as movement the way a fixed frame-fraction threshold would.
    "flow_min_moving_speed": 0.25,
    # Share of tracked people that must be moving for track speed/alignment to count;
    # keeps one fast walker from reading as a crowd.
    "flow_min_moving_frac": 0.3,
    # Share of ROI pixels that must be moving for optical-flow signals to count.
    "flow_min_moving_pixels": 0.15,
    # person down / inactivity
    "inactive_min_sec": 6.0,
    "inactive_low_aspect": 1.2,
    "inactive_low_height_ratio": 0.65,
    "inactive_max_displacement": 0.015,
    # person lying on the ground: a wide box that stays put. Someone lying flat usually
    # scores too low to become a track (detect.py keeps these as per-frame `lying` boxes),
    # and in a crowd they are soon hidden, so this needs far less time than inactivity.
    "lying_min_sec": 2.0,
    "lying_min_aspect": 1.2,
    "lying_link_iou": 0.3,
    # chains link across gaps this long (a passer-by briefly hides the person)...
    "lying_max_gap_sec": 1.0,
    # ...but must contain lying_min_sec with no gap longer than this; sparser sightings
    # after that only extend how long they are reported down
    "lying_dense_gap_sec": 0.7,
    # in box widths: a lying person stays put while the crowd moves around them
    "lying_max_displacement": 0.5,
    # possible altercation
    "alter_min_sec": 3.0,
    "alter_max_dist_heights": 1.0,
    # Gesturing shows up as box-width jitter (relative change per sampled frame), judged in
    # sliding alter_min_sec windows so a short struggle is not averaged away.
    "alter_min_jitter": 0.02,
    # ...and it must stand out from the pair's own calmest window (detector noise floor)...
    "alter_jitter_vs_self": 3.0,
    # ...and from similar-depth people around them. In a rush or packed queue everyone's
    # boxes jitter alike, so boxes alone cannot separate an argument from crowding.
    "alter_jitter_vs_neighbors": 2.0,
    "alter_neighbor_radius_heights": 1.5,
    "alter_neighbor_min_height_ratio": 0.6,
    # In a busy concourse, people walking together pass every box rule above. When the
    # tracks carry keypoints, a box proposal must also show interpersonal contact cues:
    # a wrist inside the partner's torso band, and raised wrists (above the shoulders).
    "alter_pose_min_reach_frames": 3,
    "alter_pose_min_raised_frames": 2,
    "alter_pose_kp_conf": 0.4,
    # shared
    "merge_gap_sec": 3.0,
    "max_clip_sec": 12.0,
}


def _ts(t: float) -> str:
    s = int(t)
    return f"{s // 60:02d}:{s % 60:02d}"


def _by_track(frames: list[dict]) -> dict[int, list[tuple[float, dict]]]:
    tracks: dict[int, list[tuple[float, dict]]] = defaultdict(list)
    for f in frames:
        for b in f["boxes"]:
            tracks[b["id"]].append((f["t"], b))
    return tracks


def _runs(mask: list[bool], times: list[float], min_len: float) -> list[tuple[float, float]]:
    """Contiguous True runs in `mask`, as (start, end) times, at least `min_len` long."""
    out, start = [], None
    for i, m in enumerate(mask):
        if m and start is None:
            start = times[i]
        if (not m or i == len(mask) - 1) and start is not None:
            end = times[i] if m else times[i - 1]
            if end - start >= min_len:
                out.append((start, end))
            start = None
    return out


def _window(start: float, end: float, duration: float, pre: float = 3.0, post: float = 3.0,
            max_len: float = 12.0, peak: float | None = None) -> tuple[float, float]:
    s, e = max(0.0, start - pre), min(duration, end + post)
    if e - s > max_len:
        center = peak if peak is not None else (s + e) / 2
        s = max(0.0, center - max_len / 2)
        e = min(duration, s + max_len)
    return round(float(s), 2), round(float(e), 2)


def check_restricted_zone(cam: dict, data: dict, th: dict) -> list[Candidate]:
    polys = [Polygon(p) for p in cam.get("restrictedPolygons", [])]
    if not polys:
        return []
    dt = 1.0 / data["fps"]
    min_inside = max(1, math.ceil(th["zone_min_inside_sec"] / dt))
    out = []
    for tid, samples in _by_track(data["frames"]).items():
        for pi, poly in enumerate(polys):
            inside = [poly.contains(Point((b["box"][0] + b["box"][2]) / 2, b["box"][3])) for _, b in samples]
            for i in range(1, len(inside)):
                if inside[i] and not inside[i - 1] and all(inside[i:i + min_inside]) and len(inside[i:i + min_inside]) == min_inside:
                    t_enter = samples[i][0]
                    j = i
                    while j < len(inside) and inside[j]:
                        j += 1
                    dwell = samples[j - 1][0] - t_enter
                    s, e = _window(t_enter, t_enter + min(dwell, 5.0), data["durationSec"], max_len=th["max_clip_sec"])
                    out.append(Candidate(
                        camera_id=cam["id"], event_type="restricted_zone_entry", start_sec=s, end_sec=e,
                        priority="high",
                        observations=[
                            f"tracked person #{tid} foot point moved from outside to inside restricted polygon {pi + 1} at {_ts(t_enter)}",
                            f"remained inside the polygon for {dwell:.1f}s",
                        ],
                        signals={"enterSec": round(t_enter, 2), "dwellSec": round(dwell, 2), "polygon": pi},
                        track_ids=[tid],
                    ))
    return out


def _flow_series(data: dict, th: dict, bin_sec: float) -> dict[str, np.ndarray]:
    """Per-bin track statistics plus scene-level optical flow (when detect.py recorded it)."""
    fps = data["fps"]
    frames = data["frames"]
    lag = max(1, round(fps * min(1.0, 4 * bin_sec)))
    lag_sec = lag / fps
    n = int(math.ceil(data["durationSec"] / bin_sec))
    out = {k: np.zeros(n) for k in ("count", "speed", "coherence", "direction", "moving_frac",
                                    "flow_mag", "flow_align", "flow_dir", "flow_moving")}
    buckets: dict[int, list] = defaultdict(list)
    for i in range(len(frames)):
        prev = {b["id"]: b["c"] for b in frames[i - lag]["boxes"]} if i >= lag else {}
        vels = [
            np.subtract(b["c"], prev[b["id"]]) / lag_sec / max(1e-3, b["box"][3] - b["box"][1])
            for b in frames[i]["boxes"] if b["id"] in prev
        ]
        buckets[min(n - 1, int(frames[i]["t"] / bin_sec))].append((len(frames[i]["boxes"]), vels, frames[i].get("flow")))
    for s in range(n):
        rows = buckets.get(s, [])
        if not rows:
            continue
        out["count"][s] = np.mean([r[0] for r in rows])
        flows = [r[2] for r in rows if r[2]]
        if flows:
            out["flow_mag"][s] = np.mean([f["mag"] for f in flows])
            out["flow_moving"][s] = np.mean([f["movingFrac"] for f in flows])
            # alignment over a handful of moving pixels is noise, not collective motion
            out["flow_align"][s] = np.mean([f["align"] if f["movingFrac"] >= 0.05 else 0.0 for f in flows])
            out["flow_dir"][s] = np.mean([f["dir"] for f in flows])
        vels = [v for r in rows for v in r[1]]
        if not vels:
            continue
        v = np.array(vels)
        sp = np.linalg.norm(v, axis=1)
        out["speed"][s] = sp.mean()
        moving = v[sp > th["flow_min_moving_speed"]]
        out["moving_frac"][s] = len(moving) / len(v)
        if len(moving):
            unit = moving / np.linalg.norm(moving, axis=1, keepdims=True)
            mean_unit = unit.mean(axis=0)
            out["coherence"][s] = np.linalg.norm(mean_unit)
            out["direction"][s] = math.degrees(math.atan2(mean_unit[1], mean_unit[0]))
    return out


def _rolling(x: np.ndarray, w: int) -> np.ndarray:
    if w <= 1 or len(x) < w:
        return x
    kernel = np.ones(w) / w
    return np.convolve(x, kernel, mode="same")


def _direction_words(deg: float) -> str:
    """Image-space direction (y grows downward) as words a reviewer can check on screen."""
    names = ["right", "down-right", "down", "down-left", "left", "up-left", "up", "up-right"]
    return names[int(((deg % 360) + 22.5) // 45) % 8] + " in frame"


def _circular_mean(deg: np.ndarray, weights: np.ndarray) -> float | None:
    if weights.sum() <= 0:
        return None
    r = np.radians(deg)
    return math.degrees(math.atan2((np.sin(r) * weights).sum(), (np.cos(r) * weights).sum()))


def _angle_diff(a: np.ndarray, b: float | None) -> np.ndarray:
    if b is None:
        return np.zeros_like(a)
    return np.abs((a - b + 180) % 360 - 180)


def check_crowd_flow(cam: dict, data: dict, th: dict) -> list[Candidate]:
    """Score-based: occupancy, track speed, directional alignment, optical-flow magnitude.

    Track speed/alignment only count when enough tracked people are moving; flow signals only
    count when enough ROI pixels are moving. A bin is flagged when score >= flow_min_score.
    """
    dur = data["durationSec"]
    bin_sec = min(1.0, dur / 20)
    base_sec = min(th["flow_baseline_end_sec"], dur * th["flow_baseline_max_frac"])
    base = int(base_sec / bin_sec)
    if base < 3:
        return []
    w = max(1, round(min(th["flow_window_sec"], base_sec / 2) / bin_sec))
    raw = _flow_series(data, th, bin_sec)
    r = {k: _rolling(v, w) for k, v in raw.items() if k not in ("direction", "flow_dir")}
    bl = slice(1, base)  # bin 0 has no velocities yet

    def z(x: np.ndarray) -> np.ndarray:
        mu, sd = x[bl].mean(), x[bl].std()
        return (x - mu) / max(sd, 1e-3 if mu == 0 else abs(mu) * 0.1)

    base_count = max(1e-6, r["count"][bl].mean())
    base_flow = r["flow_mag"][bl].mean()
    occupancy = r["count"] / base_count
    zs, zh, zfa, zfm = z(r["speed"]), z(r["coherence"]), z(r["flow_align"]), z(r["flow_mag"])
    track_dir_base = _circular_mean(raw["direction"][bl], raw["coherence"][bl])
    flow_dir_base = _circular_mean(raw["flow_dir"][bl], raw["flow_align"][bl])
    track_dchg = _angle_diff(raw["direction"], track_dir_base)
    flow_dchg = _angle_diff(raw["flow_dir"], flow_dir_base)

    tracks_moving = r["moving_frac"] >= th["flow_min_moving_frac"]
    flow_moving = r["flow_moving"] >= th["flow_min_moving_pixels"]
    sig_occ = occupancy >= th["flow_occupancy_ratio"]
    sig_speed = tracks_moving & (zs >= th["flow_speed_z"])
    track_align = tracks_moving & (r["coherence"] >= th["flow_alignment"]) & (
        (zh >= th["flow_alignment_z"]) | (track_dchg >= th["flow_direction_change_deg"]))
    flow_align = flow_moving & (r["flow_align"] >= th["flow_alignment"]) & (
        (zfa >= th["flow_alignment_z"]) | (flow_dchg >= th["flow_direction_change_deg"]))
    sig_align = track_align | flow_align
    sig_flow = flow_moving & (zfm >= th["flow_magnitude_z"]) & (
        r["flow_mag"] >= th["flow_magnitude_ratio"] * max(base_flow, 1e-3))
    score = sig_occ.astype(int) + sig_speed + sig_align + sig_flow

    n = len(score)
    mask = [bool(score[s] >= th["flow_min_score"] and s >= base) for s in range(n)]
    times = [s * bin_sec for s in range(n)]
    out = []
    for start, end in _runs(mask, times, min_len=min(2.0, dur * 0.1)):
        seg = slice(int(round(start / bin_sec)), int(round(end / bin_sec)) + 1)
        peak = start + bin_sec * float(np.argmax(score[seg]))
        # Signals clear their thresholds after the build-up starts; extra lead-in lets the
        # reviewer (and verifier) see the onset, not just the peak.
        s, e = _window(start, end + bin_sec, dur, pre=4, post=2, max_len=th["max_clip_sec"], peak=peak)
        obs = []
        if sig_occ[seg].any():
            obs.append(f"visible person count in the camera region rose to {r['count'][seg].max():.0f} "
                       f"(baseline {base_count:.0f}, x{occupancy[seg].max():.1f})")
        if sig_speed[seg].any():
            obs.append(f"tracked people moved faster than baseline (speed z={zs[seg].max():.1f}, "
                       f"{r['moving_frac'][seg].max():.0%} of tracks moving)")
        if sig_align[seg].any():
            if flow_align[seg].any():
                k = seg.start + int(np.argmax(r["flow_align"][seg]))
                obs.append(f"scene motion became strongly aligned (optical-flow alignment {r['flow_align'][k]:.2f}, "
                           f"heading {_direction_words(raw['flow_dir'][k])})")
            else:
                k = seg.start + int(np.argmax(r["coherence"][seg]))
                obs.append(f"tracked movement became one-directional (coherence {r['coherence'][k]:.2f}, "
                           f"heading {_direction_words(raw['direction'][k])})")
        if sig_flow[seg].any():
            obs.append(f"optical-flow speed rose to ~{r['flow_mag'][seg].max() / max(base_flow, 1e-3):.0f}x baseline "
                       f"({r['flow_moving'][seg].max():.0%} of the region moving)")
        top = int(score[seg].max())
        out.append(Candidate(
            camera_id=cam["id"], event_type="crowd_flow_anomaly", start_sec=s, end_sec=e,
            priority="high" if top >= 3 else "medium", observations=obs,
            signals={
                "score": float(top),
                "occupancyRatio": round(float(occupancy[seg].max()), 2),
                "speedZ": round(float(zs[seg].max()), 2),
                "trackAlignment": round(float(r["coherence"][seg].max()), 2),
                "flowAlignment": round(float(r["flow_align"][seg].max()), 2),
                "flowMagnitudeRatio": round(float(r["flow_mag"][seg].max() / max(base_flow, 1e-3)), 1),
                "baselineSec": round(base_sec, 1),
            },
        ))
    return out


def check_inactivity(cam: dict, data: dict, th: dict) -> list[Candidate]:
    dt = 1.0 / data["fps"]
    win = max(2, round(th["inactive_min_sec"] / dt))
    out = []
    for tid, samples in _by_track(data["frames"]).items():
        if len(samples) < win:
            continue
        heights = np.array([b["box"][3] - b["box"][1] for _, b in samples])
        median_h = float(np.median(heights))
        centers = np.array([b["c"] for _, b in samples])
        low = [
            b["ar"] >= th["inactive_low_aspect"] or (h < th["inactive_low_height_ratio"] * median_h)
            for (_, b), h in zip(samples, heights)
        ]
        still = []
        for i in range(len(samples)):
            lo, hi = max(0, i - win // 2), min(len(samples), i + win // 2 + 1)
            disp = np.linalg.norm(centers[lo:hi] - centers[lo:hi].mean(axis=0), axis=1).max()
            still.append(bool(disp <= th["inactive_max_displacement"]))
        mask = [l and s for l, s in zip(low, still)]
        times = [t for t, _ in samples]
        for start, end in _runs(mask, times, min_len=th["inactive_min_sec"]):
            dwell = end - start
            s, e = _window(start, start + min(dwell, 6.0), data["durationSec"], max_len=th["max_clip_sec"])
            i0 = times.index(start)
            out.append(Candidate(
                camera_id=cam["id"], event_type="person_down_or_inactivity", start_sec=s, end_sec=e,
                priority="high" if dwell >= 10 else "medium",
                observations=[
                    f"tracked person #{tid} in a low position (box aspect {samples[i0][1]['ar']:.2f}) from {_ts(start)}",
                    f"little to no movement for {dwell:.1f}s",
                ],
                signals={"dwellSec": round(dwell, 2), "aspect": samples[i0][1]["ar"]},
                track_ids=[tid],
            ))
    return out


def _iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def check_lying(cam: dict, data: dict, th: dict) -> list[Candidate]:
    """A wide (lying-shaped) detection that stays at one spot for lying_min_sec.

    Links per-frame `lying` boxes (raw wide detections, any confidence) by overlap, since a
    person on the ground rarely keeps one track ID. Tracks files without `lying` (other
    trackers, synthetic seeds) fall back to wide tracked boxes."""
    dt = 1.0 / data["fps"]
    chains: list[list[dict]] = []
    for f in data["frames"]:
        src = f["lying"] if "lying" in f else f["boxes"]
        obs = [{"box": b["box"], "ar": b["ar"], "conf": b.get("conf", 0.0), "id": b.get("id")}
               for b in src if b["ar"] >= th["lying_min_aspect"]]
        open_chains = [c for c in chains if f["t"] - c[-1]["t"] <= th["lying_max_gap_sec"] and c[-1]["t"] < f["t"]]
        for o in sorted(obs, key=lambda o: -o["conf"]):
            o["t"] = f["t"]
            best = max(open_chains, key=lambda c: _iou(c[-1]["box"], o["box"]), default=None)
            if best is not None and _iou(best[-1]["box"], o["box"]) >= th["lying_link_iou"]:
                best.append(o)
                open_chains.remove(best)
            else:
                chains.append([o])

    def dense_segment(c: list[dict]) -> list[dict] | None:
        """First stretch of the chain lasting lying_min_sec without a gap over lying_dense_gap_sec."""
        seg = [c[0]]
        for o in c[1:]:
            if o["t"] - seg[-1]["t"] > th["lying_dense_gap_sec"] + 1e-6:
                if seg[-1]["t"] - seg[0]["t"] >= th["lying_min_sec"]:
                    return seg
                seg = []
            seg.append(o)
        return seg if seg[-1]["t"] - seg[0]["t"] >= th["lying_min_sec"] else None

    out = []
    for c in chains:
        seg = dense_segment(c)
        if seg is None:
            continue
        boxes = np.array([o["box"] for o in seg])
        centers = (boxes[:, :2] + boxes[:, 2:]) / 2
        width = float(np.median(boxes[:, 2] - boxes[:, 0]))
        if np.linalg.norm(centers - centers.mean(axis=0), axis=1).max() > th["lying_max_displacement"] * width:
            continue
        start, end = seg[0]["t"], c[-1]["t"]
        dur = end - start
        aspect = float(np.median([o["ar"] for o in seg]))
        top_conf = max(o["conf"] for o in c)
        tids = sorted({o["id"] for o in c if o["id"] is not None})
        obs = [f"a wide, low person detection (box {aspect:.1f}x wider than tall) stayed at the same spot "
               f"from {_ts(start)}, seen continuously for {seg[-1]['t'] - start:.1f}s, consistent with someone on the ground"]
        if end > seg[-1]["t"]:
            obs.append(f"still detected there on and off until {_ts(end)} ({dur:.1f}s in total) while partly hidden")
        if not tids:
            obs.append(f"detection confidence stayed low (max {top_conf:.2f}), too low to start a track, "
                       f"which is typical for a person lying down or partly covered")
        s, e = _window(start, end, data["durationSec"], pre=2, post=2, max_len=th["max_clip_sec"])
        out.append(Candidate(
            camera_id=cam["id"], event_type="person_down_or_inactivity", start_sec=s, end_sec=e,
            priority="high", observations=obs,
            signals={"lyingSec": round(dur, 2), "aspect": round(aspect, 2), "maxConf": round(top_conf, 3),
                     "lyingFrames": float(len(c))},
            track_ids=tids,
        ))
    return out


def _pose_cues(a: dict, b: dict, conf: float) -> tuple[bool, bool]:
    """(a wrist of one person is inside the other's torso band, someone's wrist is above their shoulders)."""
    def torso_band(p: dict):
        k = p["kp"]
        sh = [k[i][1] for i in (5, 6) if k[i][2] >= conf]
        if not sh:
            return None
        hips = [k[i][1] for i in (11, 12) if k[i][2] >= conf]
        return p["box"][0], p["box"][2], min(sh) - 0.02, max(hips) if hips else p["box"][3]

    def reaches(p: dict, q: dict) -> bool:
        band = torso_band(q)
        if band is None:
            return False
        x1, x2, top, bot = band
        return any(p["kp"][i][2] >= conf and x1 <= p["kp"][i][0] <= x2 and top <= p["kp"][i][1] <= bot
                   for i in (9, 10))

    def raised(p: dict) -> bool:
        k = p["kp"]
        sh = [k[i][1] for i in (5, 6) if k[i][2] >= conf]
        return bool(sh) and any(k[i][2] >= conf and k[i][1] < min(sh) for i in (9, 10))

    return reaches(a, b) or reaches(b, a), raised(a) or raised(b)


def check_altercation(cam: dict, data: dict, th: dict) -> list[Candidate]:
    """Close pair whose box-width jitter (a gesture proxy) rises above both its own calm
    baseline and the similar-depth people around it, for at least alter_min_sec. When the
    tracks carry keypoints, the proposal must also show reach + raised-wrist pose cues."""
    dt = 1.0 / data["fps"]
    win = max(3, round(th["alter_min_sec"] / dt))
    frames = data["frames"]
    by_frame = [{b["id"]: b for b in f["boxes"]} for f in frames]
    # tracks from detect.py with the pose pass on carry `kp`; synthetic/older tracks do not
    has_pose = any("kp" in b for f in frames for b in f["boxes"])
    widths: dict[int, dict[int, float]] = defaultdict(dict)  # track -> frame index -> width
    pair_close: dict[tuple[int, int], set[int]] = defaultdict(set)
    for fi, f in enumerate(frames):
        boxes = f["boxes"]
        for b in boxes:
            widths[b["id"]][fi] = b["box"][2] - b["box"][0]
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                h = ((a["box"][3] - a["box"][1]) + (b["box"][3] - b["box"][1])) / 2
                if h > 0 and math.dist(a["c"], b["c"]) / h <= th["alter_max_dist_heights"]:
                    pair_close[tuple(sorted((a["id"], b["id"])))].add(fi)

    def jitter(tid: int, lo: int, hi: int) -> float | None:
        ws = [widths[tid][k] for k in range(lo, hi) if k in widths[tid]]
        if len(ws) < 4:
            return None
        arr = np.array(ws)
        rel = np.sort(np.abs(np.diff(arr)) / np.maximum(arr[:-1], 1e-4))
        # drop the single largest change: one posture step (standing -> lying) is not a gesture
        return float(rel[:-1].mean())

    def neighbor_jitter(a: int, b: int, lo: int, hi: int) -> float:
        bs = by_frame[(lo + hi) // 2]
        if a not in bs or b not in bs:
            return 0.0
        A, B = bs[a], bs[b]
        h = ((A["box"][3] - A["box"][1]) + (B["box"][3] - B["box"][1])) / 2
        mid = ((A["c"][0] + B["c"][0]) / 2, (A["c"][1] + B["c"][1]) / 2)
        vals = []
        for oid, o in bs.items():
            if oid in (a, b):
                continue
            similar_depth = (o["box"][3] - o["box"][1]) >= th["alter_neighbor_min_height_ratio"] * h
            if similar_depth and math.dist(o["c"], mid) / h <= th["alter_neighbor_radius_heights"]:
                j = jitter(oid, lo, hi)
                if j is not None:
                    vals.append(j)
        return float(np.median(vals)) if len(vals) >= 2 else 0.0

    out = []
    for (a, b), close in pair_close.items():
        if len(close) < win:
            continue
        both = sorted(k for k in widths[a] if k in widths[b])
        # the pair's noise floor: its calmest window anywhere they are both tracked
        calm = []
        for lo in range(both[0], both[-1] - win + 2):
            ja, jb = jitter(a, lo, lo + win), jitter(b, lo, lo + win)
            if ja is not None and jb is not None:
                calm.append((ja + jb) / 2)
        if not calm:
            continue
        floor = max(min(calm), 1e-3)

        idx = sorted(close)
        flagged = [False] * len(frames)
        best = {"pair": 0.0, "nb": 0.0}
        for lo in range(idx[0], idx[-1] - win + 2):
            hi = lo + win
            if sum(1 for k in range(lo, hi) if k in close) < 0.8 * win:
                continue
            ja, jb = jitter(a, lo, hi), jitter(b, lo, hi)
            if ja is None or jb is None:
                continue
            pj = (ja + jb) / 2
            nj = neighbor_jitter(a, b, lo, hi)
            if (pj >= th["alter_min_jitter"] and pj >= th["alter_jitter_vs_self"] * floor
                    and pj >= th["alter_jitter_vs_neighbors"] * nj):
                for k in range(lo, hi):
                    flagged[k] = True
                if pj > best["pair"]:
                    best = {"pair": pj, "nb": nj}

        times = [f["t"] for f in frames]
        for start, end in _runs(flagged, times, min_len=th["alter_min_sec"]):
            s, e = _window(start, end, data["durationSec"], max_len=th["max_clip_sec"])
            # pose cues are counted over the whole review window: contact often comes just
            # before or after the most jittery stretch
            span = [k for k, t in enumerate(times) if s <= t <= e and k in close]
            with_kp = [k for k in span if "kp" in by_frame[k][a] and "kp" in by_frame[k][b]]
            reach = raised = 0
            if has_pose:
                if len(with_kp) < 0.5 * len(span):
                    continue  # too occluded/small to confirm; boxes alone are not enough here
                for k in with_kp:
                    r, up = _pose_cues(by_frame[k][a], by_frame[k][b], th["alter_pose_kp_conf"])
                    reach += r
                    raised += up
                if reach < th["alter_pose_min_reach_frames"] or raised < th["alter_pose_min_raised_frames"]:
                    continue
            ratio_self = best["pair"] / floor
            nb_text = (f", {best['pair'] / best['nb']:.1f}x the people around them" if best["nb"] > 0
                       else ", with no similar-distance people close by")
            obs = [
                f"tracked people #{a} and #{b} stayed within about one body-height of each other "
                f"from {_ts(start)} to {_ts(end)}",
                f"rapid changes in their box widths consistent with arm gestures "
                f"({ratio_self:.0f}x their own calm baseline{nb_text})",
            ]
            if has_pose:
                obs.append(f"keypoints show a wrist inside the other person's torso area in {reach} frames "
                           f"and raised wrists in {raised} frames")
            out.append(Candidate(
                camera_id=cam["id"], event_type="possible_altercation", start_sec=s, end_sec=e,
                priority="medium", observations=obs,
                signals={"closeSec": round(end - start, 2), "gestureJitter": round(best["pair"], 3),
                         "jitterVsSelf": round(ratio_self, 1),
                         "jitterVsNeighbors": round(best["pair"] / best["nb"], 1) if best["nb"] else 0.0,
                         "poseReachFrames": float(reach), "poseRaisedFrames": float(raised)},
                track_ids=[a, b],
            ))
    return out


def merge(cands: list[Candidate], gap: float) -> list[Candidate]:
    out: list[Candidate] = []
    rank = {"low": 0, "medium": 1, "high": 2}
    for c in sorted(cands, key=lambda c: (c.event_type, c.start_sec)):
        prev = out[-1] if out else None
        if prev and prev.event_type == c.event_type and c.start_sec <= prev.end_sec + gap:
            prev.end_sec = max(prev.end_sec, c.end_sec)
            prev.observations += [o for o in c.observations if o not in prev.observations]
            prev.track_ids = sorted(set(prev.track_ids) | set(c.track_ids))
            if rank[c.priority] > rank[prev.priority]:
                prev.priority = c.priority
            for k, v in c.signals.items():
                prev.signals[k] = max(prev.signals.get(k, v), v)
        else:
            out.append(c)
    return sorted(out, key=lambda c: c.start_sec)


@op
def generate_candidates(camera_id: str) -> list[dict]:
    cam = next(c for c in load_config()["cameras"] if c["id"] == camera_id)
    data = json.loads(tracks_path(camera_id).read_text())
    th = {**DEFAULTS, **cam.get("thresholds", {})}
    raw = (
        check_restricted_zone(cam, data, th)
        + check_crowd_flow(cam, data, th)
        + check_inactivity(cam, data, th)
        + check_lying(cam, data, th)
        + check_altercation(cam, data, th)
    )
    cands = merge(raw, th["merge_gap_sec"])
    for c in cands:
        if c.end_sec - c.start_sec > th["max_clip_sec"]:
            c.end_sec = round(c.start_sec + th["max_clip_sec"], 2)
    rows = [asdict(c) for c in cands]
    candidates_path(camera_id).write_text(json.dumps(rows, indent=2))
    summary = ", ".join(f"{c.event_type}@{c.start_sec:.0f}s" for c in cands) or "none"
    print(f"[candidates] {camera_id}: {len(cands)} ({summary})")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera")
    args = ap.parse_args()
    for cam in load_config()["cameras"]:
        if args.camera and cam["id"] != args.camera:
            continue
        if not tracks_path(cam["id"]).exists():
            print(f"[candidates] {cam['id']}: no tracks, run detect.py first")
            continue
        generate_candidates(cam["id"])


if __name__ == "__main__":
    main()
