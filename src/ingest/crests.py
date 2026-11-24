"""Logos des clubs : table des identifiants API-Football et cache local des images.

Les 166 identifiants ont été relevés le 24/11/2026 et chaque logo a été contrôlé à l'œil. Les images viennent du serveur
d'images public d'API-Football (sans clé, sans consommer de requête) et sont gardées sur le PC de l'utilisateur, dans
`data/crests` : aucun logo n'est dans le dépôt. Les logos restent la propriété des clubs ; ils ne servent ici qu'à
reconnaître l'équipe, comme sur n'importe quel site de résultats.
Un club absent de la table (promu, nouveau venu en coupe) est ajouté tout seul par `lineups.sync_fixtures` quand il joue
(avec la clé API-Football) ; sans cela, l'écran affiche simplement le nom sans logo.
"""
import threading
from functools import lru_cache
from pathlib import Path

from .footballdata import download
from .names import best_match

CACHE = Path(__file__).resolve().parents[2] / "data" / "crests"
URL = "https://media.api-sports.io/football/teams/{id}.png"
PNG = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])  # signature d'un fichier PNG
MAX_BYTES = 300_000  # le plus gros logo fait 132 Ko
_lock = threading.Lock()

IDS = {
    "1. FC Köln": 192, "AC Milan": 489, "AEK Athens": 575, "AGF Aarhus": 406, "Ajax": 194, "Alavés": 542,
    "Anderlecht": 554, "Angers": 77, "Arsenal": 42, "AS Monaco": 91, "AS Roma": 497, "Aston Villa": 66,
    "Atalanta BC": 499, "Athletic Bilbao": 531, "Atlético Madrid": 530, "Augsburg": 170, "Auxerre": 108,
    "AZ Alkmaar": 201, "Barcelona": 529, "Bayer Leverkusen": 168, "Bayern Munich": 157, "Benfica": 211,
    "Besiktas JK": 549, "Bodø/Glimt": 327, "Bologna": 500, "Borussia Dortmund": 165, "Borussia Monchengladbach": 163,
    "Bournemouth": 35, "Brentford": 55, "Brest": 106, "Brighton and Hove Albion": 51, "CA Osasuna": 727,
    "Cagliari": 490, "Celta Vigo": 538, "Celtic": 247, "Chelsea": 49, "Club Brugge": 569, "Como": 895,
    "Coventry City": 1346, "Crystal Palace": 52, "Deportivo La Coruña": 544, "Dinamo Zagreb": 620,
    "Eintracht Frankfurt": 169, "Elche CF": 797, "Elversberg": 1660, "Espanyol": 540, "Everton": 45,
    "FC Ararat-Armenia": 3683, "FC Copenhagen": 400, "FC Iberia 1999": 3502, "FC Kairat": 664, "FC Lugano": 606,
    "FC Midtjylland": 397, "FC Nordsjaelland": 398, "FC Schalke 04": 174, "FC Thun": 1012, "FC Twente Enschede": 415,
    "Fenerbahce": 611, "Ferencváros TC": 651, "Feyenoord": 209, "Fiorentina": 502, "FK Borac Banja Luka": 3364,
    "FK Jablonec": 1122, "FK Kauno Žalgiris": 3872, "Frosinone": 512, "FSV Mainz 05": 164, "Fulham": 36,
    "Galatasaray": 645, "Genoa": 495, "Gent": 631, "Getafe": 546, "Hajduk Split": 608, "Hamburger SV": 175,
    "Hapoel Be'er Sheva": 563, "Hearts": 254, "Hull City": 64, "Inter Club d'Escaldes": 3342, "Inter Milan": 505,
    "Ipswich Town": 57, "Jagiellonia Białystok": 336, "Juventus": 496, "KF Egnatia": 3327, "KuPS Kuopio": 1165,
    "LASK": 1026, "Lazio": 487, "Le Havre": 111, "Le Mans FC": 1298, "Lecce": 867, "Lech Poznań": 347,
    "Leeds United": 63, "Levante": 539, "Lille": 79, "Lillestrom": 321, "Lincoln Red Imps FC": 667, "Liverpool": 40,
    "Lorient": 97, "Lyon": 80, "Manchester City": 50, "Manchester United": 33, "Marseille": 81, "Mjällby AIF": 2240,
    "Monza": 1579, "Málaga": 535, "Napoli": 492, "NEC Nijmegen": 413, "Newcastle United": 34, "Nice": 84,
    "NK Celje": 4360, "Nottingham Forest": 65, "OFI Crete": 1124, "Olympiakos Piraeus": 553, "Omonoia FC": 3402,
    "Pafos FC": 3403, "Panathinaikos FC": 617, "Paris FC": 114, "Paris Saint Germain": 85, "Parma": 523,
    "PFC CSKA Sofia": 853, "PFC Levski Sofia": 646, "Porto": 212, "PSV Eindhoven": 197, "Rayo Vallecano": 728,
    "RB Leipzig": 173, "RC Lens": 116, "Real Betis": 543, "Real Madrid": 541, "Real Racing Club de Santander": 4665,
    "Real Sociedad": 548, "Red Star Belgrade": 598, "Rennes": 94, "Riga FC": 10124, "Sabah FK": 13976,
    "Salzburg": 571, "Sassuolo": 488, "SC Braga": 217, "SC Freiburg": 160, "SC Paderborn": 185, "Sevilla": 536,
    "Shakhtar Donetsk": 550, "Sint Truiden": 735, "SK Brann": 319, "SK Sturm Graz": 637, "Slavia Praha": 560,
    "Sparta Prague": 628, "Sporting Lisbon": 228, "Strasbourg": 95, "Sunderland": 746, "Torino": 503,
    "Torreense": 4799, "Tottenham Hotspur": 47, "Toulouse": 96, "Trabzonspor": 998, "Troyes": 110,
    "TSG Hoffenheim": 167, "Udinese": 494, "Union Berlin": 182, "Union Saint-Gilloise": 1393,
    "Universitatea Craiova": 632, "Valencia": 532, "Venezia": 517, "VfB Stuttgart": 172, "Viking FK": 759,
    "Viktoria Plzeň": 567, "Villarreal": 533, "Werder Bremen": 162, "ŠK Slovan Bratislava": 656,
}


@lru_cache(maxsize=512)
def _fuzzy(name):
    found = best_match(name, list(IDS))
    return IDS[found] if found else None


def crest_id(name, extra=None):
    """Identifiant API-Football du club : table figée, puis clubs appris (`extra`), puis nom voisin ; None si inconnu."""
    return IDS.get(name) or (extra or {}).get(name) or _fuzzy(name)


def known_ids(extra=None):
    return set(IDS.values()) | set((extra or {}).values())


def image(cid, fetch=download):
    """Chemin du logo en cache, téléchargé la première fois. None si indisponible (hors ligne, réponse qui n'est pas un PNG)."""
    path = CACHE / f"{int(cid)}.png"
    with _lock:
        if path.exists():
            return path
        try:
            raw = fetch(URL.format(id=int(cid)))
        except Exception:  # réseau coupé, serveur d'images en panne : l'écran se passe du logo
            return None
        if not raw.startswith(PNG) or len(raw) > MAX_BYTES:
            return None  # on n'enregistre jamais autre chose qu'une petite image PNG
        CACHE.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(raw)
        tmp.replace(path)  # remplacement d'un bloc : jamais de fichier à moitié écrit
        return path
