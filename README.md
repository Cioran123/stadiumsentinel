# Stadium Sentinel

Searchable, evidence-grounded incident review for multi-camera stadium footage.

YOLO provides person detections and track-level signals, scene-level optical flow captures
collective crowd motion, a verifier (NVIDIA Cosmos Reason, with a Claude fallback) reviews short
candidate clips, the ledger can be mirrored into VAST, and W&B Weave traces and evaluates whether
the system's claims are supported by ground truth.

YOLO is not the crowd-understanding system: in a dense rush, people occlude each other, IDs
switch, and detected counts *drop*. So crowd checks lean on optical flow and a score over
independent signals, and pose runs only on the few tracks a candidate already selected.

Stadium Sentinel does **not** identify emergencies, violence, intent, identity, or medical
conditions. It surfaces observable events and prioritizes footage for human review. All demo
footage is synthetic and labeled as such.

Forked from VITAL (HackPrinceton S26); the healthcare features were removed.

---

## How it fits together

```
footage/CAM_0x/*.mp4 ──assemble.py──▶ storage/videos/CAM_0x.mp4 (+ manifest.json)
                                         │
                       detect.py (YOLO26 + ByteTrack, ROI, optical flow, YOLO-pose skeletons)
                                         │          ──▶ storage/pipeline/CAM_0x.tracks.json
                       candidates.py (4 checks)     ──▶ storage/pipeline/CAM_0x.candidates.json
                                         │
                       pose.py (selected tracks only, person-down / altercation)
                                         │
                       verify.py (Cosmos / Claude)  ──▶ storage/clips/<incident>.mp4
                                         │
                       run_all.py                    ──▶ storage/db/incidents.json  (the ledger)
                                         │
              ┌──────────────────────────┼─────────────────────────┐
        evaluate.py (Weave)        vast_sync.py (VAST)       Next.js app
        storage/pipeline/eval.json  S3 + vastdb tables       Overview / Search / Incident / Venue / Reel
```

The pipeline runs offline ahead of the demo; the app only reads prepared files, so the demo has
no live generation or network dependency.

| Event type | Candidate check (does not decide an incident occurred) |
|---|---|
| `restricted_zone_entry` | a track's foot point moves from outside to inside a restricted polygon |
| `crowd_flow_anomaly` | score ≥ 2 of 4 vs. the first-40s baseline: ROI occupancy ×1.4, faster tracks (≥30% of tracks moving), strongly aligned motion (tracks or optical flow) that changed from baseline, optical-flow speed ≥2× baseline |
| `person_down_or_inactivity` | a track is low (wide box or shrunken height) and nearly still for 6s+; **or** a lying-shaped detection (≥1.2× wider than tall, kept down to 0.05 confidence because people on the ground rarely become tracks) stays at one spot for 2s+; pose adds torso tilt |
| `possible_altercation` | two tracks within ~1 body-height for 3s+ with rapid box-width changes, not inside a packed crowd; pose adds wrist/arm evidence |

Detections are kept only when their foot point is inside the camera's region of interest (`roi`
in `cameras.json`, normalized polygon; default is the full frame minus the overlay banner), and
optical flow is measured only inside it. Draw the ROI around the operational area (queue lanes,
barrier approach) to exclude trees, buildings, reflections, and empty pavement.

All checks run on every camera so normal footage can produce false positives for the verifier to
reject. Thresholds live in `pipeline/candidates.py` (`DEFAULTS`) and can be overridden per camera
with a `thresholds` object in `pipeline/config/cameras.json`.

---

## Setup

```bash
npm install
python3 -m venv .venv
.venv/bin/pip install -r pipeline/requirements.txt
brew install ffmpeg            # ffmpeg + ffprobe on PATH
```

Text overlays are drawn with OpenCV, so an ffmpeg build without `drawtext` is fine.

### Environment (`.env.local`, all optional)

