# 03 — Contrato Técnico: Google Drive ⇄ AGS CRM ⇄ `clinic-automation`

Este documento especifica o **contrato de integração compartilhado** entre o **AGS CRM** (onde os pacientes enviam documentos no WhatsApp) e o **`clinic-automation`** (onde o Hermes Agent audita documentos e emite guias nos portais de convênios).

---

## 1. Estrutura Oficial de Pastas no Google Drive

Cada empresa/clínica conectada ao AGS CRM configura **1 Pasta Raiz** no seu próprio Google Drive (ex.: `Nova Gesta — Pacientes`). Dentro dela, o AGS CRM e o `clinic-automation` operam exatamente sobre a mesma convenção de nomes:

```text
📂 [Pasta Raiz da Clínica no Google Drive]
 └── 📂 <NOME_NORMALIZADO> - <CPF_11_DIGITOS_OU_TELEFONE>/
      ├── 📂 01_Identidade/           # RG, CNH, Certidão (categoria: documento_identidade)
      ├── 📂 02_Carteirinhas/         # Carteirinhas de convênio (categoria: carteirinha_convenio)
      ├── 📂 03_Pedidos_Medicos/      # Pedidos/requisições médicas (categoria: pedido_medico)
      ├── 📂 04_Comprovantes/         # Comprovantes PIX/cartão/pagamento (categoria: comprovante_pagamento)
      ├── 📂 05_Exames_Laudos/        # Exames anteriores / laudos (categoria: exame_laudo)
      ├── 📂 06_Guias_Autorizadas/    # PDFs de guias TISS/SP-SADT emitidas pelo Hermes Agent
      └── 📄 ficha_paciente.json      # Dossiê JSON estruturado e sempre atualizado
```

### Regras de Nomenclatura (Chave de Busca Determinística)

1. **Nome da Pasta do Paciente**:
   - Preferencial (quando há CPF): `MARIA_SILVA_SANTOS - 12345678900`
   - Fallback (antes de ter CPF): `MARIA_SILVA_SANTOS - 5561999998888`
   - Se o paciente enviar o CPF depois, a pasta criada por telefone pode ser renomeada/vinculada pelo `cpf` salvo em `ficha_paciente.json` (sem duplicar pasta!).
   - Busca determinística: primeiro procura pasta contendo o `CPF (11 dígitos)` no nome; se não achar, procura pelo sufixo de telefone (últimos 8 dígitos); se não achar, cria nova pasta.
2. **Nome dos Arquivos Salvos pelo AGS CRM**:
   - Padrão: `YYYY-MM-DD_<categoria>_<slug_extra>_<msgIdCurto>.<ext>`
   - Exemplos:
     - `02_Carteirinhas/2026-11-23_carteirinha_saude_caixa_a8f2c1.jpg`
     - `03_Pedidos_Medicos/2026-11-23_pedido_medico_ecografia_9d4e10.pdf`
     - `01_Identidade/2026-11-23_rg_cnh_7b1a02.jpg`
     - `04_Comprovantes/2026-11-23_comprovante_pix_3c9f44.pdf`
3. **Nome dos PDFs de Guias Salvos pelo Hermes (`06_Guias_Autorizadas/`)**:
   - Padrão: `YYYY-MM-DD_<OPERADORA>_GUIA-<NUMERO>_<PROCEDIMENTO>.pdf`
   - Exemplo: `2026-11-23_GDF-SAUDE_GUIA-13096588_ECOGRAFIA.pdf`

---

## 2. Mapeamento de Categorias do AGS CRM → Subpastas do Drive

O AGS CRM já executa `processDocumentAnalysis` (`ai.service.ts`) em todo anexo recebido. O roteamento para subpastas é direto:

| Categoria retornada pelo OCR do AGS CRM | Subpasta no Google Drive | Uso Principal no Faturamento / Hermes |
| :--- | :--- | :--- |
| `documento_identidade` | `01_Identidade` | Conferência de CPF, nome completo e data de nascimento |
| `carteirinha_convenio` | `02_Carteirinhas` | Nº da carteirinha, operadora, plano e **data de validade (anti-glosa)** |
| `pedido_medico` | `03_Pedidos_Medicos` | Upload obrigatório em SP/SADT (ex.: GDF Saúde) + **auditoria de assinatura/CRM/data** |
| `comprovante_pagamento` | `04_Comprovantes` | Conferência financeira / consultas particulares |
| `exame_laudo` | `05_Exames_Laudos` | Histórico clínico / comparação médica |
| `outro` | `05_Exames_Laudos` *(ou raiz/outros)* | Anexos diversos preservados para consulta |

---

## 3. Schema Oficial do `ficha_paciente.json`

Gravado e atualizado de forma mesclada (**merge não-destrutivo**) pelo **AGS CRM** (bloco `crm` e `documentos`) e enriquecido pelo **`clinic-automation`** (bloco `auditoria_anti_glosa` e `guias_emitidas`):

