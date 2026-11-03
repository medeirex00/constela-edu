"""Base para conectores que dependem de automação de navegador.

Concentra o ciclo de vida do navegador (abrir → usar → SEMPRE fechar) e a
injeção da fábrica (real = Playwright; teste = fake). Cada plataforma só
implementa o que é ESPECÍFICO dela: URLs, seletores e o passo de login.
"""
from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from app.sync import escola_externa
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

# Tela de verificação em DUAS ETAPAS (2FA/OTP) após o envio — a automação não
# completa código enviado por SMS/app. Damos um erro específico (código "mfa")
# em vez de um "falha_auth" genérico, orientando conta-robô sem 2FA ou import
# manual. Seletores de campo de código de uso único (não casam página logada).
_SEL_MFA = (
    "input[autocomplete='one-time-code'], input[name*='otp' i], "
    "input[name*='mfa' i], input[name*='2fa' i], input[id*='otp' i], "
    "input[name*='verification' i], input[name*='authcode' i]")


# --- Endereço de login configurável (opções avançadas: extra['url_login']) ---
# O Chromium do servidor abre esse endereço. Sem trava, um gestor de escola
# apontava o robô para QUALQUER lugar (rede interna, metadados da nuvem,
# file://, página com JavaScript de terceiros) — SSRF. Só vale https para um
# host do site da PRÓPRIA plataforma (``ConectorNavegador.dominios_login``: o
# domínio e os subdomínios dele, porque a plataforma já trocou o subdomínio do
# login antes). A checagem roda ao salvar (schemas.CredenciaisIn) e de novo
# antes de navegar (``_executar_login``), para as credenciais já gravadas.
URL_LOGIN_MAX = 500
# Host só ASCII, rótulos de letras/dígitos/hífen separados por ponto. Fecha os
# truques de parser: barra invertida (o Chromium lê "\" como "/", então
# "https://mau.invalid\.matific.com" abriria mau.invalid), IP v6 entre
# colchetes, %-escapes e caracteres Unicode que o navegador normaliza.
_HOST_VALIDO = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$")


def host_da_lista(host: str, dominios) -> bool:
    """O host é um dos ``dominios`` ou subdomínio de um deles?"""
    host = (host or "").lower()
    return any(host == d or host.endswith("." + d) for d in dominios or ())


def url_na_lista(url, dominios) -> bool:
    """True só para ``https://<host da lista>[:443]/...``, sem usuário/senha no
    endereço, sem espaço, barra invertida ou caractere fora do ASCII. Qualquer
    outra coisa (http, file:, javascript:, IP, host de fora) é False."""
    if not isinstance(url, str) or not url or len(url) > URL_LOGIN_MAX:
        return False
    if any(c == "\\" or not (0x20 < ord(c) < 0x7f) for c in url):
        return False              # espaço, controle, barra invertida, não ASCII
    try:
        partes = urlsplit(url)
        porta = partes.port
    except ValueError:            # porta que não é número, colchete solto…
        return False
    if partes.scheme != "https" or "@" in partes.netloc or porta not in (None, 443):
        return False
    host = partes.hostname or ""
    return bool(_HOST_VALIDO.match(host)) and host_da_lista(host, dominios)


def http_ok(status) -> bool:
    """Resposta 2xx? (o fetch in-page devolve ``status`` 0 em falha de rede)."""
    return isinstance(status, int) and not isinstance(status, bool) and 200 <= status < 300


def codigo_do_http(status) -> str:
    """Código estável de uma resposta NÃO 2xx do endpoint de DADOS: 401/403 é a
    plataforma recusando o acesso ao dado (permissão/sessão), o resto é falha de
    download (5xx, 404, rede, tempo esgotado no fetch)."""
    return "sem_acesso_ao_dado" if status in (401, 403) else "falha_download"


