"""Historique des pronostics sur les matchs déjà joués, gagnés comme perdus.

Chaque match est pronostiqué comme l'agent l'aurait fait AVANT de le jouer : seuls les matchs terminés au moins 3 jours plus tôt
sont connus (même protocole que le backtest). Sans les cotes d'époque, ce sont des probabilités recalculées, pas le journal réel
(le journal réel, lui, se remplit à partir du 23/11/2026). Les 10 premiers matchs de chaque club sont ignorés (notes pas encore fiables).

Ligue des Champions : les notes des clubs des 5 championnats sont rejouées à la date de chaque match, MAIS les niveaux de la table
`europe` (championnats et clubs hors des 5) ont été calés en novembre 2026 sur ces mêmes matchs. Cet historique est donc trop flatteur :
il montre ce que fait l'estimation, pas une preuve (étiquette `fitted`).
"""
from datetime import datetime, timedelta

from .engine import europe, pipeline, ratings
from .engine.dixon_coles import outcome_probs, over_prob, score_matrices
from .ingest.names import best_match, display

MIN_SEEN = 10
BANDS = ((0.0, 0.75), (0.75, 0.80), (0.80, 0.85), (0.85, 0.90), (0.90, 1.01))
SURE = 0.85  # au-dessus, le pari est dit « sûr » (mesuré : environ 9 sur 10 gagnés)
_cache = {}


CL = "Ligue des Champions"


def _bets(lh, la):
    """Probabilités des paris pour N matchs : liste de (marché, sélection, tableau de probabilités) et indices des 3 résultats 1N2."""
    mats = score_matrices(lh, la)
    probs = outcome_probs(mats)
    sels = [("1X2", "H", probs[:, 0]), ("1X2", "D", probs[:, 1]), ("1X2", "A", probs[:, 2])]
    for line in (1.5, 2.5, 3.5):
        p = over_prob(mats, line)
        sels += [(f"OU{line}", "Over", p), (f"OU{line}", "Under", 1 - p)]
    return sels


def _won(market, sel, hg, ag):
    if market == "1X2":
        return {"H": hg > ag, "D": hg == ag, "A": hg < ag}[sel]
    return (hg + ag > float(market[2:])) == (sel == "Over")


def _rows(items, fitted=False):
    """items : (date, championnat, domicile, extérieur, buts dom., buts ext., λ dom., λ ext.) -> lignes de l'historique."""
    if not items:
        return []
    sels = _bets([i[6] for i in items], [i[7] for i in items])
    rows = []
    for k, (day, league, home, away, hg, ag, _, _) in enumerate(items):
        scored = [(mk, sel, float(p[k]), _won(mk, sel, hg, ag)) for mk, sel, p in sels]
        pick, top = max(scored[:3], key=lambda x: x[2]), max(scored, key=lambda x: x[2])
        name = lambda x: pipeline.label(x[0], x[1], home, away)
        rows.append({"date": day, "competition": league, "home": home, "away": away, "score": f"{hg}-{ag}", "fitted": fitted,
                     "pick": {"label": name(pick), "p": pick[2], "hit": bool(pick[3])}, "top": {"label": name(top), "p": top[2], "hit": bool(top[3])}})
    return rows


def compute(model, min_seen=MIN_SEEN):
    h = model["history"]
    preds, _ = ratings.walk(h, lag_days=3)
    keep = [(m, p) for m, p in zip(h, preds) if p[2] >= min_seen]
    return _rows([(m["date"].strftime("%Y-%m-%d"), m["league"], display(m["home"]), display(m["away"]), m["hg"], m["ag"], p[0], p[1]) for m, p in keep])


def champions(model, results):
    """Matchs de Ligue des Champions déjà joués (voir ingest.champions), pronostiqués avec les notes connues 3 jours avant."""
    h, state, j, items = model["history"], ratings.new_state(), 0, []
    clubs = {}  # nom affiché -> (championnat, nom football-data), pour les clubs des 5 championnats de la saison
    for m in h:
        if m["season"] == model["season"]:
            for fd in (m["home"], m["away"]):
                clubs[display(fd)] = (m["league"], fd)
    outside = list(europe.CLUBS)

    def strength(name, day):
        known = best_match(name, list(clubs))
        if known:
            league, fd = clubs[known]
            return europe.strength(known, league, ratings.relative(state, league, model["season"], fd))
        return europe.strength(best_match(name, outside) or name, None, None)

    for r in sorted(results, key=lambda r: r["date"]):
        day = datetime.strptime(r["date"], "%Y-%m-%d")
        while j < len(h) and h[j]["date"] + timedelta(days=3) < day:
            ratings.update(state, h[j])
            j += 1
        lh, la = europe.expected_goals(strength(r["home"], day), strength(r["away"], day))
        items.append((r["date"], CL, r["home"], r["away"], r["hg"], r["ag"], lh, la))
    return _rows(items, fitted=True)


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


def get(model, results=(), limit=None, min_seen=MIN_SEEN):
    """Les `limit` derniers matchs (tous par défaut), du plus récent au plus ancien, avec le bilan des 5 championnats.
    `results` : matchs de Ligue des Champions déjà joués (ingest.champions.stored)."""
    key = (id(model["history"]), min_seen, len(results))
    if key not in _cache:
        _cache.clear()
        rows = compute(model, min_seen)
        _cache[key] = (rows, summary(rows), champions(model, results) if results else [])
    rows, stats, cl = _cache[key]
    merged = sorted(rows + cl, key=lambda r: r["date"])
    return {"rows": merged[::-1][:limit], "stats": stats}
