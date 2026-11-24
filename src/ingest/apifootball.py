"""Ce que partagent les appels à API-Football (clé facultative) : liste des compétitions suivies, appel HTTP et budget.

L'offre gratuite donne 100 requêtes par jour (jour UTC). Chaque appel est compté dans `settings["af_usage"]` ; les
actualisations en laissent 35 en réserve pour les compositions, qui sont réclamées au bon moment le jour des matchs.
"""
import json
import urllib.request
from datetime import timezone

from ..database import db

BASE = "https://v3.football.api-sports.io"
# Identifiants API-Football des compétitions suivies : le reste du monde est ignoré (sinon « Arsenal Sarandí » = Arsenal).
LEAGUE_IDS = {39: "Premier League", 140: "La Liga", 78: "Bundesliga", 135: "Serie A", 61: "Ligue 1",
              2: "Ligue des Champions", 3: "Ligue Europa", 848: "Ligue Conférence"}
DAY_LIMIT = 100
LIMIT_MESSAGE = "Limite quotidienne API-Football presque atteinte : elle repart de zéro à 20 h (heure du Venezuela) / 2 h (France)."


def get(key, path):
    """Réponse JSON d'API-Football ; la clé « _remaining » donne les requêtes qui restent aujourd'hui, si le serveur l'indique."""
    req = urllib.request.Request(BASE + path, headers={"x-apisports-key": key})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())
        left = r.headers.get("x-ratelimit-requests-remaining")
    data["_remaining"] = int(left) if left and left.isdigit() else None
    return data


def errors_text(data):
    """Texte lisible des erreurs d'une réponse (dictionnaire ou liste selon le cas), ou None s'il n'y en a pas."""
    errs = data.get("errors")
    if not errs:
        return None
    return "API-Football : " + "; ".join(map(str, errs.values() if isinstance(errs, dict) else errs))[:140]


def _day(now):
    return now.astimezone(timezone.utc).strftime("%Y-%m-%d")


def used(conn, now):
    u = db.get(conn, "af_usage", {})
    return u.get("used", 0) if u.get("day") == _day(now) else 0


def spender(conn, now, floor):
    """Fonction à appeler avant chaque requête : elle la compte et renvoie False quand il ne reste plus que `floor` requêtes."""
    def spend():
        n = used(conn, now)
        if n >= DAY_LIMIT - floor:
            return False
        db.put(conn, "af_usage", {"day": _day(now), "used": n + 1})
        return True
    return spend


def note_remaining(conn, now, data):
    """Recale le compteur sur ce que dit le serveur (d'autres programmes peuvent utiliser la même clé)."""
    left = data.get("_remaining")
    if left is not None:
        db.put(conn, "af_usage", {"day": _day(now), "used": max(used(conn, now), DAY_LIMIT - left)})
