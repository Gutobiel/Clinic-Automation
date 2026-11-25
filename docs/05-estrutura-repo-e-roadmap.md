# 05 — Estrutura do Repositório, Stack e Roadmap de Implementação

---

## 1. Estrutura de Diretórios Planejada (`clinic-automation/`)

```text
clinic-automation/
├── README.md                              # Visão geral e índice da arquitetura
├── .gitignore                             # Bloqueia .env, credenciais JSON, sessões e downloads
├── docker-compose.yml                     # Orquestração na VPS Hostinger (API + Workers + Hermes + Caddy)
├── Dockerfile                             # Imagem Python 3.12 + Playwright Chromium + deps
├── pyproject.toml                         # Dependências Python (FastAPI, Playwright, SQLAlchemy, Google API, Pydantic)
│
├── docs/                                  # Documentação arquitetural e contratos
│   ├── 01-arquitetura-e-responsabilidades.md
│   ├── 02-fluxos-e-diagramas.md
│   ├── 03-contrato-google-drive-e-crm.md
│   ├── 04-catalogo-motores-e-portais.md
│   └── 05-estrutura-repo-e-roadmap.md
│
├── core/                                  # 🧱 MOTOR REUTILIZÁVEL AEGIS (100% agnóstico de clínica)
│   ├── config/                            # Loader de Tenant Pack + settings via Pydantic
│   ├── domain/                            # Entidades e schemas (GuideJob, PatientDossier, AuditResult, PortalResult)
│   ├── database/                          # SQLite / SQLAlchemy (tabela guide_jobs, audit_logs, portal_sessions)
│   ├── connectors/
│   │   ├── google_drive.py                # Leitura/escrita de pastas por paciente + ficha_paciente.json
│   │   ├── igut_api.py                    # Cliente REST oficial api.igut.med.br (leitura de agendas/pacientes)
│   │   ├── igut_web_closer.py             # Playwright Worker pós-guia (Autorizado + Guias e Códigos + ARQUIVOS)
│   │   ├── crm_webhook.py                 # Receiver FastAPI (X-API-Key) + callback opcional para AGS CRM
│   │   └── notifier.py                    # Envio de alertas/resumos via Hermes Gateway (WhatsApp / Telegram)
│   ├── auditor/
│   │   └── anti_glosa.py                  # Auditoria multimodal (validade carteirinha, assinatura/CRM, TUSS)
│   ├── orchestrator/
│   │   ├── scheduler.py                   # Cron diário (agenda D-1/D-0 + rechecagem de guias "Em Análise")
│   │   ├── router.py                      # Resolve convênio -> Motor Worker + Prestador + Código Procedimento
│   │   └── runner.py                      # Máquina de estados, retries, locks por portal e modo SHADOW/ASSISTED/AUTO
│   └── workers/                           # ⚡ 6 Motores Playwright Determinísticos
│       ├── base_worker.py                 # Sessão persistente (storage_state), prints de erro, anti-reset senha
│       ├── benner_wes_worker.py           # Motor A: Postal Saúde, Plan-Assiste (MPU), Saúde Caixa
│       ├── benner_conecta_worker.py       # Motor B: Benner Conecta AMHP (7+ planos), Pró-Saúde (TJDFT)
│       ├── maida_gdf_worker.py            # Motor C: INAS — GDF Saúde (lotes 4 itens + upload pedido + capturar/executar)
│       ├── amil_worker.py                 # Motor D: Amil
│       ├── webplan_worker.py              # Motor E: PF Saúde (Fácil Informática)
│       └── tst_saude_worker.py            # Motor F: TST-Saúde
│
├── hermes/                                # 🪽 Configuração e Skills do Hermes Agent
│   ├── SOUL.md                            # Identidade operacional do agente de faturamento/clínica
│   ├── gateway.example.yaml               # Allowlist Grupo + DMs WhatsApp + Fallback Telegram
│   └── skills/
│       ├── faturamento-guias/SKILL.md     # Skill principal para operar jobs, reemitir e consultar status
│       └── auditor-anti-glosa/SKILL.md    # Skill de conferência documental e orientação à equipe
│
├── tenants/                               # 🏥 TENANT PACKS (1 pasta por clínica cliente)
│   └── nova-gesta/
│       ├── .env.example                   # Template sanitizado de variáveis (sem valores reais!)
│       ├── config.json                    # Constantes da clínica (CNPJ, códigos prestador, unidades, crons)
│       ├── portals.json                   # Mapeamento convênio -> motor + URL + tipo credenciamento
│       ├── doctors.json                   # Corpo clínico (CRM, UF, CBO, especialidade)
│       └── procedures_map.json            # Códigos TUSS e proprietários por operadora/especialidade
│
├── infra/                                 # Scripts de setup da VPS Hostinger Ubuntu 24.04 BR
│   ├── setup-vps-ubuntu.sh                # Provisionamento Docker + Playwright + UFW + Caddy + Hermes
│   └── Caddyfile                          # Proxy reverso HTTPS para webhook receiver
│
└── tests/                                 # Testes unitários (roteador, auditor, Drive, máquina de estados)
```

---

## 2. Stack Tecnológica Escolhida

