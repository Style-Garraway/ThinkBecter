"""Compositions officielles (API-Football, clé facultative). Information seule : les chances ne s'en servent pas.

1. `sync_fixtures` relie chaque match de la base au numéro de match d'API-Football (2 requêtes : aujourd'hui et demain UTC).
2. `poll` réclame la composition d'un match seulement quand elle peut être publiée : de 65 minutes avant le coup d'envoi
   jusqu'à 10 minutes après, une tentative toutes les 14 minutes, 5 au maximum. Un match sans composition ne coûte donc
   jamais plus de 5 requêtes. La page appelle `poll` toutes les 2 minutes, mais ne dépense une requête que si c'est dû.
"""
import json
from datetime import datetime, timedelta, timezone

from ..database import db
from . import apifootball, crests
from .names import best_match

FMT = "%Y-%m-%dT%H:%M"
START_BEFORE, STOP_AFTER, RETRY, MAX_TRIES = timedelta(minutes=65), timedelta(minutes=10), timedelta(minutes=14), 5
OVER = ("FT", "AET", "PEN", "CANC", "ABD", "AWD", "WO")  # statuts d'un match déjà joué ou annulé


def fetch_fixtures(key, date):
    return apifootball.get(key, f"/fixtures?date={date}")


def fetch_lineups(key, fixture_id):
    return apifootball.get(key, f"/fixtures/lineups?fixture={int(fixture_id)}")


def _local(iso):
    return datetime.fromisoformat(iso).astimezone().replace(tzinfo=None)


def sync_fixtures(conn, key, now, fetcher=fetch_fixtures, spend=None):
    """Relie les matchs à venir aux matchs d'API-Football, et apprend le logo des clubs absents de la table."""
    out = {"linked": 0, "errors": []}
    extra = db.get(conn, "crest_extra", {})
    cands = db.rows(conn, "SELECT m.id, m.kickoff, m.competition, h.name home, a.name away FROM matches m "
                          "JOIN teams h ON h.id = m.home_id JOIN teams a ON a.id = m.away_id "
                          "WHERE m.hg IS NULL AND m.kickoff BETWEEN ? AND ?",
                    ((now - timedelta(hours=12)).strftime(FMT), (now + timedelta(days=2)).strftime(FMT)))
    utc = now.astimezone(timezone.utc)
    same = lambda ours, team: crests.crest_id(ours, extra) == team["id"] or best_match(team["name"], [ours]) is not None
    for day in (utc, utc + timedelta(days=1)):
        if spend and not spend():
            out["errors"].append(apifootball.LIMIT_MESSAGE)
            break
        try:
            data = fetcher(key, day.strftime("%Y-%m-%d"))
        except (OSError, ValueError):
            out["errors"].append("API-Football injoignable.")
            continue
        apifootball.note_remaining(conn, now, data)
        if apifootball.errors_text(data):
            out["errors"].append(apifootball.errors_text(data))
            continue
        for f in data.get("response", []):
            comp = apifootball.LEAGUE_IDS.get(f["league"]["id"])
            if not comp or f["fixture"]["status"]["short"] in OVER:
                continue
            kick, home, away = _local(f["fixture"]["date"]), f["teams"]["home"], f["teams"]["away"]
            hits = [c for c in cands if c["competition"] == comp and abs(datetime.strptime(c["kickoff"], FMT) - kick) <= timedelta(hours=12)
                    and same(c["home"], home) and same(c["away"], away)]
            if len(hits) != 1:
                continue  # aucun match reconnu, ou deux possibles : on ne devine pas
            c = hits[0]
            conn.execute("INSERT INTO lineups (match_id, fixture_id, home_api, away_api) VALUES (?, ?, ?, ?) "
                         "ON CONFLICT(match_id) DO UPDATE SET fixture_id = excluded.fixture_id, "
                         "home_api = excluded.home_api, away_api = excluded.away_api",
                         (c["id"], f["fixture"]["id"], home["id"], away["id"]))
            for ours, team in ((c["home"], home), (c["away"], away)):
                if crests.crest_id(ours, extra) is None:
                    extra[ours] = team["id"]
            out["linked"] += 1
    db.put(conn, "crest_extra", extra)
    conn.commit()
    return out


def due(conn, now):
    """Matchs dont la composition peut être réclamée maintenant."""
    return db.rows(conn, "SELECT l.match_id, l.fixture_id, l.home_api, l.away_api FROM lineups l JOIN matches m ON m.id = l.match_id "
                         "WHERE l.home IS NULL AND l.tries < ? AND m.hg IS NULL AND (l.last_try IS NULL OR l.last_try <= ?) "
                         "AND m.kickoff BETWEEN ? AND ? ORDER BY m.kickoff",
                   (MAX_TRIES, (now - RETRY).strftime(FMT), (now - STOP_AFTER).strftime(FMT), (now + START_BEFORE).strftime(FMT)))


def _side(entry):
    player = lambda p: {"n": p["player"].get("number"), "name": p["player"]["name"], "pos": p["player"].get("pos")}
    return {"formation": entry.get("formation"), "coach": (entry.get("coach") or {}).get("name"),
            "xi": [player(p) for p in entry.get("startXI", [])], "bench": [player(p) for p in entry.get("substitutes", [])]}


def parse(response, row):
    """(domicile, extérieur) si la réponse contient les deux compositions complètes, sinon None."""
    if len(response) != 2 or any(len(e.get("startXI", [])) < 9 for e in response):
        return None
    by_id = {e["team"]["id"]: e for e in response}
    home, away = by_id.get(row["home_api"]), by_id.get(row["away_api"])
    if home is None or away is None:
        home, away = response  # numéros inattendus : on suit l'ordre d'API-Football (domicile, puis extérieur)
    return _side(home), _side(away)


def poll(conn, key, now, fetcher=fetch_lineups, spend=None):
    """Réclame les compositions dues. Renvoie {"found": n, "errors": [...]}."""
    out = {"found": 0, "errors": []}
    ts = now.strftime(FMT)
    for row in due(conn, now):
        if spend and not spend():
            out["errors"].append(apifootball.LIMIT_MESSAGE)
            break
        try:
            data = fetcher(key, row["fixture_id"])
        except (OSError, ValueError):
            out["errors"].append("API-Football injoignable.")
            break
        apifootball.note_remaining(conn, now, data)
        if apifootball.errors_text(data):
            out["errors"].append(apifootball.errors_text(data))
            break
        sides = parse(data.get("response", []), row)
        if sides:
            conn.execute("UPDATE lineups SET home = ?, away = ?, at = ?, tries = tries + 1, last_try = ? WHERE match_id = ?",
                         (json.dumps(sides[0], ensure_ascii=False), json.dumps(sides[1], ensure_ascii=False), ts, ts, row["match_id"]))
            out["found"] += 1
        else:
            conn.execute("UPDATE lineups SET tries = tries + 1, last_try = ? WHERE match_id = ?", (ts, row["match_id"]))
    conn.commit()
    out["errors"] = sorted(set(out["errors"]))
    return out


def stored(conn):
    """Compositions publiées : {id du match: {"home": ..., "away": ..., "at": heure de réception}}."""
    return {r["match_id"]: {"home": json.loads(r["home"]), "away": json.loads(r["away"]), "at": r["at"]}
            for r in db.rows(conn, "SELECT match_id, home, away, at FROM lineups WHERE home IS NOT NULL")}
