from __future__ import annotations

from pathlib import Path

from core.database.store import JobStore
from core.domain.models import GuideJob, GuideJobStatus


def test_job_store_idempotency_and_events(tmp_path: Path) -> None:
    store = JobStore(str(tmp_path / "test.db"))
    job = GuideJob(
        id="job-1",
        tenant_slug="nova-gesta",
        igut_appointment_id="881378",
        batch_index=0,
        patient_name="ALINE MIDORI",
        insurance_name="GDF Saúde",
        appointment_date="2026-11-25",
    )

    saved1, created1 = store.upsert_job(job)
    assert created1 is True
    assert saved1.id == "job-1"

    # Mesma combinação (tenant, appointment_id, batch_index) não duplica
    dup = job.model_copy(update={"id": "job-2"})
    saved2, created2 = store.upsert_job(dup)
    assert created2 is False
    assert saved2.id == "job-1"

    updated = store.update_job(
        saved1.id,
        status=GuideJobStatus.AUTHORIZED,
        guide_number="2026999111",
        auth_password="SEN123456",
        metadata_patch={"source": "unit-test"},
    )
    assert updated is not None
    assert updated.status == GuideJobStatus.AUTHORIZED
    assert updated.guide_number == "2026999111"
    assert updated.metadata["source"] == "unit-test"

    store.record_event(saved1.id, "TEST_EVENT", "Evento gravado", {"ok": True})
    events = store.list_events(saved1.id)
    assert len(events) == 1
    assert events[0]["event_type"] == "TEST_EVENT"
    assert events[0]["payload"]["ok"] is True

    counts = store.summary_counts("nova-gesta", appointment_date="2026-11-25")
    assert counts["AUTHORIZED"] == 1
