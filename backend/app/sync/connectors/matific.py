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

# --- Contrato de UI com o Matific (verificado em jul/2026) -------------------
# A página de login mudou de "/account/login/" (que hoje redireciona p/ a home
# de marketing) para "/login-page/". Campos: #username-input / #password-input;
# botão "Continuar" (#login-button). Um aviso de cookies aparece antes e é
# apenas DISPENSADO (nunca "Aceitar Todos"). Endereço configurável via
# extra['url_login'].
_URL_LOGIN = "https://www.matific.com/bra/pt-br/login-page/"
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
    def _parse_school_student(res, nomes: dict) -> list[dict]:
        """school_student → [{nome, uuid, turma, estrelas, atividades}]. Usa o
        nome COMPLETO (via ``nomes``) quando houver; senão, o abreviado do Placar.
        Pula linhas-fantasma (sem nome/turma — vêm zeradas no fim do relatório)."""
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
            if not abrev or not turma:   # fantasma (uuid vazio / turma vazia)
                continue
            nome = nomes.get(uuid) or abrev
            alunos.append({
                "nome": nome, "nome_abrev": abrev, "uuid": uuid, "turma": turma,
                "serie": str(it.get("grade_code") or "").strip(),
                "estrelas": _para_int(it.get("score")),
                "atividades": _para_int(it.get("activities_completed")),
            })
        return alunos

    async def sincronizar(self, cred: Credenciais,
                          contexto: Contexto) -> list[ArquivoObtido]:
        """Coleta o Placar da Escola pela API INTERNA do Matific (sem PDF):
        loga, captura o school_id/competition_id que a página dispara, chama
        school_student (com o período) + student-leaderboard (nomes completos),
        cruza por uuid e emite UM ArquivoObtido (JSON) por turma. O orquestrador
        importa cada um pelo mesmo ``confirmar`` do Excel (atividades/estrelas/
        média). Idempotente. Falha aqui NÃO derruba a sync (cai no upload manual).
        """
        log = contexto.log
        arquivos: list[ArquivoObtido] = []
        extra = getattr(cred, "extra", None) or {}
        # Período personalizado (premiação por semana/mês): se vierem as datas,
        # usa ?start_date=&end_date= (import POR PERÍODO); senão, ?duration=.
        pi = str(extra.get("matific_start_date") or "").strip()
        pf = str(extra.get("matific_end_date") or "").strip()
        duration = str(extra.get("matific_duration") or "").strip() or _DURATION_PADRAO
        if pi and pf:
            filtro = f"start_date={pi}&end_date={pf}"
            rotulo_periodo = f"{pi} a {pf}"
        else:
            filtro = f"duration={duration}"
            rotulo_periodo = duration
        async with self._sessao(contexto) as nav:
            await self._login(nav, cred, contexto)
            # A página do Placar dispara as chamadas internas ao carregar; captura-
            # mos os ids delas (school_id/competition_id) para então reconsultar
            # com o PERÍODO desejado.
            caps = await nav.coletar_respostas(_URL_LEADERBOARD, timeout_s=25)
            school_id, comp_id = self._ids_do_placar(caps)
            if not school_id:
                log("navegacao", "warn",
                    "[Matific] não achei o school_id no Placar da Escola — "
                    "usando o upload manual do relatório.")
                return arquivos
            log("navegacao", "info", "[Matific] Placar da Escola localizado.")

            # Nomes completos (uuid → nome) da competição, quando houver.
            nomes: dict = {}
            if comp_id:
                url_lb = (f"{_API_BASE}/api/v2/competition-v2/{comp_id}"
                          f"/school/{school_id}/student-leaderboard/")
                try:
                    nomes = self._mapa_nomes(await nav.avaliar(_js_get(url_lb)))
                except Exception as exc:  # noqa: BLE001 — nome cheio é um plus, não bloqueia
                    log("download", "warn",
                        f"[Matific] student-leaderboard falhou ({str(exc)[:80]}).")

            # Dados por aluno (estrelas/atividades) no período pedido.
            url_ss = (f"{_API_BASE}/api/v2/reports/leaderboard/school_student/"
                      f"?{filtro}&school_id={school_id}")
            try:
                res = await nav.avaliar(_js_get(url_ss))
            except Exception as exc:  # noqa: BLE001
                raise ErroConector(
                    f"Placar do Matific falhou na API ({str(exc)[:80]}).",
                    codigo="falha_download", recuperavel=True) from exc
            alunos = self._parse_school_student(res, nomes)
            if not alunos:
                log("download", "warn",
                    f"[Matific] Placar sem alunos (status "
                    f"{(res or {}).get('status') if isinstance(res, dict) else '?'}).")
                return arquivos

            # UM ArquivoObtido por turma (reusa o pipeline do Excel do Matific).
            por_turma: dict[str, list] = {}
            for a in alunos:
                por_turma.setdefault(a["turma"], []).append(a)
            dt_i, dt_f = _parse_data(pi), _parse_data(pf)
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
