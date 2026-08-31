@echo off
echo Iniciando Kuri Bot (Telegram)...
if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe run_bot.py
) else (
    python run_bot.py
)
pause
