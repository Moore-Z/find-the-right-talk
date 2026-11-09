#!/usr/bin/env python3
"""Seed Elasticsearch with the talk dataset — stdlib only (urllib).

Usage (Monday, after `docker compose up -d`):
    python3 seed.py                  # -> http://localhost:9200
    python3 seed.py --es http://localhost:9200

Creates index kubecon-talks-2026 from elasticsearch-mapping.json and bulk
indexes data/kubecon-talks-seed.json. Embeddings: sentence-transformers is
used if installed, otherwise talks are indexed without vectors (keyword
search still works; the app falls back to offline ranking if ES is down).

If ES is not reachable this exits non-zero with a clear message — the app
still works offline, so seeding is optional for the demo.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED = HERE / "data" / "kubecon-talks-seed.json"
MAPPING = HERE / "elasticsearch-mapping.json"
INDEX = "kubecon-talks-2026"


def _req(es_url, method, path, body=None):
    req = urllib.request.Request(
        f"{es_url.rstrip('/')}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read() or b"{}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--es", default="http://localhost:9200")
    args = ap.parse_args()

    try:
        _req(args.es, "GET", "/")
    except Exception as e:
        print(f"Elasticsearch not reachable at {args.es}: {e}", file=sys.stderr)
        print("Start it first: docker compose up -d (or run the app offline).",
              file=sys.stderr)
        return 1

    talks = json.loads(SEED.read_text())["talks"]
    mapping = json.loads(MAPPING.read_text())
    mapping.pop("notes", None)

    try:
        _req(args.es, "DELETE", f"/{INDEX}")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    _req(args.es, "PUT", f"/{INDEX}", mapping)
    print(f"Created index {INDEX}")

    vecs = [None] * len(talks)
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
        vecs = model.encode([t["title"] + ". " + t["abstract"]
                             for t in talks]).tolist()
        print(f"Embedded {len(talks)} talks (384-dim)")
    except Exception as e:
        print(f"Embeddings skipped ({e}); indexing without vectors.")

    lines = []
    for t, v in zip(talks, vecs):
        doc = dict(t)
        if v is not None:
            doc["embedding"] = v
        lines.append(json.dumps({"index": {"_index": INDEX, "_id": t["id"]}}))
        lines.append(json.dumps(doc))
    req = urllib.request.Request(
        f"{args.es.rstrip('/')}/_bulk?refresh=true",
        data=("\n".join(lines) + "\n").encode(),
        headers={"Content-Type": "application/x-ndjson"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    if result.get("errors"):
        print("Bulk index reported errors:", json.dumps(result)[:500],
              file=sys.stderr)
        return 1
    print(f"Indexed {len(talks)} talks into {INDEX} "
          f"({sum(1 for t in talks if t.get('start_time'))} with verified times)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
