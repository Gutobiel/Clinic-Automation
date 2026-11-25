from __future__ import annotations

import unicodedata
from typing import Any

from core.config.settings import TenantPack
from core.domain.models import PortalRoute


def _norm(text: str | None) -> str:
    if not text:
        return ""
    nfd = unicodedata.normalize("NFD", str(text))
    stripped = "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn")
    return " ".join(stripped.upper().strip().split())


class PortalRouter:
    """Resolve convênio + especialidade + procedimentos -> Portal, Motor, Códigos e Lotes."""

    def __init__(self, tenant_pack: TenantPack) -> None:
        self.pack = tenant_pack

    def resolve(
        self,
        insurance_name: str,
        specialty: str = "",
        appointment_type: str = "Consulta",
        explicit_tuss_codes: list[str] | None = None,
    ) -> PortalRoute | None:
        ins_norm = _norm(insurance_name)
        if not ins_norm or "PARTICULAR" in ins_norm:
            return None

        matched_portal_key: str | None = None
        matched_portal_cfg: dict[str, Any] | None = None
        matched_op_key: str | None = None
        matched_op_label: str | None = None

        for portal_key, cfg in self.pack.portals.items():
            # Verifica operadores internos (ex: Benner Conecta AMHP: Senado, STF, TRE...)
            operators = cfg.get("operators") or {}
            for op_key, op_cfg in operators.items():
                aliases = [_norm(a) for a in op_cfg.get("aliases", [])] + [_norm(op_cfg.get("label", ""))]
                if any(a and (a in ins_norm or ins_norm in a) for a in aliases):
                    matched_portal_key = portal_key
                    matched_portal_cfg = cfg
                    matched_op_key = op_key
                    matched_op_label = op_cfg.get("label")
                    break
            if matched_portal_key:
                break

            aliases = [_norm(a) for a in cfg.get("aliases", [])] + [_norm(cfg.get("display_name", ""))]
            if any(a and (a in ins_norm or ins_norm in a) for a in aliases):
                matched_portal_key = portal_key
                matched_portal_cfg = cfg
                break

        if not matched_portal_key or not matched_portal_cfg:
            return None

        codes = self._resolve_procedure_codes(
            portal_key=matched_portal_key,
            operator_key=matched_op_key,
            specialty=specialty,
            appointment_type=appointment_type,
            explicit_tuss_codes=explicit_tuss_codes,
        )

        max_items = int(matched_portal_cfg.get("max_items_per_guide") or 10)
        batches = [codes[i : i + max_items] for i in range(0, len(codes), max_items)] if codes else [[]]

        url = (
            matched_portal_cfg.get("sp_sadt_url")
            or matched_portal_cfg.get("consult_url")
            or matched_portal_cfg.get("auth_request_url")
            or matched_portal_cfg.get("request_url")
            or matched_portal_cfg.get("base_url")
            or matched_portal_cfg.get("login_url")
            or ""
        )

        is_exam = any(k in _norm(appointment_type) for k in ("ECOGRAFIA", "EXAME", "ULTRASSOM", "MORFOLOG", "DOPPLER", "CARDIO", "PROCEDIMENTO"))

        return PortalRoute(
            portal_key=matched_portal_key,
            display_name=matched_portal_cfg.get("display_name", matched_portal_key),
            motor=matched_portal_cfg.get("motor", "GenericAiBrowserWorker"),
            operator_key=matched_op_key,
            operator_label=matched_op_label,
            provider_mode=matched_portal_cfg.get("provider_mode", "direct"),
            url=url,
            wes_mode=matched_portal_cfg.get("wes_mode"),
            procedure_codes=codes,
            procedure_batches=batches,
            requires_medical_order_attachment=bool(
                matched_portal_cfg.get("requires_medical_order_attachment", False) or is_exam
            ),
            requires_capture_and_execute_step=bool(
                matched_portal_cfg.get("requires_capture_and_execute_step", False)
            ),
            max_items_per_guide=max_items,
        )

    def _resolve_procedure_codes(
        self,
        *,
        portal_key: str,
        operator_key: str | None,
        specialty: str,
        appointment_type: str,
        explicit_tuss_codes: list[str] | None,
    ) -> list[str]:
        if explicit_tuss_codes:
            return [str(c).strip() for c in explicit_tuss_codes if str(c).strip()]

        proc_map = self.pack.procedures_map or {}
        consultas_map = proc_map.get("consultas_por_operadora", {})
        lookup_key = operator_key or portal_key
        op_table = consultas_map.get(lookup_key) or consultas_map.get(portal_key) or {}

        spec_norm = _norm(specialty)
        if "PEDIATR" in spec_norm and "CIRURG" in spec_norm and op_table.get("cirurgia_pediatrica"):
            return [str(op_table["cirurgia_pediatrica"])]
        if "PEDIATR" in spec_norm and op_table.get("pediatria"):
            return [str(op_table["pediatria"])]
        if ("GINEC" in spec_norm or "OBSTET" in spec_norm) and op_table.get("ginecologia"):
            return [str(op_table["ginecologia"])]
        if "CLINIC" in spec_norm and op_table.get("clinica_medica"):
            return [str(op_table["clinica_medica"])]

        if op_table.get("default"):
            return [str(op_table["default"])]

        # Exame sem TUSS explícito: retorna lista vazia para o Auditor Anti-Glosa exigir/extrair do pedido médico
        if any(k in _norm(appointment_type) for k in ("ECOGRAFIA", "EXAME", "ULTRASSOM", "MORFOLOG", "DOPPLER")):
            return []

        return [str(proc_map.get("default_tuss_consulta", "10101012"))]
