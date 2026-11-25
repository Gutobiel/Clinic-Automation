from __future__ import annotations

from datetime import date

from core.auditor.anti_glosa import AntiGlosaAuditor
from core.domain.models import GuideJob, PortalRoute


def _sample_route(requires_order: bool = True) -> PortalRoute:
    return PortalRoute(
        portal_key="gdf_saude",
        display_name="INAS — GDF Saúde",
        motor="MaidaGdfWorker",
        procedure_codes=["40901238"],
        procedure_batches=[["40901238"]],
        requires_medical_order_attachment=requires_order,
    )


def _sample_job() -> GuideJob:
    return GuideJob(
        id="job-test-1",
        tenant_slug="nova-gesta",
        igut_appointment_id="999001",
        patient_name="MARIA CLARA",
        insurance_name="GDF Saúde",
        card_number="0045012345678901",
        appointment_type="Ecografia Obstétrica",
        appointment_date="2026-11-25",
        procedure_codes=["40901238"],
    )


def test_audit_approves_valid_dossier() -> None:
    auditor = AntiGlosaAuditor()
    res = auditor.audit(
        _sample_job(),
        _sample_route(requires_order=True),
        dossier={
            "convenio": {"numero_carteirinha": "0045012345678901", "validade": "12/2027"},
            "documentos": {
                "pedido_medico": {
                    "drive_file_id": "file-123",
                    "data_pedido": "2026-11-15",
                    "possui_assinatura": True,
                    "possui_carimbo_crm": True,
                    "legivel": True,
                }
            },
        },
        reference_date=date(2026, 11, 25),
    )
    assert res.approved is True
    assert res.status == "APROVADO"
    assert res.medical_order_file_id == "file-123"


def test_audit_blocks_expired_card_and_missing_order() -> None:
    auditor = AntiGlosaAuditor()
    res = auditor.audit(
        _sample_job(),
        _sample_route(requires_order=True),
        dossier={"convenio": {"validade": "2026-10-31"}, "documentos": {}},
        reference_date=date(2026, 11, 25),
    )
    assert res.approved is False
    assert res.status == "BLOQUEADO_RISCO_GLOSA"
    codes = {i.code for i in res.issues}
    assert "EXPIRED_CARD" in codes
    assert "MISSING_MEDICAL_ORDER" in codes
    assert res.alert_message is not None


def test_audit_blocks_order_without_signature_and_old_date() -> None:
    auditor = AntiGlosaAuditor(max_medical_order_age_days=60)
    res = auditor.audit(
        _sample_job(),
        _sample_route(requires_order=True),
        dossier={
            "convenio": {"validade": "31/12/2027"},
            "documentos": {
                "pedido_medico": {
                    "drive_file_id": "file-old",
                    "data_pedido": "2026-08-01",
                    "possui_assinatura": False,
                    "possui_carimbo_crm": False,
                }
            },
        },
        reference_date=date(2026, 11, 25),
    )
    assert res.approved is False
    codes = {i.code for i in res.issues}
    assert "INVALID_MEDICAL_ORDER" in codes
    assert "EXPIRED_MEDICAL_ORDER" in codes


def test_audit_blocks_missing_card_and_tuss() -> None:
    auditor = AntiGlosaAuditor()
    job = _sample_job()
    job.card_number = ""
    job.procedure_codes = []
    route = _sample_route(requires_order=False)
    route.procedure_codes = []
    res = auditor.audit(job, route, dossier={})
    assert res.approved is False
    codes = {i.code for i in res.issues}
    assert "MISSING_CARD_NUMBER" in codes
    assert "MISSING_TUSS_CODES" in codes
