@echo off
title AEGIS - EMITIR GUIA REAL (GOOGLE DRIVE + PORTAL AMHP)
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [ERRO] Ambiente Python .venv nao encontrado em %CD%
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "scripts\emitir_guia_real_amhp.py"
echo.
pause
