#!/usr/bin/env python3
"""
Lanceur tout-en-un : démarre le moteur LLM local (Ollama sous Windows,
LM Studio sur Mac) si nécessaire, puis l'interface web.

Usage :
    python lancer.py                     # démarre tout et ouvre le navigateur
    python lancer.py --no-web            # démarre seulement le moteur LLM
    python lancer.py --backend ollama    # force le moteur
    double-clic sur lancer.bat (Windows) ou lancer.command (Mac)

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
LMSTUDIO_URL = "http://localhost:1234"
MODELE_REQUIS_LMSTUDIO = "qwen3.5"
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


def trouver_lms() -> Path | None:
    """Localise le CLI de LM Studio (PATH puis emplacement d'installation).

    L'application installe `lms` dans ~/.lmstudio/bin sans toujours
    l'ajouter au PATH du terminal.
    """
    depuis_path = shutil.which("lms")
    if depuis_path:
        return Path(depuis_path)
    for nom in ("lms", "lms.exe"):
        chemin = Path.home() / ".lmstudio" / "bin" / nom
        if chemin.is_file():
            return chemin
    return None


def etat_lmstudio() -> tuple[bool, list[str]]:
    """(serveur joignable, modèles de chat disponibles)."""
    # Même filtrage que l'interface : LM Studio liste aussi ses modèles
    # d'embedding, incapables de répondre à un chat.
    from anonymize import check_lmstudio
    joignable, _, modeles = check_lmstudio(LMSTUDIO_URL)
    return joignable, modeles


def demarrer_lmstudio(delai_max: int = 60) -> bool:
    """Démarre le serveur local de LM Studio et attend qu'il réponde."""
    lms = trouver_lms()
    if lms is None:
        log("❌", "LM Studio introuvable. Installez-le : "
                  "https://lmstudio.ai/download")
        log("💡", "Puis lancez l'application une fois, pour installer "
                  "la commande « lms ».")
        return False
    log("🚀", "Démarrage du serveur LM Studio (lms server start)...")
    try:
        # « lms server start » rend la main une fois le serveur levé,
        # celui-ci tourne ensuite dans le service de fond de LM Studio.
        subprocess.run([str(lms), "server", "start"], timeout=delai_max,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        log("❌", f"Échec du démarrage de LM Studio : {e}")
        return False
    for _ in range(delai_max):
        joignable, _ = etat_lmstudio()
        if joignable:
            return True
        time.sleep(1)
    log("❌", f"LM Studio n'a pas répondu en {delai_max}s.")
    return False


def verifier_modele(modeles: list[str], requis: str = MODELE_REQUIS,
                    installation: str = f"ollama pull {MODELE_REQUIS}"
                    ) -> bool:
    """Vérifie qu'au moins un modèle est installé, propose le pull sinon."""
    if not modeles:
        log("⚠️", "Aucun modèle installé.")
        log("💡", f"Installez-en un : {installation}")
        log("💡", "Ou utilisez l'option « Regex uniquement » dans l'interface.")
        return False
    if any(requis in m for m in modeles):
        log("✅", f"Modèle prêt : {[m for m in modeles if requis in m][0]}")
    else:
        log("⚠️", f"'{requis}' absent. Modèles disponibles : "
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


def choisir_backend() -> str:
    """--backend ollama|lmstudio, sinon LM Studio sur Mac, Ollama ailleurs."""
    if "--backend" in sys.argv:
        i = sys.argv.index("--backend")
        if i + 1 < len(sys.argv) and sys.argv[i + 1] in ("ollama", "lmstudio"):
            return sys.argv[i + 1]
        log("❌", "--backend attend « ollama » ou « lmstudio ».")
        sys.exit(1)
    return "lmstudio" if sys.platform == "darwin" else "ollama"


def preparer_lmstudio():
    joignable, modeles = etat_lmstudio()
    if joignable:
        log("✅", "LM Studio déjà lancé.")
    elif demarrer_lmstudio():
        log("✅", "Serveur LM Studio démarré.")
        _, modeles = etat_lmstudio()
    else:
        log("⚠️", "Poursuite sans LLM : seul le mode « Regex uniquement »")
        log("  ", "sera utilisable dans l'interface.")
        modeles = []
    verifier_modele(modeles, MODELE_REQUIS_LMSTUDIO,
                    "lms get qwen/qwen3.5-9b")


def preparer_ollama():
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


def main():
    sans_web = "--no-web" in sys.argv
    backend = choisir_backend()

    print()
    print("=" * 58)
    print("  ANONYMISATION DE DOCUMENTS — lanceur")
    print("=" * 58)

    # L'interface reprend ce choix comme moteur par défaut.
    os.environ["ANONYMISE_BACKEND"] = backend
    if backend == "lmstudio":
        preparer_lmstudio()
    else:
        preparer_ollama()

    print("=" * 58)

    if sans_web:
        log("ℹ️", "Option --no-web : interface non démarrée.")
        return
    lancer_interface()


if __name__ == "__main__":
    main()
