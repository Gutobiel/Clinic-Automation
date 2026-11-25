from __future__ import annotations

from core.config.settings import load_tenant_pack
from core.orchestrator.router import PortalRouter


def _router() -> PortalRouter:
    return PortalRouter(load_tenant_pack("nova-gesta"))


def test_particular_is_ignored() -> None:
    router = _router()
    assert router.resolve("Particular", "Ginecologia") is None
    assert router.resolve("", "Ginecologia") is None


def test_gdf_saude_splits_into_batches_of_four() -> None:
    router = _router()
    codes = ["40901238", "40901246", "40901254", "40901262", "40901270", "40901289"]
    route = router.resolve(
        insurance_name="INAS - GDF Saúde",
        specialty="Obstetrícia",
        appointment_type="Ecografia Morfológica",
        explicit_tuss_codes=codes,
    )
    assert route is not None
    assert route.portal_key == "gdf_saude"
    assert route.motor == "MaidaGdfWorker"
    assert route.requires_medical_order_attachment is True
    assert route.requires_capture_and_execute_step is True
    assert route.procedure_batches == [codes[:4], codes[4:]]


def test_benner_conecta_amhp_resolves_operator_alias() -> None:
    router = _router()
    route = router.resolve(insurance_name="SIS - Senado", specialty="Ginecologia e Obstetrícia")
    assert route is not None
    assert route.portal_key == "benner_conecta_amhp"
    assert route.operator_key == "senado_federal"
    assert route.operator_label == "SENADO FEDERAL"
    assert route.provider_mode == "amhp"
    assert len(route.procedure_codes) == 1


def test_other_portals_route_correctly() -> None:
    router = _router()
    assert router.resolve("Postal Saúde", "Ginecologia").portal_key == "postal_saude"  # type: ignore[union-attr]
    assert router.resolve("Plan-Assiste MPU", "Pediatria").portal_key == "plan_assiste"  # type: ignore[union-attr]
    assert router.resolve("Saúde Caixa", "Ginecologia").portal_key == "saude_caixa"  # type: ignore[union-attr]
    assert router.resolve("Pró-Saúde TJDFT", "Ginecologia").portal_key == "prosaude_tjdft"  # type: ignore[union-attr]
    assert router.resolve("Amil", "Ginecologia").portal_key == "amil"  # type: ignore[union-attr]
    assert router.resolve("PF Saúde", "Ginecologia").portal_key == "pf_saude"  # type: ignore[union-attr]
    assert router.resolve("TST-Saúde", "Ginecologia").portal_key == "tst_saude"  # type: ignore[union-attr]
