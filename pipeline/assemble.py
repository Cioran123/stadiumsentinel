"""Assemble generated shots into one ~2-minute recording per camera.

Shots are read from footage/<CAMERA_ID>/*.mp4 in filename order (e.g. 01_baseline.mp4,
02_buildup.mp4, ...). Every shot is normalized to 1280x720 @ 30 fps, concatenated, and the
camera/zone/timecode overlay is burned in:

    STADIUM SENTINEL | VENUE A | CAM_01 | NORTH GATE | 00:57

Writes storage/videos/<videoFile> and storage/videos/manifest.json (synthetic labels,
actual durations, and ground-truth windows).

Usage:
    python pipeline/assemble.py                 # all cameras with footage
    python pipeline/assemble.py --camera CAM_04
    python pipeline/assemble.py --placeholder   # moving-shape stand-ins for UI work (no people)
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import cv2
import numpy as np

from media import TARGET_FPS, TARGET_H, TARGET_W, VideoWriter, draw_banner, mmss, probe_duration, require, run
from schema import ROOT, VIDEOS_DIR, load_config

FOOTAGE_DIR = ROOT / "footage"


def overlay_text(venue_label: str, cam: dict, t: float) -> str:
    return f"STADIUM SENTINEL | {venue_label} | {cam['id']} | {cam['zone'].upper()} | {mmss(t)}"


def concat_shots(shots: list[Path], out: Path) -> None:
    norm = (
        f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=decrease,"
        f"pad={TARGET_W}:{TARGET_H}:(ow-iw)/2:(oh-ih)/2,fps={TARGET_FPS},setsar=1,format=yuv420p"
    )
    inputs: list[str] = []
    chains = []
    for i, shot in enumerate(shots):
        inputs += ["-i", str(shot)]
        chains.append(f"[{i}:v]{norm}[v{i}]")
    graph = ";".join(chains) + ";" + "".join(f"[v{i}]" for i in range(len(shots))) + f"concat=n={len(shots)}:v=1:a=0[out]"
    run([require("ffmpeg"), "-y", *inputs, "-filter_complex", graph, "-map", "[out]",
         "-c:v", "libx264", "-preset", "veryfast", "-an", str(out)])


def burn_overlay(src: Path, out: Path, venue_label: str, cam: dict) -> None:
    cap = cv2.VideoCapture(str(src))
    fps = cap.get(cv2.CAP_PROP_FPS) or TARGET_FPS
    writer = VideoWriter(out, TARGET_W, TARGET_H, fps)
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        draw_banner(frame, overlay_text(venue_label, cam, i / fps))
        writer.write(frame)
        i += 1
    cap.release()
    writer.close()


def make_placeholder(out: Path, venue_label: str, cam: dict, seconds: float) -> None:
    """Moving shapes on a dark floor; lets the UI run before real footage exists."""
    rng = np.random.default_rng(sum(map(ord, cam["id"])))
    n = 14
    pos = rng.uniform([0, 0.3], [1, 1], size=(n, 2))
    vel = rng.normal(0, 0.002, size=(n, 2))
    writer = VideoWriter(out, TARGET_W, TARGET_H, TARGET_FPS)
    gt = cam["groundTruth"]
    for i in range(int(seconds * TARGET_FPS)):
        t = i / TARGET_FPS
        frame = np.full((TARGET_H, TARGET_W, 3), 38, dtype=np.uint8)
        for poly in cam.get("restrictedPolygons", []):
            pts = (np.array(poly) * [TARGET_W, TARGET_H]).astype(np.int32)
            cv2.polylines(frame, [pts], True, (40, 40, 160), 2)
        surge = gt["startSec"] <= t <= gt["endSec"]
        pos += vel * (4 if surge else 1)
        pos %= 1.0
        for x, y in pos:
            cv2.circle(frame, (int(x * TARGET_W), int(y * TARGET_H)), 12, (150, 150, 150), -1)
        draw_banner(frame, overlay_text(venue_label, cam, t))
        draw_banner(frame, "PLACEHOLDER - replace with assembled synthetic footage", top=False, scale=0.5)
        writer.write(frame)
    writer.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera")
    ap.add_argument("--placeholder", action="store_true")
    args = ap.parse_args()

    config = load_config()
    venue_label = config["venueId"].replace("_", " ")
    manifest_path = VIDEOS_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"cameras": {}}

    for cam in config["cameras"]:
        if args.camera and cam["id"] != args.camera:
            continue
        out = VIDEOS_DIR / cam["videoFile"]
        if args.placeholder:
            make_placeholder(out, venue_label, cam, cam["durationSec"])
            shots_used: list[str] = []
            source = "placeholder"
        else:
            shots = sorted((FOOTAGE_DIR / cam["id"]).glob("*.mp4"))
            if not shots:
                print(f"[assemble] {cam['id']}: no shots in footage/{cam['id']}/, skipping")
                continue
            with tempfile.TemporaryDirectory() as tmp:
                joined = Path(tmp) / "joined.mp4"
                concat_shots(shots, joined)
                burn_overlay(joined, out, venue_label, cam)
            shots_used = [s.name for s in shots]
            source = cam["sourceType"]

        duration = probe_duration(out)
        manifest["cameras"][cam["id"]] = {
            "file": cam["videoFile"],
            "zone": cam["zone"],
            "sourceType": source,
            "synthetic": True,
            "shots": shots_used,
            "durationSec": round(duration, 2),
            "groundTruth": cam["groundTruth"],
        }
        flag = "" if abs(duration - cam["durationSec"]) < 2 else f" (config says {cam['durationSec']}s)"
        print(f"[assemble] {cam['id']}: {out.name} {duration:.1f}s{flag}")

    manifest_path.write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
