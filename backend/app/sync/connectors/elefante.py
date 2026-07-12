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
# tempo para renderizar antes de ler o DOM. Tests zeram (_SETTLE_S=0).
_SETTLE_S = 3

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

    async def sincronizar(self, cred: Credenciais,
                          contexto: Contexto) -> list[ArquivoObtido]:
        """Fase E — passo 1 (RECONHECIMENTO ponta a ponta). Antes de coletar de
        verdade, o robô prova a cadeia REAL (turmas → alunos → relatório →
        Exportar → PDF) e registra o resultado nos logs (sem PII). A coleta que
        importa todos os alunos entra assim que esta cadeia estiver confirmada.
        Retorna [] neste passo (nada é importado)."""
        log = contexto.log
        r = await self.diagnosticar_navegacao(cred, contexto)
        log("navegacao", "info",
            f"[Elefante] RECON sessão-admin={r.get('sessao_admin_ok')} "
            f"url={r.get('url_pos_login')} erro={r.get('erro')}")
        log("navegacao", "info", "[Elefante] RECON cadeia: "
            + json.dumps({"turmas": r.get("turmas"), "alunos": r.get("alunos"),
                          "aluno_report": r.get("aluno_report"),
                          "exportar": r.get("exportar"),
                          "download": r.get("download")}, ensure_ascii=False)[:1800])
        log("navegacao", "info",
            "[Elefante] Reconhecimento concluído — se turmas/alunos/exportar/"
            "download vieram OK, a coleta completa entra no próximo passo.")
        return []

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
