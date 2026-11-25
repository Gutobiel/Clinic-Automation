from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parents[2]


class TenantPack(BaseModel):
    tenant_slug: str
    config: dict[str, Any] = Field(default_factory=dict)
    portals: dict[str, Any] = Field(default_factory=dict)
    procedures_map: dict[str, Any] = Field(default_factory=dict)
    doctors: list[dict[str, Any]] = Field(default_factory=list)


class AppSettings(BaseModel):
    tenant_slug: str = "nova-gesta"
    automation_mode: Literal["SHADOW", "ASSISTED", "AUTONOMOUS"] = "ASSISTED"
    db_path: str = str(BASE_DIR / "data" / "clinic_automation.db")
    storage_state_dir: str = str(BASE_DIR / "storage_state")
    downloads_dir: str = str(BASE_DIR / "downloads")
    screenshots_dir: str = str(BASE_DIR / "screenshots")

    # Browser & AI
    playwright_headless: bool = True
    browser_slow_mo_ms: int = 0
    ai_provider: Literal["auto", "openai", "gemini", "heuristic"] = "auto"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # CRM Bridge
    crm_webhook_api_key: str = "dev-local-api-key"
    crm_callback_url: str = ""

    # iGUT
    igut_client_name: str = "novagesta"
    igut_api_user: str = ""
    igut_api_pass: str = ""
    igut_web_url: str = "https://novagesta.igutclinicas.com.br"
    igut_web_user: str = ""
    igut_web_pass: str = ""

    # Google Drive
    google_drive_auth_mode: Literal["service_account", "oauth2"] = "service_account"
    google_drive_root_folder_id: str = ""
    google_drive_service_account_path: str = ""
    google_drive_service_account_json: str = ""
    google_drive_oauth_client_id: str = ""
    google_drive_oauth_client_secret: str = ""
    google_drive_oauth_refresh_token: str = ""

    # Notificações (Hermes Gateway / Webhook)
    notifier_webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_group_chat_id: str = ""

    @classmethod
    def load(cls, tenant_slug: str | None = None) -> "AppSettings":
        resolved_slug = tenant_slug or os.getenv("TENANT_SLUG", "nova-gesta")
        tenant_env = BASE_DIR / "tenants" / resolved_slug / ".env"
        root_env = BASE_DIR / ".env"
        if root_env.exists():
            load_dotenv(root_env, override=False)
        if tenant_env.exists():
            load_dotenv(tenant_env, override=True)

        def _bool(key: str, default: bool) -> bool:
            val = os.getenv(key)
            if val is None:
                return default
            return val.strip().lower() in ("1", "true", "yes", "sim", "on")

        return cls(
            tenant_slug=os.getenv("TENANT_SLUG", resolved_slug),
            automation_mode=os.getenv("AUTOMATION_MODE", "ASSISTED").upper(),  # type: ignore[arg-type]
            db_path=os.getenv("DB_PATH", str(BASE_DIR / "data" / "clinic_automation.db")),
            storage_state_dir=os.getenv("STORAGE_STATE_DIR", str(BASE_DIR / "storage_state")),
            downloads_dir=os.getenv("DOWNLOADS_DIR", str(BASE_DIR / "downloads")),
            screenshots_dir=os.getenv("SCREENSHOTS_DIR", str(BASE_DIR / "screenshots")),
            playwright_headless=_bool("PLAYWRIGHT_HEADLESS", True),
            browser_slow_mo_ms=int(os.getenv("BROWSER_SLOW_MO_MS", "0")),
            ai_provider=os.getenv("AI_PROVIDER", "auto").lower(),  # type: ignore[arg-type]
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            crm_webhook_api_key=os.getenv("CRM_WEBHOOK_API_KEY", "dev-local-api-key"),
            crm_callback_url=os.getenv("CRM_CALLBACK_URL", ""),
            igut_client_name=os.getenv("IGUT_CLIENT_NAME", "novagesta"),
            igut_api_user=os.getenv("IGUT_API_USER", ""),
            igut_api_pass=os.getenv("IGUT_API_PASS", ""),
            igut_web_url=os.getenv("IGUT_WEB_URL", "https://novagesta.igutclinicas.com.br"),
            igut_web_user=os.getenv("IGUT_WEB_USER", ""),
            igut_web_pass=os.getenv("IGUT_WEB_PASS", ""),
            google_drive_auth_mode=os.getenv("GOOGLE_DRIVE_AUTH_MODE", "service_account").lower(),  # type: ignore[arg-type]
            google_drive_root_folder_id=os.getenv("GOOGLE_DRIVE_ROOT_FOLDER_ID", ""),
            google_drive_service_account_path=os.getenv("GOOGLE_DRIVE_SERVICE_ACCOUNT_PATH", ""),
            google_drive_service_account_json=os.getenv("GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON", ""),
            google_drive_oauth_client_id=os.getenv("GOOGLE_DRIVE_OAUTH_CLIENT_ID", ""),
            google_drive_oauth_client_secret=os.getenv("GOOGLE_DRIVE_OAUTH_CLIENT_SECRET", ""),
            google_drive_oauth_refresh_token=os.getenv("GOOGLE_DRIVE_OAUTH_REFRESH_TOKEN", ""),
            notifier_webhook_url=os.getenv("NOTIFIER_WEBHOOK_URL", ""),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            telegram_group_chat_id=os.getenv("TELEGRAM_GROUP_CHAT_ID", ""),
        )


def load_tenant_pack(tenant_slug: str) -> TenantPack:
    tenant_dir = BASE_DIR / "tenants" / tenant_slug
    if not tenant_dir.exists():
        raise FileNotFoundError(f"Tenant Pack não encontrado em {tenant_dir}")

    def _read_json(name: str, default: Any) -> Any:
        p = tenant_dir / name
        if not p.exists():
            return default
        return json.loads(p.read_text(encoding="utf-8"))

    portals_raw = _read_json("portals.json", {"portals": {}})
    return TenantPack(
        tenant_slug=tenant_slug,
        config=_read_json("config.json", {}),
        portals=portals_raw.get("portals", portals_raw),
        procedures_map=_read_json("procedures_map.json", {}),
        doctors=_read_json("doctors.json", []),
    )
