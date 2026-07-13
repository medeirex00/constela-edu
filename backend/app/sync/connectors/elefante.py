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

import asyncio
import json
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

# --- Contrato de UI com o Elefante (verificado em jul/2026) ------------------
# O login mudou para o subdomínio "login.elefanteletrado.com.br/welcome" (o
# antigo "/login" hoje dá 404). É um SPA Angular em 2 passos: primeiro escolhe
# o perfil "Sou professor ou gestor", depois mostra o formulário (campos
# name=Username / name=Password). Endereço configurável via extra['url_login'].
# Vai DIRETO para o login de professor/gestor ("/manager"). O "/welcome" pede
# antes o perfil; se por acaso cair nele, o passo de escolher perfil (abaixo) é
# executado como fallback.
_URL_LOGIN = "https://login.elefanteletrado.com.br/manager"
# Área LOGADA fica em admin.elefanteletrado.com.br (mapeado por prints do gestor,
# jul/2026) — NÃO no www marketing. Relatórios parametrizados por URL:
#   turma:  /reports/course?period=PERIODS.LIFETIME&products=1&courseId={id}
#   aluno:  /reports/student/{studentId}?period=PERIODS.LIFETIME&products=1&courseId={id}
_URL_APP = "https://admin.elefanteletrado.com.br"
_URL_REPORTS_MENU = f"{_URL_APP}/reports/menu"
_URL_RELATORIOS = _URL_REPORTS_MENU  # compat: descritor legado aponta p/ o menu real
_PERIODO_TUDO = "PERIODS.LIFETIME"    # "Desde o início" (confirmado nas URLs reais)
_URL_COURSE = (_URL_APP + "/reports/course?period=" + _PERIODO_TUDO
               + "&products=1&courseId={course_id}")
_URL_STUDENT = (_URL_APP + "/reports/student/{student_id}?period=" + _PERIODO_TUDO
                + "&products=1&courseId={course_id}")

# SPA Angular: após navegar (domcontentloaded), os dados vêm por XHR — dá um
# tempo curto para renderizar antes de ler o DOM. Tests zeram (_SETTLE_S=0).
_SETTLE_S = 1

# Extrai CANDIDATOS a id numérico (turma/aluno) de ONDE quer que estejam —
# options de <select>, hrefs de /reports/course|student, ou data-*. Robusto a
# qualquer biblioteca de dropdown (não depende de clicar num componente frágil).
_JS_IDS = r"""(() => {
  const uniq = (a) => Array.from(new Set(a)).filter(Boolean);
  const num = (v) => { const m = String(v==null?'':v).match(/([0-9]{3,})/); return m ? m[1] : ''; };
  const q = (s) => Array.from(document.querySelectorAll(s));
  return {
    n_selects: document.querySelectorAll('select').length,
    n_options: document.querySelectorAll('option').length,
    option_ids: uniq(q('option').map(o => num(o.value))).slice(0,120),
    course_links: uniq(q("a[href*='course']").map(a => { const m=(a.getAttribute('href')||a.href||'').match(/courseId=([0-9]+)/); return m?m[1]:''; })).slice(0,120),
    student_links: uniq(q("a[href*='student']").map(a => { const m=(a.getAttribute('href')||a.href||'').match(/student\/([0-9]+)/); return m?m[1]:''; })).slice(0,120),
    data_ids: uniq(q('[data-course-id],[data-student-id],[data-id],[data-value]').map(e => num(e.getAttribute('data-course-id')||e.getAttribute('data-student-id')||e.getAttribute('data-id')||e.getAttribute('data-value')))).slice(0,120),
  };
})()"""

# Confirma o botão Exportar dentro do relatório (existe? texto? tag?).
_JS_EXPORTAR = r"""(() => {
  const c = Array.from(document.querySelectorAll('button, a, [role=button]'))
    .filter(e => /exportar/i.test((e.textContent||'') + ' ' + (e.getAttribute('aria-label')||'')));
  return { tem_exportar: c.length > 0, n: c.length,
           textos: c.slice(0,3).map(e => (e.textContent||'').trim().slice(0,24)),
           tags: c.slice(0,3).map(e => e.tagName) };
})()"""
_SEL_EXPORTAR = ("button:has-text('Exportar'), a:has-text('Exportar'), "
                 "[role='button']:has-text('Exportar')")
# O relatório do aluno só RENDERIZA depois de submeter a busca (os params vão na
# URL, mas é o "Pesquisar" que executa a consulta — dispara a API de dados e
# revela o Exportar). Ancorado no texto (rótulo estável), não em classe CSS.
_SEL_PESQUISAR = ("button:has-text('Pesquisar'), [role='button']:has-text('Pesquisar'), "
                  "input[type='submit'][value='Pesquisar']")

