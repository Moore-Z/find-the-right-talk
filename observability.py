"""Observability hooks for "Find the Right Talk".

Every search/schedule call logs one structured JSON line (stdout + logs file)
with interest, latency, result count and search mode (elasticsearch/offline).

Dash0: this module is the integration point. It reads DASH0_API_KEY from the
environment and, when present, records that a Dash0 OTel exporter SHOULD be
wired here — but no exporter is configured yet (Monday TODO: add
opentelemetry-sdk + Dash0 OTLP endpoint, or use Dash0's Agent0/MCP).
No keys or tokens are invented or stored here; do NOT commit a real key.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG_FILE = HERE / "logs" / "searches.jsonl"

_DASH0_KEY = os.environ.get("DASH0_API_KEY")
_DASH0_NOTED = False


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def dash0_status():
    """Honest placeholder state for the Dash0 track."""
    if _DASH0_KEY:
        return ("configured-key-present",
                "DASH0_API_KEY is set, but the OTel exporter is NOT wired yet — "
                "Monday TODO: add opentelemetry OTLP exporter to Dash0.")
    return ("not-configured",
            "No DASH0_API_KEY in env — Dash0 export disabled by default. "
            "Set DASH0_API_KEY and wire the OTel exporter on Monday.")


def log_event(event, **fields):
    """One structured JSON line per event: stdout + logs/searches.jsonl."""
    global _DASH0_NOTED
    record = {"ts": _utcnow(), "event": event, **fields}
    line = json.dumps(record, ensure_ascii=False)
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a") as f:
            f.write(line + "\n")
    except Exception as e:
        print(f"observability: could not write log file: {e}", file=sys.stderr)
    if not _DASH0_NOTED:
        _DASH0_NOTED = True
        status, note = dash0_status()
        print(json.dumps({"ts": _utcnow(), "event": "dash0_status",
                          "status": status, "note": note}, ensure_ascii=False),
              flush=True)
    return record


def timed(event, fn, **fields):
    """Run fn(), log its latency, return fn()'s result."""
    start = time.monotonic()
    try:
        result = fn()
        log_event(event, latency_ms=round((time.monotonic() - start) * 1000, 1),
                  ok=True, **fields)
        return result
    except Exception as e:
        log_event(event, latency_ms=round((time.monotonic() - start) * 1000, 1),
                  ok=False, error=str(e), **fields)
        raise
