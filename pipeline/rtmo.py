"""RTMO one-stage multi-person pose (via rtmlib/ONNX) as a person detector for ByteTrack.

RTMO's ONNX export has a fixed 640x640 input, which loses small people in a 1280px frame, so
each frame is also run as four overlapping tiles and the results merged (NMS, then a
score-weighted average of the boxes and skeletons each kept detection absorbed). Tiling produces
partial-body duplicates along tile seams and occasional boxes that span a group of people;
`clean` drops both. Every detection carries its own skeleton, so every track has keypoints.

Env: SENTINEL_RTMO_TILE (tile size as a fraction of the frame, default 0.6; 0 disables tiling).
"""

from __future__ import annotations

import os

import numpy as np

URLS = {
    "rtmo-s": "https://download.openmmlab.com/mmpose/v1/projects/rtmo/onnx_sdk/rtmo-s_8xb32-600e_body7-640x640-dac2bf74_20231211.zip",
    "rtmo-m": "https://download.openmmlab.com/mmpose/v1/projects/rtmo/onnx_sdk/rtmo-m_16xb16-600e_body7-640x640-39e78cc4_20231211.zip",
    "rtmo-l": "https://download.openmmlab.com/mmpose/v1/projects/rtmo/onnx_sdk/rtmo-l_16xb16-600e_body7-640x640-b37118ce_20231211.zip",
}
TILE = float(os.environ.get("SENTINEL_RTMO_TILE", "0.6"))
NMS_IOU = 0.45
FUSE_IOU = 0.55
KP_CONF = 0.4
# A real person's confident joints span most of their box; a box spanning a group does not.
MIN_KP_EXTENT = 0.3
# Share of a box inside a larger kept box above which it is a seam duplicate or body part.
MAX_CONTAINED = 0.7


def available() -> bool:
    try:
        import rtmlib  # noqa: F401
    except ImportError:
        return False
    return True


def load(name: str, dev: str | None):
    from rtmlib import RTMO
    from rtmlib.tools.file import download_checkpoint

    device = dev if dev in ("cuda", "mps") else "cpu"  # rtmlib maps mps to CoreML
    return RTMO(download_checkpoint(URLS[name]), model_input_size=(640, 640), backend="onnxruntime", device=device)


def _raw(model, img: np.ndarray):
    x, ratio = model.preprocess(img)
    det, kp = model.inference(x)
    return det[0, :, :4] / ratio, det[0, :, 4], kp[0, :, :, :2] / ratio, kp[0, :, :, 2]


def _clean(b, s, k, ks):
    keep = []
    for i in range(len(b)):
        pts = k[i][ks[i] >= KP_CONF]
        if len(pts) < 3:
            continue
        extent = np.ptp(pts[:, 0]) * np.ptp(pts[:, 1])
        if extent / max(1e-6, (b[i, 2] - b[i, 0]) * (b[i, 3] - b[i, 1])) >= MIN_KP_EXTENT:
            keep.append(i)
    b, s, k, ks = b[keep], s[keep], k[keep], ks[keep]
    area = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    kept: list[int] = []
    for i in np.argsort(-area):
        inside = False
        for j in kept:
            ix = max(0.0, min(b[i, 2], b[j, 2]) - max(b[i, 0], b[j, 0]))
            iy = max(0.0, min(b[i, 3], b[j, 3]) - max(b[i, 1], b[j, 1]))
            if ix * iy / max(1e-6, area[i]) > MAX_CONTAINED:
                inside = True
                break
        if not inside:
            kept.append(int(i))
    idx = np.array(sorted(kept), dtype=int)
    return b[idx], s[idx], k[idx], ks[idx]


def infer(model, frame: np.ndarray, score_thr: float):
    """People in pixels: boxes (N, 4), scores (N,), keypoints (N, 17, 2), keypoint scores (N, 17)."""
    from rtmlib.tools.object_detection.post_processings import multiclass_nms

    h, w = frame.shape[:2]
    regions = [(0, 0, w, h)]
    if TILE > 0:
        tw, th = int(w * TILE), int(h * TILE)
        regions += [(x, y, x + tw, y + th) for x in (0, w - tw) for y in (0, h - th)]
    parts = []
    for x1, y1, x2, y2 in regions:
        b, s, k, ks = _raw(model, frame[y1:y2, x1:x2])
        m = s >= score_thr
        parts.append((b[m] + [x1, y1, x1, y1], s[m], k[m] + [x1, y1], ks[m]))
    b, s, k, ks = (np.concatenate(p) for p in zip(*parts))
    empty = (np.zeros((0, 4)), np.zeros(0), np.zeros((0, 17, 2)), np.zeros((0, 17)))
    if not len(s):
        return empty
    _, keep = multiclass_nms(b, s[:, None], nms_thr=NMS_IOU, score_thr=score_thr)
    if keep is None:
        return empty
    return _clean(*_fuse(b, s, k, ks, np.asarray(keep)))


def _fuse(b, s, k, ks, keep):
    """Score-weighted average of each kept box with the detections NMS suppressed into it.

    The same person is usually found both in the full frame and in a tile; keeping whichever
    wins NMS makes box widths flicker frame to frame, which the altercation check reads as
    gesturing. Joints are not averaged (that blurs a fast-moving wrist toward the body);
    each joint comes from whichever absorbed detection scored it highest.
    """
    x1 = np.maximum(b[keep, None, 0], b[None, :, 0]); y1 = np.maximum(b[keep, None, 1], b[None, :, 1])
    x2 = np.minimum(b[keep, None, 2], b[None, :, 2]); y2 = np.minimum(b[keep, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    iou = inter / np.maximum(area[keep, None] + area[None, :] - inter, 1e-6)
    out_b, out_k, out_ks = [], [], []
    for row in iou >= FUSE_IOU:
        w = s[row]
        out_b.append((b[row] * w[:, None]).sum(0) / w.sum())
        best = ks[row].argmax(0)  # per joint: a person cut off by a tile edge has low-score joints there
        out_k.append(k[row][best, np.arange(k.shape[1])])
        out_ks.append(ks[row][best, np.arange(k.shape[1])])
    return np.array(out_b), s[keep], np.array(out_k), np.array(out_ks)


def track(model, bt, frame: np.ndarray, score_thr: float):
    """One frame: rows of (xyxy, track_id, score, keypoints (17, 3) in pixels)."""
    import tracking

    b, s, k, ks = infer(model, frame, score_thr)
    return [(xyxy, tid, score, np.c_[k[i], ks[i]]) for xyxy, tid, score, i in tracking.update(bt, b, s, frame)]
