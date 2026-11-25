from __future__ import annotations

import html
import random
import time
from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

router = APIRouter(prefix="/mock-portal", tags=["mock-portal"])

# Estado em memória das solicitações de guias simuladas
MOCK_GUIDES: dict[str, dict[str, Any]] = {}


def _build_minimal_pdf(lines: list[str]) -> bytes:
    """Gera um arquivo PDF 1.4 válido sem dependências externas."""
    def _esc(s: str) -> str:
        safe = s.encode("latin-1", "replace").decode("latin-1")
        return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    text_ops = ["BT", "/F1 13 Tf", "50 760 Td", "18 TL"]
    for idx, line in enumerate(lines):
        if idx == 0:
            text_ops.append(f"({_esc(line)}) Tj")
        else:
            text_ops.append(f"T* ({_esc(line)}) Tj")
    text_ops.append("ET")
    stream_bytes = "\n".join(text_ops).encode("latin-1")

    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n",
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
        f"5 0 obj << /Length {len(stream_bytes)} >> stream\n".encode("ascii") + stream_bytes + b"\nendstream endobj\n",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(pdf))
        pdf.extend(obj)
    xref_pos = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        pdf.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )
    return bytes(pdf)


BASE_STYLE = """
<style>
  * { box-sizing: border-box; font-family: 'Segoe UI', Inter, system-ui, sans-serif; }
  body { margin: 0; background: #f1f5f9; color: #0f172a; }
  .topbar {
    background: linear-gradient(90deg, #0b3a66, #0e5a8a);
    color: #fff; padding: 14px 28px; display: flex; justify-content: space-between; align-items: center;
    box-shadow: 0 2px 10px rgba(11,58,102,0.22);
  }
  .brand { font-size: 18px; font-weight: 700; letter-spacing: 0.3px; }
  .badge-env { font-size: 12px; background: rgba(255,255,255,0.18); padding: 4px 10px; border-radius: 999px; }
  .container { max-width: 900px; margin: 28px auto; padding: 0 18px; }
  .card {
    background: #fff; border-radius: 14px; padding: 26px 28px;
    box-shadow: 0 10px 28px rgba(15, 23, 42, 0.08); border: 1px solid #e2e8f0;
  }
  h1, h2 { margin-top: 0; color: #0b3a66; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .full { grid-column: 1 / -1; }
  label { display: block; font-size: 13px; font-weight: 600; color: #334155; margin-bottom: 6px; }
  input, select, textarea {
    width: 100%; padding: 10px 12px; border: 1px solid #cbd5e1; border-radius: 8px;
    font-size: 14px; background: #fff; color: #0f172a;
  }
  input:focus, select:focus, textarea:focus { outline: 2px solid #0284c7; border-color: #0284c7; }
  .btn {
    display: inline-block; padding: 11px 20px; border-radius: 8px; font-size: 14px; font-weight: 700;
    text-decoration: none; border: none; cursor: pointer; transition: transform 0.08s ease;
  }
  .btn-primary { background: #0284c7; color: #fff; }
  .btn-primary:hover { background: #0369a1; }
  .btn-success { background: #16a34a; color: #fff; }
  .btn-secondary { background: #e2e8f0; color: #1e293b; }
  .status-box {
    border-radius: 12px; padding: 18px 20px; margin: 18px 0; font-size: 15px;
    border-left: 5px solid #cbd5e1;
  }
  .status-analysis { background: #fef9c3; border-left-color: #eab308; color: #713f12; }
  .status-authorized { background: #dcfce7; border-left-color: #16a34a; color: #14532d; }
  .status-denied { background: #fee2e2; border-left-color: #dc2626; color: #7f1d1d; }
  .kv { display: grid; grid-template-columns: 200px 1fr; gap: 8px 14px; margin-top: 14px; font-size: 14px; }
  .kv div:nth-child(odd) { font-weight: 600; color: #475569; }
</style>
"""


