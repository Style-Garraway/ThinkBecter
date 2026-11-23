"""Auto-vérifications, sans internet : python -m unittest discover tests

Les sources (football-data, The Odds API, API-Football) sont remplacées par de faux mini-championnats de 4 équipes.
"""
import json
import re
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from src import refresh, track
from src.database import db
from src.engine import europe, pipeline, ratings
from src.engine.dixon_coles import outcome_probs, over_prob, score_matrices
from src.engine.montecarlo import markets, simulate
from src.ingest import footballdata, injuries, odds_api
from src.ingest.names import best_match, display

NOW = datetime(2026, 11, 20, 12, 0)
TEAMS = {"E0": ["Arsenal", "Chelsea", "Liverpool", "Man City"], "SP1": ["Barcelona", "Real Madrid", "Sevilla", "Valencia"],
         "D1": ["Bayern Munich", "Dortmund", "Mainz", "Stuttgart"], "I1": ["Inter", "Juventus", "Milan", "Roma"],
         "F1": ["Lille", "Lyon", "Marseille", "Paris SG"]}
HEADER = "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,AvgCH,AvgCD,AvgCA,AvgC>2.5,AvgC<2.5,HxG,AxG"


def season_csv(div, year, played, extra=""):
    """Chaque équipe reçoit les trois autres, un match par semaine. La première de la liste est la plus forte ;
    en 2026, la dernière d'Angleterre est remplacée par un promu (Leeds)."""
    teams = list(TEAMS[div])
    if div == "E0" and year == 2026:
        teams[3] = "Leeds"
    lines, day = [HEADER], datetime(year, 8, 15)
    pairs = [(h, a) for h in teams for a in teams if h != a]
    for h, a in pairs[:played]:
        gap = teams.index(a) - teams.index(h)  # > 0 : l'équipe à domicile est la plus forte
        home = {3: 1.25, 2: 1.45, 1: 1.80, -1: 2.60, -2: 3.40, -3: 4.50}[gap]
        away = {3: 11.0, 2: 6.50, 1: 4.20, -1: 2.55, -2: 2.05, -3: 1.70}[gap]
        lines.append(f"{div},{day:%d/%m/%Y},15:00,{h},{a},{2 if gap > 0 else 1},{0 if gap > 0 else 1},{home},3.80,{away},1.85,1.95,1.4,0.9")
        day += timedelta(days=7)
    return ("\n".join(lines) + "\n" + extra).encode()


class FakeFootballData:
    """Remplace le téléchargement : sert les faux fichiers de saison et le calendrier."""
    def __init__(self):
        self.extra = ""  # lignes ajoutées à la saison 2026 de Premier League (résultat qui « arrive »)
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        if "fixturedownload" in url:  # calendrier long : un doublon du match du 22, un nouveau match, un club inconnu, un match lointain
            game = lambda date, home, away: {"DateUtc": date, "HomeTeam": home, "AwayTeam": away, "HomeTeamScore": None}
            return json.dumps([game("2026-11-22 15:00:00Z", "Arsenal", "Chelsea"), game("2026-11-28 15:00:00Z", "Liverpool", "Arsenal"),
                               game("2026-11-29 15:00:00Z", "Spurs", "Arsenal"), game("2027-01-10 15:00:00Z", "Chelsea", "Liverpool"),
                               {"DateUtc": None}] if "/epl-2026" in url else []).encode()
        if url.endswith("fixtures.csv"):
            return (HEADER + "\nE0,22/11/2026,15:00,Arsenal,Chelsea,,,,,,,,,\nE0,22/11/2026,17:30,Leeds,Liverpool,,,,,,,,,\n"
                    "E0,01/11/2026,15:00,Chelsea,Arsenal,,,,,,,,,\nXX,22/11/2026,15:00,Ailleurs,Autre,,,,,,,,,\n").encode()
        code, div = re.search(r"mmz4281/(\d{4})/(\w+)\.csv", url).groups()
        year = 2000 + int(code[:2])
        return season_csv(div, year, 6 if year == 2026 else 12, self.extra if (div, year) == ("E0", 2026) else "")


