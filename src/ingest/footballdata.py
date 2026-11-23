"""Résultats, buts attendus (xG), cotes de clôture et calendrier depuis football-data.co.uk.

Gratuit, sans clé, fichiers CSV stables depuis plus de 20 ans. Les fichiers de saison sont mis à jour une à deux fois
par semaine (les matchs du week-end arrivent en début de semaine) ; fixtures.csv liste la journée à venir.
Les heures sont celles du Royaume-Uni : elles sont converties dans l'heure du PC.
"""
import csv
import io
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

CACHE = Path(__file__).resolve().parents[2] / "data" / "fd"
BASE = "https://www.football-data.co.uk"
LEAGUES = {"Premier League": "E0", "La Liga": "SP1", "Bundesliga": "D1", "Serie A": "I1", "Ligue 1": "F1"}
# Cotes 1N2 puis plus/moins de 2,5 buts : moyenne du marché à la clôture, sinon avant-match, sinon Bet365.
ODDS_1X2 = (("AvgCH", "AvgCD", "AvgCA"), ("AvgH", "AvgD", "AvgA"), ("B365CH", "B365CD", "B365CA"), ("B365H", "B365D", "B365A"))
ODDS_OU = (("AvgC>2.5", "AvgC<2.5"), ("Avg>2.5", "Avg<2.5"), ("B365C>2.5", "B365C<2.5"), ("B365>2.5", "B365<2.5"))


def season_start(today=None):
    today = today or datetime.now()
    return today.year if today.month >= 7 else today.year - 1


def download(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read()


def read_csv(raw):
    return [r for r in csv.DictReader(io.StringIO(raw.decode("utf-8-sig", errors="replace"))) if r.get("HomeTeam")]


def season_rows(div, year, refresh=False, fetch=download):
    """Lignes brutes d'une saison. Une saison passée est téléchargée une seule fois ; la saison en cours à la demande.
    Si le téléchargement échoue et qu'une copie existe, on garde la copie (l'erreur remonte à l'appelant via `errors`)."""
    f = CACHE / f"{year % 100:02d}{(year + 1) % 100:02d}_{div}.csv"
    if refresh or not f.exists():
        raw = fetch(f"{BASE}/mmz4281/{f.stem.split('_')[0]}/{div}.csv")
        if not read_csv(raw):
            raise ValueError(f"fichier vide ou illisible : {f.name}")
        CACHE.mkdir(parents=True, exist_ok=True)
        f.write_bytes(raw)
    return read_csv(f.read_bytes())


def uk_to_local(dt):
    """Heure britannique (naïve) -> heure locale du PC (naïve). Heure d'été : dernier dimanche de mars -> dernier d'octobre."""
    def last_sunday(month):
        d = datetime(dt.year, month + 1, 1) - timedelta(days=1)
        return d - timedelta(days=(d.weekday() + 1) % 7)
    summer = last_sunday(3) + timedelta(hours=1) <= dt < last_sunday(10) + timedelta(hours=2)
    utc = (dt - timedelta(hours=1 if summer else 0)).replace(tzinfo=timezone.utc)
    return utc.astimezone().replace(tzinfo=None)


def _num(r, key):
    try:
        return float(r[key])
    except (KeyError, TypeError, ValueError):
        return None


def _first(r, groups):
    for cols in groups:
        vals = [_num(r, c) for c in cols]
        if all(v and v > 1 for v in vals):
            return tuple(vals)
    return None


def _when(r):
    d = r["Date"].strip()
    day = datetime.strptime(d, "%d/%m/%Y" if len(d.split("/")[-1]) == 4 else "%d/%m/%y")
    try:
        h, m = (r.get("Time") or "15:00").split(":")
        return uk_to_local(day.replace(hour=int(h), minute=int(m)))
    except ValueError:
        return day.replace(hour=15)


def parse(rows, league, year):
    """Matchs joués d'une saison : dicts triables par date, avec cotes de clôture et xG quand ils existent."""
    out = []
    for r in rows:
        try:
            hg, ag = int(r["FTHG"]), int(r["FTAG"])
            when = _when(r)
        except (KeyError, TypeError, ValueError):
            continue  # match pas encore joué ou ligne abîmée
        out.append({"league": league, "season": year, "date": when, "home": r["HomeTeam"].strip(), "away": r["AwayTeam"].strip(),
                    "hg": hg, "ag": ag, "xg_h": _num(r, "HxG"), "xg_a": _num(r, "AxG"),
                    "odds": _first(r, ODDS_1X2), "ou": _first(r, ODDS_OU)})
    return out


def history(years, refresh_current=False, fetch=download, current=None):
    """Tous les matchs joués des saisons demandées, triés par date. Renvoie (matchs, erreurs)."""
    current = current if current is not None else season_start()
    matches, errors = [], []
    for league, div in LEAGUES.items():
        for year in years:
            try:
                rows = season_rows(div, year, refresh=refresh_current and year == current, fetch=fetch)
            except Exception as e:  # réseau coupé, fichier absent : on continue avec ce qu'on a
                errors.append(f"{league} {year}-{(year + 1) % 100:02d} : {e}")
                f = CACHE / f"{year % 100:02d}{(year + 1) % 100:02d}_{div}.csv"
                rows = read_csv(f.read_bytes()) if f.exists() else []
            matches += parse(rows, league, year)
    matches.sort(key=lambda m: (m["date"], m["league"], m["home"]))
    return matches, errors


def fixtures(fetch=download):
    """Matchs à venir (journée en cours) des championnats suivis : league, kickoff (heure locale), home, away."""
    by_div = {v: k for k, v in LEAGUES.items()}
    out = []
    for r in read_csv(fetch(f"{BASE}/fixtures.csv")):
        if r.get("Div") in by_div:
            try:
                out.append({"league": by_div[r["Div"]], "kickoff": _when(r), "home": r["HomeTeam"].strip(), "away": r["AwayTeam"].strip()})
            except (KeyError, ValueError):
                continue
    return out
