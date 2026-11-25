from __future__ import annotations

import socket
import threading
import time
import uuid
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from core.api.app import create_app
from core.api.mock_portal import _build_minimal_pdf
from core.config.settings import AppSettings
from core.domain.models import GuideJob, GuideJobStatus
from core.orchestrator.runner import GuideOrchestrator


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _make_settings(tmp_path: Path) -> AppSettings:
    s = AppSettings.load("nova-gesta")
    s.db_path = str(tmp_path / "e2e.db")
    s.storage_state_dir = str(tmp_path / "state")
    s.downloads_dir = str(tmp_path / "downloads")
    s.screenshots_dir = str(tmp_path / "screenshots")
    s.playwright_headless = True
    s.browser_slow_mo_ms = 0
    s.ai_provider = "heuristic"
    s.crm_webhook_api_key = "test-secret-key"
    return s


def test_api_health_webhook_and_jobs(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    app = create_app(settings=settings)
    client = TestClient(app)

    r_health = client.get("/health")
    assert r_health.status_code == 200
    assert r_health.json()["status"] == "ok"

    # Cria um job via API
    r_job = client.post(
        "/api/v1/jobs",
        json={
            "tenant_slug": "nova-gesta",
            "igut_appointment_id": "900123",
            "patient_name": "ANA PAULA TESTE",
            "patient_cpf": "111.222.333-44",
            "insurance_name": "GDF Saúde",
            "appointment_type": "Ecografia",
            "appointment_date": "2026-11-26",
            "procedure_codes": ["40901238"],
        },
    )
    assert r_job.status_code == 200
    job_id = r_job.json()["job"]["id"]

    # Webhook sem API Key deve falhar (401)
    r_bad = client.post(
        "/api/v1/webhooks/crm-event",
        json={"event": "document.synced_to_drive", "tenant_slug": "nova-gesta"},
    )
    assert r_bad.status_code == 401

    # Webhook autenticado vincula pasta do Drive ao job da paciente
    r_ok = client.post(
        "/api/v1/webhooks/crm-event",
        headers={"X-API-Key": "test-secret-key"},
        json={
            "event": "document.synced_to_drive",
            "tenant_slug": "nova-gesta",
            "patient": {"name": "ANA PAULA TESTE", "cpf": "111.222.333-44", "phone": "61999990000"},
            "drive": {
                "patient_folder_id": "drive-folder-abc",
                "file_name": "pedido_medico.pdf",
                "category": "pedido_medico",
            },
        },
    )
    assert r_ok.status_code == 200
    assert job_id in r_ok.json()["matched_job_ids"]

    r_get = client.get(f"/api/v1/jobs/{job_id}")
    assert r_get.status_code == 200
    assert r_get.json()["job"]["drive_patient_folder_id"] == "drive-folder-abc"


@pytest.mark.asyncio
async def test_e2e_ai_browser_agent_authorized_denied_and_captcha(tmp_path: Path) -> None:
    """Testa o fluxo real Playwright (headless) no Portal Simulador: Aprovação após Em Análise, Negativa e CAPTCHA."""
    settings = _make_settings(tmp_path)
    orch = GuideOrchestrator(settings)
    app = create_app(settings=settings, orchestrator=orch)

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Aguarda servidor local responder
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=1.0).status_code == 200:
                break
        except Exception:
            time.sleep(0.1)

    order_pdf = tmp_path / "pedido_medico.pdf"
    order_pdf.write_bytes(_build_minimal_pdf(["PEDIDO MEDICO VALIDO - DRA CAMILA CRM 24314"]))

    valid_dossier = {
        "convenio": {"numero_carteirinha": "0045012345678901", "validade": "2027-12-31"},
        "documentos": {
            "pedido_medico": {
                "file_name": "pedido_medico.pdf",
                "data_pedido": "2026-11-20",
                "possui_assinatura": True,
                "possui_carimbo_crm": True,
                "legivel": True,
            }
        },
    }

    try:
        # 1. Caminho completo: Login -> Formulário + Upload -> Em Análise -> Autorizada + Download PDF
        job_ok, _ = orch.store.upsert_job(
            GuideJob(
                id=str(uuid.uuid4()),
                tenant_slug="nova-gesta",
                igut_appointment_id="E2E-OK-1",
                patient_name="MARIA CLARA ALVES",
                patient_cpf="45678912300",
                insurance_name="GDF Saúde",
                card_number="0045012345678901",
                doctor_name="CAMILA LOPES GUERRA DE OLIVEIRA",
                doctor_crm="24314",
                doctor_cbo="225250",
                specialty="Ginecologia e Obstetrícia",
                appointment_type="Ecografia Obstétrica",
                appointment_date="2026-11-25",
                procedure_codes=["40901238"],
                metadata={"medical_order_local_path": str(order_pdf)},
            )
        )
        res_ok = await orch.process_job(
            job_ok.id,
            dossier_override=valid_dossier,
            target_url_override=f"http://127.0.0.1:{port}/mock-portal/login?delay=1.5&outcome=authorized",
            headless_override=True,
            poll_interval_seconds=0.8,
            max_analysis_polls=8,
        )
        assert res_ok["job"]["status"] == GuideJobStatus.AUTHORIZED.value
        assert res_ok["job"]["guide_number"] is not None
        assert res_ok["job"]["auth_password"] is not None
        pdf_path = Path(res_ok["execution"]["pdf_local_path"])
        assert pdf_path.exists()
        assert pdf_path.read_bytes().startswith(b"%PDF-1.4")

        # 2. Caminho Negado pela Operadora
        job_denied, _ = orch.store.upsert_job(
            GuideJob(
                id=str(uuid.uuid4()),
                tenant_slug="nova-gesta",
                igut_appointment_id="E2E-DENIED-1",
                patient_name="CARLA NEGADA",
                insurance_name="GDF Saúde",
                card_number="0045012345678902",
                doctor_name="MARCONDES CARNEIRO LEITE JUNIOR",
                doctor_crm="17641",
                appointment_type="Ecografia",
                appointment_date="2026-11-25",
                procedure_codes=["40901238"],
                metadata={"medical_order_local_path": str(order_pdf)},
            )
        )
        res_denied = await orch.process_job(
            job_denied.id,
            dossier_override=valid_dossier,
            target_url_override=f"http://127.0.0.1:{port}/mock-portal/login?delay=0.5&outcome=denied",
            headless_override=True,
            poll_interval_seconds=0.4,
            max_analysis_polls=6,
        )
        assert res_denied["job"]["status"] == GuideJobStatus.DENIED.value
        assert "cobertura" in (res_denied["job"]["denial_reason"] or "").lower()

        # 3. Guardrail CAPTCHA -> pausa imediata AWAITING_HUMAN_2FA
        job_captcha, _ = orch.store.upsert_job(
            GuideJob(
                id=str(uuid.uuid4()),
                tenant_slug="nova-gesta",
                igut_appointment_id="E2E-CAPTCHA-1",
                patient_name="PACIENTE CAPTCHA",
                insurance_name="GDF Saúde",
                card_number="0045012345678903",
                appointment_type="Ecografia",
                appointment_date="2026-11-25",
                procedure_codes=["40901238"],
                metadata={"medical_order_local_path": str(order_pdf)},
            )
        )
        res_captcha = await orch.process_job(
            job_captcha.id,
            dossier_override=valid_dossier,
            target_url_override=f"http://127.0.0.1:{port}/mock-portal/login?captcha=1",
            headless_override=True,
        )
        assert res_captcha["job"]["status"] == GuideJobStatus.AWAITING_HUMAN_2FA.value
    finally:
        server.should_exit = True
