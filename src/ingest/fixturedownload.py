"""Calendrier de toute la saison des 5 championnats depuis fixturedownload.com (gratuit, sans clé).

Sert à afficher deux semaines de matchs sans aucune clé. Si ce site ne répond pas, il reste le calendrier de
football-data (la journée en cours) : l'appli continue de fonctionner, l'écran le signale.
"""
import json
from datetime import datetime, timedelta, timezone

from .footballdata import download

URL = "https://fixturedownload.com/feed/json/{feed}-{year}"
FEEDS = {"Premier League": "epl", "La Liga": "la-liga", "Bundesliga": "bundesliga", "Serie A": "serie-a", "Ligue 1": "ligue-1"}


def fixtures(year, now, days=14, fetch=download):
    """Matchs non commencés des `days` prochains jours : league, kickoff (heure locale), home, away (noms du site).
    Renvoie (matchs, ligues dont le calendrier n'a pas pu être lu)."""
    out, failed = [], []
    for league, feed in FEEDS.items():
        try:
            data = json.loads(fetch(URL.format(feed=feed, year=year)).decode("utf-8-sig"))
        except Exception:  # réseau, site en panne, réponse illisible
            failed.append(league)
            continue
        for m in data:
            try:
                kick = datetime.strptime(m["DateUtc"], "%Y-%m-%d %H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
                home, away = m["HomeTeam"], m["AwayTeam"]
            except (KeyError, TypeError, ValueError):
                continue
            if now < kick <= now + timedelta(days=days):
                out.append({"league": league, "kickoff": kick, "home": home, "away": away})
    return out, failed
