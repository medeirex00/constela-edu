"""Diagnóstico da automação de navegador (Playwright/Chromium) do robô de
sincronização.

Verificado UMA vez, em thread de fundo, no boot do processo — o painel de saúde
(`/api/health`) reporta o resultado. Assim dá para validar que o robô consegue
abrir o navegador em produção SEM precisar de credenciais reais das plataformas
e SEM bloquear o health check (o teste roda fora do caminho de request).

Espelha exatamente o que o conector faz em ``sync/connectors/navegador.py``:
importar o Playwright (a falta dele é o ``navegador_indisponivel``) e abrir o
Chromium headless. Nunca registra segredo/PII — só o tipo do erro.
"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger("constela.automacao")

# None = ainda verificando; True/False = resultado do boot.
_estado: dict = {"navegador": None, "detalhe": None}


def status() -> dict:
    """Estado atual da verificação (cópia — imutável para o chamador)."""
    return dict(_estado)


def _verificar() -> None:
    try:
        from playwright.sync_api import sync_playwright  # import tardio
        with sync_playwright() as p:
            navegador = p.chromium.launch(headless=True)
            navegador.close()
        _estado["navegador"] = True
        _estado["detalhe"] = "chromium abriu com sucesso"
    except ImportError:
        _estado["navegador"] = False
        _estado["detalhe"] = "playwright nao instalado"
    except Exception as exc:  # noqa: BLE001 — qualquer falha vira estado, sem PII
        _estado["navegador"] = False
        _estado["detalhe"] = f"falha ao abrir chromium: {type(exc).__name__}"
        logger.warning("Automacao de navegador indisponivel: %s", type(exc).__name__)


def iniciar_verificacao() -> None:
    """Dispara a verificação em thread daemon (não bloqueia boot nem health)."""
    threading.Thread(target=_verificar, name="verificar-automacao", daemon=True).start()
