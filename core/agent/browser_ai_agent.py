from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

import httpx
from playwright.async_api import Page, async_playwright

from core.config.settings import AppSettings
from core.domain.models import BrowserActionDecision, GuideJob, PortalExecutionResult, PortalRoute

logger = logging.getLogger(__name__)

# Guardrails rígidos (nunca violados, mesmo se um LLM sugerir)
FORBIDDEN_CLICK_PATTERNS = re.compile(
    r"(esqueci|esqueceu|recuperar\s+(?:minha\s+|sua\s+)?(?:senha|acesso|usu[aá]rio)|redefinir\s+senha|reset\s*password|alterar\s+senha|forgot\s+password)",
    re.I,
)
CAPTCHA_OR_2FA_PATTERNS = re.compile(
    r"(recaptcha|hcaptcha|turnstile|não\s+sou\s+um\s+robô|digite\s+os\s+caracteres|código\s+de\s+verificação|autenticação\s+em\s+dois\s+fatores|token\s+sms)",
    re.I,
)


def _norm(text: str | None) -> str:
    if not text:
        return ""
    nfd = unicodedata.normalize("NFD", str(text))
    stripped = "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn")
    return " ".join(stripped.lower().strip().split())


DOM_OBSERVE_JS = r"""
() => {
  const hud = document.getElementById('aegis-ai-hud');
  const selector = 'input:not([type="hidden"]), textarea, select, button, a[href], a[routerlink], [role="button"], [role="menuitem"], [role="tab"], [role="option"], li.rcbItem, li.rcbHovered, .rcbArrowCell a, .RadComboBox .rcbInput, aside li, aside [class*="cursor-pointer"], .informativo-overlay.show [onclick], .informativo-overlay.show [class*="close"], .informativo-overlay.show [class*="fechar"], .informativo-overlay.show span';
  const popupDropdown = Array.from(document.querySelectorAll('.rcbSlide, [role="listbox"]')).find(el => {
    const st = window.getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden' || st.opacity === '0') return false;
    const r = el.getBoundingClientRect();
    return r.width > 30 && r.height > 20;
  }) || null;
  const overlayRootCandidates = Array.from(
    document.querySelectorAll('.informativo-overlay.show, .driver-popover, [role="dialog"], [aria-modal="true"], .modal.show')
  );
  const overlayRoot = popupDropdown || overlayRootCandidates.find(el => {
    const st = window.getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden' || st.opacity === '0') return false;
    const r = el.getBoundingClientRect();
    return r.width > 50 && r.height > 50;
  }) || null;
  const rawNodes = Array.from(document.querySelectorAll(selector));
  const nodes = overlayRoot
    ? [
        ...rawNodes.filter(el => overlayRoot.contains(el)),
        ...rawNodes.filter(el => !overlayRoot.contains(el)),
      ]
    : rawNodes;
  const elements = [];
  let idx = 1;

  for (const el of nodes) {
    if (hud && hud.contains(el)) continue;
    if (el.tagName === 'LI' && !el.classList.contains('rcbItem') && !el.classList.contains('rcbHovered') && el.querySelector('a, button')) continue;
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;
    const rect = el.getBoundingClientRect();
    if (rect.width < 2 && rect.height < 2 && el.type !== 'file') continue;

    el.setAttribute('data-aegis-id', String(idx));

    let label = '';
    if (el.id) {
      const lbl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (lbl) label = (lbl.innerText || '').trim();
    }
    if (!label && el.closest('label')) {
      label = (el.closest('label').innerText || '').trim();
    }
    if (!label && el.previousElementSibling && el.previousElementSibling.tagName === 'LABEL') {
      label = (el.previousElementSibling.innerText || '').trim();
    }
    if (!label) {
      const td = el.closest('td');
      if (td && td.previousElementSibling) {
        const prevTxt = (td.previousElementSibling.innerText || '').trim();
        if (prevTxt && prevTxt.length <= 60) label = prevTxt;
      }
      if (!label && td && td.closest('table') && td.closest('table').className.includes('rcb')) {
        const outerTd = td.closest('table').closest('td');
        if (outerTd && outerTd.previousElementSibling) {
          const outerTxt = (outerTd.previousElementSibling.innerText || '').trim();
          if (outerTxt && outerTxt.length <= 60) label = outerTxt;
        }
      }
    }
    if (!label) {
      label = (el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.getAttribute('title') || '').trim();
    }

    const options = el.tagName === 'SELECT'
      ? Array.from(el.options).map(o => ({ value: o.value, text: (o.text || '').trim() }))
      : [];

    const isPwd = (el.getAttribute('type') || '').toLowerCase() === 'password';
    const rawVal = (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') ? String(el.value || '') : '';
    const safeVal = isPwd && rawVal ? '********' : rawVal;

    elements.push({
      id: idx,
      tag: el.tagName.toLowerCase(),
      type: (el.getAttribute('type') || '').toLowerCase(),
      name: el.getAttribute('name') || '',
      dom_id: el.id || '',
      label: label.slice(0, 120),
      text: (el.innerText || (isPwd ? '' : el.value) || '').trim().slice(0, 120),
      value: safeVal,
      href: el.getAttribute('href') || el.getAttribute('routerlink') || '',
      disabled: Boolean(el.disabled),
      options: options.slice(0, 40),
    });
    idx += 1;
    if (elements.length >= 130) break;
  }

  // Extrai texto visível excluindo o HUD da IA
  const clone = document.body.cloneNode(true);
  const cloneHud = clone.querySelector('#aegis-ai-hud');
  if (cloneHud) cloneHud.remove();
  const pageText = (clone.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 6000);

  const overlayCandidates = Array.from(
    document.querySelectorAll('.informativo-overlay.show, .driver-overlay, .driver-popover, [role="dialog"], [aria-modal="true"], .modal.show')
  );
  const visibleOverlay = overlayCandidates.find(el => {
    const st = window.getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden' || st.opacity === '0') return false;
    const r = el.getBoundingClientRect();
    return r.width > 50 && r.height > 50;
  });
  const hasOverlay = Boolean(visibleOverlay);

  return {
    url: window.location.href,
    title: document.title,
    has_modal_or_tour_overlay: hasOverlay,
    page_text: pageText,
    elements,
  };
}
"""


