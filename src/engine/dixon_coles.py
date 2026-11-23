"""Modèle de Dixon-Coles : deux lois de Poisson corrigées sur les petits scores (0-0, 1-0, 0-1, 1-1)."""
import math

import numpy as np

RHO = -0.08
G = 11  # scores de 0 à 10 buts
LOG_FACT = np.array([math.lgamma(k + 1) for k in range(G)])
_I, _J = np.indices((G, G))


def score_matrices(lh, la, rho=RHO):
    """Probabilité de chaque score pour N matchs d'un coup : tableau (N, 11, 11), lignes = buts domicile."""
    lh, la = np.atleast_1d(np.asarray(lh, float)), np.atleast_1d(np.asarray(la, float))
    g = np.arange(G)
    pmf = lambda lam: np.exp(g[None, :] * np.log(lam[:, None]) - lam[:, None] - LOG_FACT[None, :])
    m = pmf(lh)[:, :, None] * pmf(la)[:, None, :]
    m[:, 0, 0] *= np.maximum(1 - lh * la * rho, 0)
    m[:, 0, 1] *= np.maximum(1 + lh * rho, 0)
    m[:, 1, 0] *= np.maximum(1 + la * rho, 0)
    m[:, 1, 1] *= 1 - rho
    return m / m.sum(axis=(1, 2), keepdims=True)


def outcome_probs(m):
    """(N, 3) : victoire domicile, nul, victoire extérieur."""
    return np.stack([(m * (_I > _J)).sum((1, 2)), (m * (_I == _J)).sum((1, 2)), (m * (_I < _J)).sum((1, 2))], axis=1)


def over_prob(m, line):
    return (m * ((_I + _J) > line)).sum((1, 2))
