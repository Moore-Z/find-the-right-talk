"""Core search/schedule logic for "Find the Right Talk".

Data: data/kubecon-talks-seed.json — 26 real KubeCon NA 2026 talks (seed, NOT the
full programme). 17 have verified times; 9 have start_time null and must be
shown as "time TBC — recording queue", never as scheduled. Abstracts are short
paraphrases, NOT official abstracts.

Ranking/conflict/schedule logic is reused from ../files/seed-and-search.py
(imported via importlib when available; a local port of the same logic is the
fallback so the demo never depends on that file existing). Elasticsearch access
is stdlib-only (urllib) — no pip packages needed.
"""
import importlib.util
import json
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "kubecon-talks-seed.json"
INDEX = "kubecon-talks-2026"
DEFAULT_ES = "http://localhost:9200"


# ---------------------------------------------------------------- data ----
def load_talks():
    data = json.loads(DATA.read_text())
    return data["talks"]


def minutes(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def talk_end(t):
    """End minute of a timed talk; default 25 min (usual KubeCon breakout)."""
    if t.get("end_time"):
        return minutes(t["end_time"])
    return minutes(t["start_time"]) + 25


def overlaps(a, b):
    return (a.get("date") == b.get("date")
            and a.get("start_time") and b.get("start_time")
            and minutes(b["start_time"]) < talk_end(a)
            and talk_end(b) > minutes(a["start_time"]))


# --------------------------------------- reuse seed-and-search.py ----
def _load_seed_module():
    """Import ../files/seed-and-search.py (hyphenated name) if present."""
    candidates = [
        HERE.parent / "files" / "seed-and-search.py",
        HERE / "seed-and-search.py",
    ]
    for path in candidates:
        if path.exists():
            spec = importlib.util.spec_from_file_location("seed_and_search", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    return None


_SEED_MOD = _load_seed_module()


def find_conflicts(talks):
    """Overlapping pairs among talks with verified date+start_time."""
    if _SEED_MOD is not None:
        return _SEED_MOD.find_conflicts(talks)
    timed = [t for t in talks if t.get("date") and t.get("start_time")]
    by_day = {}
    for t in timed:
        by_day.setdefault(t["date"], []).append(t)
    clashes = []
    for date, day_talks in by_day.items():
        day_talks.sort(key=lambda t: minutes(t["start_time"]))
        for i, a in enumerate(day_talks):
            for b in day_talks[i + 1:]:
                if minutes(b["start_time"]) < talk_end(a):
                    clashes.append((date, a, b))
                else:
                    break
    return clashes


# ------------------------------------------------------------ ranking ----
def _words(interest):
    return set(interest.lower().replace(",", " ").split())


def score_talk(talk, words):
    """Same weighting as seed-and-search.py / the ES multi_match boost:
    title x3, tags x2, abstract x1."""
    return (3 * sum(1 for w in words if w in talk["title"].lower())
            + 2 * sum(1 for w in words if w in " ".join(talk["tags"]).lower())
            + sum(1 for w in words if w in talk["abstract"].lower()))


def rank_talks(talks, interest):
    """[(score, talk)] sorted by score desc; zero-score talks are not
    recommendations."""
    words = _words(interest)
    scored = [(score_talk(t, words), t) for t in talks]
    scored = [(s, t) for s, t in scored if s > 0]
    scored.sort(key=lambda x: -x[0])
    return scored


def build_schedule(talks, interest):
    """(picked, clash_skipped, watch_later).
    picked: highest-scored talks that fit the schedule, in score order.
    clash_skipped: relevant timed talks that overlap a picked talk.
    watch_later: relevant talks with no verified time — recording queue only,
    never a schedule slot."""
    if _SEED_MOD is not None:
        return _SEED_MOD.build_schedule(talks, interest)
    picked, skipped, watch_later = [], [], []
    for _, t in rank_talks(talks, interest):
        if not t.get("date") or not t.get("start_time"):
            watch_later.append(t)
            continue
        if any(overlaps(p, t) for p in picked):
            skipped.append(t)
        else:
            picked.append(t)
    return picked, skipped, watch_later


# ------------------------------------------------------- embeddings ----
_embedding_model = None
_embedding_tried = False


def embed(text):
    """384-dim embedding via sentence-transformers if installed, else None.
    Never blocks the demo on a model download."""
    global _embedding_model, _embedding_tried
    if _embedding_tried:
        model = _embedding_model
    else:
        _embedding_tried = True
        try:
            from sentence_transformers import SentenceTransformer
            _embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
            model = _embedding_model
        except Exception:
            model = None
    if model is None:
        return None
    try:
        return model.encode([text]).tolist()[0]
    except Exception:
        return None


# --------------------------------------------------- elasticsearch ----
_es_available = None
_es_checked_at = None


def es_available(es_url=DEFAULT_ES, cache_secs=5):
    """Cached ES reachability probe (short timeout so a dead ES never stalls)."""
    global _es_available, _es_checked_at
    now = datetime.now().timestamp()
    if _es_available is not None and _es_checked_at and now - _es_checked_at < cache_secs:
        return _es_available
    try:
        req = urllib.request.Request(es_url, method="GET")
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            _es_available = resp.status == 200
    except Exception:
        _es_available = False
    _es_checked_at = now
    return _es_available


def es_search(es_url, interest, size=10, timeout=3):
    """Hybrid ES search: multi_match (title^3 / abstract / tags^2) + kNN on
    `embedding` when an embedding is available, keyword-only otherwise.
    Returns [(score, talk-dict)] or raises on any ES error (caller falls back
    to offline ranking)."""
    vec = embed(interest)
    body = {
        "query": {"multi_match": {
            "query": interest,
            "fields": ["title^3", "abstract", "tags^2"],
        }},
        "size": size,
    }
    if vec is not None:
        body["knn"] = {"field": "embedding", "query_vector": vec,
                       "k": 10, "num_candidates": 50}
    req = urllib.request.Request(
        f"{es_url.rstrip('/')}/{INDEX}/_search",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read())
    out = []
    for hit in payload.get("hits", {}).get("hits", []):
        src = hit.get("_source", {})
        out.append((hit.get("_score", 0), src))
    return out


def search(talks, interest, es_url=DEFAULT_ES):
    """Best-effort search. Returns (results, mode) where mode is
    'elasticsearch' or 'offline' — the demo never blocks on ES."""
    if es_available(es_url):
        try:
            return es_search(es_url, interest), "elasticsearch"
        except Exception:
            pass
    return rank_talks(talks, interest), "offline"
