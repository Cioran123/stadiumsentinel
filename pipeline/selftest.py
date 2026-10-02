"""Self-test for candidates.py using synthetic tracks (no YOLO, no video).

For each scenario it builds tracks that behave normally outside the ground-truth
window and abnormally inside it, then checks that the matching candidate fires
inside the window and that a calm control camera produces nothing.

    python pipeline/selftest.py
"""

from __future__ import annotations

import math

import numpy as np

import candidates as C

FPS, DUR = 5.0, 120.0


def frames_from(tracks_at, lying_at=None):
    frames = []
    for i in range(int(DUR * FPS)):
        t = round(i / FPS, 3)
        boxes = []
        for tid, (cx, cy, w, h) in tracks_at(t):
            boxes.append({
                "id": tid, "box": [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2],
                "c": [cx, cy], "ar": round((w * 1280) / (h * 720), 3), "conf": 0.9,
            })
        row = {"t": t, "boxes": boxes}
        if lying_at is not None:
            # untracked low-confidence wide detections, as detect.py writes them
            row["lying"] = [{"box": [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2],
                             "ar": round((w * 1280) / (h * 720), 3), "conf": 0.08, "id": None}
                            for cx, cy, w, h in lying_at(t)]
        frames.append(row)
    return {"cameraId": "TEST", "fps": FPS, "width": 1280, "height": 720, "durationSec": DUR, "frames": frames}


rng = np.random.default_rng(0)
WANDER = rng.uniform(0, 2 * math.pi, size=(40, 2))


def wander(tid, t, base_x, base_y, amp=0.004):
    # tiny, uncorrelated jitter around a fixed spot: "normal" standing/queuing
    a, b = WANDER[tid % 40]
    return base_x + amp * math.sin(0.7 * t + a), base_y + amp * math.cos(0.5 * t + b)


def scene_calm(t):
    for tid in range(10):
        x, y = wander(tid, t, 0.1 + 0.08 * tid, 0.7)
        yield tid, (x, y, 0.04, 0.16)


def scene_surge(t, gt=(48, 68)):
    n = 8 if not gt[0] <= t <= gt[1] else 20
    for tid in range(n):
        if gt[0] <= t <= gt[1]:
            x = (0.05 + 0.04 * tid + 0.06 * (t - gt[0])) % 1.0
            yield tid, (x, 0.55 + 0.01 * (tid % 5), 0.04, 0.16)
        else:
            x, y = wander(tid, t, 0.1 + 0.1 * tid, 0.6)
            yield tid, (x, y, 0.04, 0.16)


def scene_zone(t, gt=(50, 70)):
    yield from scene_calm(t)
    y = 0.75 if t < gt[0] + 2 else 0.3  # foot point crosses into polygon (y < 0.42)
    yield 99, (0.5, y, 0.04, 0.16)


def scene_down(t, gt=(60, 80)):
    yield from scene_calm(t)
    if gt[0] + 2 <= t <= gt[1]:
        yield 77, (0.6, 0.8, 0.12, 0.06)  # wide, low box, not moving
    else:
        x, y = wander(77, t, 0.6, 0.75, amp=0.03)
        yield 77, (x, y, 0.04, 0.16)


def scene_fall_tracks(t, gt=(55, 61)):
    # person 77 walks, then drops out of tracking when they fall (too low-confidence to track)
    yield from scene_calm(t)
    if t < gt[0]:
        x, y = wander(77, t, 0.6, 0.75, amp=0.03)
        yield 77, (x, y, 0.04, 0.16)


def lying_fall(t, gt=(55, 61)):
    # seen lying for 3s, then only now and then as the crowd covers them
    i = int(round(t * FPS))
    if gt[0] <= t <= gt[0] + 3 or (gt[0] + 3 < t <= gt[1] and i % 5 == 0):
        return [(0.6, 0.8, 0.1, 0.05)]
    return []


def lying_bend(t):
    # wide for 1s only (someone bending down to pick something up)
    return [(0.3, 0.8, 0.08, 0.05)] if 70 <= t <= 71 else []


def scene_argue(t, gt=(42, 62)):
    yield from scene_calm(t)
    if gt[0] + 2 <= t <= gt[1] - 2:
        wobble = 0.012 * (1 if int(t * FPS) % 2 else -1)
        yield 50, (0.45, 0.4, 0.05 + wobble, 0.16)
        yield 51, (0.5, 0.4, 0.05 - wobble, 0.16)
    else:
        yield 50, (0.2, 0.4, 0.05, 0.16)
        yield 51, (0.8, 0.4, 0.05, 0.16)


def run(name, cam, scene, expect, gt, lying=None):
    data = frames_from(scene, lying)
    th = dict(C.DEFAULTS)
    cands = C.merge(
        C.check_restricted_zone(cam, data, th) + C.check_crowd_flow(cam, data, th)
        + C.check_inactivity(cam, data, th) + C.check_lying(cam, data, th)
        + C.check_altercation(cam, data, th),
        th["merge_gap_sec"],
    )
    got = [(c.event_type, c.start_sec, c.end_sec) for c in cands]
    ok = True
    if expect:
        hit = [c for c in cands if c.event_type == expect and c.end_sec >= gt[0] and c.start_sec <= gt[1]]
        ok = bool(hit)
    extra = [g for g in got if g[0] != expect]
    status = "PASS" if ok and not extra else "FAIL"
    print(f"{status} {name}: {got}")
    return status == "PASS"


def main():
    zone_cam = {"id": "TEST", "restrictedPolygons": [[[0, 0], [1, 0], [1, 0.42], [0, 0.42]]]}
    plain = {"id": "TEST"}
    results = [
        run("calm control", zone_cam, scene_calm, None, None),
        run("crowd surge", plain, scene_surge, "crowd_flow_anomaly", (48, 68)),
        run("zone entry", zone_cam, scene_zone, "restricted_zone_entry", (50, 70)),
        run("person down", plain, scene_down, "person_down_or_inactivity", (60, 80)),
        run("fall (untracked, lying)", plain, scene_fall_tracks, "person_down_or_inactivity", (55, 61), lying_fall),
        run("bend 1s (control)", plain, scene_calm, None, None, lying_bend),
        run("altercation", plain, scene_argue, "possible_altercation", (42, 62)),
    ]
    raise SystemExit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
