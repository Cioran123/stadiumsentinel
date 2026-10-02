"""Shared schema and paths for the Stadium Sentinel pipeline.

Mirrors `Incident` / `Camera` in src/app/lib/types.ts. Ground truth is only read
from config/cameras.json and is never written into the incident ledger.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "pipeline" / "config" / "cameras.json"
STORAGE = ROOT / "storage"
VIDEOS_DIR = STORAGE / "videos"
CLIPS_DIR = STORAGE / "clips"
PIPELINE_DIR = STORAGE / "pipeline"
DB_DIR = STORAGE / "db"
LEDGER_PATH = DB_DIR / "incidents.json"

for _d in (VIDEOS_DIR, CLIPS_DIR, PIPELINE_DIR, DB_DIR):
    _d.mkdir(parents=True, exist_ok=True)

EventType = Literal[
    "crowd_flow_anomaly",
    "restricted_zone_entry",
    "possible_altercation",
    "person_down_or_inactivity",
]
EVENT_TYPES: tuple[str, ...] = (
    "crowd_flow_anomaly",
    "restricted_zone_entry",
    "possible_altercation",
    "person_down_or_inactivity",
)
Priority = Literal["low", "medium", "high"]
VerificationStatus = Literal["candidate", "kept", "rejected"]


def load_env() -> None:
    """Load KEY=VALUE pairs from .env.local / .env without overriding the environment."""
    for name in (".env.local", ".env"):
        p = ROOT / name
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))
    from builders import apply_builders_env

    apply_builders_env()


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text())


def weights(name: str) -> str:
    """Model weights live at the repo root regardless of cwd (Ultralytics downloads there)."""
    return name if "/" in name else str(ROOT / name)


def tracks_path(camera_id: str) -> Path:
    return PIPELINE_DIR / f"{camera_id}.tracks.json"


def candidates_path(camera_id: str) -> Path:
    return PIPELINE_DIR / f"{camera_id}.candidates.json"


@dataclass
class Candidate:
    camera_id: str
    event_type: str
    start_sec: float
    end_sec: float
    priority: str
    observations: list[str]
    signals: dict[str, float] = field(default_factory=dict)
    track_ids: list[int] = field(default_factory=list)


@dataclass
class Incident:
    id: str
    videoId: str
    venueId: str
    cameraId: str
    zone: str
    eventType: str
    startSec: float
    endSec: float
    priority: str
    observations: list[str]
    sourceType: str
    verificationStatus: str
    requiresHumanReview: bool
    signalNotes: list[str] = field(default_factory=list)
    evidenceClipUrl: Optional[str] = None
    cosmosExplanation: Optional[str] = None
    verifier: Optional[str] = None
    promptVersion: Optional[str] = None
    signals: dict[str, float] = field(default_factory=dict)
    trackIds: list[int] = field(default_factory=list)
    createdAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_json(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


def write_ledger(incidents: list[Incident]) -> None:
    tmp = LEDGER_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps([i.to_json() for i in incidents], indent=2))
    tmp.replace(LEDGER_PATH)


def read_ledger() -> list[dict]:
    if not LEDGER_PATH.exists():
        return []
    return json.loads(LEDGER_PATH.read_text() or "[]")
