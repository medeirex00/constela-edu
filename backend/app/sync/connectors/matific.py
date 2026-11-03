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

import json
import re
from datetime import date, datetime, timedelta, timezone

from app.core.config import settings
from app.sync import escola_externa
from app.sync.connectors.base import (
    ConectorNavegador,
    codigo_do_http,
    http_ok,
    registrar_descarte_coleta,
    registrar_falha_coleta,
    resolver_escola_externa,
)
from app.sync.connectors.navegador import Navegador
from app.sync.interfaces import (
    ArquivoObtido,
    Contexto,
    Credenciais,
    ErroConector,
    Estrategia,
    RelatorioDisponivel,
)

# Marcador do JSON entregue ao orquestrador (== orchestrator.CT_MATIFIC_API).
_CT_API = "application/x-matific-leaderboard"
_API_BASE = "https://www.matific.com"
# API interna do Placar da Escola (descoberta por DevTools, jul/2026):
#   GET /api/v2/reports/leaderboard/school_student/?duration=<periodo>&school_id=<uuid>
#     → [{ total_points, school_score, students_count_in_school, data:[{account_id,
#          score(=estrelas), activities_completed, grade_code, klassName, uuid}] }]
#   GET /api/v2/competition-v2/<comp>/school/<uuid>/student-leaderboard/
#     → { leaderboard:[{ student_id(=uuid), student_name(NOME COMPLETO), ... }] }
# Auth por COOKIE de sessão (Django sessionid) — same-origin, então o fetch da
# própria página logada já a envia (credentials:'include'); sem token/Bearer.
_EP_CURRENT = f"{_API_BASE}/api/v2/accounts/current/"   # traz school_id do logado
_EP_COMPETITIONS = f"{_API_BASE}/api/v2/competition-v2/"  # lista (p/ competition_id)
_DURATION_PADRAO = "this-year"   # "Ano acadêmico atual" (cumulativo)
_RE_SCHOOL_ID = re.compile(r"school_id=([0-9a-f-]{36})", re.I)
_RE_COMPETICAO = re.compile(r"/competition-v2/([0-9a-f-]{36})/", re.I)

# GET in-page com cookie da sessão (same-origin). AbortController: uma chamada
# travada não segura a sync para sempre. Devolve status + corpo JSON (sem PII).
_JS_GET = r"""(async () => {
  const ctrl = new AbortController();
  const tid = setTimeout(() => ctrl.abort(), 25000);
  try {
    const r = await fetch(__URL__, { method: 'GET', credentials: 'include',
      signal: ctrl.signal, headers: { 'accept': 'application/json, text/plain, */*' } });
    let body = null; try { body = await r.json(); } catch (e) { body = null; }
    return { ok: r.ok, status: r.status, body: body };
  } catch (e) { return { ok: false, status: 0, erro: String(e).slice(0, 160), body: null }; }
  finally { clearTimeout(tid); }
})()"""


def _js_get(url: str) -> str:
    return _JS_GET.replace("__URL__", json.dumps(url))


def _separar_uuids_em_varias_turmas(alunos: list[dict], contexto, log) -> list[dict]:
    """O MESMO uuid em mais de uma turma do Placar. A sync divide o Placar em um
    arquivo por turma e a conferência de id repetido só olha DENTRO do arquivo:
    a 2ª turma aplicava os números dela e MOVIA a matrícula (e, com números
    iguais, a matrícula ia e voltava a cada coleta).

    Forma segura enquanto a semântica do Placar não está confirmada:
      * números IGUAIS → fica só a primeira linha, marcada ``turma_ambigua`` (a
        importação não move a matrícula por ela);
      * números DIFERENTES → o uuid sai desta coleta, contado no descarte
        'id_em_varias_turmas' (aviso 'coleta_parcial'): não dá para saber quais
        números são da criança."""
    turmas: dict[str, set] = {}
    numeros: dict[str, set] = {}
    for a in alunos:
        uuid = a.get("uuid") or ""
        if uuid:
            turmas.setdefault(uuid, set()).add(a.get("turma"))
            numeros.setdefault(uuid, set()).add((a.get("estrelas"), a.get("atividades")))
    repetidos = {u for u, ts in turmas.items() if len(ts) > 1}
    if not repetidos:
        return alunos
    divergentes = {u for u in repetidos if len(numeros[u]) > 1}
    saida, vistos, descartadas = [], set(), 0
    for a in alunos:
        uuid = a.get("uuid") or ""
        if uuid in divergentes:
            descartadas += 1
            continue
        if uuid in repetidos:
            if uuid in vistos:
                continue
            vistos.add(uuid)
            a = {**a, "turma_ambigua": True}
        saida.append(a)
    if descartadas and contexto is not None:
        registrar_descarte_coleta(contexto, "id_em_varias_turmas", descartadas)
    log("download", "warn",
        f"[Matific] {len(repetidos)} conta(s) aparecem em mais de uma turma do Placar: "
        f"{len(repetidos) - len(divergentes)} com os mesmos números (aplicadas uma vez, "
        f"sem mudar a turma) e {len(divergentes)} com números diferentes (não aplicadas "
        "nesta coleta — confira a turma da criança no Matific).")
    return saida


