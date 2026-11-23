"""Facultatif (clé gratuite API-Football : 100 requêtes par jour, aujourd'hui et demain seulement) : joueurs forfaits.

Information seule, affichée sous le match. Le calcul des chances n'en tient PAS compte : la correction essayée en
octobre 2026 dégradait les pronostics (journal réel, 28 matchs : 1,02 avec contre 0,96 sans ; plus bas = mieux).
"""
import json
import urllib.request
from datetime import datetime, timedelta, timezone

from ..database import db
from .names import best_match

URL = "https://v3.football.api-sports.io/injuries?date={date}"
# Identifiants API-Football des compétitions suivies : le reste du monde est ignoré (sinon « Arsenal Sarandí » = Arsenal).
LEAGUE_IDS = {39: "Premier League", 140: "La Liga", 78: "Bundesliga", 135: "Serie A", 61: "Ligue 1",
              2: "Ligue des Champions", 3: "Ligue Europa", 848: "Ligue Conférence"}
NOT_AN_ABSENCE = ("off the roster", "inactive")  # joueurs non inscrits dans la compétition : ni blessés ni suspendus


def fetch(key, date):
    req = urllib.request.Request(URL.format(date=date), headers={"x-apisports-key": key})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def sync(conn, key, now, fetcher=fetch):
    """Remplace la liste des forfaits des matchs d'aujourd'hui et de demain. Renvoie {"absents": n, "errors": [...]}."""
    out = {"absents": 0, "errors": []}
    lo, hi = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"), (now + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M")
    playing = {}  # compétition -> {nom du club: id}, pour les clubs qui jouent ces jours-ci
    for r in db.rows(conn, "SELECT m.competition, t.id, t.name FROM matches m JOIN teams t ON t.id IN (m.home_id, m.away_id) "
                           "WHERE m.hg IS NULL AND m.kickoff BETWEEN ? AND ?", (lo, hi)):
        playing.setdefault(r["competition"], {})[r["name"]] = r["id"]
    found, answered = {}, False
    today = now.astimezone(timezone.utc)
    for day in (today, today + timedelta(days=1)):
        date = day.strftime("%Y-%m-%d")
        try:
            data = fetcher(key, date)
        except (OSError, ValueError):
            out["errors"].append("API-Football injoignable.")
            continue
        errs = data.get("errors")
        if errs:  # clé refusée, quota, date hors de l'offre gratuite... (dictionnaire ou liste selon le cas)
            out["errors"].append("API-Football : " + "; ".join(map(str, errs.values() if isinstance(errs, dict) else errs))[:140])
            continue
        answered = True
        for it in data.get("response", []):
            teams = playing.get(LEAGUE_IDS.get(it["league"]["id"]), {})
            out_for_real = it["player"]["type"] == "Missing Fixture" and (it["player"].get("reason") or "").lower() not in NOT_AN_ABSENCE
            name = best_match(it["team"]["name"], list(teams)) if out_for_real and teams else None
            if name:
                ts = datetime.fromisoformat(it["fixture"]["date"]).astimezone().replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M")
                found[(teams[name], it["player"]["name"], ts)] = it["player"].get("reason")
    if answered:  # instantané : on ne remplace l'ancienne liste que si au moins un jour a répondu
        conn.execute("DELETE FROM absences")
        conn.executemany("INSERT INTO absences (team_id, player, fixture_ts, reason) VALUES (?, ?, ?, ?)",
                         [(tid, player, ts, reason) for (tid, player, ts), reason in found.items()])
        conn.commit()
        out["absents"] = len(found)
    out["errors"] = sorted(set(out["errors"]))
    return out