def registrar_falha_coleta(contexto: Contexto, unidade: str, identificador,
                           codigo: str, http=None) -> None:
    """Anota no contexto uma UNIDADE esperada que não chegou (turma, lote de
    livros, aluno, endpoint) — o serviço transforma isso em 'parcial'/'erro' e
    no alerta 'coleta_parcial'. Só ids da plataforma e códigos (sem nome)."""
    coleta = getattr(contexto, "coleta", None)
    if coleta is None:
        return
    coleta.setdefault("falhas", []).append({
        "unidade": unidade, "id": str(identificador)[:40], "codigo": codigo,
        "http": http if isinstance(http, int) else None})


def registrar_descarte_coleta(contexto: Contexto, motivo: str, n: int = 1) -> None:
    """Anota linhas que a plataforma mandou com DEFEITO e que não viram dado
    (ex.: livro sem título) — contadas por motivo, para não sumirem em silêncio."""
    coleta = getattr(contexto, "coleta", None)
    if coleta is None or n <= 0:
        return
    descartes = coleta.setdefault("descartes", {})
    descartes[motivo] = int(descartes.get(motivo, 0)) + int(n)


def codigo_dominante(falhas: list[dict]) -> str:
    """O código que explica um conjunto de falhas: acesso recusado em TODAS →
    'sem_acesso_ao_dado'; interpretação em todas → 'parser_incompativel'; senão
    'falha_download'."""
    codigos = {f.get("codigo") for f in falhas or []}
    if codigos == {"sem_acesso_ao_dado"}:
        return "sem_acesso_ao_dado"
    if codigos == {"parser_incompativel"}:
        return "parser_incompativel"
    if len(codigos) == 1 and next(iter(codigos)) in escola_externa.CODIGOS:
        # Turma recusada por não se saber de qual escola ela é (ver
        # ``resolver_escola_externa``): o motivo diz isso, não "falha ao baixar".
        return next(iter(codigos))
    return "falha_download"


def juntar_escolas(*listas) -> list[dict]:
    """Une listas de escolas [{id, nome}] por id, na ordem em que apareceram,
    ficando com o primeiro nome não vazio de cada uma."""
    saida: dict[str, dict] = {}
    for lista in listas:
        for e in lista or ():
            if not isinstance(e, dict):
                continue
            eid = str(e.get("id") or "").strip()
            if not eid:
                continue
            atual = saida.setdefault(eid, {"id": eid, "nome": ""})
            if not atual["nome"] and e.get("nome"):
                atual["nome"] = str(e["nome"]).strip()[:200]
    return list(saida.values())


