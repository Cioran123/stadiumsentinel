"""Mirror the corpus and incident ledger into VAST Data.

  1. Upload camera videos and evidence clips to a VAST S3 bucket (boto3, custom endpoint).
  2. (Re)create `cameras` and `incidents` tables in VAST DataBase (vastdb SDK) and insert
     the ledger, so search can run against VAST via pipeline/vast_search.py.

Environment (from .env.local or the shell):
  VAST_S3_ENDPOINT   e.g. http://vip-pool.example.vastdata.com
  VAST_ACCESS_KEY / VAST_SECRET_KEY
  VAST_MEDIA_BUCKET  S3 bucket for videos/clips (default: sentinel-media)
  VAST_DB_ENDPOINT   defaults to VAST_S3_ENDPOINT
  VAST_DB_BUCKET     database bucket (default: sentinel-db)
  VAST_DB_SCHEMA     schema name (default: sentinel)

Requires network access to a VAST cluster (provided by the sponsor at the event).

    python pipeline/vast_sync.py [--skip-media]
"""

from __future__ import annotations

import argparse
import json
import os

from schema import CLIPS_DIR, VIDEOS_DIR, load_config, load_env, read_ledger

INCIDENT_COLUMNS = [
    ("id", "string"), ("videoId", "string"), ("venueId", "string"), ("cameraId", "string"),
    ("zone", "string"), ("zoneId", "string"), ("eventType", "string"), ("startSec", "float64"),
    ("endSec", "float64"), ("priority", "string"), ("verificationStatus", "string"),
    ("requiresHumanReview", "bool"), ("sourceType", "string"), ("verifier", "string"),
    ("promptVersion", "string"), ("cosmosExplanation", "string"), ("evidenceClipUrl", "string"),
    ("mediaKey", "string"), ("createdAt", "string"),
    # nested values stored as JSON text
    ("observations", "string"), ("signalNotes", "string"), ("signals", "string"), ("trackIds", "string"),
]
CAMERA_COLUMNS = [
    ("id", "string"), ("zone", "string"), ("zoneId", "string"), ("videoFile", "string"),
    ("mediaKey", "string"), ("durationSec", "float64"), ("sourceType", "string"), ("scenario", "string"),
]
JSON_FIELDS = {"observations", "signalNotes", "signals", "trackIds"}


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if not value:
        raise SystemExit(f"{name} is not set (see pipeline/vast_sync.py docstring)")
    return value


def arrow_schema(cols):
    import pyarrow as pa

    types = {"string": pa.utf8(), "float64": pa.float64(), "bool": pa.bool_()}
    return pa.schema([(name, types[t]) for name, t in cols])


def upload_media(s3, bucket: str, config: dict) -> None:
    try:
        s3.head_bucket(Bucket=bucket)
    except Exception:
        s3.create_bucket(Bucket=bucket)
    for cam in config["cameras"]:
        path = VIDEOS_DIR / cam["videoFile"]
        if path.exists():
            s3.upload_file(str(path), bucket, f"videos/{cam['videoFile']}", ExtraArgs={"ContentType": "video/mp4"})
            print(f"[vast] uploaded videos/{cam['videoFile']}")
    for clip in sorted(CLIPS_DIR.glob("*.mp4")):
        s3.upload_file(str(clip), bucket, f"clips/{clip.name}", ExtraArgs={"ContentType": "video/mp4"})
    print(f"[vast] uploaded {len(list(CLIPS_DIR.glob('*.mp4')))} clips")


def recreate_table(schema, name: str, columns):
    existing = schema.table(name, fail_if_missing=False)
    if existing is not None:
        existing.drop()
    return schema.create_table(name, arrow_schema(columns))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-media", action="store_true")
    args = ap.parse_args()
    load_env()

    config = load_config()
    ledger = read_ledger()
    zone_of = {c["id"]: c["zoneId"] for c in config["cameras"]}
    s3_endpoint = env("VAST_S3_ENDPOINT")
    access, secret = env("VAST_ACCESS_KEY"), env("VAST_SECRET_KEY")
    media_bucket = os.environ.get("VAST_MEDIA_BUCKET", "sentinel-media")

    if not args.skip_media:
        import boto3

        s3 = boto3.client("s3", endpoint_url=s3_endpoint, aws_access_key_id=access, aws_secret_access_key=secret)
        upload_media(s3, media_bucket, config)

    import pyarrow as pa
    import vastdb

    session = vastdb.connect(endpoint=os.environ.get("VAST_DB_ENDPOINT", s3_endpoint), access=access, secret=secret)
    with session.transaction() as tx:
        bucket = tx.bucket(os.environ.get("VAST_DB_BUCKET", "sentinel-db"))
        schema_name = os.environ.get("VAST_DB_SCHEMA", "sentinel")
        schema = bucket.schema(schema_name, fail_if_missing=False) or bucket.create_schema(schema_name)

        cameras = recreate_table(schema, "cameras", CAMERA_COLUMNS)
        cam_rows = [{
            **{k: c.get(k) for k, _ in CAMERA_COLUMNS},
            "mediaKey": f"s3://{media_bucket}/videos/{c['videoFile']}",
            "durationSec": float(c["durationSec"]),
        } for c in config["cameras"]]
        cameras.insert(pa.Table.from_pylist(cam_rows, schema=arrow_schema(CAMERA_COLUMNS)))

        incidents = recreate_table(schema, "incidents", INCIDENT_COLUMNS)
        inc_rows = []
        for inc in ledger:
            row = {}
            for name, _ in INCIDENT_COLUMNS:
                value = inc.get(name)
                row[name] = json.dumps(value) if name in JSON_FIELDS else value
            row["zoneId"] = zone_of.get(inc["cameraId"], "")
            row["mediaKey"] = f"s3://{media_bucket}/clips/{inc['id']}.mp4"
            inc_rows.append(row)
        if inc_rows:
            incidents.insert(pa.Table.from_pylist(inc_rows, schema=arrow_schema(INCIDENT_COLUMNS)))
    print(f"[vast] wrote {len(cam_rows)} cameras and {len(inc_rows)} incidents to {schema_name}")


if __name__ == "__main__":
    main()
