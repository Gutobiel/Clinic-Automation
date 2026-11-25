from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from core.api.mock_portal import router as mock_portal_router
from core.config.settings import AppSettings
from core.domain.models import CrmWebhookPayload, GuideJob, GuideJobStatus
from core.orchestrator.runner import GuideOrchestrator


class CreateJobRequest(BaseModel):
    tenant_slug: str = "nova-gesta"
    igut_appointment_id: str
    patient_name: str
    patient_cpf: str = ""
    patient_phone: str = ""
    insurance_name: str
    card_number: str = ""
    doctor_name: str = ""
    doctor_crm: str = ""
    doctor_cbo: str = ""
    specialty: str = ""
    appointment_type: str = "Consulta"
    appointment_date: str = ""
    appointment_time: str = ""
    procedure_codes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScanIgutRequest(BaseModel):
    date_start: str
    date_end: str | None = None


class RunJobRequest(BaseModel):
    dossier_override: dict[str, Any] | None = None
    target_url_override: str | None = None
    headless_override: bool | None = None
    slow_mo_override: int | None = None
    poll_interval_seconds: float = 2.0
    max_analysis_polls: int = 8


def create_app(
    settings: AppSettings | None = None,
    orchestrator: GuideOrchestrator | None = None,
) -> FastAPI:
    app_settings = settings or AppSettings.load()
    orch = orchestrator or GuideOrchestrator(app_settings)

    app = FastAPI(
        title="Clinic Automation API (Aegis + Hermes)",
        version="0.1.0",
        description="Plataforma multi-clínica para auditoria Anti-Glosa e emissão/monitoramento de guias médicas por IA.",
    )
    app.state.settings = app_settings
    app.state.orchestrator = orch
    app.state.recent_webhooks = []
    app.include_router(mock_portal_router)

    @app.get("/")
    async def root() -> dict[str, Any]:
        return {
            "service": "AEGIS Clinic Automation (Hermes Worker)",
            "status": "online",
            "tenant_slug": app_settings.tenant_slug,
            "webhook_endpoint": "/api/v1/webhooks/crm-event",
            "recent_webhooks_count": len(app.state.recent_webhooks),
            "recent_webhooks": app.state.recent_webhooks[:10],
        }

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "tenant_slug": app_settings.tenant_slug,
            "automation_mode": app_settings.automation_mode,
            "ai_provider": app_settings.ai_provider,
            "drive_configured": orch.drive.is_configured(),
            "igut_configured": orch.igut.is_configured(),
        }

    @app.post("/api/v1/webhooks/crm-event")
    async def receive_crm_webhook(
        payload: CrmWebhookPayload,
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    ) -> dict[str, Any]:
        if app_settings.crm_webhook_api_key and x_api_key != app_settings.crm_webhook_api_key:
            raise HTTPException(status_code=401, detail="X-API-Key inválida.")
        raw = payload.model_dump()
        patient_name = (raw.get("patient") or {}).get("name") or "N/A"
        file_name = (raw.get("drive") or {}).get("file_name") or "-"
        event_name = raw.get("event") or "unknown"
        is_test = bool(raw.get("test"))
        print("\n" + "=" * 72, flush=True)
        print(f" [WEBHOOK RECEBIDO DO AGS CRM] Evento: {event_name} {'(TESTE)' if is_test else '(REAL)'}", flush=True)
        print(f" Tenant: {raw.get('tenant_slug')} | Paciente: {patient_name} | Arquivo: {file_name}", flush=True)
        print("=" * 72 + "\n", flush=True)
        result = await orch.handle_crm_document_webhook(raw)
        entry = {
            "event": event_name,
            "test": is_test,
            "tenant_slug": raw.get("tenant_slug"),
            "patient_name": patient_name,
            "file_name": file_name,
            "timestamp": raw.get("timestamp"),
            "matched_job_ids": result.get("matched_job_ids", []),
        }
        app.state.recent_webhooks.insert(0, entry)
        app.state.recent_webhooks = app.state.recent_webhooks[:30]

        launched_real_worker = False
        folder_id = (raw.get("drive") or {}).get("patient_folder_id")
        if (
            not is_test
            and event_name == "document.synced_to_drive"
            and folder_id
            and os.getenv("AUTO_OPEN_REAL_AMHP_ON_WEBHOOK", "").strip() in ("1", "true", "yes")
        ):
            root_dir = Path(__file__).resolve().parents[2]
            script_path = root_dir / "scripts" / "emitir_guia_real_amhp.py"
            if script_path.exists():
                auto_mode = os.getenv("AUTO_WEBHOOK_AMHP_MODE", "fill_only")
                print(
                    f" [AUTO-DISPARO REAL] Abrindo Chrome no Portal AMHP para pasta Drive {folder_id} (modo={auto_mode})...",
                    flush=True,
                )
                subprocess.Popen(
                    [sys.executable, str(script_path), "--folder-id", str(folder_id), "--mode", auto_mode],
                    cwd=str(root_dir),
                )
                launched_real_worker = True

        return {
            **result,
            "received_event": event_name,
            "test": is_test,
            "launched_real_worker": launched_real_worker,
            "worker": "clinic-automation-local",
            "tenant_slug": app_settings.tenant_slug,
            "message": (
                f"Evento de teste '{event_name}' recebido com sucesso pelo servidor da clinica!"
                if is_test
                else (
                    f"Evento real '{event_name}' recebido e robo do portal AMHP disparado para o paciente!"
                    if launched_real_worker
                    else f"Evento '{event_name}' processado pelo orquestrador da clinica."
                )
            ),
        }

    @app.post("/api/v1/jobs")
    async def create_job(req: CreateJobRequest) -> dict[str, Any]:
        route = orch.router.resolve(
            insurance_name=req.insurance_name,
            specialty=req.specialty,
            appointment_type=req.appointment_type,
            explicit_tuss_codes=req.procedure_codes or None,
        )
        job = GuideJob(
            id=str(uuid.uuid4()),
            tenant_slug=req.tenant_slug,
            igut_appointment_id=req.igut_appointment_id,
            patient_name=req.patient_name,
            patient_cpf=req.patient_cpf,
            patient_phone=req.patient_phone,
            insurance_name=req.insurance_name,
            card_number=req.card_number,
            doctor_name=req.doctor_name,
            doctor_crm=req.doctor_crm,
            doctor_cbo=req.doctor_cbo,
            specialty=req.specialty,
            appointment_type=req.appointment_type,
            appointment_date=req.appointment_date,
            appointment_time=req.appointment_time,
            portal_key=route.portal_key if route else "",
            procedure_codes=req.procedure_codes or (route.procedure_codes if route else []),
            metadata=req.metadata,
        )
        saved, created = orch.store.upsert_job(job)
        if created:
            orch.store.record_event(saved.id, "JOB_CREATED_API", "Job criado via API.")
        return {"created": created, "job": saved.model_dump()}

    @app.get("/api/v1/jobs")
    async def list_jobs(
        tenant_slug: str | None = None,
        status: GuideJobStatus | None = None,
        appointment_date: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        jobs = orch.store.list_jobs(
            tenant_slug=tenant_slug or app_settings.tenant_slug,
            status=status,
            appointment_date=appointment_date,
            limit=limit,
        )
        return {"count": len(jobs), "jobs": [j.model_dump() for j in jobs]}

    @app.get("/api/v1/jobs/{job_id}")
    async def get_job(job_id: str) -> dict[str, Any]:
        job = orch.store.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job não encontrado.")
        return {"job": job.model_dump(), "events": orch.store.list_events(job_id)}

    @app.post("/api/v1/jobs/scan-igut")
    async def scan_igut(req: ScanIgutRequest) -> dict[str, Any]:
        return await orch.scan_igut_appointments(req.date_start, req.date_end)

    @app.post("/api/v1/jobs/{job_id}/run")
    async def run_job(job_id: str, req: RunJobRequest | None = None) -> dict[str, Any]:
        body = req or RunJobRequest()
        try:
            return await orch.process_job(
                job_id,
                dossier_override=body.dossier_override,
                target_url_override=body.target_url_override,
                headless_override=body.headless_override,
                slow_mo_override=body.slow_mo_override,
                poll_interval_seconds=body.poll_interval_seconds,
                max_analysis_polls=body.max_analysis_polls,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/v1/jobs/recheck-analysis")
    async def recheck_analysis() -> dict[str, Any]:
        return await orch.recheck_in_analysis_jobs()

    @app.get("/api/v1/summary")
    async def summary(tenant_slug: str | None = None, appointment_date: str | None = None) -> dict[str, Any]:
        slug = tenant_slug or app_settings.tenant_slug
        counts = orch.store.summary_counts(slug, appointment_date=appointment_date)
        return {"tenant_slug": slug, "appointment_date": appointment_date, "counts": counts}

    return app


app = create_app()
