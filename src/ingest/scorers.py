"""Buteurs et passeurs probables, sans clé et sans compte.

Sources (deux services publics gratuits, aucune clé) :
- Premier League : l'API publique de Fantasy Premier League (tous les joueurs : buts, passes, buts attendus xG, passes attendues xA,
  blessés/suspendus) ;
- La Liga, Bundesliga, Serie A, Ligue 1 : l'API publique d'ESPN, qui ne donne que les 25 meilleurs buteurs et les 25 meilleurs passeurs
  de chaque championnat. Un joueur hors de ces classements n'est donc jamais proposé.

Estimation simple, NON validée par un backtest : chances = 1 - exp(-taux du joueur par match x buts attendus ce soir / buts habituels
de son équipe par match). Un joueur marque donc davantage quand son équipe doit marquer plus que d'habitude.
"""
import json
import math
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from ..database import db
from .names import best_match

FPL = "https://fantasy.premierleague.com/api/bootstrap-static/"
ESPN = "https://sports.core.api.espn.com/v2/sports/soccer/leagues/{slug}/seasons/{year}/types/1/leaders"
ESPN_LEAGUES = {"La Liga": "esp.1", "Bundesliga": "ger.1", "Serie A": "ita.1", "Ligue 1": "fra.1"}
POS = {1: "G", 2: "D", 3: "M", 4: "F"}
AVG_GOALS = 1.45  # buts par match d'une équipe dont on ne connaît pas la moyenne de la saison
MIN_MATCHES = 3  # en dessous, le taux d'un joueur ne veut rien dire
EVERY = timedelta(hours=12)


def get_json(url):
    req = urllib.request.Request(url.replace("http://", "https://"), headers={"User-Agent": "ThinkBecter"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def fpl_players(data):
    """{club: [joueur]} depuis la réponse de Fantasy Premier League. Les joueurs blessés, suspendus ou partis sont écartés."""
    teams = {t["id"]: t["name"] for t in data["teams"]}
    played = {}
    for p in data["elements"]:
        played[p["team"]] = max(played.get(p["team"], 0), p["minutes"] / 90)
    out = {}
    for p in data["elements"]:
        tm = played.get(p["team"], 0)
        if p["status"] != "a" or p["minutes"] < 90 or tm < MIN_MATCHES:
            continue
        g, a = (p["goals_scored"] + float(p["expected_goals"])) / 2, (p["assists"] + float(p["expected_assists"])) / 2  # réel et attendu à parts égales
        out.setdefault(teams[p["team"]], []).append({"name": p["web_name"], "pos": POS.get(p["element_type"]), "rg": g / tm, "ra": a / tm})
    return out


def espn_players(league, slug, year, get=get_json):
    """{club: [joueur]} pour un championnat : seulement les 25 premiers buteurs et passeurs."""
    cats = {c["name"]: c["leaders"] for c in get(ESPN.format(slug=slug, year=year))["categories"]}
    cache = {}

    def fetch(ref):
        if ref not in cache:
            cache[ref] = get(ref)
        return cache[ref]

    rows = [(kind, e) for kind, name in (("g", "goalsLeaders"), ("a", "assistsLeaders")) for e in cats.get(name, [])]
    refs = {e[k]["$ref"] for _, e in rows for k in ("athlete", "team")}
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(fetch, refs))
    matches = max((int(e["displayValue"].split("Matches: ")[1].split(",")[0]) for _, e in rows), default=0)
    players = {}
    for kind, e in rows:
        club, who = fetch(e["team"]["$ref"])["displayName"], fetch(e["athlete"]["$ref"])
        p = players.setdefault((club, who["fullName"]), {"name": who.get("displayName") or who["fullName"], "pos": (who.get("position") or {}).get("abbreviation"), "rg": 0, "ra": 0})
        p["r" + kind] = e["value"] / matches if matches >= MIN_MATCHES else 0
    out = {}
    for (club, _), p in players.items():
        out.setdefault(club, []).append(p)
    return out


def fetch_all(now):
    """({club: [joueur]}, erreurs). Chaque source est indépendante : une panne n'efface pas les autres."""
    out, errors = {}, []
    year = now.year if now.month >= 7 else now.year - 1
    try:
        out.update(fpl_players(get_json(FPL)))
    except (OSError, ValueError, KeyError):
        errors.append("Joueurs de Premier League indisponibles pour le moment.")
    for league, slug in ESPN_LEAGUES.items():
        try:
            out.update(espn_players(league, slug, year))
        except (OSError, ValueError, KeyError, IndexError):
            errors.append(f"Buteurs de {league} indisponibles pour le moment.")
    return out, errors


def sync(conn, now, fetcher=fetch_all):
    """Une fois toutes les 12 h au plus. Renvoie {"players": n, "errors": [...]}. Si tout échoue, la liste déjà enregistrée reste."""
    old = db.get(conn, "players", {})
    if old and now - datetime.fromisoformat(old["at"]) < EVERY:
        return {"players": sum(map(len, old["clubs"].values())), "errors": []}
    clubs, errors = fetcher(now)
    if not clubs:
        return {"players": sum(map(len, old.get("clubs", {}).values())), "errors": errors}
    db.put(conn, "players", {"at": now.isoformat(), "clubs": clubs})
    return {"players": sum(map(len, clubs.values())), "errors": errors}


def likely(clubs, club, goals, usual=None, limit=3):
    """Buteurs et passeurs les plus probables d'un club qui doit marquer `goals` buts en moyenne : ([(nom, p)], [(nom, p)])."""
    name = best_match(club, list(clubs)) if clubs else None
    squad = clubs.get(name, []) if name else []
    chance = lambda rate: 1 - math.exp(-rate * goals / (usual or AVG_GOALS))
    top = lambda key: [{"name": p["name"], "pos": p["pos"], "p": chance(p[key])} for p in sorted(squad, key=lambda p: -p[key])[:limit] if p[key] > 0]
    return {"scorers": top("rg"), "assists": top("ra")}
