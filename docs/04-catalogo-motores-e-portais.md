# 04 — Catálogo dos 6 Motores Playwright = 9 Portais (15+ Convênios) + Fechamento iGUT

Resumo executivo de engenharia consolidado a partir da decupagem operacional da **Clínica Nova Gesta** (base para implementação de `core/workers/` e `tenants/nova-gesta/`).

> **Segurança / LGPD**: Nenhuma senha real nem dado pessoal de paciente consta neste arquivo. Credenciais ficam isoladas no `.env` da VPS de produção.

---

## 1. Mapa de Reaproveitamento de Motores (Curva ABC)

| Prioridade | Motor Base (`core/workers/`) | Portais / Convênios Cobertos | URL Base | Credenciamento (Nova Gesta) | Peculiaridade Crítica |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1 (P0)** | **`MaidaGdfWorker`** *(Motor C)* | **INAS — GDF Saúde** *(maior volume observado)* | `https://gdf.maida.health/sso/login` | Direto (`2326`) + Solicitante AMHP (`2073`) | Exige anexo `05 - Pedido do profissional de saúde`, divide combos em **lotes de até 4 exames por guia** e exige etapa pós-autorização **`Capturar guia → Executar itens`** antes de imprimir. |
| **2 (P0)** | **`BennerWesWorker`** *(Motor A)* | **Postal Saúde**, **Plan-Assiste (MPU)**, **Saúde Caixa (CEF)** | `autorizador.postalsaudeservicos.com.br` · `sistema.planassiste.mpu.mp.br` · `credenciadosaude.caixa.gov.br` | Postal/Plan-Assiste: Direto<br>Saúde Caixa: **AMHP-DF** | **Postal**: Consulta 1 passo (`Solicitação de Consulta → Validar`).<br>**Plan-Assiste e Caixa**: SADT em **2 passos** (*Salvar cabeçalho → `Inserir eventos` → `Validar`*). |
| **3 (P0)** | **`BennerConectaWorker`** *(Motor B)* | **Benner Conecta AMHP** *(Senado, STF-MED, TRE-SAÚDE, PMDF, CAMED, FAPES, CONAB)* + **Pró-Saúde (TJDFT)** | `portalconectasaude.com.br` · `prosaudeconecta.tjdft.jus.br` | Conecta: **AMHP-DF**<br>Pró-Saúde: Direto | Wizard idêntico em 3 passos (`/Guias/Consulta/NovaConsulta`). Usa **tabela própria de códigos por especialidade** (não TUSS genérico!). |
| **4 (P1)** | **`AmilWorker`** *(Motor D)* | **Amil** | `https://credenciado.amil.com.br/pedidos-autorizacao` | Direto (`75693771`) | Busca por **CPF ou Carteirinha** (se buscar por CPF, retorna a carteirinha oficial). Campos obrigatórios: `Data de solicitação do pedido` e `Atendimento RN`. |
| **5 (P1)** | **`WebPlanWorker`** *(Motor E)* | **PF Saúde (Polícia Federal)** | `novowebplanpfdf.facilinformatica.com.br/GuiasTISS/Logon` | **AMHP-DF** (`PRESTADOR PJ`) | Código por especialidade (`7.00.10.70-7` Pediatria). Regra AMHP: se médico não localizado, usar **`BCWQM-0`** e nome/CRM nas observações. |
| **6 (P1)** | **`TstSaudeWorker`** *(Motor F)* | **TST-Saúde** | `aplicacao.tstsaude.tst.jus.br/tstsaude/SolicitarProcedimento.do` | Direto | Mesmo consulta usa `SolicitarProcedimento.do` (SP/SADT) trocando modal para **`Tabela TUSS`** (`10101012`). |
| **Hub** | **`AmhpHubReader`** | **Portal do Associado AMHP** | `https://portal.amhp.com.br/faturamento` | AMHP-DF | Consulta regras, URLs e avisos oficiais dos convênios credenciados via associação. |

---

## 2. Regras de Ouro Anti-Bloqueio & Segurança nos Portais

