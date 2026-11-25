r"""
Demonstração AO VIVO da automação de guias com Agente IA operando o navegador + Gravação de Vídeo.

O que este script faz:
1. Sobe um servidor local FastAPI com o Portal Simulador TISS (/mock-portal).
2. Mostra primeiro o Auditor Anti-Glosa bloqueando um paciente com carteirinha vencida/sem pedido médico.
3. Abre o Chromium VISÍVEL na sua tela (headless=False) com HUD ao vivo, destaque neon e gravação de vídeo:
   - A IA (OpenAI GPT-4o, Gemini ou Planner Local) observa a página, faz login e abre Nova Solicitação SP/SADT,
   - Preenche carteirinha, paciente, CPF, médico, CRM, CBO, TUSS e anexa o Pedido Médico PDF,
   - Submete a solicitação ao convênio,
   - Acompanha o status "EM ANÁLISE" consultando o portal até virar "AUTORIZADA",
   - Captura Nº da Guia, Senha, Validade e baixa o PDF oficial da guia autorizada!
4. Salva a gravação em .webm e converte automaticamente para .mp4 (compatível com Windows/WhatsApp).

Uso:
    .\.venv\Scripts\python.exe scripts\demo_visual_guia.py
    .\.venv\Scripts\python.exe scripts\demo_visual_guia.py --provider openai --delay 6 --record-video
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx
import uvicorn

from core.api.app import create_app
from core.api.mock_portal import _build_minimal_pdf
from core.config.settings import AppSettings
from core.domain.models import GuideJob
from core.orchestrator.runner import GuideOrchestrator


def _find_ffmpeg() -> str | None:
    try:
        import imageio_ffmpeg  # type: ignore[import-not-found]
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path
    local_app = os.environ.get("LOCALAPPDATA", "")
    if local_app:
        matches = glob.glob(str(Path(local_app) / "ms-playwright" / "ffmpeg-*" / "ffmpeg*.exe"))
        if matches:
            return matches[0]
    return None


def _convert_webm_to_mp4(webm_path: Path, mp4_path: Path) -> Path | None:
    ffmpeg_bin = _find_ffmpeg()
    if not ffmpeg_bin or not webm_path.exists():
        return None
    cmd = [
        ffmpeg_bin,
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
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode == 0 and mp4_path.exists():
        return mp4_path
    # Fallback mpeg4 caso build do ffmpeg não inclua libx264
    cmd_fallback = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(webm_path),
        "-c:v",
        "mpeg4",
        "-q:v",
        "4",
        str(mp4_path),
    ]
    proc2 = subprocess.run(cmd_fallback, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return mp4_path if proc2.returncode == 0 and mp4_path.exists() else None


def _start_local_server(app, host: str, port: int) -> uvicorn.Server:
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            r = httpx.get(f"http://{host}:{port}/health", timeout=1.0)
            if r.status_code == 200:
                return server
        except Exception:
            time.sleep(0.15)
    raise RuntimeError("Servidor local do portal simulador não respondeu a tempo.")


async def run_demo(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    demo_dir = ROOT / "data" / "demo"
    demo_dir.mkdir(parents=True, exist_ok=True)
    videos_dir = ROOT / "videos"
    if args.record_video:
        videos_dir.mkdir(parents=True, exist_ok=True)

    db_path = str(demo_dir / "demo_visual.db")

    sample_order_pdf = demo_dir / "pedido_medico_dra_camila.pdf"
    sample_order_pdf.write_bytes(
        _build_minimal_pdf(
            [
                "PEDIDO MEDICO - CLINICA NOVA GESTA",
                "Paciente: MARIA CLARA ALVES DE SOUZA",
                "Convenio: INAS - GDF SAUDE",
                "Exame Solicitado: Ultrassonografia Obstetrica Morfologica (TUSS 40901238)",
                "Medica Solicitante: Dra. Camila Lopes Guerra de Oliveira - CRM-DF 24314",
                "Assinado e carimbado em 20/11/2026",
            ]
        )
    )

    settings = AppSettings.load("nova-gesta")
    settings.db_path = db_path
    settings.automation_mode = "ASSISTED"
    settings.playwright_headless = args.headless
    settings.browser_slow_mo_ms = 0 if args.headless else args.slow_mo
    settings.ai_provider = args.provider

    orchestrator = GuideOrchestrator(settings)
    app = create_app(settings=settings, orchestrator=orchestrator)

    host = "127.0.0.1"
    port = args.port
    server = _start_local_server(app, host, port)

    print("\n" + "=" * 78)
    print("  🤖 CLINIC AUTOMATION — DEMONSTRAÇÃO SPRINT 1 (ANTI-GLOSA + AGENTE IA)")
    print("=" * 78)

    try:
        print("\n[CENÁRIO 1] Testando Auditor Anti-Glosa (carteirinha vencida + sem pedido médico)...")
        blocked_job = GuideJob(
            id=str(uuid.uuid4()),
            tenant_slug="nova-gesta",
            igut_appointment_id=f"DEMO-BLOCK-{int(time.time())}",
            patient_name="JULIANA MENDES (TESTE ANTI-GLOSA)",
            patient_cpf="321.654.987-00",
            insurance_name="GDF Saúde",
            card_number="0045999988887777",
            doctor_name="CAMILA LOPES GUERRA DE OLIVEIRA",
            doctor_crm="24314",
            doctor_cbo="225250",
            specialty="Ginecologia e Obstetrícia",
            appointment_type="Ecografia Obstétrica Morfológica",
            appointment_date="2026-11-25",
            appointment_time="10:30",
            procedure_codes=["40901238"],
        )
        saved_blocked, _ = orchestrator.store.upsert_job(blocked_job)
        res_blocked = await orchestrator.process_job(
            saved_blocked.id,
            dossier_override={
                "convenio": {"numero_carteirinha": "0045999988887777", "validade": "2026-09-30"},
                "documentos": {},
            },
        )
        print(f"  -> Status final: {res_blocked['job']['status']}")
        print(f"  -> Alerta enviado ao grupo da clínica:\n{res_blocked['audit']['alert_message']}")

        print("\n" + "-" * 78)
        print("[CENÁRIO 2] Abrindo navegador Chromium com o Agente IA operando AO VIVO...")
        print(f"  -> Portal Simulador : http://{host}:{port}/mock-portal/login?delay={args.delay}&outcome={args.outcome}")
        print(f"  -> Provedor IA      : {orchestrator.browser_agent._resolve_provider()} (modelo={settings.openai_model})")
        print(f"  -> Gravação Vídeo   : {'ATIVADA (' + str(videos_dir) + ')' if args.record_video else 'Desativada'}")
        print("  -> Observe o HUD no canto superior direito mostrando cada decisão da IA!")
        print("-" * 78)

        ok_job = GuideJob(
            id=str(uuid.uuid4()),
            tenant_slug="nova-gesta",
            igut_appointment_id=f"DEMO-OK-{int(time.time())}",
            patient_name="MARIA CLARA ALVES DE SOUZA",
            patient_cpf="456.789.123-00",
            insurance_name="GDF Saúde",
            card_number="0045012345678901",
            doctor_name="CAMILA LOPES GUERRA DE OLIVEIRA",
            doctor_crm="24314",
            doctor_cbo="225250",
            specialty="Ginecologia e Obstetrícia",
            appointment_type="Ecografia Obstétrica Morfológica",
            appointment_date="2026-11-25",
            appointment_time="14:00",
            procedure_codes=["40901238"],
            metadata={"medical_order_local_path": str(sample_order_pdf)},
        )
        saved_ok, _ = orchestrator.store.upsert_job(ok_job)
        result = await orchestrator.process_job(
            saved_ok.id,
            dossier_override={
                "convenio": {"numero_carteirinha": "0045012345678901", "validade": "2027-12-31"},
                "documentos": {
                    "pedido_medico": {
                        "file_name": sample_order_pdf.name,
                        "data_pedido": "2026-11-20",
                        "possui_assinatura": True,
                        "possui_carimbo_crm": True,
                        "legivel": True,
                    }
                },
            },
            target_url_override=f"http://{host}:{port}/mock-portal/login?delay={args.delay}&outcome={args.outcome}",
            headless_override=args.headless,
            slow_mo_override=0 if args.headless else args.slow_mo,
            record_video_dir=str(videos_dir) if args.record_video else None,
            poll_interval_seconds=2.5,
            max_analysis_polls=12,
        )

        job_out = result["job"]
        exec_out = result["execution"]
        steps = exec_out.get("steps_executed", [])
        providers_summary: dict[str, int] = {}
        for s in steps:
            p = s.get("provider", "unknown")
            providers_summary[p] = providers_summary.get(p, 0) + 1

        webm_raw = exec_out.get("video_path")
        final_webm: Path | None = None
        final_mp4: Path | None = None
        if webm_raw and Path(webm_raw).exists():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            final_webm = videos_dir / f"demo_guia_ia_{stamp}.webm"
            shutil.move(webm_raw, final_webm)
            mp4_target = videos_dir / f"demo_guia_ia_{stamp}.mp4"
            final_mp4 = _convert_webm_to_mp4(final_webm, mp4_target)

        print("\n" + "=" * 78)
        print("  ✅ RESULTADO FINAL DO AGENTE IA")
        print("=" * 78)
        print(f"  Status do Job     : {job_out['status']}")
        print(f"  Nº da Guia        : {job_out.get('guide_number') or '-'}")
        print(f"  Senha Autorização : {job_out.get('auth_password') or '-'}")
        print(f"  Validade          : {job_out.get('validity_date') or '-'}")
        print(f"  Passos da IA      : {len(steps)} {providers_summary}")
        print(f"  PDF Baixado       : {exec_out.get('pdf_local_path') or '-'}")
        print(f"  Screenshot        : {exec_out.get('screenshot_path') or '-'}")
        print(f"  Vídeo WEBM        : {final_webm or '-'}")
        print(f"  Vídeo MP4         : {final_mp4 or '-'}")
        print("=" * 78 + "\n")
    finally:
        server.should_exit = True


def main() -> None:
    parser = argparse.ArgumentParser(description="Demonstração visual ao vivo do Agente IA de Guias")
    parser.add_argument("--delay", type=float, default=6.0, help="Segundos que a guia fica 'Em Análise' antes de aprovar")
    parser.add_argument("--outcome", choices=["authorized", "denied"], default="authorized", help="Desfecho simulado do convênio")
    parser.add_argument("--slow-mo", type=int, default=350, help="Atraso em ms por ação para visualização confortável")
    parser.add_argument("--port", type=int, default=8787, help="Porta local do Portal Simulador")
    parser.add_argument("--provider", choices=["auto", "openai", "gemini", "heuristic"], default="auto")
    parser.add_argument("--record-video", action="store_true", default=True, help="Grava vídeo da sessão do Chromium")
    parser.add_argument("--no-video", dest="record_video", action="store_false", help="Desativa gravação de vídeo")
    parser.add_argument("--headless", action="store_true", help="Executa sem janela visível")
    args = parser.parse_args()
    asyncio.run(run_demo(args))


if __name__ == "__main__":
    main()