# Fallback do browser (relatório por aluno) é lento e instável — mantido só como
# última tentativa RÁPIDA de poucos alunos. O caminho principal dos dados é a API
# interna (in-page fetch), como o roster.
_LIMITE_ALUNOS = 2

# Endpoint interno que lista turmas + alunos aninhados (host prod-ecs-apiadmin…).
_EP_CURSOS = "/course/get-courses-students"

# CHAMA a API interna direto da PÁGINA autenticada (in-page fetch). Usado quando o
# SPA não dispara /course/get-courses-students sozinho — ele só o faz depois de
# selecionar a escola e clicar "Pesquisar" (corrida). Em vez de clicar em
# componentes Angular frágeis, reproduzimos a chamada com o MESMO token que o SPA
# já mandou. page.evaluate aguarda a promise; devolve status/corpo (sem PII).
# credentials: 'omit' quando há Authorization (evita conflito CORS '*'+credenciais);
# 'include' quando a auth é por cookie (sem header capturado).
_JS_FETCH_TMPL = r"""(async () => {
  try {
    const opts = { method: __METHOD__, credentials: __CREDS__,
                   headers: Object.assign({}, __HEADERS__) };
    const corpo = __BODY__;
    if (corpo !== null) {                 // POST com JSON (relatórios /report/*)
      opts.body = JSON.stringify(corpo);
      opts.headers['Content-Type'] = 'application/json';
    }
    const r = await fetch(__URL__, opts);
    let body = null;
    try { body = await r.json(); } catch (e) { body = null; }
    return { ok: r.ok, status: r.status,
             tipo: Array.isArray(body) ? 'list' : (body === null ? 'null' : typeof body),
             n: Array.isArray(body) ? body.length : 0, body: body };
  } catch (e) { return { ok: false, status: 0, tipo: 'erro',
                         erro: String(e).slice(0, 160), body: null }; }
})()"""

# Diagnóstico da tela do aluno quando o Exportar não aparece: quais botões há?
_JS_PAGINA_ALUNO = r"""(() => {
  const t = (e) => (e.textContent || '').trim().slice(0, 20);
  const btns = Array.from(document.querySelectorAll('button, a, [role=button]'))
    .map(t).filter(Boolean);
  return { url: location.href, tem_exportar: btns.some(x => /exportar/i.test(x)),
           botoes: Array.from(new Set(btns)).slice(0, 25) };
})()"""
_SEL_PERFIL_GESTOR = ("button:has-text('professor'), button:has-text('gestor'), "
                      "button:has-text('Sou professor')")
_SEL_USUARIO = ("input[name='Username'], input[placeholder='Digite seu login'], "
                "input[name='email'], input[type='email']")
_SEL_SENHA = "input[name='Password'], input[type='password']"
_SEL_ENTRAR = ("input[type='submit'][value='Entrar'], .custom-button[type='submit'], "
               "button:has-text('Entrar')")