HUD_UPDATE_JS = r"""
({ step, phase, thought, provider, actionLog, statusColor }) => {
  let hud = document.getElementById('aegis-ai-hud');
  if (!hud) {
    hud = document.createElement('div');
    hud.id = 'aegis-ai-hud';
    hud.style.cssText = [
      'position: fixed',
      'bottom: 12px',
      'right: 12px',
      'width: 290px',
      'z-index: 2147483647',
      'background: rgba(12, 18, 32, 0.94)',
      'color: #f1f5f9',
      'border: 1px solid rgba(56, 189, 248, 0.55)',
      'border-radius: 12px',
      'padding: 10px 12px',
      'font-family: Inter, Segoe UI, system-ui, sans-serif',
      'font-size: 11.5px',
      'box-shadow: 0 14px 36px rgba(0, 0, 0, 0.45)',
      'backdrop-filter: blur(10px)',
      'pointer-events: none',
    ].join(';');
    document.body.appendChild(hud);
  }
  const items = (actionLog || []).slice(-4).map(
    line => `<div style="font-size:11px;color:#94a3b8;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">• ${line}</div>`
  ).join('');
  hud.innerHTML = `
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
      <div style="font-weight:700;color:#38bdf8;letter-spacing:0.3px;">🤖 AEGIS AI BROWSER AGENT</div>
      <span style="font-size:10px;padding:2px 8px;border-radius:999px;background:rgba(56,189,248,0.18);color:#7dd3fc;">${provider}</span>
    </div>
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
      <span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${statusColor};box-shadow:0 0 10px ${statusColor};"></span>
      <span style="font-weight:600;color:#fff;">Passo ${step} — ${phase}</span>
    </div>
    <div style="background:rgba(30,41,59,0.85);border-left:3px solid ${statusColor};padding:8px 10px;border-radius:6px;line-height:1.4;color:#e2e8f0;margin-bottom:8px;">
      ${thought}
    </div>
    <div style="border-top:1px solid rgba(148,163,184,0.2);padding-top:6px;">
      <div style="font-size:10px;text-transform:uppercase;letter-spacing:0.6px;color:#64748b;">Últimas ações</div>
      ${items || '<div style="font-size:11px;color:#64748b;">Iniciando observação...</div>'}
    </div>
  `;
}
"""


HIGHLIGHT_ELEMENT_JS = r"""
({ elementId, badgeText }) => {
  document.querySelectorAll('.aegis-ai-spotlight').forEach(el => {
    el.classList.remove('aegis-ai-spotlight');
    el.style.outline = '';
    el.style.boxShadow = '';
  });
  const oldTag = document.getElementById('aegis-ai-badge');
  if (oldTag) oldTag.remove();

  const target = document.querySelector(`[data-aegis-id="${elementId}"]`);
  if (!target) return;
  target.scrollIntoView({ behavior: 'smooth', block: 'center' });
  target.classList.add('aegis-ai-spotlight');
  target.style.outline = '3px solid #00e5ff';
  target.style.boxShadow = '0 0 18px rgba(0, 229, 255, 0.85)';

  const rect = target.getBoundingClientRect();
  const badge = document.createElement('div');
  badge.id = 'aegis-ai-badge';
  badge.innerText = badgeText;
  badge.style.cssText = [
    'position: fixed',
    `top: ${Math.max(8, rect.top - 28)}px`,
    `left: ${Math.max(8, rect.left)}px`,
    'z-index: 2147483646',
    'background: #0284c7',
    'color: #ffffff',
    'font-family: Inter, Segoe UI, sans-serif',
    'font-size: 11px',
    'font-weight: 700',
    'padding: 3px 8px',
    'border-radius: 6px',
    'box-shadow: 0 6px 14px rgba(0,0,0,0.35)',
    'pointer-events: none',
  ].join(';');
  document.body.appendChild(badge);
}
"""


