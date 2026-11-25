#!/usr/bin/env bash
set -euo pipefail

# Provisionamento base de VPS Ubuntu 24.04 para clinic-automation (Hermes + Playwright + FastAPI)
echo "=== [1/4] Atualizando pacotes e instalando dependências do sistema ==="
sudo apt-get update
sudo apt-get install -y python3.12 python3.12-venv python3-pip git curl xvfb ca-certificates

echo "=== [2/4] Criando ambiente virtual Python ==="
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "=== [3/4] Instalando Chromium do Playwright e bibliotecas gráficas ==="
playwright install --with-deps chromium

echo "=== [4/4] Criando diretórios de estado persistente ==="
mkdir -p data downloads screenshots storage_state

echo "Pronto! Copie tenants/nova-gesta/.env.example para tenants/nova-gesta/.env, preencha as credenciais e rode:"
echo "  source .venv/bin/activate && uvicorn core.api.app:app --host 0.0.0.0 --port 8000"
