from __future__ import annotations

import base64
import logging
import re
from typing import Any

import httpx

from core.config.settings import AppSettings

logger = logging.getLogger(__name__)

IGUT_BASE_URL = "https://api.igut.med.br"


def encode_igut_client_token(client_name: str) -> str:
    raw = (client_name or "").strip()
    try:
        decoded = base64.b64decode(raw).decode("utf-8")
        if len(decoded) >= 3 and re.match(r"^[a-z0-9_-]+$", decoded, re.I):
            if base64.b64encode(decoded.encode("utf-8")).decode("ascii") == raw:
                return raw
    except Exception:
        pass
    normalized = re.sub(r"\s+", "", raw.lower())
    return base64.b64encode(normalized.encode("utf-8")).decode("ascii")


class IgutApiConnector:
    """Conector assíncrono oficial para a API REST v2 do iGUT."""

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.base_url = IGUT_BASE_URL
        self._access_token: str | None = None

    def is_configured(self) -> bool:
        return bool(
            self.settings.igut_client_name
            and self.settings.igut_api_user
            and self.settings.igut_api_pass
        )

    @property
    def client_token(self) -> str:
        return encode_igut_client_token(self.settings.igut_client_name)

    async def login(self) -> str:
        if not self.is_configured():
            raise RuntimeError("Credenciais da API iGUT não configuradas.")

        headers = {
            "client_token": self.client_token,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        payload = {
            "username": self.settings.igut_api_user,
            "password": self.settings.igut_api_pass,
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(f"{self.base_url}/v2/usuarios/login", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "failed":
                raise RuntimeError(f"Falha no login iGUT: {data.get('message')}")
            token = (
                (data.get("data") or {}).get("token")
                or data.get("token")
                or (data.get("data") or {}).get("access_token")
                or data.get("access_token")
            )
            if not token:
                raise RuntimeError("Resposta de login iGUT não retornou token.")
            self._access_token = str(token).strip()
            return self._access_token

    async def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        token = self._access_token or await self.login()
        headers = {
            "client_token": self.client_token,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.request(method, f"{self.base_url}{path}", headers=headers, json=body)
            if resp.status_code == 401:
                token = await self.login()
                headers["Authorization"] = f"Bearer {token}"
                resp = await client.request(method, f"{self.base_url}{path}", headers=headers, json=body)
            if resp.status_code == 404:
                return {"status": "not_found", "data": []}
            resp.raise_for_status()
            return resp.json()

    async def list_scheduled_appointments(
        self,
        date_start: str,
        date_end: str | None = None,
        *,
        include_test_doctors: bool = False,
        include_cancelled: bool = False,
    ) -> list[dict[str, Any]]:
        """Busca consultas agendadas (status=3) no período AAAA-MM-DD."""
        payload = {
            "Agendamento.data": date_start.strip(),
            "Agendamento.data_fim": (date_end or date_start).strip(),
            "Agendamento.status": 3,
        }
        response = await self._request("POST", "/v2/consultas/buscar", payload)
        raw_list = response.get("data", []) if isinstance(response, dict) else (response if isinstance(response, list) else [])

        appointments: list[dict[str, Any]] = []
        for item in raw_list:
            ag = item.get("Agendamento") or item
            pac = item.get("Paciente") or {}
            prof = item.get("Profissional") or item.get("Medico") or {}
            conv = item.get("Convenio") or {}
            loc = item.get("Local") or item.get("Unidade") or {}
            tipo_at = item.get("TipoAtendimento") or {}

            if not ag.get("id") or not ag.get("data"):
                continue

            confirmed_str = str(ag.get("confirmado") or "").strip()
            status_str = str(ag.get("status") or "").strip()
            if not include_cancelled and (
                re.search(r"desmarcad|cancelad|faltou", confirmed_str, re.I)
                or re.search(r"desmarcad|cancelad", status_str, re.I)
            ):
                continue

            prof_id = str(prof.get("id") or ag.get("medico_id") or "").strip()
            prof_name = str(prof.get("nome") or "").strip()
            if not include_test_doctors and (prof_id == "36564" or re.search(r"ficticio|teste", prof_name, re.I)):
                continue

            appointments.append(
                {
                    "appointment_id": str(ag["id"]),
                    "date": str(ag["data"]).strip(),
                    "time": str(ag.get("horario") or ag.get("hora_inicio") or "").strip()[:5],
                    "appointment_type": str(ag.get("tipodeatendimento") or ag.get("procedimento") or tipo_at.get("nome") or "Consulta").strip(),
                    "confirmed_status": confirmed_str or "Nao Confirmado",
                    "status": status_str or "Agendado",
                    "patient": {
                        "id": str(pac.get("id") or ""),
                        "name": str(pac.get("nome") or pac.get("nomesocial") or "").strip(),
                        "cpf": str(pac.get("cpf") or "").strip(),
                        "phone": str(pac.get("celular") or "").strip(),
                        "birth_date": str(pac.get("datadenascimento") or "").strip(),
                    },
                    "professional": {
                        "id": prof_id,
                        "name": prof_name,
                        "specialty": str(prof.get("especialidade") or "").strip(),
                    },
                    "insurance": {
                        "id": str(conv.get("id") or ""),
                        "name": str(conv.get("nome") or "").strip(),
                    },
                    "unit": {
                        "id": str(loc.get("id") or "1"),
                        "name": str(loc.get("nome") or "Asa Norte").strip(),
                    },
                }
            )
        return appointments
