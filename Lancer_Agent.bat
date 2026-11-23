@echo off
setlocal
chcp 65001 >nul
title ThinkBecter
cd /d "%~dp0"

if not exist "src\main.py" (
    echo Ce fichier a ete lance depuis l'archive ZIP, sans l'extraire.
    echo Fais un clic droit sur le fichier ZIP, choisis "Extraire tout", puis relance Lancer_Agent.bat depuis le dossier extrait.
    pause
    exit /b 1
)

rem Les composants sont installes une seule fois, dans le dossier .venv de l'appli : rien n'est modifie ailleurs sur le PC.
if exist ".venv\installe.ok" goto lancer

echo Premier lancement : installation des composants, 1 a 3 minutes. Laisse cette fenetre ouverte...
rem Versions stables d'abord : une version de Python toute recente n'a pas toujours les composants prets.
for %%V in (3.13 3.12 3.14 3.11 3.10 3.15) do (
    py -0p 2>nul | findstr /C:"-V:%%V" >nul && call :essayer py -%%V
    if exist ".venv\installe.ok" goto lancer
)
call :essayer python
if exist ".venv\installe.ok" goto lancer
call :essayer py -3
if exist ".venv\installe.ok" goto lancer

echo.
echo L'installation n'a pas abouti.
echo - Si Python n'est pas installe : va sur https://www.python.org/downloads/windows/ , installe Python 3.13
echo   en cochant la case "Add python.exe to PATH", puis relance ce fichier.
echo - Sinon : verifie ta connexion internet, puis relance ce fichier.
pause
exit /b 1

:essayer
rem %* = commande Python a essayer. Sans Python, "python" ouvre le Microsoft Store au lieu de repondre : d'ou le test.
%* -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul
if errorlevel 1 exit /b 1
echo   essai avec : %*
if exist ".venv" rmdir /s /q ".venv"
%* -m venv .venv >nul 2>nul
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 exit /b 1
rem Fenetre integree, facultative : si son installation echoue, l'appli s'ouvre dans une fenetre Edge a la place.
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q pywebview >nul 2>nul
type nul > ".venv\installe.ok"
exit /b 0

:lancer
rem pythonw = sans console : seule la fenetre de l'appli s'affiche. En cas de souci, voir data\thinkbecter.log.
start "" ".venv\Scripts\pythonw.exe" -m src.main
exit /b 0