def _layout(title: str, body: str) -> HTMLResponse:
    page = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <title>{html.escape(title)} — Portal TISS Convênio (Simulador)</title>
  {BASE_STYLE}
</head>
<body>
  <div class="topbar">
    <div class="brand">🏥 Portal Autorizador TISS — GDF Saúde / Benner (Sandbox)</div>
    <div class="badge-env">Ambiente de Homologação Local</div>
  </div>
  <div class="container">{body}</div>
</body>
</html>"""
    return HTMLResponse(page)


@router.get("", response_class=HTMLResponse)
@router.get("/login", response_class=HTMLResponse)
async def mock_login_page(delay: float = 4.0, outcome: str = "authorized", captcha: int = 0) -> HTMLResponse:
    captcha_block = (
        '<div class="status-box status-denied"><strong>reCAPTCHA:</strong> Digite os caracteres da imagem abaixo para continuar.</div>'
        if captcha
        else ""
    )
    body = f"""
    <div class="card" style="max-width:480px;margin:30px auto;">
      <h2>Acesso do Prestador Credenciado</h2>
      <p style="color:#64748b;font-size:14px;">Informe suas credenciais de prestador (Nova Gesta / AMHP-DF) para solicitar autorizações de guias TISS.</p>
      {captcha_block}
      <form method="post" action="/mock-portal/login">
        <input type="hidden" name="delay" value="{delay}" />
        <input type="hidden" name="outcome" value="{html.escape(outcome)}" />
        <div style="margin-bottom:14px;">
          <label for="username">Usuário / Código Prestador</label>
          <input id="username" name="username" type="text" placeholder="Ex: prestador.novagesta" required />
        </div>
        <div style="margin-bottom:18px;">
          <label for="password">Senha de Acesso</label>
          <input id="password" name="password" type="password" placeholder="••••••••" required />
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <button type="submit" class="btn btn-primary">Entrar no Portal</button>
          <a href="#esqueci-senha" style="font-size:12px;color:#64748b;">Esqueci minha senha</a>
        </div>
      </form>
    </div>
    """
    return _layout("Login do Prestador", body)


@router.post("/login")
async def mock_login_submit(
    username: str = Form(...),
    password: str = Form(...),
    delay: float = Form(4.0),
    outcome: str = Form("authorized"),
) -> RedirectResponse:
    _ = (username, password)
    return RedirectResponse(
        url=f"/mock-portal/dashboard?delay={delay}&outcome={outcome}",
        status_code=303,
    )


@router.get("/dashboard", response_class=HTMLResponse)
async def mock_dashboard(delay: float = 4.0, outcome: str = "authorized") -> HTMLResponse:
    body = f"""
    <div class="card">
      <h1>Central de Autorizações TISS</h1>
      <p style="color:#475569;">Prestador conectado: <strong>NOVA GESTA GINECOLOGIA E OBSTETRICIA LTDA (Código 02326)</strong></p>
      <div style="display:flex;gap:14px;margin-top:22px;flex-wrap:wrap;">
        <a href="/mock-portal/nova-guia?delay={delay}&outcome={outcome}" class="btn btn-primary">
          ➕ Nova Solicitação SP/SADT ou Consulta
        </a>
      </div>
    </div>
    """
    return _layout("Painel do Prestador", body)


@router.get("/nova-guia", response_class=HTMLResponse)
async def mock_new_guide_form(delay: float = 4.0, outcome: str = "authorized") -> HTMLResponse:
    body = f"""
    <div class="card">
      <h2>Nova Solicitação de Guia (TISS SP/SADT &amp; Consulta)</h2>
      <p style="color:#64748b;font-size:14px;">Preencha os dados do beneficiário, profissional solicitante, código TUSS e anexe o pedido médico quando aplicável.</p>
      <form method="post" action="/mock-portal/nova-guia" enctype="multipart/form-data">
        <input type="hidden" name="delay" value="{delay}" />
        <input type="hidden" name="outcome" value="{html.escape(outcome)}" />
        <div class="grid">
          <div>
            <label for="card_number">Número da Carteirinha do Beneficiário</label>
            <input id="card_number" name="card_number" type="text" placeholder="0045..." required />
          </div>
          <div>
            <label for="guide_type">Tipo de Guia</label>
            <select id="guide_type" name="guide_type" required>
              <option value="">Selecione...</option>
              <option value="SP/SADT">SP/SADT</option>
              <option value="Consulta">Consulta</option>
            </select>
          </div>
          <div>
            <label for="patient_name">Nome do Paciente</label>
            <input id="patient_name" name="patient_name" type="text" required />
          </div>
          <div>
            <label for="patient_cpf">CPF do Paciente</label>
            <input id="patient_cpf" name="patient_cpf" type="text" />
          </div>
          <div>
            <label for="doctor_name">Médico Solicitante</label>
            <input id="doctor_name" name="doctor_name" type="text" required />
          </div>
          <div>
            <label for="doctor_crm">CRM do Médico</label>
            <input id="doctor_crm" name="doctor_crm" type="text" />
          </div>
          <div>
            <label for="doctor_cbo">CBO Especialidade</label>
            <input id="doctor_cbo" name="doctor_cbo" type="text" />
          </div>
          <div>
            <label for="tuss_code">Código TUSS / Procedimento</label>
            <input id="tuss_code" name="tuss_code" type="text" required />
          </div>
          <div class="full">
            <label for="clinical_indication">Indicação Clínica / Observação</label>
            <textarea id="clinical_indication" name="clinical_indication" rows="2"></textarea>
          </div>
          <div class="full">
            <label for="medical_order">Anexar Pedido Médico (PDF/JPG/PNG)</label>
            <input id="medical_order" name="medical_order" type="file" />
          </div>
        </div>
        <div style="margin-top:22px;display:flex;gap:12px;">
          <button type="submit" class="btn btn-primary">Solicitar Guia ao Convênio</button>
        </div>
      </form>
    </div>
    """
    return _layout("Nova Solicitação de Guia", body)


@router.post("/nova-guia")
async def mock_submit_guide(
    card_number: str = Form(...),
    guide_type: str = Form("SP/SADT"),
    patient_name: str = Form(...),
    patient_cpf: str = Form(""),
    doctor_name: str = Form(""),
    doctor_crm: str = Form(""),
    doctor_cbo: str = Form(""),
    tuss_code: str = Form("10101012"),
    clinical_indication: str = Form(""),
    delay: float = Form(4.0),
    outcome: str = Form("authorized"),
    medical_order: UploadFile | None = File(default=None),
) -> RedirectResponse:
    guide_id = f"2026{random.randint(100000, 999999)}"
    auth_pwd = f"SEN{random.randint(100000, 999999)}"
    MOCK_GUIDES[guide_id] = {
        "guide_id": guide_id,
        "auth_password": auth_pwd,
        "validity_date": "23/12/2026",
        "card_number": card_number,
        "guide_type": guide_type,
        "patient_name": patient_name,
        "patient_cpf": patient_cpf,
        "doctor_name": doctor_name,
        "doctor_crm": doctor_crm,
        "doctor_cbo": doctor_cbo,
        "tuss_code": tuss_code,
        "clinical_indication": clinical_indication,
        "attachment_name": medical_order.filename if medical_order and medical_order.filename else "Nenhum anexo",
        "created_at": time.monotonic(),
        "delay": float(delay),
        "outcome": outcome,
        "checks": 0,
    }
    return RedirectResponse(url=f"/mock-portal/guia/{guide_id}", status_code=303)


@router.get("/guia/{guide_id}", response_class=HTMLResponse)
async def mock_guide_status(guide_id: str, request: Request) -> HTMLResponse:
    _ = request
    g = MOCK_GUIDES.get(guide_id)
    if not g:
        return _layout("Guia não encontrada", "<div class='card'><h2>Guia não encontrada</h2></div>")

    g["checks"] += 1
    elapsed = time.monotonic() - g["created_at"]
    ready = elapsed >= g["delay"]

    if not ready:
        remaining = max(0.0, g["delay"] - elapsed)
        status_html = f"""
        <div class="status-box status-analysis">
          <strong>🟡 STATUS: EM ANÁLISE (Auditoria da Operadora)</strong><br/>
          Sua solicitação foi protocolada e está em fila de auditoria técnica.
          <div style="font-size:12px;margin-top:6px;">
            Consultas realizadas: {g['checks']} | Tempo decorrido: {elapsed:.1f}s (previsão restante ~{remaining:.1f}s)
          </div>
        </div>
        <div style="margin-top:16px;">
          <a href="/mock-portal/guia/{guide_id}" class="btn btn-primary">🔄 Atualizar Status da Guia</a>
        </div>
        """
    elif g["outcome"] == "denied":
        status_html = """
        <div class="status-box status-denied">
          <strong>❌ STATUS: GUIA NEGADA</strong><br/>
          Motivo da Negativa: Procedimento fora da cobertura contratual ou aguardando carência.
        </div>
        """
    else:
        status_html = f"""
        <div class="status-box status-authorized">
          <strong>✅ STATUS: GUIA AUTORIZADA COM SUCESSO</strong><br/>
          A operadora aprovou o procedimento solicitado. Faça o download da guia autorizada para anexar ao prontuário.
          <div class="kv">
            <div>Nº da Guia:</div><div><strong>{g['guide_id']}</strong></div>
            <div>Senha de Autorização:</div><div><strong>{g['auth_password']}</strong></div>
            <div>Validade da Senha:</div><div><strong>{g['validity_date']}</strong></div>
          </div>
        </div>
        <div style="margin-top:18px;display:flex;gap:12px;">
          <a href="/mock-portal/guia/{guide_id}/pdf" class="btn btn-success">📄 Baixar Guia PDF</a>
        </div>
        """

    body = f"""
    <div class="card">
      <h2>Acompanhamento de Solicitação — Protocolo #{g['guide_id']}</h2>
      {status_html}
      <hr style="border:none;border-top:1px solid #e2e8f0;margin:22px 0;" />
      <div class="kv">
        <div>Beneficiário:</div><div>{html.escape(g['patient_name'])}</div>
        <div>Carteirinha:</div><div>{html.escape(g['card_number'])}</div>
        <div>Tipo de Guia:</div><div>{html.escape(g['guide_type'])}</div>
        <div>Médico Solicitante:</div><div>{html.escape(g['doctor_name'])} (CRM {html.escape(g['doctor_crm'])})</div>
        <div>Código TUSS:</div><div>{html.escape(g['tuss_code'])}</div>
        <div>Pedido Médico Anexado:</div><div>{html.escape(g['attachment_name'])}</div>
      </div>
    </div>
    """
    return _layout(f"Guia #{guide_id}", body)


@router.get("/guia/{guide_id}/pdf")
async def mock_guide_pdf(guide_id: str) -> Response:
    g = MOCK_GUIDES.get(guide_id)
    if not g:
        return Response(status_code=404, content=b"Guide not found")

    pdf_bytes = _build_minimal_pdf(
        [
            "GUIA DE AUTORIZACAO TISS - COMPROVANTE OFICIAL (SANDBOX)",
            "========================================================",
            f"Numero da Guia: {g['guide_id']}",
            f"Senha de Autorizacao: {g['auth_password']}",
            f"Validade da Senha: {g['validity_date']}",
            f"Tipo de Guia: {g['guide_type']}",
            f"Paciente: {g['patient_name']}",
            f"Carteirinha: {g['card_number']}",
            f"Medico Solicitante: {g['doctor_name']} (CRM {g['doctor_crm']})",
            f"Procedimento TUSS: {g['tuss_code']}",
            f"Status: AUTORIZADA",
        ]
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="guia_{guide_id}_autorizada.pdf"'},
    )
