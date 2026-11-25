"""Du match au pronostic : notes des équipes -> buts attendus -> Dixon-Coles -> Monte-Carlo -> probabilités."""
import zlib
from datetime import datetime, timedelta

from ..database import db
from ..ingest import crests, footballdata, lineups, scorers
from . import europe, ratings
from .dixon_coles import score_matrices
from .montecarlo import extras, markets, simulate

FMT = "%Y-%m-%dT%H:%M"
MIN_SEEN = 5  # une équipe vue moins de 5 fois (promu en début de saison) : pronostic marqué « * »


def offline(url):
    """À passer comme `fetch` pour ne lire que les fichiers déjà téléchargés (démarrage de l'appli)."""
    raise OSError("hors ligne")


def build_model(refresh=False, fetch=footballdata.download, today=None):
    """Recalcule les notes depuis l'historique football-data. La saison en cours et la précédente suffisent :
    l'écart sur les buts attendus est inférieur à 0,6 % par rapport à cinq saisons d'historique."""
    season = footballdata.season_start(today)
    history, errors = footballdata.history((season - 1, season), refresh_current=refresh, fetch=fetch, current=season)
    if not history:
        raise RuntimeError("Données football-data indisponibles" + (f" ({errors[0]})" if errors else ""))
    ratings.add_market_goals(history)
    _, state = ratings.walk(history)
    return {"state": state, "season": season, "history": history, "errors": errors, "until": history[-1]["date"]}


def label(market, sel, home, away):
    if market == "1X2":
        return {"H": f"Victoire {home}", "D": "Match nul", "A": f"Victoire {away}"}[sel]
    line = market[2:].replace(".", ",")
    return f"Plus de {line} buts" if sel == "Over" else f"Moins de {line} buts"


def expected_goals(model, m):
    """(buts attendus domicile, extérieur, estimé ?) pour une ligne de match (voir db.UPCOMING)."""
    state, season = model["state"], model["season"]
    if m["competition"] in footballdata.LEAGUES:
        lh, la, seen = ratings.predict(state, m["competition"], season, m["home_fd"] or m["home"], m["away_fd"] or m["away"])
        return lh, la, seen < MIN_SEEN
    rel = lambda fd, league: ratings.relative(state, league, season, fd) if fd else None
    lh, la = europe.expected_goals(europe.strength(m["home"], m["home_league"], rel(m["home_fd"], m["home_league"])),
                                   europe.strength(m["away"], m["away_league"], rel(m["away_fd"], m["away_league"])))
    return lh, la, True


def absent(conn, m):
    """Joueurs annoncés forfaits pour ce match. Information seule : le calcul des chances n'en tient pas compte."""
    sql = "SELECT player FROM absences WHERE team_id = ? AND ABS(julianday(fixture_ts) - julianday(?)) < 0.5 ORDER BY player"
    return {side: [r["player"] for r in conn.execute(sql, (m[side + "_id"], m["kickoff"]))] for side in ("home", "away")}


def usual_goals(model):
    """Buts marqués par match cette saison, par club (noms football-data). Calculé une fois par actualisation."""
    key = ("usual", id(model["history"]))
    if key not in usual_goals.cache:
        usual_goals.cache = {key: None}
        goals, played = {}, {}
        for h in model["history"]:
            if h["season"] == model["season"]:
                for club, g in ((h["home"], h["hg"]), (h["away"], h["ag"])):
                    goals[club], played[club] = goals.get(club, 0) + g, played.get(club, 0) + 1
        usual_goals.cache[key] = {c: goals[c] / played[c] for c in goals if played[c] >= 3}
    return usual_goals.cache[key]


usual_goals.cache = {}


def verdict(conn, model, m, ctx=None):
    """Résultat net d'un match : chances 1N2, pronostic, pari le plus probable, cotes Betclic, absents, logos, composition.
    `ctx` (voir `context`) évite de relire la base pour chaque match d'une liste."""
    ctx = ctx or context(conn)
    lh, la, estimated = expected_goals(model, m)
    # Graine tirée du match lui-même : tous les utilisateurs voient les mêmes chiffres.
    seed = zlib.crc32(f"{m['home']}|{m['away']}|{m['kickoff'][:10]}".encode())
    sims = simulate(score_matrices(lh, la)[0], seed=seed)
    mk = markets(*sims)
    sel, p = max(mk["1X2"].items(), key=lambda kv: kv[1])
    market, tsel, tp = max(((k, s, v) for k, sels in mk.items() for s, v in sels.items()), key=lambda t: t[2])
    odds = {r["selection"]: r["odds"] for r in conn.execute("SELECT selection, odds FROM odds WHERE match_id = ?", (m["id"],))}
    return {
        "id": m["id"], "kickoff": m["kickoff"], "competition": m["competition"], "home": m["home"], "away": m["away"],
        "estimated": estimated, "probs": mk["1X2"], "more": {**extras(*sims), "ou": {k[2:]: v["Over"] for k, v in mk.items() if k.startswith("OU")}},
        "pick": {"label": {"H": f"{m['home']} gagne", "D": "Match nul", "A": f"{m['away']} gagne"}[sel], "p": p, "fair_odds": 1 / p},
        "top": {"label": label(market, tsel, m["home"], m["away"]), "p": tp, "fair_odds": 1 / tp, "market": market, "sel": tsel},
        "odds": odds if len(odds) == 3 else {}, "absent": absent(conn, m),
        "home_crest": crests.crest_id(m["home"], ctx["crests"]), "away_crest": crests.crest_id(m["away"], ctx["crests"]),
        "lineup": ctx["lineups"].get(m["id"]),
        "players": {"home": scorers.likely(ctx["players"], m["home"], lh, usual_goals(model).get(m["home_fd"])),
                    "away": scorers.likely(ctx["players"], m["away"], la, usual_goals(model).get(m["away_fd"]))},
    }


def context(conn):
    """Ce que `verdict` lit dans la base en dehors du match lui-même : logos appris, compositions publiées."""
    return {"crests": db.get(conn, "crest_extra", {}), "lineups": lineups.stored(conn),
            "players": db.get(conn, "players", {}).get("clubs", {})}


def upcoming(conn, model, now=None, days=14):
    """Pronostics de tous les matchs non commencés des `days` prochains jours."""
    now = now or datetime.now()
    rows, ctx = db.rows(conn, db.UPCOMING, (now.strftime(FMT), (now + timedelta(days=days)).strftime(FMT))), context(conn)
    return [verdict(conn, model, m, ctx) for m in rows]
