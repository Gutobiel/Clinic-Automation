---
name: faturamento-guias
description: Orquestra a varredura da agenda iGUT, auditoria Anti-Glosa no Google Drive, solicitação de guias nos portais de convênio via Agente IA de Navegador e monitoramento contínuo até aprovação.
---

# Skill: Faturamento e Autorização de Guias (`faturamento-guias`)

## Quando usar
- Nas rotinas agendadas (07h, 13h, 18h) para preparar guias de D+0 a D+2.
- A cada 30 minutos para acompanhar guias em `IN_ANALYSIS`.
- Quando um humano pedir no Telegram/WhatsApp: *"emitir guia da paciente X"*, *"como estão as guias de amanhã?"* ou *"reconsultar guias em análise"*.

## Endpoints locais da API (`http://127.0.0.1:8000`)

1. **Saúde do serviço**:
   `GET /health`
2. **Varrer agenda iGUT (D+0 a D+2)**:
   `POST /api/v1/jobs/scan-igut`
   ```json
   { "date_start": "2026-11-24", "date_end": "2026-11-26" }
   ```
3. **Executar um job específico (Drive -> Anti-Glosa -> Agente IA -> Monitoramento)**:
   `POST /api/v1/jobs/{job_id}/run`
4. **Reconsultar guias `IN_ANALYSIS`**:
   `POST /api/v1/jobs/recheck-analysis`
5. **Resumo operacional**:
   `GET /api/v1/summary?appointment_date=2026-11-24`

## Fluxo de Decisão
1. Sempre verifique `GET /api/v1/jobs?status=DISCOVERED` e `READY_FOR_PORTAL`.
2. Para cada job descoberto, acione `POST /api/v1/jobs/{job_id}/run`.
3. Se retornar `BLOCKED_MISSING_DOCS`, **não** force envio ao portal — confirme que o alerta Anti-Glosa listando exatamente o documento faltante/vencido foi entregue ao grupo da clínica.
4. Se retornar `IN_ANALYSIS`, informe o número do protocolo e confirme que o monitoramento automático seguirá ativo.
5. Se retornar `AUTHORIZED`, informe `Nº Guia`, `Senha`, `Validade` e o arquivo PDF salvo em `06_Guias_Autorizadas/`.
6. Se retornar `AWAITING_HUMAN_2FA`, avise imediatamente qual portal pediu CAPTCHA/2FA e aguarde liberação humana.
