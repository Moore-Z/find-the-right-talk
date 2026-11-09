#!/usr/bin/env python3
"""Find the Right Talk — minimal skeleton server (stdlib only).

Serves the one-page UI and a small JSON API:

  GET  /                  one-page UI (static/index.html)
  GET  /api/health        {es_reachable, mode, talks}
  GET  /api/talks         all 26 seed talks
  GET  /api/conflicts     verified time clashes (timed talks only)
  POST /api/search        {"interest": "..."} -> ranked talks
  POST /api/schedule      {"interest": "..."} -> schedule + conflicts + watch-later

Search tries Elasticsearch first (localhost:9200, index kubecon-talks-2026,
hybrid keyword + kNN when embeddings are available) and falls back to the
offline ranking in search_core.py when ES is unreachable — the demo never
blocks on ES or a model download.

Run:  python3 app.py            # http://localhost:8000
        python3 app.py --port 8000 --es http://localhost:9200
"""
import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import observability
import search_core

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
TALKS = search_core.load_talks()


def talk_view(t, score=None):
    """Public shape of a talk. Untimed talks are flagged time_tbc=True and
    must be rendered as 'time TBC — recording queue', never as scheduled."""
    v = {
        "id": t["id"],
        "title": t["title"],
        "abstract": t["abstract"],
        "tags": t.get("tags", []),
        "track": t.get("track"),
        "day": t.get("day"),
        "date": t.get("date"),
        "start_time": t.get("start_time"),
        "end_time": t.get("end_time"),
        "room": t.get("room"),
        "speakers": t.get("speakers", []),
        "level": t.get("level"),
        "time_tbc": not bool(t.get("date") and t.get("start_time")),
    }
    if score is not None:
        v["score"] = round(score, 2)
    return v


def _es_mode(es_url):
    return "elasticsearch" if search_core.es_available(es_url) else "offline"


class Handler(BaseHTTPRequestHandler):
    es_url = os.environ.get("ES_URL", search_core.DEFAULT_ES)

    def log_message(self, fmt, *args):  # keep stdout for structured JSON logs
        pass

    # -- helpers ------------------------------------------------------
    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return {}

    # -- routes -------------------------------------------------------
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            page = (STATIC / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            return
        if self.path == "/api/health":
            self._json(200, {
                "status": "ok",
                "talks": len(TALKS),
                "timed_talks": sum(1 for t in TALKS if t.get("start_time")),
                "es_url": self.es_url,
                "es_reachable": search_core.es_available(self.es_url),
                "mode": _es_mode(self.es_url),
                "dash0": observability.dash0_status()[0],
                "seed_note": "26-talk seed, not the full KubeCon programme",
            })
            return
        if self.path == "/api/talks":
            self._json(200, {"talks": [talk_view(t) for t in TALKS]})
            return
        if self.path == "/api/conflicts":
            clashes = search_core.find_conflicts(TALKS)
            self._json(200, {"conflicts": [
                {"date": d, "a": talk_view(a), "b": talk_view(b)}
                for d, a, b in clashes
            ]})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):
        body = self._read_body()
        interest = (body.get("interest") or "").strip()
        if not interest:
            self._json(400, {"error": "interest is required"})
            return

        if self.path == "/api/search":
            def _run():
                return search_core.search(TALKS, interest, self.es_url)
            results, mode = observability.timed(
                "search", _run, interest=interest)
            observability.log_event(
                "search_result", interest=interest, mode=mode,
                result_count=len(results))
            self._json(200, {
                "interest": interest,
                "mode": mode,
                "results": [talk_view(t, s) for s, t in results],
            })
            return

        if self.path == "/api/schedule":
            def _run():
                return search_core.build_schedule(TALKS, interest)
            # build_schedule is offline logic; mode reflects the search path
            mode = _es_mode(self.es_url)
            picked, clash_skipped, watch_later = observability.timed(
                "schedule", _run, interest=interest)
            # Demo narrative: clash-skipped talks go to the recording queue
            # too (they are real talks you watch later), flagged with why.
            watch_later_all = [
                {**talk_view(t), "reason": "time TBC — recording queue"}
                for t in watch_later
            ] + [
                {**talk_view(t), "reason": "clash — watch the recording"}
                for t in clash_skipped
            ]
            observability.log_event(
                "schedule_result", interest=interest, mode=mode,
                scheduled=len(picked), clash_skipped=len(clash_skipped),
                watch_later=len(watch_later_all))
            self._json(200, {
                "interest": interest,
                "mode": mode,
                "schedule": [talk_view(t) for t in picked],
                "clash_skipped": [talk_view(t) for t in clash_skipped],
                "watch_later": watch_later_all,
            })
            return

        self._json(404, {"error": "not found"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--es", default=os.environ.get("ES_URL", search_core.DEFAULT_ES))
    args = ap.parse_args()
    Handler.es_url = args.es
    print(f"Find the Right Talk skeleton — http://localhost:{args.port}", flush=True)
    print(f"Talks loaded: {len(TALKS)} (seed only, not the full programme)", flush=True)
    print(f"Elasticsearch: {args.es} "
          f"({'reachable' if search_core.es_available(args.es) else 'NOT reachable — offline fallback active'})", flush=True)
    print(f"Dash0: {observability.dash0_status()[1]}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
