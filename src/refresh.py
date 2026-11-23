"""Une actualisation complète. Chaque source est indépendante : si l'une échoue, les autres continuent et l'écran le dit.

1. football-data (sans clé) : notes des équipes, scores des matchs joués, calendrier de la journée à venir ;
   fixturedownload (sans clé) : calendrier des deux semaines à venir ;
2. The Odds API (clé facultative) : coupes d'Europe et cotes Betclic ;
3. API-Football (clé facultative) : joueurs forfaits ;
4. journal de preuve : les pronostics du moment sont enregistrés.
"""
from datetime import datetime, timedelta

from . import track
from .database import db
from .engine import pipeline
from .ingest import fixturedownload, footballdata, injuries, odds_api
from .ingest.names import best_match, display

FMT = "%Y-%m-%dT%H:%M"


def sync_footballdata(conn, model, now, fetch=footballdata.download):
    """Clubs de la saison, scores des matchs déjà en base, calendrier à venir. Renvoie (scores enregistrés, erreurs)."""
    current = [m for m in model["history"] if m["season"] == model["season"]]
    ids = {}
    club = lambda league, name: ids.get((league, name)) or ids.setdefault((league, name), db.team_id(conn, display(name), league, name))
    settled = 0
    for m in current:
        home, away = club(m["league"], m["home"]), club(m["league"], m["away"])
        if m["date"] > now - timedelta(days=60):
            settled += conn.execute(
                "UPDATE matches SET hg = ?, ag = ? WHERE home_id = ? AND away_id = ? AND competition = ? AND hg IS NULL "
                "AND ABS(julianday(kickoff) - julianday(?)) < 4", (m["hg"], m["ag"], home, away, m["league"], m["date"].strftime(FMT))).rowcount
    errors = []
    try:
        fixtures = footballdata.fixtures(fetch)
    except Exception:  # réseau, fichier absent : le calendrier déjà en base reste valable
        fixtures = []
        errors.append("Calendrier football-data indisponible pour le moment.")
    for f in fixtures:
        if f["kickoff"] > now:  # un match commencé ne se pronostique plus
            db.match_id(conn, club(f["league"], f["home"]), club(f["league"], f["away"]), f["kickoff"], f["league"])
    conn.commit()
    return settled, errors


def sync_calendar(conn, model, now, fetch=footballdata.download):
    """Deux semaines de calendrier sans clé (fixturedownload.com). Chaque club est rapproché par son nom dans sa ligue ;
    un nom non reconnu est ignoré plutôt que deviné. Renvoie les erreurs lisibles."""
    fixtures, failed = fixturedownload.fixtures(model["season"], now, fetch=fetch)
    clubs = {}
    for r in db.rows(conn, "SELECT id, name, league FROM teams WHERE fd_name IS NOT NULL"):
        clubs.setdefault(r["league"], {})[r["name"]] = r["id"]
    for f in fixtures:
        league = clubs.get(f["league"], {})
        home, away = best_match(f["home"], list(league)), best_match(f["away"], list(league))
        if home and away:
            db.match_id(conn, league[home], league[away], f["kickoff"], f["league"])
    conn.commit()
    return [f"Calendrier des semaines à venir indisponible ({', '.join(failed)})."] if failed else []


def run(conn, model, now=None, fetch=footballdata.download, odds_fetcher=odds_api.fetch, injuries_fetcher=injuries.fetch):
    """Met à jour `model` (dictionnaire partagé avec le serveur) et la base. Renvoie le compte rendu, aussi enregistré
    dans les réglages (clé « status ») pour que l'écran dise de quand datent les données. Lève RuntimeError sans aucune donnée."""
    now = now or datetime.now()
    model.update(pipeline.build_model(refresh=True, fetch=fetch, today=now))
    warnings = []
    if model["errors"]:
        warnings.append(f"football-data : {len(model['errors'])} fichier(s) non mis à jour, les données déjà téléchargées sont utilisées.")
    settled, errors = sync_footballdata(conn, model, now, fetch)
    warnings += errors + sync_calendar(conn, model, now, fetch)
    status = {"refreshed_at": now.strftime(FMT), "data_until": model["until"].strftime("%Y-%m-%d"), "settled": settled}
    key = db.get(conn, "odds_api_key")
    if key:
        o = odds_api.sync(conn, key, now, odds_fetcher)
        warnings += o["errors"]
        status.update(credits=o["remaining"], with_odds=o["with_odds"])
    key = db.get(conn, "apifootball_key")
    if key:
        i = injuries.sync(conn, key, now, injuries_fetcher)
        warnings += i["errors"]
        status["absents"] = i["absents"]
    status["logged"] = track.log_predictions(conn, pipeline.upcoming(conn, model, now), now)
    status["warnings"] = list(dict.fromkeys(warnings))  # sans doublons, dans l'ordre
    db.put(conn, "status", status)
    return status