```json
{
  "schema_version": "1.0",
  "updated_at": "2026-11-23T14:30:00-03:00",
  "tenant_slug": "nova-gesta",
  "paciente": {
    "nome": "MARIA SILVA SANTOS",
    "cpf": "12345678900",
    "cpf_formatado": "123.456.789-00",
    "data_nascimento": "1992-05-14",
    "telefone": "+5561999998888",
    "crm_lead_id": 342,
    "crm_contact_id": "uuid-do-contato",
    "igut_paciente_id": "98765"
  },
  "convenio_atual": {
    "operadora": "SAUDE CAIXA",
    "numero_carteirinha": "0001234567890123",
    "plano": "SAUDE CAIXA",
    "titular": "MARIA SILVA SANTOS",
    "validade": "2027-03-31",
    "atendimento_rn": false,
    "atualizado_em": "2026-11-23T14:25:00-03:00",
    "origem": "ags_crm_ocr"
  },
  "documentos": [
    {
      "drive_file_id": "1AbCDefGhIjKlMnOpQrStUvWxYz",
      "subpasta": "02_Carteirinhas",
      "nome_arquivo": "2026-11-23_carteirinha_saude_caixa_a8f2c1.jpg",
      "mime_type": "image/jpeg",
      "categoria": "carteirinha_convenio",
      "recebido_em": "2026-11-23T14:25:00-03:00",
      "crm_message_id": "uuid-msg",
      "crm_ticket_id": "uuid-ticket",
      "ocr_resumo": "Carteirinha Saúde Caixa em nome de Maria Silva Santos, validade 03/2027",
      "ocr_campos": {
        "convenio": "Saúde Caixa",
        "carteirinha": "0001234567890123",
        "validade": "2027-03-31",
        "cpf": "12345678900"
      },
      "ocr_alertas": []
    }
  ],
  "auditoria_anti_glosa": {
    "status": "APROVADO",
    "ultima_verificacao": "2026-11-23T14:32:00-03:00",
    "pendencias": []
  },
  "guias_emitidas": [
    {
      "igut_appointment_id": "896151",
      "data_consulta": "2026-11-24",
      "operadora": "SAUDE CAIXA",
      "numero_guia": "0003406478",
      "senha": "93688570",
      "validade_senha": "2026-12-24",
      "status": "AUTORIZADA",
      "drive_pdf_file_id": "1ZyXwVuTsRqPoNmLkJiHgFeDcBa",
      "lancada_no_igut": true,
      "emitida_em": "2026-11-23T14:35:00-03:00"
    }
  ]
}
```

---

## 4. Contrato de Webhooks (AGS CRM ⇄ `clinic-automation`)

Comunicação leve, assíncrona e autenticada via header `X-API-Key` (sem compartilhar banco de dados):

### 4.1. AGS CRM → `clinic-automation` (`POST /api/v1/webhooks/crm-event`)

Disparado quando ocorre um evento relevante (novo documento salvo no Drive ou novo agendamento confirmado):

```json
{
  "event": "document.synced_to_drive",
  "tenant_slug": "nova-gesta",
  "timestamp": "2026-11-23T14:25:10-03:00",
  "patient": {
    "name": "MARIA SILVA SANTOS",
    "cpf": "12345678900",
    "phone": "+5561999998888"
  },
  "drive": {
    "patient_folder_id": "1FolderIdPaciente",
    "file_id": "1FileIdNovoAnexo",
    "category": "carteirinha_convenio",
    "subfolder": "02_Carteirinhas"
  },
  "crm": {
    "ticket_id": "uuid-ticket",
    "lead_id": 342
  }
}
```

### 4.2. `clinic-automation` → AGS CRM (Opcional / Fase 4)

Callback para registrar uma nota interna na timeline do ticket ou atualizar etapa/observação do lead quando uma guia for autorizada ou travada por glosa:
- `POST /api/integrations/clinic-automation/callback` (autenticado por `X-API-Key` do tenant).

---

## 5. Autenticação Google Drive (Multi-Tenant)

Para funcionar **imediatamente e para qualquer empresa** no AGS CRM:

| Campo na tabela `integrations` (`provider = 'google_drive'`) | Descrição |
| :--- | :--- |
| `authMode` | `'service_account'` *(Fase 1 — imediato, token nunca expira)* ou `'oauth2'` *(Fase futura — botão "Conectar com Google")* |
| `serviceAccountJson` *(criptografado via `CryptoHelper`)* | JSON da Conta de Serviço do Google Cloud (`client_email`, `private_key`, `project_id`) |
| `rootFolderId` | ID da pasta raiz no Google Drive compartilhada como **Editor** com o `client_email` da Service Account |
| `autoSyncCategories` | Lista de categorias habilitadas para upload automático (`["carteirinha_convenio", "documento_identidade", "pedido_medico", "comprovante_pagamento", "exame_laudo"]`) |
| `webhookUrl` *(opcional)* | URL do `clinic-automation` para notificar novos documentos sincronizados |
| `webhookApiKey` *(criptografado, opcional)* | Chave `X-API-Key` para autenticar o webhook |

> **Dica operacional importante (Google Drive Quota)**: Em contas Gmail pessoais, arquivos criados por uma Service Account consomem a cota da própria Service Account (0 GB em drives pessoais sem Shared Drive) **a menos que** a pasta esteja em um **Drive Compartilhado (Google Workspace Shared Drive)** OU use **OAuth 2.0** da conta Google da clínica. Na hora do setup da Nova Gesta, verificaremos se a conta da clínica é **Google Workspace** (usa Shared Drive + Service Account sem limite) ou **Gmail gratuito** (nesse caso, OAuth 2.0 com `refresh_token` da própria conta grava direto na cota do Drive dela!). O módulo suportará ambos os modos de forma transparente.
