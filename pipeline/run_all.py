"""Run the full pipeline and write the incident ledger (storage/db/incidents.json).

    detect (YOLO + ByteTrack) -> candidates -> verify (Cosmos / Claude) -> ledger

Usage:
    python pipeline/run_all.py                    # all cameras; reuses existing tracks
    python pipeline/run_all.py --camera CAM_04
    python pipeline/run_all.py --redetect         # re-run YOLO even if tracks exist
    python pipeline/run_all.py --verifier none    # skip model verification
"""

from __future__ import annotations

import argparse
import json
import os

import pose
from candidates import generate_candidates
from detect import DEFAULT_MODEL, detect_camera
from schema import CLIPS_DIR, VIDEOS_DIR, Candidate, Incident, load_config, read_ledger, tracks_path, write_ledger
from tracing import op
from verify import prompt_version, resolve_backend, verify_candidate

STATUS = {"keep": "kept", "drop": "rejected", "unclear": "candidate"}


def to_incident(c: Candidate, cam: dict, venue_id: str, incident_id: str, verdict) -> Incident:
    status = STATUS[verdict.decision]
    observations = verdict.evidence if verdict.evidence else list(c.observations)
    return Incident(
        id=incident_id,
        videoId=cam["videoFile"],
        venueId=venue_id,
        cameraId=cam["id"],
        zone=cam["zone"],
        eventType=c.event_type,
        startSec=c.start_sec,
        endSec=c.end_sec,
        priority=verdict.severity if status == "kept" else c.priority,
        observations=observations,
        signalNotes=list(c.observations),
        evidenceClipUrl=f"/api/clips/{incident_id}",
        sourceType=cam["sourceType"],
        verificationStatus=status,
        # Everything except an explicit, confident drop stays in front of a human.
        requiresHumanReview=status != "rejected" or verdict.requires_human_review,
        cosmosExplanation=verdict.explanation or None,
        verifier=verdict.verifier,
        promptVersion=prompt_version(),
        signals={k: float(v) for k, v in c.signals.items()},
        trackIds=c.track_ids,
    )


@op
def process_camera(cam: dict, venue_id: str, backend: str, redetect: bool, model: str) -> list[Incident]:
    video = VIDEOS_DIR / cam["videoFile"]
    if redetect or not tracks_path(cam["id"]).exists():
        detect_camera(cam, model)
    rows = generate_candidates(cam["id"])
    for stale in CLIPS_DIR.glob(f"{cam['id']}-*.mp4"):
        stale.unlink()
    tracks = json.loads(tracks_path(cam["id"]).read_text()) if pose.enabled() and rows else None
    incidents = []
    for row in rows:
        c = Candidate(**row)
        if tracks is not None:
            pose_obs, pose_signals = pose.pose_evidence(str(video), tracks, c)
            c.observations += pose_obs
            c.signals.update(pose_signals)
        incident_id = f"{cam['id']}-{c.event_type}-{int(c.start_sec)}"
        verdict = verify_candidate(c, cam, str(video), incident_id, backend)
        incidents.append(to_incident(c, cam, venue_id, incident_id, verdict))
        print(f"[verify] {incident_id}: {verdict.decision} ({verdict.verifier})")
    return incidents


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera")
    ap.add_argument("--redetect", action="store_true")
    ap.add_argument("--verifier", choices=["auto", "cosmos", "claude", "none"])
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args()
    if args.verifier:
        os.environ["SENTINEL_VERIFIER"] = args.verifier
    backend = resolve_backend()
    print(f"[run_all] verifier backend: {backend}, prompt {prompt_version()}")

    config = load_config()
    processed: set[str] = set()
    incidents: list[Incident] = []
    for cam in config["cameras"]:
        if args.camera and cam["id"] != args.camera:
            continue
        if not (VIDEOS_DIR / cam["videoFile"]).exists():
            print(f"[run_all] {cam['id']}: no video at storage/videos/{cam['videoFile']}, skipping")
            continue
        incidents += process_camera(cam, config["venueId"], backend, args.redetect, args.model)
        processed.add(cam["id"])

    # Keep ledger rows for cameras that were not re-processed this run.
    kept_rows = [r for r in read_ledger() if r["cameraId"] not in processed]
    merged = [Incident(**r) for r in kept_rows] + incidents
    merged.sort(key=lambda i: (i.cameraId, i.startSec))
    write_ledger(merged)
    print(f"[run_all] ledger: {len(merged)} incidents "
          f"({sum(i.verificationStatus == 'kept' for i in merged)} kept)")


if __name__ == "__main__":
    main()
