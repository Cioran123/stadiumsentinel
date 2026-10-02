"""Compare detector / tracker / confidence settings on one camera.

Reports, per combination:
  dets/frame    mean detections kept per sampled frame (higher = fewer missed people)
  tracks        unique track IDs
  ids/person    tracks divided by mean detections (1.0 = no ID churn; higher = fragmentation)
  median life   median track lifespan in seconds
  persistent    share of detections that belong to tracks lasting >= MIN_LIFE seconds
  sec           wall-clock runtime

Nothing is written to storage; pick the winner and set SENTINEL_YOLO_MODEL / SENTINEL_TRACKER
/ SENTINEL_YOLO_CONF (or pass --model/--tracker to run_all.py).

    python pipeline/compare_trackers.py --camera CAM_01
    python pipeline/compare_trackers.py --camera CAM_01 --models yolo26m.pt yolo26s.pt \
        --trackers bytetrack.yaml botsort.yaml ocsort.yaml --confs 0.15 0.2 0.3
"""

from __future__ import annotations

import argparse
import statistics
import time
from collections import defaultdict

from detect import IMGSZ, detect_camera
from schema import load_config


def metrics(data: dict) -> dict:
    frames = data["frames"]
    dt = 1.0 / data["fps"]
    min_life = min(1.5, 0.4 * data["durationSec"])
    seen: dict[int, list[float]] = defaultdict(list)
    for f in frames:
        for b in f["boxes"]:
            seen[b["id"]].append(f["t"])
    lives = {tid: ts[-1] - ts[0] + dt for tid, ts in seen.items()}
    n_det = sum(len(ts) for ts in seen.values())
    mean_det = n_det / max(1, len(frames))
    persistent = sum(len(seen[t]) for t, life in lives.items() if life >= min_life)
    return {
        "dets/frame": round(mean_det, 1),
        "tracks": len(seen),
        "ids/person": round(len(seen) / mean_det, 2) if mean_det else 0.0,
        "median life": round(statistics.median(lives.values()), 2) if lives else 0.0,
        "persistent": round(persistent / n_det, 2) if n_det else 0.0,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", required=True)
    ap.add_argument("--models", nargs="+", default=["yolo26m.pt"])
    ap.add_argument("--trackers", nargs="+", default=["bytetrack.yaml", "botsort.yaml", "ocsort.yaml"])
    ap.add_argument("--confs", nargs="+", type=float, default=[0.15, 0.2, 0.3])
    ap.add_argument("--imgsz", type=int, default=IMGSZ)
    args = ap.parse_args()
    cam = next(c for c in load_config()["cameras"] if c["id"] == args.camera)

    rows = []
    for model in args.models:
        for tracker in args.trackers:
            for conf in args.confs:
                start = time.time()
                data = detect_camera(cam, model, tracker, conf=conf, imgsz=args.imgsz, write=False)
                m = metrics(data)
                m["sec"] = round(time.time() - start, 1)
                rows.append((model, tracker, conf, m))
                print(f"{model:12} {tracker:15} conf {conf:<4} {m}")

    print("\nBest persistence (ties broken by detections per frame):")
    best = max(rows, key=lambda r: (r[3]["persistent"], r[3]["dets/frame"]))
    print(f"  {best[0]} + {best[1]} @ conf {best[2]}: {best[3]}")


if __name__ == "__main__":
    main()
