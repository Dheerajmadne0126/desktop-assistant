@echo off
title JARVIS Dashboard
cd /d "%~dp0frontend"
echo Starting JARVIS dashboard on http://localhost:5173 ...
call npm run dev