def resolver_escola_externa(visiveis: list[dict], contexto: Contexto, nome: str) -> dict:
    """QUAL escola da plataforma esta coleta lê — antes de pedir qualquer dado de
    turma. ``visiveis`` = as escolas que a conta enxerga ([{id, nome}]);
    ``contexto.escola_externa`` = o vínculo gravado (ou None). Regras em
    ``sync/escola_externa.py``. Anota em ``contexto.coleta`` as visíveis e a
    escolhida (o serviço aprende o vínculo dela); levanta ``ErroConector`` com
    código próprio quando não dá para saber com segurança — nada é coletado."""
    visiveis = juntar_escolas(visiveis)
    coleta = getattr(contexto, "coleta", None)
    if coleta is not None:
        coleta["escolas_externas"] = [dict(e) for e in visiveis]
    vinculo = getattr(contexto, "escola_externa", None) or {}
    vinculado = str(vinculo.get("id") or "").strip().lower()
    if vinculado:
        # uuid do Matific comparado sem caixa; o id da plataforma segue como veio.
        alvo = next((e for e in visiveis if e["id"].lower() == vinculado), None)
        if alvo is None and not visiveis:
            raise ErroConector(
                f"Não identifiquei, na resposta do {nome}, a escola que a conta enxerga "
                f"(esta escola está vinculada à escola {escola_externa.descrever([vinculo])} "
                "da plataforma). Nada foi aplicado: a plataforma pode ter mudado a resposta.",
                codigo=escola_externa.ESCOLA_NAO_IDENTIFICADA, recuperavel=True)
        if alvo is None:
            raise ErroConector(
                f"A conta do {nome} cadastrada nesta escola enxerga a(s) escola(s) "
                f"{escola_externa.descrever(visiveis)}, mas esta escola está vinculada à "
                f"escola {escola_externa.descrever([vinculo])} da plataforma. Nada foi "
                "aplicado: confira se a credencial é desta escola. Se a escola trocou de "
                "conta de propósito, o Admin Global refaz o vínculo.",
                codigo=escola_externa.ESCOLA_TROCADA, recuperavel=False)
    elif len(visiveis) == 1:
        alvo = visiveis[0]
    elif visiveis:
        raise ErroConector(
            f"A conta do {nome} enxerga {len(visiveis)} escolas na plataforma "
            f"({escola_externa.descrever(visiveis)}) e esta escola ainda não tem a escola "
            "externa vinculada. Nada foi aplicado: o Admin Global escolhe qual delas é "
            "esta escola (vínculo da escola externa).",
            codigo=escola_externa.CONTA_MULTIESCOLA, recuperavel=False)
    else:
        raise ErroConector(
            f"Não identifiquei, na resposta do {nome}, a escola que a conta enxerga. Nada "
            "foi aplicado: sem saber a escola, os dados podem ser de outra.",
            codigo=escola_externa.ESCOLA_NAO_IDENTIFICADA, recuperavel=True)
    ocupadas = {str(i).lower() for i in getattr(contexto, "externas_de_outras_escolas", ()) or ()}
    if alvo["id"].lower() in ocupadas:
        # A conta lê uma escola da plataforma que já alimenta OUTRA escola do
        # Constela: a credencial cadastrada aqui é (provavelmente) a de lá.
        raise ErroConector(
            f"A conta desta credencial lê a escola {escola_externa.descrever([alvo])} do "
            f"{nome}, que já está vinculada a outra escola do Constela. Nada foi aplicado: "
            "confira se a credencial cadastrada é desta escola.",
            codigo=escola_externa.ESCOLA_EM_OUTRA_ESCOLA, recuperavel=False)
    if coleta is not None:
        coleta["escola_externa"] = {"id": alvo["id"], "nome": alvo.get("nome") or ""}
    return alvo


