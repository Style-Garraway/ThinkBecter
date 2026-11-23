"""Noms d'équipes : chaque source écrit les clubs à sa façon.

Le nom affiché est celui de The Odds API (nom complet). football-data.co.uk utilise des noms courts : la table ci-dessous
fait le lien pour les 96 clubs de la saison 2026-27 (relevés le 23/11/2026 sur les deux sources). Un club absent de la
table garde son nom football-data ; `best_match` rapproche alors les écritures voisines.
"""
import unicodedata
from difflib import SequenceMatcher

FD_TO_NAME = {
    # Premier League
    "Brighton": "Brighton and Hove Albion", "Coventry": "Coventry City", "Hull": "Hull City", "Ipswich": "Ipswich Town",
    "Leeds": "Leeds United", "Man City": "Manchester City", "Man United": "Manchester United", "Newcastle": "Newcastle United",
    "Nott'm Forest": "Nottingham Forest", "Tottenham": "Tottenham Hotspur",
    # La Liga
    "Alaves": "Alavés", "Ath Bilbao": "Athletic Bilbao", "Ath Madrid": "Atlético Madrid", "Betis": "Real Betis", "Celta": "Celta Vigo",
    "Elche": "Elche CF", "Espanol": "Espanyol", "La Coruna": "Deportivo La Coruña", "Malaga": "Málaga", "Osasuna": "CA Osasuna",
    "Santander": "Real Racing Club de Santander", "Sociedad": "Real Sociedad", "Vallecano": "Rayo Vallecano",
    # Bundesliga
    "Dortmund": "Borussia Dortmund", "Ein Frankfurt": "Eintracht Frankfurt", "FC Koln": "1. FC Köln", "Freiburg": "SC Freiburg",
    "Hamburg": "Hamburger SV", "Hoffenheim": "TSG Hoffenheim", "Leverkusen": "Bayer Leverkusen", "M'gladbach": "Borussia Monchengladbach",
    "Mainz": "FSV Mainz 05", "Paderborn": "SC Paderborn", "Schalke 04": "FC Schalke 04", "Stuttgart": "VfB Stuttgart",
    # Serie A
    "Atalanta": "Atalanta BC", "Inter": "Inter Milan", "Milan": "AC Milan", "Roma": "AS Roma",
    # Ligue 1
    "Le Mans": "Le Mans FC", "Lens": "RC Lens", "Monaco": "AS Monaco", "Paris SG": "Paris Saint Germain",
}
# Mots qui ne distinguent pas un club d'un autre (formes juridiques, préfixes).
NOISE = {"fc", "cf", "ac", "as", "sc", "rc", "ca", "bc", "afc", "sv", "fsv", "vfb", "vfl", "tsg", "fk", "sk", "kv", "cp", "club", "de"}
# Écritures qu'aucune règle ne rapproche (clé réduite, voir `key` -> nom affiché). Relevées sur fixturedownload.com et API-Football.
ALIASES = {
    "man city": "Manchester City", "man utd": "Manchester United", "spurs": "Tottenham Hotspur",
    "r racing": "Real Racing Club de Santander", "rcd espanyol barcelona": "Espanyol", "internazionale": "Inter Milan",
    "havre athletic": "Le Havre", "olympique lyonnais": "Lyon", "stade rennais": "Rennes", "stade brestois": "Brest",
}


def display(fd_name):
    return FD_TO_NAME.get(fd_name, fd_name)


def norm(s):
    """Minuscules sans accents ni ponctuation : « 1. FC Köln » -> « 1 fc koln »."""
    s = unicodedata.normalize("NFKD", s.replace("ø", "o").replace("Ø", "O")).encode("ascii", "ignore").decode().lower()
    return " ".join("".join(ch if ch.isalnum() else " " for ch in s).split())


def key(s):
    """Nom réduit aux mots qui comptent : « 1. FC Köln » -> « koln », « AC Milan » -> « milan »."""
    words = [w for w in norm(s).split() if w not in NOISE and not w.isdigit()]
    k = " ".join(words) or norm(s)
    return key(ALIASES[k]) if k in ALIASES else k


def best_match(name, candidates, threshold=0.8):
    """Le candidat qui désigne le même club que `name`, ou None si aucun n'est assez proche ou si deux se valent."""
    k = key(name)
    exact = [c for c in candidates if key(c) == k]
    if len(exact) == 1:
        return exact[0]
    scored = []
    for c in candidates:
        kc = key(c)
        inside = set(k.split()) <= set(kc.split()) or set(kc.split()) <= set(k.split())  # « Tottenham » dans « Tottenham Hotspur »
        scored.append((1.0 if inside else SequenceMatcher(None, k, kc).ratio(), c))
    scored.sort(reverse=True)
    if scored and scored[0][0] >= threshold and (len(scored) == 1 or scored[0][0] - scored[1][0] > 0.05):
        return scored[0][1]
    return None
