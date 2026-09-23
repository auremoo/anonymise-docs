#!/bin/bash
# Lanceur cliquable pour Mac : démarre LM Studio si besoin puis l'interface web.
# Double-clic dans le Finder (ou ./lancer.command dans un terminal).
# Au premier lancement, crée l'environnement Python .venv et installe les
# dépendances : c'est le seul moment où le script accède au réseau.

cd "$(dirname "$0")" || exit 1

if [ ! -x .venv/bin/python ]; then
    echo "  🔧 Premier lancement : création de l'environnement Python..."
    python3 -m venv .venv || { echo "  ❌ python3 introuvable (brew install python)"; read -r; exit 1; }
    .venv/bin/pip install -q -r requirements.txt || { echo "  ❌ Installation des dépendances échouée"; read -r; exit 1; }
fi

.venv/bin/python lancer.py "$@"
