@echo off
echo Iniciando Dashboard Web de Kuri...
echo Abre tu navegador en: http://localhost:8000
if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe run_web.py
) else (
    python run_web.py
)
pause
