"""Conector Elefante Letrado — automação de navegador (Playwright).

ESTRATÉGIA E JUSTIFICATIVA (requisito de documentação):
    O Elefante Letrado não anuncia API pública; a plataforma expõe relatórios
    de leitura (por turma e por aluno) pela própria interface, com login
    (inclusive SSO Google). Sem acordo comercial/API, a obtenção automática
    reproduz o acesso do professor: login → relatórios → exportar/baixar.
    → ``Estrategia.NAVEGADOR``. Migrável para ``API_OFICIAL`` via novo conector.

PONTOS DE EXTENSÃO (verificáveis só com conta real):
    As constantes ``_URL_*``/``_SEL_*`` são o contrato de UI. O fluxo completo é
    testado com ``NavegadorFake``; o sucesso real do login depende das
    credenciais. SSO Google, quando obrigatório, é um ponto de extensão
    (``cred.extra['sso'] == 'google'``) documentado — pode exigir tratamento
    específico e é sinalizado como alerta ao admin.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.sync.connectors.base import ConectorNavegador
from app.sync.connectors.navegador import Navegador
from app.sync.interfaces import (
    ArquivoObtido,
    Contexto,
    Credenciais,
    ErroConector,
    Estrategia,
    RelatorioDisponivel,
)

_URL_LOGIN = "https://www.elefanteletrado.com.br/login"
_URL_RELATORIOS = "https://www.elefanteletrado.com.br/relatorios"
_SEL_USUARIO = "input[name='email'], input[name='usuario'], input[type='email']"
_SEL_SENHA = "input[name='senha'], input[type='password']"
_SEL_ENTRAR = "button[type='submit']"
_SEL_ERRO_LOGIN = ".error, .alert-danger, [role='alert']"
_SEL_LOGADO = "a[href*='logout'], a[href*='sair'], .painel, nav"
_SEL_BAIXAR = "a[href*='export'], button:has-text('Exportar'), button:has-text('Baixar')"


class ConectorElefante(ConectorNavegador):
    plataforma = "elefante"
    versao = "1.0.0"
    estrategia = Estrategia.NAVEGADOR
    justificativa = (
        "Sem API pública anunciada; obtenção reproduz o portal (login → "
        "relatórios de leitura → exportar). SSO Google é ponto de extensão. "
        "Trocável por API oficial via novo conector.")

    async def _login(self, nav: Navegador, cred: Credenciais,
                     contexto: Contexto) -> None:
        if cred.extra.get("sso") == "google":
            # Extensão documentada: login social exige fluxo próprio (e às vezes
            # é incompatível com automação). Sinaliza claramente ao admin.
            raise ErroConector(
                "A conta usa login pelo Google (SSO). Configure uma senha "
                "direta do Elefante ou solicite acesso por API/parceria.",
                codigo="falha_auth", recuperavel=False)
        if not cred.usuario or not cred.senha:
            raise ErroConector("Usuário e senha do Elefante são obrigatórios.",
                               codigo="senha_invalida", recuperavel=False)
        await nav.ir_para(cred.extra.get("url_login") or _URL_LOGIN)
        await nav.preencher(_SEL_USUARIO, cred.usuario)
        await nav.preencher(_SEL_SENHA, cred.senha)
        await nav.clicar(_SEL_ENTRAR)
        if await nav.esperar(_SEL_LOGADO, timeout_s=min(contexto.timeout_s, 25)):
            return
        if await nav.visivel(_SEL_ERRO_LOGIN):
            raise ErroConector("Usuário ou senha do Elefante inválidos.",
                               codigo="senha_invalida", recuperavel=False)
        raise ErroConector(
            "Não foi possível confirmar o login no Elefante (a página pode ter "
            "mudado ou exige verificação).",
            codigo="falha_auth", recuperavel=True)

    async def localizar_relatorios(self, cred: Credenciais,
                                   contexto: Contexto) -> list[RelatorioDisponivel]:
        async with self._sessao(contexto) as nav:
            await self._login(nav, cred, contexto)
            contexto.log("download", "info", "Relatório de leitura localizado.")
        return [RelatorioDisponivel(
            plataforma="elefante", tipo="turma",
            identificador=_URL_RELATORIOS,
            rotulo="Relatório de leitura por turma (Elefante Letrado)")]

    async def obter(self, cred: Credenciais, relatorio: RelatorioDisponivel,
                    contexto: Contexto) -> ArquivoObtido:
        async with self._sessao(contexto) as nav:
            await self._login(nav, cred, contexto)
            await nav.ir_para(relatorio.identificador)
            contexto.log("download", "info", "Baixando relatório do Elefante…")
            conteudo, nome = await nav.baixar(
                _SEL_BAIXAR, timeout_s=contexto.timeout_s)
        if not conteudo:
            raise ErroConector("Download do Elefante veio vazio.",
                               codigo="falha_download", recuperavel=True)
        agora = datetime.now(timezone.utc)
        return ArquivoObtido(
            conteudo=conteudo,
            nome_arquivo=nome or f"elefante_{agora:%Y%m%d}.pdf",
            plataforma="elefante",
            content_type="application/pdf",
            formato_hint="resumo",
            metadados={"origem": "navegador", "url": relatorio.identificador})
