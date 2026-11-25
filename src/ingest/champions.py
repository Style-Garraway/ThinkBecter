"""Résultats passés de la Ligue des Champions (ESPN, sans clé) : football-data n'a pas les coupes d'Europe.

Un appel par jour de match (mardi, mercredi, jeudi depuis le 1er septembre) ; les jours déjà lus sont gardés et jamais redemandés,
sauf les deux derniers jours (un match peut ne pas être fini). Sert uniquement à l'historique.
"""
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from ..database import db

URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/uefa.champions/scoreboard?dates={day}"
MATCH_DAYS = (1, 2, 3)  # mardi, mercredi, jeudi
RECENT = 2


def fetch_day(day):
    """Matchs terminés d'un jour (AAAAMMJJ) : [{date, home, away, hg, ag}]."""
    req = urllib.request.Request(URL.format(day=day), headers={"User-Agent": "ThinkBecter"})
    with urllib.request.urlopen(req, timeout=25) as r:
        events = json.load(r).get("events", [])
    out = []
    for e in events:
        c = e["competitions"][0]
        if not c["status"]["type"]["completed"]:
            continue
        side = {t["homeAway"]: t for t in c["competitors"]}
        out.append({"date": e["date"][:10], "home": side["home"]["team"]["displayName"], "away": side["away"]["team"]["displayName"],
                    "hg": int(side["home"]["score"]), "ag": int(side["away"]["score"])})
    return out


def sync(conn, today, fetcher=fetch_day):
    """Complète les résultats enregistrés. Renvoie {"matches": n, "errors": [...]}. Une panne garde ce qui est déjà lu."""
    store = db.get(conn, "cl_results", {"days": [], "matches": []})
    start = date(today.year if today.month >= 7 else today.year - 1, 9, 1)
    last = today.date() - timedelta(days=1)
    days = [start + timedelta(n) for n in range((last - start).days + 1)]
    todo = [d for d in days if d.weekday() in MATCH_DAYS and (d.isoformat() not in store["days"] or (last - d).days < RECENT)]
    errors = []

    def read(d):
        try:
            return d, fetcher(d.strftime("%Y%m%d"))
        except (OSError, ValueError, KeyError):
            return d, None

    with ThreadPoolExecutor(6) as pool:
        got = list(pool.map(read, todo))
    for d, matches in got:
        if matches is None:
            errors.append("Résultats de la Ligue des Champions indisponibles pour le moment.")
            continue
        store["matches"] = [m for m in store["matches"] if m["date"] != d.isoformat()] + [dict(m, date=d.isoformat()) for m in matches]
        if d.isoformat() not in store["days"]:
            store["days"].append(d.isoformat())
    db.put(conn, "cl_results", store)
    return {"matches": len(store["matches"]), "errors": sorted(set(errors))}


def stored(conn):
    return sorted(db.get(conn, "cl_results", {"matches": []})["matches"], key=lambda m: m["date"])
