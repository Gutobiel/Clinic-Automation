@echo off
title AEGIS - SERVIDOR REAL DE WEBHOOKS (WHATSAPP -> DRIVE -> PORTAL AMHP)
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [ERRO] Ambiente Python .venv nao encontrado em %CD%
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -u "scripts\iniciar_servidor_com_tunel.py"
echo.
pause
