"""Map VAST Builders Challenge config onto Stadium Sentinel's env names.

The workshop VM exports team settings from /config/<team>.config (S3, VastDB,
Cosmos3-Reason). This process does not use those names. apply_builders_env()
loads that file when it is present, then fills the variables verify.py and
vast_sync.py already read. Existing environment values win.

Stadium rows go in schema `sentinel` inside the team database bucket. They are
not written into `vss-schema`. Media uploads stay in `sentinel-media` so they
do not land in the ingest chunks bucket.
"""

from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_COSMOS_MODEL = "nvidia/cosmos3-nano-reasoner"


def parse_config(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip("'\"")
        if not value or value.startswith("<"):
            continue
        out[key.strip()] = value
    return out


def cosmos_base_url(url: str) -> str:
    """OpenAI-compatible clients expect the /v1 prefix. Challenge URLs omit it."""
    trimmed = url.rstrip("/")
    if trimmed.endswith("/v1"):
        return trimmed
    return trimmed + "/v1"


def apply_builders_env() -> None:
    for path in _config_paths():
        if not path.is_file():
            continue
        for key, value in parse_config(path.read_text()).items():
            os.environ.setdefault(key, value)

    reason = os.environ.get("COSMOS3_REASON_URL", "").strip()
    if reason:
        _set_default("COSMOS_BASE_URL", cosmos_base_url(reason))
        _set_default("COSMOS_MODEL", os.environ.get("COSMOS3_REASON_MODEL", "").strip() or _DEFAULT_COSMOS_MODEL)
        # Workshop bearer belongs to this host, not api.nvidia.com.
        _set_default("NVIDIA_API_KEY", os.environ.get("GPU_BEARER_TOKEN", "").strip())

    team, project = os.environ.get("WANDB_TEAM", "").strip(), os.environ.get("WANDB_PROJECT", "").strip()
    if team and project:
        _set_default("WEAVE_PROJECT", f"{team}/{project}")

    _set_default("VAST_S3_ENDPOINT", os.environ.get("S3_ENDPOINT", "").strip())
    _set_default("VAST_ACCESS_KEY", os.environ.get("ACCESS_KEY", "").strip())
    _set_default("VAST_SECRET_KEY", os.environ.get("SECRET_KEY", "").strip())
    db_endpoint = os.environ.get("VDB_ENDPOINT", "").strip() or os.environ.get("S3_ENDPOINT", "").strip()
    _set_default("VAST_DB_ENDPOINT", db_endpoint)
    _set_default("VAST_DB_BUCKET", os.environ.get("VASTDB_BUCKET", "").strip())


def _config_paths() -> list[Path]:
    paths: list[Path] = []
    explicit = os.environ.get("BUILDERS_CONFIG", "").strip()
    if explicit:
        paths.append(Path(explicit))
    config_dir = Path("/config")
    if config_dir.is_dir():
        found = sorted(p for p in config_dir.glob("*.config") if p.is_file())
        if len(found) == 1:
            paths.append(found[0])
    return paths


def _set_default(key: str, value: str) -> None:
    if value and not os.environ.get(key):
        os.environ[key] = value
