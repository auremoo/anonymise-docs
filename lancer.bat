@echo off
REM Lanceur cliquable : demarre Ollama si besoin puis l'interface web.
REM Se place dans le dossier du script pour fonctionner depuis n'importe ou.
cd /d "%~dp0"

REM Python a utiliser : l'environnement .venv du projet s'il existe, sinon le
REM Python du systeme s'il a deja les dependances. A defaut, .venv est cree
REM au premier lancement, comme sur Mac : c'est le seul moment ou le script
REM accede au reseau. Un environnement dans le dossier du projet evite aussi
REM la limite de 260 caracteres de Windows, que depassent certains fichiers
REM de Streamlit installes dans le dossier du Python du Microsoft Store.
set "PY=.venv\Scripts\python.exe"
if exist "%PY%" goto :lancer

python -c "import requests, docx, fitz, streamlit, pandas" >nul 2>nul
if not errorlevel 1 (
    set "PY=python"
    goto :lancer
)

echo   Premier lancement : creation de l'environnement Python .venv...
python -m venv .venv
if errorlevel 1 (
    echo   Python introuvable. Installez-le depuis https://www.python.org/downloads/
    goto :erreur
)
"%PY%" -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo   Installation des dependances echouee.
    goto :erreur
)

:lancer
"%PY%" lancer.py %*
REM Si le lanceur s'arrete sur une erreur, garder la fenetre ouverte
REM pour que le message reste lisible.
if not errorlevel 1 goto :eof

:erreur
echo.
echo Une erreur s'est produite. Appuyez sur une touche pour fermer.
pause >nul