1. **Proibição Absoluta de "Esqueci minha senha" (Regra AMHP)**:
   - O Portal AMHP adverte expressamente que é proibido alterar/recuperar senhas dos portais credenciados via associação.
   - Se qualquer worker receber falha de autenticação **1 única vez**, ele marca o job como `CREDENTIAL_LOCKED`, pausa aquela operadora e notifica o administrador imediatamente.
2. **Sessão Persistente (`storage_state.json`)**:
   - Cada portal mantém seu próprio estado de cookies/sessão em disco protegido na VPS, evitando logins repetitivos a cada guia.
3. **Execução Sequencial por Portal + Jitter Humano**:
   - Máximo de 1 worker simultâneo por portal de operadora (evita conflito de sessão única ASP.NET/Benner) e pausas leves naturais entre cliques.
4. **IP Brasileiro Obrigatório**:
   - VPS obrigatoriamente em datacenter Brasil (São Paulo) para evitar Captchas/WAFs agressivos de portais públicos (`caixa.gov.br`, `tst.jus.br`, `tjdft.jus.br`, `gdf.maida.health`).

---

## 3. Tabela Inicial de Códigos por Operadora (Nova Gesta)

> Será armazenada em `tenants/nova-gesta/procedures_map.json` e enriquecida com as planilhas da clínica (`CÓDIGOS ROTINAS`, `RelacaoDoConvenio`, `PLANILHA PLENUM`).

| Operadora | Código Consulta (Referência Mapeada) | Tipo de Tabela |
| :--- | :--- | :--- |
| **Postal Saúde**, **Amil**, **TST-Saúde**, **Saúde Caixa** | `10101012` | TUSS Padrão |
| **PF Saúde (WebPlan)** | `7.00.10.70-7` *(Pediatria)* | Tabela própria (`21/22`) por especialidade |
| **Plan-Assiste (MPU)** | `700010707` *(Pediatria)* | Numeração própria sem pontuação por especialidade |
| **Pró-Saúde (TJDFT)** | `90050288` *(Pediatria)* · `90050690` *(Ginecologia)* · `90050296` *(Clínica Médica)* | Tabela própria por especialidade |
| **Senado Federal (Benner Conecta)** | `000010530` *(Pediatria)* · `000010014` *(Ginecologia)* · `000010557` *(Cirurgião Pediátrico)* | Tabela própria por especialidade |
| **INAS — GDF Saúde** | Tabela `22` TUSS (`40901300`, `40901386`, `40901360`, `40901114`, `40901203`, `40901211`, `40901122`...) | TUSS Exames / SP-SADT (máx. 4 itens/guia) |

---

## 4. Ritual Obrigatório de Fechamento no iGUT (`Worker Pós-Guia iGUT`)

Após **qualquer portal** retornar `AUTORIZADA` e o PDF ser salvo no Google Drive (`06_Guias_Autorizadas/`):

1. **Passo A — Ficha do Agendamento (`novagesta.igutclinicas.com.br`)**:
   - Abrir o agendamento na agenda do médico.
   - Conferir/preencher `Token / Número` (carteirinha) e `Data Validade`.
   - Alterar status de autorização para **`Autorizado`** e salvar.
2. **Passo B — Modal `Guias e Códigos`**:
   - Preencher **`Nº Guia Operadora`**, **`Senha`**, **`Validade da Senha`**, **`Data Autorização`** e **`Tipo de Atendimento`** (`Consulta` ou `Exame Ambulatorial`).
   - Incluir todos os códigos TUSS/operadora autorizados + quantidades e clicar **`SALVAR`**.
3. **Passo C — Anexo em `Arquivos e Imagens -> ARQUIVOS`**:
   - Subir o PDF da guia com nome padronizado:
     - Exame: `AUT EXAME - DRA <MEDICO> (<DD/MM>)`
     - Consulta: `AUT CONSULTA - DRA <MEDICO> (<DD/MM>)`
   - Tratar popup de replicação de status quando o paciente tiver múltiplos agendamentos no mesmo dia conforme regra de combo.
