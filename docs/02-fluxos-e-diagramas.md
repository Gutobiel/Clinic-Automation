# 02 — Fluxos Operacionais e Diagramas

Este documento detalha visualmente **como os dados e documentos trafegam de ponta a ponta**, desde o momento em que o paciente envia uma foto no WhatsApp até a guia autorizada estar salva no Google Drive e lançada no iGUT.

---

## 1. Fluxo 1 — Captura de Documentos no AGS CRM → Espelhamento no Google Drive

```mermaid
sequenceDiagram
    autonumber
    actor P as 👩 Paciente (WhatsApp)
    participant CRM as 🤖 AGS CRM (webhook-processor)
    participant OCR as 👁️ Vision / OCR (ai.service)
    participant DRIVE as 📂 Google Drive (Pasta da Clínica)
    participant AUTO as 🪽 clinic-automation (Hermes)

    P->>CRM: Envia foto/PDF (Carteirinha, RG, Pedido Médico ou Comprovante)
    CRM->>OCR: processDocumentAnalysis(buffer, filename, mimetype)
    OCR-->>CRM: categoria + extractedFields (CPF, operadora, carteirinha, validade, alertas)
    CRM->>CRM: Salva metadata.documentAnalysis + enriquece Lead/Ficha CRM
    CRM-->>P: Agente de IA continua atendimento normalmente (sem travar!)

    par Espelhamento Assíncrono em Background
        CRM->>DRIVE: Localiza ou cria pasta "<NOME_PACIENTE> - <CPF_OU_TEL>"
        CRM->>DRIVE: Faz upload na subpasta correta (ex: 02_Carteirinhas / 03_Pedidos_Medicos)
        CRM->>DRIVE: Atualiza ficha_paciente.json (campos extraídos + índice de arquivos)
        CRM-->>AUTO: Webhook POST /api/v1/webhooks/crm-event (opcional, assíncrono)
    end
```

> **Ponto-chave**: O upload para o Google Drive roda **em background (non-blocking)** após a análise do anexo no AGS CRM. Se a API do Google oscilar por 5 segundos, o atendimento do paciente no WhatsApp não sofre atraso algum e uma fila/retry garante o espelhamento.

---

## 2. Fluxo 2 — Emissão de Guia com Barreira Anti-Glosa (Ponta a Ponta)

```mermaid
flowchart TD
    G(["🎯 Gatilhos de Entrada\n1. Cron diário (lê agenda D-1 / D-0 no iGUT)\n2. Webhook do AGS CRM (agendamento ou novo doc)\n3. Comando da equipe no Grupo / DM do Hermes"]) --> FETCH["🏥 Consulta Agendamento no iGUT\nObtém Paciente, CPF, Convênio, Médica,\nEspecialidade, Procedimento, Data/Hora"]

    FETCH --> CHECK_PREV{"Guia já emitida\ne Autorizada?"}
    CHECK_PREV -->|"Sim"| SKIP(["⏭️ Ignora (Idempotência)\nRegistra log sem duplicar"])
    CHECK_PREV -->|"Não"| DRIVE_READ["📂 Lê Dossiê no Google Drive\nBaixa ficha_paciente.json +\nCarteirinha + RG + Pedido Médico"]

    DRIVE_READ --> AUDIT{"🛡️ AUDITOR ANTI-GLOSA\n1. Carteirinha existe e está válida?\n2. Pedido médico (se exame/SADT) tem\n   ASSINATURA + CARIMBO/CRM + data válida?\n3. Dados batem com paciente/convênio?\n4. Código TUSS/operadora mapeado?"}

    AUDIT -->|"❌ Risco de Glosa Detectado"| BLOCK["🚨 TRAVA EMISSÃO + ALERTA NO GRUPO\nInforma paciente, convênio e pendência exata\n(ex: carteirinha vencida ou pedido sem assinatura)"]
    BLOCK --> WAIT_DOC["⏳ Job fica em BLOCKED_MISSING_DOCS\nAguarda envio do doc corrigido no CRM/Drive/Grupo"]
    WAIT_DOC -->|"Novo doc recebido"| DRIVE_READ

    AUDIT -->|"✅ 100% Aprovado"| ROUTE["🧭 Roteador de Convênio\nSeleciona Motor (A..F) + Prestador (Direto/AMHP)\n+ Tabela de Códigos da Operadora"]

    ROUTE --> WORKER["🤖 Agente IA + Browser (Hermes/Playwright)\nExecuta ações humanas no portal com a Skill do convênio\ne acompanha a aprovação da guia em tempo real"]

    WORKER --> AUTH{"🔐 Sessão / Login"}
    AUTH -->|"Pediu 2FA ou Captcha"| HITL_2FA["📸 Pausa e avisa Grupo/Admin\npara resolver 2FA/Captcha"] --> WORKER
    AUTH -->|"Erro de senha"| LOCK_CRED["🛑 TRAVA CREDENCIAL\nNUNCA clica em 'Esqueci minha senha' (Regra AMHP)\nNotifica Admin imediatamente"]
    AUTH -->|"Sessão ativa"| FILL["⌨️ Preenche Formulário do Portal\n• Beneficiário + Prestador + Profissional/CBO\n• Códigos (lotes de até 4 no GDF Saúde)\n• Upload Pedido Médico (se SP/SADT)\n• Valida / Envia solicitação"]

    FILL --> RESULT{"📄 Retorno do Portal"}

    RESULT -->|"✅ AUTORIZADA"| POST["✅ Pós-Emissão em 3 Passos\n1. GDF: Capturar guia → Executar itens → Imprimir PDF\n2. Salva PDF em Drive/06_Guias_Autorizadas/\n3. Atualiza ficha_paciente.json"]
    POST --> IGUT_CLOSE["🏥 Worker Pós-Guia iGUT\n1. Marca agendamento como 'Autorizado'\n2. Preenche 'Guias e Códigos' (Guia/Senha/TUSS)\n3. Sobe PDF em 'ARQUIVOS' no padrão AUT EXAME/CONSULTA"]
    IGUT_CLOSE --> DONE(["🎉 Job COMPLETED\nRegistra na auditoria + entra no Resumo Diário"])

    RESULT -->|"🟡 EM ANÁLISE"| ANALYSIS["🕒 Salva Protocolo no SQLite\nAgenda rechecagem periódica via Cron\nAvisa Grupo que ficou em auditoria da operadora"]

    RESULT -->|"🔴 NEGADA"| DENIED["🚨 Captura screenshot + motivo exato da negativa\nSalva evidência na pasta do Drive\nAlerta Grupo da Clínica imediatamente"]
```

