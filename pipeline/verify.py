"""Verify candidate clips with NVIDIA Cosmos Reason (fallback: Claude on sampled frames).

Backend selection (SENTINEL_VERIFIER, default "auto"):
  cosmos  OpenAI-compatible chat API with a base64 mp4 `video_url`.
          COSMOS_BASE_URL (default https://integrate.api.nvidia.com/v1, a local NIM/vLLM
          server such as http://localhost:8000/v1, or the Builders Challenge
          COSMOS3_REASON_URL). COSMOS_MODEL, NVIDIA_API_KEY or GPU_BEARER_TOKEN.
  claude  ANTHROPIC_API_KEY; sends ~8 frames sampled from the clip with the same prompt.
  none    No model call; every candidate stays "candidate" and needs human review.
  auto    cosmos if NVIDIA_API_KEY, GPU_BEARER_TOKEN, COSMOS3_REASON_URL, or a
          non-default COSMOS_BASE_URL is set, else claude if ANTHROPIC_API_KEY is set,
          else none.
"""

from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass, field

import cv2

from media import cut_clip, mmss, sample_frames
from schema import CLIPS_DIR, Candidate, load_env
from tracing import op

DEFAULT_COSMOS_URL = "https://integrate.api.nvidia.com/v1"

LABELS = {
    "crowd_flow_anomaly": "possible crowd-flow anomaly (rush, bottleneck, convergence, or flow reversal)",
    "restricted_zone_entry": "a person entering a restricted / staff-only area",
    "possible_altercation": "a possible non-contact altercation (heated close-range gesturing)",
    "person_down_or_inactivity": "a person down, low to the ground, or motionless for an extended period",
}

SYSTEM_PROMPT = (
    "You review short clips from fixed, elevated security cameras at a fictional stadium. "
    "You help a human operator decide which moments need review. You describe only what is "
    "visible. You never infer intent, identity, criminality, or any medical condition."
)

PROMPTS = {
    "v1": """An automated check flagged this clip as a candidate for: {label}.
Camera {camera} ({zone}), source time {start}-{end}.
Signals from person tracking:
{signals}

Decide whether the clip contains observable evidence supporting that candidate.
Rules:
- Describe only observable behavior (positions, movement, posture, gestures, barriers crossed).
- Do not infer intent, identity, criminality, or medical condition.
- Normal crowd behavior is not an incident: queuing, walking to seats, celebrating, cheering, sitting down normally.
- If the evidence is insufficient or ambiguous, use decision "unclear".

Return ONLY a JSON object, no markdown:
{{"event_type": "{event_type}" or "none",
  "decision": "keep" | "drop" | "unclear",
  "severity": "low" | "medium" | "high",
  "observable_evidence": ["short observable statement", "..."],
  "explanation": "one or two sentences, observable facts only",
  "requires_human_review": true | false}}""",
    "v2": """An automated check flagged this clip as a candidate for: {label}.
Camera {camera} ({zone}), source time {start}-{end}.
Signals from person tracking:
{signals}

First compare the start of the clip with the end: what changed in where people are and how they move?
Then decide whether that change supports the candidate.
Rules:
- Observable behavior only. No intent, identity, criminality, or medical inference.
- Celebrations, cheering, queuing, normal exits, and people sitting down to watch are "drop".
- A restricted-zone entry needs a person visibly crossing a barrier or marked threshold.
- A person-down candidate needs a person visibly low or on the ground for several seconds.
- An altercation candidate needs two people facing each other with repeated, emphatic gestures.
- Use "unclear" whenever you are not confident.

Return ONLY a JSON object, no markdown:
{{"event_type": "{event_type}" or "none",
  "decision": "keep" | "drop" | "unclear",
  "severity": "low" | "medium" | "high",
  "observable_evidence": ["short observable statement", "..."],
  "explanation": "one or two sentences, observable facts only",
  "requires_human_review": true | false}}""",
}

REASONING_SUFFIX = (
    "\n\nAnswer the question in the following format: <think>\nyour reasoning\n</think>\n\n"
    "<answer>\nyour answer\n</answer>."
)


def prompt_version() -> str:
    return os.environ.get("SENTINEL_PROMPT_VERSION", "v1")


@dataclass
class Verdict:
    decision: str  # keep | drop | unclear
    severity: str
    evidence: list[str] = field(default_factory=list)
    explanation: str = ""
    requires_human_review: bool = True
    event_type: str = ""
    verifier: str = "none"
    raw: str = ""


def build_prompt(c: Candidate, cam: dict) -> str:
    text = PROMPTS[prompt_version()].format(
        label=LABELS[c.event_type],
        camera=c.camera_id,
        zone=cam["zone"],
        start=mmss(c.start_sec),
        end=mmss(c.end_sec),
        signals="\n".join(f"- {o}" for o in c.observations),
        event_type=c.event_type,
    )
    return text


