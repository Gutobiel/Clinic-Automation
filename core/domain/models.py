from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class GuideJobStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    DOCS_COLLECTING = "DOCS_COLLECTING"
    ANTI_GLOSA_AUDIT = "ANTI_GLOSA_AUDIT"
    BLOCKED_MISSING_DOCS = "BLOCKED_MISSING_DOCS"
    READY_FOR_PORTAL = "READY_FOR_PORTAL"
    PORTAL_RUNNING = "PORTAL_RUNNING"
    AWAITING_HUMAN_2FA = "AWAITING_HUMAN_2FA"
    CREDENTIAL_LOCKED = "CREDENTIAL_LOCKED"
    IN_ANALYSIS = "IN_ANALYSIS"
    DENIED = "DENIED"
    AUTHORIZED = "AUTHORIZED"
    IGUT_CLOSING = "IGUT_CLOSING"
    IGUT_CLOSE_FAILED = "IGUT_CLOSE_FAILED"
    COMPLETED = "COMPLETED"


class PortalRoute(BaseModel):
    portal_key: str
    display_name: str
    motor: str
    operator_key: str | None = None
    operator_label: str | None = None
    provider_mode: str = "direct"
    url: str = ""
    wes_mode: str | None = None
    procedure_codes: list[str] = Field(default_factory=list)
    procedure_batches: list[list[str]] = Field(default_factory=list)
    requires_medical_order_attachment: bool = False
    requires_capture_and_execute_step: bool = False
    max_items_per_guide: int = 10


class AntiGlosaIssue(BaseModel):
    code: str
    severity: Literal["BLOCKER", "WARNING"] = "BLOCKER"
    message: str


class AntiGlosaResult(BaseModel):
    approved: bool
    status: Literal["APROVADO", "BLOQUEADO_RISCO_GLOSA"]
    issues: list[AntiGlosaIssue] = Field(default_factory=list)
    extracted_card_number: str | None = None
    extracted_card_expiry: str | None = None
    medical_order_file_id: str | None = None
    alert_message: str | None = None


class BrowserActionDecision(BaseModel):
    thought: str
    action: Literal["click", "fill", "select", "upload", "wait", "refresh", "done", "needs_human", "fail"]
    element_id: int | None = None
    value: str | None = None
    wait_seconds: float | None = None
    portal_status: Literal["RUNNING", "IN_ANALYSIS", "AUTHORIZED", "DENIED", "AWAITING_HUMAN_2FA"] = "RUNNING"
    guide_number: str | None = None
    auth_password: str | None = None
    validity_date: str | None = None
    denial_reason: str | None = None


class PortalExecutionResult(BaseModel):
    final_status: Literal["AUTHORIZED", "IN_ANALYSIS", "DENIED", "AWAITING_HUMAN_2FA", "CREDENTIAL_LOCKED", "FAILED"]
    guide_number: str | None = None
    auth_password: str | None = None
    validity_date: str | None = None
    protocol_number: str | None = None
    denial_reason: str | None = None
    pdf_local_path: str | None = None
    screenshot_path: str | None = None
    video_path: str | None = None
    steps_executed: list[dict[str, Any]] = Field(default_factory=list)
    ai_provider_used: str = "heuristic"


class GuideJob(BaseModel):
    id: str
    tenant_slug: str
    igut_appointment_id: str
    batch_index: int = 0
    status: GuideJobStatus = GuideJobStatus.DISCOVERED
    patient_name: str
    patient_cpf: str = ""
    patient_phone: str = ""
    insurance_name: str = ""
    card_number: str = ""
    doctor_name: str = ""
    doctor_crm: str = ""
    doctor_cbo: str = ""
    specialty: str = ""
    appointment_type: str = "Consulta"
    appointment_date: str = ""
    appointment_time: str = ""
    portal_key: str = ""
    procedure_codes: list[str] = Field(default_factory=list)
    guide_number: str | None = None
    auth_password: str | None = None
    validity_date: str | None = None
    drive_patient_folder_id: str | None = None
    drive_pdf_file_id: str | None = None
    denial_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


class CrmWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    event: str = "document.synced_to_drive"
    tenant_slug: str = "nova-gesta"
    timestamp: str | None = None
    test: bool = False
    patient: dict[str, Any] = Field(default_factory=dict)
    drive: dict[str, Any] = Field(default_factory=dict)
    drive: dict[str, Any] = Field(default_factory=dict)
    crm: dict[str, Any] = Field(default_factory=dict)
