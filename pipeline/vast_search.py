"""Tiny HTTP search service over the VAST `incidents` table.

The Next.js search route calls this when INDEX_BACKEND=vast (VAST_SEARCH_URL, default
http://127.0.0.1:8765/search). Filters are pushed down to VAST DataBase as predicates.

    POST /search  {"eventTypes": [...], "zoneIds": [...], "priorities": [...], "statuses": [...]}
    -> {"incidents": [Incident, ...]}

    python pipeline/vast_search.py [--port 8765]
"""

from __future__ import annotations

import argparse
import json
import os
from functools import reduce
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from schema import load_env
from vast_sync import JSON_FIELDS, env

FILTER_COLUMNS = {"eventTypes": "eventType", "zoneIds": "zoneId", "priorities": "priority", "statuses": "verificationStatus"}


def connect():
    import vastdb

    load_env()
    return vastdb.connect(
        endpoint=os.environ.get("VAST_DB_ENDPOINT", env("VAST_S3_ENDPOINT")),
        access=env("VAST_ACCESS_KEY"),
        secret=env("VAST_SECRET_KEY"),
    )


def build_predicate(filters: dict):
    from ibis import _

    clauses = []
    for key, column in FILTER_COLUMNS.items():
        values = [v for v in filters.get(key, []) if isinstance(v, str)]
        if values:
            clauses.append(reduce(lambda a, b: a | b, [getattr(_, column) == v for v in values]))
    return reduce(lambda a, b: a & b, clauses) if clauses else None


def search(session, filters: dict) -> list[dict]:
    with session.transaction() as tx:
        table = (tx.bucket(os.environ.get("VAST_DB_BUCKET", "sentinel-db"))
                 .schema(os.environ.get("VAST_DB_SCHEMA", "sentinel"))
                 .table("incidents"))
        predicate = build_predicate(filters)
        reader = table.select(predicate=predicate) if predicate is not None else table.select()
        rows = reader.read_all().to_pylist()
    for row in rows:
        for f in JSON_FIELDS:
            if isinstance(row.get(f), str):
                row[f] = json.loads(row[f])
        row.pop("zoneId", None)
        row.pop("mediaKey", None)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    session = connect()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            if self.path != "/search":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                filters = json.loads(self.rfile.read(length) or b"{}")
                body = json.dumps({"incidents": search(session, filters)}).encode()
                self.send_response(200)
            except Exception as err:
                body = json.dumps({"error": str(err)}).encode()
                self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    print(f"[vast_search] listening on http://127.0.0.1:{args.port}/search")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
