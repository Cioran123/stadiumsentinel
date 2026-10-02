"""Person detection with pose + multi-object tracking + scene-level optical flow.

Tracks come from YOLO + ByteTrack. Skeletons come from a separate frame-wide YOLO-pose pass
matched onto the tracks, which is fast enough for a live stream. SENTINEL_POSE_SOURCE=rtmo-m
uses tiled RTMO (pipeline/rtmo.py) instead, with YOLO-pose filling tracks RTMO did not match:
~40% more skeletons in these crowds, but ~1s per frame, so offline only. `--model rtmo-m`
tracks RTMO detections directly; every track then has a skeleton, but RTMO boxes are less
stable frame to frame, which breaks the box-jitter altercation check (CAM_03 is missed).

Individual tracks are unreliable in dense crowds (occlusion, ID switches, motion blur), so
each sampled frame also records dense optical flow (Farneback) inside the camera's region
of interest. Crowd-flow checks use flow for collective motion and tracks for local signals.

Writes storage/pipeline/<CAM>.tracks.json:

    {"cameraId": "CAM_01", "fps": 5.0, "width": 1280, "height": 720, "durationSec": 120.0,
     "model": "yolo26m.pt", "tracker": "bytetrack.yaml",
     "frames": [{"t": 0.2,
                 "boxes": [{"id": 3, "box": [x1, y1, x2, y2], "c": [cx, cy], "ar": 0.42, "conf": 0.81,
                            "kp": [[x, y, conf], ...17 COCO keypoints]}],
                 "flow": {"mag": 0.03, "align": 0.71, "dir": -80.0, "movingFrac": 0.4},
                 "lying": [{"box": [x1, y1, x2, y2], "ar": 1.6, "conf": 0.08}]}]}

Boxes/centers are normalized 0..1; `ar` is box width / height in pixels. Flow `mag` is the
mean speed in frame-widths per second over ROI pixels; `align` is the length of the mean unit
flow vector over moving pixels (1 = everyone moving the same way); `dir` is in degrees
(image coordinates, -90 = up the frame).

`kp` (normalized) comes from the pose pass matched to tracked boxes by IoU (or from RTMO
directly with `--model rtmo-m`); boxes with no matching skeleton omit it. Frame-wide keypoints are unreliable in dense crowds, so no
check reads them scene-wide: the altercation check only consults them for pairs its box rule
already proposed (wrist-into-torso reach + raised wrists), and pose.py re-runs pose on crops
for evidence text. SENTINEL_POSE=0 skips the YOLO pose pass (RTMO always has keypoints).

`lying` holds every raw wide detection (width >= 1.2x height) down to SENTINEL_LYING_CONF
(default 0.05), with the ID of the track it overlaps, if any: a person on the ground often
scores too low to start a ByteTrack track, and when they are tracked the smoothed track box
lags their change of shape. candidates.py links these across frames by position. Only
written when the tracker is ByteTrack (detection and tracking then run as separate steps).

Only boxes whose foot point is inside the camera ROI are kept. Set `roi` in cameras.json
(normalized polygon); the default is the full frame minus the burned-in overlay banner.

Usage:
    python pipeline/detect.py [--camera CAM_01] [--model yolo26m.pt|rtmo-m] [--tracker bytetrack.yaml]
"""

from __future__ import annotations

import argparse
import json
import math
import os

import cv2
import numpy as np
from shapely.geometry import Point, Polygon

import pose
import rtmo
import tracking
from schema import VIDEOS_DIR, load_config, tracks_path, weights
from tracing import op

SAMPLE_FPS = float(os.environ.get("SENTINEL_SAMPLE_FPS", "5"))
YOLO_MODEL = os.environ.get("SENTINEL_YOLO_MODEL", "yolo26m.pt")
DEFAULT_MODEL = os.environ.get("SENTINEL_DETECTOR", YOLO_MODEL)
FALLBACK_MODEL = "yolo11m.pt"
# Skeleton source for the frame-wide pose pass on YOLO tracks: an RTMO size or "yolo" (pose.POSE_MODEL).
POSE_SOURCE = os.environ.get("SENTINEL_POSE_SOURCE", "yolo")
# RTMO detection score floor; ByteTrack's own thresholds decide what becomes a track.
RTMO_CONF = float(os.environ.get("SENTINEL_RTMO_CONF", "0.1"))
# A person lying on the ground scores well below ByteTrack's new-track threshold (0.25), so
# wide detections down to this confidence are kept per frame as `lying`, outside tracking.
LYING_CONF = float(os.environ.get("SENTINEL_LYING_CONF", "0.05"))
# An elevated camera foreshortens someone lying toward it, so this is lower than a flat 2:1.
LYING_ASPECT = 1.2
LYING_TRACKED_IOU = 0.5
DEFAULT_TRACKER = os.environ.get("SENTINEL_TRACKER", "bytetrack.yaml")
# Dense crowds need a medium model, higher input resolution, and a lower confidence floor so
# the tracker sees tentative detections; temporal persistence and ROI rules filter them later.
IMGSZ = int(os.environ.get("SENTINEL_YOLO_IMGSZ", "1280"))
CONF = float(os.environ.get("SENTINEL_YOLO_CONF", "0.15"))
IOU = float(os.environ.get("SENTINEL_YOLO_IOU", "0.5"))

