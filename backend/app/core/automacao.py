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

# None = ainda verificando; True/False = resultado do boot. `login` guarda o
# diagnóstico (sem credenciais) das páginas de login de cada plataforma.
_estado: dict = {"navegador": None, "detalhe": None, "login": None}


def status() -> dict:
    """Estado atual da verificação (cópia — imutável para o chamador)."""
    return dict(_estado)


def _diagnosticar_paginas_login() -> None:
    """Abre as páginas de login (SEM credenciais) e registra se o formulário
    aparece e se há CAPTCHA/bloqueio — do IP REAL de produção. Valida se o robô
    consegue chegar ao formulário sem precisar de contas das plataformas."""
    import asyncio

    from app.sync import connectors
    from app.sync.interfaces import Contexto

    async def _rodar() -> dict:
        saida: dict = {}
        for plat in ("matific", "elefante"):
            con = connectors.obter(plat)
            if con is None or not hasattr(con, "diagnosticar_login"):
                continue
            ctx = Contexto(escola_id=0, execucao_id=None,
                           log=lambda *a: None, timeout_s=30)
            saida[plat] = await con.diagnosticar_login(ctx)
        return saida

    try:
        _estado["login"] = asyncio.run(_rodar())
    except Exception as exc:  # noqa: BLE001
        _estado["login"] = {"erro": type(exc).__name__}
        logger.warning("Diagnóstico de login falhou: %s", type(exc).__name__)


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
        return
    except Exception as exc:  # noqa: BLE001 — qualquer falha vira estado, sem PII
        _estado["navegador"] = False
        _estado["detalhe"] = f"falha ao abrir chromium: {type(exc).__name__}"
        logger.warning("Automacao de navegador indisponivel: %s", type(exc).__name__)
        return
    # Chromium OK → valida também se as PÁGINAS DE LOGIN abrem (sem credenciais).
    _diagnosticar_paginas_login()


def iniciar_verificacao() -> None:
    """Dispara a verificação em thread daemon (não bloqueia boot nem health)."""
    threading.Thread(target=_verificar, name="verificar-automacao", daemon=True).start()
