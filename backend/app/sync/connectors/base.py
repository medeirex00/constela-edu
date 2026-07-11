"""Base para conectores que dependem de automação de navegador.

Concentra o ciclo de vida do navegador (abrir → usar → SEMPRE fechar) e a
injeção da fábrica (real = Playwright; teste = fake). Cada plataforma só
implementa o que é ESPECÍFICO dela: URLs, seletores e o passo de login.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from app.sync.connectors.navegador import FabricaNavegador, Navegador, abrir_playwright
from app.sync.interfaces import Conector, Contexto, Credenciais, ErroConector


class ConectorNavegador(Conector):
    """Conector com sessão de navegador. Subclasses definem ``_login`` e os
    métodos da ``Conector`` (localizar/obter), usando ``_sessao``."""

    def __init__(self, fabrica_navegador: FabricaNavegador | None = None) -> None:
        # A fábrica é injetável: os testes passam um NavegadorFake e exercitam
        # todo o fluxo sem browser real nem contas nas plataformas.
        self._fabrica: FabricaNavegador = fabrica_navegador or abrir_playwright

    @asynccontextmanager
    async def _sessao(self, contexto: Contexto):
        """Abre o navegador e garante o fechamento mesmo em erro."""
        nav = await self._fabrica(timeout_s=contexto.timeout_s)
        try:
            yield nav
        finally:
            try:
                await nav.fechar()
            except Exception:  # noqa: BLE001 — fechamento best-effort
                pass

    async def _login(self, nav: Navegador, cred: Credenciais,
                     contexto: Contexto) -> None:
        """Executa o login; levanta ``ErroConector`` com código estável em
        falha. Implementado por cada plataforma."""
        raise NotImplementedError

    async def testar_credenciais(self, cred, contexto):
        from app.sync.interfaces import ResultadoValidacao
        contexto.log("autenticacao", "info",
                     f"Validando credenciais em {self.plataforma}…")
        try:
            async with self._sessao(contexto) as nav:
                await self._login(nav, cred, contexto)
        except ErroConector as exc:
            contexto.log("autenticacao", "warn", f"Credencial recusada: {exc}")
            return ResultadoValidacao(ok=False, mensagem=str(exc), codigo=exc.codigo)
        contexto.log("autenticacao", "info", "Credenciais válidas.")
        return ResultadoValidacao(ok=True, mensagem="Conexão bem-sucedida.",
                                  codigo="ok")
