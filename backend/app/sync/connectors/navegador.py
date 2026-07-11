"""Abstração de navegador para conectores que dependem de automação (Playwright).

Por que uma abstração e não Playwright direto nos conectores:
  * TESTABILIDADE — os testes injetam um ``NavegadorFake`` e exercitam TODO o
    fluxo do conector (login → localizar → baixar) sem browser real nem contas.
  * TROCABILIDADE — quando uma plataforma liberar API oficial, o conector migra
    de ``Estrategia.NAVEGADOR`` para ``API_OFICIAL`` sem que orquestrador/
    scheduler/painel percebam.
  * ISOLAMENTO DE DEPENDÊNCIA — o Playwright é import TARDIO: o app sobe e os
    testes rodam sem o pacote instalado; só ``abrir()`` real o exige.

Regra: nenhum método loga a senha. O conector passa o valor a ``preencher`` e
pronto — o valor nunca vai para ``SincronizacaoLog``.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from app.sync.interfaces import ErroConector


@runtime_checkable
class Navegador(Protocol):
    """Superfície mínima de navegador usada pelos conectores."""

    async def ir_para(self, url: str) -> None: ...
    async def preencher(self, seletor: str, valor: str) -> None: ...
    async def clicar(self, seletor: str) -> None: ...
    async def esperar(self, seletor: str, timeout_s: int = 20) -> bool: ...
    async def visivel(self, seletor: str) -> bool: ...
    async def texto(self, seletor: str) -> str: ...
    async def url_atual(self) -> str: ...
    async def baixar(self, seletor: str,
                     timeout_s: int = 60) -> tuple[bytes, str]: ...
    async def fechar(self) -> None: ...


# Fábrica de navegador: () -> Navegador (async). Injetável para teste.
FabricaNavegador = Callable[..., Awaitable[Navegador]]


async def abrir_playwright(*, headless: bool = True,
                           timeout_s: int = 30) -> Navegador:
    """Fábrica REAL — import tardio do Playwright. Só chamada em produção com
    credenciais reais. Levanta ``ErroConector`` claro se o pacote não estiver
    instalado (o app não depende dele para subir)."""
    try:
        from playwright.async_api import async_playwright  # import tardio
    except ImportError as exc:  # pragma: no cover — exige o pacote instalado
        raise ErroConector(
            "Playwright não está instalado neste ambiente. Instale "
            "`playwright` e rode `playwright install chromium` para habilitar "
            "a obtenção automática.", codigo="navegador_indisponivel",
            recuperavel=False) from exc

    pw = await async_playwright().start()  # pragma: no cover — precisa do browser
    navegador = await pw.chromium.launch(headless=headless)
    contexto = await navegador.new_context(accept_downloads=True)
    pagina = await contexto.new_page()
    pagina.set_default_timeout(timeout_s * 1000)
    return _NavegadorPlaywright(pw, navegador, pagina)


class _NavegadorPlaywright:  # pragma: no cover — exercitado só com browser real
    """Adaptador do Playwright para a interface ``Navegador``. Mantido fino de
    propósito: se um seletor mudar, ajusta-se no CONECTOR, não aqui."""

    def __init__(self, pw, navegador, pagina):
        self._pw, self._navegador, self._pagina = pw, navegador, pagina

    async def ir_para(self, url: str) -> None:
        await self._pagina.goto(url, wait_until="domcontentloaded")

    async def preencher(self, seletor: str, valor: str) -> None:
        await self._pagina.fill(seletor, valor)

    async def clicar(self, seletor: str) -> None:
        await self._pagina.click(seletor)

    async def esperar(self, seletor: str, timeout_s: int = 20) -> bool:
        try:
            await self._pagina.wait_for_selector(seletor, timeout=timeout_s * 1000)
            return True
        except Exception:  # noqa: BLE001 — ausência do seletor = False
            return False

    async def visivel(self, seletor: str) -> bool:
        return await self._pagina.is_visible(seletor)

    async def texto(self, seletor: str) -> str:
        return (await self._pagina.text_content(seletor)) or ""

    async def url_atual(self) -> str:
        return self._pagina.url

    async def baixar(self, seletor: str, timeout_s: int = 60) -> tuple[bytes, str]:
        async with self._pagina.expect_download(timeout=timeout_s * 1000) as info:
            await self._pagina.click(seletor)
        download = await info.value
        caminho = await download.path()
        with open(caminho, "rb") as fh:
            return fh.read(), (download.suggested_filename or "relatorio")

    async def fechar(self) -> None:
        try:
            await self._navegador.close()
        finally:
            await self._pw.stop()
