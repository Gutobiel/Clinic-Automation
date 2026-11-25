from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.domain.models import GuideJob, GuideJobStatus


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    """Persistência SQLite WAL com idempotência e trilha completa de auditoria."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS guide_jobs (
                    id TEXT PRIMARY KEY,
                    tenant_slug TEXT NOT NULL,
                    igut_appointment_id TEXT NOT NULL,
                    batch_index INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    patient_name TEXT NOT NULL,
                    patient_cpf TEXT NOT NULL DEFAULT '',
                    patient_phone TEXT NOT NULL DEFAULT '',
                    insurance_name TEXT NOT NULL DEFAULT '',
                    card_number TEXT NOT NULL DEFAULT '',
                    doctor_name TEXT NOT NULL DEFAULT '',
                    doctor_crm TEXT NOT NULL DEFAULT '',
                    doctor_cbo TEXT NOT NULL DEFAULT '',
                    specialty TEXT NOT NULL DEFAULT '',
                    appointment_type TEXT NOT NULL DEFAULT 'Consulta',
                    appointment_date TEXT NOT NULL DEFAULT '',
                    appointment_time TEXT NOT NULL DEFAULT '',
                    portal_key TEXT NOT NULL DEFAULT '',
                    procedure_codes_json TEXT NOT NULL DEFAULT '[]',
                    guide_number TEXT,
                    auth_password TEXT,
                    validity_date TEXT,
                    drive_patient_folder_id TEXT,
                    drive_pdf_file_id TEXT,
                    denial_reason TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(tenant_slug, igut_appointment_id, batch_index)
                );

                CREATE TABLE IF NOT EXISTS job_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES guide_jobs(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_jobs_tenant_status
                    ON guide_jobs(tenant_slug, status);
                CREATE INDEX IF NOT EXISTS idx_jobs_date
                    ON guide_jobs(tenant_slug, appointment_date);
                CREATE INDEX IF NOT EXISTS idx_events_job
                    ON job_events(job_id, id);
                """
            )

    def _row_to_job(self, row: sqlite3.Row) -> GuideJob:
        return GuideJob(
            id=row["id"],
            tenant_slug=row["tenant_slug"],
            igut_appointment_id=row["igut_appointment_id"],
            batch_index=row["batch_index"],
            status=GuideJobStatus(row["status"]),
            patient_name=row["patient_name"],
            patient_cpf=row["patient_cpf"],
            patient_phone=row["patient_phone"],
            insurance_name=row["insurance_name"],
            card_number=row["card_number"],
            doctor_name=row["doctor_name"],
            doctor_crm=row["doctor_crm"],
            doctor_cbo=row["doctor_cbo"],
            specialty=row["specialty"],
            appointment_type=row["appointment_type"],
            appointment_date=row["appointment_date"],
            appointment_time=row["appointment_time"],
            portal_key=row["portal_key"],
            procedure_codes=json.loads(row["procedure_codes_json"] or "[]"),
            guide_number=row["guide_number"],
            auth_password=row["auth_password"],
            validity_date=row["validity_date"],
            drive_patient_folder_id=row["drive_patient_folder_id"],
            drive_pdf_file_id=row["drive_pdf_file_id"],
            denial_reason=row["denial_reason"],
            metadata=json.loads(row["metadata_json"] or "{}"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def upsert_job(self, job: GuideJob) -> tuple[GuideJob, bool]:
        """Cria um novo GuideJob se não existir; retorna (job, created)."""
        now = _utc_now()
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT * FROM guide_jobs
                WHERE tenant_slug = ? AND igut_appointment_id = ? AND batch_index = ?
                """,
                (job.tenant_slug, job.igut_appointment_id, job.batch_index),
            ).fetchone()
            if existing:
                return self._row_to_job(existing), False

            job_id = job.id or str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO guide_jobs (
                    id, tenant_slug, igut_appointment_id, batch_index, status,
                    patient_name, patient_cpf, patient_phone, insurance_name, card_number,
                    doctor_name, doctor_crm, doctor_cbo, specialty, appointment_type,
                    appointment_date, appointment_time, portal_key, procedure_codes_json,
                    guide_number, auth_password, validity_date, drive_patient_folder_id,
                    drive_pdf_file_id, denial_reason, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    job.tenant_slug,
                    job.igut_appointment_id,
                    job.batch_index,
                    job.status.value,
                    job.patient_name,
                    job.patient_cpf,
                    job.patient_phone,
                    job.insurance_name,
                    job.card_number,
                    job.doctor_name,
                    job.doctor_crm,
                    job.doctor_cbo,
                    job.specialty,
                    job.appointment_type,
                    job.appointment_date,
                    job.appointment_time,
                    job.portal_key,
                    json.dumps(job.procedure_codes, ensure_ascii=False),
                    job.guide_number,
                    job.auth_password,
                    job.validity_date,
                    job.drive_patient_folder_id,
                    job.drive_pdf_file_id,
                    job.denial_reason,
                    json.dumps(job.metadata, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            created_row = conn.execute("SELECT * FROM guide_jobs WHERE id = ?", (job_id,)).fetchone()
            return self._row_to_job(created_row), True

    def get_job(self, job_id: str) -> GuideJob | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM guide_jobs WHERE id = ?", (job_id,)).fetchone()
            return self._row_to_job(row) if row else None

    def list_jobs(
        self,
        tenant_slug: str | None = None,
        status: GuideJobStatus | None = None,
        appointment_date: str | None = None,
        limit: int = 100,
    ) -> list[GuideJob]:
        clauses: list[str] = []
        params: list[Any] = []
        if tenant_slug:
            clauses.append("tenant_slug = ?")
            params.append(tenant_slug)
        if status:
            clauses.append("status = ?")
            params.append(status.value)
        if appointment_date:
            clauses.append("appointment_date = ?")
            params.append(appointment_date)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM guide_jobs {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
            return [self._row_to_job(r) for r in rows]

    def update_job(
        self,
        job_id: str,
        *,
        status: GuideJobStatus | None = None,
        card_number: str | None = None,
        portal_key: str | None = None,
        procedure_codes: list[str] | None = None,
        guide_number: str | None = None,
        auth_password: str | None = None,
        validity_date: str | None = None,
        drive_patient_folder_id: str | None = None,
        drive_pdf_file_id: str | None = None,
        denial_reason: str | None = None,
        metadata_patch: dict[str, Any] | None = None,
    ) -> GuideJob | None:
        current = self.get_job(job_id)
        if not current:
            return None

        updates: dict[str, Any] = {"updated_at": _utc_now()}
        if status is not None:
            updates["status"] = status.value
        if card_number is not None:
            updates["card_number"] = card_number
        if portal_key is not None:
            updates["portal_key"] = portal_key
        if procedure_codes is not None:
            updates["procedure_codes_json"] = json.dumps(procedure_codes, ensure_ascii=False)
        if guide_number is not None:
            updates["guide_number"] = guide_number
        if auth_password is not None:
            updates["auth_password"] = auth_password
        if validity_date is not None:
            updates["validity_date"] = validity_date
        if drive_patient_folder_id is not None:
            updates["drive_patient_folder_id"] = drive_patient_folder_id
        if drive_pdf_file_id is not None:
            updates["drive_pdf_file_id"] = drive_pdf_file_id
        if denial_reason is not None:
            updates["denial_reason"] = denial_reason
        if metadata_patch:
            merged = {**current.metadata, **metadata_patch}
            updates["metadata_json"] = json.dumps(merged, ensure_ascii=False)

        set_clause = ", ".join(f"{col} = ?" for col in updates.keys())
        values = list(updates.values()) + [job_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE guide_jobs SET {set_clause} WHERE id = ?", values)
        return self.get_job(job_id)

    def record_event(self, job_id: str, event_type: str, message: str, payload: dict[str, Any] | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO job_events (job_id, event_type, message, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (job_id, event_type, message, json.dumps(payload or {}, ensure_ascii=False), _utc_now()),
            )

    def list_events(self, job_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, job_id, event_type, message, payload_json, created_at FROM job_events WHERE job_id = ? ORDER BY id ASC",
                (job_id,),
            ).fetchall()
            return [
                {
                    "id": r["id"],
                    "job_id": r["job_id"],
                    "event_type": r["event_type"],
                    "message": r["message"],
                    "payload": json.loads(r["payload_json"] or "{}"),
                    "created_at": r["created_at"],
                }
                for r in rows
            ]

    def summary_counts(self, tenant_slug: str, appointment_date: str | None = None) -> dict[str, int]:
        where = "WHERE tenant_slug = ?"
        params: list[Any] = [tenant_slug]
        if appointment_date:
            where += " AND appointment_date = ?"
            params.append(appointment_date)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT status, COUNT(*) as qtd FROM guide_jobs {where} GROUP BY status",
                params,
            ).fetchall()
            return {r["status"]: int(r["qtd"]) for r in rows}
