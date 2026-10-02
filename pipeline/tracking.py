"""Standalone ByteTrack over detections from any model.

Ultralytics' `model.track` hides the raw detections once tracking has run, but detect.py
also needs the low-confidence ones (people lying on the ground score below ByteTrack's
new-track threshold). Running detection and ByteTrack separately keeps both.
"""

from __future__ import annotations

import numpy as np


class Detections:
    """The results interface Ultralytics' BYTETracker reads: `conf`, `cls`, `xywh`, boolean indexing."""

    def __init__(self, xyxy: np.ndarray, conf: np.ndarray):
        self.xyxy, self.conf = xyxy, conf
        self.cls = np.zeros(len(conf))
        self.xywh = np.c_[(xyxy[:, :2] + xyxy[:, 2:]) / 2, xyxy[:, 2:] - xyxy[:, :2]] if len(xyxy) else np.zeros((0, 4))

    def __len__(self) -> int:
        return len(self.conf)

    def __getitem__(self, mask):
        return Detections(self.xyxy[mask], self.conf[mask])


def is_bytetrack(config: str) -> bool:
    from ultralytics.utils import YAML
    from ultralytics.utils.checks import check_yaml

    return YAML.load(check_yaml(config)).get("tracker_type") == "bytetrack"


def bytetrack(config: str):
    from ultralytics.trackers.byte_tracker import BYTETracker
    from ultralytics.utils import YAML, IterableSimpleNamespace
    from ultralytics.utils.checks import check_yaml

    cfg = IterableSimpleNamespace(**YAML.load(check_yaml(config)))
    if cfg.tracker_type != "bytetrack":
        raise ValueError(f"standalone tracking supports ByteTrack only, got {cfg.tracker_type}")
    return BYTETracker(cfg)


def update(bt, xyxy: np.ndarray, conf: np.ndarray, frame: np.ndarray) -> list[tuple[np.ndarray, int, float, int]]:
    """Rows of (xyxy, track_id, score, index into the input detections)."""
    out = bt.update(Detections(xyxy, conf), frame)
    return [(row[:4], int(row[4]), float(row[5]), int(row[7])) for row in out]
