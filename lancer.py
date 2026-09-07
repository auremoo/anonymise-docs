#!/usr/bin/env python3
"""
Lanceur tout-en-un : démarre Ollama si nécessaire, puis l'interface web.

Usage :
    python lancer.py            # démarre tout et ouvre le navigateur
    python lancer.py --no-web   # démarre seulement Ollama
    double-clic sur lancer.bat  # idem, sans passer par le terminal

Le script est volontairement sans dépendance autre que celles déjà
requises par l'application (requests, streamlit).
"""

import os
import sys
import time
import shutil
import subprocess
import webbrowser
from pathlib import Path

OLLAMA_URL = "http://localhost:11434"
MODELE_REQUIS = "mistral"
RACINE = Path(__file__).resolve().parent

_LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", ""))
_PROGRAMFILES = Path(os.environ.get("PROGRAMFILES", ""))

# On privilégie l'application de bureau Ollama : c'est elle qui applique la
# configuration de l'utilisateur (notamment OLLAMA_MODELS, qui n'est PAS une
# variable d'environnement mais un réglage interne de l'app). Un
# « ollama serve » lancé à la main démarre un serveur qui ne voit pas les
# modèles si ceux-ci sont stockés ailleurs que dans le dossier par défaut.
CHEMINS_APP = [
    _LOCALAPPDATA / "Programs" / "Ollama" / "ollama app.exe",
    _PROGRAMFILES / "Ollama" / "ollama app.exe",
]

# Repli : le binaire CLI, avec « serve ».
CHEMINS_OLLAMA = [
    _LOCALAPPDATA / "Programs" / "Ollama" / "ollama.exe",
    _PROGRAMFILES / "Ollama" / "ollama.exe",
]


def log(icone: str, message: str):
    print(f"  {icone} {message}", flush=True)


def trouver_ollama() -> Path | None:
    """Localise l'exécutable ollama (PATH puis emplacements connus)."""
    depuis_path = shutil.which("ollama")
    if depuis_path:
        return Path(depuis_path)
    for chemin in CHEMINS_OLLAMA:
        if chemin.is_file():
            return chemin
    return None


def etat_ollama() -> tuple[bool, list[str]]:
    """(serveur joignable, liste des modèles installés)."""
    try:
        import requests
    except ImportError:
        log("❌", "Module 'requests' manquant : pip install -r requirements.txt")
        sys.exit(1)
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        r.raise_for_status()
        return True, [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return False, []


def _commande_demarrage() -> list[str] | None:
    """Commande à utiliser pour démarrer Ollama, app de bureau en priorité."""
    for chemin in CHEMINS_APP:
        if chemin.is_file():
            return [str(chemin)]
    binaire = trouver_ollama()
    if binaire is not None:
        return [str(binaire), "serve"]
    return None


def demarrer_ollama(delai_max: int = 90) -> bool:
    """Démarre Ollama en arrière-plan et attend qu'il réponde."""
    commande = _commande_demarrage()
    if commande is None:
        log("❌", "Ollama introuvable. Installez-le : https://ollama.com/download")
        return False

    nom = Path(commande[0]).name
    log("🚀", f"Démarrage d'Ollama ({nom})...")
    creationflags = 0
    if sys.platform == "win32":
        # Pas de fenêtre console, et le serveur survit à la fermeture
        # de ce lanceur.
        creationflags = (
            subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
        )
    try:
        subprocess.Popen(
            commande,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
    except Exception as e:
        log("❌", f"Échec du démarrage d'Ollama : {e}")
        return False

    # L'app de bureau met quelques secondes à lever son serveur ; on attend
    # aussi que les modèles soient indexés, sinon l'interface démarre en
    # croyant qu'aucun modèle n'est installé.
    for i in range(delai_max):
        time.sleep(1)
        joignable, modeles = etat_ollama()
        if joignable and (modeles or i >= 10):
            return True
    log("❌", f"Ollama n'a pas répondu en {delai_max}s.")
    return False


def verifier_modele(modeles: list[str]) -> bool:
    """Vérifie qu'au moins un modèle est installé, propose le pull sinon."""
    if not modeles:
        log("⚠️", "Aucun modèle installé.")
        log("💡", f"Installez-en un : ollama pull {MODELE_REQUIS}")
        log("💡", "Ou utilisez l'option « Regex uniquement » dans l'interface.")
        return False
    if any(MODELE_REQUIS in m for m in modeles):
        log("✅", f"Modèle prêt : {[m for m in modeles if MODELE_REQUIS in m][0]}")
    else:
        log("⚠️", f"'{MODELE_REQUIS}' absent. Modèles disponibles : "
                  f"{', '.join(modeles)}")
        log("💡", "Sélectionnez-en un dans la barre latérale de l'interface.")
    return True


def lancer_interface():
    """Démarre Streamlit dans ce terminal (bloquant) et ouvre le navigateur."""
    app = RACINE / "app.py"
    if not app.is_file():
        log("❌", f"app.py introuvable dans {RACINE}")
        sys.exit(1)

    log("🌐", "Démarrage de l'interface web...")
    print()
    # Streamlit ouvre déjà le navigateur ; on le fait nous-mêmes seulement
    # si Streamlit est configuré pour ne pas le faire.
    commande = [
        sys.executable, "-m", "streamlit", "run", str(app),
        "--server.headless=false",
    ]
    try:
        subprocess.run(commande, cwd=str(RACINE))
    except KeyboardInterrupt:
        print()
        log("🛑", "Interface arrêtée.")
    except FileNotFoundError:
        log("❌", "Streamlit manquant : pip install -r requirements.txt")
        sys.exit(1)


def main():
    sans_web = "--no-web" in sys.argv

    print()
    print("=" * 58)
    print("  ANONYMISATION DE DOCUMENTS — lanceur")
    print("=" * 58)

    joignable, modeles = etat_ollama()
    if joignable:
        log("✅", "Ollama déjà lancé.")
    else:
        if not demarrer_ollama():
            log("⚠️", "Poursuite sans LLM : seul le mode « Regex uniquement »")
            log("  ", "sera utilisable dans l'interface.")
            modeles = []
        else:
            log("✅", "Ollama démarré.")
            _, modeles = etat_ollama()

    verifier_modele(modeles)

    print("=" * 58)

    if sans_web:
        log("ℹ️", "Option --no-web : interface non démarrée.")
        return
    lancer_interface()


if __name__ == "__main__":
    main()
