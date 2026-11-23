"""Journal de preuve : chaque actualisation enregistre les pronostics des matchs à venir (jamais modifiés ensuite).
Une fois les matchs joués, on compare au résultat réel, au hasard et aux cotes Betclic relevées au même moment.
Seuls les championnats reçoivent leurs résultats (football-data) : les matchs de coupe ne sont pas notés."""
import numpy as np

from .database import db
from .engine.ratings import devig
from .ingest.footballdata import LEAGUES

NAIVE = np.array([0.45, 0.25, 0.30])  # fréquences habituelles : victoire à domicile, nul, victoire à l'extérieur


def log_predictions(conn, verdicts, now):
    ts = now.strftime("%Y-%m-%dT%H:%M")
    for v in verdicts:
        o, top = v["odds"], v["top"]
        conn.execute("INSERT INTO predictions (match_id, ts, p_h, p_d, p_a, top_market, top_sel, top_p, odds_h, odds_d, odds_a) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (v["id"], ts, v["probs"]["H"], v["probs"]["D"], v["probs"]["A"], top["market"], top["sel"], top["p"],
                      o.get("H"), o.get("D"), o.get("A")))
    conn.commit()
    return len(verdicts)


def won(market, sel, hg, ag):
    if market == "1X2":
        return {"H": hg > ag, "D": hg == ag, "A": hg < ag}[sel]
    return (hg + ag > float(market[2:])) == (sel == "Over")


def summary(conn):
    """Bilan des matchs joués, sur le dernier pronostic enregistré AVANT le coup d'envoi (log-loss : plus bas = mieux)."""
    marks = ",".join("?" * len(LEAGUES))
    rows = db.rows(conn, f"""
        SELECT p.*, m.hg, m.ag FROM predictions p JOIN matches m ON m.id = p.match_id
        WHERE m.hg IS NOT NULL AND p.ts = (SELECT MAX(ts) FROM predictions q WHERE q.match_id = p.match_id AND q.ts < m.kickoff)
        GROUP BY p.match_id""")
    pending = conn.execute(f"SELECT COUNT(DISTINCT p.match_id) FROM predictions p JOIN matches m ON m.id = p.match_id "
                           f"WHERE m.hg IS NULL AND m.competition IN ({marks})", tuple(LEAGUES)).fetchone()[0]
    out = {"n": len(rows), "pending": pending}
    if not rows:
        return out
    y = np.array([0 if r["hg"] > r["ag"] else 1 if r["hg"] == r["ag"] else 2 for r in rows])
    p = np.array([[r["p_h"], r["p_d"], r["p_a"]] for r in rows])
    loss = lambda q, yy: float(-np.mean(np.log(np.clip(q[np.arange(len(yy)), yy], 1e-9, 1))))
    out.update(model=loss(p, y), naive=loss(np.tile(NAIVE, (len(y), 1)), y), pick_hit=float(np.mean(p.argmax(1) == y)),
               top_hit=float(np.mean([won(r["top_market"], r["top_sel"], r["hg"], r["ag"]) for r in rows])),
               top_claimed=float(np.mean([r["top_p"] for r in rows])))
    with_odds = [i for i, r in enumerate(rows) if r["odds_h"]]
    if with_odds:
        book = devig([[rows[i]["odds_h"], rows[i]["odds_d"], rows[i]["odds_a"]] for i in with_odds])
        out.update(with_market=len(with_odds), model_same=loss(p[with_odds], y[with_odds]), market=loss(book, y[with_odds]))
    return out
