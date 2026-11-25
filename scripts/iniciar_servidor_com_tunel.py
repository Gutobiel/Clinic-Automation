"""
Sobe o servidor local da automacao de guias (FastAPI na porta 8000) + Tunel HTTPS publico
via Cloudflare Quick Tunnel (sem conta, sem configuracao), para receber webhooks reais
do AGS CRM em producao direto no seu notebook durante a apresentacao!
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn
from core.api.app import create_app
from core.config.settings import AppSettings


def _copy_to_clipboard(text: str) -> bool:
    try:
        proc = subprocess.Popen(["clip"], stdin=subprocess.PIPE, shell=True)
        proc.communicate(input=text.encode("utf-8"))
        return proc.returncode == 0
    except Exception:
        return False


def _run_api(port: int) -> None:
    os.environ["AUTO_OPEN_REAL_AMHP_ON_WEBHOOK"] = "1"
    os.environ.setdefault("AUTO_WEBHOOK_AMHP_MODE", "fill_only")
    settings = AppSettings.load()
    # Em modo tunel de demonstracao local, se nenhuma chave real foi definida no .env,
    # permite receber disparos do AGS CRM sem travar em 401.
    if not os.getenv("CRM_WEBHOOK_API_KEY") or settings.crm_webhook_api_key == "dev-local-api-key":
        settings.crm_webhook_api_key = ""
    app = create_app(settings=settings)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)

    port = 8000
    cloudflared = ROOT / "bin" / "cloudflared.exe"
    if not cloudflared.exists():
        print("[ERRO] bin\\cloudflared.exe nao encontrado.")
        print("Execute novamente o setup ou baixe cloudflared-windows-amd64.exe em bin\\cloudflared.exe.")
        sys.exit(1)

    print("============================================================================")
    print("  AEGIS CLINIC AUTOMATION - SERVIDOR DE WEBHOOKS + TUNEL HTTPS AO VIVO")
    print("============================================================================")
    print(f"[1/2] Subindo API local da clinica em http://127.0.0.1:{port} ...")

    api_thread = threading.Thread(target=_run_api, args=(port,), daemon=True)
    api_thread.start()
    time.sleep(1.5)

    print("[2/2] Abrindo tunel HTTPS publico (Cloudflare Quick Tunnel)...")
    print("      Aguarde 3 a 5 segundos pela URL publica...")
    print("")

    proc = subprocess.Popen(
        [str(cloudflared), "tunnel", "--url", f"http://127.0.0.1:{port}", "--no-autoupdate"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
    printed_banner = False

    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            match = url_pattern.search(line)
            if match and not printed_banner:
                base_url = match.group(0)
                webhook_url = f"{base_url}/api/v1/webhooks/crm-event"
                copied = _copy_to_clipboard(webhook_url)
                printed_banner = True
                print("")
                print("============================================================================")
                print("  SERVIDOR ONLINE! PRONTO PARA RECEBER WEBHOOKS REAIS DO AGS CRM")
                print("============================================================================")
                print(f"  URL DO WEBHOOK (COLE NO CARD DO AGS CRM):")
                print(f"  >>> {webhook_url}")
                print("")
                if copied:
                    print("  [OK] Essa URL JA FOI COPIADA para sua area de transferencia (Ctrl+V)!")
                print("  Passo rapido no AGS CRM:")
                print("    1. Va em Configuracoes > Integracoes > Webhooks")
                print("    2. Clique no lapis (Editar) no card 'Hermes - Automacao de Guias'")
                print("    3. Cole essa URL no campo '2. URL de Destino' e clique Salvar")
                print("    4. Clique em 'Testar Disparo' -> vai responder HTTP 200 na hora!")
                print("")
                print("  Deixe esta janela aberta enquanto demonstra. Todos os eventos que")
                print("  chegarem do WhatsApp/Google Drive/iGUT aparecerao aqui em tempo real.")
                print("  (Pressione Ctrl+C para encerrar)")
                print("============================================================================")
                print("")
    except KeyboardInterrupt:
        print("\nEncerrando servidor e tunel...")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    main()
