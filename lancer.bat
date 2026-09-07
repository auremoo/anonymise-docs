@echo off
REM Lanceur cliquable : demarre Ollama si besoin puis l'interface web.
REM Se place dans le dossier du script pour fonctionner depuis n'importe ou.
cd /d "%~dp0"

python lancer.py %*

REM Si le lanceur s'arrete sur une erreur, garder la fenetre ouverte
REM pour que le message reste lisible.
if errorlevel 1 (
    echo.
    echo Une erreur s'est produite. Appuyez sur une touche pour fermer.
    pause >nul
)
