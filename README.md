# Find the Right Talk — minimal skeleton

KubeCon talk recommender for the **Build with Kelsey Hightower** hackathon
(Mon Nov 9, 2026). Direction: **Elasticsearch + Dash0 only** (Radar dropped).

Type an interest → ranked talks (hybrid keyword + vector search in
Elasticsearch) → personal schedule with clash handling → watch-later queue.

**Honesty notes (keep these in the demo):** the seed is **26 talks, not the
full KubeCon programme**; abstracts are short paraphrases, not official
abstracts; talks without a verified time are shown as
"time TBC — recording queue" and are never presented as scheduled.

## Files

| File | What it is |
| --- | --- |
| `app.py` | stdlib-only server (UI + JSON API), port 8000 |
| `search_core.py` | ranking / conflict / schedule logic; ES via urllib |
| `observability.py` | structured JSON logging + Dash0 placeholder |
| `static/index.html` | one-page UI (no external deps) |
| `seed.py` | stdlib-only ES seeder (no pip packages needed) |
| `data/kubecon-talks-seed.json` | 26-talk seed (copy of ../files/) |
| `elasticsearch-mapping.json` | index `kubecon-talks-2026` |
| `docker-compose.yml` | single-node Elasticsearch 8.15 |

Ranking/conflict logic is reused from `../files/seed-and-search.py`
(imported when present, local port as fallback).

## Monday run (in this order)

```bash
cd find-the-right-talk

# 1. Elasticsearch (11:00 first check — do this before anything else)
docker compose up -d
curl http://localhost:9200            # should answer with cluster info

# 2. Seed the index (stdlib only; embeddings if sentence-transformers
#    is installed, otherwise indexes without vectors)
python3 seed.py

# 3. Start the app
python3 app.py                       # http://localhost:8000

# No ES? The app still works: search/schedule fall back to offline
# ranking automatically (badge in the UI says "Offline fallback").
```

## API

- `GET /api/health` — ES reachability, mode, talk count, Dash0 status
- `GET /api/talks` — all 26 seed talks
- `GET /api/conflicts` — verified time clashes (timed talks only)
- `POST /api/search {"interest": "..."}` — ranked talks
- `POST /api/schedule {"interest": "..."}` — schedule + clash-skipped + watch-later

## Demo script (2 min)

1. Persona 1: interest `vLLM GPU scheduling tail latency` → top picks
   "From Routing Weights to Tail Latency" (Mon 10:40), "Kueue, DRA, and WAS"
   (Mon 11:15), "Who's Governing the GPU Lane?" (Tue 11:25).
2. Persona 2: interest `MCP agents authorization` → "Can Your Agent Execute
   Anything? Authorization for Backstage MCP Actions" (Mon 14:05), "MCP
   Without Polling" (Mon 10:40).
3. Clash demo: interest `GPU platform inference` → Tuesday 11:25–11:30,
   three talks overlap; the schedule keeps one ("Who's Governing the GPU
   Lane?") and sends the other two to the watch-later queue.

## Dash0 (Monday TODO)

`observability.py` logs one JSON line per search/schedule to stdout and
`logs/searches.jsonl` (interest, latency, result count, mode). The Dash0
OTel exporter is **not wired yet** — it reads `DASH0_API_KEY` from the
environment and reports its status honestly. Monday: add the OTel exporter
(or Dash0 Agent0/MCP), add traces/logs/metrics to every search, and show a
dashboard/SLO in the demo. Do NOT commit a real API key.

## Still TODO for Monday (per monday-build-plan.md)

- [ ] `docker compose up -d` + `python3 seed.py` on Henry's laptop (first
      check at 11:00; live ES indexing was NOT verified on the build VM —
      no Docker there)
- [ ] Gitar + Dash0 accounts (Henry's — never registered by the agent);
      Gitar must see PRs from the first commit, not one PR at the end
- [ ] Dash0 instrumentation beyond the logging hooks (traces, dashboard/SLO,
      Agent0/MCP fix of a real issue shown in the demo)
- [ ] UI polish + demo rehearsal 16:00–17:00; submit 17:30
