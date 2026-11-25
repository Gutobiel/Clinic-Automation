from __future__ import annotations

import base64
import json
import logging
import re
import time
import unicodedata
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from core.config.settings import AppSettings

logger = logging.getLogger(__name__)

DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _only_digits(text: str | None) -> str:
    return re.sub(r"\D+", "", text or "")


def _norm(text: str | None) -> str:
    if not text:
        return ""
    nfd = unicodedata.normalize("NFD", str(text))
    stripped = "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn")
    return " ".join(stripped.upper().strip().split())


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class GoogleDriveConnector:
    """Conector assíncrono Google Drive API v3 (Service Account RS256 ou OAuth 2.0 + Shared Drives)."""

    def __init__(self, settings: AppSettings, dossier_filename: str = "ficha_paciente.json") -> None:
        self.settings = settings
        self.dossier_filename = dossier_filename
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    def is_configured(self) -> bool:
        if not self.settings.google_drive_root_folder_id:
            return False
        if self.settings.google_drive_auth_mode == "service_account":
            return bool(self.settings.google_drive_service_account_json or self.settings.google_drive_service_account_path)
        return bool(
            self.settings.google_drive_oauth_client_id
            and self.settings.google_drive_oauth_client_secret
            and self.settings.google_drive_oauth_refresh_token
        )

    def _load_service_account_dict(self) -> dict[str, Any]:
        if self.settings.google_drive_service_account_json:
            return json.loads(self.settings.google_drive_service_account_json)
        if self.settings.google_drive_service_account_path:
            raw = Path(self.settings.google_drive_service_account_path).read_text(encoding="utf-8")
            return json.loads(raw)
        raise RuntimeError("Credenciais de Service Account do Google Drive não configuradas.")

    def _build_service_account_jwt(self, sa: dict[str, Any]) -> str:
        now = int(time.time())
        header = {"alg": "RS256", "typ": "JWT"}
        payload = {
            "iss": sa["client_email"],
            "scope": DRIVE_SCOPE,
            "aud": sa.get("token_uri", GOOGLE_TOKEN_URL),
            "iat": now,
            "exp": now + 3600,
        }
        signing_input = f"{_b64url(json.dumps(header, separators=(',', ':')).encode())}.{_b64url(json.dumps(payload, separators=(',', ':')).encode())}"
        private_key = serialization.load_pem_private_key(sa["private_key"].encode("utf-8"), password=None)
        signature = private_key.sign(  # type: ignore[union-attr]
            signing_input.encode("ascii"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return f"{signing_input}.{_b64url(signature)}"

    async def get_access_token(self) -> str:
        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token

        async with httpx.AsyncClient(timeout=20.0) as client:
            if self.settings.google_drive_auth_mode == "service_account":
                sa = self._load_service_account_dict()
                assertion = self._build_service_account_jwt(sa)
                resp = await client.post(
                    sa.get("token_uri", GOOGLE_TOKEN_URL),
                    data={
                        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                        "assertion": assertion,
                    },
                )
            else:
                resp = await client.post(
                    GOOGLE_TOKEN_URL,
                    data={
                        "client_id": self.settings.google_drive_oauth_client_id,
                        "client_secret": self.settings.google_drive_oauth_client_secret,
                        "refresh_token": self.settings.google_drive_oauth_refresh_token,
                        "grant_type": "refresh_token",
                    },
                )
            resp.raise_for_status()
            data = resp.json()
            self._access_token = data["access_token"]
            self._token_expires_at = time.time() + int(data.get("expires_in", 3600))
            return self._access_token

    async def _auth_headers(self) -> dict[str, str]:
        token = await self.get_access_token()
        return {"Authorization": f"Bearer {token}"}

    async def _list_files(self, query: str, fields: str = "files(id,name,mimeType,modifiedTime,webViewLink)") -> list[dict[str, Any]]:
        headers = await self._auth_headers()
        params = {
            "q": query,
            "fields": fields,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
            "pageSize": "50",
        }
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.get(f"{DRIVE_API_BASE}/files", headers=headers, params=params)
            resp.raise_for_status()
            return resp.json().get("files", [])

    async def find_patient_folder(
        self,
        *,
        cpf: str = "",
        phone: str = "",
        name: str = "",
        root_folder_id: str | None = None,
    ) -> dict[str, Any] | None:
        parent_id = root_folder_id or self.settings.google_drive_root_folder_id
        if not parent_id:
            return None

        folders = await self._list_files(
            f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        )
        cpf_digits = _only_digits(cpf)
        phone_digits = _only_digits(phone)
        name_norm = _norm(name)

        if cpf_digits:
            for f in folders:
                if cpf_digits in _only_digits(f.get("name", "")):
                    return f
        if phone_digits and len(phone_digits) >= 8:
            tail = phone_digits[-8:]
            for f in folders:
                if tail in _only_digits(f.get("name", "")):
                    return f
        if name_norm:
            for f in folders:
                if name_norm in _norm(f.get("name", "")):
                    return f
        return None

    async def ensure_subfolder(self, parent_folder_id: str, subfolder_name: str) -> str:
        safe_name = subfolder_name.replace("'", "\\'")
        found = await self._list_files(
            f"'{parent_folder_id}' in parents and name = '{safe_name}' "
            "and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        )
        if found:
            return found[0]["id"]

        headers = await self._auth_headers()
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(
                f"{DRIVE_API_BASE}/files",
                headers={**headers, "Content-Type": "application/json"},
                params={"supportsAllDrives": "true", "fields": "id,name"},
                json={
                    "name": subfolder_name,
                    "mimeType": "application/vnd.google-apps.folder",
                    "parents": [parent_folder_id],
                },
            )
            resp.raise_for_status()
            return resp.json()["id"]

    async def list_subfolder_files(self, patient_folder_id: str, subfolder_name: str) -> list[dict[str, Any]]:
        safe_name = subfolder_name.replace("'", "\\'")
        subfolders = await self._list_files(
            f"'{patient_folder_id}' in parents and name = '{safe_name}' "
            "and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        )
        if not subfolders:
            return []
        sub_id = subfolders[0]["id"]
        return await self._list_files(f"'{sub_id}' in parents and trashed = false")

    async def read_patient_dossier(self, patient_folder_id: str) -> dict[str, Any]:
        safe_name = self.dossier_filename.replace("'", "\\'")
        files = await self._list_files(
            f"'{patient_folder_id}' in parents and name = '{safe_name}' and trashed = false"
        )
        if not files:
            return {}
        file_id = files[0]["id"]
        headers = await self._auth_headers()
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.get(
                f"{DRIVE_API_BASE}/files/{file_id}",
                headers=headers,
                params={"alt": "media", "supportsAllDrives": "true"},
            )
            resp.raise_for_status()
            try:
                return resp.json()
            except ValueError:
                logger.warning("ficha_paciente.json inválido na pasta %s", patient_folder_id)
                return {}

    async def update_patient_dossier(
        self,
        patient_folder_id: str,
        patch: dict[str, Any],
        append_guide: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current = await self.read_patient_dossier(patient_folder_id)
        updated = _deep_merge(current, patch)
        if append_guide:
            guides = list(updated.get("guias_emitidas") or [])
            guides.append(append_guide)
            updated["guias_emitidas"] = guides

        content_bytes = json.dumps(updated, ensure_ascii=False, indent=2).encode("utf-8")
        safe_name = self.dossier_filename.replace("'", "\\'")
        existing = await self._list_files(
            f"'{patient_folder_id}' in parents and name = '{safe_name}' and trashed = false"
        )
        headers = await self._auth_headers()

        async with httpx.AsyncClient(timeout=30.0) as client:
            if existing:
                file_id = existing[0]["id"]
                resp = await client.patch(
                    f"{DRIVE_UPLOAD_BASE}/files/{file_id}",
                    headers={**headers, "Content-Type": "application/json; charset=UTF-8"},
                    params={"uploadType": "media", "supportsAllDrives": "true"},
                    content=content_bytes,
                )
                resp.raise_for_status()
            else:
                await self._multipart_upload(
                    client=client,
                    headers=headers,
                    metadata={"name": self.dossier_filename, "parents": [patient_folder_id]},
                    mime_type="application/json",
                    data=content_bytes,
                )
        return updated

    async def download_file(self, file_id: str, dest_path: Path) -> Path:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        headers = await self._auth_headers()
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(
                f"{DRIVE_API_BASE}/files/{file_id}",
                headers=headers,
                params={"alt": "media", "supportsAllDrives": "true"},
            )
            resp.raise_for_status()
            dest_path.write_bytes(resp.content)
        return dest_path

    async def upload_guide_pdf(
        self,
        patient_folder_id: str,
        pdf_path: Path,
        filename: str,
        subfolder_name: str = "06_Guias_Autorizadas",
    ) -> dict[str, Any]:
        sub_id = await self.ensure_subfolder(patient_folder_id, subfolder_name)
        headers = await self._auth_headers()
        data = pdf_path.read_bytes()
        async with httpx.AsyncClient(timeout=60.0) as client:
            return await self._multipart_upload(
                client=client,
                headers=headers,
                metadata={"name": filename, "parents": [sub_id]},
                mime_type="application/pdf",
                data=data,
            )

    async def _multipart_upload(
        self,
        *,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        metadata: dict[str, Any],
        mime_type: str,
        data: bytes,
    ) -> dict[str, Any]:
        boundary = "aegis_clinic_automation_boundary"
        body = (
            f"--{boundary}\r\n"
            "Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{json.dumps(metadata, ensure_ascii=False)}\r\n"
            f"--{boundary}\r\n"
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode("utf-8") + data + f"\r\n--{boundary}--\r\n".encode("utf-8")

        resp = await client.post(
            f"{DRIVE_UPLOAD_BASE}/files",
            headers={**headers, "Content-Type": f"multipart/related; boundary={boundary}"},
            params={"uploadType": "multipart", "supportsAllDrives": "true", "fields": "id,name,webViewLink"},
            content=body,
        )
        resp.raise_for_status()
        return resp.json()
