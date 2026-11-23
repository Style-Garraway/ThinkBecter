"""Notes d'attaque et de défense de chaque équipe, apprises match après match sur les matchs PASSÉS.

Signal utilisé : les buts attendus par le marché pour chaque match déjà joué, déduits des cotes de clôture (1N2 et
plus/moins de 2,5 buts). Chaque note est un lissage exponentiel (le match le plus récent pèse le plus), corrigé de la
force de l'adversaire. Aucune cote du match à pronostiquer n'est utilisée : seulement ce qu'on savait avant lui.
Les xG et les buts réels ont été essayés comme signaux supplémentaires : ils n'apportent rien (voir CLAUDE.md).
"""
from datetime import timedelta

import numpy as np

from .dixon_coles import RHO, outcome_probs, score_matrices

# Valeurs choisies par le test sur le passé (python -m src.backtest.run) ; ne pas les changer sans le refaire.
K = 0.3       # part de la nouvelle information après chaque match
K_EARLY, N_EARLY = 0.5, 4  # apprentissage plus rapide sur les 4 premiers matchs de chaque saison (effectifs changés)
K_HOME = 0.05  # vitesse d'apprentissage de l'avantage du terrain propre à chaque club
SPREAD = 1.12  # écart entre les deux équipes amplifié (le lissage rend les notes trop prudentes) ; total de buts inchangé
K_MU = 0.01   # idem pour les moyennes de buts de la ligue
PROMO = 1.15  # un promu démarre avec une attaque à 1/1,15 et une défense à 1,15 (1 = équipe moyenne)
START_MU = (1.5, 1.2)  # buts moyens domicile / extérieur avant d'avoir vu des matchs


def devig(odds):
    """Cotes d'un même marché -> probabilités sans la marge du bookmaker (méthode proportionnelle)."""
    inv = 1.0 / np.asarray(odds, float)
    return inv / inv.sum(axis=-1, keepdims=True)


def total_from_over(p_over):
    """Nombre de buts attendu T tel que P(plus de 2,5 buts) = p_over sous une loi de Poisson (recherche par dichotomie)."""
    p = np.asarray(p_over, float)
    lo, hi = np.full(p.shape, 0.2), np.full(p.shape, 9.0)
    for _ in range(50):
        mid = (lo + hi) / 2
        below = 1 - np.exp(-mid) * (1 + mid + mid ** 2 / 2) < p
        lo, hi = np.where(below, mid, lo), np.where(below, hi, mid)
    return (lo + hi) / 2


def implied_goals(p1x2, total, rho=RHO):
    """Buts attendus (domicile, extérieur) qui reproduisent l'écart P(1) - P(2) du marché pour un total donné."""
    p1x2, total = np.asarray(p1x2, float), np.asarray(total, float)
    target = p1x2[:, 0] - p1x2[:, 2]
    lo, hi = np.full(total.shape, 0.02), np.full(total.shape, 0.98)
    for _ in range(40):
        mid = (lo + hi) / 2
        pr = outcome_probs(score_matrices(total * mid, total * (1 - mid), rho))
        below = pr[:, 0] - pr[:, 2] < target
        lo, hi = np.where(below, mid, lo), np.where(below, hi, mid)
    share = (lo + hi) / 2
    return total * share, total * (1 - share)


def add_market_goals(matches):
    """Ajoute m["mkt"] = buts attendus par le marché à chaque match qui a des cotes 1N2.
    Sans cote plus/moins de 2,5 buts, le total est la moyenne de sa ligue."""
    rows = [m for m in matches if m.get("odds")]
    if not rows:
        return
    p = devig([m["odds"] for m in rows])
    over = np.array([devig(m["ou"])[0] if m.get("ou") else np.nan for m in rows])
    total = np.where(np.isnan(over), np.nan, total_from_over(np.nan_to_num(over, nan=0.5)))
    for league in {m["league"] for m in rows}:
        idx = np.array([m["league"] == league for m in rows])
        known = total[idx & ~np.isnan(total)]
        total[idx & np.isnan(total)] = known.mean() if len(known) else sum(START_MU)
    lh, la = implied_goals(p, total)
    for m, h, a in zip(rows, lh, la):
        m["mkt"] = (float(h), float(a))


def new_state():
    return {"teams": {}, "mu": {}, "members": {}, "home": {}}


