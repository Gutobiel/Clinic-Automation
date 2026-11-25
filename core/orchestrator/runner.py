from __future__ import annotations

import logging
import os
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.agent.browser_ai_agent import BrowserAiAgent
from core.auditor.anti_glosa import AntiGlosaAuditor
from core.config.settings import AppSettings, TenantPack, load_tenant_pack
from core.connectors.google_drive import GoogleDriveConnector
from core.connectors.igut_api import IgutApiConnector
from core.connectors.notifier import ClinicNotifier
from core.database.store import JobStore
from core.domain.models import GuideJob, GuideJobStatus, PortalExecutionResult
from core.orchestrator.router import PortalRouter

logger = logging.getLogger(__name__)


def _norm(text: str | None) -> str:
    if not text:
        return ""
    nfd = unicodedata.normalize("NFD", str(text))
    stripped = "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn")
    return " ".join(stripped.upper().strip().split())


class GuideOrchestrator:
    """Orquestrador central da máquina de estados dos GuideJobs."""

    def __init__(
        self,
        settings: AppSettings,
        *,
        tenant_pack: TenantPack | None = None,
        store: JobStore | None = None,
        igut: IgutApiConnector | None = None,
        drive: GoogleDriveConnector | None = None,
        notifier: ClinicNotifier | None = None,
        auditor: AntiGlosaAuditor | None = None,
        browser_agent: BrowserAiAgent | None = None,
    ) -> None:
        self.settings = settings
        self.pack = tenant_pack or load_tenant_pack(settings.tenant_slug)
        self.store = store or JobStore(settings.db_path)
        self.router = PortalRouter(self.pack)
        self.igut = igut or IgutApiConnector(settings)
        self.drive = drive or GoogleDriveConnector(settings)
        self.notifier = notifier or ClinicNotifier(settings)
        self.auditor = auditor or AntiGlosaAuditor()
        self.browser_agent = browser_agent or BrowserAiAgent(settings)

    def _enrich_doctor(self, doctor_name: str) -> tuple[str, str, str]:
        target = _norm(doctor_name)
        for doc in self.pack.doctors:
            if target and (target in _norm(doc.get("name")) or _norm(doc.get("name")) in target):
                return (str(doc.get("crm") or ""), str(doc.get("cbo") or ""), str(doc.get("specialty") or ""))
        return ("", "", "")

    def _portal_credentials(self, portal_key: str) -> dict[str, str]:
        prefix = f"PORTAL_{portal_key.upper()}"
        return {
            "username": os.getenv(f"{prefix}_USER", ""),
            "password": os.getenv(f"{prefix}_PASS", ""),
        }

    async def scan_igut_appointments(
        self,
        date_start: str,
        date_end: str | None = None,
    ) -> dict[str, Any]:
        """Consulta agendamentos no iGUT e cria GuideJobs idempotentes (particionando lotes quando necessário)."""
        appointments = await self.igut.list_scheduled_appointments(date_start, date_end)
        created_jobs: list[GuideJob] = []
        skipped_particular = 0
        skipped_unmapped = 0
        already_existing = 0

        for appt in appointments:
            insurance_name = appt["insurance"]["name"]
            specialty = appt["professional"]["specialty"]
            appt_type = appt["appointment_type"]

            route = self.router.resolve(
                insurance_name=insurance_name,
                specialty=specialty,
                appointment_type=appt_type,
            )
            if route is None:
                if "PARTICULAR" in _norm(insurance_name) or not insurance_name:
                    skipped_particular += 1
                else:
                    skipped_unmapped += 1
                continue

            crm, cbo, doc_spec = self._enrich_doctor(appt["professional"]["name"])
            for batch_idx, batch_codes in enumerate(route.procedure_batches):
                candidate = GuideJob(
                    id=str(uuid.uuid4()),
                    tenant_slug=self.settings.tenant_slug,
                    igut_appointment_id=appt["appointment_id"],
                    batch_index=batch_idx,
                    status=GuideJobStatus.DISCOVERED,
                    patient_name=appt["patient"]["name"],
                    patient_cpf=appt["patient"]["cpf"],
                    patient_phone=appt["patient"]["phone"],
                    insurance_name=insurance_name,
                    doctor_name=appt["professional"]["name"],
                    doctor_crm=crm,
                    doctor_cbo=cbo,
                    specialty=specialty or doc_spec,
                    appointment_type=appt_type,
                    appointment_date=appt["date"],
                    appointment_time=appt["time"],
                    portal_key=route.portal_key,
                    procedure_codes=batch_codes,
                    metadata={"unit": appt["unit"]["name"], "operator_key": route.operator_key},
                )
                saved, was_created = self.store.upsert_job(candidate)
                if was_created:
                    self.store.record_event(
                        saved.id,
                        "JOB_DISCOVERED",
                        f"Job criado a partir do iGUT #{appt['appointment_id']} -> portal {route.display_name}.",
                        {"portal_key": route.portal_key, "batch_index": batch_idx, "procedure_codes": batch_codes},
                    )
                    created_jobs.append(saved)
                else:
                    already_existing += 1

        return {
            "date_start": date_start,
            "date_end": date_end or date_start,
            "total_appointments_found": len(appointments),
            "created": len(created_jobs),
            "already_existing": already_existing,
            "skipped_particular": skipped_particular,
            "skipped_unmapped": skipped_unmapped,
            "jobs": [j.model_dump() for j in created_jobs],
        }

    async def handle_crm_document_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Recebe evento do AGS CRM (Sprint 0) quando um novo documento vai para o Google Drive."""
        patient = payload.get("patient") or {}
        drive_info = payload.get("drive") or {}
        cpf_digits = "".join(ch for ch in str(patient.get("cpf") or "") if ch.isdigit())
        phone_digits = "".join(ch for ch in str(patient.get("phone") or "") if ch.isdigit())
        folder_id = drive_info.get("patient_folder_id")

        candidate_jobs = self.store.list_jobs(tenant_slug=payload.get("tenant_slug") or self.settings.tenant_slug, limit=200)
        matched_ids: list[str] = []

        for job in candidate_jobs:
            if job.status not in (GuideJobStatus.DISCOVERED, GuideJobStatus.BLOCKED_MISSING_DOCS):
                continue
            j_cpf = "".join(ch for ch in job.patient_cpf if ch.isdigit())
            j_phone = "".join(ch for ch in job.patient_phone if ch.isdigit())
            is_match = (
                (cpf_digits and j_cpf and cpf_digits == j_cpf)
                or (phone_digits and j_phone and phone_digits[-8:] == j_phone[-8:])
                or (_norm(patient.get("name")) and _norm(patient.get("name")) == _norm(job.patient_name))
            )
            if not is_match:
                continue

            self.store.update_job(
                job.id,
                drive_patient_folder_id=folder_id or job.drive_patient_folder_id,
                metadata_patch={"last_crm_webhook_event": payload},
            )
            self.store.record_event(
                job.id,
                "CRM_DOC_SYNCED",
                f"Novo documento '{drive_info.get('file_name', 'arquivo')}' sincronizado no Drive ({drive_info.get('category', 'geral')}).",
                {"drive": drive_info},
            )
            matched_ids.append(job.id)

        return {"status": "accepted", "matched_job_ids": matched_ids}

    async def process_job(
        self,
        job_id: str,
        *,
        dossier_override: dict[str, Any] | None = None,
        target_url_override: str | None = None,
        headless_override: bool | None = None,
        slow_mo_override: int | None = None,
        record_video_dir: str | None = None,
        poll_interval_seconds: float = 2.0,
        max_analysis_polls: int = 8,
    ) -> dict[str, Any]:
        """Executa o fluxo completo de um GuideJob: Drive -> Anti-Glosa -> Agente IA -> Pós-processamento."""
        job = self.store.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} não encontrado.")

        route = self.router.resolve(
            insurance_name=job.insurance_name,
            specialty=job.specialty,
            appointment_type=job.appointment_type,
            explicit_tuss_codes=job.procedure_codes or None,
        )
        if not route:
            raise ValueError(f"Não foi possível rotear o convênio '{job.insurance_name}'.")

        # 1. Coleta de Dossiê no Google Drive
        self.store.update_job(job.id, status=GuideJobStatus.DOCS_COLLECTING, portal_key=route.portal_key)
        dossier: dict[str, Any] = dict(dossier_override or {})
        medical_order_files: list[dict[str, Any]] = []
        medical_order_local_path: str | None = (job.metadata or {}).get("medical_order_local_path")

        if not dossier and self.drive.is_configured():
            folder_id = job.drive_patient_folder_id
            if not folder_id:
                folder = await self.drive.find_patient_folder(
                    cpf=job.patient_cpf,
                    phone=job.patient_phone,
                    name=job.patient_name,
                )
                if folder:
                    folder_id = folder["id"]
                    job = self.store.update_job(job.id, drive_patient_folder_id=folder_id) or job
            if folder_id:
                dossier = await self.drive.read_patient_dossier(folder_id)
                medical_order_files = await self.drive.list_subfolder_files(folder_id, "03_Pedidos_Medicos")
                self.store.record_event(
                    job.id,
                    "DRIVE_DOSSIER_LOADED",
                    f"Dossiê carregado do Google Drive (pasta {folder_id}).",
                    {"medical_orders_found": len(medical_order_files)},
                )

        # 2. Auditoria Anti-Glosa
        self.store.update_job(job.id, status=GuideJobStatus.ANTI_GLOSA_AUDIT)
        audit = self.auditor.audit(
            job,
            route,
            dossier,
            medical_order_files=medical_order_files,
        )
        if audit.extracted_card_number and not job.card_number:
            job = self.store.update_job(job.id, card_number=audit.extracted_card_number) or job

        self.store.record_event(
            job.id,
            "ANTI_GLOSA_RESULT",
            f"Auditoria Anti-Glosa: {audit.status}",
            audit.model_dump(),
        )

        # Persiste resultado da auditoria no ficha_paciente.json do Drive se configurado
        if job.drive_patient_folder_id and self.drive.is_configured():
            try:
                await self.drive.update_patient_dossier(
                    job.drive_patient_folder_id,
                    {
                        "auditoria_anti_glosa": {
                            "ultimo_status": audit.status,
                            "ultima_checagem": datetime.now(timezone.utc).isoformat(),
                            "pendencias": [i.message for i in audit.issues],
                        }
                    },
                )
            except Exception as exc:
                logger.warning("Não foi possível atualizar auditoria no Drive: %s", exc)

        if not audit.approved:
            job = self.store.update_job(
                job.id,
                status=GuideJobStatus.BLOCKED_MISSING_DOCS,
                denial_reason=audit.alert_message,
            ) or job
            await self.notifier.notify_anti_glosa_block(job, audit)
            return {"job": job.model_dump(), "audit": audit.model_dump(), "execution": None}

        # 3. Modo SHADOW para após auditoria (não acessa portal)
        job = self.store.update_job(
            job.id,
            status=GuideJobStatus.READY_FOR_PORTAL,
            procedure_codes=job.procedure_codes or route.procedure_codes,
        ) or job

        if self.settings.automation_mode == "SHADOW" and not target_url_override:
            self.store.record_event(
                job.id,
                "SHADOW_MODE_STOP",
                "Modo SHADOW ativo: pronto para o portal, mas execução real pausada por configuração.",
            )
            return {"job": job.model_dump(), "audit": audit.model_dump(), "execution": None}

        # Baixa pedido médico do Drive se necessário para anexo
        if (
            route.requires_medical_order_attachment
            and not medical_order_local_path
            and audit.medical_order_file_id
            and self.drive.is_configured()
        ):
            dest = Path(self.settings.downloads_dir) / f"pedido_{job.id}.pdf"
            await self.drive.download_file(audit.medical_order_file_id, dest)
            medical_order_local_path = str(dest)

        # 4. Execução via Agente IA no Navegador (com monitoramento ativo de aprovação)
        self.store.update_job(job.id, status=GuideJobStatus.PORTAL_RUNNING)
        start_url = target_url_override or route.url
        if not start_url:
            raise ValueError(f"URL de portal não configurada para {route.portal_key}.")

        exec_result: PortalExecutionResult = await self.browser_agent.execute_guide_flow(
            job=job,
            route=route,
            start_url=start_url,
            portal_credentials=self._portal_credentials(route.portal_key),
            medical_order_local_path=medical_order_local_path,
            headless_override=headless_override,
            slow_mo_override=slow_mo_override,
            record_video_dir=record_video_dir,
            poll_interval_seconds=poll_interval_seconds,
            max_analysis_polls=max_analysis_polls,
        )

        self.store.record_event(
            job.id,
            "PORTAL_EXECUTION_FINISHED",
            f"Agente IA concluiu interação no portal com status {exec_result.final_status}.",
            {
                "final_status": exec_result.final_status,
                "guide_number": exec_result.guide_number,
                "auth_password": exec_result.auth_password,
                "validity_date": exec_result.validity_date,
                "steps_count": len(exec_result.steps_executed),
                "ai_provider": exec_result.ai_provider_used,
                "pdf_local_path": exec_result.pdf_local_path,
            },
        )

        # 5. Atualiza status e dispara ações pós-portal (Drive + Notifier)
        if exec_result.final_status == "AUTHORIZED":
            drive_pdf_id: str | None = None
            if exec_result.pdf_local_path and job.drive_patient_folder_id and self.drive.is_configured():
                try:
                    pdf_file = Path(exec_result.pdf_local_path)
                    uploaded = await self.drive.upload_guide_pdf(
                        job.drive_patient_folder_id,
                        pdf_file,
                        pdf_file.name,
                    )
                    drive_pdf_id = uploaded.get("id")
                    await self.drive.update_patient_dossier(
                        job.drive_patient_folder_id,
                        {},
                        append_guide={
                            "job_id": job.id,
                            "igut_appointment_id": job.igut_appointment_id,
                            "portal": route.portal_key,
                            "numero_guia": exec_result.guide_number,
                            "senha": exec_result.auth_password,
                            "validade": exec_result.validity_date,
                            "drive_pdf_file_id": drive_pdf_id,
                            "emitida_em": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                except Exception as exc:
                    logger.warning("Falha ao subir PDF da guia para o Google Drive: %s", exc)

            final_status = (
                GuideJobStatus.COMPLETED
                if self.settings.automation_mode == "AUTONOMOUS"
                else GuideJobStatus.AUTHORIZED
            )
            job = self.store.update_job(
                job.id,
                status=final_status,
                guide_number=exec_result.guide_number,
                auth_password=exec_result.auth_password,
                validity_date=exec_result.validity_date,
                drive_pdf_file_id=drive_pdf_id,
                metadata_patch={
                    "pdf_local_path": exec_result.pdf_local_path,
                    "screenshot_path": exec_result.screenshot_path,
                },
            ) or job
            await self.notifier.notify_guide_authorized(job, exec_result)

        elif exec_result.final_status == "IN_ANALYSIS":
            job = self.store.update_job(
                job.id,
                status=GuideJobStatus.IN_ANALYSIS,
                guide_number=exec_result.guide_number,
                metadata_patch={"screenshot_path": exec_result.screenshot_path},
            ) or job
            await self.notifier.notify_guide_in_analysis(job, exec_result)

        elif exec_result.final_status == "DENIED":
            job = self.store.update_job(
                job.id,
                status=GuideJobStatus.DENIED,
                denial_reason=exec_result.denial_reason,
                metadata_patch={"screenshot_path": exec_result.screenshot_path},
            ) or job
            await self.notifier.notify_guide_denied(job, exec_result)

        elif exec_result.final_status == "AWAITING_HUMAN_2FA":
            job = self.store.update_job(
                job.id,
                status=GuideJobStatus.AWAITING_HUMAN_2FA,
                denial_reason=exec_result.denial_reason,
                metadata_patch={"screenshot_path": exec_result.screenshot_path},
            ) or job
            await self.notifier.notify_needs_human_2fa(job, exec_result)

        elif exec_result.final_status == "CREDENTIAL_LOCKED":
            job = self.store.update_job(
                job.id,
                status=GuideJobStatus.CREDENTIAL_LOCKED,
                denial_reason=exec_result.denial_reason,
            ) or job

        else:
            job = self.store.update_job(
                job.id,
                status=GuideJobStatus.IGUT_CLOSE_FAILED,
                denial_reason=exec_result.denial_reason,
            ) or job

        return {
            "job": job.model_dump(),
            "audit": audit.model_dump(),
            "execution": exec_result.model_dump(),
        }

    async def recheck_in_analysis_jobs(
        self,
        *,
        target_url_override: str | None = None,
        headless_override: bool | None = None,
    ) -> dict[str, Any]:
        pending = self.store.list_jobs(tenant_slug=self.settings.tenant_slug, status=GuideJobStatus.IN_ANALYSIS)
        results = []
        for job in pending:
            res = await self.process_job(
                job.id,
                target_url_override=target_url_override,
                headless_override=headless_override,
            )
            results.append({"job_id": job.id, "new_status": res["job"]["status"]})
        return {"checked": len(results), "results": results}
