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

# Recon estrutural da área de relatórios — SEM PII (só tags, contagens, ids em
# hrefs/values e cabeçalhos de tabela; nunca nomes de alunos). Revela onde ficam
# os códigos de turma/aluno para montar a enumeração sem seletor frágil.
_JS_RECON = r"""(() => {
  const sel = (s) => Array.from(document.querySelectorAll(s));
  const only = (v) => (/^[0-9]+$/.test(String(v||'').trim()) ? String(v).trim() : '');
  return {
    url: location.href,
    titulo: (document.querySelector('h1,h2')||{}).textContent?.trim().slice(0,40) || '',
    selects: sel('select').slice(0,8).map(s => ({
      id: s.id||'', name: s.name||'', n: s.options.length,
      valores: Array.from(s.options).slice(0,4).map(o => only(o.value)).filter(Boolean),
    })),
    combos: sel('[role="combobox"], [class*="select" i], [class*="dropdown" i]')
      .slice(0,10).map(e => ({ tag: e.tagName, cls: String(e.className||'').slice(0,50) })),
    n_links_course: sel("a[href*='/reports/course']").length,
    n_links_student: sel("a[href*='/reports/student']").length,
    ex_links_course: sel("a[href*='/reports/course']").slice(0,4).map(a => a.getAttribute('href')),
    ex_links_student: sel("a[href*='/reports/student']").slice(0,4).map(a => a.getAttribute('href')),
    tem_exportar: sel('button, a').some(e => /exportar/i.test(e.textContent||'')),
    tabelas: sel('table').slice(0,4).map(t => ({
      linhas: t.rows.length,
      cabecalhos: sel('th').slice(0,8).map(th => (th.textContent||'').trim()).filter(Boolean),
    })),
  };
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

    async def diagnosticar_navegacao(self, cred: Credenciais,
                                     contexto: Contexto) -> dict:
        """RECON estrutural (SEM PII) da área de relatórios logada — para
        CONFIRMAR a navegação real (host admin, onde ficam os códigos de turma/
        aluno, botão Exportar) ANTES de implementar a coleta. Loga com as
        credenciais salvas, abre o menu de relatórios e a tela de turma, e
        devolve a estrutura (contagens/ids/cabeçalhos — nunca nomes de alunos)."""
        r = {"plataforma": self.plataforma, "url_pos_login": None,
             "sessao_admin_ok": False, "erro": None, "estrutura": {}}
        try:
            async with self._sessao(contexto) as nav:
                await self._login(nav, cred, contexto)
                await nav.ir_para(_URL_REPORTS_MENU)
                atual = await nav.url_atual()
                r["url_pos_login"] = atual
                # A sessão criada no login (login.elefante…) precisa valer no
                # admin.elefante… — se voltar p/ login, o cookie não cruzou.
                r["sessao_admin_ok"] = "admin.elefanteletrado.com.br" in (atual or "")
                r["estrutura"]["menu"] = await nav.avaliar(_JS_RECON)
                await nav.ir_para(f"{_URL_APP}/reports/course")
                r["estrutura"]["course"] = await nav.avaliar(_JS_RECON)
        except ErroConector as exc:
            r["erro"] = f"{exc.codigo}: {str(exc)[:140]}"
        except Exception as exc:  # noqa: BLE001
            r["erro"] = f"{type(exc).__name__}: {str(exc)[:140]}"
        return r

    async def sincronizar(self, cred: Credenciais,
                          contexto: Contexto) -> list[ArquivoObtido]:
        """Fase E — passo 1 (RECONHECIMENTO). Antes de coletar, o robô mapeia a
        estrutura REAL da área logada e registra nos logs (sem PII), para a
        coleta ser construída sobre a interface confirmada, não sobre suposição.
        A coleta por aluno (baixar cada relatório → eventos) entra assim que
        esta estrutura for confirmada. Retorna [] neste passo (nada é importado).
        """
        log = contexto.log
        recon = await self.diagnosticar_navegacao(cred, contexto)
        log("navegacao", "info",
            f"[Elefante] RECON — sessão no admin: {recon.get('sessao_admin_ok')} · "
            f"endereço: {recon.get('url_pos_login')} · erro: {recon.get('erro')}")
        log("navegacao", "info",
            "[Elefante] RECON estrutura (sem PII): "
            + json.dumps(recon.get("estrutura", {}), ensure_ascii=False)[:1800])
        log("navegacao", "info",
            "[Elefante] Reconhecimento concluído — mapeando a interface real "
            "antes de coletar. A coleta por aluno entra no próximo passo.")
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