# Cabeçalhos das requisições HTTP DIRETAS (sem navegador): imitam o Chrome do
# robô para que a API interna aceite o cookie de sessão same-origin. GET a
# endpoint DRF com SessionAuthentication não exige CSRF.
_HEADERS_HTTP = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Referer": "https://www.matific.com/bra/pt-br/teachers/admin/school-leaderboard/",
    "X-Requested-With": "XMLHttpRequest",
}


def _slug(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (texto or "turma").lower()).strip("-")[:40] or "turma"


def _para_int(valor) -> int:
    """A API do Matific manda os números como STRING ('3914'). Robusto a lixo."""
    try:
        return int(float(str(valor).strip()))
    except (TypeError, ValueError):
        return 0


def _parse_data(s: str):
    """'2026-07-14' → datetime (p/ periodo_inicio/fim); '' → None."""
    try:
        return datetime.strptime(s, "%Y-%m-%d") if s else None
    except (TypeError, ValueError):
        return None


# --- Semântica do ``end_date`` do Placar (MATIFIC_END_DATE) -------------------
# NÃO confirmada com a plataforma. O pedido da escola é sempre "de I a F, os dois
# dias inclusive" (a rota aceita início = fim). Como isso vira o filtro e a data do
# retrato depende do que o Matific faz com o end_date:
#   desconhecida (padrão): end_date=F e o retrato fica na véspera de F (o
#       comportamento de sempre, que trata F como limite exclusivo); 1 dia é
#       RECUSADO — com I = F não há intervalo para datar.
#   inclusiva: end_date=F (o Matific inclui F) e o retrato fica em F 23:59:59.
#   exclusiva: end_date=F+1 (o Matific exclui o end_date) e o retrato em F 23:59:59.
# A sync (aqui) e o placar ao vivo (``aovivo.mapa_filtro``) usam as MESMAS funções.
SEMANTICAS_FIM = ("desconhecida", "inclusiva", "exclusiva")
MSG_UM_DIA = ("A semântica do fim de período do Matific ainda não foi confirmada; "
              "escolha pelo menos 2 dias.")


def semantica_fim() -> str:
    """'desconhecida' | 'inclusiva' | 'exclusiva' (valor fora da lista → desconhecida)."""
    valor = str(getattr(settings, "MATIFIC_END_DATE", "") or "").strip().lower()
    return valor if valor in SEMANTICAS_FIM else "desconhecida"


def periodo_um_dia_permitido() -> bool:
    """Período de 1 dia (início = fim) só com a semântica do fim CONFIRMADA."""
    return semantica_fim() != "desconhecida"


def end_date_do_filtro(fim: date) -> date:
    """Data que vai no ``end_date`` do Placar para um pedido que termina em ``fim``
    (inclusive): F+1 se o Matific trata o end_date como exclusivo; F nos demais."""
    return fim + timedelta(days=1) if semantica_fim() == "exclusiva" else fim


def limite_exclusivo_do_retrato(fim: datetime) -> datetime:
    """Limite EXCLUSIVO (00:00) que a importação por período recebe como
    ``periodo_fim`` — ela data o retrato 1 s antes. Com a semântica confirmada, o
    retrato cai em F 23:59:59; com 'desconhecida', na véspera de F (como sempre)."""
    return fim if semantica_fim() == "desconhecida" else fim + timedelta(days=1)

# --- Contrato de UI com o Matific (verificado em jul/2026) -------------------
# A página de login mudou de "/account/login/" (que hoje redireciona p/ a home
# de marketing) para "/login-page/". Campos: #username-input / #password-input;
# botão "Continuar" (#login-button). Um aviso de cookies aparece antes e é
# apenas DISPENSADO (nunca "Aceitar Todos"). Endereço configurável via
# extra['url_login'] — só https e host de DOMINIOS_LOGIN (ver base.url_na_lista).
_URL_LOGIN = "https://www.matific.com/bra/pt-br/login-page/"
# Domínio do site do Matific (login, área do professor e API interna em
# www.matific.com). O host do endereço de login vale também com subdomínio.
DOMINIOS_LOGIN = ("matific.com",)
_URL_LEADERBOARD = "https://www.matific.com/bra/pt-br/teachers/admin/school-leaderboard/"
# Só DISPENSAR o aviso de cookies (privacidade): "Mais tarde"/fechar (X). Nunca
# "Aceitar Todos" — o robô não dá consentimento de cookies pela escola. Se
# nenhum aparecer, o passo é pulado (clica-se-existir).
_SEL_COOKIE = "#c-later-btn, #c-close-btn"
_SEL_USUARIO = "#username-input, input[name='username']"
_SEL_SENHA = "#password-input, input[name='password']"
# Login em DUAS etapas: o MESMO #login-button é "Continuar" (revela a senha) e
# depois "Iniciar sessão" (envia). NÃO usar `button[type='submit']` genérico: o
# #login-button é type=button, e a página tem outros submit (cookies, acessibi-
# lidade, SSO) que poderiam ser clicados por engano. Fallback por RÓTULO.
_SEL_ENTRAR = ("#login-button, button:has-text('Iniciar sessão'), "
               "button:has-text('Continuar')")
