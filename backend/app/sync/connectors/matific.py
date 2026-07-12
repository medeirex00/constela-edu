"""Conector Matific — automação de navegador (Playwright).

ESTRATÉGIA E JUSTIFICATIVA (requisito de documentação):
    O Matific NÃO oferece API pública self-serve de *data-out* ativável com
    login/senha. OneRoster/Clever servem para colocar alunos DENTRO do Matific
    (rostering-in); feeds de saída existem só em contrato district/enterprise
    (chave de API negociada). Portanto, sem parceria oficial, a única obtenção
    automática é reproduzir o que o professor faz: logar no portal e baixar o
    "school leaderboard"/relatório de atividade.
    → ``Estrategia.NAVEGADOR``. Quando houver API oficial, criar
      ``ConectorMatificAPI(Estrategia.API_OFICIAL)`` e trocar o registro — o
      resto do sistema não muda.

PONTOS DE EXTENSÃO (só verificáveis com uma conta real — sem conta aqui):
    As constantes ``_URL_*`` e ``_SEL_*`` abaixo são o "contrato de UI" com o
    Matific. Se a página mudar, ajusta-se AQUI (não no núcleo). O fluxo
    (login → localizar → baixar) está completo e é exercitado por testes com
    ``NavegadorFake``; apenas o SUCESSO real do login depende das credenciais.
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

# --- Contrato de UI com o Matific (verificado em jul/2026) -------------------
# A página de login mudou de "/account/login/" (que hoje redireciona p/ a home
# de marketing) para "/login-page/". Campos: #username-input / #password-input;
# botão "Continuar" (#login-button). Um aviso de cookies aparece antes e é
# dispensado. Endereço configurável por escola via extra['url_login'].
_URL_LOGIN = "https://www.matific.com/bra/pt-br/login-page/"
_URL_LEADERBOARD = "https://www.matific.com/bra/pt-br/teachers/admin/school-leaderboard/"
_SEL_COOKIE = "#c-later-btn, #c-accept-btn"
_SEL_USUARIO = "#username-input, input[name='username']"
_SEL_SENHA = "#password-input, input[name='password']"
_SEL_ENTRAR = "#login-button, button[type='submit']"
_SEL_ERRO_LOGIN = ".login-error, .error-message, .errorlist, .error, [role='alert']"
# Indicadores de "já entrou" — evita `nav` genérico (existe na tela de login).
_SEL_LOGADO = ("a[href*='logout'], a[href*='sign-out'], a[href*='signout'], "
               "[class*='dashboard' i], [class*='school-leaderboard' i]")
_SEL_BAIXAR = "a[href*='export'], button:has-text('Exportar'), button:has-text('Download')"


class ConectorMatific(ConectorNavegador):
    plataforma = "matific"
    versao = "1.0.0"
    estrategia = Estrategia.NAVEGADOR
    justificativa = (
        "Sem API oficial self-serve de data-out; obtenção reproduz o portal do "
        "professor (login → school leaderboard → exportar). Trocável por API "
        "oficial via novo conector, sem alterar o núcleo.")

    async def _login(self, nav: Navegador, cred: Credenciais,
                     contexto: Contexto) -> None:
        if not cred.usuario or not cred.senha:
            raise ErroConector("Usuário e senha do Matific são obrigatórios.",
                               codigo="senha_invalida", recuperavel=False)
        await nav.ir_para(cred.extra.get("url_login") or _URL_LOGIN)
        # Dispensa o aviso de cookies, se aparecer (senão intercepta cliques).
        if await nav.esperar(_SEL_COOKIE, timeout_s=5):
            await nav.clicar(_SEL_COOKIE)
        # Espera o formulário aparecer (SPA + possível redirecionamento). Se não
        # surgir, erro CLARO com o endereço alcançado — em vez de estourar no
        # preencher — para o admin saber o motivo real.
        if not await nav.esperar(_SEL_USUARIO, timeout_s=min(contexto.timeout_s, 20)):
            atual = await nav.url_atual()
            raise ErroConector(
                "Não encontrei o formulário de login do Matific "
                f"(endereço atual: {atual}). O endereço de login pode ter "
                "mudado, a página redirecionou, ou exigiu verificação de "
                "segurança. Informe o endereço correto em ‘url de login’ nas "
                "opções avançadas, ou use a importação manual do relatório.",
                codigo="pagina_login", recuperavel=True)
        await nav.preencher(_SEL_USUARIO, cred.usuario)
        await nav.preencher(_SEL_SENHA, cred.senha)
        await nav.clicar(_SEL_ENTRAR)
        # Sucesso = elemento de área logada aparece; senão, erro de login.
        if await nav.esperar(_SEL_LOGADO, timeout_s=min(contexto.timeout_s, 25)):
            return
        if await nav.visivel(_SEL_ERRO_LOGIN):
            raise ErroConector("Usuário ou senha do Matific inválidos.",
                               codigo="senha_invalida", recuperavel=False)
        raise ErroConector(
            "Não foi possível confirmar o login no Matific (a página pode ter "
            "mudado ou exige verificação adicional).",
            codigo="falha_auth", recuperavel=True)

    async def localizar_relatorios(self, cred: Credenciais,
                                   contexto: Contexto) -> list[RelatorioDisponivel]:
        # O Matific expõe UM relatório-alvo (leaderboard da escola). Logamos
        # para garantir a sessão e devolvemos o descritor de download.
        async with self._sessao(contexto) as nav:
            await self._login(nav, cred, contexto)
            contexto.log("download", "info", "Leaderboard da escola localizado.")
        return [RelatorioDisponivel(
            plataforma="matific", tipo="leaderboard",
            identificador=_URL_LEADERBOARD,
            rotulo="Placar/atividade da escola (Matific)")]

    async def obter(self, cred: Credenciais, relatorio: RelatorioDisponivel,
                    contexto: Contexto) -> ArquivoObtido:
        async with self._sessao(contexto) as nav:
            await self._login(nav, cred, contexto)
            await nav.ir_para(relatorio.identificador)
            contexto.log("download", "info", "Baixando relatório do Matific…")
            conteudo, nome = await nav.baixar(
                _SEL_BAIXAR, timeout_s=contexto.timeout_s)
        if not conteudo:
            raise ErroConector("Download do Matific veio vazio.",
                               codigo="falha_download", recuperavel=True)
        agora = datetime.now(timezone.utc)
        return ArquivoObtido(
            conteudo=conteudo,
            nome_arquivo=nome or f"matific_{agora:%Y%m%d}.xlsx",
            plataforma="matific",
            # O leaderboard do Matific é uma planilha; o pipeline detecta pelo
            # conteúdo (magic bytes) de qualquer forma.
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            metadados={"origem": "navegador", "url": relatorio.identificador})
