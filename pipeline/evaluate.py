"""Evaluate the incident ledger against ground truth.

Dataset rows: one per camera scenario (from cameras.json groundTruth) plus the known-normal
segments in cameras.json `normalSegments`. The "model" under evaluation is the ledger
produced by run_all.py; it is read, not re-run.

Scorers:
  temporal_iou      IoU between the best matching incident span and the ground-truth window
  type_match        best match has the scripted event type
  surfaced / kept   matching incident exists and is not rejected / was kept by the verifier
  false_positive    (normal rows) a non-rejected incident overlaps a known-normal segment
  evidence_present  kept incidents carry camera, zone, timestamp, and observable evidence

Always writes storage/pipeline/eval.json (shown on the Overview page). When WANDB_API_KEY is
set, the same dataset and scorers also run as a `weave.Evaluation`.

    python pipeline/evaluate.py
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone

from schema import PIPELINE_DIR, load_config, read_ledger
from tracing import init as init_weave
from verify import prompt_version, resolve_backend

EVAL_PATH = PIPELINE_DIR / "eval.json"


def iou(a0: float, a1: float, b0: float, b1: float) -> float:
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    union = max(a1, b1) - min(a0, b0)
    return inter / union if union > 0 else 0.0


def build_dataset(config: dict) -> list[dict]:
    rows = []
    for cam in config["cameras"]:
        gt = cam["groundTruth"]
        rows.append({"cameraId": cam["id"], "kind": "scenario", "expected": gt["eventType"],
                     "gtStart": gt["startSec"], "gtEnd": gt["endSec"]})
    for seg in config.get("normalSegments", []):
        rows.append({"cameraId": seg["cameraId"], "kind": "normal", "expected": "normal",
                     "gtStart": seg["startSec"], "gtEnd": seg["endSec"]})
    return rows


def predict(ledger: list[dict], cameraId: str, gtStart: float, gtEnd: float, **_: object) -> dict:
    """Best-overlapping incident for this camera/window, or none."""
    best, best_iou = None, 0.0
    for inc in ledger:
        if inc["cameraId"] != cameraId:
            continue
        score = iou(inc["startSec"], inc["endSec"], gtStart, gtEnd)
        if score > best_iou:
            best, best_iou = inc, score
    if best is None:
        return {"eventType": "none", "status": "none", "iou": 0.0, "hasEvidence": False, "incidentId": None}
    has_evidence = bool(best.get("observations")) and all(
        best.get(k) not in (None, "") for k in ("cameraId", "zone", "startSec", "endSec")
    )
    return {"eventType": best["eventType"], "status": best["verificationStatus"], "iou": round(best_iou, 3),
            "hasEvidence": has_evidence, "incidentId": best["id"]}


def score_row(row: dict, output: dict) -> dict:
    if row["kind"] == "normal":
        return {"false_positive": output["status"] in ("kept", "candidate")}
    typed = output["eventType"] == row["expected"]
    return {
        "temporal_iou": output["iou"] if typed else 0.0,
        "type_match": typed,
        "surfaced": typed and output["status"] in ("kept", "candidate"),
        "kept": typed and output["status"] == "kept",
        "evidence_present": output["hasEvidence"] if output["status"] == "kept" else None,
    }


def summarize(rows: list[dict], outputs: list[dict], scores: list[dict]) -> dict:
    scen = [s for r, s in zip(rows, scores) if r["kind"] == "scenario"]
    normal = [s for r, s in zip(rows, scores) if r["kind"] == "normal"]
    ev = [s["evidence_present"] for s in scen if s.get("evidence_present") is not None]

    def rate(xs: list) -> float:
        return round(sum(1 for x in xs if x) / len(xs), 3) if xs else 0.0

    return {
        "detected_rate": rate([s["surfaced"] for s in scen]),
        "kept_rate": rate([s["kept"] for s in scen]),
        "mean_iou": round(sum(s["temporal_iou"] for s in scen) / len(scen), 3) if scen else 0.0,
        "type_match_rate": rate([s["type_match"] for s in scen]),
        "normal_false_positive_rate": rate([s["false_positive"] for s in normal]),
        "evidence_rate": rate(ev),
    }


def run_weave(weave, rows: list[dict], ledger: list[dict]) -> str | None:
    @weave.op()
    def sentinel_ledger(cameraId: str, gtStart: float, gtEnd: float, kind: str, expected: str) -> dict:
        return predict(ledger, cameraId, gtStart, gtEnd)

    @weave.op()
    def temporal_iou(kind: str, expected: str, output: dict) -> dict:
        if kind == "normal":
            return {}
        return {"iou": output["iou"] if output["eventType"] == expected else 0.0}

    @weave.op()
    def type_and_status(kind: str, expected: str, output: dict) -> dict:
        if kind == "normal":
            return {"false_positive": output["status"] in ("kept", "candidate")}
        typed = output["eventType"] == expected
        return {"type_match": typed, "surfaced": typed and output["status"] in ("kept", "candidate"),
                "kept": typed and output["status"] == "kept"}

    @weave.op()
    def evidence_present(output: dict) -> dict:
        return {"evidence_present": output["hasEvidence"]} if output["status"] == "kept" else {}

    dataset = weave.Dataset(name="stadium-sentinel-ground-truth", rows=rows)
    evaluation = weave.Evaluation(
        name=f"sentinel-{prompt_version()}",
        dataset=dataset,
        scorers=[temporal_iou, type_and_status, evidence_present],
    )
    asyncio.run(evaluation.evaluate(sentinel_ledger))
    try:
        client = weave.get_client()
        return f"https://wandb.ai/{client.entity}/{client.project}/weave/evaluations"
    except Exception:
        return None


def main() -> None:
    config = load_config()
    ledger = read_ledger()
    if not ledger:
        raise SystemExit("storage/db/incidents.json is empty; run pipeline/run_all.py first")
    rows = build_dataset(config)
    outputs = [predict(ledger, **r) for r in rows]
    scores = [score_row(r, o) for r, o in zip(rows, outputs)]
    metrics = summarize(rows, outputs, scores)

    verifiers = sorted({i.get("verifier", "none") for i in ledger})
    prompt_versions = sorted({i.get("promptVersion", prompt_version()) for i in ledger})
    weave_url = None
    weave = init_weave()
    if weave is not None:
        weave_url = run_weave(weave, rows, ledger)

    summary = {
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "promptVersion": ",".join(prompt_versions),
        "verifier": ",".join(verifiers) or resolve_backend(),
        "weaveUrl": weave_url or os.environ.get("WEAVE_URL"),
        "metrics": metrics,
        "rows": [
            {"cameraId": r["cameraId"], "expected": r["expected"], "predicted": o["eventType"],
             "iou": o["iou"], "status": o["status"]}
            for r, o in zip(rows, outputs)
        ],
    }
    EVAL_PATH.write_text(json.dumps({k: v for k, v in summary.items() if v is not None}, indent=2))
    print(json.dumps(metrics, indent=2))
    print(f"[evaluate] wrote {EVAL_PATH.relative_to(PIPELINE_DIR.parent.parent)}"
          + (f"; Weave: {weave_url}" if weave_url else "; Weave disabled (no WANDB_API_KEY)"))


if __name__ == "__main__":
    main()
