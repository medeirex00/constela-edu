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
# diagnóstico (sem credenciais) das páginas de login de cada plataforma;
# `egress` guarda o IP/ASN de saída do robô (evidência: datacenter vs residencial).
_estado: dict = {"navegador": None, "detalhe": None, "login": None, "egress": None}


def status() -> dict:
    """Estado atual da verificação (cópia — imutável para o chamador)."""
    return dict(_estado)


def _diagnosticar_egress() -> None:
    """Descobre o IP de SAÍDA do robô e seu provedor (ASN/org). É a evidência
    concreta de que a coleta sai por um IP de DATACENTER (Railway) — o que
    derruba a nota do reCAPTCHA v3 do Matific e faz o login com senha válida ser
    recusado. Um único GET a um serviço público de geo-IP, sem credenciais."""
    import json
    import ssl
    import urllib.request

    import certifi

    # O mesmo bundle de CAs do httpx (certifi, com piso no requirements): o contexto
    # padrão do urllib usaria o ca-certificates da imagem, que não acompanha o piso.
    contexto = ssl.create_default_context(cafile=certifi.where())
    for url in ("https://ipinfo.io/json", "https://ipapi.co/json/"):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "constela-diag/1.0"})
            with urllib.request.urlopen(req, timeout=8, context=contexto) as resp:  # noqa: S310
                d = json.loads(resp.read().decode("utf-8"))
            _estado["egress"] = {
                "ip": d.get("ip"),
                "org": d.get("org") or d.get("asn") or d.get("network"),
                "cidade": d.get("city"), "regiao": d.get("region"),
                "pais": d.get("country") or d.get("country_code"),
            }
            return
        except Exception:  # noqa: BLE001 — tenta o próximo serviço
            continue
    _estado["egress"] = {"erro": "nao_foi_possivel_descobrir_o_ip"}


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
    # Descobre o IP/ASN de saída ANTES do resto (independe do Chromium) — é a
    # evidência do datacenter que explica a recusa do reCAPTCHA v3 do Matific.
    _diagnosticar_egress()
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


_DESLIGADO = frozenset({"0", "false", "nao", "não", "no", "off"})
_LIGADO = frozenset({"", "1", "true", "sim", "yes", "on"})


def verificacao_no_boot_ligada(cfg=None) -> bool:
    """``AUTOMACAO_VERIFICAR_NO_BOOT`` interpretado (texto). Só os valores de
    "desligado" desligam; vazio ou fora da lista mantém o padrão — LIGADO, o que a
    produção sempre fez — e avisa no log, em vez de derrubar o boot."""
    if cfg is None:
        from app.core.config import settings as cfg   # tardio: não carrega config no import
    valor = str(getattr(cfg, "AUTOMACAO_VERIFICAR_NO_BOOT", "") or "").strip().lower()
    if valor in _DESLIGADO:
        return False
    if valor not in _LIGADO:
        logger.warning("AUTOMACAO_VERIFICAR_NO_BOOT com valor não reconhecido: o "
                       "diagnóstico do robô no boot fica LIGADO (use true/false).")
    return True


def iniciar_no_boot(cfg=None) -> bool:
    """O que o ``app.main`` chama no import: dispara a verificação se o interruptor
    deixar. Desligado (testes e E2E), nenhuma thread nasce e nada sai para a rede —
    nem o GET de IP de saída, nem o Chromium. Devolve se disparou."""
    if not verificacao_no_boot_ligada(cfg):
        _estado["detalhe"] = "verificacao desligada no boot (AUTOMACAO_VERIFICAR_NO_BOOT)"
        logger.info("Diagnóstico do robô no boot desligado (AUTOMACAO_VERIFICAR_NO_BOOT): "
                    "sem consulta do IP de saída e sem abrir o Chromium.")
        return False
    iniciar_verificacao()
    return True
