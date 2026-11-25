"""API locale (127.0.0.1 uniquement) et page de l'appli."""
import threading
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from .. import history, refresh, track
from ..database import db
from ..engine import pipeline
from ..ingest import apifootball, crests, lineups
from . import clipboard

STATIC = Path(__file__).resolve().parents[1] / "ui" / "static"

app = FastAPI(title="ThinkBecter", docs_url=None, redoc_url=None, openapi_url=None)
conn = db.connect()
lock = threading.Lock()  # une seule connexion SQLite partagée : on sérialise les accès
MODEL = {}  # notes des équipes, en mémoire : relues au démarrage depuis les fichiers déjà téléchargés
try:
    MODEL.update(pipeline.build_model(fetch=pipeline.offline))
except RuntimeError:
    pass  # premier lancement : aucune donnée encore, l'écran lance la première actualisation


def allowed(host, origin):
    """Seule la page de l'appli peut appeler l'API : un autre site ouvert dans un navigateur de ce PC est refusé
    (en-tête Origin différent), de même qu'un nom de domaine qui pointerait vers 127.0.0.1 (en-tête Host)."""
    return host.split(":")[0] in ("127.0.0.1", "localhost") and (not origin or origin.split("//", 1)[-1] == host)


@app.middleware("http")
async def local_only(request: Request, call_next):
    if not allowed(request.headers.get("host", ""), request.headers.get("origin")):
        return JSONResponse({"detail": "Requête refusée."}, status_code=403)
    return await call_next(request)


def payload():
    return {"matches": pipeline.upcoming(conn, MODEL) if MODEL else [], "ready": bool(MODEL), "status": db.get(conn, "status", {}),
            "keys": {k: bool(db.get(conn, k)) for k in db.SECRET_KEYS}}  # les clés elles-mêmes ne repartent jamais vers l'écran


@app.get("/api/today")
def today():
    with lock:
        return payload()


@app.post("/api/refresh")
def do_refresh():
    with lock:
        try:
            refresh.run(conn, MODEL)
        except RuntimeError as e:
            raise HTTPException(502, f"{e}. Vérifie ta connexion internet puis réessaie.")
        return payload()


@app.post("/api/lineups")
def poll_lineups():
    """Réclame les compositions qui peuvent être publiées maintenant (la page appelle ceci toutes les 2 minutes ;
    une requête n'est dépensée que si une composition est due) et renvoie toutes les compositions connues."""
    now = datetime.now()
    with lock:
        key, errors = db.get(conn, "apifootball_key"), []
        if key:
            errors = lineups.poll(conn, key, now, spend=apifootball.spender(conn, now, floor=3))["errors"]
        return {"lineups": lineups.stored(conn), "errors": errors}


@app.get("/crest/{cid}")
def crest(cid: int):
    """Logo d'un club connu, gardé en cache sur ce PC. Un numéro inconnu est refusé : ce serveur ne sert pas de relais."""
    with lock:
        known = crests.known_ids(db.get(conn, "crest_extra", {}))
    path = crests.image(cid) if cid in known else None  # téléchargement hors verrou : le réseau peut être lent
    if not path:
        raise HTTPException(404, "Logo indisponible.")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.post("/api/copy/{match_id}")
def copy_bet(match_id: int):
    with lock:
        m = conn.execute(db.BY_ID, (match_id,)).fetchone()
        if not (m and MODEL):
            raise HTTPException(404, "Match introuvable.")
        v = pipeline.verdict(conn, MODEL, dict(m))
    fair = f"{v['top']['fair_odds']:.2f}".replace(".", ",")
    text = f"{v['home']} - {v['away']} | {v['top']['label']} | {round(v['top']['p'] * 100)} % | cote juste {fair}"
    try:
        clipboard.copy(text)
    except OSError as e:
        raise HTTPException(500, str(e))
    return {"text": text}


@app.get("/api/history")
def get_history():
    with lock:
        if not MODEL:
            raise HTTPException(404, "Pas encore de données : clique sur « Actualiser ».")
        return history.get(MODEL)


@app.get("/api/track")
def get_track():
    with lock:
        return track.summary(conn)


@app.put("/api/settings")
def put_settings(values: dict):
    """Enregistre une clé (texte non vide) ou l'efface (texte vide). Les autres champs sont ignorés."""
    with lock:
        for k in db.SECRET_KEYS:
            if k in values:
                db.put(conn, k, str(values[k] or "").strip())
        return {k: bool(db.get(conn, k)) for k in db.SECRET_KEYS}


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/logo.svg")
def logo():
    return FileResponse(STATIC / "logo.svg", media_type="image/svg+xml")