def parse_verdict(text: str, verifier: str, fallback_severity: str) -> Verdict:
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    answer = re.search(r"<answer>(.*?)</answer>", cleaned, flags=re.S)
    if answer:
        cleaned = answer.group(1)
    cleaned = re.sub(r"```(?:json)?", "", cleaned)
    match = re.search(r"\{.*\}", cleaned, flags=re.S)
    if not match:
        return Verdict("unclear", fallback_severity, explanation="Verifier returned no JSON.", verifier=verifier, raw=text)
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return Verdict("unclear", fallback_severity, explanation="Verifier returned malformed JSON.", verifier=verifier, raw=text)

    decision = str(obj.get("decision", "")).lower()
    if decision not in ("keep", "drop", "unclear"):
        keep = obj.get("keep")
        decision = "keep" if keep is True else "drop" if keep is False else "unclear"
    severity = str(obj.get("severity", fallback_severity)).lower()
    if severity not in ("low", "medium", "high"):
        severity = fallback_severity
    evidence = [str(e) for e in obj.get("observable_evidence", []) if str(e).strip()]
    return Verdict(
        decision=decision,
        severity=severity,
        evidence=evidence,
        explanation=str(obj.get("explanation", "")).strip(),
        requires_human_review=bool(obj.get("requires_human_review", True)),
        event_type=str(obj.get("event_type", "")),
        verifier=verifier,
        raw=text,
    )


def resolve_backend() -> str:
    load_env()
    choice = os.environ.get("SENTINEL_VERIFIER", "auto")
    if choice != "auto":
        return choice
    if (
        os.environ.get("NVIDIA_API_KEY")
        or os.environ.get("GPU_BEARER_TOKEN")
        or os.environ.get("COSMOS3_REASON_URL")
        or os.environ.get("COSMOS_BASE_URL", DEFAULT_COSMOS_URL) != DEFAULT_COSMOS_URL
    ):
        return "cosmos"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "claude"
    return "none"


def call_cosmos(clip_path, prompt: str) -> tuple[str, str]:
    from openai import OpenAI

    base_url = os.environ.get("COSMOS_BASE_URL", DEFAULT_COSMOS_URL)
    model = os.environ.get("COSMOS_MODEL", "nvidia/cosmos-reason2-8b")
    client = OpenAI(base_url=base_url, api_key=os.environ.get("NVIDIA_API_KEY", "not-used"))
    if os.environ.get("COSMOS_REASONING") == "1":
        prompt += REASONING_SUFFIX
    video_b64 = base64.b64encode(clip_path.read_bytes()).decode()
    request = dict(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": [
                # Cosmos was trained with media before text.
                {"type": "video_url", "video_url": {"url": f"data:video/mp4;base64,{video_b64}"}},
                {"type": "text", "text": prompt},
            ]},
        ],
        max_tokens=2048,
        temperature=0.2,
        top_p=0.95,
    )
    # The public NVIDIA endpoint samples frames from this hint. The Builders
    # Challenge server is only known to work without it.
    if base_url.rstrip("/") == DEFAULT_COSMOS_URL.rstrip("/"):
        request["extra_body"] = {"media_io_kwargs": {"video": {"fps": float(os.environ.get("COSMOS_FPS", "4"))}}}
    resp = client.chat.completions.create(**request)
    return resp.choices[0].message.content or "", f"cosmos:{model}"


def call_claude(clip_path, c: Candidate, prompt: str) -> tuple[str, str]:
    import anthropic

    model = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5")
    frames = sample_frames(clip_path, 0, max(0.5, c.end_sec - c.start_sec), 8)
    content: list[dict] = []
    for i, frame in enumerate(frames):
        h, w = frame.shape[:2]
        if w > 640:
            frame = cv2.resize(frame, (640, int(h * 640 / w)))
        ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            continue
        content.append({"type": "text", "text": f"Frame {i + 1} of {len(frames)}:"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                     "data": base64.b64encode(jpg.tobytes()).decode()}})
    content.append({"type": "text", "text": "These frames are evenly sampled from the clip.\n\n" + prompt})
    client = anthropic.Anthropic()
    resp = client.messages.create(model=model, max_tokens=1024, temperature=0.1, system=SYSTEM_PROMPT,
                                  messages=[{"role": "user", "content": content}])
    text = "".join(b.text for b in resp.content if b.type == "text")
    return text, f"claude:{model}"


def clip_for(incident_id: str):
    return CLIPS_DIR / f"{incident_id}.mp4"


@op
def verify_candidate(c: Candidate, cam: dict, video_path: str, incident_id: str, backend: str) -> Verdict:
    from pathlib import Path

    clip = cut_clip(Path(video_path), c.start_sec, c.end_sec, clip_for(incident_id))
    if backend == "none":
        return Verdict("unclear", c.priority, explanation="No verifier configured; review manually.",
                       verifier="none")
    prompt = build_prompt(c, cam)
    try:
        if backend == "cosmos":
            text, name = call_cosmos(clip, prompt)
        elif backend == "claude":
            text, name = call_claude(clip, c, prompt)
        else:
            raise ValueError(f"unknown verifier backend {backend!r}")
    except Exception as err:  # keep the pipeline going; the incident stays a reviewable candidate
        print(f"[verify] {incident_id}: {backend} failed: {err}")
        return Verdict("unclear", c.priority, explanation=f"Verifier error: {err}", verifier=f"{backend}:error")
    return parse_verdict(text, name, c.priority)
