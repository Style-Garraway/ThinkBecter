"""Base SQLite locale : schéma, connexion, réglages et petites aides d'écriture."""
import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "thinkbecter.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL,
    league TEXT,   -- championnat national (NULL pour un club hors des 5 championnats)
    fd_name TEXT   -- nom du club chez football-data.co.uk (NULL s'il n'y est pas)
);
CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY, home_id INTEGER NOT NULL REFERENCES teams(id), away_id INTEGER NOT NULL REFERENCES teams(id),
    kickoff TEXT NOT NULL, competition TEXT NOT NULL,
    hg INTEGER, ag INTEGER   -- score final, NULL tant que le match n'est pas joué (ou que le résultat n'est pas arrivé)
);
CREATE TABLE IF NOT EXISTS odds (
    match_id INTEGER NOT NULL, selection TEXT NOT NULL, odds REAL NOT NULL, PRIMARY KEY (match_id, selection)
);
CREATE TABLE IF NOT EXISTS odds_history (match_id INTEGER NOT NULL, selection TEXT NOT NULL, odds REAL NOT NULL, ts TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY, match_id INTEGER NOT NULL, ts TEXT NOT NULL, p_h REAL, p_d REAL, p_a REAL,
    top_market TEXT, top_sel TEXT, top_p REAL, odds_h REAL, odds_d REAL, odds_a REAL
);
CREATE TABLE IF NOT EXISTS absences (team_id INTEGER NOT NULL, player TEXT NOT NULL, reason TEXT, fixture_ts TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""
SECRET_KEYS = ("odds_api_key", "apifootball_key")  # ne quittent jamais la base (ni vers l'écran, ni vers le journal)


def connect(path=DB_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get(conn, key, default=None):
    r = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return json.loads(r["value"]) if r else default


def put(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, json.dumps(value)))
    conn.commit()


def team_id(conn, name, league=None, fd_name=None):
    """Identifiant du club, créé s'il n'existe pas. Un club retrouvé chez football-data reçoit son championnat du moment."""
    r = conn.execute("SELECT id FROM teams WHERE name = ?", (name,)).fetchone()
    if not r:
        return conn.execute("INSERT INTO teams (name, league, fd_name) VALUES (?, ?, ?)", (name, league, fd_name)).lastrowid
    if fd_name:
        conn.execute("UPDATE teams SET league = ?, fd_name = ? WHERE id = ?", (league, fd_name, r["id"]))
    return r["id"]


def match_id(conn, home_id, away_id, kickoff, competition):
    """Le match non joué entre ces deux clubs (même compétition, à moins de 4 jours), créé s'il n'existe pas.
    L'heure est mise à jour : les matchs sont souvent reprogrammés."""
    kick = kickoff.strftime("%Y-%m-%dT%H:%M")
    r = conn.execute("SELECT id FROM matches WHERE home_id = ? AND away_id = ? AND competition = ? AND hg IS NULL "
                     "AND ABS(julianday(kickoff) - julianday(?)) < 4", (home_id, away_id, competition, kick)).fetchone()
    if r:
        conn.execute("UPDATE matches SET kickoff = ? WHERE id = ?", (kick, r["id"]))
        return r["id"]
    return conn.execute("INSERT INTO matches (home_id, away_id, kickoff, competition) VALUES (?, ?, ?, ?)",
                        (home_id, away_id, kick, competition)).lastrowid


MATCH = """
SELECT m.id, m.kickoff, m.competition, h.id home_id, a.id away_id, h.name home, a.name away,
       h.fd_name home_fd, a.fd_name away_fd, h.league home_league, a.league away_league
FROM matches m JOIN teams h ON h.id = m.home_id JOIN teams a ON a.id = m.away_id
"""
UPCOMING = MATCH + "WHERE m.hg IS NULL AND m.kickoff > ? AND m.kickoff <= ? ORDER BY m.kickoff, m.competition, h.name"
BY_ID = MATCH + "WHERE m.id = ?"