_SEL_ERRO_LOGIN = ".login-error, .error-message, .errorlist, .error, [role='alert']"
# Indicadores de "já entrou" — evita `nav` genérico (existe na tela de login).
_SEL_LOGADO = ("a[href*='logout'], a[href*='sign-out'], a[href*='signout'], "
               "[class*='dashboard' i], [class*='school-leaderboard' i]")
_SEL_BAIXAR = "a[href*='export'], button:has-text('Exportar'), button:has-text('Download')"


class ConectorMatific(ConectorNavegador):
    plataforma = "matific"
    versao = "1.0.0"
    estrategia = Estrategia.NAVEGADOR
    dominios_login = DOMINIOS_LOGIN
    # O serviço exige que a coleta diga de qual escola da plataforma ela é (ver
    # ``resolver_escola_externa``); sem isso, recusa antes de aplicar.
    confere_escola_externa = True
    justificativa = (
        "Sem API oficial self-serve de data-out; obtenção reproduz o portal do "
        "professor (login → school leaderboard → exportar). Trocável por API "
        "oficial via novo conector, sem alterar o núcleo.")

    def _config_login(self) -> dict:
        """URL + seletores do login. Usado pelo fluxo real E pelo diagnóstico."""
        return dict(url=_URL_LOGIN, sel_usuario=_SEL_USUARIO, sel_senha=_SEL_SENHA,
                    sel_entrar=_SEL_ENTRAR, sel_logado=_SEL_LOGADO,
                    sel_erro=_SEL_ERRO_LOGIN, pre_passos=(_SEL_COOKIE,),
                    # Pós-login o Matific redireciona p/ a área do professor; a
                    # URL confirma o login mesmo sem link de logout no HTML.
                    url_logado=("/teachers", "/dashboard"),
                    nome="Matific")

    async def _login(self, nav: Navegador, cred: Credenciais,
                     contexto: Contexto) -> None:
        if not cred.usuario or not cred.senha:
            raise ErroConector("Usuário e senha do Matific são obrigatórios.",
                               codigo="senha_invalida", recuperavel=False)
        # Fluxo instrumentado (logs por etapa + detecção de CAPTCHA) no base.
        await self._executar_login(nav, cred, contexto, **self._config_login())

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

    # ---- COLETA PELA API INTERNA (Placar da Escola) -------------------------

    @staticmethod
    def _ids_do_placar(caps: list) -> tuple[str, str]:
        """Extrai (school_id, competition_id) das requisições que a página do
        Placar dispara ao carregar. school_id vem do school_student e/ou do
        student-leaderboard; competition_id só do student-leaderboard."""
        school_id, comp_id = "", ""
        for c in caps or []:
            url = (c or {}).get("url", "") if isinstance(c, dict) else ""
            if not school_id and (m := _RE_SCHOOL_ID.search(url)):
                school_id = m.group(1)
            if not comp_id and (m := _RE_COMPETICAO.search(url)):
                comp_id = m.group(1)
        return school_id, comp_id

    @staticmethod
    def _school_ids_do_trafego(caps: list) -> list[str]:
        """TODOS os school_id distintos das requisições do Placar (o fallback de
        quando o accounts/current não informa a escola): mais de um é conta que
        enxerga várias escolas — não se escolhe "o primeiro"."""
        vistos: list[str] = []
        for c in caps or []:
            url = (c or {}).get("url", "") if isinstance(c, dict) else ""
            for m in _RE_SCHOOL_ID.finditer(url):
                sid = m.group(1)
                if sid.lower() not in {v.lower() for v in vistos}:
                    vistos.append(sid)
        return vistos

    @staticmethod
    def _escola_do_current(body) -> dict | None:
        """{id, nome} da escola da conta pelo ``accounts/current`` (SUPOSIÇÃO: o
        ``school_id`` dele é a escola da conta logada; o nome só se a resposta o
        trouxer — ver docs/SINCRONIZACAO.md). None se não veio."""
        if not isinstance(body, dict):
            return None
        sid = str(body.get("school_id") or "").strip()
        if not sid:
            return None
        nome = body.get("school_name") or body.get("schoolName") or ""
        return {"id": sid, "nome": str(nome).strip()[:200]}

    async def _detectar_escolas(self, nav, contexto: Contexto) -> list | None:
        """"Testar conexão": a escola da conta (accounts/current), sem segredo."""
        await nav.ir_para(_URL_LEADERBOARD)
        try:
            res = await nav.avaliar(_js_get(_EP_CURRENT))
        except Exception:  # noqa: BLE001 — acessório do teste
            return None
        escola = self._escola_do_current(res.get("body") if isinstance(res, dict) else None)
        return [escola] if escola else []

    @staticmethod
    def _mapa_nomes(res) -> dict:
        """student-leaderboard → {uuid: nome COMPLETO}. Resolve o nome abreviado
        do Placar (account_id = 'ANTONELLA D') para o nome cheio matriculável."""
        res = res if isinstance(res, dict) else {}
        body = res.get("body")
        linhas = body.get("leaderboard") if isinstance(body, dict) else None
        nomes: dict[str, str] = {}
        for it in linhas or []:
            if not isinstance(it, dict):
                continue
            uuid = str(it.get("student_id") or "").strip()
            nome = str(it.get("student_name") or "").strip()
            if uuid and nome:
                nomes[uuid] = nome
        return nomes

    @staticmethod
    def _parse_school_student(res, nomes: dict,
                              descartes: dict | None = None) -> list[dict]:
        """school_student → [{nome, uuid, turma, estrelas, atividades}]. Usa o
        nome COMPLETO (via ``nomes``) quando houver; senão, o abreviado do Placar.
        Pula linhas-fantasma (sem nome, turma NEM uuid — vêm zeradas no fim do
        relatório). Linha com só parte disso é DEFEITO: não entra e é contada em
        ``descartes['sem_nome_ou_turma']`` (quando o chamador passa o dict).

        Campo numérico AUSENTE (não "zero": a chave não veio — ex.: renomeado no
        Placar) fica listado em ``ausentes`` do aluno; a sync o manda como nulo e
        a importação NÃO grava retrato herdado com data nova (ver importacoes)."""
        res = res if isinstance(res, dict) else {}
        body = res.get("body")
        # O corpo é uma lista com UM objeto {..., data:[...]}.
        raiz = body[0] if isinstance(body, list) and body else body
        dados = raiz.get("data") if isinstance(raiz, dict) else None
        alunos: list[dict] = []
        for it in dados or []:
            if not isinstance(it, dict):
                continue
            uuid = str(it.get("uuid") or "").strip()
            abrev = str(it.get("account_id") or "").strip()
            turma = str(it.get("klassName") or "").strip()
            if not abrev or not turma:
                if (abrev or turma or uuid) and descartes is not None:
                    descartes["sem_nome_ou_turma"] = descartes.get("sem_nome_ou_turma", 0) + 1
                continue                 # fantasma (tudo vazio) ou linha com defeito
            nome = nomes.get(uuid) or abrev
            aluno = {
                "nome": nome, "nome_abrev": abrev, "uuid": uuid, "turma": turma,
                "serie": str(it.get("grade_code") or "").strip(),
                "estrelas": _para_int(it.get("score")),
                "atividades": _para_int(it.get("activities_completed")),
            }
            ausentes = [campo for campo, chave in (("estrelas", "score"),
                                                   ("atividades", "activities_completed"))
                        if chave not in it]
            if ausentes:
                aluno["ausentes"] = ausentes
            alunos.append(aluno)
        return alunos

    @staticmethod
    def _corpo_leaderboard_valido(res) -> bool:
        """O corpo 2xx do student-leaderboard tem a forma conhecida
        (``{leaderboard: [...]}``)?"""
        body = res.get("body") if isinstance(res, dict) else None
        return isinstance(body, dict) and isinstance(body.get("leaderboard"), list)

    @staticmethod
    def _corpo_school_student_valido(res) -> bool:
        """O corpo 2xx do school_student tem a forma conhecida? Lista vazia é
        "nenhum aluno" (legítimo); objeto sem ``data`` (ou corpo não-JSON) é a API
        que mudou — interpretar isso como "0 alunos" esconderia a quebra."""
        body = res.get("body") if isinstance(res, dict) else None
        if isinstance(body, list):
            return not body or (isinstance(body[0], dict)
                                and isinstance(body[0].get("data"), list))
        return isinstance(body, dict) and isinstance(body.get("data"), list)

    @staticmethod
    def _conferir_escola_do_corpo(res, school_id: str) -> None:
        """J: o corpo do school_student traz ``school_id`` (MATIFIC_API §4.1). Se
        ele disser OUTRA escola (ou mais de uma), nada é aplicado. Sem o campo, não
        há o que conferir (segue como antes)."""
        body = res.get("body") if isinstance(res, dict) else None
        itens = body if isinstance(body, list) else [body]
        do_corpo = {str(i.get("school_id")).strip().lower() for i in itens
                    if isinstance(i, dict) and i.get("school_id")}
        if do_corpo and do_corpo != {str(school_id).strip().lower()}:
            raise ErroConector(
                "O Placar do Matific respondeu com dados de outra escola da plataforma "
                f"({len(do_corpo)} escola(s) no corpo, diferente da pedida). Nada foi "
                "aplicado.", codigo=escola_externa.ESCOLA_TROCADA, recuperavel=False)

    async def _buscar_json_campo(self, nav, url: str, campo: str) -> str:
        """GET in-page (cookie) e devolve um campo string do corpo (dict). '' se falhar."""
        try:
            res = await nav.avaliar(_js_get(url))
        except Exception:  # noqa: BLE001 — endpoint acessório; segue com fallback
            return ""
        body = res.get("body") if isinstance(res, dict) else None
        return str(body.get(campo) or "").strip() if isinstance(body, dict) else ""

    async def _primeira_competicao(self, nav) -> str:
        """id da competição (para o student-leaderboard com nome completo). Prefere
        a que está AO VIVO; senão a primeira. '' se não houver."""
        try:
            res = await nav.avaliar(_js_get(_EP_COMPETITIONS))
        except Exception:  # noqa: BLE001
            return ""
        body = res.get("body") if isinstance(res, dict) else None
        if not isinstance(body, list):
            return ""
        comps = [c for c in body if isinstance(c, dict) and c.get("id")]
        ao_vivo = next((c for c in comps if c.get("is_live")), None)
        alvo = ao_vivo or (comps[0] if comps else None)
        return str(alvo.get("id")).strip() if alvo else ""

    async def _coletar_do_placar(self, nav, filtro: str, log,
                                 contexto: Contexto | None = None, *,
                                 conferir_escola: Contexto | None = None) -> list[dict]:
        """Estando LOGADO em www.matific.com, coleta o Placar da Escola pela API
        interna para o ``filtro`` (``duration=…`` OU ``start_date=…&end_date=…``):
        resolve school_id/competition_id, busca os nomes completos e o
        ``school_student``, cruza por uuid e devolve
        ``[{nome, nome_abrev, uuid, turma, serie, estrelas, atividades}]``.

        Levanta ``ErroConector(codigo='sem_escola')`` se não achar a escola. HTTP
        que não é 2xx no ``school_student`` também levanta (401/403 →
        ``sem_acesso_ao_dado``; outros → ``falha_download``): antes virava "0
        alunos" e a execução terminava 'sem_dados' com a credencial carimbada
        válida. Corpo 2xx fora da forma conhecida → ``parser_incompativel``. O
        ``student-leaderboard`` (só os nomes completos) é acessório: a falha dele
        é anotada como unidade com falha e a coleta segue (ver abaixo). Núcleo
        COMPARTILHADO pela sync (por turma) e pela consulta ao vivo (caminho pelo
        navegador).

        ESCOLA EXTERNA: a escola da conta é conferida contra o vínculo desta escola
        (``resolver_escola_externa``, com ``conferir_escola`` ou ``contexto``)
        ANTES de pedir os alunos — escola diferente da vinculada, ou várias escolas
        no tráfego sem vínculo, levantam e nada é coletado."""
        # same-origin para os fetches com cookie de sessão; NÃO dependemos das
        # chamadas que a própria tela dispara (school_id vem do accounts/current).
        await nav.ir_para(_URL_LEADERBOARD)
        try:
            res_cur = await nav.avaliar(_js_get(_EP_CURRENT))
        except Exception:  # noqa: BLE001 — sem o current, cai no fallback do tráfego
            res_cur = None
        escola_cur = self._escola_do_current(
            res_cur.get("body") if isinstance(res_cur, dict) else None)
        visiveis = [escola_cur] if escola_cur else []
        comp_id = await self._primeira_competicao(nav)
        if not visiveis:  # fallback: requisições que a página do Placar dispara
            caps = await nav.coletar_respostas(_URL_LEADERBOARD, timeout_s=20)
            _cap_school, cap_comp = self._ids_do_placar(caps)
            visiveis = [{"id": s, "nome": ""} for s in self._school_ids_do_trafego(caps)]
            comp_id = comp_id or cap_comp
        if not visiveis:
            raise ErroConector(
                "[Matific] não localizei a escola do usuário (accounts/current).",
                codigo="sem_escola", recuperavel=True)
        conferir = conferir_escola or contexto
        if conferir is not None:
            school_id = resolver_escola_externa(visiveis, conferir, "Matific")["id"]
        else:
            school_id = visiveis[0]["id"]
        log("navegacao", "info", "[Matific] Escola localizada — coletando o Placar.")

        # Nomes completos (uuid → nome) da competição, quando houver. É endpoint
        # ACESSÓRIO: os números vêm do school_student e quem já está vinculado
        # casa pelo uuid; sem o nome cheio, a conta ainda não vinculada vai para a
        # revisão "nome_incompleto" (nunca vira ficha abreviada). Por isso uma
        # falha aqui NÃO derruba a coleta (antes derrubava a escola inteira, e o
        # placar ao vivo): vira uma unidade com falha ('endpoint') — a execução
        # termina 'parcial' com o alerta 'coleta_parcial' —, e uma resposta 2xx
        # fora do formato é anotada como 'parser_incompativel' (alerta crítico),
        # em vez de seguir calada com nomes vazios.
        nomes: dict = {}
        if comp_id:
            url_lb = (f"{_API_BASE}/api/v2/competition-v2/{comp_id}"
                      f"/school/{school_id}/student-leaderboard/")
            codigo_lb, status_lb = None, None
            try:
                res_lb = await nav.avaliar(_js_get(url_lb))
            except Exception as exc:  # noqa: BLE001
                res_lb, codigo_lb = None, "falha_download"
                log("download", "warn",
                    f"[Matific] student-leaderboard falhou ({str(exc)[:80]}): sigo sem "
                    "os nomes completos.")
            if codigo_lb is None:
                status_lb = res_lb.get("status") if isinstance(res_lb, dict) else None
                if not http_ok(status_lb):
                    codigo_lb = codigo_do_http(status_lb)
                    log("download", "warn",
                        f"[Matific] student-leaderboard respondeu HTTP {status_lb}: sigo "
                        "sem os nomes completos (conta não vinculada vai para revisão).")
                elif not self._corpo_leaderboard_valido(res_lb):
                    codigo_lb = "parser_incompativel"
                    log("download", "warn",
                        "[Matific] student-leaderboard fora do formato conhecido (sem a "
                        "lista 'leaderboard'): sigo sem os nomes completos.")
                else:
                    nomes = self._mapa_nomes(res_lb)
            if codigo_lb is not None and contexto is not None:
                registrar_falha_coleta(contexto, "endpoint", "student-leaderboard",
                                       codigo_lb, http=status_lb)

        # Dados por aluno (estrelas/atividades) DENTRO do período pedido.
        url_ss = (f"{_API_BASE}/api/v2/reports/leaderboard/school_student/"
                  f"?{filtro}&school_id={school_id}")
        try:
            res = await nav.avaliar(_js_get(url_ss))
        except Exception as exc:  # noqa: BLE001
            raise ErroConector(
                f"Placar do Matific falhou na API ({str(exc)[:80]}).",
                codigo="falha_download", recuperavel=True) from exc
        status_ss = res.get("status") if isinstance(res, dict) else None
        if not http_ok(status_ss):
            codigo = codigo_do_http(status_ss)
            raise ErroConector(
                f"Placar do Matific respondeu HTTP {status_ss} no school_student"
                + (" (acesso ao dado recusado)." if codigo == "sem_acesso_ao_dado"
                   else "."), codigo=codigo, recuperavel=codigo == "falha_download")
        if not self._corpo_school_student_valido(res):
            raise ErroConector(
                "Resposta do Placar do Matific fora do formato conhecido (sem a lista "
                "'data') — a API pode ter mudado. Verifique o conector.",
                codigo="parser_incompativel", recuperavel=False)
        self._conferir_escola_do_corpo(res, school_id)
        descartes: dict = {}
        alunos = self._parse_school_student(res, nomes, descartes)
        for motivo, n in descartes.items():
            if contexto is not None:
                registrar_descarte_coleta(contexto, motivo, n)
            log("download", "warn",
                f"[Matific] {n} linha(s) do Placar sem nome ou sem turma — não importada(s).")
        if not alunos:
            log("download", "warn",
                f"[Matific] Placar sem alunos no período (HTTP {status_ss}).")
        return alunos

    async def _sessao_valida(self, nav) -> bool:
        """True se a sessão REAPROVEITADA caiu numa área logada (URL /teachers|
        /dashboard ou selo de logado) — assim a consulta ao vivo pula o login."""
        try:
            atual = (await nav.url_atual()) or ""
        except Exception:  # noqa: BLE001
            return False
        if any(m in atual for m in ("/teachers", "/dashboard")):
            return True
        if "login" in atual:            # voltou pro formulário → sessão expirou
            return False
        try:
            return await nav.visivel(_SEL_LOGADO)
        except Exception:  # noqa: BLE001
            return False

    # ---- COLETA POR HTTP DIRETO (sem navegador) -----------------------------

    @staticmethod
    def _cookies_de(storage_state: dict | None) -> dict:
        """{nome: valor} dos cookies de matific.com de um storage_state salvo."""
        out: dict[str, str] = {}
        for c in (storage_state or {}).get("cookies") or []:
            if not isinstance(c, dict):
                continue
            if "matific.com" in str(c.get("domain") or "") and c.get("name"):
                out[str(c["name"])] = str(c.get("value") or "")
        return out

    def coletar_via_http(self, storage_state: dict | None, filtro: str, *,
                         escola_esperada: str = "",
                         escolas_recusadas: frozenset = frozenset()) -> list[dict]:
        """Coleta o Placar pela API interna por HTTP DIRETO — SEM navegador —,
        reusando o cookie de sessão do ``storage_state``. É o caminho preferencial
        (item de arquitetura): rápido e sem abrir o Chromium.

        Levanta ``ErroConector('sessao_invalida')`` se a sessão não serve (sem
        cookie / 401 / 403 / redirecionou para o login) — o chamador então usa o
        navegador SÓ para autenticar e tenta de novo por HTTP. Não faz login aqui.

        ``escola_esperada`` (o vínculo da escola): a escola do accounts/current
        diferente dela levanta ``escola_externa_trocada`` ANTES de pedir os alunos
        (o placar ao vivo mostraria os nomes de crianças de outra escola);
        ``escolas_recusadas`` (as vinculadas a OUTRAS escolas do Constela): a
        escola da conta entre elas levanta ``escola_externa_em_outra_escola``."""
        import httpx

        cookies = self._cookies_de(storage_state)
        if "sessionid" not in cookies:
            raise ErroConector("Sem cookie de sessão do Matific para o HTTP direto.",
                               codigo="sessao_invalida", recuperavel=True)

        def _get(client: "httpx.Client", url: str) -> dict:
            r = client.get(url)
            ct = r.headers.get("content-type", "")
            # Sessão expirada → o Matific responde 401/403 ou REDIRECIONA para o
            # login (302/HTML). Em qualquer caso, não é o JSON esperado.
            if r.status_code in (401, 403) or r.is_redirect or "json" not in ct:
                raise ErroConector(
                    f"Sessão do Matific inválida no HTTP (status {r.status_code}).",
                    codigo="sessao_invalida", recuperavel=True)
            try:
                corpo = r.json()
            except ValueError as exc:
                raise ErroConector("Resposta não-JSON do Matific no HTTP.",
                                   codigo="sessao_invalida", recuperavel=True) from exc
            return {"ok": True, "status": r.status_code, "body": corpo}

        try:
            with httpx.Client(cookies=cookies, headers=_HEADERS_HTTP, timeout=25.0,
                              follow_redirects=False) as client:
                cur = _get(client, _EP_CURRENT)
                school_id = str((cur.get("body") or {}).get("school_id") or "").strip()
                if not school_id:
                    raise ErroConector("HTTP: não achei o school_id (accounts/current).",
                                       codigo="sessao_invalida", recuperavel=True)
                esperada = (escola_esperada or "").strip().lower()
                if esperada and school_id.lower() != esperada:
                    raise ErroConector(
                        f"A conta do Matific cadastrada nesta escola é da escola {school_id} "
                        f"da plataforma, mas esta escola está vinculada à {esperada}. Nada "
                        "foi consultado: confira se a credencial é desta escola.",
                        codigo=escola_externa.ESCOLA_TROCADA, recuperavel=False)
                if school_id.lower() in {str(s).lower() for s in escolas_recusadas or ()}:
                    raise ErroConector(
                        f"A conta do Matific cadastrada nesta escola é da escola {school_id} "
                        "da plataforma, já vinculada a outra escola do Constela. Nada foi "
                        "consultado: confira se a credencial é desta escola.",
                        codigo=escola_externa.ESCOLA_EM_OUTRA_ESCOLA, recuperavel=False)
                # competition_id (nomes completos) — ACESSÓRIO: engole QUALQUER
                # falha (inclusive um 403/non-JSON que _get mapeia p/ sessao_
                # invalida). A sessão de verdade é validada por accounts/current
                # (acima) e school_student (abaixo); não deixamos o placar cair por
                # causa do nome completo, que é só um plus.
                comp_id = ""
                try:
                    comps = _get(client, _EP_COMPETITIONS).get("body")
                    if isinstance(comps, list):
                        vivos = [c for c in comps if isinstance(c, dict) and c.get("id")]
                        alvo = next((c for c in vivos if c.get("is_live")),
                                    vivos[0] if vivos else None)
                        comp_id = str((alvo or {}).get("id") or "").strip()
                except Exception:  # noqa: BLE001 — acessório, não derruba a coleta
                    comp_id = ""
                nomes: dict = {}
                if comp_id:
                    url_lb = (f"{_API_BASE}/api/v2/competition-v2/{comp_id}"
                              f"/school/{school_id}/student-leaderboard/")
                    try:
                        nomes = self._mapa_nomes(_get(client, url_lb))
                    except Exception:  # noqa: BLE001 — nome cheio é um plus
                        nomes = {}
                url_ss = (f"{_API_BASE}/api/v2/reports/leaderboard/school_student/"
                          f"?{filtro}&school_id={school_id}")
                res_ss = _get(client, url_ss)
                self._conferir_escola_do_corpo(res_ss, school_id)
                return self._parse_school_student(res_ss, nomes)
        except ErroConector:
            raise
        except httpx.HTTPError as exc:
            # Falha de transporte (rede/timeout/conexão): não é "sessão inválida",
            # mas o chamador deve cair para o navegador (fetch same-origin).
            raise ErroConector(f"HTTP ao Matific indisponível ({str(exc)[:80]}).",
                               codigo="http_indisponivel", recuperavel=True) from exc

    async def autenticar(self, cred: Credenciais, contexto: Contexto, *,
                         storage_state: dict | None = None) -> dict:
        """Usa o navegador APENAS para autenticar (item de arquitetura: navegador
        só para login/fallback) e devolve o storage_state (cookies) para as
        consultas HTTP. Reaproveita a sessão salva quando ainda válida."""
        async with self._sessao(contexto, storage_state=storage_state) as nav:
            logado = False
            if storage_state:
                try:
                    await nav.ir_para(_URL_LEADERBOARD)
                    logado = await self._sessao_valida(nav)
                except Exception:  # noqa: BLE001
                    logado = False
            if logado:
                contexto.log("login", "info", "[Matific] Sessão reaproveitada (auth).")
            else:
                await self._login(nav, cred, contexto)
                await nav.ir_para(_URL_LEADERBOARD)
            try:
                return await nav.estado_sessao()
            except Exception:  # noqa: BLE001
                return {}

    async def coletar_placar_ao_vivo(
        self, cred: Credenciais, contexto: Contexto, *, filtro: str,
        storage_state: dict | None = None,
    ) -> tuple[list[dict], dict | None]:
        """Consulta em TEMPO REAL o Placar do Matific para o ``filtro`` e devolve
        ``(alunos, novo_storage_state)``. Reusa ``storage_state`` (sessão de um
        login anterior): se ainda válida, PULA o login (rápido); senão, loga. O
        chamador persiste o ``novo_storage_state`` cifrado para a próxima consulta
        já sair rápida. Não escreve nada no banco — é leitura pura do período."""
        async with self._sessao(contexto, storage_state=storage_state) as nav:
            logado = False
            if storage_state:
                try:
                    await nav.ir_para(_URL_LEADERBOARD)
                    logado = await self._sessao_valida(nav)
                except Exception:  # noqa: BLE001 — sessão ruim: refaz o login
                    logado = False
            if logado:
                contexto.log("login", "info",
                             "[Matific] Sessão reaproveitada — sem novo login.")
            else:
                await self._login(nav, cred, contexto)
            alunos = await self._coletar_do_placar(nav, filtro, contexto.log,
                                                   conferir_escola=contexto)
            try:
                novo_estado = await nav.estado_sessao()
            except Exception:  # noqa: BLE001 — sem estado, só perde o atalho
                novo_estado = None
            return alunos, novo_estado

    async def sincronizar(self, cred: Credenciais,
                          contexto: Contexto) -> list[ArquivoObtido]:
        """Coleta o Placar da Escola pela API INTERNA do Matific (sem PDF):
        loga, captura o school_id/competition_id que a página dispara, chama
        school_student (com o período) + student-leaderboard (nomes completos),
        cruza por uuid e emite UM ArquivoObtido (JSON) por turma. O orquestrador
        importa cada um pelo mesmo ``confirmar`` do Excel (atividades/estrelas/
        média). Idempotente.

        Placar que respondeu 2xx sem nenhum aluno devolve ``[]`` (o serviço
        registra 'sem_dados'); escola não localizada ou HTTP de erro LEVANTAM
        (o serviço registra 'erro' com alerta) — antes os dois viravam "sem dados".
        """
        log = contexto.log
        arquivos: list[ArquivoObtido] = []
        extra = getattr(cred, "extra", None) or {}
        # Período personalizado (premiação por semana/mês): se vierem as datas,
        # usa ?start_date=&end_date= (import POR PERÍODO); senão, ?duration=.
        pi = str(extra.get("matific_start_date") or "").strip()
        pf = str(extra.get("matific_end_date") or "").strip()
        duration = str(extra.get("matific_duration") or "").strip() or _DURATION_PADRAO
        dt_i, dt_f = _parse_data(pi), _parse_data(pf)
        if pi and pf:
            if dt_i is None or dt_f is None:
                # Data que não existe (2026-02-31) ou fora do formato: sem ela o
                # arquivo sairia SEM período e o pipeline gravaria os números do
                # período como ACUMULADO (sem a trava de queda). A rota já recusa;
                # esta trava cobre uma execução antiga na fila ou de outro caminho.
                raise ErroConector(f"Período inválido: {pi} a {pf} (data inexistente).",
                                   codigo="periodo_invalido", recuperavel=False)
            if dt_i is not None and dt_f is not None and dt_i == dt_f \
                    and not periodo_um_dia_permitido():
                # A rota já recusa; esta trava cobre uma execução antiga na fila
                # (ou criada por outro caminho) com início = fim.
                raise ErroConector(MSG_UM_DIA, codigo="periodo_invalido", recuperavel=False)
            fim_filtro = (end_date_do_filtro(dt_f.date()).isoformat()
                          if dt_f is not None else pf)
            filtro = f"start_date={pi}&end_date={fim_filtro}"
            rotulo_periodo = f"{pi} a {pf}"
            # A importação por período data o retrato 1 s antes deste limite.
            dt_f = limite_exclusivo_do_retrato(dt_f) if dt_f is not None else None
        else:
            filtro = f"duration={duration}"
            rotulo_periodo = duration
        async with self._sessao(contexto) as nav:
            await self._login(nav, cred, contexto)
            alunos = await self._coletar_do_placar(nav, filtro, log, contexto)
            if not (pi and pf) and getattr(contexto, "coleta", None) is not None:
                # Acumulado do ano: o serviço confere quais contas JÁ vinculadas
                # não vieram (resposta parcial do Placar não pode passar calada).
                contexto.coleta["ids_recebidos"] = sorted(
                    {a["uuid"] for a in alunos if a.get("uuid")})
            if not alunos:
                return arquivos

            alunos = _separar_uuids_em_varias_turmas(alunos, contexto, log)
            if not alunos:
                return arquivos
            # UM ArquivoObtido por turma (reusa o pipeline do Excel do Matific).
            por_turma: dict[str, list] = {}
            for a in alunos:
                # Campo numérico que NÃO veio vai NULO (não 0): a importação
                # reconhece o campo ausente e não grava retrato herdado.
                for campo in a.pop("ausentes", None) or ():
                    a[campo] = None
                por_turma.setdefault(a["turma"], []).append(a)
            for turma, lista in por_turma.items():
                payload = {"turma": turma, "alunos": lista,
                           "periodo_inicio": pi, "periodo_fim": pf}
                arquivos.append(ArquivoObtido(
                    conteudo=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    nome_arquivo=f"matific_{_slug(turma)}.json",
                    plataforma="matific", content_type=_CT_API,
                    formato_hint="resumo",
                    # Com datas → import POR PERÍODO (o orquestrador lê daqui).
                    periodo_inicio=dt_i, periodo_fim=dt_f,
                    metadados={"origem": "api", "periodo": rotulo_periodo}))
            # Sem PII: só contagens (nome completo casado / abreviado).
            com_nome = sum(1 for a in alunos if a["nome"] != a["nome_abrev"])
            log("download", "info",
                f"[Matific] {len(alunos)} aluno(s) em {len(por_turma)} turma(s) "
                f"(período {rotulo_periodo}; {com_nome} com nome completo).")
        return arquivos
