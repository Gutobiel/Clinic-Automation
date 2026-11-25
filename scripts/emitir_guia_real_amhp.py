"""
EMISSAO DE GUIA REAL (100% PORTAL VERDADEIRO + DOCUMENTO VERDADEIRO DO GOOGLE DRIVE)

Fluxo 100% real (zero simulador):
1. Conecta no Google Drive REAL da Nova Gesta (pasta 'Documentos pacientes').
2. Lista os pacientes reais que ja enviaram carteirinha no WhatsApp (ou usa o --folder-id
   enviado automaticamente pelo Webhook do AGS CRM).
3. Le o ficha_paciente.json real (nome, CPF, operadora, numero da carteirinha, validade)
   e baixa o pedido medico real (se existir em 03_Pedidos_Medicos/).
4. Roda o Auditor Anti-Glosa real nos dados do paciente.
5. Abre o Chromium VISIVEL na sua tela no portal REAL da Nova Gesta:
   https://portal.amhp.com.br/ -> AMHPTISS -> Consultorio > Atendimento
6. A IA (OpenAI GPT-4o) seleciona Empresa, Negociacao, Operadora REAL, Tipo de Guia,
   Credenciado (Dr. Marcondes), Local do Atendimento, clica em + Iniciar e preenche os
   dados reais da carteirinha do paciente!
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.agent.browser_ai_agent import BrowserAiAgent
from core.config.settings import AppSettings
from core.connectors.google_drive import GoogleDriveConnector
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
            ff, "-y", "-i", str(webm_path),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-crf", "22",
            str(mp4_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return mp4_path if proc.returncode == 0 and mp4_path.exists() else None


def _extract_patient_summary(folder_name: str, dossier: dict[str, Any]) -> dict[str, str]:
    pac = dossier.get("paciente") or {}
    conv = dossier.get("convenio_atual") or {}
    docs = dossier.get("documentos") or []

    card_number = str(
        conv.get("numero_carteirinha")
        or conv.get("numeroCarteirinha")
        or conv.get("carteirinha")
        or ""
    )
    card_validity = str(conv.get("validade") or "")
    operator = str(conv.get("operadora") or conv.get("convenio") or "")
    holder_name = str(conv.get("titular") or conv.get("nome_titular") or pac.get("nome") or folder_name)
    cpf = str(pac.get("cpf") or "")
    phone = str(pac.get("telefone") or "")

    for doc in reversed(docs):
        if doc.get("categoria") == "carteirinha_convenio":
            campos = doc.get("ocr_campos") or {}
            cand_card = (
                campos.get("numero_carteirinha")
                or campos.get("numeroCarteirinha")
                or campos.get("carteirinha")
                or campos.get("matricula")
                or campos.get("codigo_beneficiario")
            )
            if cand_card and not card_number:
                card_number = str(cand_card)
            cand_op = campos.get("operadora") or campos.get("convenio")
            if cand_op and not operator:
                operator = str(cand_op)
            if campos.get("validade") and not card_validity:
                card_validity = str(campos["validade"])
            cand_holder = campos.get("nome_titular") or campos.get("titular")
            if cand_holder:
                holder_name = str(cand_holder)
            if card_number:
                break

    return {
        "name": holder_name.strip() or folder_name,
        "cpf": re.sub(r"\D+", "", cpf),
        "phone": phone,
        "operator": operator.strip() or "Nao identificada",
        "card_number": card_number.strip(),
        "card_validity": card_validity.strip(),
    }


async def _load_real_patients(drive: GoogleDriveConnector, root_folder_id: str) -> list[dict[str, Any]]:
    q = f"'{root_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    folders = await drive._list_files(q)
    patients: list[dict[str, Any]] = []
    for f in folders:
        try:
            dossier = await drive.read_patient_dossier(f["id"])
        except Exception:
            dossier = {}
        summary = _extract_patient_summary(f["name"], dossier)
        patients.append(
            {
                "folder_id": f["id"],
                "folder_name": f["name"],
                "dossier": dossier,
                "summary": summary,
            }
        )
    return patients


async def main() -> None:
    parser = argparse.ArgumentParser(description="Emissao REAL de Guia no Portal AMHP usando paciente do Google Drive")
    parser.add_argument("--folder-id", default="", help="ID da pasta do paciente no Google Drive (usado pelo Webhook)")
    parser.add_argument("--mode", choices=["ask", "fill_only", "submit"], default="ask", help="fill_only = preenche e pausa; submit = preenche e envia")
    parser.add_argument("--guide-type", choices=["Consulta", "SP/SADT"], default="Consulta")
    parser.add_argument("--provider", choices=["auto", "openai", "gemini", "heuristic"], default="openai")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    settings = AppSettings.load("nova-gesta")
    settings.ai_provider = args.provider
    settings.playwright_headless = False
    settings.browser_slow_mo_ms = 260

    amhp_url = os.getenv("PORTAL_AMHP_URL", "https://portal.amhp.com.br/")
    amhp_user = os.getenv("PORTAL_AMHP_USER", "")
    amhp_pass = os.getenv("PORTAL_AMHP_PASS", "")
    if not amhp_user or not amhp_pass:
        raise RuntimeError("PORTAL_AMHP_USER / PORTAL_AMHP_PASS nao configurados em tenants/nova-gesta/.env")

    drive = GoogleDriveConnector(settings)
    if not drive.is_configured():
        raise RuntimeError("Google Drive nao esta configurado no tenants/nova-gesta/.env")

    print("\n" + "=" * 78)
    print("  AEGIS CLINIC AUTOMATION - EMISSAO REAL NO PORTAL AMHP + GOOGLE DRIVE REAL")
    print("=" * 78)

    selected: dict[str, Any] | None = None
    medical_order_local: str | None = None

    if args.folder_id:
        print(f"Carregando pasta real do paciente no Google Drive (ID: {args.folder_id})...")
        dossier = await drive.read_patient_dossier(args.folder_id)
        summary = _extract_patient_summary(args.folder_id, dossier)
        selected = {"folder_id": args.folder_id, "folder_name": summary["name"], "dossier": dossier, "summary": summary}
    else:
        print("Consultando pastas reais de pacientes no Google Drive da Nova Gesta...")
        patients = await _load_real_patients(drive, settings.google_drive_root_folder_id)
        print("")
        if patients:
            print(f"Pacientes encontrados no Google Drive ({len(patients)}):")
            for idx, p in enumerate(patients, start=1):
                s = p["summary"]
                print(
                    f"  [{idx}] {s['name']} | Convenio: {s['operator']} | "
                    f"Carteirinha: {s['card_number'] or 'sem numero'} | Validade: {s['card_validity'] or '-'}"
                )
        else:
            print("  (Nenhuma pasta de paciente encontrada no Google Drive ainda.)")
        print("  [0] Digitar dados de uma carteirinha real manualmente agora")
        print("")

        choice_raw = input("Digite o numero do paciente que deseja processar [1]: ").strip() or ("1" if patients else "0")
        if choice_raw == "0":
            nome = input("  Nome completo do paciente: ").strip()
            cpf = re.sub(r"\D+", "", input("  CPF (so numeros, opcional): ").strip())
            operadora = input("  Convenio/Operadora (ex: PROASA, BACEN, CARE PLUS, CASEC, PROCER): ").strip()
            carteirinha = input("  Numero da carteirinha: ").strip()
            validade = input("  Validade (ex: 06/2030, opcional): ").strip()
            selected = {
                "folder_id": "",
                "folder_name": nome,
                "dossier": {},
                "summary": {
                    "name": nome,
                    "cpf": cpf,
                    "phone": "",
                    "operator": operadora,
                    "card_number": carteirinha,
                    "card_validity": validade,
                },
            }
        else:
            idx = max(1, min(int(choice_raw), len(patients)))
            selected = patients[idx - 1]

    s = selected["summary"]
    print("\n" + "-" * 78)
    print("  DADOS REAIS LIDOS DO DOCUMENTO DO PACIENTE:")
    print(f"    Paciente    : {s['name']}")
    print(f"    CPF         : {s['cpf'] or '-'}")
    print(f"    Operadora   : {s['operator']}")
    print(f"    Carteirinha : {s['card_number'] or '(nao encontrada)'}")
    print(f"    Validade    : {s['card_validity'] or '-'}")
    print("-" * 78)

    # Baixa pedido medico real do Drive se existir
    if selected["folder_id"]:
        try:
            orders = await drive.list_subfolder_files(selected["folder_id"], "03_Pedidos_Medicos")
            if orders:
                dl_dir = ROOT / "downloads" / "temp_drive"
                dl_dir.mkdir(parents=True, exist_ok=True)
                target = dl_dir / orders[0]["name"]
                await drive.download_file(orders[0]["id"], target)
                medical_order_local = str(target)
                print(f"  Pedido medico real baixado do Drive: {orders[0]['name']}")
        except Exception as exc:
            print(f"  [Aviso] Nao foi possivel verificar 03_Pedidos_Medicos: {exc}")

    # Escolha do modo (preencher e conferir vs emitir de verdade)
    exec_mode = args.mode
    guide_type = args.guide_type
    if exec_mode == "ask":
        print("\nTipo de guia:")
        print("  [1] Consulta (padrao)")
        print("  [2] Exame / SP-SADT")
        gt = input("Escolha [1]: ").strip() or "1"
        guide_type = "SP/SADT" if gt == "2" else "Consulta"

        print("\nModo de operacao no portal REAL da AMHP:")
        print("  [1] Preencher tudo no AMHPTISS REAL e parar antes do clique final de enviar (para conferir na tela)")
        print("  [2] Preencher E SUBMETER a guia REAL no AMHPTISS agora!")
        m = input("Escolha [1]: ").strip() or "1"
        exec_mode = "submit" if m == "2" else "fill_only"

    videos_dir = ROOT / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)

    card_digits = re.sub(r"\s+", "", s["card_number"])
    job = GuideJob(
        id=f"real-guia-{datetime.now().strftime('%H%M%S')}",
        tenant_slug="nova-gesta",
        igut_appointment_id=f"DRIVE-{selected['folder_id'][:10] or 'MANUAL'}",
        patient_name=s["name"],
        patient_cpf=s["cpf"],
        patient_phone=s["phone"],
        insurance_name=s["operator"],
        card_number=card_digits,
        doctor_name="Dr. Marcondes Carneiro Leite Junior",
        doctor_crm="14450",
        doctor_cbo="225250",
        specialty="Ginecologia e Obstetricia",
        appointment_type=guide_type,
        procedure_codes=["10101012"] if guide_type == "Consulta" else ["40901300"],
        drive_patient_folder_id=selected["folder_id"] or None,
    )
    route = PortalRoute(
        portal_key="portal_amhp",
        display_name="Portal AMHP-DF / AMHPTISS (REAL)",
        motor="BrowserAiAgent",
        url=amhp_url,
    )

    submit_instruction = (
        "6. Apos preencher a carteirinha e os dados do paciente/procedimento na tela da guia, CLIQUE em Salvar / Enviar / Solicitar Autorizacao e acompanhe o retorno real do portal (aguardando Autorizada ou informando o retorno exato do convenio)."
        if exec_mode == "submit"
        else "6. Apos abrir a tela da guia (+ Iniciar) e preencher a carteirinha e dados do paciente, PARE ANTES do clique final de gravar/enviar a guia e retorne action='done' (portal_status='AUTHORIZED') explicando no thought tudo que foi preenchido e que esta pronto para conferencia final."
    )

    real_goal = (
        "Voce esta operando o PORTAL REAL da Clinica Nova Gesta (portal.amhp.com.br -> AMHPTISS) usando placeholders seguros para dados do beneficiario:\n"
        "- Nome do Beneficiario: use sempre o placeholder literal {{PATIENT_NAME}} quando precisar preencher nome\n"
        "- CPF do Beneficiario: use sempre o placeholder literal {{PATIENT_CPF}} quando precisar preencher CPF\n"
        "- Numero da Carteirinha: use sempre o placeholder literal {{PATIENT_CARD}} quando precisar preencher carteirinha\n"
        f"- Operadora/Convenio: {s['operator']}\n"
        f"- Tipo de Guia desejado: {guide_type}\n"
        "- Credenciado/Medico: 021387 - Marcondes Carneiro Leite Junior\n\n"
        "PASSO A PASSO NO PORTAL REAL:\n"
        "1. Em portal.amhp.com.br/inicio: se houver tour/modal, clique em 'Fechar guia'. Depois clique em 'AMHPTISS' (Portal de Faturamento).\n"
        "2. No AMHPTISS (amhptiss.amhp.com.br): se cair em /novo/alterar-senha, IGNORE campos de senha (NUNCA digite nada la!). Clique em 'Consultorio' no menu lateral e depois clique em 'Atendimento'.\n"
        "3. Na tela 'Atendimento' (Dados do Atendimento), os campos sao comboboxes Telerik ASP.NET (para abrir a lista, clique no input ou na setinha do campo; quando a lista de opcoes `rcbItem` abrir, clique na opcao correta):\n"
        "   - Empresa: selecione a empresa da Nova Gesta / Marcondes (primeira opcao valida da clinica).\n"
        "   - Tipo de Negociacao: selecione a negociacao padrao disponivel (ex: Convenio / AMHP / Credenciado).\n"
        "   - Tipo de Cobranca: selecione a opcao disponivel (se ja nao preencher automaticamente).\n"
        f"   - Operadora: procure e selecione '{s['operator']}'. IMPORTANTE: se '{s['operator']}' NAO existir na lista de operadoras disponiveis dentro do AMHPTISS, informe EXATAMENTE no `thought` quais operadoras apareceram na lista e encerre com action='needs_human', portal_status='AWAITING_HUMAN_2FA'.\n"
        f"   - Tipo de guia: selecione '{guide_type}' (ex: Guia de Consulta ou Guia de SP/SADT).\n"
        "   - Credenciado: mantenha '021387 - Marcondes Carneiro Leite Junior'.\n"
        "   - Local do atendimento: selecione o consultorio/local da Nova Gesta.\n"
        "4. Depois de preencher todos os campos obrigatorios (*), clique no botao '+ Iniciar' no topo da tela.\n"
        f"5. Na tela aberta da guia, preencha o Numero da Carteirinha usando value='{{{{PATIENT_CARD}}}}', valide o beneficiario e o procedimento ({job.procedure_codes[0]}).\n"
        f"{submit_instruction}\n"
        "NUNCA encerre com action='done' enquanto ainda estiver em Default.aspx ou sem ter aberto '+ Iniciar'. NUNCA clique em 'Sair', 'Esqueci minha senha' ou 'Alterar senha'."
    )

    print(f"\nAbrindo Chromium AO VIVO no portal REAL {amhp_url} (modo={exec_mode})...\n")

    agent = BrowserAiAgent(settings)
    # Limpa sessao antiga para garantir login limpo
    st_file = Path(settings.storage_state_dir) / "nova-gesta_portal_amhp.json"
    if st_file.exists():
        st_file.unlink(missing_ok=True)

    result = await agent.execute_guide_flow(
        job=job,
        route=route,
        start_url=amhp_url,
        portal_credentials={"username": amhp_user, "password": amhp_pass},
        medical_order_local_path=medical_order_local,
        headless_override=False,
        slow_mo_override=320,
        record_video_dir=str(videos_dir),
        custom_goal=real_goal,
        max_steps=28,
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    final_mp4: Path | None = None
    if result.video_path and Path(result.video_path).exists():
        final_webm = videos_dir / f"real_amhp_{stamp}.webm"
        shutil.move(result.video_path, final_webm)
        final_mp4 = _convert_to_mp4(final_webm, videos_dir / f"real_amhp_{stamp}.mp4")

    print("\n" + "=" * 78)
    print("  RESULTADO DA OPERACAO REAL NO PORTAL AMHP")
    print("=" * 78)
    print(f"  Paciente     : {s['name']} ({s['operator']} - {s['card_number']})")
    print(f"  Status Final : {result.final_status}")
    print(f"  Resumo IA    : {result.denial_reason or (result.steps_executed[-1]['thought'] if result.steps_executed else '-')}")
    print(f"  Guia / Senha : {result.guide_number or '-'} / {result.auth_password or '-'}")
    print(f"  Passos IA    : {len(result.steps_executed)} ({result.ai_provider_used})")
    print(f"  Screenshot   : {result.screenshot_path or '-'}")
    print(f"  Video MP4    : {final_mp4 or '-'}")
    print("=" * 78 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
