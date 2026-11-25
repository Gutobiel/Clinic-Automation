from __future__ import annotations

import logging
from typing import Any

import httpx

from core.config.settings import AppSettings
from core.domain.models import AntiGlosaResult, GuideJob, PortalExecutionResult

logger = logging.getLogger(__name__)


class ClinicNotifier:
    """Envia alertas estruturados para o Grupo da Clínica (Telegram / Hermes Gateway / Log)."""

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.sent_messages: list[dict[str, Any]] = []

    async def send(self, text: str, *, event_type: str = "info", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        record = {"event_type": event_type, "text": text, "metadata": metadata or {}, "delivered_via": []}
        self.sent_messages.append(record)
        logger.info("[NOTIFIER:%s]\n%s", event_type, text)

        if self.settings.telegram_bot_token and self.settings.telegram_group_chat_id:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(
                        f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage",
                        json={
                            "chat_id": self.settings.telegram_group_chat_id,
                            "text": text,
                            "parse_mode": "Markdown",
                        },
                    )
                    if resp.is_success:
                        record["delivered_via"].append("telegram")
            except Exception as exc:
                logger.warning("Falha ao enviar notificação Telegram: %s", exc)

        if self.settings.notifier_webhook_url:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(
                        self.settings.notifier_webhook_url,
                        json={"event_type": event_type, "text": text, "metadata": metadata or {}},
                    )
                    if resp.is_success:
                        record["delivered_via"].append("webhook")
            except Exception as exc:
                logger.warning("Falha ao enviar notificação Webhook: %s", exc)

        if not record["delivered_via"]:
            record["delivered_via"].append("local_log")
        return record

    async def notify_anti_glosa_block(self, job: GuideJob, audit: AntiGlosaResult) -> dict[str, Any]:
        issues_txt = "\n".join(f"• {i.message}" for i in audit.issues)
        msg = (
            f"🚨 *ALERTA ANTI-GLOSA — GUIA BLOQUEADA*\n"
            f"Paciente: *{job.patient_name}*\n"
            f"Convênio: {job.insurance_name or 'Não informado'}\n"
            f"Consulta/Exame: {job.appointment_type} ({job.appointment_date} {job.appointment_time})\n"
            f"Pendências detectadas:\n{issues_txt}\n"
            f"Ação: regularizar documentação antes do atendimento para evitar glosa."
        )
        return await self.send(msg, event_type="anti_glosa_block", metadata={"job_id": job.id})

    async def notify_guide_in_analysis(self, job: GuideJob, result: PortalExecutionResult) -> dict[str, Any]:
        msg = (
            f"⏳ *GUIA EM ANÁLISE NO CONVÊNIO*\n"
            f"Paciente: *{job.patient_name}* | Convênio: {job.insurance_name}\n"
            f"Portal: {job.portal_key} | Protocolo/Guia: `{result.guide_number or result.protocol_number or 'Aguardando'}`\n"
            f"O agente continuará monitorando automaticamente até sair a aprovação."
        )
        return await self.send(msg, event_type="guide_in_analysis", metadata={"job_id": job.id})

    async def notify_guide_authorized(self, job: GuideJob, result: PortalExecutionResult) -> dict[str, Any]:
        msg = (
            f"✅ *GUIA AUTORIZADA COM SUCESSO*\n"
            f"Paciente: *{job.patient_name}* | Convênio: {job.insurance_name}\n"
            f"Nº Guia: `{result.guide_number or '-'}` | Senha: `{result.auth_password or '-'}`\n"
            f"Validade: `{result.validity_date or '-'}`\n"
            f"PDF salvo: `{result.pdf_local_path or 'Em processamento'}`"
        )
        return await self.send(msg, event_type="guide_authorized", metadata={"job_id": job.id})

    async def notify_guide_denied(self, job: GuideJob, result: PortalExecutionResult) -> dict[str, Any]:
        msg = (
            f"❌ *GUIA NEGADA PELO CONVÊNIO*\n"
            f"Paciente: *{job.patient_name}* | Convênio: {job.insurance_name}\n"
            f"Motivo retornado: {result.denial_reason or 'Não informado pelo portal'}\n"
            f"Ação necessária: verificar com a operadora ou recepção."
        )
        return await self.send(msg, event_type="guide_denied", metadata={"job_id": job.id})

    async def notify_needs_human_2fa(self, job: GuideJob, result: PortalExecutionResult) -> dict[str, Any]:
        msg = (
            f"🔐 *INTERVENÇÃO HUMANA NECESSÁRIA (2FA / CAPTCHA)*\n"
            f"Paciente: *{job.patient_name}* | Portal: {job.portal_key}\n"
            f"Detalhe: {result.denial_reason or 'O portal solicitou validação humana ou CAPTCHA.'}\n"
            f"O robô pausou com segurança e aguarda liberação."
        )
        return await self.send(msg, event_type="needs_human_2fa", metadata={"job_id": job.id})

    async def notify_daily_summary(self, tenant_slug: str, date_iso: str, counts: dict[str, int]) -> dict[str, Any]:
        total = sum(counts.values())
        lines = [
            f"📊 *FECHAMENTO DE GUIAS — {tenant_slug.upper()} ({date_iso})*",
            f"Total de jobs: *{total}*",
            f"• Autorizadas/Concluídas: {counts.get('AUTHORIZED', 0) + counts.get('COMPLETED', 0)}",
            f"• Em Análise (monitoradas): {counts.get('IN_ANALYSIS', 0)}",
            f"• Bloqueadas Anti-Glosa: {counts.get('BLOCKED_MISSING_DOCS', 0)}",
            f"• Negadas: {counts.get('DENIED', 0)}",
            f"• Aguardando 2FA/Humano: {counts.get('AWAITING_HUMAN_2FA', 0)}",
        ]
        return await self.send("\n".join(lines), event_type="daily_summary", metadata={"counts": counts})
