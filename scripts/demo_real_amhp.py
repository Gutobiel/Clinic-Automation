r"""
Teste REAL e SEGURO (Somente Leitura) no Portal AMHP (https://portal.amhp.com.br/)
com OpenAI GPT-4o operando o navegador Chromium ao vivo + gravação MP4.

Segurança:
- Credenciais lidas exclusivamente do arquivo local `tenants/nova-gesta/.env` (fora do Git).
- Modo SOMENTE LEITURA: faz login, fecha avisos iniciais e navega até a área de
  Autorizações / Guias / Convênios sem criar, alterar ou submeter nenhuma guia falsa.
- Pausa imediatamente (AWAITING_HUMAN_2FA) caso o portal apresente CAPTCHA ou 2FA.
- NUNCA clica em "Esqueci minha senha" ou "Alterar senha".
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.agent.browser_ai_agent import BrowserAiAgent
from core.config.settings import AppSettings
from core.domain.models import GuideJob, PortalRoute


def _convert_to_mp4(webm_path: Path, mp4_path: Path) -> Path | None:
    try:
        import imageio_ffmpeg  # type: ignore[import-not-found]
        ff = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        ff = shutil.which("ffmpeg")
    if not ff or not webm_path.exists():
        return None
    proc = subprocess.run(
        [
            ff,
            "-y",
            "-i",
            str(webm_path),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-crf",
            "22",
            str(mp4_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return mp4_path if proc.returncode == 0 and mp4_path.exists() else None


async def main() -> None:
    parser = argparse.ArgumentParser(description="Demo real e segura no Portal AMHP + AMHPTISS")
    parser.add_argument("--provider", choices=["auto", "openai", "gemini", "heuristic"], default="heuristic")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    settings = AppSettings.load("nova-gesta")
    settings.ai_provider = args.provider
    settings.playwright_headless = False
    settings.browser_slow_mo_ms = 280

    amhp_url = os.getenv("PORTAL_AMHP_URL", "https://portal.amhp.com.br/")
    amhp_user = os.getenv("PORTAL_AMHP_USER", "")
    amhp_pass = os.getenv("PORTAL_AMHP_PASS", "")
    if not amhp_user or not amhp_pass:
        raise RuntimeError("PORTAL_AMHP_USER / PORTAL_AMHP_PASS não configurados em tenants/nova-gesta/.env")

    videos_dir = ROOT / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)

    agent = BrowserAiAgent(settings)
    job = GuideJob(
        id=f"real-amhp-{datetime.now().strftime('%H%M%S')}",
        tenant_slug="nova-gesta",
        igut_appointment_id="REAL-AMHP-READONLY",
        patient_name="MODO LEITURA (SEM EMISSAO FALSA)",
        insurance_name="AMHP-DF",
    )
    route = PortalRoute(
        portal_key="portal_amhp",
        display_name="Portal AMHP-DF (Real)",
        motor="BrowserAiAgent",
        url=amhp_url,
    )

    safe_goal = (
        "Você está executando uma demonstração AO VIVO REAL e 100% SEGURA (MODO DRY-RUN / SOMENTE LEITURA) no Portal da AMHP -> AMHPTISS.\n"
        "SEU OBJETIVO PASSO A PASSO:\n"
        "1. Em portal.amhp.com.br/inicio: se houver tour/modal (has_modal_or_tour_overlay=true), clique em 'Fechar guia'. Em seguida clique em 'AMHPTISS' (Portal de Faturamento).\n"
        "2. No AMHPTISS (amhptiss.amhp.com.br): se cair em /novo/alterar-senha, IGNORE completamente os campos de senha (NUNCA digite nada lá!). "
        "Clique no menu lateral 'Consultório' para expandir os submenus e depois clique em 'Atendimento' (a tela real de guias/atendimento).\n"
        "3. Se aparecer algum erro 504/502/503 do servidor AMHPTISS, retorne action='fail' informando a indisponibilidade.\n"
        "4. Assim que carregar a tela real de 'Atendimento' (ou outra tela de guias dentro de Consultório), OBSERVE todos os campos visíveis (Credenciado, Operadora/Convênio, Carteirinha, Tipo de Guia, Procedimentos, etc.).\n"
        "5. PROIBIDO clicar em Salvar, Gravar, Enviar, Solicitar ou alterar qualquer dado real (estamos sem paciente real agora!). NUNCA clique em 'Sair' nem em 'Esqueci/Esqueceu'.\n"
        "6. Assim que chegar na tela de 'Atendimento' (ou listar os campos reais disponíveis para emissão de guia), encerre com action='done', portal_status='AUTHORIZED', "
        "descrevendo no `thought` em pt-BR exatamente a tela onde chegou e quais campos reais de emissão/autorização estão prontos para preenchimento."
    )

    print("\n" + "=" * 78)
    print("  🏥 TESTE AO VIVO NO PORTAL REAL DA AMHP (SOMENTE LEITURA + GPT-4o)")
    print(f"  -> URL: {amhp_url}")
    print("=" * 78)

    result = await agent.execute_guide_flow(
        job=job,
        route=route,
        start_url=amhp_url,
        portal_credentials={"username": amhp_user, "password": amhp_pass},
        headless_override=False,
        slow_mo_override=350,
        record_video_dir=str(videos_dir),
        custom_goal=safe_goal,
        max_steps=16,
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    final_webm: Path | None = None
    final_mp4: Path | None = None
    if result.video_path and Path(result.video_path).exists():
        final_webm = videos_dir / f"demo_real_amhp_{stamp}.webm"
        shutil.move(result.video_path, final_webm)
        final_mp4 = _convert_to_mp4(final_webm, videos_dir / f"demo_real_amhp_{stamp}.mp4")

    print("\n" + "=" * 78)
    print("  ✅ RESULTADO DO TESTE REAL NO PORTAL AMHP")
    print("=" * 78)
    print(f"  Status Final : {result.final_status}")
    print(f"  Observação   : {result.denial_reason or (result.steps_executed[-1]['thought'] if result.steps_executed else '-')}")
    print(f"  Passos IA    : {len(result.steps_executed)} (provedor={result.ai_provider_used})")
    print(f"  Screenshot   : {result.screenshot_path or '-'}")
    print(f"  Vídeo WEBM   : {final_webm or '-'}")
    print(f"  Vídeo MP4    : {final_mp4 or '-'}")
    print("=" * 78 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
