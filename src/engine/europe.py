"""Coupes d'Europe : forces ESTIMÉES. Aucun test sur le passé n'est possible ici (pas d'historique de cotes de coupes),
ces pronostics sont donc marqués « * » dans l'appli.

Calage fait une fois, le 23/11/2026, sur les cotes Betclic de 72 matchs de coupe DÉJÀ JOUÉS (octobre-novembre 2026) :
- LEVEL : niveau de l'équipe moyenne de chaque championnat (1 = club médian hors des 5 championnats) ;
- CLUBS : niveau de 68 clubs hors des 5 championnats, connus par 1 ou 2 matchs chacun (donc imprécis, borné à MAX_CLUB).
À refaire chaque saison. Un club absent de la table prend DEFAULT.
"""
CUP_MU = (1.60, 1.25)  # buts moyens domicile / extérieur : total 2,85 et avantage du terrain 1,27 mesuré sur ces matchs
LEVEL = {"Premier League": 1.39, "La Liga": 1.18, "Bundesliga": 1.14, "Serie A": 1.04, "Ligue 1": 1.00}
DEFAULT, MAX_CLUB = 0.95, 1.30
CLUBS = {
    "AEK Athens": 0.99, "AGF Aarhus": 1.08, "AZ Alkmaar": 1.11, "Ajax": 1.03,
    "Anderlecht": 1.01, "Benfica": 1.15, "Besiktas JK": 1.02, "Bodø/Glimt": 1.06,
    "Celtic": 0.97, "Club Brugge": 1.04, "Dinamo Zagreb": 1.0, "FC Ararat-Armenia": 0.8,
    "FC Copenhagen": 1.0, "FC Iberia 1999": 0.92, "FC Kairat": 0.86, "FC Lugano": 0.92,
    "FC Midtjylland": 1.06, "FC Nordsjaelland": 1.1, "FC Thun": 0.93, "FC Twente Enschede": 1.28,
    "FK Borac Banja Luka": 1.01, "FK Jablonec": 0.88, "FK Kauno Žalgiris": 0.88, "Fenerbahce": 1.12,
    "Ferencváros TC": 1.08, "Feyenoord": 1.02, "Galatasaray": 1.1, "Gent": 0.94,
    "Hajduk Split": 1.05, "Hapoel Be'er Sheva": 0.81, "Hearts": 0.87, "Jagiellonia Białystok": 0.88,
    "KF Egnatia": 0.91, "KuPS Kuopio": 0.97, "LASK": 0.88, "Lech Poznań": 0.89,
    "Lincoln Red Imps FC": 0.77, "Mjällby AIF": 1.07, "NEC Nijmegen": 0.89, "NK Celje": 0.82,
    "OFI Crete": 0.81, "Olympiakos Piraeus": 1.04, "Omonoia FC": 0.77, "PFC CSKA Sofia": 0.89,
    "PFC Levski Sofia": 0.9, "PSV Eindhoven": 0.95, "Pafos FC": 1.06, "Panathinaikos FC": 1.14,
    "Porto": 1.15, "Red Star Belgrade": 0.98, "Riga FC": 0.93, "SC Braga": 1.05,
    "SK Brann": 1.12, "SK Sturm Graz": 0.89, "Sabah FK": 0.8, "Salzburg": 1.09,
    "Shakhtar Donetsk": 0.92, "Sint Truiden": 0.93, "Slavia Praha": 0.96, "Sparta Prague": 0.86,
    "Sporting Lisbon": 1.24, "Torreense": 0.82, "Trabzonspor": 1.12, "Union Saint-Gilloise": 1.09,
    "Universitatea Craiova": 1.53, "Viking FK": 0.92, "Viktoria Plzeň": 0.98, "ŠK Slovan Bratislava": 0.74,
}


def strength(name, league, relative):
    """(attaque, défense) à l'échelle européenne. `relative` = notes du club dans son championnat (None s'il n'en a pas)."""
    if relative and league in LEVEL:
        return relative[0] * LEVEL[league], relative[1] / LEVEL[league]
    g = min(CLUBS.get(name, DEFAULT), MAX_CLUB)
    return g, 1 / g


def expected_goals(home, away):
    return CUP_MU[0] * home[0] * away[1], CUP_MU[1] * away[0] * home[1]