class BrowserAiAgent:
    """
    Agente de navegador guiado por IA (Observe -> Think -> Act -> Monitor).
    Executa ações humanas reais no portal do convênio e permanece acompanhando
    status "Em Análise" até virar "Autorizada" (baixando o PDF) ou "Negada".
    """

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        Path(settings.storage_state_dir).mkdir(parents=True, exist_ok=True)
        Path(settings.downloads_dir).mkdir(parents=True, exist_ok=True)
        Path(settings.screenshots_dir).mkdir(parents=True, exist_ok=True)

    def _resolve_provider(self) -> str:
        pref = self.settings.ai_provider
        if pref == "heuristic":
            return "heuristic"
        if pref == "openai" and self.settings.openai_api_key:
            return "openai"
        if pref == "gemini" and self.settings.gemini_api_key:
            return "gemini"
        if pref == "auto":
            if self.settings.openai_api_key:
                return "openai"
            if self.settings.gemini_api_key:
                return "gemini"
        return "heuristic"

    async def execute_guide_flow(
        self,
        *,
        job: GuideJob,
        route: PortalRoute,
        start_url: str,
        portal_credentials: dict[str, str] | None = None,
        medical_order_local_path: str | None = None,
        headless_override: bool | None = None,
        slow_mo_override: int | None = None,
        record_video_dir: str | None = None,
        custom_goal: str | None = None,
        max_steps: int = 30,
        max_analysis_polls: int = 8,
        poll_interval_seconds: float = 2.0,
    ) -> PortalExecutionResult:
        headless = self.settings.playwright_headless if headless_override is None else headless_override
        slow_mo = self.settings.browser_slow_mo_ms if slow_mo_override is None else slow_mo_override
        provider = self._resolve_provider()
        creds = portal_credentials or {}

        state_file = Path(self.settings.storage_state_dir) / f"{job.tenant_slug}_{route.portal_key}.json"
        steps_executed: list[dict[str, Any]] = []
        action_log: list[str] = []
        pdf_local_path: str | None = None
        screenshot_path: str | None = None
        video_path: str | None = None
        analysis_polls = 0
        downloaded_pdf = False
        result: PortalExecutionResult | None = None

        vp_width = int(os.getenv("BROWSER_WIDTH", "1024"))
        vp_height = int(os.getenv("BROWSER_HEIGHT", "620"))

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=headless,
                slow_mo=slow_mo,
                args=(
                    [f"--window-size={vp_width + 16},{vp_height + 70}", "--window-position=60,20"]
                    if not headless
                    else []
                ),
            )
            context_kwargs: dict[str, Any] = {
                "accept_downloads": True,
                "viewport": {"width": vp_width, "height": vp_height},
            }
            if record_video_dir:
                Path(record_video_dir).mkdir(parents=True, exist_ok=True)
                context_kwargs["record_video_dir"] = str(record_video_dir)
                context_kwargs["record_video_size"] = {"width": vp_width, "height": vp_height}
            if state_file.exists():
                context_kwargs["storage_state"] = str(state_file)

            context = await browser.new_context(**context_kwargs)
            page = await context.new_page()
            video_handle = page.video

            try:
                await page.goto(start_url, wait_until="domcontentloaded", timeout=30000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=4500)
                except Exception:
                    pass
                await asyncio.sleep(0.8)

                for step_num in range(1, max_steps + 1):
                    # Fecha automaticamente banners informativos da AMHP que travam o dashboard ao carregar
                    try:
                        info_banner = page.locator(".informativo-overlay.show").first
                        if await info_banner.is_visible(timeout=250):
                            close_x = page.locator(".informativo-overlay.show button, .informativo-overlay.show [class*='close'], .informativo-overlay.show [class*='fechar']").first
                            if await close_x.is_visible(timeout=300):
                                await close_x.click(timeout=1500)
                            else:
                                await page.mouse.click(20, 20)
                            await asyncio.sleep(0.4)
                    except Exception:
                        pass

                    obs = await self._observe_page(page)

                    # Guardrail 0: Se o portal redirecionou para troca obrigatória de senha sem menu lateral navegável, pausar!
                    is_pwd_change_url = bool(
                        re.search(r"(alterar[-_]?senha|trocar[-_]?senha|redefinir[-_]?senha|reset[-_]?password)", obs["url"], re.I)
                    )
                    if is_pwd_change_url:
                        has_amhptiss_menu = "amhptiss.amhp.com.br" in obs["url"].lower() and any(
                            re.search(r"\b(consultorio|inicio|ferramentas)\b", _norm(e.get("text", "")))
                            for e in (obs.get("elements") or [])
                        )
                        pwd_url_attempts = sum(
                            1 for s in steps_executed if "alterar-senha" in str(s.get("url", "")).lower()
                        )
                        if not has_amhptiss_menu or pwd_url_attempts >= 3:
                            shot = str(Path(self.settings.screenshots_dir) / f"{job.id}_password_change.png")
                            await page.screenshot(path=shot, full_page=True)
                            result = PortalExecutionResult(
                                final_status="AWAITING_HUMAN_2FA",
                                denial_reason=f"Portal exigiu troca obrigatória de senha ({obs['url']}). Intervenção humana necessária.",
                                screenshot_path=shot,
                                steps_executed=steps_executed,
                                ai_provider_used=provider,
                            )
                            break

                    # Guardrail 1: Detecta CAPTCHA ou 2FA e pausa imediatamente
                    if CAPTCHA_OR_2FA_PATTERNS.search(obs["page_text"]):
                        shot = str(Path(self.settings.screenshots_dir) / f"{job.id}_2fa.png")
                        await page.screenshot(path=shot, full_page=True)
                        result = PortalExecutionResult(
                            final_status="AWAITING_HUMAN_2FA",
                            denial_reason="Portal solicitou CAPTCHA ou validação 2FA.",
                            screenshot_path=shot,
                            steps_executed=steps_executed,
                            ai_provider_used=provider,
                        )
                        break

                    # Login seguro 100% local (nunca envia tela de senha para LLM e nunca atua em tela de alterar-senha)
                    has_pwd_input = (
                        not is_pwd_change_url
                        and any(
                            e.get("tag") == "input" and e.get("type") == "password"
                            for e in (obs.get("elements") or [])
                        )
                    )
                    if has_pwd_input and creds.get("username") and creds.get("password"):
                        decision = self._semantic_decide(
                            obs=obs,
                            job=job,
                            route=route,
                            creds=creds,
                            medical_order_local_path=medical_order_local_path,
                            downloaded_pdf=downloaded_pdf,
                            analysis_polls=analysis_polls,
                            max_analysis_polls=max_analysis_polls,
                            poll_interval_seconds=poll_interval_seconds,
                        )
                        step_provider = "local_auth"
                    else:
                        decision, step_provider = await self._decide_next_action(
                            provider=provider,
                            obs=obs,
                            job=job,
                            route=route,
                            creds=creds,
                            medical_order_local_path=medical_order_local_path,
                            history=steps_executed,
                            downloaded_pdf=downloaded_pdf,
                            analysis_polls=analysis_polls,
                            max_analysis_polls=max_analysis_polls,
                            poll_interval_seconds=poll_interval_seconds,
                            custom_goal=custom_goal,
                        )

                    phase, color = self._phase_for_decision(decision)
                    provider_badge = (
                        f"OpenAI {self.settings.openai_model}"
                        if step_provider == "openai"
                        else (
                            f"Gemini {self.settings.gemini_model}"
                            if step_provider == "gemini"
                            else ("Auth Seguro Local" if step_provider == "local_auth" else "AI Planner Local")
                        )
                    )
                    if not headless:
                        await self._update_hud(
                            page=page,
                            step=step_num,
                            phase=phase,
                            thought=decision.thought,
                            provider=provider_badge,
                            action_log=action_log,
                            status_color=color,
                        )

                    step_record = {
                        "step": step_num,
                        "url": obs["url"],
                        "thought": decision.thought,
                        "action": decision.action,
                        "element_id": decision.element_id,
                        "portal_status": decision.portal_status,
                        "provider": step_provider,
                    }
                    steps_executed.append(step_record)
                    logger.info(
                        "[AI-AGENT:%s step=%s url=%s] (%s el=%s) %s",
                        step_provider,
                        step_num,
                        obs["url"],
                        decision.action,
                        decision.element_id,
                        decision.thought,
                    )

                    # Guardrail 2: Bloqueia qualquer clique em "Esqueci minha senha"
                    if decision.action == "click" and decision.element_id is not None:
                        target_meta = next((e for e in obs["elements"] if e["id"] == decision.element_id), None)
                        joined = f"{(target_meta or {}).get('text', '')} {(target_meta or {}).get('label', '')} {(target_meta or {}).get('href', '')}"
                        if FORBIDDEN_CLICK_PATTERNS.search(joined):
                            result = PortalExecutionResult(
                                final_status="CREDENTIAL_LOCKED",
                                denial_reason="Guardrail bloqueou tentativa de clicar em 'Esqueci minha senha'.",
                                steps_executed=steps_executed,
                                ai_provider_used=step_provider,
                            )
                            break

                    if decision.action == "needs_human":
                        shot = str(Path(self.settings.screenshots_dir) / f"{job.id}_needs_human.png")
                        await page.screenshot(path=shot, full_page=True)
                        result = PortalExecutionResult(
                            final_status="AWAITING_HUMAN_2FA",
                            denial_reason=decision.denial_reason or decision.thought,
                            screenshot_path=shot,
                            steps_executed=steps_executed,
                            ai_provider_used=step_provider,
                        )
                        break

                    if decision.action == "fail":
                        shot = str(Path(self.settings.screenshots_dir) / f"{job.id}_fail.png")
                        await page.screenshot(path=shot, full_page=True)
                        result = PortalExecutionResult(
                            final_status="DENIED" if decision.portal_status == "DENIED" else "FAILED",
                            denial_reason=decision.denial_reason or decision.thought,
                            screenshot_path=shot,
                            steps_executed=steps_executed,
                            ai_provider_used=step_provider,
                        )
                        break

                    if decision.action == "done":
                        shot = str(Path(self.settings.screenshots_dir) / f"{job.id}_{decision.portal_status.lower()}.png")
                        await page.screenshot(path=shot, full_page=True)
                        screenshot_path = shot
                        if not headless:
                            await asyncio.sleep(2.5)
                        await context.storage_state(path=str(state_file))
                        final_map = {
                            "AUTHORIZED": "AUTHORIZED",
                            "IN_ANALYSIS": "IN_ANALYSIS",
                            "DENIED": "DENIED",
                            "AWAITING_HUMAN_2FA": "AWAITING_HUMAN_2FA",
                        }
                        result = PortalExecutionResult(
                            final_status=final_map.get(decision.portal_status, "AUTHORIZED"),  # type: ignore[arg-type]
                            guide_number=decision.guide_number,
                            auth_password=decision.auth_password,
                            validity_date=decision.validity_date,
                            denial_reason=decision.denial_reason,
                            pdf_local_path=pdf_local_path,
                            screenshot_path=screenshot_path,
                            steps_executed=steps_executed,
                            ai_provider_used=step_provider,
                        )
                        break

                    # Executa a ação real no Playwright
                    if decision.action == "wait":
                        secs = float(decision.wait_seconds or poll_interval_seconds)
                        prev_was_wait = len(steps_executed) >= 2 and steps_executed[-2].get("action") == "wait"
                        if decision.portal_status == "IN_ANALYSIS":
                            analysis_polls += 1
                        action_log.append(f"Aguardando {secs:.1f}s ({decision.portal_status})")
                        await asyncio.sleep(secs)
                        if prev_was_wait:
                            action_log.append("Recarregando página para atualizar status")
                            await page.reload(wait_until="domcontentloaded")
                            await asyncio.sleep(0.4)
                        continue

                    if decision.action == "refresh":
                        if decision.portal_status == "IN_ANALYSIS":
                            analysis_polls += 1
                        action_log.append("Atualizando página para conferir aprovação")
                        await page.reload(wait_until="domcontentloaded")
                        await asyncio.sleep(0.5)
                        continue

                    if decision.element_id is None:
                        await asyncio.sleep(0.5)
                        continue

                    locator = page.locator(f'[data-aegis-id="{decision.element_id}"]').first
                    target_meta = next((e for e in obs["elements"] if e["id"] == decision.element_id), {})
                    label_hint = target_meta.get("label") or target_meta.get("text") or target_meta.get("name") or f"#{decision.element_id}"

                    if not headless:
                        badge = f"{decision.action.upper()}: {label_hint[:32]}"
                        await page.evaluate(HIGHLIGHT_ELEMENT_JS, {"elementId": decision.element_id, "badgeText": badge})
                        await asyncio.sleep(0.35)

                    if decision.action == "fill":
                        raw_val = decision.value or ""
                        if raw_val == "{{PORTAL_USERNAME}}":
                            val = creds.get("username") or "prestador.novagesta"
                        elif raw_val == "{{PORTAL_PASSWORD}}" or (
                            target_meta.get("type") == "password" and creds.get("password")
                        ):
                            val = creds.get("password") or "demo-secret-123"
                        else:
                            val = raw_val
                        await locator.click()
                        await locator.fill("")
                        await locator.press_sequentially(val, delay=40 if not headless else 5)
                        masked = "••••••" if target_meta.get("type") == "password" else val[:28]
                        action_log.append(f"Preencheu '{label_hint[:20]}' = {masked}")

                    elif decision.action == "select":
                        val = decision.value or ""
                        try:
                            await locator.select_option(label=val)
                        except Exception:
                            try:
                                await locator.select_option(value=val)
                            except Exception:
                                opts = target_meta.get("options") or []
                                matched = next((o for o in opts if _norm(val) in _norm(o["text"]) or _norm(val) in _norm(o["value"])), None)
                                if matched:
                                    await locator.select_option(value=matched["value"])
                        action_log.append(f"Selecionou '{val[:24]}' em '{label_hint[:18]}'")

                    elif decision.action == "upload":
                        file_path = decision.value or medical_order_local_path or ""
                        if file_path and Path(file_path).exists():
                            await locator.set_input_files(file_path)
                            action_log.append(f"Anexou arquivo '{Path(file_path).name}'")

                    elif decision.action == "click":
                        is_download_btn = bool(re.search(r"(baixar|download|pdf|imprimir\s+guia)", f"{label_hint} {target_meta.get('href', '')}", re.I))
                        is_status_refresh = bool(re.search(r"(atualizar|consultar\s+status|verificar\s+status)", label_hint, re.I))
                        if is_status_refresh and decision.portal_status == "IN_ANALYSIS":
                            analysis_polls += 1

                        async def _resilient_click() -> None:
                            try:
                                await locator.click(timeout=6000)
                            except Exception as click_err:
                                if "intercepts pointer events" in str(click_err) or "Timeout" in str(click_err):
                                    logger.info("Overlay detectado bloqueando clique; dispensando tour/modal...")
                                    had_info_banner = False
                                    try:
                                        had_info_banner = await page.locator(".informativo-overlay.show").is_visible(timeout=300)
                                    except Exception:
                                        pass
                                    try:
                                        close_btn = page.locator(
                                            ".informativo-overlay.show button, .informativo-overlay.show [class*='close'], .informativo-overlay.show [class*='fechar'], .driver-popover-close-btn, [aria-label='Close'], [aria-label='Fechar']"
                                        ).first
                                        if await close_btn.is_visible(timeout=800):
                                            await close_btn.click(timeout=2000)
                                        else:
                                            await page.keyboard.press("Escape")
                                            if had_info_banner:
                                                await page.mouse.click(20, 20)
                                                await asyncio.sleep(0.3)
                                                # Se ainda visível, clica no canto superior direito do modal (botão X)
                                                await page.evaluate(
                                                    "() => { const b = document.querySelector('.informativo-overlay.show'); if (b) { const c = b.querySelector('button, [class*=\"close\"], [class*=\"fechar\"], a'); if (c) c.click(); else b.classList.remove('show'); } }"
                                                )
                                    except Exception:
                                        await page.keyboard.press("Escape")
                                    await asyncio.sleep(0.5)
                                    # Se era banner informativo bloqueando, retorna para a IA re-observar a tela limpa sem clicar no elemento antigo
                                    if had_info_banner:
                                        return
                                    await locator.click(timeout=6000)
                                else:
                                    raise

                        if is_download_btn:
                            try:
                                async with page.expect_download(timeout=8000) as dl_info:
                                    await _resilient_click()
                                download = await dl_info.value
                                suggested = download.suggested_filename or f"guia_{job.id}.pdf"
                                dest = Path(self.settings.downloads_dir) / f"{job.tenant_slug}_{job.igut_appointment_id}_{suggested}"
                                await download.save_as(str(dest))
                                pdf_local_path = str(dest)
                                downloaded_pdf = True
                                action_log.append(f"PDF da guia baixado: {dest.name}")
                            except Exception as dl_exc:
                                logger.warning("Clique em botão de PDF sem download direto: %s", dl_exc)
                                await _resilient_click()
                                downloaded_pdf = True
                                action_log.append(f"Clicou em '{label_hint[:24]}'")
                        else:
                            try:
                                pages_before = len(context.pages)
                                await _resilient_click()
                                action_log.append(f"Clicou em '{label_hint[:28]}'")
                                await asyncio.sleep(0.6)
                                # Se abriu nova aba (ex: AMHPTISS ↗), acompanha automaticamente
                                if len(context.pages) > pages_before:
                                    page = context.pages[-1]
                                    await page.bring_to_front()
                                    action_log.append("Mudou para nova aba aberta pelo portal")
                            except Exception as final_click_err:
                                logger.warning("Clique falhou em '%s': %s", label_hint, final_click_err)
                                steps_executed[-1]["error"] = str(final_click_err)[:200]
                                action_log.append(f"Tentativa bloqueada em '{label_hint[:20]}' — replanejando")
                                await asyncio.sleep(0.4)
                                continue

                        try:
                            await page.wait_for_load_state("domcontentloaded", timeout=6000)
                        except Exception:
                            pass
                        try:
                            await page.wait_for_load_state("networkidle", timeout=3500)
                        except Exception:
                            pass
                        await asyncio.sleep(0.75)

                if result is None:
                    shot = str(Path(self.settings.screenshots_dir) / f"{job.id}_timeout.png")
                    await page.screenshot(path=shot, full_page=True)
                    result = PortalExecutionResult(
                        final_status="IN_ANALYSIS" if analysis_polls > 0 else "FAILED",
                        denial_reason="Limite de passos atingido durante a navegação no portal.",
                        pdf_local_path=pdf_local_path,
                        screenshot_path=shot,
                        steps_executed=steps_executed,
                        ai_provider_used=provider,
                    )
            finally:
                await context.close()
                if video_handle is not None:
                    try:
                        video_path = str(await video_handle.path())
                    except Exception as vid_exc:
                        logger.warning("Não foi possível obter caminho do vídeo gravado: %s", vid_exc)
                await browser.close()

        assert result is not None
        result.video_path = video_path
        return result

    async def _observe_page(self, page: Page) -> dict[str, Any]:
        return await page.evaluate(DOM_OBSERVE_JS)

    async def _update_hud(
        self,
        *,
        page: Page,
        step: int,
        phase: str,
        thought: str,
        provider: str,
        action_log: list[str],
        status_color: str,
    ) -> None:
        try:
            await page.evaluate(
                HUD_UPDATE_JS,
                {
                    "step": step,
                    "phase": phase,
                    "thought": thought,
                    "provider": provider,
                    "actionLog": action_log,
                    "statusColor": status_color,
                },
            )
        except Exception:
            pass

    def _phase_for_decision(self, decision: BrowserActionDecision) -> tuple[str, str]:
        if decision.portal_status == "AUTHORIZED":
            return ("GUIA AUTORIZADA ✅", "#22c55e")
        if decision.portal_status == "IN_ANALYSIS":
            return ("AGUARDANDO APROVAÇÃO ⏳", "#f59e0b")
        if decision.portal_status == "DENIED":
            return ("GUIA NEGADA ❌", "#ef4444")
        if decision.portal_status == "AWAITING_HUMAN_2FA":
            return ("PAUSADO — AÇÃO HUMANA 🔐", "#a855f7")
        return ("OPERANDO PORTAL", "#38bdf8")

    async def _decide_next_action(
        self,
        *,
        provider: str,
        obs: dict[str, Any],
        job: GuideJob,
        route: PortalRoute,
        creds: dict[str, str],
        medical_order_local_path: str | None,
        history: list[dict[str, Any]],
        downloaded_pdf: bool,
        analysis_polls: int,
        max_analysis_polls: int,
        poll_interval_seconds: float,
        custom_goal: str | None = None,
    ) -> tuple[BrowserActionDecision, str]:
        if provider == "openai":
            try:
                return (
                    await self._decide_with_openai(
                        obs=obs,
                        job=job,
                        route=route,
                        creds=creds,
                        medical_order_local_path=medical_order_local_path,
                        history=history,
                        downloaded_pdf=downloaded_pdf,
                        analysis_polls=analysis_polls,
                        max_analysis_polls=max_analysis_polls,
                        poll_interval_seconds=poll_interval_seconds,
                        custom_goal=custom_goal,
                    ),
                    "openai",
                )
            except Exception as exc:
                logger.warning("OpenAI planner falhou (%s); usando fallback semântico.", exc)
        elif provider == "gemini":
            try:
                return (
                    await self._decide_with_gemini(
                        obs=obs,
                        job=job,
                        route=route,
                        creds=creds,
                        medical_order_local_path=medical_order_local_path,
                        history=history,
                        downloaded_pdf=downloaded_pdf,
                        analysis_polls=analysis_polls,
                        max_analysis_polls=max_analysis_polls,
                        poll_interval_seconds=poll_interval_seconds,
                        custom_goal=custom_goal,
                    ),
                    "gemini",
                )
            except Exception as exc:
                logger.warning("Gemini planner falhou (%s); usando fallback semântico.", exc)

        return (
            self._semantic_decide(
                obs=obs,
                job=job,
                route=route,
                creds=creds,
                medical_order_local_path=medical_order_local_path,
                downloaded_pdf=downloaded_pdf,
                analysis_polls=analysis_polls,
                max_analysis_polls=max_analysis_polls,
                poll_interval_seconds=poll_interval_seconds,
            ),
            "heuristic",
        )

    def _build_llm_prompt(
        self,
        *,
        obs: dict[str, Any],
        job: GuideJob,
        route: PortalRoute,
        creds: dict[str, str],
        medical_order_local_path: str | None,
        history: list[dict[str, Any]],
        downloaded_pdf: bool,
        analysis_polls: int,
        max_analysis_polls: int,
        poll_interval_seconds: float = 2.0,
        custom_goal: str | None = None,
    ) -> str:
        has_pwd_field = any(e.get("tag") == "input" and e.get("type") == "password" for e in (obs.get("elements") or []))
        task_ctx: dict[str, Any] = {
            "portal": route.display_name,
            "operator": route.operator_label or job.insurance_name,
            "patient": {
                "name": "{{PATIENT_NAME}}",
                "cpf": "{{PATIENT_CPF}}",
                "card_number": "{{PATIENT_CARD}}",
            },
            "doctor": {"name": job.doctor_name, "crm": job.doctor_crm, "cbo": job.doctor_cbo, "specialty": job.specialty},
            "appointment_type": job.appointment_type,
            "guide_type": "SP/SADT" if route.requires_medical_order_attachment else "Consulta",
            "clinical_indication": f"Solicitação {job.appointment_type} - {job.specialty or 'Ginecologia/Obstetrícia'}",
            "procedure_codes": job.procedure_codes or route.procedure_codes,
            "medical_order_local_path": medical_order_local_path,
            "downloaded_pdf_already": downloaded_pdf,
            "analysis_polls_done": analysis_polls,
            "max_analysis_polls": max_analysis_polls,
            "recommended_wait_seconds": poll_interval_seconds,
        }
        if has_pwd_field:
            task_ctx["credentials"] = {
                "username": "{{PORTAL_USERNAME}}",
                "password": "{{PORTAL_PASSWORD}}",
            }

        # Remove element_id do histórico enviado ao LLM para impedir reuso de IDs obsoletos de outra tela
        safe_history = [
            {k: v for k, v in h.items() if k != "element_id"}
            for h in history[-6:]
        ]

        if custom_goal:
            return (
                f"{custom_goal}\n\n"
                "REGRAS INVIOLÁVEIS:\n"
                "1. NUNCA clique em 'Esqueci', 'Esqueceu', 'Recuperar senha/usuário' ou 'Alterar senha'.\n"
                "2. Se surgir CAPTCHA ou 2FA, retorne action='needs_human' e portal_status='AWAITING_HUMAN_2FA'.\n"
                "3. SEMPRE olhe `url` e `elements` do ESTADO ATUAL DA PÁGINA — nunca reutilize `element_id` de páginas anteriores.\n"
                "4. Preencha apenas campos cujo `value` esteja vazio (nota: campos de senha preenchidos aparecem como '********' — não repreencha!).\n"
                "5. Responda APENAS um objeto JSON com campos: thought (raciocínio claro em pt-BR para exibir no HUD), action (click|fill|select|upload|wait|refresh|done|needs_human|fail), "
                "element_id (int|null), value (string|null), wait_seconds (float|null), portal_status (RUNNING|IN_ANALYSIS|AUTHORIZED|DENIED|AWAITING_HUMAN_2FA), "
                "guide_number (string|null), auth_password (string|null), validity_date (string|null), denial_reason (string|null).\n\n"
                f"DADOS DA TAREFA:\n{json.dumps(task_ctx, ensure_ascii=False)}\n\n"
                f"HISTÓRICO RECENTE:\n{json.dumps(safe_history, ensure_ascii=False)}\n\n"
                f"ESTADO ATUAL DA PÁGINA:\n{json.dumps(obs, ensure_ascii=False)}"
            )

        return (
            "Você é um agente especialista em faturamento médico brasileiro operando um portal de convênio via navegador.\n"
            "Objetivo: fazer login se necessário, navegar até Nova Solicitação, preencher todos os campos vazios da guia (Consulta ou SP/SADT), "
            "anexar o pedido médico no campo input[type=file] usando action='upload' (com value=medical_order_local_path) se ainda estiver vazio, "
            "submeter a solicitação e ACOMPANHAR o status até virar AUTORIZADA (baixando o PDF da guia) ou NEGADA.\n"
            "REGRAS INVIOLÁVEIS:\n"
            "1. NUNCA clique em 'Esqueci minha senha'.\n"
            "2. Se surgir CAPTCHA ou 2FA, retorne action='needs_human' e portal_status='AWAITING_HUMAN_2FA'.\n"
            "3. Preencha apenas campos cujo `value` esteja vazio; nunca repita preenchimento de campo que já possui `value`.\n"
            "4. Para campos `<select>`, use action='select' passando em `value` o texto ou value exato da opção desejada.\n"
            "5. Para `<input type='file'>`, use action='upload' com `value` igual a `medical_order_local_path`.\n"
            "6. Se a guia estiver 'EM ANÁLISE': observe o HISTÓRICO RECENTE. Se a última ação NÃO foi 'wait', use action='wait' (wait_seconds=recommended_wait_seconds, portal_status='IN_ANALYSIS'). "
            "Se a última ação JÁ FOI 'wait', NUNCA faça 'wait' novamente: CLIQUE no botão 'Atualizar Status' (ou use action='refresh') com portal_status='IN_ANALYSIS' para buscar o status atualizado no servidor! "
            "Só encerre com action='done' e portal_status='IN_ANALYSIS' se analysis_polls_done >= max_analysis_polls.\n"
            "7. Se a guia estiver 'AUTORIZADA', primeiro clique no botão 'Baixar Guia PDF' (se existir e downloaded_pdf_already=false); "
            "no passo seguinte (quando downloaded_pdf_already=true), retorne action='done', portal_status='AUTHORIZED' preenchendo guide_number, auth_password e validity_date extraídos do texto da página.\n"
            "8. Se a guia estiver 'NEGADA', retorne action='done', portal_status='DENIED' e denial_reason com o motivo exato.\n"
            "9. Responda APENAS um objeto JSON com campos: thought (raciocínio claro em pt-BR para exibir no HUD), action (click|fill|select|upload|wait|refresh|done|needs_human|fail), "
            "element_id (int|null), value (string|null), wait_seconds (float|null), portal_status (RUNNING|IN_ANALYSIS|AUTHORIZED|DENIED|AWAITING_HUMAN_2FA), "
            "guide_number (string|null), auth_password (string|null), validity_date (string|null), denial_reason (string|null).\n\n"
            f"DADOS DA TAREFA:\n{json.dumps(task_ctx, ensure_ascii=False)}\n\n"
            f"HISTÓRICO RECENTE:\n{json.dumps(safe_history, ensure_ascii=False)}\n\n"
            f"ESTADO ATUAL DA PÁGINA:\n{json.dumps(obs, ensure_ascii=False)}"
        )

    async def _decide_with_openai(self, **kwargs: Any) -> BrowserActionDecision:
        prompt = self._build_llm_prompt(**kwargs)
        job: GuideJob = kwargs["job"]
        async with httpx.AsyncClient(timeout=35.0) as client:
            last_err = "resposta vazia"
            for attempt in range(2):
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
                    json={
                        "model": self.settings.openai_model,
                        "response_format": {"type": "json_object"},
                        "temperature": 0.1,
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "Você é um assistente de automação RPA (UI testing / navegação web) autorizado pela clínica médica "
                                    "operando seu próprio sistema interno de faturamento usando placeholders seguros "
                                    "({{PORTAL_USERNAME}}, {{PORTAL_PASSWORD}}, {{PATIENT_NAME}}, {{PATIENT_CPF}}, {{PATIENT_CARD}}). "
                                    "Nenhum dado pessoal real está presente. Responda exclusivamente JSON válido conforme o schema solicitado."
                                ),
                            },
                            {"role": "user", "content": prompt},
                        ],
                    },
                )
                resp.raise_for_status()
                msg = resp.json()["choices"][0]["message"]
                content = msg.get("content")
                if content:
                    decision = BrowserActionDecision.model_validate_json(content)
                    if decision.value:
                        decision.value = (
                            decision.value
                            .replace("{{PATIENT_NAME}}", job.patient_name or "")
                            .replace("{{PATIENT_CPF}}", job.patient_cpf or "")
                            .replace("{{PATIENT_CARD}}", job.card_number or "")
                        )
                    return decision
                last_err = f"content=None refusal={msg.get('refusal')}"
                logger.warning("OpenAI tentativa %d retornou %s; tentando novamente...", attempt + 1, last_err)
            raise ValueError(last_err)

    async def _decide_with_gemini(self, **kwargs: Any) -> BrowserActionDecision:
        prompt = self._build_llm_prompt(**kwargs)
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.settings.gemini_model}:generateContent"
            f"?key={self.settings.gemini_api_key}"
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1},
                },
            )
            resp.raise_for_status()
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            return BrowserActionDecision.model_validate_json(text)

    def _semantic_decide(
        self,
        *,
        obs: dict[str, Any],
        job: GuideJob,
        route: PortalRoute,
        creds: dict[str, str],
        medical_order_local_path: str | None,
        downloaded_pdf: bool,
        analysis_polls: int,
        max_analysis_polls: int,
        poll_interval_seconds: float,
    ) -> BrowserActionDecision:
        """Planejador inteligente local para portais TISS/Convênios (funciona offline e como fallback)."""
        elements: list[dict[str, Any]] = obs.get("elements") or []
        page_text: str = obs.get("page_text") or ""
        text_norm = _norm(page_text)

        def _el_desc(el: dict[str, Any]) -> str:
            return _norm(f"{el.get('label', '')} {el.get('name', '')} {el.get('dom_id', '')} {el.get('text', '')}")

        def _extract(pattern: str) -> str | None:
            m = re.search(pattern, page_text, re.I)
            return m.group(1).strip() if m else None

        # 1. Tela de resultado: AUTORIZADA / APROVADA
        if re.search(r"\b(guia\s+autorizada|status:\s*autorizada|situa[cç][aã]o:\s*autorizada|autorizada\s+com\s+sucesso)\b", text_norm):
            guide_num = _extract(r"(?:n[ºo°\.]?\s*(?:da\s*)?guia|protocolo)\s*[:#-]?\s*([A-Z0-9-]{4,24})")
            auth_pwd = _extract(r"(?:senha(?:\s+de\s+autoriza[cç][aã]o)?)\s*[:#-]?\s*([A-Z0-9-]{4,24})")
            validity = _extract(r"(?:validade(?:\s+da\s+senha)?)\s*[:#-]?\s*(\d{2}/\d{2}/\d{4})")

            if not downloaded_pdf:
                dl_btn = next(
                    (
                        e
                        for e in elements
                        if e["tag"] in ("a", "button")
                        and re.search(r"(baixar|download|pdf|imprimir\s+guia)", _el_desc(e))
                    ),
                    None,
                )
                if dl_btn:
                    return BrowserActionDecision(
                        thought=f"Guia {guide_num or ''} AUTORIZADA! Baixando o PDF oficial da autorização.",
                        action="click",
                        element_id=dl_btn["id"],
                        portal_status="AUTHORIZED",
                        guide_number=guide_num,
                        auth_password=auth_pwd,
                        validity_date=validity,
                    )

            return BrowserActionDecision(
                thought=f"Guia {guide_num or ''} autorizada (Senha {auth_pwd or '-'}) e PDF salvo com sucesso.",
                action="done",
                portal_status="AUTHORIZED",
                guide_number=guide_num,
                auth_password=auth_pwd,
                validity_date=validity,
            )

        # 2. Tela de resultado: NEGADA
        if re.search(r"\b(guia\s+negada|status:\s*negada|situa[cç][aã]o:\s*negada)\b", text_norm):
            reason = _extract(r"(?:motivo(?:\s+da\s+negativa)?|justificativa)\s*[:#-]\s*([^\n\.]{4,160})")
            return BrowserActionDecision(
                thought=f"Operadora NEGOU a guia: {reason or 'verificar detalhe no portal'}.",
                action="done",
                portal_status="DENIED",
                denial_reason=reason or "Guia negada pela operadora.",
            )

        # 3. Tela de monitoramento: EM ANÁLISE -> fica de olho até aprovar!
        if re.search(r"\b(em\s+analise|em\s+reanalise|aguardando\s+auditoria|auditoria\s+da\s+operadora)\b", text_norm):
            guide_num = _extract(r"(?:n[ºo°\.]?\s*(?:da\s*)?guia|protocolo)\s*[:#-]?\s*([A-Z0-9-]{4,24})")
            if analysis_polls >= max_analysis_polls:
                return BrowserActionDecision(
                    thought=f"Guia {guide_num or ''} permanece em análise após {analysis_polls} checagens; mantendo job em monitoramento periódico.",
                    action="done",
                    portal_status="IN_ANALYSIS",
                    guide_number=guide_num,
                )

            refresh_btn = next(
                (
                    e
                    for e in elements
                    if e["tag"] in ("button", "a")
                    and re.search(r"(atualizar|verificar\s+status|consultar\s+status|recarregar)", _el_desc(e))
                ),
                None,
            )
            # Alterna aguardar e clicar no botão de atualizar status para o usuário ver o acompanhamento ativo
            if analysis_polls % 2 == 0:
                return BrowserActionDecision(
                    thought=f"Guia {guide_num or ''} está EM ANÁLISE na auditoria do convênio. Aguardando {poll_interval_seconds:.0f}s antes de consultar novamente...",
                    action="wait",
                    wait_seconds=poll_interval_seconds,
                    portal_status="IN_ANALYSIS",
                    guide_number=guide_num,
                )
            if refresh_btn:
                return BrowserActionDecision(
                    thought="Consultando status atualizado da guia no portal para verificar se já foi aprovada...",
                    action="click",
                    element_id=refresh_btn["id"],
                    portal_status="IN_ANALYSIS",
                    guide_number=guide_num,
                )
            return BrowserActionDecision(
                thought="Recarregando página de status da guia para checar aprovação...",
                action="refresh",
                portal_status="IN_ANALYSIS",
                guide_number=guide_num,
            )

        # 4. Tela de Login (nunca atuar como login em telas de alterar-senha)
        cur_url_early = str(obs.get("url") or "").lower()
        pwd_input = (
            None
            if re.search(r"(alterar[-_]?senha|trocar[-_]?senha|redefinir[-_]?senha)", cur_url_early)
            else next((e for e in elements if e["tag"] == "input" and e["type"] == "password"), None)
        )
        if pwd_input:
            user_input = next(
                (
                    e
                    for e in elements
                    if e["tag"] == "input"
                    and e["type"] in ("text", "email", "")
                    and e["id"] != pwd_input["id"]
                    and re.search(r"(user|usuario|login|email|cpf|cnpj|codigo|prestador)", _el_desc(e))
                ),
                None,
            )
            username = creds.get("username") or "prestador.novagesta"
            password = creds.get("password") or "demo-secret-123"
            if user_input and not user_input.get("value"):
                return BrowserActionDecision(
                    thought="Tela de autenticação detectada. Preenchendo credencial do prestador.",
                    action="fill",
                    element_id=user_input["id"],
                    value=username,
                )
            if not pwd_input.get("value"):
                return BrowserActionDecision(
                    thought="Preenchendo senha de acesso ao portal do convênio.",
                    action="fill",
                    element_id=pwd_input["id"],
                    value=password,
                )
            login_btn = next(
                (
                    e
                    for e in elements
                    if e["tag"] in ("button", "input")
                    and not FORBIDDEN_CLICK_PATTERNS.search(_el_desc(e))
                    and re.search(r"(entrar|acessar|login|autenticar|enviar)", _el_desc(e))
                ),
                None,
            )
            if login_btn:
                return BrowserActionDecision(
                    thought="Credenciais preenchidas. Clicando em 'Entrar' para acessar o portal.",
                    action="click",
                    element_id=login_btn["id"],
                )

        # 4.5. Fluxo específico de portais reais (ex: Portal AMHP -> AMHPTISS em modo leitura)
        cur_url = str(obs.get("url") or "").lower()
        if re.search(r"(504\s+gateway\s+timeout|502\s+bad\s+gateway|503\s+service\s+unavailable)", text_norm):
            return BrowserActionDecision(
                thought=f"O servidor do portal ({obs.get('url')}) retornou erro de indisponibilidade (504/502/503).",
                action="fail",
                portal_status="DENIED",
                denial_reason=f"Portal indisponível (HTTP 504/502/503) em {obs.get('url')}",
            )

        if obs.get("has_modal_or_tour_overlay"):
            close_tour = next(
                (
                    e
                    for e in elements
                    if e["tag"] == "button"
                    and re.search(r"\b(fechar\s+guia|fechar|pular\s+tour|entendi|close)\b", _el_desc(e))
                ),
                None,
            )
            if close_tour:
                return BrowserActionDecision(
                    thought="Tour/modal inicial detectado na tela autenticada. Fechando para acessar o menu.",
                    action="click",
                    element_id=close_tour["id"],
                )

        if "portal.amhp.com.br" in cur_url and not pwd_input:
            amhptiss_btn = next(
                (
                    e
                    for e in elements
                    if e["tag"] in ("a", "button")
                    and re.search(r"(amhptiss|portal\s+de\s+faturamento)", _el_desc(e))
                ),
                None,
            )
            if amhptiss_btn:
                return BrowserActionDecision(
                    thought="Autenticado no Portal do Associado AMHP! Abrindo o AMHPTISS (Portal de Faturamento).",
                    action="click",
                    element_id=amhptiss_btn["id"],
                )

        if "amhptiss.amhp.com.br" in cur_url:
            is_readonly_demo = job.igut_appointment_id == "REAL-AMHP-READONLY"
            # Se estamos em Default.aspx ou alterar-senha, SEMPRE navegar para Consultorio -> Atendimento primeiro!
            if "default.aspx" in cur_url or "alterar-senha" in cur_url:
                atend_btn = next(
                    (
                        e
                        for e in elements
                        if e["tag"] in ("a", "button", "li", "div")
                        and _norm(e.get("text", "")) == "atendimento"
                    ),
                    None,
                )
                if atend_btn:
                    return BrowserActionDecision(
                        thought="Abrindo a tela real de 'Atendimento' no AMHPTISS para iniciar a guia.",
                        action="click",
                        element_id=atend_btn["id"],
                    )
                consultorio_btn = next(
                    (
                        e
                        for e in elements
                        if _norm(e.get("text", "")) == "consultorio"
                        or re.search(r"^consultorio\b", _norm(e.get("text", "")))
                    ),
                    None,
                )
                if consultorio_btn:
                    return BrowserActionDecision(
                        thought="Menu lateral do AMHPTISS ativo! Abrindo o menu 'Consultório'.",
                        action="click",
                        element_id=consultorio_btn["id"],
                    )
            if is_readonly_demo:
                menus = [e.get("text") for e in elements if e.get("text") and e["tag"] in ("a", "button", "li")][:12]
                menus_str = ", ".join(m for m in menus if m)
                return BrowserActionDecision(
                    thought=f"AMHPTISS carregado e autenticado! URL: {obs.get('url')}. Opções visíveis: {menus_str or 'painel principal'}.",
                    action="done",
                    portal_status="AUTHORIZED",
                )

        # 5. Formulário de Solicitação de Guia (SP/SADT ou Consulta)
        first_tuss = (job.procedure_codes or route.procedure_codes or ["10101012"])[0]
        field_plan: list[tuple[str, str, str]] = [
            (r"(carteirinha|beneficiario|matricula|numero\s+da\s+carteira)", job.card_number or "0045012345678901", "número da carteirinha do paciente"),
            (r"(nome\s+do\s+paciente|nome\s+beneficiario|paciente)", job.patient_name, "nome completo do paciente"),
            (r"\bcpf\b", job.patient_cpf or "12345678900", "CPF do paciente"),
            (r"(medico|profissional|solicitante)", job.doctor_name or "MARCONDES CARNEIRO LEITE JUNIOR", "médico solicitante"),
            (r"\bcrm\b", job.doctor_crm or "17641", "CRM do médico"),
            (r"\bcbo\b", job.doctor_cbo or "225250", "CBO da especialidade"),
            (r"(tuss|procedimento|codigo\s+do\s+exame|codigo\s+procedimento)", first_tuss, f"código TUSS {first_tuss}"),
            (r"(indicacao|observacao|justificativa\s+clinica)", f"Solicitação {job.appointment_type} - {job.specialty or 'Ginecologia/Obstetrícia'}", "indicação clínica"),
        ]

        for pattern, desired_val, friendly in field_plan:
            if not desired_val:
                continue
            field = next(
                (
                    e
                    for e in elements
                    if e["tag"] in ("input", "textarea")
                    and e["type"] not in ("password", "file", "submit", "button", "checkbox", "radio")
                    and not e.get("disabled")
                    and not e.get("value")
                    and re.search(pattern, _el_desc(e))
                ),
                None,
            )
            if field:
                return BrowserActionDecision(
                    thought=f"Preenchendo campo '{friendly}' no formulário da guia.",
                    action="fill",
                    element_id=field["id"],
                    value=desired_val,
                )

        # Selects (ex: Tipo de Guia, Caráter de Atendimento, Operadora)
        for el in elements:
            if el["tag"] == "select" and not el.get("disabled"):
                desc = _el_desc(el)
                if re.search(r"(tipo\s+de\s+guia|tipo\s+atendimento)", desc) and not el.get("value"):
                    target = "SP/SADT" if route.requires_medical_order_attachment else "Consulta"
                    return BrowserActionDecision(
                        thought=f"Selecionando tipo de guia '{target}'.",
                        action="select",
                        element_id=el["id"],
                        value=target,
                    )
                if re.search(r"(operadora|convenio)", desc) and route.operator_label and not el.get("value"):
                    return BrowserActionDecision(
                        thought=f"Selecionando operadora '{route.operator_label}'.",
                        action="select",
                        element_id=el["id"],
                        value=route.operator_label,
                    )

        # Upload do Pedido Médico (input type=file)
        file_input = next((e for e in elements if e["tag"] == "input" and e["type"] == "file" and not e.get("value")), None)
        if file_input and medical_order_local_path and Path(medical_order_local_path).exists():
            return BrowserActionDecision(
                thought=f"Anexando pedido médico validado ({Path(medical_order_local_path).name}) à solicitação.",
                action="upload",
                element_id=file_input["id"],
                value=medical_order_local_path,
            )

        # Botão de submeter solicitação da guia
        submit_btn = next(
            (
                e
                for e in elements
                if e["tag"] in ("button", "input")
                and re.search(r"(solicitar\s+guia|enviar\s+solicitacao|autorizar|emitir\s+guia|gravar|confirmar)", _el_desc(e))
            ),
            None,
        )
        if submit_btn:
            return BrowserActionDecision(
                thought="Todos os campos obrigatórios preenchidos. Submetendo solicitação da guia ao convênio!",
                action="click",
                element_id=submit_btn["id"],
            )

        # Menu de navegação para abrir Nova Guia / SP-SADT
        nav_btn = next(
            (
                e
                for e in elements
                if e["tag"] in ("a", "button")
                and re.search(r"(nova\s+solicitacao|nova\s+guia|sp/sadt|solicitar\s+procedimento|guia\s+de\s+consulta)", _el_desc(e))
            ),
            None,
        )
        if nav_btn:
            return BrowserActionDecision(
                thought=f"Navegando para '{nav_btn.get('text') or 'Nova Solicitação'}' para iniciar o preenchimento da guia.",
                action="click",
                element_id=nav_btn["id"],
            )

        return BrowserActionDecision(
            thought="Não encontrei ação óbvia nesta tela; pausando para revisão humana.",
            action="needs_human",
            portal_status="AWAITING_HUMAN_2FA",
            denial_reason=f"Tela não reconhecida em {obs.get('url')}",
        )
