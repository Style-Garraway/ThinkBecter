"""Simulation Monte-Carlo d'un match à partir de sa matrice de scores Dixon-Coles."""
import numpy as np

N_SIMS = 10000


def simulate(matrix, n=N_SIMS, seed=None):
    """Tire n scores dans la matrice (lignes = buts domicile). Renvoie (buts domicile, buts extérieur)."""
    rng = np.random.default_rng(seed)
    size = matrix.shape[1]
    idx = rng.choice(matrix.size, size=n, p=matrix.ravel())
    return idx // size, idx % size


def markets(hg, ag):
    """Probabilités 1N2 et plus/moins de 1,5 / 2,5 / 3,5 buts, comptées sur les matchs simulés."""
    tot = hg + ag
    out = {"1X2": {"H": float(np.mean(hg > ag)), "D": float(np.mean(hg == ag)), "A": float(np.mean(hg < ag))}}
    for line in (1.5, 2.5, 3.5):
        over = float(np.mean(tot > line))
        out[f"OU{line}"] = {"Over": over, "Under": 1 - over}
    return out
