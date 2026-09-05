@echo off
REM Lance l'application (Windows). Double-cliquez sur ce fichier.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Creation de l'environnement virtuel...
    python -m venv .venv
    call .venv\Scripts\activate
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate
)
streamlit run app.py
pause