_SEL_ERRO_LOGIN = ".error, .alert-danger, .invalid-feedback, [role='alert']"
# Indicadores de "já entrou" — evita `nav` genérico (existe na tela de login).
_SEL_LOGADO = ("a[href*='logout'], a[href*='sair'], a[href*='sign-out'], "
               "[class*='painel' i], [class*='dashboard' i]")
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
        # Fluxo instrumentado (logs por etapa + detecção de CAPTCHA) no base.
        await self._executar_login(nav, cred, contexto, **self._config_login())

    def _config_login(self) -> dict:
        """URL + seletores do login. Usado pelo fluxo real E pelo diagnóstico.
        Pré-passo (fallback): se cair na tela de boas-vindas, escolhe o perfil."""
        return dict(url=_URL_LOGIN, sel_usuario=_SEL_USUARIO, sel_senha=_SEL_SENHA,
                    sel_entrar=_SEL_ENTRAR, sel_logado=_SEL_LOGADO,
                    sel_erro=_SEL_ERRO_LOGIN, pre_passos=(_SEL_PERFIL_GESTOR,),
                    nome="Elefante")

    @staticmethod
    async def _assentar(nav) -> None:
        """Dá tempo do SPA carregar os dados por XHR após a navegação."""
        if _SETTLE_S:
            await asyncio.sleep(_SETTLE_S)

    async def diagnosticar_navegacao(self, cred: Credenciais,
                                     contexto: Contexto) -> dict:
        """RECON de ponta a ponta (SEM PII): loga, entra no admin, ENUMERA as
        turmas, entra numa turma, ENUMERA os alunos, abre o relatório de UM
        aluno e CONFIRMA o Exportar — chegando a baixar o PDF só para provar que
        a cadeia funciona (conta bytes; NÃO importa/persiste nada). Reporta
        contagens e ids (nunca nomes de aluno) para calibrar a coleta real."""
        r = {"plataforma": self.plataforma, "url_pos_login": None,
             "sessao_admin_ok": False, "erro": None,
             "turmas": {}, "alunos": {}, "aluno_report": {},
             "exportar": {}, "download": {}}
        try:
            async with self._sessao(contexto) as nav:
                await self._login(nav, cred, contexto)
                await nav.ir_para(_URL_REPORTS_MENU)
                atual = await nav.url_atual()
                r["url_pos_login"] = atual
                r["sessao_admin_ok"] = "admin.elefanteletrado.com.br" in (atual or "")

                # 1) TURMAS — abre a tela de turma (sem courseId) e extrai ids.
                await nav.ir_para(_URL_COURSE.format(course_id=""))
                await self._assentar(nav)
                ids_t = await nav.avaliar(_JS_IDS)
                turmas = (ids_t.get("course_links") or ids_t.get("option_ids")
                          or ids_t.get("data_ids") or [])
                r["turmas"] = {"n_selects": ids_t.get("n_selects"),
                               "n_options": ids_t.get("n_options"),
                               "candidatas": len(turmas), "amostra": turmas[:5]}
                if not turmas:
                    return r
                cid = turmas[0]

                # 2) ALUNOS — abre a turma (com courseId) e extrai ids de aluno.
                await nav.ir_para(_URL_COURSE.format(course_id=cid))
                await self._assentar(nav)
                ids_a = await nav.avaliar(_JS_IDS)
                alunos = (ids_a.get("student_links")
                          or [x for x in (ids_a.get("option_ids") or []) if x != cid]
                          or ids_a.get("data_ids") or [])
                r["alunos"] = {"n_options": ids_a.get("n_options"),
                               "candidatos": len(alunos), "amostra": alunos[:5]}
                if not alunos:
                    return r
                sid = alunos[0]

                # 3) RELATÓRIO DO ALUNO — confirma o Exportar e prova o download.
                await nav.ir_para(_URL_STUDENT.format(student_id=sid, course_id=cid))
                await self._assentar(nav)
                r["aluno_report"] = {"url": await nav.url_atual()}
                r["exportar"] = await nav.avaliar(_JS_EXPORTAR)
                if r["exportar"].get("tem_exportar"):
                    try:
                        conteudo, nome = await nav.baixar_acao(
                            lambda: nav.clicar(_SEL_EXPORTAR),
                            timeout_s=min(contexto.timeout_s, 45))
                        r["download"] = {
                            "ok": True, "bytes": len(conteudo or b""),
                            "parece_pdf": (conteudo or b"")[:5] == b"%PDF-"}
                    except Exception as exc:  # noqa: BLE001
                        r["download"] = {"ok": False,
                                         "erro": f"{type(exc).__name__}: {str(exc)[:80]}"}
        except ErroConector as exc:
            r["erro"] = f"{exc.codigo}: {str(exc)[:140]}"
        except Exception as exc:  # noqa: BLE001
            r["erro"] = f"{type(exc).__name__}: {str(exc)[:140]}"
        return r

    @staticmethod
    def _ids_do_json(obj, chaves: tuple) -> list[str]:
        """Extrai ids de ENTIDADES de um JSON: para cada objeto que é item de uma
        lista e tem um campo id-like (`chaves`), pega esse id. Assim pega "lista
        de turmas/alunos" sem varrer ids aninhados (livro, atividade…)."""
        achados: list[str] = []

        def anda(o):
            if isinstance(o, list):
                for item in o:
                    if isinstance(item, dict):
                        for k in chaves:
                            v = item.get(k)
                            if isinstance(v, (int, str)) and str(v).isdigit():
                                achados.append(str(v))
                                break
                    anda(item)
            elif isinstance(o, dict):
                for v in o.values():
                    anda(v)

        anda(obj)
        return achados

    @staticmethod
    def _forma_json(obj, prof: int = 0) -> str:
        """Forma (nomes de campos, SEM valores/PII) de um JSON — p/ eu ver como
        extrair os ids quando a heurística falha, num único log."""
        if isinstance(obj, list):
            return f"[{len(obj)}]" + (ConectorElefante._forma_json(obj[0], prof + 1)
                                      if obj and prof < 2 else "")
        if isinstance(obj, dict):
            return "{" + ",".join(list(obj.keys())[:12]) + "}"
        return type(obj).__name__

    @staticmethod
    def _diag_alunos(cursos: list) -> str:
        """Diagnóstico SEM PII de onde estão os alunos numa lista de turmas: para
        a 1ª turma, mostra o TIPO de cada campo candidato a lista de alunos e, se
        for lista, as CHAVES do 1º elemento (nunca os valores/nomes) + o tamanho.
        Se for número, é contagem (os alunos vêm de outro endpoint)."""
        if not (isinstance(cursos, list) and cursos and isinstance(cursos[0], dict)):
            return "sem turma para inspecionar"
        curso = cursos[0]
        partes = []
        for chave in ("student", "students", "alunos", "studentList", "studentCount"):
            if chave not in curso:
                continue
            v = curso[chave]
            if isinstance(v, list):
                elem = (sorted(v[0].keys())[:12] if v and isinstance(v[0], dict)
                        else (type(v[0]).__name__ if v else "vazia"))
                partes.append(f"{chave}=lista[{len(v)}] campos_do_1o={elem}")
            elif isinstance(v, (int, float, bool)):
                partes.append(f"{chave}={type(v).__name__}={v}")  # nº = contagem, não PII
            elif isinstance(v, dict):
                partes.append(f"{chave}=dict{sorted(v.keys())[:12]}")
            else:
                partes.append(f"{chave}={type(v).__name__}")
        return "; ".join(partes) or "nenhum campo de aluno reconhecível"

    @staticmethod
    def _api_elefante(url: str) -> bool:
        """Resposta da API do Elefante (qualquer host *.elefanteletrado.com.br),
        ignorando i18n/assets e trackers de terceiros (userway/cdn)."""
        u = (url or "").lower()
        return ("elefanteletrado.com.br" in u and "/assets/" not in u
                and "i18n" not in u and "userway" not in u)

    @staticmethod
    def _parse_courses_students(caps: list) -> dict:
        """Da resposta REAL `/course/get-courses-students`: mapa PRECISO
        {course_id: [student_ids]} — turma.id + os ids do campo `student` de
        CADA turma (sem varrer ids aninhados que geram ruído)."""
        mapa: dict[str, list[str]] = {}

        def _num(v) -> str:
            return str(v) if isinstance(v, (int, str)) and str(v).isdigit() else ""

        for c in caps:
            if "get-courses-students" not in c["url"]:
                continue
            j = c.get("json")
            if not isinstance(j, list):
                continue
            for curso in j:
                if not isinstance(curso, dict):
                    continue
                cid = _num(curso.get("id"))
                if not cid:
                    continue
                sids: list[str] = []
                # A lista de alunos pode vir sob chaves diferentes; cada aluno pode
                # ter o id sob chaves diferentes. Aceita tudo que for LISTA (se for
                # int, é contagem — cai fora e o diagnóstico avisa).
                alunos = None
                for chave in ("student", "students", "alunos", "studentList",
                              "studentsList", "studentList "):
                    v = curso.get(chave)
                    if isinstance(v, list):
                        alunos = v
                        break
                if isinstance(alunos, list):
                    for al in alunos:
                        if isinstance(al, dict):
                            v = _num(al.get("id") or al.get("studentId")
                                     or al.get("userId") or al.get("personId")
                                     or al.get("alunoId"))
                        else:
                            v = _num(al)
                        if v and v not in sids:
                            sids.append(v)
                mapa.setdefault(cid, [])
                for s in sids:
                    if s not in mapa[cid]:
                        mapa[cid].append(s)
        return mapa

    @staticmethod
    def _origem(url: str) -> str:
        """scheme://host de uma URL (base da API interna capturada)."""
        from urllib.parse import urlsplit
        p = urlsplit(url or "")
        return f"{p.scheme}://{p.netloc}" if p.netloc else ""

    @staticmethod
    def _js_fetch(url: str, metodo: str, headers: dict, creds: str,
                  corpo: dict | None = None) -> str:
        """Monta o fetch in-page com os valores injetados de forma segura
        (json.dumps → sem quebrar aspas nem template). `corpo` != None → POST JSON."""
        return (_JS_FETCH_TMPL
                .replace("__URL__", json.dumps(url))
                .replace("__METHOD__", json.dumps(metodo))
                .replace("__HEADERS__", json.dumps(headers))
                .replace("__CREDS__", json.dumps(creds))
                .replace("__BODY__", json.dumps(corpo)))

    @classmethod
    def _base_e_auth(cls, caps: list) -> tuple[str, dict, str, str]:
        """Descobre a base da API interna (prod-ecs-apiadmin…) e o Authorization
        que o SPA já mandou — para o conector CHAMAR a API direto (in-page fetch),
        reusando a mesma sessão. Devolve (base, headers, creds, auth)."""
        api = [c for c in caps if cls._api_elefante(c["url"])]
        base = ""
        for c in api:
            o = cls._origem(c["url"])
            if o and ("apiadmin" in o or "/school" in c["url"] or "/course" in c["url"]):
                base = o
                break
        base = base or (cls._origem(api[0]["url"]) if api else "")
        auth = next((c.get("req_auth") for c in api if c.get("req_auth")), "")
        headers = {"Authorization": auth} if auth else {}
        creds = "omit" if auth else "include"   # Bearer → sem cookie (evita CORS *)
        return base, headers, creds, auth

    @staticmethod
    def _amostra_roster(cursos: list) -> str:
        """Campos (CHAVES, sem valores/PII) da 1ª turma e do 1º aluno do roster —
        revela se os DADOS DE LEITURA já vêm embutidos no aluno (aí extraímos na
        hora) ou se só há id/nome (aí buscamos os dados noutro endpoint)."""
        if not (isinstance(cursos, list) and cursos and isinstance(cursos[0], dict)):
            return ""
        t = cursos[0]
        acampos: list = []
        for k in ("student", "students", "alunos", "studentList"):
            v = t.get(k)
            if isinstance(v, list) and v and isinstance(v[0], dict):
                acampos = sorted(v[0].keys())[:24]
                break
        return f"turma_campos={sorted(t.keys())[:24]} aluno_campos={acampos}"

    @staticmethod
    def _school_id(caps: list) -> str:
        """schoolId da resposta /school/active-schools (para o overall-school-report)."""
        for c in caps:
            if "active-schools" in c["url"] and isinstance(c.get("json"), list):
                for e in c["json"]:
                    if isinstance(e, dict) and str(e.get("id", "")).isdigit():
                        return str(e["id"])
        return ""

    @staticmethod
    def _corpo_relatorio(**extra) -> dict:
        """Corpo POST dos endpoints /report/* (formato capturado por DevTools do
        gestor): período LIFETIME com datas amplas + fuso do Brasil. `extra` traz
        studentId/schoolId/etc."""
        hoje = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        corpo = {"startPeriodCustom": "2010-01-01", "endPeriodCustom": hoje,
                 "timezoneOffset": 180, "languageId": 1, "period": _PERIODO_TUDO}
        corpo.update(extra)
        return corpo

    @classmethod
    def _estrutura(cls, obj, prof: int = 0, max_prof: int = 5) -> str:
        """Árvore de TIPOS/CHAVES de um JSON (SEM valores → sem PII: nomes de livro,
        de aluno etc. nunca aparecem). Revela onde estão leituras/livros/questões
        para eu escrever o parser dos eventos com precisão."""
        if isinstance(obj, dict):
            if prof >= max_prof:
                return "{…}"
            return "{" + ", ".join(
                f"{k}:{cls._estrutura(v, prof + 1, max_prof)}"
                for k, v in list(obj.items())[:40]) + "}"
        if isinstance(obj, list):
            return "[]" if not obj else f"[{len(obj)}×{cls._estrutura(obj[0], prof + 1, max_prof)}]"
        if isinstance(obj, bool):
            return "bool"
        if isinstance(obj, (int, float)):
            return "num"
        if isinstance(obj, str):
            return "str"        # NUNCA o valor
        return "null" if obj is None else type(obj).__name__

    async def _diagnosticar_relatorio_api(self, nav, log, caps: list, mapa: dict) -> None:
        """Chama a API REAL dos dados (/report/overall-*, POST — descoberta por
        DevTools) e loga a ESTRUTURA da resposta (só tipos/chaves, sem PII). É o
        mapa para o parser final que vira eventos da linha do tempo."""
        base, headers, creds, _auth = self._base_e_auth(caps)
        if not base:
            return
        escola = self._school_id(caps)
        cid = next((c for c in mapa if mapa[c]), next(iter(mapa), ""))
        sid = mapa.get(cid, [""])[0] if cid else ""
        alvos = []
        # overall-course-report: dados por ALUNO dentro da turma (10 chamadas p/ a
        # escola toda) — provável caminho definitivo, e evita o 403 do per-aluno.
        if cid.isdigit():
            corpo_curso = self._corpo_relatorio(courseId=int(cid),
                                                useCache=True, selectedProducts="")
            if escola.isdigit():
                corpo_curso["schoolId"] = int(escola)
            alvos.append(("overall-course-report", corpo_curso))
        # per-aluno deu 403 SEM courseId → tenta COM o contexto da turma.
        if sid.isdigit() and cid.isdigit():
            alvos += [
                ("overall-student-report",
                 self._corpo_relatorio(studentId=int(sid), courseId=int(cid))),
                ("overall-student-books-read",
                 self._corpo_relatorio(studentId=int(sid), courseId=int(cid))),
            ]
        if escola.isdigit():
            alvos.append(("overall-school-report",
                          self._corpo_relatorio(schoolId=int(escola),
                                                useCache=True, selectedProducts="")))
        for nome, corpo in alvos:
            url = f"{base}/report/{nome}"
            try:
                res = await nav.avaliar(self._js_fetch(url, "POST", headers, creds, corpo))
            except Exception as exc:  # noqa: BLE001
                res = {"status": "exc", "erro": str(exc)[:80]}
            res = res if isinstance(res, dict) else {}
            det = f"{res.get('status')}/{res.get('tipo')}"
            if res.get("erro"):
                det += f" {res['erro']}"
            if res.get("status") == 200:
                det += " estrutura=" + self._estrutura(res.get("body"))
            log("navegacao", "info",
                f"[Elefante] /report/{nome} → " + det[:1700])

    async def _cursos_alunos_via_api(self, nav, log, caps: list) -> dict:
        """FALLBACK robusto: quando o SPA não disparou /course/get-courses-students
        (depende de selecionar escola + Pesquisar — corrida), chama a API interna
        DIRETO da página autenticada. Descobre host + token do tráfego que SEMPRE
        dispara (/school/active-schools) e reusa o MESMO Authorization. Sem clicar
        em nada. Devolve {course_id: [student_ids]} (ou {})."""
        base, headers, creds, auth = self._base_e_auth(caps)
        if not base:
            return {}
        # Escolas (id) de /school/active-schools — a maioria das contas tem 1.
        escolas: list[str] = []
        for c in caps:
            if "active-schools" in c["url"] and isinstance(c.get("json"), list):
                for e in c["json"]:
                    if isinstance(e, dict) and str(e.get("id", "")).isdigit():
                        sid = str(e["id"])
                        if sid not in escolas:
                            escolas.append(sid)
        # Candidatos (o 1º que trouxer ALUNO vence): sem params (o JWT já carrega a
        # escola); por escola; e por escola COM os filtros que a UI usa (period/
        # products) — os alunos aninhados podem só popular com esses parâmetros.
        ep = f"{base}{_EP_CURSOS}"
        filtros = f"period={_PERIODO_TUDO}&products=1"
        candidatos = [("GET", ep)]
        for sid in escolas:
            candidatos.append(("GET", f"{ep}?schoolId={sid}"))
            candidatos.append(("GET", f"{ep}?schoolId={sid}&{filtros}"))
        resumo: list[str] = []
        # Guarda o melhor "turmas sem alunos" — se NENHUM candidato trouxer alunos,
        # ele vira diagnóstico (forma dos campos + onde estão os alunos), em vez de
        # um falso-sucesso "N turmas / 0 alunos".
        melhor_forma = ""
        melhor_corpo: list = []
        for metodo, url in candidatos:
            res = await nav.avaliar(self._js_fetch(url, metodo, headers, creds))
            res = res if isinstance(res, dict) else {}
            det = f"{res.get('status')}/{res.get('tipo')}({res.get('n')})"
            if res.get("erro"):                       # CORS/rede: mostra a causa real
                det += f" {res['erro']}"
            resumo.append(f"{metodo} …{url.split('elefanteletrado.com.br')[-1][:44]}"
                          f" → {det}")
            corpo = res.get("body")
            if isinstance(corpo, list) and corpo:
                mapa = self._parse_courses_students([{"url": ep, "json": corpo}])
                # Só é SUCESSO se veio ALUNO — {cid: []} é truthy mas inútil; nesse
                # caso segue tentando o próximo candidato (ex.: ?schoolId=).
                if mapa and any(mapa.values()):
                    total = sum(len(v) for v in mapa.values())
                    log("navegacao", "info",
                        f"[Elefante] cursos via API direta: {len(mapa)} turma(s), "
                        f"{total} aluno(s) (host={base}, "
                        f"auth={'sim' if auth else 'cookie'}). "
                        f"{self._amostra_roster(corpo)}")
                    return mapa
                if mapa and not melhor_corpo:         # turmas, mas 0 alunos: guarda p/ diagnóstico
                    melhor_forma = self._forma_json(corpo)
                    melhor_corpo = corpo
        if melhor_corpo:
            log("navegacao", "warn",
                f"[Elefante] API direta trouxe turmas mas 0 alunos. forma={melhor_forma} "
                f"| alunos: {self._diag_alunos(melhor_corpo)} | host={base} "
                f"tentativas={resumo}")
            return {}
        log("navegacao", "warn",
            f"[Elefante] API direta não trouxe turmas. host={base} "
            f"auth={'sim' if auth else 'nao'} escolas={escolas} tentativas={resumo}")
        return {}

    async def _enumerar(self, nav, log, url: str, tipo: str,
                        excluir: frozenset = frozenset()) -> list[str]:
        """Enumera ids (turma/aluno) navegando p/ `url` e capturando a API JSON
        do Elefante (qualquer host dela) — E o DOM. SEMPRE loga a FORMA (nomes de
        campos, sem PII) das respostas da API, para eu ver onde ficam os códigos
        e calibrar sem novo recon."""
        caps = await nav.coletar_respostas(url, timeout_s=25)
        await self._assentar(nav)
        dom = await nav.avaliar(_JS_IDS)
        if tipo == "turma":
            dom_ids = dom.get("course_links") or []
            chaves = ("courseId", "classId", "turmaId", "id", "code")
        else:
            dom_ids = dom.get("student_links") or []
            chaves = ("studentId", "userId", "alunoId", "id")
        dom_ids = dom_ids or dom.get("option_ids") or dom.get("data_ids") or []

        relevantes = [c for c in caps if self._api_elefante(c["url"])]
        api_ids: list[str] = []
        for c in relevantes:
            j = c.get("json")
            # Pula listas gigantes (ex.: todas as escolas do município) p/ não
            # extrair ruído; extrai de listas de tamanho razoável.
            if isinstance(j, list) and len(j) > 300:
                continue
            api_ids += self._ids_do_json(j, chaves)

        ids: list[str] = []
        for x in list(dom_ids) + api_ids:
            if x and x not in ids and x not in excluir:
                ids.append(x)

        # SEMPRE: forma (nomes de campos) das respostas da API — mostra a
        # estrutura real p/ eu mirar o endpoint/campo certo dos códigos.
        formas = [(c["url"].split("elefanteletrado.com.br")[-1].split("?")[0],
                   self._forma_json(c.get("json"))) for c in relevantes][:8]
        log("navegacao", "info",
            f"[Elefante] {tipo}: DOM={len(dom_ids)} API={len(api_ids)} → {len(ids)} "
            f"id(s). API Elefante: {json.dumps(formas, ensure_ascii=False)[:1400]}")
        return ids

    async def _baixar_relatorio_aluno(self, nav, contexto, log, course_id: str,
                                      student_id: str):
        """Abre o relatório INDIVIDUAL do aluno, SUBMETE a busca (Pesquisar — o SPA
        só renderiza o relatório depois disso) capturando a API de dados dele, e
        baixa o PDF pelo Exportar. Falha RÁPIDO se o Exportar não aparecer e dumpa
        a estrutura + a API do aluno (revela o endpoint JSON dos dados p/ eu passar
        a puxar direto). Devolve ArquivoObtido pronto p/ o pipeline, ou None."""
        # Timeouts CURTOS: este caminho (relatório em tela) é um fallback instável
        # que quase sempre falha rápido — não pode gastar minutos por aluno.
        caps = await nav.coletar_respostas(
            _URL_STUDENT.format(student_id=student_id, course_id=course_id),
            timeout_s=8)
        await self._assentar(nav)
        # Os params vão na URL, mas o relatório só RENDERIZA ao submeter a busca —
        # clicar "Pesquisar" dispara a API de dados do aluno e revela o Exportar.
        if await nav.esperar(_SEL_PESQUISAR, timeout_s=3):
            try:
                caps += await nav.coletar_apos_acao(
                    lambda: nav.clicar(_SEL_PESQUISAR), timeout_s=6)
            except Exception:  # noqa: BLE001 — clique pode falhar; segue p/ diagnóstico
                pass
            await self._assentar(nav)
        if not await nav.esperar(_SEL_EXPORTAR, timeout_s=4):
            pag = await nav.avaliar(_JS_PAGINA_ALUNO)
            # SÓ os endpoints NOVOS do aluno (tira o roster e a rede do município já
            # conhecidos) — é aqui que aparece a API de dados por aluno.
            apis = [(c["url"].split("elefanteletrado.com.br")[-1].split("?")[0],
                     f"{c.get('method', '')} {c.get('status', '')} "
                     + self._forma_json(c.get("json")))
                    for c in caps if self._api_elefante(c["url"])
                    and "get-courses-students" not in c["url"]
                    and "all-sp-municipal" not in c["url"]
                    and "active-schools" not in c["url"]][:10]
            log("download", "warn",
                f"[Elefante] aluno {student_id}: Exportar não apareceu. "
                f"Botões: {pag.get('botoes')}. API do aluno: "
                + json.dumps(apis, ensure_ascii=False)[:1100])
            return None
        conteudo, nome = await nav.baixar_acao(
            lambda: nav.clicar(_SEL_EXPORTAR), timeout_s=min(contexto.timeout_s, 45))
        if not conteudo:
            return None
        agora = datetime.now(timezone.utc)
        return ArquivoObtido(
            conteudo=conteudo,
            nome_arquivo=(nome or f"elefante_estudante_{student_id}_{agora:%Y%m%d}.pdf"),
            plataforma="elefante",
            content_type="application/pdf",
            # Relatório INDIVIDUAL = formato "leituras" (parser PerfilElefante
            # Estudante); a detecção por conteúdo confirma, o hint é a rede.
            formato_hint="leituras",
            metadados={"origem": "navegador", "student_id": student_id,
                       "course_id": course_id})

    async def sincronizar(self, cred: Credenciais,
                          contexto: Contexto) -> list[ArquivoObtido]:
        """Fase E — COLETA COMPLETA: loga uma vez, varre TODAS as turmas, e para
        cada uma varre TODOS os alunos, baixando o relatório INDIVIDUAL (PDF) de
        cada aluno pelo fluxo real (Exportar). Devolve a lista de PDFs; o
        orquestrador casa o nome e importa cada um pelo mesmo `confirmar` do
        upload manual — que já gera os eventos da linha do tempo. Idempotente:
        reimportar não duplica (chave_natural do evento). Logs detalhados por
        etapa; falha de um aluno não derruba os demais."""
        log = contexto.log
        arquivos: list[ArquivoObtido] = []
        async with self._sessao(contexto) as nav:
            await self._login(nav, cred, contexto)
            await nav.ir_para(_URL_REPORTS_MENU)
            atual = await nav.url_atual()
            if "admin.elefanteletrado.com.br" not in (atual or ""):
                raise ErroConector(
                    f"Não abri o painel do Elefante (endereço final: {atual}). A "
                    "sessão do login pode não ter cruzado para o admin. Tente "
                    "novamente ou use a importação manual do relatório.",
                    codigo="falha_auth", recuperavel=True)
            log("navegacao", "info", f"[Elefante] Painel logado em {atual}.")

            # Turmas + alunos vêm da API /course/get-courses-students. Ao abrir a
            # tela de turma o SPA às vezes já a dispara (fast-path); quando NÃO
            # dispara (precisa selecionar a escola e "Pesquisar" — corrida), nós
            # CHAMAMOS a API interna direto da página autenticada, reusando o token
            # do tráfego que sempre roda (/school/active-schools). Parse PRECISO:
            # turma.id + turma.student[].
            caps = await nav.coletar_respostas(f"{_URL_APP}/reports/course", timeout_s=25)
            await self._assentar(nav)
            mapa = self._parse_courses_students(caps)
            # "Turmas sem alunos" ({cid: []}) NÃO conta como sucesso — cai no
            # fallback da API direta (que pode trazer os alunos com ?schoolId=).
            if not any(mapa.values()):
                mapa = await self._cursos_alunos_via_api(nav, log, caps)
            if not any(mapa.values()):
                formas = [(c["url"].split("elefanteletrado.com.br")[-1].split("?")[0],
                           self._forma_json(c.get("json")))
                          for c in caps if self._api_elefante(c["url"])][:8]
                log("navegacao", "warn",
                    "[Elefante] Não achei /course/get-courses-students. API: "
                    + json.dumps(formas, ensure_ascii=False)[:1000])
                return []
            total = sum(len(v) for v in mapa.values())
            log("navegacao", "info",
                f"[Elefante] {len(mapa)} turma(s), {total} aluno(s) no total.")

            # DADOS DE LEITURA pela API REAL (/report/overall-*, POST — descoberta
            # por DevTools). Esta rodada mapeia a ESTRUTURA da resposta (sem PII)
            # para o parser final que vira eventos da linha do tempo. O caminho por
            # PDF/navegador (Exportar) foi abandonado: o relatório não renderiza por
            # URL e era lento/instável — a coleta definitiva será por esta API.
            try:
                await self._diagnosticar_relatorio_api(nav, log, caps, mapa)
            except Exception as exc:  # noqa: BLE001 — nunca derruba a sync
                log("navegacao", "warn", f"[Elefante] sonda de relatório falhou: {str(exc)[:80]}")
        return arquivos

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