class ConectorNavegador(Conector):
    """Conector com sessão de navegador. Subclasses definem ``_login`` e os
    métodos da ``Conector`` (localizar/obter), usando ``_sessao``."""

    # Domínios do site da plataforma (o host vale também com subdomínio). Só
    # para eles o robô aceita um endereço de login configurado (extra['url_login'])
    # e só endereços deles aparecem nas mensagens. Vazio = nenhum aceito.
    dominios_login: tuple[str, ...] = ()

    def _endereco_exibivel(self, url, nome: str) -> str:
        """O endereço para a mensagem/log que o gestor lê: o próprio, se é do site
        da plataforma; senão, só o aviso (não repete endereço de fora da lista)."""
        if url_na_lista(url, self.dominios_login):
            return url
        return f"um endereço fora do site do {nome}, não exibido"

    def __init__(self, fabrica_navegador: FabricaNavegador | None = None) -> None:
        # A fábrica é injetável: os testes passam um NavegadorFake e exercitam
        # todo o fluxo sem browser real nem contas nas plataformas.
        self._fabrica: FabricaNavegador = fabrica_navegador or abrir_playwright

    @asynccontextmanager
    async def _sessao(self, contexto: Contexto, *, storage_state: dict | None = None):
        """Abre o navegador e garante o fechamento mesmo em erro.

        ``storage_state`` reidrata a sessão de um login anterior (consulta ao
        vivo) — só é repassado à fábrica quando presente, para não quebrar
        fábricas de teste que não conhecem o parâmetro."""
        kwargs: dict = {"timeout_s": contexto.timeout_s}
        if storage_state is not None:
            kwargs["storage_state"] = storage_state
        nav = await self._fabrica(**kwargs)
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
        url_logado: tuple[str, ...] = (), nome: str = "a plataforma",
    ) -> None:
        """Fluxo de login GENÉRICO, instrumentado e com detecção de bloqueio.

        Passos (cada um com log claro em ``SincronizacaoLog``): abrir → detectar
        CAPTCHA → pré-passos (cookies/perfil, clica-se-existir) → esperar o
        formulário → preencher → enviar → detectar o resultado (logado /
        senha inválida / CAPTCHA / não confirmado). Nunca vaza a senha nos logs.
        As subclasses só informam URL e seletores."""
        log = contexto.log
        exibir = self._endereco_exibivel
        url_login = (cred.extra or {}).get("url_login")
        if url_login and not url_na_lista(url_login, self.dominios_login):
            # Credencial gravada antes da trava (ou por outro caminho) com endereço
            # de fora do site da plataforma: o robô NÃO abre. O endereço não é
            # repetido; a correção é salvar as credenciais de novo.
            log("login", "erro", f"[{nome}] O endereço de login salvo nas opções "
                "avançadas não é do site da plataforma; nada foi aberto.")
            sites = ", ".join(self.dominios_login) or "da própria plataforma"
            raise ErroConector(
                f"O endereço de login salvo nas opções avançadas do {nome} não é "
                f"aceito: ele precisa começar com https:// e ser do site do {nome} "
                f"({sites}). Por segurança, nada foi aberto. Salve as credenciais de "
                "novo deixando o campo ‘Endereço de login’ das opções avançadas em "
                "branco (o sistema usa o endereço oficial) ou informe um endereço do "
                f"site do {nome}.",
                codigo="pagina_login", recuperavel=False)
        alvo = url_login or url
        log("login", "info", f"[{nome}] Abrindo a página de login ({exibir(alvo, nome)})…")
        await nav.ir_para(alvo)
        atual = await nav.url_atual()
        log("login", "info", f"[{nome}] Página carregada: {exibir(atual, nome)}")
        # Prova de que o navegador DESTE servidor abriu e a página respondeu: o serviço
        # fecha o alerta de quando ele não subia ('plataforma_indisponivel') mesmo que
        # a coleta falhe depois (401/403 no dado, download, escola externa…). Não nasce
        # antes (a fábrica que devolve um navegador que cai na 1ª página não prova nada).
        coleta = getattr(contexto, "coleta", None)
        if coleta is not None:
            coleta["navegador_abriu"] = True

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
            onde = exibir(atual, nome)
            log("login", "erro", f"[{nome}] Formulário de login não apareceu ({onde}).")
            raise ErroConector(
                f"Não encontrei o formulário de login do {nome} (endereço atual: "
                f"{onde}). O endereço pode ter mudado, a página redirecionou, ou "
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
                onde = exibir(atual, nome)
                log("login", "erro", f"[{nome}] Campo de senha não apareceu ({onde}).")
                raise ErroConector(
                    f"Não consegui avançar para a senha no {nome} (endereço atual: "
                    f"{onde}). A página pode ter mudado. Tente novamente ou use a "
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
        # A URL saiu da tela de login e caiu numa área logada conhecida (ex.: o
        # Matific redireciona p/ /teachers). É um sinal tão forte quanto o
        # seletor — alguns painéis não expõem link de logout no HTML inicial.
        atual = await nav.url_atual()
        rota = (atual or "").split("?")[0].rstrip("/")
        if (url_logado and any(marca in rota for marca in url_logado)
                and "login" not in rota.rsplit("/", 1)[-1].lower()):
            log("login", "info",
                f"[{nome}] Login confirmado (área logada pela URL: {exibir(atual, nome)}).")
            return
        if await nav.visivel(sel_erro):
            log("login", "warn", f"[{nome}] Mensagem de erro de login detectada.")
            raise ErroConector(
                f"Usuário ou senha do {nome} inválidos. Se as credenciais estão "
                "corretas e funcionam no navegador, a plataforma pode estar "
                "recusando o acesso automatizado do servidor por proteção "
                "anti-robô (reCAPTCHA). O Constela não contorna essa proteção: "
                "envie o relatório exportado pela escola em Importações ou peça "
                "ao fornecedor um acesso oficial aos dados.",
                codigo="senha_invalida", recuperavel=False)
        if await nav.visivel(_SEL_BLOQUEIO):
            raise ErroConector(
                f"O {nome} pediu verificação de segurança (CAPTCHA) após o envio. "
                "Use a importação manual do relatório.",
                codigo="captcha", recuperavel=True)
        if await nav.visivel(_SEL_MFA):
            log("login", "warn", f"[{nome}] Verificação em duas etapas (2FA) detectada.")
            raise ErroConector(
                f"O {nome} pediu verificação em duas etapas (código/2FA), que a "
                "automação não completa. Use uma conta-robô SEM 2FA (dedicada, papel "
                "de gestor) ou a importação manual do relatório.",
                codigo="mfa", recuperavel=True)
        atual = await nav.url_atual()
        # A conta pode ser Google-only (SSO) sem senha direta: aí o login
        # tradicional falha sem "área logada" nem erro explícito. Damos o
        # endereço final e orientamos definir senha direta / usar import manual.
        onde = exibir(atual, nome)
        log("login", "erro", f"[{nome}] Não confirmei a área logada nem erro ({onde}).")
        raise ErroConector(
            f"Não foi possível confirmar o login no {nome}: enviei as credenciais "
            "mas não reconheci nem a área logada nem uma mensagem de erro (o "
            f"endereço final foi {onde}). A conta pode usar login pelo Google (SSO) "
            "sem senha direta, ter verificação extra, ou a página pode ter mudado. "
            "Defina uma senha direta na conta (ex.: ‘Esqueci a senha’) ou use a "
            "importação manual do relatório.",
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
            # No log vai a EXCEÇÃO, não o texto já montado: o formatador tira dela o
            # dado pessoal (observabilidade.redigir_dados_pessoais); o "%.140s" corta
            # como antes. Sem dado pessoal, a linha é a mesma de antes.
            logger.warning("Diagnóstico de login %s: %s: %.140s", self.plataforma,
                           type(exc).__name__, exc)
        return r

    async def testar_credenciais(self, cred, contexto):
        from app.sync.interfaces import ResultadoValidacao
        contexto.log("autenticacao", "info",
                     f"Validando credenciais em {self.plataforma}…")
        escolas = None
        try:
            async with self._sessao(contexto) as nav:
                await self._login(nav, cred, contexto)
                # Login OK: qual(is) escola(s) a conta enxerga? Só para o gestor
                # conferir (sem segredo). Falhar aqui não invalida o login.
                try:
                    escolas = await self._detectar_escolas(nav, contexto)
                except Exception as exc:  # noqa: BLE001 — acessório do teste
                    logger.warning("Detecção da escola externa falhou (%s): %s",
                                   self.plataforma, type(exc).__name__)
                    escolas = None
        except ErroConector as exc:
            if exc.codigo == "navegador_indisponivel":
                # O NOSSO navegador não abriu: a credencial nem chegou à plataforma,
                # e "recusada" seria mentira (a mensagem já diz o que houve).
                contexto.log("autenticacao", "erro", f"Credencial não testada: {exc}")
            else:
                contexto.log("autenticacao", "warn", f"Credencial recusada: {exc}")
            return ResultadoValidacao(ok=False, mensagem=str(exc), codigo=exc.codigo)
        except Exception as exc:  # noqa: BLE001
            # Qualquer falha INESPERADA do navegador/site (seletor mudou,
            # timeout, bloqueio anti-bot, página fora do ar) é convertida em um
            # resultado claro — validar credencial NUNCA deve derrubar o request
            # (500). Log técnico p/ diagnóstico. O erro do Playwright ao preencher
            # traz o VALOR no "Call log" (fill("…")) e o value do campo na prévia
            # do elemento: o navegador o relança sem o valor (preencher) e o
            # formatador do log redige a exceção (redigir_valor_digitado), então
            # nem o usuário nem a senha vão para o log.
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
                                  codigo="ok", escolas_externas=escolas)

    async def _detectar_escolas(self, nav: Navegador, contexto: Contexto) -> list | None:
        """Escolas que a conta logada enxerga ([{id, nome}]) — para o "Testar
        conexão". None = a plataforma não informa. Subclasses sobrescrevem."""
        return None
