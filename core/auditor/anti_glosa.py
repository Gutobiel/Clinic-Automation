from __future__ import annotations

import calendar
import re
from datetime import date, datetime
from typing import Any

from core.domain.models import AntiGlosaIssue, AntiGlosaResult, GuideJob, PortalRoute


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    s = str(raw).strip()
    # YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except ValueError:
            return None
    # DD/MM/YYYY
    if re.match(r"^\d{2}/\d{2}/\d{4}$", s):
        try:
            return datetime.strptime(s, "%d/%m/%Y").date()
        except ValueError:
            return None
    # MM/YYYY -> último dia do mês
    m = re.match(r"^(\d{2})/(\d{4})$", s)
    if m:
        month, year = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12:
            last_day = calendar.monthrange(year, month)[1]
            return date(year, month, last_day)
    # MM/YY
    m2 = re.match(r"^(\d{2})/(\d{2})$", s)
    if m2:
        month, year = int(m2.group(1)), 2000 + int(m2.group(2))
        if 1 <= month <= 12:
            last_day = calendar.monthrange(year, month)[1]
            return date(year, month, last_day)
    return None


class AntiGlosaAuditor:
    """Audita carteirinha, validade, pedido médico (assinatura/carimbo/prazo) e códigos TUSS antes do portal."""

    def __init__(self, *, max_medical_order_age_days: int = 60) -> None:
        self.max_medical_order_age_days = max_medical_order_age_days

    def audit(
        self,
        job: GuideJob,
        route: PortalRoute,
        dossier: dict[str, Any] | None = None,
        *,
        medical_order_files: list[dict[str, Any]] | None = None,
        reference_date: date | None = None,
    ) -> AntiGlosaResult:
        dossier = dossier or {}
        ref_date = reference_date or _parse_date(job.appointment_date) or date.today()
        issues: list[AntiGlosaIssue] = []

        # 1. Carteirinha do convênio
        pac_info = dossier.get("paciente") or {}
        conv_info = dossier.get("convenio") or {}
        docs_info = dossier.get("documentos") or {}
        card_doc = docs_info.get("carteirinha_convenio") or {}

        card_number = (
            (job.card_number or "").strip()
            or str(conv_info.get("numero_carteirinha") or "").strip()
            or str(pac_info.get("carteirinha") or "").strip()
            or str(card_doc.get("numero_carteirinha") or "").strip()
        )
        if not card_number or len(re.sub(r"\W+", "", card_number)) < 5:
            issues.append(
                AntiGlosaIssue(
                    code="MISSING_CARD_NUMBER",
                    severity="BLOCKER",
                    message="Número da carteirinha do convênio ausente ou incompleto (solicitar foto da carteirinha).",
                )
            )

        # 2. Validade da carteirinha
        raw_expiry = (
            conv_info.get("validade")
            or conv_info.get("validade_carteirinha")
            or card_doc.get("validade")
            or dossier.get("validade_carteirinha")
        )
        expiry_date = _parse_date(raw_expiry)
        if expiry_date and expiry_date < ref_date:
            issues.append(
                AntiGlosaIssue(
                    code="EXPIRED_CARD",
                    severity="BLOCKER",
                    message=f"Carteirinha do convênio vencida em {expiry_date.strftime('%d/%m/%Y')} (atendimento em {ref_date.strftime('%d/%m/%Y')}).",
                )
            )

        # 3. Pedido médico obrigatório (exames / SP-SADT / GDF Saúde)
        order_doc = docs_info.get("pedido_medico") or dossier.get("pedido_medico") or {}
        order_files = list(medical_order_files or [])
        if isinstance(order_doc, dict) and order_doc.get("drive_file_id"):
            order_files.append({"id": order_doc["drive_file_id"], "name": order_doc.get("file_name", "pedido_medico")})
        elif isinstance(order_doc, list):
            order_files.extend(order_doc)

        medical_order_file_id: str | None = None
        if order_files:
            first = order_files[0]
            medical_order_file_id = str(first.get("id") or first.get("drive_file_id") or "") or None

        if route.requires_medical_order_attachment:
            has_local_order = bool((job.metadata or {}).get("medical_order_local_path"))
            if not medical_order_file_id and not has_local_order:
                issues.append(
                    AntiGlosaIssue(
                        code="MISSING_MEDICAL_ORDER",
                        severity="BLOCKER",
                        message="Pedido médico obrigatório não encontrado na pasta do paciente (03_Pedidos_Medicos).",
                    )
                )
            else:
                # Verifica alertas de OCR/qualidade (assinatura, carimbo, CRM, legibilidade)
                order_meta = order_doc if isinstance(order_doc, dict) else {}
                ocr_alerts = list(order_meta.get("ocr_alertas") or [])
                if order_meta.get("possui_assinatura") is False:
                    ocr_alerts.append("Pedido médico sem assinatura do médico solicitante.")
                if order_meta.get("possui_carimbo_crm") is False:
                    ocr_alerts.append("Pedido médico sem carimbo ou CRM legível.")
                if order_meta.get("legivel") is False:
                    ocr_alerts.append("Imagem do pedido médico ilegível/cortada.")

                for alert in ocr_alerts:
                    issues.append(
                        AntiGlosaIssue(
                            code="INVALID_MEDICAL_ORDER",
                            severity="BLOCKER",
                            message=f"Risco de glosa no pedido médico: {alert}",
                        )
                    )

                raw_order_date = order_meta.get("data_pedido") or order_meta.get("data_emissao")
                order_date = _parse_date(raw_order_date)
                if order_date:
                    age_days = (ref_date - order_date).days
                    if age_days > self.max_medical_order_age_days:
                        issues.append(
                            AntiGlosaIssue(
                                code="EXPIRED_MEDICAL_ORDER",
                                severity="BLOCKER",
                                message=(
                                    f"Pedido médico vencido ({age_days} dias desde {order_date.strftime('%d/%m/%Y')}; "
                                    f"limite {self.max_medical_order_age_days} dias)."
                                ),
                            )
                        )

        # 4. Códigos TUSS resolvidos
        tuss_codes = (
            list(job.procedure_codes)
            or list(route.procedure_codes)
            or list((order_doc.get("codigos_tuss") if isinstance(order_doc, dict) else []) or [])
        )
        if not tuss_codes:
            issues.append(
                AntiGlosaIssue(
                    code="MISSING_TUSS_CODES",
                    severity="BLOCKER",
                    message="Nenhum código TUSS/procedimento identificado para solicitar a guia.",
                )
            )

        blockers = [i for i in issues if i.severity == "BLOCKER"]
        approved = len(blockers) == 0
        alert_message = None
        if not approved:
            bullet_lines = "\n".join(f"- [{b.code}] {b.message}" for b in blockers)
            alert_message = (
                f"Auditoria Anti-Glosa bloqueou a guia de {job.patient_name} ({job.insurance_name}):\n{bullet_lines}"
            )

        return AntiGlosaResult(
            approved=approved,
            status="APROVADO" if approved else "BLOQUEADO_RISCO_GLOSA",
            issues=issues,
            extracted_card_number=card_number or None,
            extracted_card_expiry=expiry_date.isoformat() if expiry_date else (str(raw_expiry) if raw_expiry else None),
            medical_order_file_id=medical_order_file_id,
            alert_message=alert_message,
        )