class Maths(unittest.TestCase):
    def test_dixon_coles(self):
        m, indep = score_matrices(1.5, 1.2), score_matrices(1.5, 1.2, rho=0.0)
        self.assertAlmostEqual(float(m.sum()), 1.0)
        self.assertGreater(m[0, 0, 0], indep[0, 0, 0])  # rho < 0 : plus de 0-0 et de 1-1 que deux Poisson indépendants
        self.assertGreater(m[0, 1, 1], indep[0, 1, 1])
        self.assertAlmostEqual(float(outcome_probs(m).sum()), 1.0)
        # la correction ne déplace des probabilités qu'entre des scores de 2 buts ou moins : plus de 2,5 buts reste du Poisson pur
        t = 2.7
        self.assertAlmostEqual(float(over_prob(m, 2.5)[0]), 1 - np.exp(-t) * (1 + t + t * t / 2), places=5)

    def test_market_odds_round_trip(self):
        m = score_matrices(1.7, 1.1)
        total = ratings.total_from_over(over_prob(m, 2.5))
        lh, la = ratings.implied_goals(outcome_probs(m), total)
        self.assertAlmostEqual(float(lh[0]), 1.7, places=3)
        self.assertAlmostEqual(float(la[0]), 1.1, places=3)
        self.assertAlmostEqual(float(ratings.devig([2.0, 3.4, 3.8]).sum()), 1.0)

    def test_monte_carlo_matches_matrix(self):
        m = score_matrices(1.6, 1.1)
        mk = markets(*simulate(m[0], seed=1))
        self.assertAlmostEqual(mk["1X2"]["H"], float(outcome_probs(m)[0, 0]), delta=0.02)
        self.assertAlmostEqual(sum(mk["1X2"].values()), 1.0)
        self.assertAlmostEqual(mk["OU2.5"]["Over"] + mk["OU2.5"]["Under"], 1.0)
        self.assertEqual(mk, markets(*simulate(m[0], seed=1)))  # même graine : mêmes chiffres


class Ratings(unittest.TestCase):
    def history(self):
        out = []
        for year in (2025, 2026):
            out += footballdata.parse(footballdata.read_csv(season_csv("E0", year, 12)), "Premier League", year)
        ratings.add_market_goals(out)
        return out

    def test_learns_who_is_strong(self):
        h = self.history()
        _, state = ratings.walk(h)
        lh, la, seen = ratings.predict(state, "Premier League", 2026, "Arsenal", "Liverpool")
        self.assertGreater(lh, la * 1.5)  # Arsenal (le plus fort) reçoit Liverpool (3e)
        self.assertGreaterEqual(seen, 5)
        rel = ratings.relative(state, "Premier League", 2026, "Arsenal")
        self.assertGreater(rel[0], 1.0)   # attaque au-dessus de la moyenne de la ligue
        self.assertLess(rel[1], 1.0)      # défense qui encaisse moins que la moyenne
        self.assertIsNone(ratings.relative(state, "Premier League", 2026, "Inconnu"))

    def test_never_uses_the_future(self):
        h = self.history()
        full, _ = ratings.walk(h)
        cut, _ = ratings.walk(h[:15])
        self.assertEqual(full[:15], cut)  # la prévision d'un match ne dépend d'aucun match joué après lui
        lagged, _ = ratings.walk(h, lag_days=3000)
        self.assertTrue(all(p[:2] == lagged[0][:2] for p in lagged[:12]))  # avec un délai énorme, rien n'est jamais appris

    def test_promoted_team_starts_below_average(self):
        h = self.history()
        first = next(i for i, m in enumerate(h) if "Leeds" in (m["home"], m["away"]))
        _, state = ratings.walk(h[:first])  # tout ce qui précède le premier match du promu
        m = h[first]
        self.assertEqual(ratings.predict(state, m["league"], m["season"], m["home"], m["away"])[2], 0)
        self.assertEqual(state["teams"][("Premier League", "Leeds")], {"a": 1 / ratings.PROMO, "d": ratings.PROMO, "n": 0})
        self.assertNotEqual(state["teams"][("Premier League", "Arsenal")]["a"], 1.0)  # un ancien garde ses notes
        self.assertNotIn("Man City", state["members"][("Premier League", 2026)])


