"""Historique des pronostics sur les matchs déjà joués, gagnés comme perdus.

Chaque match est pronostiqué comme l'agent l'aurait fait AVANT de le jouer : seuls les matchs terminés au moins 3 jours plus tôt
sont connus (même protocole que le backtest). Sans les cotes d'époque, ce sont des probabilités recalculées, pas le journal réel
(le journal réel, lui, se remplit à partir du 23/11/2026). Les 10 premiers matchs de chaque club sont ignorés (notes pas encore fiables).
"""
import numpy as np

from .engine import pipeline, ratings
from .engine.dixon_coles import outcome_probs, over_prob, score_matrices
from .ingest.names import display

MIN_SEEN = 10
BANDS = ((0.0, 0.75), (0.75, 0.80), (0.80, 0.85), (0.85, 0.90), (0.90, 1.01))
SURE = 0.85  # au-dessus, le pari est dit « sûr » (mesuré : environ 9 sur 10 gagnés)
_cache = {}


def compute(model, min_seen=MIN_SEEN):
    h = model["history"]
    preds, _ = ratings.walk(h, lag_days=3)
    keep = [(m, p) for m, p in zip(h, preds) if p[2] >= min_seen]
    mats = score_matrices([p[0] for _, p in keep], [p[1] for _, p in keep])
    probs = outcome_probs(mats)
    over = {line: over_prob(mats, line) for line in (1.5, 2.5, 3.5)}
    rows = []
    for k, (m, _) in enumerate(keep):
        hg, ag = m["hg"], m["ag"]
        sels = [("1X2", "H", probs[k, 0], hg > ag), ("1X2", "D", probs[k, 1], hg == ag), ("1X2", "A", probs[k, 2], hg < ag)]
        for line, p in over.items():
            sels += [(f"OU{line}", "Over", p[k], hg + ag > line), (f"OU{line}", "Under", 1 - p[k], hg + ag < line)]
        pick = max(sels[:3], key=lambda s: s[2])
        top = max(sels, key=lambda s: s[2])
        name = lambda s: pipeline.label(s[0], s[1], display(m["home"]), display(m["away"]))
        rows.append({"date": m["date"].strftime("%Y-%m-%d"), "competition": m["league"], "home": display(m["home"]), "away": display(m["away"]),
                     "score": f"{hg}-{ag}", "pick": {"label": name(pick), "p": float(pick[2]), "hit": bool(pick[3])},
                     "top": {"label": name(top), "p": float(top[2]), "hit": bool(top[3])}})
    return rows


def summary(rows):
    n = len(rows)
    bands = []
    for lo, hi in BANDS:
        sel = [r for r in rows if lo <= r["top"]["p"] < hi]
        if sel:
            bands.append({"from": lo, "to": min(hi, 1.0), "n": len(sel), "hit": sum(r["top"]["hit"] for r in sel) / len(sel),
                          "claimed": sum(r["top"]["p"] for r in sel) / len(sel)})
    return {"n": n, "top_hit": sum(r["top"]["hit"] for r in rows) / n, "pick_hit": sum(r["pick"]["hit"] for r in rows) / n,
            "bands": bands, "sure": SURE} if n else {"n": 0}


def get(model, limit=None, min_seen=MIN_SEEN):
    """Les `limit` derniers matchs (tous par défaut), du plus récent au plus ancien, avec le bilan sur tous."""
    key = (id(model["history"]), min_seen)
    if key not in _cache:
        _cache.clear()
        rows = compute(model, min_seen)
        _cache[key] = (rows, summary(rows))
    rows, stats = _cache[key]
    return {"rows": rows[::-1][:limit], "stats": stats}
