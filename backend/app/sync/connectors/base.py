"""Base para conectores que dependem de automação de navegador.

Concentra o ciclo de vida do navegador (abrir → usar → SEMPRE fechar) e a
injeção da fábrica (real = Playwright; teste = fake). Cada plataforma só
implementa o que é ESPECÍFICO dela: URLs, seletores e o passo de login.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from app.sync.connectors.navegador import FabricaNavegador, Navegador, abrir_playwright
from app.sync.interfaces import Conector, Contexto, Credenciais, ErroConector

logger = logging.getLogger("constela.sync")

# Sinais de verificação anti-robô (CAPTCHA/desafio) que a automação NÃO resolve.
# reCAPTCHA / hCaptcha / Cloudflare "Just a moment". Detectados p/ dar um erro
# específico (código "captcha") em vez de um "não confirmei o login" genérico.
#
# IMPORTANTE: só entra aqui o DESAFIO INTERATIVO — o que de fato bloqueia. O
# reCAPTCHA invisível (v3) mostra um BADGE fixo ("protegido por reCAPTCHA":
# iframe .../api2/anchor dentro de .grecaptcha-badge, com title "reCAPTCHA") que
# NÃO bloqueia login algum. O Matific usa exatamente esse badge — por isso NÃO
# casamos o iframe genérico de recaptcha nem o title "captcha" (dariam falso
# positivo e travariam TODO login do Matific). O desafio real é o bframe (janela
# de imagens), identificado pelo src (independe de idioma), visível só quando
# aparece; o checkbox v2 vive num contêiner .g-recaptcha.
_SEL_BLOQUEIO = (
    "iframe[src*='recaptcha/api2/bframe'], .g-recaptcha, #g-recaptcha, "
    ".h-captcha, iframe[src*='hcaptcha'], "
    "#challenge-form, #cf-challenge-running, iframe[src*='challenges.cloudflare']")


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

    async def _executar_login(
        self, nav: Navegador, cred: Credenciais, contexto: Contexto, *,
        url: str, sel_usuario: str, sel_senha: str, sel_entrar: str,
        sel_logado: str, sel_erro: str, pre_passos: tuple[str, ...] = (),
        nome: str = "a plataforma",
    ) -> None:
        """Fluxo de login GENÉRICO, instrumentado e com detecção de bloqueio.

        Passos (cada um com log claro em ``SincronizacaoLog``): abrir → detectar
        CAPTCHA → pré-passos (cookies/perfil, clica-se-existir) → esperar o
        formulário → preencher → enviar → detectar o resultado (logado /
        senha inválida / CAPTCHA / não confirmado). Nunca vaza a senha nos logs.
        As subclasses só informam URL e seletores."""
        log = contexto.log
        alvo = cred.extra.get("url_login") or url
        log("login", "info", f"[{nome}] Abrindo a página de login ({alvo})…")
        await nav.ir_para(alvo)
        atual = await nav.url_atual()
        log("login", "info", f"[{nome}] Página carregada: {atual}")

        if await nav.visivel(_SEL_BLOQUEIO):
            log("login", "erro", f"[{nome}] Verificação de segurança (CAPTCHA) na abertura.")
            raise ErroConector(
                f"O {nome} exibiu uma verificação de segurança (CAPTCHA/desafio) "
                "na tela de login — a automação não resolve isso. Use a "
                "importação manual do relatório.",
                codigo="captcha", recuperavel=True)

        for passo in pre_passos:
            if await nav.esperar(passo, timeout_s=5):
                log("login", "info", f"[{nome}] Passo intermediário concluído.")
                await nav.clicar(passo)

        if not await nav.esperar(sel_usuario, timeout_s=min(contexto.timeout_s, 20)):
            atual = await nav.url_atual()
            if await nav.visivel(_SEL_BLOQUEIO):
                raise ErroConector(
                    f"O {nome} pediu verificação de segurança (CAPTCHA) e não "
                    "mostrou o formulário. Use a importação manual do relatório.",
                    codigo="captcha", recuperavel=True)
            log("login", "erro", f"[{nome}] Formulário de login não apareceu ({atual}).")
            raise ErroConector(
                f"Não encontrei o formulário de login do {nome} (endereço atual: "
                f"{atual}). O endereço pode ter mudado, a página redirecionou, ou "
                "exigiu verificação de segurança. Informe o endereço correto em "
                "‘url de login’ nas opções avançadas, ou use a importação manual.",
                codigo="pagina_login", recuperavel=True)

        log("login", "info", f"[{nome}] Formulário encontrado — preenchendo o usuário…")
        await nav.preencher(sel_usuario, cred.usuario)

        # Login em DUAS etapas (ex.: Matific "Continuar"): se o campo de senha
        # ainda não está visível, avança para revelá-lo antes de digitar. Em
        # formulários de uma etapa (ex.: Elefante) a senha já está visível e este
        # bloco é pulado. Confirmado ao vivo: o Matific só mostra #password-input
        # depois de clicar #login-button (que então vira "Iniciar sessão").
        if not await nav.visivel(sel_senha):
            log("login", "info", f"[{nome}] Etapa 1 concluída — avançando para a senha…")
            await nav.clicar(sel_entrar)
            if not await nav.esperar(sel_senha, timeout_s=min(contexto.timeout_s, 15)):
                if await nav.visivel(_SEL_BLOQUEIO):
                    raise ErroConector(
                        f"O {nome} pediu verificação de segurança (CAPTCHA) após o "
                        "usuário. Use a importação manual do relatório.",
                        codigo="captcha", recuperavel=True)
                if await nav.visivel(sel_erro):
                    raise ErroConector(
                        f"Usuário do {nome} não reconhecido.",
                        codigo="senha_invalida", recuperavel=False)
                atual = await nav.url_atual()
                log("login", "erro", f"[{nome}] Campo de senha não apareceu ({atual}).")
                raise ErroConector(
                    f"Não consegui avançar para a senha no {nome} (endereço atual: "
                    f"{atual}). A página pode ter mudado. Tente novamente ou use a "
                    "importação manual do relatório.",
                    codigo="pagina_login", recuperavel=True)

        log("login", "info", f"[{nome}] Preenchendo a senha…")
        await nav.preencher(sel_senha, cred.senha)
        log("login", "info", f"[{nome}] Enviando o formulário de login…")
        await nav.clicar(sel_entrar)
        log("login", "info", f"[{nome}] Aguardando o resultado do login…")

        if await nav.esperar(sel_logado, timeout_s=min(contexto.timeout_s, 25)):
            log("login", "info", f"[{nome}] Login confirmado (área logada detectada).")
            return
        if await nav.visivel(sel_erro):
            log("login", "warn", f"[{nome}] Mensagem de erro de login detectada.")
            raise ErroConector(f"Usuário ou senha do {nome} inválidos.",
                               codigo="senha_invalida", recuperavel=False)
        if await nav.visivel(_SEL_BLOQUEIO):
            raise ErroConector(
                f"O {nome} pediu verificação de segurança (CAPTCHA) após o envio. "
                "Use a importação manual do relatório.",
                codigo="captcha", recuperavel=True)
        atual = await nav.url_atual()
        log("login", "erro", f"[{nome}] Não confirmei a área logada nem erro ({atual}).")
        raise ErroConector(
            f"Não foi possível confirmar o login no {nome}: enviei as credenciais "
            "mas não reconheci nem a área logada nem uma mensagem de erro (o "
            f"endereço final foi {atual}). A página pode ter mudado. Tente "
            "novamente ou use a importação manual do relatório.",
            codigo="falha_auth", recuperavel=True)

    def _config_login(self) -> dict:
        """URL + seletores do login (subclasses sobrescrevem)."""
        raise NotImplementedError

    async def diagnosticar_login(self, contexto: Contexto) -> dict:
        """Diagnóstico SEM credenciais: abre a página de login atual, roda os
        pré-passos (cookies/perfil) e verifica se o FORMULÁRIO aparece e se há
        CAPTCHA/bloqueio. NÃO preenche nem envia nada. Serve para validar, no
        ambiente REAL (ex.: produção), se o robô consegue chegar ao formulário —
        sem precisar de contas das plataformas. Devolve um dicionário simples."""
        cfg = self._config_login()
        r = {"plataforma": self.plataforma, "formulario_encontrado": False,
             "usuario_encontrado": False, "senha_encontrada": False,
             "botao_encontrado": False, "login_progressivo": False,
             "pre_passos_ok": True, "bloqueio_detectado": False,
             "url": cfg["url"], "erro": None}
        try:
            async with self._sessao(contexto) as nav:
                await nav.ir_para(cfg["url"])
                r["url"] = await nav.url_atual()
                r["bloqueio_detectado"] = await nav.visivel(_SEL_BLOQUEIO)
                for passo in cfg["pre_passos"]:
                    # clica-se-existir; se aparecer mas o clique falhar, registra.
                    if await nav.esperar(passo, timeout_s=5):
                        try:
                            await nav.clicar(passo)
                        except Exception:  # noqa: BLE001
                            r["pre_passos_ok"] = False
                # Confirma que os TRÊS alvos do preenchimento/envio resolvem para
                # um elemento VISÍVEL — valida "preencher usuário e senha" e
                # "submeter o formulário" SEM credenciais.
                r["usuario_encontrado"] = await nav.esperar(
                    cfg["sel_usuario"], timeout_s=min(contexto.timeout_s, 20))
                r["senha_encontrada"] = await nav.esperar(cfg["sel_senha"], timeout_s=5)
                r["botao_encontrado"] = await nav.esperar(cfg["sel_entrar"], timeout_s=5)
                # Login em duas etapas (ex.: Matific "Continuar"): usuário e botão
                # já visíveis, senha revelada só depois de avançar. O diagnóstico
                # não avança (sem credenciais), então reconhece o padrão pela
                # senha ainda oculta com usuário+botão presentes.
                r["login_progressivo"] = (
                    r["usuario_encontrado"] and r["botao_encontrado"]
                    and not r["senha_encontrada"])
                r["formulario_encontrado"] = (
                    r["usuario_encontrado"] and r["botao_encontrado"]
                    and (r["senha_encontrada"] or r["login_progressivo"]))
                r["url"] = await nav.url_atual()
                if not r["bloqueio_detectado"]:
                    r["bloqueio_detectado"] = await nav.visivel(_SEL_BLOQUEIO)
        except Exception as exc:  # noqa: BLE001
            r["erro"] = f"{type(exc).__name__}: {str(exc)[:140]}"
            logger.warning("Diagnóstico de login %s: %s", self.plataforma, r["erro"])
        return r

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
        except Exception as exc:  # noqa: BLE001
            # Qualquer falha INESPERADA do navegador/site (seletor mudou,
            # timeout, bloqueio anti-bot, página fora do ar) é convertida em um
            # resultado claro — validar credencial NUNCA deve derrubar o request
            # (500). Log técnico p/ diagnóstico; a mensagem de Playwright cita o
            # seletor/timeout, não o valor preenchido, então não vaza a senha.
            logger.warning(
                "Falha inesperada ao validar %s (escola %s): %s: %s",
                self.plataforma, getattr(contexto, "escola_id", "?"),
                type(exc).__name__, exc, exc_info=True)
            contexto.log("autenticacao", "erro",
                         f"Erro inesperado ao validar {self.plataforma}.")
            nome = (self.plataforma or "plataforma").capitalize()
            return ResultadoValidacao(
                ok=False,
                mensagem=(
                    f"Não foi possível validar o login no {nome} agora: a página "
                    "não respondeu como esperado (pode ter mudado, exigir "
                    "verificação de segurança ou estar indisponível). As "
                    "credenciais foram salvas — tente validar novamente mais "
                    "tarde ou use a importação manual do relatório."),
                codigo="erro_navegador")
        contexto.log("autenticacao", "info", "Credenciais válidas.")
        return ResultadoValidacao(ok=True, mensagem="Conexão bem-sucedida.",
                                  codigo="ok")
