# ThinkBecter

(Nommé ainsi par l'utilisateur le 23/11/2026 ; ancien nom : QuantBet Desk. Le dossier local s'appelle encore `quantbet-desk`.)

Application desktop locale (Windows), volontairement **ultra-épurée** : un seul écran listant les matchs à venir avec
les chances calculées par l'agent, le pronostic 1N2, le pari le plus probable, la cote Betclic (information) et un
bouton « Copier ». Tout le calcul reste invisible. Ne pas réintroduire de curseurs, d'onglets, de graphiques, de
« value bets » ni de mises sans demande explicite de l'utilisateur.

Le projet est destiné à être partagé (dépôt GitHub + `README.md` = guide d'installation pour des non-techniciens).
Ne jamais y mettre le dossier `data/` (il contient les clés API de l'utilisateur) : il est dans `.gitignore`.

Lancement : double-clic sur `Lancer_Agent.bat` (crée `.venv` au premier lancement, puis `pythonw -m src.main`).
Serveur seul pour tester : `python -m src.main --server` puis http://127.0.0.1:8765.
Tests (sans internet) : `python -m unittest discover tests`. Test sur le passé : `python -m src.backtest.run`.

## Arborescence

```
ThinkBecter/
├── Lancer_Agent.bat            lanceur : cherche un Python stable (3.13, 3.12, 3.14…), crée .venv, lance la fenêtre
├── README.md                   guide pour les utilisateurs (installation, clés, chiffres, dépannage)
├── requirements.txt            fastapi, uvicorn, numpy (pywebview est installé à part, facultatif)
├── data/                       local, jamais partagé : thinkbecter.db (clés, journal), fd/ (CSV téléchargés), thinkbecter.log
├── src/
│   ├── main.py                 uvicorn en thread + fenêtre PyWebView ; repli : Edge ou Chrome en mode --app
│   ├── refresh.py              une actualisation complète, source par source (les pannes n'arrêtent rien)
│   ├── track.py                journal de preuve (pronostics enregistrés, puis comparés aux résultats)
│   ├── database/db.py          schéma SQLite, réglages, aides team_id / match_id
│   ├── ingest/footballdata.py  résultats, cotes de clôture, calendrier de la journée (football-data.co.uk, sans clé)
│   ├── ingest/fixturedownload.py  calendrier de toute la saison (fixturedownload.com, sans clé)
│   ├── ingest/odds_api.py      facultatif : cotes Betclic + coupes d'Europe (The Odds API, 8 crédits par actualisation)
│   ├── ingest/injuries.py      facultatif : forfaits du jour et du lendemain (API-Football), information seule
│   ├── ingest/apifootball.py   appel API-Football + budget de 100 requêtes/jour (réserve pour les compositions)
│   ├── ingest/lineups.py       numéros des matchs du jour, compositions réclamées de H-65 min à H+10 min
│   ├── ingest/scorers.py       buteurs/passeurs probables : Fantasy Premier League (tous) + ESPN (25 premiers par championnat), sans clé, 1 fois/12 h
│   ├── ingest/crests.py        logos : table club -> id API-Football, cache local data/crests (hors dépôt)
│   ├── ingest/names.py         noms de clubs entre sources (table football-data -> nom affiché, alias, best_match)
│   ├── engine/ratings.py       notes d'attaque/défense apprises sur les cotes de clôture des matchs passés
│   ├── engine/dixon_coles.py   matrice des scores (numpy seul)
│   ├── engine/montecarlo.py    10 000 simulations -> 1N2 et plus/moins de 1,5 / 2,5 / 3,5 buts
│   ├── engine/europe.py        coupes d'Europe : niveaux de ligues et de clubs ESTIMÉS (table datée)
│   ├── engine/pipeline.py      build_model (notes) et verdict (pronostic d'un match)
│   ├── backtest/run.py         test sur le passé, refaisable par tous
│   ├── api/server.py           /api/today, /api/refresh, /api/copy, /api/track, /api/settings ; filtre Host/Origin
│   ├── api/clipboard.py        copie dans le presse-papiers par l'API Win32
│   └── ui/static/              index.html (l'unique écran), logo.svg (logo, écran d'ouverture), logo.ico (icône de fenêtre)
└── tests/test_engine.py        18 tests, sources remplacées par de faux mini-championnats
```

## Le modèle (ne pas le modifier sans refaire `python -m src.backtest.run`)

1. Pour chaque match **déjà joué** : cotes de clôture moyennes du marché (1N2 et plus/moins de 2,5 buts), marge retirée
   (méthode proportionnelle) -> buts attendus par le marché (λ dom, λ ext). Le total vient de P(plus de 2,5) (Poisson),
   le partage de l'écart P(1) − P(2) (dichotomie sur la matrice Dixon-Coles).
2. Notes par équipe et par ligue, `a` (attaque) et `d` (défense, plus grand = encaisse plus), lissage exponentiel K = 0,3 :
   `a_dom += K·(λ_dom / (μ_dom·d_ext) − a_dom)`, de même pour les trois autres. Moyennes de ligue μ : K_MU = 0,01.
   Promu (absent la saison d'avant) : a = 1/1,15, d = 1,15. Sur les 4 premiers matchs de chaque saison d'une équipe
   (`ns` < N_EARLY = 4), K_EARLY = 0,5 au lieu de K.
3. Avantage du terrain par club `h` (log), appris AVANT la mise à jour des notes : `h += 0,05·(½·[ln(λ_dom/λ̂_dom) − ln(λ_ext/λ̂_ext)] − h)`.
4. Match à venir : `λ_dom = μ_dom·a_dom·d_ext·e^h`, `λ_ext = μ_ext·a_ext·d_dom/e^h`, puis écart amplifié
   (SPREAD = 1,12) : rapport λ_dom/λ_ext élevé à la puissance 1,12, total λ_dom + λ_ext inchangé (+/- buts inchangés).
   Dixon-Coles ρ = −0,08 ; 10 000 simulations (graine = clubs + date : mêmes chiffres chez tout le monde).
5. Aucune cote du match pronostiqué n'entre dans le calcul. Historique chargé : saison en cours + précédente
   (écart < 0,6 % sur les λ par rapport à cinq saisons).

### Mesures (23/11/2026, délai de 3 jours simulé, log-loss 1N2, plus bas = mieux)

Protocole : K_EARLY, K_HOME et SPREAD choisis sur 2022-23 à 2024-25 (5 330 matchs) ; 2025-26 et 2026-27 jamais
utilisés pour choisir. Gain mesuré sur ce test : +0,0021 de log-loss 1N2 (± 0,0011), positif sur les deux saisons.

| | hasard | agent | marché (clôture) |
|---|---|---|---|
| 2025-26, 1 752 matchs | 1,072 | **0,979** (avant : 0,980) | 0,977 |
| 2026-27, 545 matchs | 1,061 | **0,940** (avant : 0,946) | 0,948 |

Bon pronostic 1N2 sur le test : 54,4 % contre 54,1 % (marché) ; sur 7 627 matchs depuis 2022 : 53,8 % contre 54,6 %.
Plus/moins de 2,5 buts 2025-26 : 0,692 / 0,676 / 0,673. Fiabilité : annoncé 70-80 % -> arrivé 76,0 %.
Pari le plus probable : réussi 80,7 % (annoncé 80,0 %). **Aucun avantage prouvé** : parier quand l'agent voit +5 %
sur la cote de clôture donne +2,4 % ± 6,5 (592 paris, 2025-26), soit dans la marge du hasard ; et la cote de
clôture n'est pas celle qu'on obtient en pariant plus tôt. Ne jamais présenter l'appli comme un moyen de gagner.

Essayé le 23/11/2026 sans gain (banc identique au moteur) : retour vers la moyenne en début de saison (10 à 35 %),
mélange notes rapides + lentes, cotes Pinnacle en priorité, calibration appliquée au 1N2 seul (remplacée par SPREAD).

### Ce qui a été essayé et abandonné (ne pas refaire sans raison nouvelle)

- Ancien modèle (xG Understat sur 20 matchs + Elo, joueurs, fatigue) : 0,993 en 2025-26 ; journal réel du 19/10 au
  08/11/2026 (115 matchs) : 1,006 contre 0,939 pour le modèle actuel rejoué et 0,945 pour le marché.
- xG ou buts réels ajoutés aux notes : 0,9808 à 0,9824 au lieu de 0,9803 (aucun gain). Réglage de K, PROMO, K_MU, ρ : plat.
- Correction des absents sur les probabilités : journal réel, 28 matchs, 1,02 avec contre 0,96 sans. Retirée :
  les forfaits sont affichés, sans effet sur le calcul.
- Understat et ClubElo : en panne en novembre 2026 (l'appli tournait sur des données figées sans le dire). Supprimés.
  Leçon : toute source peut tomber ; chaque étape de `refresh.run` échoue seule et l'écran affiche un bandeau.

## Sources et pannes

| Source | Clé | Sert à | Si elle tombe |
|---|---|---|---|
| football-data.co.uk | non | notes, résultats (1 à 2 mises à jour par semaine), calendrier de la journée | on garde les CSV en cache, bandeau |
| fixturedownload.com | non | calendrier des 14 jours | seule la journée en cours est listée, bandeau |
| The Odds API | facultative | cotes Betclic (`betclic_fr`, 1N2 seulement), coupes d'Europe | pas de cotes ni de coupes, bandeau |
| API-Football | facultative | forfaits (offre gratuite : aujourd'hui et demain) | liste précédente gardée, bandeau |

`data_until` (date du dernier match connu) et `refreshed_at` sont enregistrés dans `settings.status` et affichés en haut.

## Noms de clubs

Nom affiché = nom The Odds API. `names.FD_TO_NAME` relie les noms courts de football-data pour les 96 clubs 2026-27
(vérifié le 23/11/2026 : identiques aux noms The Odds API dans les 5 ligues). Autres sources : `best_match` dans la
ligue du match (clé réduite, inclusion de mots, similarité ≥ 0,8, refus si deux candidats se valent) + `ALIASES`.
**À chaque nouvelle saison** : ajouter les promus à `FD_TO_NAME` si leur nom diffère, et vérifier le calendrier.
API-Football renvoie le monde entier : toujours filtrer par identifiant de ligue (`injuries.LEAGUE_IDS`).

## Coupes d'Europe

Pas de source de cotes passées, donc pas de test : pronostics marqués « * ». `europe.py` contient des niveaux calés une
fois (23/11/2026) sur les cotes Betclic de 72 matchs déjà joués : niveau de chaque championnat (appliqué aux notes
du club rapportées à la moyenne de sa ligue, `ratings.relative`) et 68 clubs hors des 5 championnats (1 ou 2 matchs
chacun, bornés à 1,30). Vérification sur 18 matchs non utilisés : quelques points d'écart avec Betclic. À recaler
chaque saison. Les matchs de coupe ne reçoivent pas de résultat (pas de source) : ils ne sont pas dans le journal.

## Conventions

- Interface et messages en français simple, tutoiement. Heures affichées dans le fuseau du PC.
- Les clés API (`db.SECRET_KEYS`) ne quittent jamais la base : ni vers l'écran, ni vers le journal, ni dans un message d'erreur.
- L'API n'écoute que sur 127.0.0.1 et refuse tout en-tête Origin ou Host étranger (`server.allowed`).
- Compatibilité : Python 3.10 à 3.15, Windows 10/11. Edge peut être désinstallé (Europe) : ne jamais le supposer présent.