| Variable | Used by | Purpose |
|---|---|---|
| `NVIDIA_API_KEY` | verify.py | Cosmos Reason via `https://integrate.api.nvidia.com/v1`. On the Builders Challenge VM this is filled from `GPU_BEARER_TOKEN` |
| `COSMOS_BASE_URL` | verify.py | override endpoint, e.g. a local NIM/vLLM `http://localhost:8000/v1`. Filled from `COSMOS3_REASON_URL` (with `/v1` appended) |
| `COSMOS_MODEL` | verify.py | default `nvidia/cosmos-reason2-8b`, or `nvidia/cosmos3-nano-reasoner` when `COSMOS3_REASON_URL` is set (check `$COSMOS3_REASON_URL/v1/models`) |
| `COSMOS3_REASON_URL`, `COSMOS3_REASON_MODEL`, `GPU_BEARER_TOKEN` | verify.py | Builders Challenge Cosmos3-Reason. Loaded from `/config/<team>.config` on the VM, or from `.env.local` |
| `COSMOS_FPS`, `COSMOS_REASONING=1` | verify.py | frame sampling; ask for `<think>`/`<answer>` output |
| `ANTHROPIC_API_KEY`, `CLAUDE_MODEL` | verify.py, search | fallback verifier; natural-language query parsing |
| `SENTINEL_VERIFIER` | verify.py | `auto` (default), `cosmos`, `claude`, or `none` |
| `SENTINEL_PROMPT_VERSION` | verify.py | `v1` (default) or `v2`, to compare prompts in W&B |
| `WANDB_API_KEY`, `WEAVE_PROJECT` | pipeline + search | Weave tracing and evaluation (default project `stadium-sentinel`) |
| `VAST_S3_ENDPOINT`, `VAST_ACCESS_KEY`, `VAST_SECRET_KEY` | vast_*.py | VAST cluster access. Filled from `S3_ENDPOINT`, `ACCESS_KEY`, `SECRET_KEY` |
| `VAST_MEDIA_BUCKET`, `VAST_DB_BUCKET`, `VAST_DB_SCHEMA`, `VAST_DB_ENDPOINT` | vast_*.py | defaults `sentinel-media`, `sentinel-db`, `sentinel`. Database bucket and endpoint are filled from `VASTDB_BUCKET` and `VDB_ENDPOINT`. Schema stays `sentinel` so stadium rows are not written into `vss-schema` |
| `INDEX_BACKEND=vast`, `VAST_SEARCH_URL` | search | query VAST through `vast_search.py` instead of the local ledger |
| `SENTINEL_YOLO_MODEL` | detect.py | default `yolo26m.pt` (falls back to `yolo11m.pt`) |
| `SENTINEL_TRACKER` | detect.py | `bytetrack.yaml` (default), `botsort.yaml`, `ocsort.yaml`, `deepocsort.yaml`, ... |
| `SENTINEL_YOLO_IMGSZ`, `SENTINEL_YOLO_CONF`, `SENTINEL_YOLO_IOU` | detect.py | defaults 1280, 0.15, 0.5 |
| `SENTINEL_SAMPLE_FPS`, `SENTINEL_DEVICE` | detect.py | default 5 fps; device auto (cuda, mps, cpu) |
| `SENTINEL_POSE=0`, `SENTINEL_POSE_MODEL` | pose.py, detect.py | disable pose (crop evidence and the display-only skeleton pass); default `yolo26m-pose.pt` |
| `SENTINEL_POSE_SOURCE` | detect.py | skeletons on YOLO tracks: `yolo` (default; YOLO-pose, live-capable) or `rtmo-m` / `rtmo-l` / `rtmo-s` (tiled RTMO, ~40% more skeletons in crowds, ~1s/frame, offline only) |
| `SENTINEL_RTMO_TILE`, `SENTINEL_RTMO_CONF` | rtmo.py, detect.py | RTMO tile size as a fraction of the frame (0 = whole frame only) / score floor; default 0.6 / 0.1 |
| `SENTINEL_POSE_IMGSZ`, `SENTINEL_POSE_CONF` | detect.py | YOLO-pose skeleton pass resolution / confidence; default 1536 / 0.10 |
| `SENTINEL_DETECTOR` | detect.py | tracking detector; default `SENTINEL_YOLO_MODEL`. `rtmo-m` tracks RTMO detections directly (skeleton on every track, but jittery boxes; misses the CAM_03 altercation) |

