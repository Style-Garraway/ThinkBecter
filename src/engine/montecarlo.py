"""Simulation Monte-Carlo d'un match à partir de sa matrice de scores Dixon-Coles."""
import numpy as np

N_SIMS = 10000


def simulate(matrix, n=N_SIMS, seed=None):
    """Tire n scores dans la matrice (lignes = buts domicile). Renvoie (buts domicile, buts extérieur)."""
    rng = np.random.default_rng(seed)
    size = matrix.shape[1]
    idx = rng.choice(matrix.size, size=n, p=matrix.ravel())
    return idx // size, idx % size


def extras(hg, ag, n_scores=3):
    """Autres paris, comptés sur les mêmes matchs simulés (ils ne servent pas au « pari le plus probable ») : les deux équipes
    marquent, double chance, équipe qui ne prend pas de but, scores les plus fréquents."""
    mean = lambda x: float(np.mean(x))
    btts = mean((hg > 0) & (ag > 0))
    scores, counts = np.unique(hg * 100 + ag, return_counts=True)
    best = np.argsort(-counts)[:n_scores]
    return {"btts": {"Yes": btts, "No": 1 - btts},
            "double": {"1N": mean(hg >= ag), "12": mean(hg != ag), "N2": mean(hg <= ag)},
            "clean": {"home": mean(ag == 0), "away": mean(hg == 0)},
            "scores": [{"score": f"{int(scores[i]) // 100}-{int(scores[i]) % 100}", "p": float(counts[i] / len(hg))} for i in best]}


def markets(hg, ag):
    """Probabilités 1N2 et plus/moins de 1,5 / 2,5 / 3,5 buts, comptées sur les matchs simulés."""
    tot = hg + ag
    out = {"1X2": {"H": float(np.mean(hg > ag)), "D": float(np.mean(hg == ag)), "A": float(np.mean(hg < ag))}}
    for line in (1.5, 2.5, 3.5):
        over = float(np.mean(tot > line))
        out[f"OU{line}"] = {"Over": over, "Under": 1 - over}
    return out
