"""Facultatif (clé gratuite the-odds-api.com, 500 crédits par mois) : calendrier sur deux semaines, coupes d'Europe
et cotes Betclic. Une actualisation coûte 1 crédit par compétition (marché 1N2, région « eu »), soit 8 crédits :
environ 60 actualisations par mois. Betclic ne publie par cette voie que le 1N2, le marché « totals » n'est donc pas demandé.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from ..database import db
from .footballdata import LEAGUES
from .names import best_match

URL = "https://api.the-odds-api.com/v4/sports/{sport}/odds"
BOOKMAKER = "betclic_fr"
SPORTS = {
    "Premier League": "soccer_epl", "La Liga": "soccer_spain_la_liga", "Bundesliga": "soccer_germany_bundesliga",
    "Serie A": "soccer_italy_serie_a", "Ligue 1": "soccer_france_ligue_one",
    "Ligue des Champions": "soccer_uefa_champs_league", "Ligue Europa": "soccer_uefa_europa_league",
    "Ligue Conférence": "soccer_uefa_europa_conference_league",
}
HTTP_ERRORS = {401: "Clé The Odds API refusée : vérifie-la dans ⚙.", 429: "Quota The Odds API épuisé pour ce mois."}


def fetch(api_key, sport):
    q = urllib.parse.urlencode({"apiKey": api_key, "regions": "eu", "markets": "h2h", "oddsFormat": "decimal"})
    with urllib.request.urlopen(f"{URL.format(sport=sport)}?{q}", timeout=25) as r:
        return json.loads(r.read().decode()), r.headers.get("x-requests-remaining")


def betclic(event):
    """Cotes Betclic 1N2 d'un événement : {"H": cote, "D": cote, "A": cote}, ou {} si Betclic ne l'a pas encore ouvert."""
    for bk in event.get("bookmakers", []):
        if bk.get("key") != BOOKMAKER:
            continue
        for mk in bk.get("markets", []):
            if mk.get("key") == "h2h":
                out = {"H" if o["name"] == event["home_team"] else "A" if o["name"] == event["away_team"] else "D": float(o["price"])
                       for o in mk["outcomes"]}
                return out if len(out) == 3 else {}
    return {}


def team(conn, name, competition):
    """Club d'un événement : même nom exact ; sinon, en championnat, le club de la ligue à l'écriture voisine ; sinon nouveau club."""
    r = conn.execute("SELECT id FROM teams WHERE name = ?", (name,)).fetchone()
    if r:
        return r["id"]
    if competition in LEAGUES:
        names = [t["name"] for t in db.rows(conn, "SELECT name FROM teams WHERE league = ? AND fd_name IS NOT NULL", (competition,))]
        close = best_match(name, names)
        if close:
            return conn.execute("SELECT id FROM teams WHERE name = ?", (close,)).fetchone()["id"]
    return db.team_id(conn, name, competition if competition in LEAGUES else None)


def sync(conn, api_key, now, fetcher=fetch):
    """Ajoute les matchs à venir et leurs cotes Betclic. Renvoie le décompte, les crédits restants et les erreurs lisibles."""
    out = {"matches": 0, "with_odds": 0, "remaining": None, "errors": []}
    ts = now.strftime("%Y-%m-%dT%H:%M")
    for competition, sport in SPORTS.items():
        try:
            events, remaining = fetcher(api_key, sport)
        except urllib.error.HTTPError as e:
            out["errors"].append(HTTP_ERRORS.get(e.code, f"The Odds API : erreur {e.code} ({competition})."))
            if e.code in HTTP_ERRORS:
                break  # clé refusée ou quota épuisé : inutile d'essayer les autres compétitions
            continue
        except (OSError, ValueError):
            out["errors"].append(f"The Odds API injoignable ({competition}).")
            continue
        out["remaining"] = remaining or out["remaining"]
        for ev in events:
            kick = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
            if kick <= now:
                continue  # match déjà commencé
            mid = db.match_id(conn, team(conn, ev["home_team"], competition), team(conn, ev["away_team"], competition), kick, competition)
            prices = betclic(ev)
            for sel, price in prices.items():
                conn.execute("INSERT OR REPLACE INTO odds VALUES (?, ?, ?)", (mid, sel, price))
                conn.execute("INSERT INTO odds_history VALUES (?, ?, ?, ?)", (mid, sel, price, ts))  # pour mesurer la CLV plus tard
            out["matches"] += 1
            out["with_odds"] += bool(prices)
    conn.commit()
    return out