class Names(unittest.TestCase):
    def test_matching(self):
        clubs = ["AC Milan", "Inter Milan", "Paris FC", "Paris Saint Germain", "TSG Hoffenheim", "Bayern Munich", "Athletic Bilbao",
                 "Brest", "Tottenham Hotspur", "Manchester City", "Manchester United", "Real Racing Club de Santander", "1. FC Köln"]
        for name, want in (("Milan", "AC Milan"), ("Inter", "Inter Milan"), ("Paris FC", "Paris FC"), ("1899 Hoffenheim", "TSG Hoffenheim"),
                           ("Bayern München", "Bayern Munich"), ("Athletic Club", "Athletic Bilbao"), ("Stade Brestois 29", "Brest"),
                           ("Tottenham", "Tottenham Hotspur"), ("Racing Santander", "Real Racing Club de Santander"), ("FC Koln", "1. FC Köln"),
                           ("Manchester", None), ("Olympiakos", None)):
            self.assertEqual(best_match(name, clubs), want, name)
        self.assertEqual(display("Man United"), "Manchester United")
        self.assertEqual(display("Arsenal"), "Arsenal")


class FootballData(unittest.TestCase):
    def test_parse(self):
        raw = (HEADER + "\nE0,25/10/2026,14:00,Monaco,Lille,1,1,2.10,3.50,3.60,1.80,2.05,2.35,0.75\n"
               "E0,26/10/26,20:00,Lens,Nice,,,2.0,3.4,3.9,,,,\n").encode()
        rows = footballdata.parse(footballdata.read_csv(raw), "Ligue 1", 2026)
        self.assertEqual(len(rows), 1)  # le match sans score n'est pas « joué »
        m = rows[0]
        self.assertEqual((m["home"], m["hg"], m["ag"], m["odds"], m["ou"], m["xg_h"]), ("Monaco", 1, 1, (2.10, 3.50, 3.60), (1.80, 2.05), 2.35))

    def test_uk_time(self):
        to_utc = lambda d: footballdata.uk_to_local(d).astimezone(timezone.utc).replace(tzinfo=None)
        self.assertEqual(to_utc(datetime(2026, 12, 5, 15, 0)), datetime(2026, 12, 5, 15, 0))   # hiver : heure de Londres = UTC
        self.assertEqual(to_utc(datetime(2026, 8, 15, 15, 0)), datetime(2026, 8, 15, 14, 0))   # été : UTC + 1
        self.assertEqual(to_utc(datetime(2026, 10, 25, 14, 0)), datetime(2026, 10, 25, 14, 0))  # jour du passage à l'heure d'hiver
        self.assertEqual(footballdata.season_start(datetime(2027, 3, 1)), 2026)
        self.assertEqual(footballdata.season_start(datetime(2027, 7, 1)), 2027)