With no keys at all, everything still runs: incidents stay unverified `candidate`s and search uses
keyword rules.

---

## Preparing the demo

1. **Footage.** Put each camera's generated shots in `footage/CAM_0x/` (sorted by filename), then
   `python pipeline/assemble.py`. Camera zones, restricted polygons (normalized 0–1), and
   ground-truth windows are in `pipeline/config/cameras.json`.
   - No footage yet? `python pipeline/assemble.py --placeholder` writes moving-shape stand-ins and
     `python pipeline/seed_demo.py` writes synthetic tracks matching each scenario, so the UI and
     verifier can be exercised. Replace both with real data before demoing.
2. **Pipeline.** `npm run pipeline` (or `.venv/bin/python pipeline/run_all.py`). Use `--redetect`
   to re-run YOLO, `--camera CAM_04` for one camera, `--verifier none` to skip model calls.
3. **Evaluate.** `npm run eval` writes `storage/pipeline/eval.json` (shown on Overview) and, with
   `WANDB_API_KEY`, logs a `weave.Evaluation`.
4. **VAST and Cosmos (Builders Challenge).** On the workshop VM, `/config/<team>.config` is picked up automatically. Off the VM, copy `S3_ENDPOINT`, `ACCESS_KEY`, `SECRET_KEY`, `VDB_ENDPOINT`, `VASTDB_BUCKET`, `COSMOS3_REASON_URL`, and `GPU_BEARER_TOKEN` into `.env.local`, or point `BUILDERS_CONFIG` at that file. Then:

   ```bash
   python pipeline/vast_sync.py          # videos + incident ledger → team VAST bucket, schema sentinel
   python pipeline/vast_search.py        # local search API over that table
   INDEX_BACKEND=vast npm run dev
   ```

   `npm run pipeline` sends candidate clips to Cosmos3-Reason when `COSMOS3_REASON_URL` is set. Media uploads use bucket `sentinel-media`, not the ingest chunks bucket.
5. **Check.** `npm run doctor`, then `npm run dev`.

`python pipeline/selftest.py` checks the four candidate checks against synthetic tracks
(no YOLO or video needed).

**Tuning detection.** Don't assume the default tracker is best for your footage:
`python pipeline/compare_trackers.py --camera CAM_01` runs model × tracker × confidence
combinations and reports detections per frame, ID churn (tracks per visible person), median track
life, and persistence, without writing anything. Apply the winner with `SENTINEL_TRACKER` /
`SENTINEL_YOLO_CONF` / `SENTINEL_YOLO_MODEL`.

**Demo wording.** Say "YOLO provides person detections and track-level signals, while
scene-level motion analysis captures collective crowd behavior; Cosmos verifies the resulting
candidate clips." Don't say YOLO tracks the crowd's body positions.

---

## App

- **Overview**: six camera tiles (synthetic label, index status, latest incident) and the
  evaluation panel.
- **Incident Search**: natural-language queries become filters (event type, zone, priority,
  verification status). Unsupported asks (weapons, identity, intent, medical) return a grounded
  "no supported incident found".
- **Incident detail**: player opens 5s before the span, with YOLO boxes and the restricted polygon
  overlaid, a ground-truth vs. detection timeline, the verifier's decision and observable evidence,
  the candidate signals, the exact clip sent to the verifier, and source metadata.
- **Venue**: a zone diagram shaded by incident count; click a zone to search it.
- **Review Reel**: concatenates verifier-kept spans only, each with a lower third showing camera,
  zone, source timestamp, event type, and inclusion reason, and links back to the source.

## Safeguards

Synthetic clips only, fictional venue, no face recognition or identity matching, no intent,
criminality, or medical inference, "possible" / "review recommended" language throughout, and a
human operator in the loop for every result.
