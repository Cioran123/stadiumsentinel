"""YOLO pose on selected tracks only.

Pose is unreliable across a dense crowd (occluded people get missing or wrong keypoints),
so it never runs frame-wide. After candidates.py selects a person-down or possible-altercation
window, this crops just the candidate's tracks over that window, runs a pose model on the
crops, and adds posture evidence to the candidate. It never creates or removes a candidate;
the verifier still decides.

Env: SENTINEL_POSE=0 disables; SENTINEL_POSE_MODEL (default yolo26m-pose.pt).
"""

from __future__ import annotations

import math
import os
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

from schema import Candidate, weights
from tracing import op

POSE_MODEL = os.environ.get("SENTINEL_POSE_MODEL", "yolo26m-pose.pt")
MAX_FRAMES = 10
KP_CONF = 0.4
L_SH, R_SH, L_WR, R_WR, L_HIP, R_HIP = 5, 6, 9, 10, 11, 12

_model = None


def enabled() -> bool:
    return os.environ.get("SENTINEL_POSE", "1") != "0"


def _get_model():
    global _model
    if _model is None:
        from ultralytics import YOLO

        _model = YOLO(weights(POSE_MODEL))
    return _model


def _crop_keypoints(frame: np.ndarray, box: list[float]) -> np.ndarray | None:
    """Pose of the most confident person inside a padded crop; keypoints as (17, 3) in pixels."""
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = box
    bw, bh = x2 - x1, y2 - y1
    pad_x, pad_y = bw * 0.25, bh * 0.15
    cx1, cy1 = max(0, int((x1 - pad_x) * w)), max(0, int((y1 - pad_y) * h))
    cx2, cy2 = min(w, int((x2 + pad_x) * w)), min(h, int((y2 + pad_y) * h))
    if cx2 - cx1 < 16 or cy2 - cy1 < 16:
        return None
    crop = frame[cy1:cy2, cx1:cx2]
    res = _get_model().predict(crop, imgsz=320, conf=0.2, verbose=False)[0]
    if res.keypoints is None or len(res.keypoints) == 0:
        return None
    best = int(res.boxes.conf.argmax()) if res.boxes is not None and len(res.boxes) else 0
    kp = res.keypoints.data[best].cpu().numpy().copy()  # (17, 3): x, y, conf
    kp[:, 0] += cx1
    kp[:, 1] += cy1
    return kp


def _mid(kp: np.ndarray, a: int, b: int) -> np.ndarray | None:
    pts = [kp[i, :2] for i in (a, b) if kp[i, 2] >= KP_CONF]
    return np.mean(pts, axis=0) if pts else None


def torso_tilt(kp: np.ndarray) -> float | None:
    """Degrees from vertical of the hip->shoulder vector (0 upright, 90 horizontal)."""
    sh, hip = _mid(kp, L_SH, R_SH), _mid(kp, L_HIP, R_HIP)
    if sh is None or hip is None:
        return None
    dx, dy = sh - hip
    return math.degrees(math.atan2(abs(dx), abs(dy) + 1e-6))


def arm_features(kp: np.ndarray) -> tuple[bool, np.ndarray | None]:
    """(a wrist is above the shoulders, wrist positions normalized by shoulder width)."""
    if kp[L_SH, 2] < KP_CONF or kp[R_SH, 2] < KP_CONF:
        return False, None
    sh_y = min(kp[L_SH, 1], kp[R_SH, 1])
    width = max(1.0, float(np.linalg.norm(kp[L_SH, :2] - kp[R_SH, :2])))
    center = (kp[L_SH, :2] + kp[R_SH, :2]) / 2
    raised = any(kp[i, 2] >= KP_CONF and kp[i, 1] < sh_y for i in (L_WR, R_WR))
    wrists = np.array([(kp[i, :2] - center) / width if kp[i, 2] >= KP_CONF else [np.nan, np.nan]
                       for i in (L_WR, R_WR)])
    return raised, wrists


def _samples(tracks: dict, c: Candidate) -> dict[int, list[tuple[float, list[float]]]]:
    by_track: dict[int, list] = defaultdict(list)
    for f in tracks["frames"]:
        if c.start_sec <= f["t"] <= c.end_sec:
            for b in f["boxes"]:
                if b["id"] in c.track_ids:
                    by_track[b["id"]].append((f["t"], b["box"]))
    # consecutive samples from the middle of the window (motion needs neighbors)
    out = {}
    for tid, rows in by_track.items():
        mid = len(rows) // 2
        lo = max(0, mid - MAX_FRAMES // 2)
        out[tid] = rows[lo:lo + MAX_FRAMES]
    return out


@op
def pose_evidence(video: str, tracks: dict, c: Candidate) -> tuple[list[str], dict[str, float]]:
    if c.event_type not in ("person_down_or_inactivity", "possible_altercation") or not c.track_ids:
        return [], {}
    samples = _samples(tracks, c)
    if not samples:
        return [], {}
    cap = cv2.VideoCapture(str(Path(video)))
    kps: dict[int, list[np.ndarray]] = defaultdict(list)
    visible: list[int] = []
    for tid, rows in samples.items():
        for t, box in rows:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            kp = _crop_keypoints(frame, box)
            if kp is not None:
                kps[tid].append(kp)
                visible.append(int((kp[:, 2] >= KP_CONF).sum()))
    cap.release()

    n_frames = sum(len(v) for v in samples.values())
    if not visible or np.mean(visible) < 6:
        return ([f"pose unreliable for the selected track(s): most body keypoints occluded "
                 f"({np.mean(visible) if visible else 0:.0f}/17 visible on average)"],
                {"poseKeypointsVisible": round(float(np.mean(visible)) if visible else 0.0, 1)})

    obs: list[str] = []
    signals: dict[str, float] = {"poseKeypointsVisible": round(float(np.mean(visible)), 1),
                                 "poseFrames": float(n_frames)}
    if c.event_type == "person_down_or_inactivity":
        tilts = [t for kp_list in kps.values() for t in map(torso_tilt, kp_list) if t is not None]
        if tilts:
            tilt = float(np.median(tilts))
            signals["torsoTiltDeg"] = round(tilt, 1)
            posture = ("torso near horizontal" if tilt >= 60 else
                       "torso strongly tilted" if tilt >= 35 else "torso upright")
            obs.append(f"pose on tracked person: {posture} (median {tilt:.0f} deg from vertical "
                       f"over {len(tilts)} frames)")
    else:
        for tid, kp_list in kps.items():
            feats = [arm_features(kp) for kp in kp_list]
            raised = sum(1 for r, _ in feats if r)
            wrists = [w for _, w in feats if w is not None]
            steps = []
            for a, b in zip(wrists, wrists[1:]):
                d = np.linalg.norm(b - a, axis=1)
                d = d[np.isfinite(d)]
                if len(d):
                    steps.append(float(d.mean()))
            if not steps:
                obs.append(f"pose on tracked person #{tid}: wrists not visible in enough consecutive frames "
                           f"to measure gestures")
                continue
            motion = float(np.mean(steps))
            signals[f"track{tid}WristMotion"] = round(motion, 3)
            signals[f"track{tid}ArmsRaisedFrames"] = float(raised)
            obs.append(f"pose on tracked person #{tid}: wrists above shoulders in {raised}/{len(kp_list)} frames, "
                       f"wrist movement {motion:.2f} shoulder-widths per frame")
    return obs, signals