def _team(state, league, season, name):
    """Notes de l'équipe : a = attaque, d = défense (plus grand = encaisse plus), n = matchs vus, ns = vus cette saison.
    À sa première apparition dans une saison, un promu (absent la saison d'avant) repart sous la moyenne."""
    key, members = (league, name), state["members"]
    cur = members.setdefault((league, season), set())
    if name not in cur:
        cur.add(name)
        prev = members.get((league, season - 1))
        if prev and name not in prev:
            state["teams"][key] = {"a": 1 / PROMO, "d": PROMO, "n": 0, "ns": 0}
        elif key in state["teams"]:
            state["teams"][key]["ns"] = 0
    return state["teams"].setdefault(key, {"a": 1.0, "d": 1.0, "n": 0, "ns": 0})


def _raw(state, league, season, home, away):
    """Buts attendus bruts, sans l'avantage du terrain propre au club ni l'amplification de l'écart."""
    th, ta = _team(state, league, season, home), _team(state, league, season, away)
    mu = state["mu"].setdefault(league, list(START_MU))
    return mu[0] * th["a"] * ta["d"], mu[1] * ta["a"] * th["d"], min(th["n"], ta["n"])


def predict(state, league, season, home, away):
    """Buts attendus (domicile, extérieur) d'un match, et nombre de matchs déjà vus par l'équipe la moins connue."""
    lh, la, seen = _raw(state, league, season, home, away)
    g = float(np.exp(state["home"].get((league, home), 0.0)))
    lh, la = lh * g, la / g
    total, share = lh + la, 1 / (1 + (la / lh) ** SPREAD)
    return total * share, total * (1 - share), seen


def relative(state, league, season, name):
    """(attaque, défense) de l'équipe rapportées à la moyenne de sa ligue cette saison : 1 = équipe moyenne.
    Sert à comparer des clubs de ligues différentes (coupes d'Europe). None si l'équipe n'y a pas encore joué."""
    names = state["members"].get((league, season), ())
    if name not in names:
        return None
    mean = lambda k: float(np.exp(np.mean([np.log(state["teams"][(league, n)][k]) for n in names])))
    t = state["teams"][(league, name)]
    return t["a"] / mean("a"), t["d"] / mean("d")


def update(state, m):
    """Après un match joué : chaque note se rapproche de ce que le marché en attendait, compte tenu de l'adversaire."""
    if not m.get("mkt"):
        return
    (oh, oa), clip = m["mkt"], lambda x: min(max(x, 0.0), 4.0)
    # Avantage du terrain du club : part de l'écart au marché que les notes générales n'expliquent pas.
    h0, a0, _ = _raw(state, m["league"], m["season"], m["home"], m["away"])
    key = (m["league"], m["home"])
    resid = 0.5 * (np.log(oh / h0) - np.log(oa / a0))
    state["home"][key] = state["home"].get(key, 0.0) + K_HOME * (resid - state["home"].get(key, 0.0))
    th, ta = _team(state, m["league"], m["season"], m["home"]), _team(state, m["league"], m["season"], m["away"])
    mu = state["mu"].setdefault(m["league"], list(START_MU))
    kh = K_EARLY if th["ns"] < N_EARLY else K
    ka = K_EARLY if ta["ns"] < N_EARLY else K
    ah, dh, aa, da = th["a"], th["d"], ta["a"], ta["d"]
    th["a"] = ah + kh * (clip(oh / (mu[0] * da)) - ah)
    ta["d"] = da + ka * (clip(oh / (mu[0] * ah)) - da)
    ta["a"] = aa + ka * (clip(oa / (mu[1] * dh)) - aa)
    th["d"] = dh + kh * (clip(oa / (mu[1] * aa)) - dh)
    mu[0] += K_MU * (oh - mu[0])
    mu[1] += K_MU * (oa - mu[1])
    for t in (th, ta):
        t["n"] += 1
        t["ns"] += 1


def walk(matches, lag_days=0.0):
    """Parcourt les matchs joués dans l'ordre des dates. Pour chacun : la prévision faite AVANT lui (λ dom, λ ext, n),
    en ne connaissant que les matchs joués au moins `lag_days` jours plus tôt. Renvoie (prévisions, état final)."""
    state, preds, j, lag = new_state(), [], 0, timedelta(days=lag_days)
    for i, m in enumerate(matches):
        while j < i and matches[j]["date"] + lag < m["date"]:
            update(state, matches[j])
            j += 1
        preds.append(predict(state, m["league"], m["season"], m["home"], m["away"]))
    for m in matches[j:]:
        update(state, m)
    return preds, state
