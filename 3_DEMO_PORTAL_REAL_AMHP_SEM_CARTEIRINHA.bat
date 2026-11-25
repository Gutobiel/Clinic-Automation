@echo off
title AEGIS - DEMO PORTAL REAL AMHP e AMHPTISS (SEM CARTEIRINHA)
cd /d "%~dp0"
echo ============================================================================
echo   AEGIS CLINIC AUTOMATION - PORTAL REAL AMHP e AMHPTISS (SOMENTE LEITURA)
echo   Sem carteirinha - IA faz login real, navega no AMHPTISS e grava MP4
echo ============================================================================
echo.
if not exist ".venv\Scripts\python.exe" (
  echo [ERRO] Ambiente Python .venv nao encontrado em %CD%
  pause
  exit /b 1
)
del /q "storage_state\nova-gesta_portal_amhp.json" 2>nul
echo Abrindo Chromium ao vivo no Portal Real AMHP... aguarde...
echo.
".venv\Scripts\python.exe" "scripts\demo_real_amhp.py" --provider openai
echo.
echo Finalizado! Video salvo na pasta videos\
pause