---

## 3. Fluxo 3 — Máquina de Estados de um `GuideJob` (SQLite)

Todo pedido de emissão de guia possui rastreabilidade completa e idempotência pela chave `(tenant_id, igut_appointment_id, procedure_batch_index)`:

```mermaid
stateDiagram-v2
    [*] --> DISCOVERED : Cron iGUT / Webhook CRM / Comando Equipe
    DISCOVERED --> DOCS_COLLECTING : Busca pasta e ficha no Google Drive
    DOCS_COLLECTING --> ANTI_GLOSA_AUDIT : Documentos carregados

    ANTI_GLOSA_AUDIT --> BLOCKED_MISSING_DOCS : Carteirinha vencida / sem assinatura / falta doc
    BLOCKED_MISSING_DOCS --> DOCS_COLLECTING : Novo documento recebido no Drive/CRM/Grupo

    ANTI_GLOSA_AUDIT --> READY_FOR_PORTAL : Auditoria aprovada (0 pendências)
    READY_FOR_PORTAL --> PORTAL_RUNNING : Playwright Worker iniciado

    PORTAL_RUNNING --> AWAITING_HUMAN_2FA : Portal exigiu 2FA ou Captcha
    AWAITING_HUMAN_2FA --> PORTAL_RUNNING : Operador liberou acesso

    PORTAL_RUNNING --> CREDENTIAL_LOCKED : Falha de login (trava segurança AMHP)
    CREDENTIAL_LOCKED --> READY_FOR_PORTAL : Admin atualizou credencial

    PORTAL_RUNNING --> IN_ANALYSIS : Portal colocou guia em auditoria/reanálise
    IN_ANALYSIS --> PORTAL_RUNNING : Cron recheca status no histórico do portal

    PORTAL_RUNNING --> DENIED : Operadora negou a guia
    PORTAL_RUNNING --> AUTHORIZED : Guia autorizada + PDF baixado

    AUTHORIZED --> IGUT_CLOSING : Salva PDF no Drive + lança no iGUT
    IGUT_CLOSING --> COMPLETED : Status Autorizado + Guias e Códigos + PDF no iGUT
    IGUT_CLOSING --> IGUT_CLOSE_FAILED : Erro temporário ao lançar no iGUT
    IGUT_CLOSE_FAILED --> IGUT_CLOSING : Retry automático ou manual

    COMPLETED --> [*]
    DENIED --> [*]
```

---

## 4. Fluxo 4 — Operação Humana no Grupo & DMs (WhatsApp / Telegram)

```mermaid
flowchart LR
    subgraph HERMES_OUT["📤 Mensagens Proativas do Hermes"]
        A1["🚨 Alerta Anti-Glosa\n'Maria Silva (GDF Saúde — 24/11 10h):\n• Pedido médico sem assinatura\n• Carteirinha vencida em 10/11'"]
        A2["🟡 Guia em Análise / 🔴 Negada\nMotivo exato + protocolo + print"]
        A3["📊 Resumo Diário (18h)\n'28 autorizadas · 2 em análise · 3 aguardando doc'"]
    end

    subgraph TEAM_IN["📥 Comandos da Equipe (Allowlist)"]
        C1["No Grupo (menção @Hermes / Hermes):\n'Hermes, a Maria mandou o pedido assinado,\npode reemitir a guia dela no GDF Saúde'"]
        C2["Na DM Individual (funcionária autorizada):\n'Hermes, puxa o status das guias de amanhã\nda Dra. Camila'"]
    end

    HERMES_OUT --> CHAT["💬 Grupo Nova Gesta + DMs\nPrincipal: WhatsApp Allowlist\nFallback 1-min: Telegram Bot"]
    TEAM_IN --> CHAT
    CHAT --> ENGINE["🪽 Hermes Agent\n(Executa ação e devolve retorno com PDF/status)"]
```

---

## 5. Modo de Operação Progressivo (Segurança na Implantação)

Para garantir **confiança total da equipe** antes de deixar 100% autônomo:

1. **Modo Sombra / Auditoria (`SHADOW`)**: Lê agenda iGUT + Drive, roda o **Auditor Anti-Glosa** e reporta pendências no grupo, sem submeter nada nos portais ainda.
2. **Modo Assistido (`ASSISTED`)**: Emite a guia no portal (ou prepara tudo) e envia o PDF + números no Grupo para conferência rápida antes ou logo após lançar no iGUT.
3. **Modo Autônomo (`AUTONOMOUS`)**: Emite, salva no Drive, fecha no iGUT e envia apenas exceções (glosas evitadas / negativas / 2FA) + o resumo consolidado do dia.