| Camada | Tecnologia | Motivo da Escolha |
| :--- | :--- | :--- |
| **Agente Conversacional & Orquestração Humana** | **Hermes Agent** (`hermes gateway` + Skills) | Já dominado na infraestrutura AEGIS; nativo para Grupo + DM Allowlist (WhatsApp/Telegram), memória e invocação de ferramentas. |
| **API / Webhook Receiver / Orquestrador** | **Python 3.12 + FastAPI + Pydantic v2** | Ecossistema nativo do Hermes, tipagem rigorosa de contratos JSON (`ficha_paciente.json`, webhooks) e excelente suporte a Playwright/Google API. |
| **Automação Web de Portais** | **Playwright (Python Async + Chromium)** | Mais rápido, estável e resistente a SPAs modernas (`Maida/GDF`) e iframes/popups legados (`Benner WES / ASP.NET`) do que RPA puramente visual. |
| **Persistência & Auditoria Local** | **SQLite (WAL) + SQLAlchemy** | Zero sobrecarga de administração na VPS dedicada, backup trivial em 1 arquivo, suporta fila e histórico completo de auditoria. |
| **Armazenamento Documental** | **Google Drive API v3** | Compartilhamento nativo com o AGS CRM e com a equipe humana do faturamento. |
| **Lado AGS CRM (Espelhamento Drive)** | **NestJS 11 + `googleapis` (ou REST Drive v3)** | Aproveita a tabela `integrations` multi-tenant + `processDocumentAnalysis` já em produção no `Ags-Crm`. |

---

## 3. Roadmap de Execução (Sprint a Sprint)

| Sprint | Onde mexemos | Entregáveis Concretos | Critério de Pronto (DoD) |
| :--- | :--- | :--- | :--- |
| **Sprint 0 — Ponte Google Drive no AGS CRM** | `Ags-Crm` (`crm-api` + `crm-client`) | 1. Conector `GoogleDriveService` multi-tenant (`integrations` provider `google_drive`, suportando Service Account e OAuth2).<br>2. Hook assíncrono em `processDocumentAnalysis` salvando anexos nas subpastas `01..05` + atualizando `ficha_paciente.json`.<br>3. Card de configuração na aba **Integrações** do AGS CRM + botão de teste de conexão. | Paciente envia foto de carteirinha/RG/pedido no WhatsApp → em segundos o arquivo e o `ficha_paciente.json` aparecem organizados na pasta do paciente no Google Drive. |
| **Sprint 1 — Fundação `clinic-automation` + Anti-Glosa** | `clinic-automation` | 1. Scaffold Python/FastAPI/SQLite + Tenant Pack `nova-gesta`.<br>2. Conectores: Google Drive + API iGUT + Webhook Receiver CRM.<br>3. **Auditor Anti-Glosa** (Vision/LLM) + integração com Grupo WhatsApp/Telegram.<br>4. Operação em **Modo Sombra (`SHADOW`)** lendo agenda real D-1 e alertando pendências reais no grupo. | Todos os agendamentos do dia seguinte são auditados automaticamente e pendências reais (carteirinha vencida/falta assinatura) geram alerta limpo no grupo. |
| **Sprint 2 — Primeiros Motores (Curva ABC)** | `clinic-automation` | 1. **Motor C — `MaidaGdfWorker`** (GDF Saúde: lotes de 4 exames, upload de pedido médico, `Capturar → Executar → Imprimir PDF`).<br>2. **Motor A — `BennerWesWorker`** (Postal Saúde 1 passo + Plan-Assiste e Saúde Caixa 2 passos). | Emissão ponta a ponta em modo `ASSISTED` com PDF salvo automaticamente em `06_Guias_Autorizadas/` no Drive. |
| **Sprint 3 — Expansão Total dos Portais** | `clinic-automation` | 1. **Motor B — `BennerConectaWorker`** (7+ planos AMHP + Pró-Saúde TJDFT).<br>2. **Motor D (`AmilWorker`)**, **Motor E (`WebPlanWorker` — PF Saúde)** e **Motor F (`TstSaudeWorker`)**. | Cobertura dos 9 portais mapeados (15+ convênios da Nova Gesta). |
| **Sprint 4 — Fechamento iGUT & Autonomia** | `clinic-automation` + VPS Hostinger BR | 1. **`Worker Pós-Guia iGUT`** (`Autorizado` + `Guias e Códigos` + upload `ARQUIVOS` no padrão `AUT EXAME/CONSULTA`).<br>2. Provisionamento na VPS Hostinger Ubuntu 24.04 BR com `setup-vps-ubuntu.sh`.<br>3. 1 semana em `ASSISTED` → virada para `AUTONOMOUS` + resumo diário automático. | Ciclo 100% fechado sem intervenção manual para casos sem pendência documental. |

---

## 4. Checklist de Pré-Requisitos (Para Avançarmos Sem Travas)

1. **Para Sprint 0 (Google Drive no AGS CRM — já podemos começar hoje!)**:
   - Saber se a conta Google Drive onde ficarão os documentos da clínica é **Google Workspace** (domínio próprio / Shared Drive) ou **Gmail gratuito** (`@gmail.com`) — isso define se ativamos primeiro **Service Account** ou **OAuth 2.0**.
2. **Para Sprint 1 (VPS + Hermes + Anti-Glosa)**:
   - VPS Hostinger Ubuntu 24.04 (Datacenter Brasil) provisionada + número WhatsApp (ou Bot Telegram) do grupo interno.
3. **Para Sprints 2–4 (Emissão nos Portais + Fechamento iGUT)**:
   - Credenciais dos portais diretos + login iGUT Web (AMHP já guardado fora do Git).
   - Planilhas de códigos da recepção (`CÓDIGOS ROTINAS`, `RelacaoDoConvenio`, `PLANILHA PLENUM`).
