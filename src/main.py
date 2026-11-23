"""Point d'entrée : serveur FastAPI en arrière-plan + fenêtre desktop dédiée.

    python -m src.main            fenêtre PyWebView (repli : Edge --app, puis navigateur)
    python -m src.main --server   serveur seul (http://127.0.0.1:8765)
"""
import logging
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "data" / "thinkbecter.log"
ICON = ROOT / "src" / "ui" / "static" / "logo.ico"
HOST = "127.0.0.1"


def free_port(preferred=8765):
    with socket.socket() as s:
        if s.connect_ex((HOST, preferred)) != 0:
            return preferred
    with socket.socket() as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def wait_ready(url, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url + "/api/health", timeout=1)
            return True
        except OSError:
            time.sleep(0.25)
    return False


def app_browser():
    """Chemin d'Edge ou de Chrome (ils savent ouvrir une fenêtre sans barre d'adresse), ou None. Edge peut être désinstallé."""
    import winreg
    for exe in ("msedge.exe", "chrome.exe"):
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                path = winreg.QueryValue(root, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}")
            except OSError:
                continue
            if path and Path(path).exists():
                return path
    return None


def open_window(url):
    try:
        import ctypes
        import webview
        # Identité propre à l'appli : sans elle, la barre des tâches range la fenêtre avec Python et ignore son icône.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ThinkBecter.App")
        webview.create_window("ThinkBecter", url, width=1250, height=760, min_size=(900, 500), background_color="#0b0f14")
        webview.start(icon=str(ICON))  # logo dans la barre de titre et la barre des tâches
        return
    except Exception as e:
        logging.warning("Fenêtre intégrée indisponible (%s) : ouverture dans le navigateur", e)
    browser = app_browser()
    if browser:
        # Profil dédié : le navigateur reste attaché à ce processus tant que la fenêtre est ouverte.
        subprocess.run([browser, f"--app={url}", f"--user-data-dir={ROOT / 'data' / 'profil-navigateur'}", "--window-size=1250,760",
                        "--no-first-run", "--no-default-browser-check"])
    else:
        # shortcut: sans fenêtre intégrée, ni Edge, ni Chrome, rien ne dit quand l'onglet est fermé : le serveur reste 12 h.
        # À remplacer par un signal de vie envoyé par la page si ce cas devient courant.
        webbrowser.open(url)
        time.sleep(12 * 3600)


def main():
    LOG.parent.mkdir(exist_ok=True)
    if sys.stdout is None:  # lancé par pythonw : pas de console, tout ce qui s'affiche part dans le log
        sys.stdout = sys.stderr = open(LOG, "a", encoding="utf-8", buffering=1)
    logging.basicConfig(filename=LOG, encoding="utf-8", level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server_only = "--server" in sys.argv
    port = 8765 if server_only else free_port()
    url = f"http://{HOST}:{port}"
    config = uvicorn.Config("src.api.server:app", host=HOST, port=port, log_level="warning",
                            log_config=None if not server_only else uvicorn.config.LOGGING_CONFIG)
    server = uvicorn.Server(config)
    if server_only:
        print(f"ThinkBecter : {url}")
        server.run()
        return
    threading.Thread(target=server.run, daemon=True).start()
    if not wait_ready(url):
        logging.error("Le serveur n'a pas démarré, voir les erreurs ci-dessus")
        sys.exit(1)
    logging.info("Serveur prêt sur %s", url)
    open_window(url)
    server.should_exit = True


if __name__ == "__main__":
    main()
