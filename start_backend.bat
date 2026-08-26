@echo off
title JARVIS Backend
cd /d "%~dp0backend"
echo Starting JARVIS backend on http://127.0.0.1:8000 ...
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 %*