DEFAULT_ROI = [[0.0, 0.06], [1.0, 0.06], [1.0, 1.0], [0.0, 1.0]]  # skip the overlay banner
FLOW_WIDTH = 480
FLOW_MOVING = 0.03  # frame-widths per second
POSE_MATCH_IOU = 0.4
POSE_IMGSZ = int(os.environ.get("SENTINEL_POSE_IMGSZ", "1536"))
POSE_CONF = float(os.environ.get("SENTINEL_POSE_CONF", "0.10"))


def device() -> str | None:
    if os.environ.get("SENTINEL_DEVICE"):
        return os.environ["SENTINEL_DEVICE"]
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return None


def load_model(name: str):
    from ultralytics import YOLO

    try:
        return YOLO(weights(name)), name
    except Exception as err:
        print(f"[detect] could not load {name} ({err}); falling back to {FALLBACK_MODEL}")
        return YOLO(weights(FALLBACK_MODEL)), FALLBACK_MODEL


def roi_mask(roi: list[list[float]], w: int, h: int) -> np.ndarray:
    mask = np.zeros((h, w), dtype=np.uint8)
    pts = (np.array(roi) * [w, h]).astype(np.int32)
    cv2.fillPoly(mask, [pts], 1)
    return mask.astype(bool)


def flow_stats(prev: np.ndarray, cur: np.ndarray, mask: np.ndarray, dt: float) -> dict:
    flow = cv2.calcOpticalFlowFarneback(prev, cur, None, 0.5, 3, 15, 3, 5, 1.2, 0)
    w = prev.shape[1]
    v = flow[mask] / (w * dt)  # frame-widths per second
    mag = np.linalg.norm(v, axis=1)
    moving = v[mag > FLOW_MOVING]
    stats = {"mag": round(float(mag.mean()), 4) if len(mag) else 0.0,
             "movingFrac": round(len(moving) / max(1, len(v)), 3), "align": 0.0, "dir": 0.0}
    if len(moving):
        unit = moving / np.linalg.norm(moving, axis=1, keepdims=True)
        mean = unit.mean(axis=0)
        stats["align"] = round(float(np.linalg.norm(mean)), 3)
        stats["dir"] = round(math.degrees(math.atan2(mean[1], mean[0])), 1)
    return stats


def frame_keypoints(frame: np.ndarray, imgsz: int, conf: float, dev: str | None,
                    rtmo_model=None) -> tuple[np.ndarray, np.ndarray]:
    """Frame-wide pose: (N, 4) person boxes and (N, 17, 3) keypoints, both in pixels."""
    if rtmo_model is not None:
        b, _, k, ks = rtmo.infer(rtmo_model, frame, RTMO_CONF)
        return b, np.concatenate([k, ks[..., None]], axis=-1)
    res = pose._get_model().predict(frame, imgsz=imgsz, conf=conf, iou=IOU, max_det=500,
                                    device=dev, verbose=False)[0]
    if res.keypoints is None or res.boxes is None or len(res.boxes) == 0:
        return np.zeros((0, 4)), np.zeros((0, 17, 3))
    return res.boxes.xyxy.cpu().numpy(), res.keypoints.data.cpu().numpy()