class App(unittest.TestCase):
    """Parcours complet sur une base et un dossier de cache temporaires."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache, footballdata.CACHE = footballdata.CACHE, Path(self.tmp.name) / "fd"
        self.addCleanup(setattr, footballdata, "CACHE", self.cache)
        self.conn = db.connect(Path(self.tmp.name) / "t.db")
        self.addCleanup(self.conn.close)  # Windows refuse de supprimer le dossier tant que la base est ouverte
        self.fd, self.model = FakeFootballData(), {}

    def run_refresh(self, now=NOW, **kw):
        return refresh.run(self.conn, self.model, now=now, fetch=self.fd, **kw)

    def test_first_launch_without_any_key(self):
        with self.assertRaises(RuntimeError):
            pipeline.build_model(fetch=pipeline.offline, today=NOW)  # ni cache ni réseau : erreur claire
        status = self.run_refresh()
        self.assertEqual(status["warnings"], [])
        self.assertEqual(status["data_until"], "2026-09-19")
        names = {r["name"] for r in db.rows(self.conn, "SELECT name FROM teams")}
        self.assertTrue({"Arsenal", "Leeds United", "Paris Saint Germain", "Inter Milan"} <= names)
        self.assertNotIn("Man City", names)
        self.assertEqual(pipeline.build_model(fetch=pipeline.offline, today=NOW)["until"], self.model["until"])  # relancé hors ligne : le cache suffit
        verdicts = pipeline.upcoming(self.conn, self.model, NOW)
        self.assertEqual([(v["home"], v["away"]) for v in verdicts],  # ni le match passé, ni l'autre ligue, ni le club inconnu, ni le match lointain
                         [("Arsenal", "Chelsea"), ("Leeds United", "Liverpool"), ("Liverpool", "Arsenal")])
        arsenal, leeds, _ = verdicts
        self.assertAlmostEqual(sum(arsenal["probs"].values()), 1.0)
        self.assertGreater(arsenal["probs"]["H"], 0.5)
        self.assertFalse(arsenal["estimated"])
        self.assertTrue(leeds["estimated"])  # promu : 3 matchs vus seulement
        self.assertGreaterEqual(arsenal["top"]["p"], arsenal["pick"]["p"])
        self.assertEqual((arsenal["odds"], arsenal["absent"]), ({}, {"home": [], "away": []}))
        self.assertEqual(status["logged"], 3)
        self.assertEqual(self.run_refresh()["logged"], 3)  # une 2e actualisation ne duplique aucun match
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0], 3)

    def test_journal_scores_predictions_once_results_arrive(self):
        self.run_refresh()
        self.assertEqual(track.summary(self.conn), {"n": 0, "pending": 3})
        p_home = self.conn.execute("SELECT p.p_h FROM predictions p JOIN matches m ON m.id = p.match_id JOIN teams h ON h.id = m.home_id "
                                   "WHERE h.name = 'Arsenal'").fetchone()[0]
        self.fd.extra = "E0,22/11/2026,15:00,Arsenal,Chelsea,2,0,1.80,3.80,4.20,1.85,1.95,1.9,0.6\n"
        status = self.run_refresh(now=NOW + timedelta(days=5))
        self.assertEqual(status["settled"], 1)
        s = track.summary(self.conn)
        self.assertEqual((s["n"], s["pending"]), (1, 2))
        self.assertAlmostEqual(s["model"], -np.log(p_home), places=6)  # victoire à domicile : erreur = -log(chance annoncée)
        self.assertEqual(s["pick_hit"], 1.0)
        self.assertNotIn("market", s)  # aucune cote Betclic relevée : pas de comparaison au marché

    def test_keeps_working_when_the_source_is_down(self):
        self.run_refresh()

        def down(url):
            raise OSError("panne")
        status = refresh.run(self.conn, self.model, now=NOW + timedelta(hours=1), fetch=down)
        self.assertEqual(len(status["warnings"]), 3)  # données et les deux calendriers non mis à jour : dit à l'écran, sans planter
        self.assertEqual(len(pipeline.upcoming(self.conn, self.model, NOW)), 3)

    def test_betclic_odds_and_european_cups(self):
        self.run_refresh()
        self.conn.execute("INSERT OR REPLACE INTO settings VALUES ('odds_api_key', '\"cle\"')")
        book = lambda key, h, d, a, home, away: {"key": key, "markets": [{"key": "h2h", "outcomes": [
            {"name": home, "price": h}, {"name": away, "price": a}, {"name": "Draw", "price": d}]}]}
        events = {
            "soccer_epl": [
                {"home_team": "Arsenal", "away_team": "Chelsea FC", "commence_time": "2026-11-22T15:30:00Z",
                 "bookmakers": [book("winamax_fr", 9, 9, 9, "Arsenal", "Chelsea FC"), book("betclic_fr", 1.7, 3.9, 4.8, "Arsenal", "Chelsea FC")]},
                {"home_team": "Liverpool", "away_team": "Arsenal", "commence_time": "2026-11-19T15:00:00Z", "bookmakers": []}],  # déjà commencé
            "soccer_uefa_champs_league": [
                {"home_team": "Benfica", "away_team": "Arsenal", "commence_time": "2026-11-25T20:00:00Z", "bookmakers": []}],
        }
        status = self.run_refresh(odds_fetcher=lambda key, sport: (events.get(sport, []), "450"))
        self.assertEqual((status["credits"], status["with_odds"], status["warnings"]), ("450", 1, []))
        by_home = {v["home"]: v for v in pipeline.upcoming(self.conn, self.model, NOW)}
        self.assertEqual(by_home["Arsenal"]["odds"], {"H": 1.7, "D": 3.9, "A": 4.8})  # Betclic, pas l'autre bookmaker ; « Chelsea FC » = Chelsea
        self.assertEqual(by_home["Arsenal"]["kickoff"][:10], "2026-11-22")
        self.assertEqual(len(by_home), 4)  # le match de coupe s'ajoute, le match commencé non, aucun doublon
        cup = by_home["Benfica"]
        self.assertTrue(cup["estimated"])
        self.assertGreater(cup["probs"]["A"], cup["probs"]["H"])  # Arsenal, meilleure équipe de sa ligue, favori à l'extérieur
        self.assertEqual(self.conn.execute("SELECT league FROM teams WHERE name = 'Benfica'").fetchone()[0], None)

        def refused(key, sport):
            raise urllib.error.HTTPError("u", 401, "Unauthorized", None, None)
        status = self.run_refresh(odds_fetcher=refused)
        self.assertEqual(status["warnings"], [odds_api.HTTP_ERRORS[401]])  # un seul message, et l'appli continue

    def test_absences_are_shown_but_do_not_move_the_odds(self):
        self.run_refresh()
        before = pipeline.upcoming(self.conn, self.model, NOW)[0]
        self.conn.execute("INSERT OR REPLACE INTO settings VALUES ('apifootball_key', '\"cle\"')")
        item = lambda league, team, player, kind, reason="Knee Injury": {
            "league": {"id": league}, "team": {"name": team}, "fixture": {"date": "2026-11-22T15:00:00+00:00"},
            "player": {"name": player, "type": kind, "reason": reason}}
        answers = {"errors": [], "response": [item(39, "Arsenal", "B. Saka", "Missing Fixture"), item(39, "Arsenal", "M. Odegaard", "Questionable"),
                                               item(39, "Arsenal", "R. Reserve", "Missing Fixture", "Off the roster"),
                                               item(128, "Arsenal Sarandi", "J. Autre", "Missing Fixture"), item(39, "Chelsea", "C. Palmer", "Missing Fixture")]}
        status = self.run_refresh(injuries_fetcher=lambda key, date: answers)
        self.assertEqual(status["absents"], 2)
        after = pipeline.upcoming(self.conn, self.model, NOW)[0]
        self.assertEqual(after["absent"], {"home": ["B. Saka"], "away": ["C. Palmer"]})  # ni l'incertain, ni le non-inscrit, ni l'homonyme argentin
        self.assertEqual(after["probs"], before["probs"])
        status = self.run_refresh(injuries_fetcher=lambda key, date: {"errors": {"plan": "Free plans do not have access to this date"}, "response": []})
        self.assertEqual(len(status["warnings"]), 1)
        self.assertEqual(pipeline.upcoming(self.conn, self.model, NOW)[0]["absent"]["home"], ["B. Saka"])  # liste gardée si l'API ne répond pas

    def test_european_strength(self):
        strong, weak = europe.strength("Arsenal", "Premier League", (1.2, 0.8)), europe.strength("Inconnu FC", None, None)
        self.assertEqual(weak, (europe.DEFAULT, 1 / europe.DEFAULT))
        self.assertLessEqual(europe.strength("FC Copenhagen", None, None)[0], europe.MAX_CLUB)
        lh, la = europe.expected_goals(strong, weak)
        self.assertGreater(lh, la * 2)


class Server(unittest.TestCase):
    def test_only_the_app_page_may_call_the_api(self):
        from src.api.server import allowed
        self.assertTrue(allowed("127.0.0.1:8765", None))                       # la fenêtre de l'appli (requête simple)
        self.assertTrue(allowed("127.0.0.1:8765", "http://127.0.0.1:8765"))    # la page de l'appli
        self.assertFalse(allowed("127.0.0.1:8765", "https://site-malveillant.example"))
        self.assertFalse(allowed("faux-domaine.example:8765", None))           # nom de domaine pointant vers 127.0.0.1


if __name__ == "__main__":
    unittest.main()
