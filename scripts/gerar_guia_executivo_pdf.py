r"""
Gera o Guia Executivo em PDF (A4) para apresentação a clínicas (piloto: Clínica Nova Gesta / Dr. Marcondes).
Reutiliza o Chromium do Playwright já instalado no ambiente virtual.

Uso:
    .\.venv\Scripts\python.exe scripts\gerar_guia_executivo_pdf.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT_HTML = ROOT / "docs" / "Guia_Executivo_Automacao_Guias_AEGIS_Nova_Gesta.html"
OUT_PDF = ROOT / "docs" / "Guia_Executivo_Automacao_Guias_AEGIS_Nova_Gesta.pdf"


HTML_CONTENT = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8" />
<title>Guia Executivo — Automação Inteligente de Guias | AEGIS × Clínica Nova Gesta</title>
<style>
  @page {
    size: A4;
    margin: 14mm 15mm 16mm 15mm;
  }
  * {
    box-sizing: border-box;
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
  }
  body {
    margin: 0;
    font-family: 'Segoe UI', Inter, -apple-system, BlinkMacSystemFont, sans-serif;
    color: #0f172a;
    font-size: 10.2pt;
    line-height: 1.48;
    background: #ffffff;
  }
  .hero {
    background: linear-gradient(135deg, #0b2545 0%, #0f4c75 60%, #0e7490 100%);
    color: #ffffff;
    border-radius: 14px;
    padding: 24px 28px;
    margin-bottom: 18px;
    position: relative;
    overflow: hidden;
  }
  .hero-badge {
    display: inline-block;
    background: rgba(255,255,255,0.16);
    border: 1px solid rgba(255,255,255,0.28);
    color: #e0f2fe;
    font-size: 8.5pt;
    font-weight: 700;
    letter-spacing: 0.9px;
    text-transform: uppercase;
    padding: 4px 10px;
    border-radius: 999px;
    margin-bottom: 10px;
  }
  .hero h1 {
    margin: 0 0 8px 0;
    font-size: 19pt;
    line-height: 1.2;
    font-weight: 800;
    letter-spacing: -0.3px;
  }
  .hero p {
    margin: 0;
    font-size: 10.2pt;
    color: #dbeafe;
    max-width: 96%;
  }
  .hero-meta {
    display: flex;
    gap: 18px;
    margin-top: 14px;
    padding-top: 12px;
    border-top: 1px solid rgba(255,255,255,0.2);
    font-size: 8.8pt;
    color: #bae6fd;
  }
  .hero-meta strong { color: #ffffff; }

  h2 {
    font-size: 12.6pt;
    color: #0b2545;
    margin: 18px 0 8px 0;
    padding-bottom: 5px;
    border-bottom: 2px solid #0ea5e9;
    display: flex;
    align-items: center;
    gap: 7px;
    page-break-after: avoid;
  }
  h3 {
    font-size: 10.5pt;
    color: #0f4c75;
    margin: 11px 0 5px 0;
    page-break-after: avoid;
  }
  p { margin: 0 0 8px 0; }

  .summary-strip {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 10px;
    margin: 12px 0 16px 0;
  }
  .kpi {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-top: 3px solid #0284c7;
    border-radius: 10px;
    padding: 10px 11px;
  }
  .kpi-num {
    font-size: 13pt;
    font-weight: 800;
    color: #0b2545;
    margin-bottom: 2px;
  }
  .kpi-lbl {
    font-size: 8.2pt;
    color: #475569;
    line-height: 1.3;
  }

  /* Flow Steps */
  .flow-grid {
    display: grid;
    grid-template-columns: 1fr;
    gap: 8px;
    margin: 10px 0 14px 0;
  }
  .step-card {
    display: grid;
    grid-template-columns: 36px 1fr;
    gap: 12px;
    align-items: start;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-left: 4px solid #0284c7;
    border-radius: 10px;
    padding: 10px 14px;
    page-break-inside: avoid;
  }
  .step-card.emerald { border-left-color: #10b981; background: #f0fdf4; border-color: #bbf7d0; }
  .step-card.amber { border-left-color: #f59e0b; background: #fffbeb; border-color: #fde68a; }
  .step-card.indigo { border-left-color: #4f46e5; background: #eef2ff; border-color: #c7d2fe; }
  .step-num {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background: #0b2545;
    color: #ffffff;
    font-weight: 800;
    font-size: 10.5pt;
    display: flex;
    align-items: center;
    justify-content: center;
    margin-top: 2px;
  }
  .step-title {
    font-weight: 800;
    color: #0f172a;
    font-size: 10.3pt;
    margin-bottom: 3px;
  }
  .step-desc {
    font-size: 9.2pt;
    color: #334155;
    margin: 0;
  }

  table {
    width: 100%;
    border-collapse: collapse;
    margin: 8px 0 14px 0;
    font-size: 8.9pt;
    page-break-inside: avoid;
  }
  th {
    background: #0b2545;
    color: #ffffff;
    text-align: left;
    padding: 7px 9px;
    font-weight: 700;
  }
  td {
    padding: 7px 9px;
    border-bottom: 1px solid #e2e8f0;
    vertical-align: top;
  }
  tr:nth-child(even) td { background: #f8fafc; }

  .two-col {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    margin: 8px 0 14px 0;
  }
  .box {
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 12px 14px;
    background: #ffffff;
    page-break-inside: avoid;
  }
  .box-highlight {
    background: #f0f9ff;
    border-color: #bae6fd;
  }
  .box-safe {
    background: #f0fdf4;
    border-color: #bbf7d0;
  }
  .box-warn {
    background: #fffbeb;
    border-color: #fde68a;
  }
  ul {
    margin: 4px 0 0 0;
    padding-left: 17px;
  }
  li {
    margin-bottom: 4px;
    font-size: 9.1pt;
    color: #1e293b;
  }

  .folder-tree {
    font-family: Consolas, 'Courier New', monospace;
    font-size: 8.1pt;
    background: #0f172a;
    color: #e2e8f0;
    padding: 11px 13px;
    border-radius: 10px;
    line-height: 1.55;
    white-space: pre;
    overflow: hidden;
    margin: 8px 0 12px 0;
    page-break-inside: avoid;
  }
  .folder-tree .hl { color: #38bdf8; font-weight: 700; }
  .folder-tree .ok { color: #4ade80; font-weight: 700; }

  .pill {
    display: inline-block;
    padding: 2px 7px;
    border-radius: 999px;
    font-size: 7.8pt;
    font-weight: 700;
  }
  .pill-green { background: #dcfce7; color: #166534; }
  .pill-blue { background: #e0f2fe; color: #075985; }
  .pill-amber { background: #fef3c7; color: #92400e; }

  .page-break { page-break-before: always; }

  .footer {
    margin-top: 16px;
    padding-top: 8px;
    border-top: 1px solid #cbd5e1;
    display: flex;
    justify-content: space-between;
    font-size: 8pt;
    color: #64748b;
  }
</style>
</head>
<body>

  <!-- HERO / CAPA EXECUTIVA -->
  <div class="hero">
    <div class="hero-badge">AEGIS Tecnologia • Documento Executivo de Operação</div>
    <h1>Automação Inteligente de Documentos, Auditoria Anti-Glosa e Emissão de Guias</h1>
    <p>
      Guia completo de funcionamento do ecossistema <strong>AGS CRM + Google Drive + iGUT + Agente IA Hermes</strong>
      para eliminar tarefas manuais de recepção/faturamento, prevenir glosas antes do atendimento e acompanhar
      autorizações de convênios em tempo real.
    </p>
    <div class="hero-meta">
      <div><strong>Clínica Piloto:</strong> Clínica Nova Gesta (Dr. Marcondes)</div>
      <div><strong>Arquitetura:</strong> Multi-Clínica &amp; 100% LGPD</div>
      <div><strong>Data:</strong> Novembro/2026</div>
    </div>
  </div>

  <!-- KPIs -->
  <div class="summary-strip">
    <div class="kpi">
      <div class="kpi-num">0 arquivos</div>
      <div class="kpi-lbl">retidos no servidor do SaaS — 100% no Google Drive da própria clínica</div>
    </div>
    <div class="kpi">
      <div class="kpi-num">Anti-Glosa</div>
      <div class="kpi-lbl">auditoria automática de carteirinha, validade, assinatura e CRM antes do portal</div>
    </div>
    <div class="kpi">
      <div class="kpi-num">9 Portais</div>
      <div class="kpi-lbl">AMHPTISS, Benner Conecta, GDF Saúde, Caixa, Postal, Plan-Assiste, TJDFT, Amil, TST, PF</div>
    </div>
    <div class="kpi">
      <div class="kpi-num">24/7 Ativo</div>
      <div class="kpi-lbl">monitoramento automático de guias <em>Em Análise</em> até virarem <em>Autorizadas</em></div>
    </div>
  </div>

  <!-- SEÇÃO 1: FLUXO PONTA A PONTA -->
  <h2>1. Como Funciona o Fluxo Completo (Passo a Passo)</h2>
  <p>
    Cada sistema cumpre um papel único e bem definido. A recepcionista <strong>não precisa mais baixar fotos do WhatsApp</strong>,
    subir carteirinhas manualmente no iGUT nem ficar dando F5 nos portais de convênios:
  </p>

  <div class="flow-grid">
    <div class="step-card">
      <div class="step-num">1</div>
      <div>
        <div class="step-title">Recebimento no WhatsApp + Leitura Inteligente (AGS CRM)</div>
        <p class="step-desc">
          Quando o paciente envia foto ou PDF da <strong>carteirinha do convênio</strong>, <strong>RG/CNH</strong>,
          <strong>pedido médico</strong>, <strong>comprovante PIX</strong> ou <strong>exame</strong> no WhatsApp, a IA do AGS CRM
          classifica automaticamente o documento e extrai por OCR/Vision o número da carteirinha, validade, operadora, CPF e exames solicitados.
        </p>
      </div>
    </div>

    <div class="step-card emerald">
      <div class="step-num">2</div>
      <div>
        <div class="step-title">Armazenamento Automático no Google Drive da Clínica (LGPD)</div>
        <p class="step-desc">
          Imediatamente após a leitura, o AGS CRM envia o arquivo direto para o <strong>Google Drive da própria clínica</strong>
          (pasta <code>Documentos pacientes</code>), criando sozinho a pasta do paciente e atualizando a ficha estruturada
          <code>ficha_paciente.json</code>. Ao salvar, dispara um <strong>evento em tempo real (webhook)</strong> para o agente de faturamento.
        </p>
      </div>
    </div>

    <div class="step-card amber">
      <div class="step-num">3</div>
      <div>
        <div class="step-title">Cruzamento Agenda iGUT + Barreira Auditora Anti-Glosa</div>
        <p class="step-desc">
          O agente <strong>Hermes</strong> consulta a <strong>agenda do iGUT</strong> (paciente, data, médica, especialidade e convênio)
          e cruza com a pasta do paciente no <strong>Google Drive</strong>. Antes de abrir qualquer portal, o <strong>Auditor Anti-Glosa</strong>
          verifica: carteirinha válida na data da consulta, existência de pedido médico (para exames/SP-SADT), presença de assinatura,
          carimbo/CRM, prazo de 60 dias e código TUSS. <strong>Se houver pendência, bloqueia e avisa a recepção na hora</strong> com o motivo exato.
        </p>
      </div>
    </div>

    <div class="step-card indigo">
      <div class="step-num">4</div>
      <div>
        <div class="step-title">Agente IA Operando o Portal do Convênio + Vigilância Contínua</div>
        <p class="step-desc">
          Com a documentação aprovada, o roteador identifica o portal exato do convênio (AMHPTISS, Benner Conecta, GDF Saúde, Caixa,
          Postal, Amil, Plan-Assiste, TJDFT, PF Saúde ou TST) e aciona o <strong>Agente IA de Navegador</strong>. A IA preenche a solicitação,
          anexa o pedido médico quando exigido, submete e <strong>acompanha continuamente guias que ficam "Em Análise"</strong> até
          saírem <strong>Autorizadas</strong> (baixando o PDF oficial) ou <strong>Negadas</strong> (notificando o motivo exato).
        </p>
      </div>
    </div>

    <div class="step-card emerald">
      <div class="step-num">5</div>
      <div>
        <div class="step-title">Entrega do PDF Autorizado + Fechamento no Prontuário iGUT</div>
        <p class="step-desc">
          Assim que a guia é autorizada, o PDF oficial é salvo em <code>06_Guias_Autorizadas/</code> no Google Drive do paciente,
          os dados (<code>Nº da Guia</code>, <code>Senha</code> e <code>Validade</code>) são gravados no <code>ficha_paciente.json</code>,
          o grupo da clínica recebe a confirmação e (na fase de fechamento iGUT) o agendamento é marcado como <strong>Autorizado</strong>
          com o PDF anexado no padrão da clínica (<code>AUT CONSULTA</code> / <code>AUT EXAME</code>).
        </p>
      </div>
    </div>
  </div>

  <!-- SEÇÃO 2: ANTES VS DEPOIS -->
  <h2>2. Comparativo Operacional: Processo Manual vs. Automação AEGIS</h2>
  <table>
    <thead>
      <tr>
        <th style="width:22%;">Etapa</th>
        <th style="width:39%;">Antes (Manual pela Recepção)</th>
        <th style="width:39%;">Agora (AGS CRM + Drive + Agente IA)</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td><strong>Documentos do WhatsApp</strong></td>
        <td>Recepcionista baixa imagem por imagem no PC e sobe manualmente no iGUT.</td>
        <td>Salvo automaticamente no Google Drive da clínica em subpastas organizadas por paciente.</td>
      </tr>
      <tr>
        <td><strong>Conferência Anti-Glosa</strong></td>
        <td>Erro descoberto só na hora do atendimento ou depois, gerando glosa do convênio.</td>
        <td>Auditoria instantânea ao receber o documento: alerta imediato se faltar assinatura, CRM ou se a carteirinha venceu.</td>
      </tr>
      <tr>
        <td><strong>Solicitação nos Portais</strong></td>
        <td>Digitação manual em até 9 portais diferentes com tabelas TUSS distintas.</td>
        <td>Roteamento automático por convênio/especialidade e preenchimento operado por IA com quebra automática de lotes (ex.: máx. 4 itens no GDF Saúde).</td>
      </tr>
      <tr>
        <td><strong>Guias "Em Análise"</strong></td>
        <td>Equipe precisa lembrar de entrar várias vezes ao dia para dar F5 e conferir.</td>
        <td>Robô monitora automaticamente a cada 30 min e avisa no segundo em que sair <em>Autorizada</em> ou <em>Negada</em>.</td>
      </tr>
      <tr>
        <td><strong>Posse dos Dados (LGPD)</strong></td>
        <td>Arquivos espalhados em computadores locais e WhatsApp Web.</td>
        <td>100% centralizados no Google Drive da própria clínica, com trilha de auditoria e revogação a 1 clique.</td>
      </tr>
    </tbody>
  </table>

  <div class="page-break"></div>

  <!-- SEÇÃO 3: SERVIDOR HERMES ORIENTADO A EVENTOS + DRIVE + NOTIFICAÇÕES -->
  <h2>3. Como Funciona o Servidor Dedicado com Hermes AEGIS (100% por Eventos)</h2>
  <p>
    A automação roda em um <strong>servidor dedicado exclusivo da clínica</strong> (totalmente separado do SaaS AGS CRM),
    onde vive o agente <strong>Hermes AEGIS</strong> conectado diretamente ao <strong>Google Drive da clínica</strong> e
    escutando eventos em tempo real via Webhook. <strong>Ninguém precisa pedir nem clicar em nada:</strong>
  </p>

  <div class="flow-grid">
    <div class="step-card indigo">
      <div class="step-num">A</div>
      <div>
        <div class="step-title">Gatilho Instantâneo por Evento (Carteirinha Nova ou Agendamento Novo)</div>
        <p class="step-desc">
          Com o servidor Hermes ativo 24/7, no segundo em que um paciente envia uma <strong>carteirinha nova no WhatsApp</strong>
          (salva automaticamente no Google Drive) ou surge um <strong>agendamento novo no iGUT</strong>, o AGS CRM dispara um
          evento em tempo real para o Hermes da clínica — acordando o fluxo na hora, sem intervenção humana.
        </p>
      </div>
    </div>

    <div class="step-card">
      <div class="step-num">B</div>
      <div>
        <div class="step-title">Abertura Automática do Portal Específico + Emissão de Guia Real</div>
        <p class="step-desc">
          O Hermes lê automaticamente o dossiê daquele paciente no <strong>Google Drive</strong> (<code>ficha_paciente.json</code>,
          carteirinha e pedido médico), passa pelo <strong>Auditor Anti-Glosa</strong>, identifica o convênio e
          <strong>abre automaticamente o portal do convênio específico</strong> (AMHPTISS, Benner Conecta, GDF Saúde, Caixa,
          Postal, etc.) para <strong>emitir a guia real em nome do paciente verdadeiro</strong>.
        </p>
      </div>
    </div>

    <div class="step-card emerald">
      <div class="step-num">C</div>
      <div>
        <div class="step-title">Devolução Automática do PDF Autorizado + Notificação Omnichannel pelo Hermes</div>
        <p class="step-desc">
          Assim que o convênio aprova, o Hermes baixa o <strong>PDF oficial da guia autorizada</strong>, salva de volta na pasta
          do paciente no Google Drive (<code>06_Guias_Autorizadas/</code>) e <strong>dispara imediatamente uma notificação
          personalizada</strong> — no <strong>WhatsApp</strong>, por <strong>E-mail</strong> ou no canal interno definido pela
          clínica — já com o resumo (paciente, nº da guia, senha e link do PDF) para a responsável apenas <strong>conferir,
          imprimir ou arquivar</strong> como preferir.
        </p>
      </div>
    </div>
  </div>

  <div class="two-col">
    <div>
      <h3>📂 Árvore Criada Sozinha no Drive da Clínica</h3>
      <div class="folder-tree">
<span class="hl">Documentos pacientes/</span>
└── MARIA_CLARA_ALVES - 45678912300/
    ├── <span class="ok">ficha_paciente.json</span> (dados OCR + guias)
    ├── 01_Identidade/       (RG / CNH)
    ├── 02_Carteirinhas/     (Carteirinha convênio)
    ├── 03_Pedidos_Medicos/  (Pedidos p/ exames)
    ├── 04_Comprovantes/     (Comprovantes PIX)
    ├── 05_Exames_Laudos/    (Laudos enviados)
    └── <span class="ok">06_Guias_Autorizadas/</span> (PDFs oficiais!)
      </div>
      <p style="font-size:8.4pt;color:#475569;">
        <strong>Autonomia total:</strong> recepção e médicos acessam qualquer pasta direto pelo Google Drive normal,
        a qualquer momento — sem depender de sistema fechado.
      </p>
    </div>

    <div class="box box-highlight">
      <h3 style="margin-top:0;">🔔 Por que o Hermes faz tanta diferença?</h3>
      <ul>
        <li><strong>Notificação na hora da aprovação:</strong> guia autorizada → aviso imediato no <strong>WhatsApp ou E-mail</strong> da faturista/recepção para conferência e impressão rápida.</li>
        <li><strong>Alerta proativo de pendência:</strong> carteirinha vencida, pedido sem CRM ou guia negada → Hermes avisa imediatamente quem precisa agir, com o motivo exato.</li>
        <li><strong>Timing inteligente de validade:</strong> se a consulta é para daqui a 40 dias, audita hoje e dispara a solicitação no portal na janela segura (<strong>D-2 / D-1</strong>).</li>
        <li><strong>Rede de segurança (07h / 13h / 18h + 30 min):</strong> garante que agendamentos feitos por telefone/balcão entrem na fila e guias <em>Em Análise</em> sejam vigiadas até aprovar.</li>
      </ul>
    </div>
  </div>

  <div class="page-break"></div>

  <!-- SEÇÃO 4: MODOS DE OPERAÇÃO E OPÇÃO DE TESTE REAL -->
  <h2>4. Diferença entre os Modos de Operação &amp; Opção de Teste Real</h2>
  <p>
    Todo o processo funciona com <strong>documentos reais do Google Drive</strong> e nos <strong>portais verdadeiros dos convênios</strong>.
    A clínica pode operar em <strong>dois modos complementares</strong> — começando pelo teste assistido e avançando para o piloto automático 24/7:
  </p>

  <div class="two-col">
    <div class="box box-warn">
      <h3 style="margin-top:0;color:#92400e;">🧪 Modo 1 — Teste Real / Piloto Assistido</h3>
      <p style="font-size:8.7pt;color:#78350f;margin-bottom:6px;">
        <strong>Ideal para validação inicial com a diretoria e faturamento (1 paciente por vez).</strong>
      </p>
      <ul>
        <li>Conecta ao vivo no <strong>Google Drive real da clínica</strong> e lista os pacientes que já enviaram carteirinha (ou permite digitar uma carteirinha real na hora).</li>
        <li>Abre o navegador visível na tela no <strong>portal real do convênio</strong> (ex.: AMHP → AMHPTISS), faz login real e preenche todos os campos com os dados verdadeiros do paciente.</li>
        <li><strong>Duas travas de escolha na hora:</strong> <em>(1) Preencher tudo e pausar antes do clique final</em> para conferência visual, ou <em>(2) Preencher e emitir a guia real imediatamente</em>.</li>
        <li>Requisito para emissão real no AMHPTISS: <strong>1 carteirinha real</strong> de paciente agendado em convênio da AMHP (ex.: PROASA, BACEN, CARE PLUS, CASEC, PRÓ-SER).</li>
      </ul>
    </div>

    <div class="box box-safe">
      <h3 style="margin-top:0;color:#166534;">⚡ Modo 2 — Produção 100% por Eventos (Hermes 24/7)</h3>
      <p style="font-size:8.7pt;color:#14532d;margin-bottom:6px;">
        <strong>Operação definitiva no servidor dedicado da clínica — sem nenhum clique manual.</strong>
      </p>
      <ul>
        <li>Fica ativo 24 horas conectado ao Google Drive e recebendo eventos do AGS CRM via Webhook (<code>document.synced_to_drive</code>, <code>appointment.created</code>, <code>appointment.cancelled</code>).</li>
        <li>Chegou carteirinha nova ou agendamento novo → <strong>abre o portal do convênio específico automaticamente na hora</strong>.</li>
        <li>Emite a guia real em nome do paciente verdadeiro, acompanha até virar <strong>Autorizada</strong> e salva o PDF oficial de volta em <code>06_Guias_Autorizadas/</code> no Google Drive.</li>
        <li>Dispara <strong>notificação automática no WhatsApp e/ou E-mail</strong> da equipe para conferência, impressão ou arquivamento imediato.</li>
      </ul>
    </div>
  </div>

  <!-- SEÇÃO 5: MAPA DE PORTAIS E DOCUMENTOS -->
  <h2>5. Mapeamento dos Convênios e Portais Atendidos (Nova Gesta)</h2>
  <table>
    <thead>
      <tr>
        <th style="width:24%;">Portal / Motor</th>
        <th style="width:36%;">Convênios Cobertos</th>
        <th style="width:20%;">Credenciamento</th>
        <th style="width:20%;">Docs Exigidos</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td><strong>AMHPTISS</strong><br/><span style="font-size:8pt;color:#64748b;">amhptiss.amhp.com.br</span></td>
        <td>PROASA, BACEN, CARE PLUS, CASEC (CODEVASF), PRÓ-SER (STJ), NOTRE DAME, OMINT, TRT SAÚDE</td>
        <td>AMHP-DF (Dr. Marcondes)</td>
        <td>Carteirinha (+ Pedido p/ exame)</td>
      </tr>
      <tr>
        <td><strong>Benner Conecta AMHP</strong><br/><span style="font-size:8pt;color:#64748b;">portalconectasaude.com.br</span></td>
        <td>Senado Federal (SIS), STF-MED, TRE-SAÚDE, PMDF Saúde, CAMED, FAPES (BNDES), CONAB</td>
        <td>Via AMHP-DF</td>
        <td>Carteirinha (Consulta) / + Pedido (Exame)</td>
      </tr>
      <tr>
        <td><strong>INAS — GDF Saúde</strong><br/><span style="font-size:8pt;color:#64748b;">gdf.maida.health</span></td>
        <td>GDF Saúde (SP/SADT, ecografias e combos até 4 itens por guia + etapa Capturar/Executar)</td>
        <td>Nova Gesta + AMHP Solicitante</td>
        <td>Carteirinha + Pedido Médico assinado/carimbado</td>
      </tr>
      <tr>
        <td><strong>Benner WES</strong><br/><span style="font-size:8pt;color:#64748b;">Postal / Plan-Assiste / Caixa</span></td>
        <td>Postal Saúde (Correios), Plan-Assiste (MPU/MPF), Saúde Caixa (CEF)</td>
        <td>Direto Nova Gesta / AMHP (Caixa)</td>
        <td>Carteirinha (+ Pedido p/ SADT)</td>
      </tr>
      <tr>
        <td><strong>Portais Diretos</strong><br/><span style="font-size:8pt;color:#64748b;">TJDFT / Amil / PF / TST</span></td>
        <td>Pró-Saúde (TJDFT), Amil, PF Saúde (WebPlan), TST-Saúde</td>
        <td>Direto Nova Gesta / AMHP (PF)</td>
        <td>Carteirinha (+ Pedido p/ exame)</td>
      </tr>
    </tbody>
  </table>

  <!-- SEÇÃO 6: SEGURANÇA, LGPD E GUARDRAILS -->
  <h2>6. Segurança, LGPD e Travas Invioláveis da IA</h2>
  <div class="two-col">
    <div class="box box-safe">
      <h3 style="margin-top:0;color:#166534;">🔒 Privacidade &amp; LGPD</h3>
      <ul>
        <li><strong>Zero retenção no SaaS:</strong> o AGS CRM transfere os documentos direto para o Google Drive da clínica (OAuth 1-clique com conta da própria clínica).</li>
        <li><strong>Servidor dedicado por clínica:</strong> o Hermes + automação de guias roda em uma VPS exclusiva da clínica, totalmente isolada do servidor do SaaS e de outras clínicas.</li>
        <li><strong>Senhas nunca vão para a IA:</strong> o login nos portais é executado localmente pelo motor seguro; a IA só opera a navegação pós-login.</li>
      </ul>
    </div>

    <div class="box box-warn">
      <h3 style="margin-top:0;color:#92400e;">🛡️ Travas de Segurança nos Portais</h3>
      <ul>
        <li><strong>Proibido redefinir senhas:</strong> trava física no código impede qualquer clique em <em>"Esqueci minha senha"</em> ou alteração de senha (evita bloqueio da clínica na AMHP).</li>
        <li><strong>Pausa inteligente em CAPTCHA / 2FA:</strong> se um portal exigir código SMS ou CAPTCHA, o robô pausa na hora e avisa a equipe humana com print da tela.</li>
        <li><strong>Idempotência:</strong> o banco SQLite garante que nunca sejam emitidas duas guias duplicadas para o mesmo agendamento.</li>
      </ul>
    </div>
  </div>

  <!-- SEÇÃO 7: ROADMAP DE IMPLANTAÇÃO -->
  <h2>7. Plano de Implantação Segura na Clínica Nova Gesta</h2>
  <table>
    <thead>
      <tr>
        <th style="width:18%;">Fase</th>
        <th style="width:16%;">Status</th>
        <th style="width:66%;">Escopo e Entregas</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td><strong>Fase 1 — Base, Drive &amp; Portal Real</strong></td>
        <td><span class="pill pill-green">✅ CONCLUÍDA</span></td>
        <td>Integração 1-clique Google Drive ativa em produção na Nova Gesta (<code>Documentos pacientes</code>), salvamento automático do WhatsApp com OCR/Vision, Webhooks em tempo real no AGS CRM, Auditor Anti-Glosa e Agente IA validado no portal real AMHP/AMHPTISS.</td>
      </tr>
      <tr>
        <td><strong>Fase 2 — Piloto Assistido &amp; Hermes</strong></td>
        <td><span class="pill pill-blue">🚀 EM INÍCIO</span></td>
        <td>Teste real com 1 paciente agendado (Modo Assistido) + ativação da VPS dedicada da clínica com Hermes 24/7, emissão automática no AMHPTISS, salvamento dos PDFs autorizados em <code>06_Guias_Autorizadas/</code> e notificações automáticas no WhatsApp/E-mail da equipe.</td>
      </tr>
      <tr>
        <td><strong>Fase 3 — Escala Total</strong></td>
        <td><span class="pill pill-amber">⏳ PRÓXIMA</span></td>
        <td>Expansão para todos os 9 portais/15+ convênios, fechamento automático no iGUT Web (<code>Autorizado</code> + <code>Guias e Códigos</code> + anexo PDF) e resumo diário de faturamento às 18h.</td>
      </tr>
    </tbody>
  </table>

  <div class="footer">
    <div><strong>AEGIS Tecnologia</strong> — Plataforma Multi-Clínica de Atendimento IA &amp; Faturamento Autônomo</div>
    <div>Clínica Nova Gesta • Documento para Alinhamento Executivo</div>
  </div>

</body>
</html>
"""


async def main() -> None:
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(HTML_CONTENT, encoding="utf-8")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(OUT_HTML.as_uri(), wait_until="networkidle")
        await page.pdf(
            path=str(OUT_PDF),
            format="A4",
            print_background=True,
            margin={"top": "12mm", "right": "12mm", "bottom": "12mm", "left": "12mm"},
        )
        await browser.close()

    print(f"PDF_GENERATED={OUT_PDF}")
    print(f"PDF_SIZE_KB={round(OUT_PDF.stat().st_size / 1024, 1)}")


if __name__ == "__main__":
    asyncio.run(main())
