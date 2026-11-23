"""Test sur le passé, refaisable par tous : python -m src.backtest.run
(télécharge six saisons de football-data.co.uk au premier lancement, environ 30 secondes)

Pour chaque match, l'agent ne connaît que les matchs joués au moins LAG_DAYS jours plus tôt (délai de publication des
données). Ses probabilités sont comparées au résultat réel, au hasard et aux cotes de clôture du marché.
L'erreur est le « log-loss » : plus elle est basse, mieux c'est.
"""
import sys

import numpy as np

from ..engine import ratings
from ..engine.dixon_coles import outcome_probs, over_prob, score_matrices
from ..ingest import footballdata
from ..track import NAIVE

LAG_DAYS = 3
FIRST = 2021  # première saison chargée : sert de rodage, elle n'est pas notée


def loss3(p, y):
    return float(-np.mean(np.log(np.clip(p[np.arange(len(y)), y], 1e-9, 1))))


def loss2(p, hit):
    return float(-np.mean(np.log(np.clip(np.where(hit, p, 1 - p), 1e-9, 1))))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    current = footballdata.season_start()
    hist, errors = footballdata.history(range(FIRST, current + 1), current=current)
    for e in errors:
        print("Attention :", e)
    hist = [m for m in hist if m.get("odds") and m.get("ou")]
    ratings.add_market_goals(hist)
    preds, _ = ratings.walk(hist, lag_days=LAG_DAYS)
    matrices = score_matrices([p[0] for p in preds], [p[1] for p in preds])
    p1x2 = outcome_probs(matrices)
    season = np.array([m["season"] for m in hist])
    goals = np.array([m["hg"] + m["ag"] for m in hist])
    y = np.array([0 if m["hg"] > m["ag"] else 1 if m["hg"] == m["ag"] else 2 for m in hist])
    market = ratings.devig([m["odds"] for m in hist])
    market_over = ratings.devig([m["ou"] for m in hist])[:, 0]
    odds = np.array([m["odds"] for m in hist])
    fr = lambda x, d=3: f"{x:.{d}f}".replace(".", ",")

    for year in (current - 1, current):
        i = season == year
        over, p_over = goals[i] > 2.5, over_prob(matrices[i], 2.5)
        print(f"\nSaison {year}-{(year + 1) % 100:02d} : {int(i.sum())} matchs des 5 championnats")
        print(f"  1N2              : hasard {fr(loss3(np.tile(NAIVE, (int(i.sum()), 1)), y[i]))} | agent {fr(loss3(p1x2[i], y[i]))} | marché {fr(loss3(market[i], y[i]))}")
        print(f"  +/- 2,5 buts     : hasard {fr(loss2(np.full(int(i.sum()), 0.52), over))} | agent {fr(loss2(p_over, over))} | marché {fr(loss2(market_over[i], over))}")
        print(f"  bon pronostic 1N2 : agent {fr(100 * np.mean(p1x2[i].argmax(1) == y[i]), 1)} % | marché {fr(100 * np.mean(market[i].argmax(1) == y[i]), 1)} %")
        ev = p1x2[i] * odds[i] - 1  # parier chaque fois que l'agent croit voir plus de 5 % d'avantage sur la cote de clôture
        pick, best = ev.argmax(1), ev.max(1)
        gain = np.where(pick == y[i], odds[i][np.arange(int(i.sum())), pick] - 1, -1.0)[best > 0.05]
        if len(gain):
            print(f"  parier dès que l'agent voit +5 % d'avantage : {len(gain)} paris, résultat {fr(100 * gain.mean(), 1)} % "
                  f"(± {fr(100 * gain.std() / np.sqrt(len(gain)), 1)})")

    # Fiabilité : quand l'agent annonce x %, est-ce que ça arrive x % du temps ? (toutes les saisons notées, tous les paris)
    i = season > FIRST
    claimed = [p1x2[i].ravel()]
    happened = [np.eye(3)[y[i]].ravel()]
    for line in (1.5, 2.5, 3.5):
        p = over_prob(matrices[i], line)
        claimed += [p, 1 - p]
        happened += [goals[i] > line, goals[i] < line]
    claimed, happened = np.concatenate(claimed), np.concatenate(happened).astype(float)
    print(f"\nFiabilité des chances annoncées ({int(i.sum())} matchs depuis {FIRST + 1}, paris 1N2 et plus/moins de 1,5 / 2,5 / 3,5 buts)")
    for lo in range(0, 100, 10):
        b = (claimed >= lo / 100) & (claimed < (lo + 10) / 100)
        if b.sum() >= 50:
            print(f"  annoncé {lo:>2}-{lo + 10} % : arrivé {fr(100 * happened[b].mean(), 1)} % du temps ({int(b.sum())} paris)")

    # Le « pari le plus probable » affiché par l'appli
    cols = np.concatenate([p1x2[i]] + [np.stack([over_prob(matrices[i], l), 1 - over_prob(matrices[i], l)], 1) for l in (1.5, 2.5, 3.5)], axis=1)
    wins = np.concatenate([np.eye(3)[y[i]]] + [np.stack([goals[i] > l, goals[i] < l], 1) for l in (1.5, 2.5, 3.5)], axis=1)
    top = cols.argmax(1)
    print(f"\nPari le plus probable de chaque match : réussi {fr(100 * wins[np.arange(len(top)), top].mean(), 1)} % du temps "
          f"(annoncé en moyenne {fr(100 * cols.max(1).mean(), 1)} %)")


if __name__ == "__main__":
    main()