def attach_keypoints(boxes: list[dict], pose_xyxy: np.ndarray, pose_kp: np.ndarray, width: int, height: int) -> None:
    """Greedy one-to-one IoU match of pose detections onto tracked boxes that have no `kp` yet."""
    boxes = [b for b in boxes if "kp" not in b]
    if not boxes or len(pose_xyxy) == 0:
        return
    tb = np.array([b["box"] for b in boxes]) * [width, height, width, height]
    x1 = np.maximum(tb[:, None, 0], pose_xyxy[None, :, 0])
    y1 = np.maximum(tb[:, None, 1], pose_xyxy[None, :, 1])
    x2 = np.minimum(tb[:, None, 2], pose_xyxy[None, :, 2])
    y2 = np.minimum(tb[:, None, 3], pose_xyxy[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area_t = (tb[:, 2] - tb[:, 0]) * (tb[:, 3] - tb[:, 1])
    area_p = (pose_xyxy[:, 2] - pose_xyxy[:, 0]) * (pose_xyxy[:, 3] - pose_xyxy[:, 1])
    iou = inter / np.maximum(area_t[:, None] + area_p[None, :] - inter, 1e-6)
    used_t, used_p = set(), set()
    for flat in np.argsort(-iou, axis=None):
        i, j = divmod(int(flat), iou.shape[1])
        if iou[i, j] < POSE_MATCH_IOU:
            break
        if i in used_t or j in used_p:
            continue
        used_t.add(i)
        used_p.add(j)
        boxes[i]["kp"] = [[round(float(x / width), 4), round(float(y / height), 4), round(float(c), 2)]
                          for x, y, c in pose_kp[j]]


def lying_boxes(dets: list[tuple[np.ndarray, float]], boxes: list[dict], roi_poly: Polygon,
                width: int, height: int) -> list[dict]:
    """Wide raw detections inside the ROI, normalized like `boxes`, with the overlapping track ID.

    Raw boxes rather than track boxes: when someone falls, ByteTrack's smoothed box keeps
    the upright shape for a while even though the detection is already lying-shaped."""
    out = []
    for (x1, y1, x2, y2), c in dets:
        nb = [x1 / width, y1 / height, x2 / width, y2 / height]
        if not roi_poly.contains(Point((nb[0] + nb[2]) / 2, nb[3])):
            continue
        tid = max(boxes, key=lambda b: _iou(nb, b["box"]), default=None)
        out.append({"box": [round(float(v), 4) for v in nb],
                    "ar": round(float((x2 - x1) / max(1e-6, y2 - y1)), 3), "conf": round(c, 3),
                    "id": tid["id"] if tid is not None and _iou(nb, tid["box"]) >= LYING_TRACKED_IOU else None})
    return out


def _iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


@op
def detect_camera(cam: dict, model_name: str = DEFAULT_MODEL, tracker: str = DEFAULT_TRACKER,
                  conf: float | None = None, imgsz: int = IMGSZ, write: bool = True) -> dict:
    src = VIDEOS_DIR / cam["videoFile"]
    if not src.exists():
        raise FileNotFoundError(f"{src} missing; run pipeline/assemble.py first")

    dev = device()
    use_rtmo = model_name in rtmo.URLS
    if use_rtmo and not rtmo.available():
        print(f"[detect] rtmlib not installed; falling back to {YOLO_MODEL}")
        use_rtmo, model_name = False, YOLO_MODEL
    if use_rtmo:
        model, model_used = rtmo.load(model_name, dev), f"{model_name} (tiled {rtmo.TILE})" if rtmo.TILE else model_name
        bt = tracking.bytetrack(tracker)
    else:
        model, model_used = load_model(model_name)
    # ByteTrack runs outside model.track so low-confidence lying detections stay visible;
    # other trackers (BoT-SORT's camera-motion step, OC-SORT, ...) still go through model.track.
    standalone = not use_rtmo and tracking.is_bytetrack(tracker)
    if standalone:
        bt = tracking.bytetrack(tracker)
    if conf is None:
        conf = RTMO_CONF if use_rtmo else CONF
    roi = cam.get("roi") or DEFAULT_ROI
    roi_poly = Polygon(roi)
    cap = cv2.VideoCapture(str(src))
    native_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    stride = max(1, round(native_fps / SAMPLE_FPS))
    dt = stride / native_fps
    flow_h = round(height * FLOW_WIDTH / width)
    mask = roi_mask(roi, FLOW_WIDTH, flow_h)
    with_pose = not use_rtmo and pose.enabled()
    pose_rtmo = None
    pose_used = pose.POSE_MODEL
    if with_pose and POSE_SOURCE in rtmo.URLS:
        if rtmo.available():
            pose_rtmo = rtmo.load(POSE_SOURCE, dev)
            pose_used = (f"{POSE_SOURCE} (tiled {rtmo.TILE})" if rtmo.TILE else POSE_SOURCE) + f" + {pose.POSE_MODEL} fill"
        else:
            print(f"[detect] rtmlib not installed; skeletons from {pose.POSE_MODEL}")

    frames = []
    prev_gray = None
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % stride == 0:
            lying_dets: list[tuple[np.ndarray, float]] = []
            if use_rtmo:
                people = rtmo.track(model, bt, frame, conf)
            elif standalone:
                r = model.predict(frame, classes=[0], imgsz=imgsz, conf=min(conf, LYING_CONF), iou=IOU,
                                  max_det=500, device=dev, verbose=False)[0]
                xyxy, sc = r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy()
                tracked = sc >= conf
                people = [(b, tid, s, None) for b, tid, s, _ in tracking.update(bt, xyxy[tracked], sc[tracked], frame)]
                wide = (xyxy[:, 2] - xyxy[:, 0]) >= LYING_ASPECT * (xyxy[:, 3] - xyxy[:, 1])
                lying_dets = [(b, float(s)) for b, s in zip(xyxy[wide], sc[wide])]
            else:
                result = model.track(frame, persist=True, tracker=tracker, classes=[0], imgsz=imgsz,
                                     conf=conf, iou=IOU, max_det=500, device=dev, verbose=False)[0]
                people = []
                if result.boxes is not None and result.boxes.id is not None:
                    people = list(zip(result.boxes.xyxy.cpu().numpy(), result.boxes.id.cpu().numpy().astype(int),
                                      result.boxes.conf.cpu().numpy(), [None] * len(result.boxes)))
            boxes = []
            for (x1, y1, x2, y2), tid, c, kp in people:
                nx1, ny1, nx2, ny2 = x1 / width, y1 / height, x2 / width, y2 / height
                if not roi_poly.contains(Point((nx1 + nx2) / 2, ny2)):
                    continue
                bw, bh = max(1e-6, nx2 - nx1), max(1e-6, ny2 - ny1)
                box = {
                    "id": int(tid),
                    "box": [round(float(v), 4) for v in (nx1, ny1, nx2, ny2)],
                    "c": [round(float((nx1 + nx2) / 2), 4), round(float((ny1 + ny2) / 2), 4)],
                    "ar": round(float((bw * width) / (bh * height)), 3),
                    "conf": round(float(c), 3),
                }
                if kp is not None:
                    box["kp"] = [[round(float(x / width), 4), round(float(y / height), 4), round(float(s), 2)]
                                 for x, y, s in kp]
                boxes.append(box)
            if with_pose:
                if pose_rtmo is not None:
                    attach_keypoints(boxes, *frame_keypoints(frame, POSE_IMGSZ, POSE_CONF, dev, pose_rtmo), width, height)
                # YOLO-pose fills tracks RTMO left without a skeleton (it matches better in packed crowds)
                if any("kp" not in b for b in boxes):
                    attach_keypoints(boxes, *frame_keypoints(frame, POSE_IMGSZ, POSE_CONF, dev), width, height)
            gray = cv2.cvtColor(cv2.resize(frame, (FLOW_WIDTH, flow_h)), cv2.COLOR_BGR2GRAY)
            flow = flow_stats(prev_gray, gray, mask, dt) if prev_gray is not None else None
            prev_gray = gray
            row = {"t": round(idx / native_fps, 3), "boxes": boxes, "flow": flow}
            if standalone:
                row["lying"] = lying_boxes(lying_dets, boxes, roi_poly, width, height)
            frames.append(row)
        idx += 1
    cap.release()
    # Trackers keep state on the predictor; reset so the next camera starts fresh.
    if not use_rtmo and not standalone and getattr(model, "predictor", None) is not None:
        model.predictor = None

    data = {
        "cameraId": cam["id"],
        "fps": native_fps / stride,
        "width": width,
        "height": height,
        "durationSec": round(idx / native_fps, 2),
        "model": model_used,
        "tracker": tracker,
        "imgsz": 640 if use_rtmo else imgsz,
        "conf": conf,
        "lyingConf": LYING_CONF if standalone else None,
        "poseModel": model_used if use_rtmo else pose_used if with_pose else None,
        "poseImgsz": 640 if (use_rtmo or pose_rtmo) else POSE_IMGSZ if with_pose else None,
        "poseConf": RTMO_CONF if (use_rtmo or pose_rtmo) else POSE_CONF if with_pose else None,
        "roi": roi,
        "frames": frames,
    }
    n_tracks = len({b["id"] for f in frames for b in f["boxes"]})
    if write:
        tracks_path(cam["id"]).write_text(json.dumps(data))
        n_kp = sum(1 for f in frames for b in f["boxes"] if "kp" in b)
        n_boxes = sum(len(f["boxes"]) for f in frames)
        pose_note = f"pose ({data['poseModel']}) on {n_kp}/{n_boxes} boxes" if data["poseModel"] else "pose off"
        print(f"[detect] {cam['id']}: {len(frames)} frames, {n_tracks} tracks ({model_used}, {tracker}, "
              f"imgsz {data['imgsz']}, conf {conf}, device {dev or 'cpu'}), {pose_note}")
    return data


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--tracker", default=DEFAULT_TRACKER)
    args = ap.parse_args()
    for cam in load_config()["cameras"]:
        if args.camera and cam["id"] != args.camera:
            continue
        if not (VIDEOS_DIR / cam["videoFile"]).exists():
            print(f"[detect] {cam['id']}: no video, skipping")
            continue
        detect_camera(cam, args.model, args.tracker)


if __name__ == "__main__":
    main()
