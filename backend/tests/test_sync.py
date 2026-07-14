"""Testes do Módulo de Sincronização Automática.

Cobre: cofre de credenciais (cifra/decifra/isolamento), conectores (fluxo com
navegador fake, sem browser real nem conta), e o orquestrador reusando o
pipeline de importação existente (conector → confirmar → snapshot).
"""
import asyncio

import pytest
from sqlalchemy import select

from app.sync import connectors, vault
from app.sync.interfaces import (
    ArquivoObtido,
    Contexto,
    Credenciais,
    Estrategia,
)


# --------------------------------------------------------------------------
# Navegador fake — exercita TODO o conector sem Playwright nem conta real
# --------------------------------------------------------------------------
class NavegadorFake:
    def __init__(self, *, logado=True, erro_login=False, bloqueado=False,
                 conteudo=b"PKxlsxfake"):
        self.logado, self.erro_login, self.conteudo = logado, erro_login, conteudo
        self.bloqueado = bloqueado          # simula CAPTCHA/desafio anti-robô
        self.valores_preenchidos: list[str] = []

    async def ir_para(self, url): pass
    async def preencher(self, seletor, valor): self.valores_preenchidos.append(valor)
    async def clicar(self, seletor): pass
    async def esperar(self, seletor, timeout_s=20):
        # Distingue "cheguei na área logada" (usa self.logado) de "o formulário
        # de login apareceu" (True) — o conector espera o form antes de digitar.
        marcas_logado = ("logout", "sair", "dashboard", "painel", "nav")
        if any(m in seletor for m in marcas_logado):
            return self.logado
        return True
    async def visivel(self, seletor):
        # CAPTCHA/bloqueio → self.bloqueado; campo de senha → visível (login de
        # UMA etapa, ex.: Elefante); demais chamadas são sobre a msg de erro.
        marcas_bloqueio = ("captcha", "recaptcha", "hcaptcha", "challenge", "cloudflare")
        if any(m in seletor for m in marcas_bloqueio):
            return self.bloqueado
        if "password" in seletor.lower() or "senha" in seletor.lower():
            return True
        return self.erro_login
    async def texto(self, seletor): return ""
    async def avaliar(self, expressao):
        # Lote de livros lidos COM DATA por aluno (overall-student-books-read).
        if "fetch(" in expressao and "overall-student-books-read" in expressao:
            return [{"studentId": 4427356, "n": 1, "books": [
                {"bookTitle": "Livro X", "levelName": "F", "genre": "Aventura",
                 "totalTimeSpent": 1088, "lastReadWhen": "2026-06-26T08:59:43"}]}]
        # Fetch in-page do relatório de turma: devolve students[] com os dados por
        # aluno (é o que a sincronização coleta).
        if "fetch(" in expressao and "overall-course-report" in expressao:
            return {"ok": True, "status": 200, "tipo": "object", "n": 0, "body": {
                "courseSchoolDescriptors": {"courseName": "5 ANO B",
                                            "schoolName": "EMEI", "teachers": "Prof X",
                                            "grade": 5},
                "students": [{"studentId": 4427356, "studentName": "Aluno X",
                              "currentStudentLevel": "N5", "totalBooksRead": 86,
                              "totalReadTime": 15731, "responses": 100,
                              "approvedResponses": 90}]}}
        # Fake do recon: ids de turma/aluno e o botão Exportar presente. Serve
        # tanto ao _JS_IDS quanto ao _JS_EXPORTAR (o fake não distingue a query).
        return {"n_selects": 1, "n_options": 3,
                "option_ids": ["511434"], "course_links": ["511434"],
                "student_links": ["4427356"], "data_ids": [],
                "tem_exportar": True, "n": 1, "textos": ["Exportar"], "tags": ["BUTTON"]}
    async def url_atual(self): return "https://x"
    async def coletar_respostas(self, url, timeout_s=25):
        # API real do Elefante: /course/get-courses-students traz cada turma com
        # seus alunos aninhados (id da turma + student[].id).
        return [{"url": "https://prod-ecs-apiadmin.elefanteletrado.com.br/course/get-courses-students",
                 "json": [{"id": 511434, "name": "5 ANO B",
                           "student": [{"id": 4427356, "name": "Aluno X"}]}]}]
    async def coletar_apos_acao(self, acao, timeout_s=20):
        try:
            await acao()
        except Exception:       # noqa: BLE001 — clique fake é no-op
            pass
        return []
    async def baixar_acao(self, acao, timeout_s=60):
        try:
            await acao()
        except Exception:       # noqa: BLE001 — clique fake é no-op
            pass
        return (self.conteudo, "rel.pdf")
    async def baixar(self, seletor, timeout_s=60): return (self.conteudo, "rel.xlsx")
    async def fechar(self): pass


def _fabrica(nav):
    async def fab(**_kw):
        return nav
    return fab


def _contexto(escola_id=1):
    return Contexto(escola_id=escola_id, execucao_id=None,
                    log=lambda etapa, nivel, msg: None)


# --------------------------------------------------------------------------
# Cofre de credenciais
# --------------------------------------------------------------------------
def test_cofre_cifra_decifra_roundtrip(db, escola_completa):
    escola = escola_completa["escola"]
    vault.salvar_credencial(db, escola.id, "matific",
                            Credenciais(usuario="prof@x", senha="s3nh4-secreta"))
    linha = vault.obter_linha(db, escola.id, "matific")
    # em repouso está CIFRADO (a senha não aparece em claro)
    assert "s3nh4-secreta" not in linha.segredo_cifrado
    assert linha.status == "nao_validada"
    # decifra devolve o original
    cred = vault.obter_credencial(db, escola.id, "matific")
    assert cred.usuario == "prof@x" and cred.senha == "s3nh4-secreta"


def test_cofre_isola_por_escola(db, escola_completa):
    from app.models import Escola
    outra = Escola(nome="OUTRA", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    vault.salvar_credencial(db, escola_completa["escola"].id, "matific",
                            Credenciais(usuario="a", senha="b"))
    # a outra escola não enxerga a credencial da primeira
    assert vault.obter_credencial(db, outra.id, "matific") is None


def test_cofre_salvar_reseta_status_e_incrementa_versao(db, escola_completa):
    escola = escola_completa["escola"]
    l1 = vault.salvar_credencial(db, escola.id, "elefante",
                                 Credenciais(usuario="a", senha="b"))
    vault.marcar_status(db, l1, "valida")
    l2 = vault.salvar_credencial(db, escola.id, "elefante",
                                 Credenciais(usuario="a", senha="nova"))
    assert l2.status == "nao_validada" and l2.token_version == 2


# --------------------------------------------------------------------------
# Conectores
# --------------------------------------------------------------------------
def test_registro_tem_manual_matific_elefante():
    plats = {c.plataforma for c in connectors.listar()}
    assert {"manual", "matific", "elefante"} <= plats
    assert set(connectors.plataformas_automatizaveis()) == {"matific", "elefante"}
    assert connectors.obter("manual").estrategia == Estrategia.UPLOAD_MANUAL
    assert connectors.obter("matific").estrategia == Estrategia.NAVEGADOR


@pytest.mark.parametrize("plataforma", ["matific", "elefante"])
def test_testar_credenciais_ok_e_erro(plataforma):
    Classe = type(connectors.obter(plataforma))
    cred = Credenciais(usuario="prof@x", senha="segredo-nao-vaza")

    ok = asyncio.run(Classe(_fabrica(NavegadorFake(logado=True)))
                     .testar_credenciais(cred, _contexto()))
    assert ok.ok and ok.codigo == "ok"

    ruim = asyncio.run(Classe(_fabrica(NavegadorFake(logado=False, erro_login=True)))
                       .testar_credenciais(cred, _contexto()))
    assert not ruim.ok and ruim.codigo == "senha_invalida"


@pytest.mark.parametrize("plataforma", ["matific", "elefante"])
def test_testar_credenciais_erro_cru_do_navegador_nao_propaga(plataforma):
    """Se o navegador lança uma exceção CRUA (seletor mudou/timeout — NÃO
    ErroConector), testar_credenciais devolve ok=False claro (codigo
    'erro_navegador') em vez de estourar — a causa raiz do 500 em produção."""
    class NavegadorQuebra(NavegadorFake):
        async def preencher(self, seletor, valor):
            # imita o erro do Playwright: cita o seletor, nunca o valor digitado
            raise RuntimeError(f"Timeout 30000ms waiting for selector {seletor}")

    Classe = type(connectors.obter(plataforma))
    res = asyncio.run(Classe(_fabrica(NavegadorQuebra()))
                      .testar_credenciais(Credenciais(usuario="u", senha="p-secreta"),
                                          _contexto()))
    assert res.ok is False
    assert res.codigo == "erro_navegador"
    assert "p-secreta" not in res.mensagem          # não vaza a senha na mensagem


@pytest.mark.parametrize("plataforma", ["matific", "elefante"])
def test_login_sem_formulario_da_diagnostico_claro(plataforma):
    """Quando a página de login não mostra o formulário (endereço mudou,
    redirecionou p/ a home, ou exigiu verificação), o conector dá um erro CLARO
    e ACIONÁVEL (código 'pagina_login', com o endereço alcançado) — não um
    timeout cru nem a mensagem genérica."""
    class SemFormulario(NavegadorFake):
        async def esperar(self, seletor, timeout_s=20):
            return False  # nada aparece
        async def url_atual(self):
            return "https://www.matific.com/"  # redirecionou para a home

    Classe = type(connectors.obter(plataforma))
    res = asyncio.run(Classe(_fabrica(SemFormulario()))
                      .testar_credenciais(Credenciais(usuario="u", senha="p"),
                                          _contexto()))
    assert res.ok is False
    assert res.codigo == "pagina_login"
    assert "endereço atual" in res.mensagem and "manual" in res.mensagem.lower()


def test_proxy_playwright_traduz_url(monkeypatch):
    """SYNC_PROXY_URL vira o formato proxy= do Playwright — necessário para o
    robô sair por IP residencial e passar o reCAPTCHA v3 do Matific."""
    from app.core.config import settings
    from app.sync.connectors import navegador as nav

    monkeypatch.setattr(settings, "SYNC_PROXY_URL", "", raising=False)
    assert nav._proxy_playwright() is None                    # sem proxy = None

    monkeypatch.setattr(settings, "SYNC_PROXY_URL",
                        "http://usuario:segredo@proxy.exemplo:3128", raising=False)
    cfg = nav._proxy_playwright()
    assert cfg == {"server": "http://proxy.exemplo:3128",
                   "username": "usuario", "password": "segredo"}

    monkeypatch.setattr(settings, "SYNC_PROXY_URL", "socks5://host:1080",
                        raising=False)
    assert nav._proxy_playwright() == {"server": "socks5://host:1080"}


def test_elefante_recon_prova_a_cadeia(monkeypatch):
    """diagnosticar_navegacao prova a cadeia (turmas → alunos → relatório →
    Exportar → PDF), reportando ids/estrutura (sem PII)."""
    from app.sync.connectors import elefante
    monkeypatch.setattr(elefante, "_SETTLE_S", 0)
    ctx = Contexto(escola_id=1, execucao_id=None, log=lambda e, n, m: None)
    con = elefante.ConectorElefante(_fabrica(NavegadorFake(logado=True)))
    r = asyncio.run(con.diagnosticar_navegacao(Credenciais(usuario="u", senha="p"), ctx))
    assert r["turmas"]["candidatas"] == 1 and r["turmas"]["amostra"] == ["511434"]
    assert r["alunos"]["candidatos"] == 1 and r["alunos"]["amostra"] == ["4427356"]
    assert r["exportar"]["tem_exportar"] is True
    assert r["download"]["ok"] is True and r["download"]["bytes"] > 0


def test_elefante_sincronizar_coleta_dados_por_turma(monkeypatch):
    """A sincronização enumera turmas+alunos (roster via API) e coleta os DADOS de
    cada turma pelo overall-course-report → um ArquivoObtido (JSON) por turma, no
    formato que o pipeline importa (resumo)."""
    from app.sync.connectors import elefante
    monkeypatch.setattr(elefante, "_SETTLE_S", 0)

    class NavAdmin(NavegadorFake):
        async def url_atual(self):   # sessão cruzou p/ o admin
            return "https://admin.elefanteletrado.com.br/reports/menu"

    etapas: list[str] = []
    ctx = Contexto(escola_id=1, execucao_id=None,
                   log=lambda e, n, m: etapas.append(m))
    con = elefante.ConectorElefante(_fabrica(NavAdmin(logado=True)))
    arquivos = asyncio.run(con.sincronizar(Credenciais(usuario="u", senha="p"), ctx))
    assert "aluno(s) no total" in " | ".join(etapas)          # roster enumerado
    # 2 arquivos por turma: o agregado (resumo) + o granular (leituras datadas).
    formatos = {a.formato_hint for a in arquivos}
    assert formatos == {"resumo", "leituras"}
    assert all(a.content_type == elefante._CT_API for a in arquivos)
    granular = next(a for a in arquivos if a.formato_hint == "leituras")
    assert b"Livro X" in granular.conteudo and b"lastReadWhen" in granular.conteudo


def test_elefante_sincronizar_via_api_direta(monkeypatch):
    """Se o SPA NÃO dispara /course/get-courses-students sozinho (só /school/
    active-schools aparece), o conector CHAMA a API interna direto da página
    autenticada (in-page fetch, reusando o token) e ainda coleta os alunos."""
    from app.sync.connectors import elefante
    monkeypatch.setattr(elefante, "_SETTLE_S", 0)

    class NavApiDireta(NavegadorFake):
        async def url_atual(self):
            return "https://admin.elefanteletrado.com.br/reports/menu"

        async def coletar_respostas(self, url, timeout_s=25):
            # A navegação só disparou o seletor de escolas (com o token no
            # Authorization) — NÃO as turmas. É o cenário da execução #9.
            return [{
                "url": "https://prod-ecs-apiadmin.elefanteletrado.com.br/school/active-schools",
                "json": [{"id": 987, "fantasyName": "EMEI", "productIds": [1]}],
                "method": "GET", "status": 200, "req_auth": "Bearer TOKEN-abc"}]

        async def avaliar(self, expressao):
            # O fetch in-page da API de cursos devolve as turmas + alunos; qualquer
            # outra avaliação cai no fake padrão (ids/Exportar).
            if "fetch(" in expressao and "get-courses-students" in expressao:
                assert "Bearer TOKEN-abc" in expressao   # reusou o token real
                return {"ok": True, "status": 200, "tipo": "list", "n": 1,
                        "body": [{"id": 511434, "name": "5B",
                                  "student": [{"id": 4427356, "name": "Aluno X"}]}]}
            return await super().avaliar(expressao)

    etapas: list[str] = []
    ctx = Contexto(escola_id=1, execucao_id=None,
                   log=lambda e, n, m: etapas.append(m))
    con = elefante.ConectorElefante(_fabrica(NavApiDireta(logado=True)))
    arquivos = asyncio.run(con.sincronizar(Credenciais(usuario="u", senha="p"), ctx))
    assert "via API direta" in " | ".join(etapas)
    assert len(arquivos) >= 1                             # coletou a turma
    assert all(a.content_type == elefante._CT_API for a in arquivos)


def test_parse_courses_students_aceita_chaves_alternativas():
    """O id do aluno pode vir sob chave diferente de 'id' (studentId/userId) e a
    lista sob chave diferente de 'student' — o parser reconhece as duas coisas."""
    from app.sync.connectors.elefante import ConectorElefante as C
    caps = [{"url": "https://x/course/get-courses-students", "json": [
        {"id": 10, "studentList": [{"studentId": 111}, {"studentId": 222}]},
        {"id": 20, "student": [{"userId": 333}]},
    ]}]
    mapa = C._parse_courses_students(caps)
    assert mapa == {"10": ["111", "222"], "20": ["333"]}


def test_parse_courses_students_student_contagem_nao_quebra():
    """Se 'student' vier como NÚMERO (contagem, não lista), não extrai aluno e não
    quebra — o diagnóstico é quem sinaliza que os alunos vêm de outro endpoint."""
    from app.sync.connectors.elefante import ConectorElefante as C
    caps = [{"url": "https://x/course/get-courses-students",
             "json": [{"id": 10, "student": 25}]}]
    mapa = C._parse_courses_students(caps)
    assert mapa == {"10": []}


def test_analisar_elefante_api_mapeia_campos():
    """O JSON do overall-course-report vira uma Analise 'resumo' com os campos
    certos por aluno (livros/tempo/questões) — o mesmo que o import manual gera."""
    from app.services.importacao import analisar_elefante_api
    payload = {"courseSchoolDescriptors": {"courseName": "5 ANO B",
                                           "schoolName": "EMEI", "teachers": "Prof"},
               "students": [{"studentId": 1, "studentName": "Veronica X",
                             "currentStudentLevel": "N5", "totalBooksRead": 86,
                             "totalReadTime": 15731, "responses": 100,
                             "approvedResponses": 90},
                            {"studentName": "", "totalBooksRead": 5}]}  # sem nome → ignorado
    a = analisar_elefante_api(payload)
    assert a.plataforma == "elefante" and a.formato == "resumo"
    assert a.turma_detectada == "5 ANO B"
    assert len(a.linhas) == 1                       # o sem-nome foi descartado
    d = a.linhas[0].dados
    assert a.linhas[0].nome == "Veronica X"
    assert d["livros_unicos"] == 86
    assert d["tempo_leitura_min"] == round(15731 / 60)   # segundos → minutos
    assert d["questoes_tentativas"] == 100 and d["questoes_acertos"] == 90
    assert d["turma_relatorio"] == "5 ANO B"             # desambigua homônimos

    # Sem courseName: cai no id da turma (não deixa a turma vazia → não descarta).
    b = analisar_elefante_api({"courseId": 511434,
                               "students": [{"studentName": "Fulano", "totalBooksRead": 3}]})
    assert b.turma_detectada == "Turma 511434"
    assert b.linhas[0].dados["turma_relatorio"] == "Turma 511434"


def test_analisar_elefante_api_leituras_datadas():
    """O payload GRANULAR (leituras) vira Analise 'leituras' — uma linha por LIVRO,
    com data normalizada p/ ISO (ranking por período) e tempo em minutos."""
    from app.services.importacao import analisar_elefante_api
    payload = {"courseSchoolDescriptors": {"courseName": "5 ANO B"},
               "leituras": [
                   {"nome": "Veronica X", "bookTitle": "De bem com a vida",
                    "levelName": "F", "genre": "Amizade", "totalTimeSpent": 1088,
                    "lastReadWhen": "2026-06-26T08:59:43"},
                   {"nome": "", "bookTitle": "Ignorado"},        # sem nome → descartado
                   {"nome": "Veronica X", "bookTitle": "Sem data",
                    "lastReadWhen": ""}]}                        # sem data → descartado
    a = analisar_elefante_api(payload)
    assert a.formato == "leituras" and a.turma_detectada == "5 ANO B"
    assert len(a.linhas) == 1                       # só o livro COM data entra
    d = a.linhas[0].dados
    assert a.linhas[0].nome == "Veronica X"
    assert d["livro"] == "De bem com a vida" and d["nivel"] == "F"
    assert d["data"].startswith("2026-06-26T08:59:43")
    assert d["tempo_livro_min"] == round(1088 / 60)  # segundos → minutos
    assert d["turma_relatorio"] == "5 ANO B"


def test_data_iso_elefante_formatos():
    """Normaliza ISO e formato brasileiro; vazio quando não parseia."""
    from app.services.importacao import _data_iso_elefante
    assert _data_iso_elefante("2026-06-26T08:59:43").startswith("2026-06-26T08:59:43")
    assert _data_iso_elefante("26/06/2026 08:59:43").startswith("2026-06-26T08:59:43")
    assert _data_iso_elefante("26/06/2026").startswith("2026-06-26")
    assert _data_iso_elefante("bagunça") == "" and _data_iso_elefante(None) == ""


def test_corpo_relatorio_e_js_fetch_post():
    """O corpo POST do /report/* leva os filtros certos; o js_fetch com corpo vira
    um POST com JSON (Content-Type) e injeta studentId sem quebrar o template."""
    from app.sync.connectors.elefante import ConectorElefante as C
    corpo = C._corpo_relatorio(studentId=4427356)
    assert corpo["studentId"] == 4427356
    assert corpo["period"] == "PERIODS.LIFETIME"
    assert corpo["languageId"] == 1 and corpo["timezoneOffset"] == 180
    js = C._js_fetch("https://api/report/overall-student-report", "POST",
                     {"Authorization": "Bearer T"}, "omit", corpo)
    assert '"POST"' in js and "4427356" in js and "application/json" in js


def test_estrutura_tipos_sem_valores():
    """_estrutura mostra chaves+tipos e NUNCA valores string (sem PII: nome de
    aluno / título de livro jamais aparecem)."""
    from app.sync.connectors.elefante import ConectorElefante as C
    dados = {"studentName": "Fulano Secreto",
             "completedReadings": 86,
             "books": [{"title": "O Livro Secreto", "date": "2026-01-01"}]}
    e = C._estrutura(dados)
    assert "studentName:str" in e and "completedReadings:num" in e
    assert "books:[1×{title:str, date:str}]" in e
    assert "Fulano" not in e and "Secreto" not in e and "Livro" not in e


def test_diag_alunos_sem_pii():
    """O diagnóstico mostra TIPO e CHAVES (nunca valores/nomes de aluno)."""
    from app.sync.connectors.elefante import ConectorElefante as C
    # lista de alunos: só as chaves, jamais o nome
    d = C._diag_alunos([{"id": 1, "student": [{"id": 9, "name": "Fulano Secreto"}]}])
    assert "lista[1]" in d and "id" in d and "name" in d
    assert "Fulano" not in d and "Secreto" not in d
    # contagem: mostra o número (não é PII)
    assert "student=int=25" in C._diag_alunos([{"id": 1, "student": 25}])


def test_login_detecta_mfa_2fa():
    """Se após o envio aparece tela de verificação em duas etapas (2FA/OTP), o
    conector dá erro ESPECÍFICO (código 'mfa') orientando conta sem 2FA / import
    manual — não um 'falha_auth' genérico."""
    class ComMFA(NavegadorFake):
        async def visivel(self, seletor):
            s = seletor.lower()
            if "otp" in s or "one-time-code" in s or "2fa" in s or "mfa" in s \
                    or "verification" in s or "authcode" in s:
                return True          # tela de 2FA visível após o envio
            return await super().visivel(seletor)

    Classe = type(connectors.obter("matific"))
    res = asyncio.run(Classe(_fabrica(ComMFA(logado=False)))
                      .testar_credenciais(Credenciais(usuario="u", senha="p"),
                                          _contexto()))
    assert res.ok is False
    assert res.codigo == "mfa"
    assert "duas etapas" in res.mensagem.lower()


@pytest.mark.parametrize("plataforma", ["matific", "elefante"])
def test_login_detecta_captcha_bloqueio(plataforma):
    """Se a plataforma mostra CAPTCHA/desafio anti-robô, o conector devolve um
    erro ESPECÍFICO (código 'captcha') orientando a importação manual — não um
    'não confirmei o login' genérico."""
    Classe = type(connectors.obter(plataforma))
    res = asyncio.run(Classe(_fabrica(NavegadorFake(bloqueado=True)))
                      .testar_credenciais(Credenciais(usuario="u", senha="p"),
                                          _contexto()))
    assert res.ok is False
    assert res.codigo == "captcha"
    assert "manual" in res.mensagem.lower()


def test_login_registra_etapas_no_log():
    """O fluxo de login registra etapas CLARAS (abrir → formulário → enviar →
    resultado) em SincronizacaoLog, sem vazar a senha."""
    etapas: list[str] = []
    ctx = Contexto(escola_id=1, execucao_id=None,
                   log=lambda etapa, nivel, msg: etapas.append(msg))
    Classe = type(connectors.obter("matific"))
    asyncio.run(Classe(_fabrica(NavegadorFake(logado=True)))
                .testar_credenciais(Credenciais(usuario="u", senha="TOPSECRET"), ctx))
    texto = " | ".join(etapas)
    assert "Abrindo a página de login" in texto
    assert "Formulário encontrado" in texto
    assert "Enviando o formulário" in texto
    assert "Login confirmado" in texto
    assert "TOPSECRET" not in texto        # a senha NUNCA aparece no log


@pytest.mark.parametrize("plataforma", ["matific", "elefante"])
def test_diagnosticar_login_sem_credenciais(plataforma):
    """O diagnóstico (sem credenciais) abre a página e reporta se o formulário
    aparece e se há bloqueio — para validar o ambiente sem contas reais."""
    Classe = type(connectors.obter(plataforma))
    ok = asyncio.run(Classe(_fabrica(NavegadorFake()))
                     .diagnosticar_login(_contexto()))
    assert ok["formulario_encontrado"] is True
    # O diagnóstico confirma os TRÊS alvos do preenchimento/envio (usuário,
    # senha e botão) — assim "preencher usuário e senha" e "submeter" ficam
    # validados no ambiente real SEM credenciais.
    assert ok["usuario_encontrado"] is True
    assert ok["senha_encontrada"] is True
    assert ok["botao_encontrado"] is True
    assert ok["pre_passos_ok"] is True
    assert ok["bloqueio_detectado"] is False
    assert ok["erro"] is None
    assert ok["plataforma"] == plataforma

    # Login de uma etapa: a senha já aparece → NÃO é progressivo.
    assert ok["login_progressivo"] is False

    bloq = asyncio.run(Classe(_fabrica(NavegadorFake(bloqueado=True)))
                       .diagnosticar_login(_contexto()))
    assert bloq["bloqueio_detectado"] is True


class NavegadorProgressivo(NavegadorFake):
    """Simula login em DUAS etapas (ex.: Matific): a senha só fica visível DEPOIS
    de clicar em avançar ("Continuar")."""
    def __init__(self, **kw):
        super().__init__(**kw)
        self._revelada = False
        self.cliques: list[str] = []

    def _eh_avancar(self, seletor):
        s = seletor.lower()
        return "login-button" in s or "submit" in s or "entrar" in s

    async def clicar(self, seletor):
        self.cliques.append(seletor)
        if self._eh_avancar(seletor):     # avançar/enviar revela a senha
            self._revelada = True

    async def esperar(self, seletor, timeout_s=20):
        if "password" in seletor.lower() or "senha" in seletor.lower():
            return self._revelada
        return await super().esperar(seletor, timeout_s)

    async def visivel(self, seletor):
        if "password" in seletor.lower() or "senha" in seletor.lower():
            return self._revelada
        return await super().visivel(seletor)


def test_login_duas_etapas_revela_e_preenche_a_senha():
    """Login progressivo (Matific 'Continuar'): o robô preenche o usuário, avança
    para revelar a senha, preenche a senha e envia. A senha só é digitada DEPOIS
    de revelada (não some/erra) e o resultado é sucesso."""
    etapas: list[str] = []
    ctx = Contexto(escola_id=1, execucao_id=None,
                   log=lambda e, n, m: etapas.append(m))
    nav = NavegadorProgressivo(logado=True)
    Classe = type(connectors.obter("matific"))
    res = asyncio.run(Classe(_fabrica(nav))
                      .testar_credenciais(Credenciais(usuario="u@x", senha="S3nh4"), ctx))
    assert res.ok is True
    assert "S3nh4" in nav.valores_preenchidos          # a senha FOI preenchida
    # avançou (revelar senha) e depois enviou → o botão foi clicado 2x
    assert sum(nav._eh_avancar(c) for c in nav.cliques) >= 2
    assert any("avançando para a senha" in m for m in etapas)


def test_diagnosticar_login_progressivo():
    """No login em duas etapas, o diagnóstico reconhece o formulário mesmo sem
    a senha visível (login_progressivo=True) — usuário e botão bastam para
    confirmar que o robô chega ao formulário."""
    nav = NavegadorProgressivo()               # senha ainda não revelada
    Classe = type(connectors.obter("matific"))
    r = asyncio.run(Classe(_fabrica(nav)).diagnosticar_login(_contexto()))
    assert r["usuario_encontrado"] is True
    assert r["botao_encontrado"] is True
    assert r["senha_encontrada"] is False
    assert r["login_progressivo"] is True
    assert r["formulario_encontrado"] is True
    assert r["bloqueio_detectado"] is False


def test_conector_nao_vaza_senha_no_log():
    registros: list[str] = []
    ctx = Contexto(escola_id=1, execucao_id=None,
                   log=lambda e, n, m: registros.append(f"{e}{n}{m}"))
    Classe = type(connectors.obter("matific"))
    asyncio.run(Classe(_fabrica(NavegadorFake())).testar_credenciais(
        Credenciais(usuario="prof@x", senha="TOPSECRET"), ctx))
    assert all("TOPSECRET" not in r for r in registros)


def test_login_confirmado_pela_url_sem_seletor():
    """Matific: pós-login cai em /teachers, que não tem link de logout no HTML
    inicial. A URL confirma o login — senão o robô dava 'não confirmei a área
    logada' mesmo com o login OK (bug reportado pelo gestor)."""
    class NavTeachers(NavegadorFake):
        async def url_atual(self):
            return "https://www.matific.com/bra/pt-br/teachers"
    nav = NavTeachers(logado=False)   # o seletor de área logada NÃO casa
    con = type(connectors.obter("matific"))(_fabrica(nav))
    # Não deve levantar: o login é confirmado pela URL /teachers.
    asyncio.run(con._login(nav, Credenciais(usuario="a", senha="b"), _contexto()))


def test_login_url_de_login_nao_conta_como_logado():
    """Guarda: se a URL final AINDA é a de login, não confirma (evita falso OK)."""
    from app.sync.interfaces import ErroConector
    class NavPreso(NavegadorFake):
        async def url_atual(self):
            return "https://www.matific.com/bra/pt-br/login-page/"
    nav = NavPreso(logado=False)
    con = type(connectors.obter("matific"))(_fabrica(nav))
    with pytest.raises(ErroConector):
        asyncio.run(con._login(nav, Credenciais(usuario="a", senha="b"), _contexto()))


def test_obter_devolve_arquivo_para_pipeline():
    """O download direto (obter) do Matific ainda alimenta o pipeline como
    fallback. A coleta PRINCIPAL agora é pela API interna do Placar da Escola —
    coberta em test_matific_api.py (sincronizar sobrescrito)."""
    Classe = type(connectors.obter("matific"))
    con = Classe(_fabrica(NavegadorFake(conteudo=b"PKdados")))
    cred, ctx = Credenciais(usuario="a", senha="b"), _contexto()
    rel = asyncio.run(con.localizar_relatorios(cred, ctx))
    arquivo = asyncio.run(con.obter(cred, rel[0], ctx))
    assert arquivo.plataforma == "matific" and arquivo.conteudo == b"PKdados"


# --------------------------------------------------------------------------
# Orquestrador — reusa o pipeline de importação existente
# --------------------------------------------------------------------------
def test_orquestrador_reusa_pipeline_cria_snapshot(db, escola_completa, monkeypatch):
    from app.models.plataformas import Importacao, SnapshotMatific
    from app.services import importacao as svc
    from app.sync import orchestrator

    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]  # "Ana Beatriz Souza"

    # _parsear controlado: uma linha Matific com o nome real da aluna.
    def fake_parsear(arquivo):
        analise = svc.Analise(plataforma="matific", formato="resumo",
                              turma_detectada="")
        analise.linhas = [svc.LinhaImportacao(
            numero=1, nome="Ana Beatriz Souza",
            dados={"atividades": 20, "estrelas": 5, "pontuacao_media": 85.0})]
        return analise, "xlsx"

    monkeypatch.setattr(orchestrator, "_parsear", fake_parsear)
    # sem tocar o disco: sem token -> confirmar pula o arquivamento
    monkeypatch.setattr(orchestrator.imp, "_guardar_temporario", lambda *a, **k: None)

    arquivo = ArquivoObtido(conteudo=b"PKxlsx", nome_arquivo="matific.xlsx",
                            plataforma="matific")
    res = orchestrator.aplicar_arquivo(
        db, escola, arquivo, usuario_id=None, recalcular=True, contexto=_contexto(escola.id))

    assert res["qtd_alunos"] == 1 and res["sem_dados"] is False
    # o pipeline REAL rodou: existe snapshot Matific para a Ana + uma Importacao
    snap = db.execute(select(SnapshotMatific).where(
        SnapshotMatific.escola_id == escola.id,
        SnapshotMatific.aluno_id == ana.id)).scalars().first()
    assert snap is not None
    assert db.execute(select(Importacao).where(
        Importacao.escola_id == escola.id)).scalars().first() is not None


def test_orquestrador_importa_elefante_api_json(db, escola_completa, monkeypatch):
    """Ponta a ponta: um ArquivoObtido JSON (overall-course-report) passa pelo
    _parsear REAL (branch da API) → casar_nomes → confirmar → SnapshotElefante com
    os valores mapeados. Prova que a coleta por API entra no pipeline existente."""
    import json as _json

    from app.models.plataformas import Importacao, SnapshotElefante
    from app.sync import orchestrator

    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]  # "Ana Beatriz Souza"
    monkeypatch.setattr(orchestrator.imp, "_guardar_temporario", lambda *a, **k: None)

    payload = {"courseSchoolDescriptors": {"courseName": "5 ANO B"},
               "students": [{"studentId": 1, "studentName": "Ana Beatriz Souza",
                             "totalBooksRead": 42, "totalReadTime": 12000,
                             "responses": 30, "approvedResponses": 25}]}
    arq = ArquivoObtido(
        conteudo=_json.dumps(payload).encode("utf-8"),
        nome_arquivo="elefante_turma_1.json", plataforma="elefante",
        content_type=orchestrator.CT_ELEFANTE_API, formato_hint="resumo")
    res = orchestrator.aplicar_arquivo(
        db, escola, arq, usuario_id=None, recalcular=True, contexto=_contexto(escola.id))

    assert res["qtd_alunos"] == 1 and res["sem_dados"] is False
    snap = db.execute(select(SnapshotElefante).where(
        SnapshotElefante.escola_id == escola.id,
        SnapshotElefante.aluno_id == ana.id)).scalars().first()
    assert snap is not None
    assert snap.livros_unicos == 42
    assert snap.tempo_leitura_min == round(12000 / 60)   # segundos → minutos
    assert snap.questoes_tentativas == 30 and snap.questoes_acertos == 25
    assert db.execute(select(Importacao).where(
        Importacao.escola_id == escola.id)).scalars().first() is not None


def test_orquestrador_importa_elefante_api_leituras_datadas(db, escola_completa, monkeypatch):
    """Ponta a ponta do GRANULAR: um ArquivoObtido 'leituras' (JSON do books-read)
    vira Leitura DATADA — base do ranking por período e da linha do tempo."""
    import json as _json

    from app.models import Leitura, Livro
    from app.sync import orchestrator

    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]  # "Ana Beatriz Souza"
    monkeypatch.setattr(orchestrator.imp, "_guardar_temporario", lambda *a, **k: None)

    payload = {"courseSchoolDescriptors": {"courseName": "5 ANO B"},
               "leituras": [{"nome": "Ana Beatriz Souza", "bookTitle": "De bem com a vida",
                             "levelName": "F", "genre": "Amizade", "totalTimeSpent": 1088,
                             "lastReadWhen": "2026-06-26T08:59:43"}]}
    arq = ArquivoObtido(
        conteudo=_json.dumps(payload).encode("utf-8"),
        nome_arquivo="elefante_leituras_1.json", plataforma="elefante",
        content_type=orchestrator.CT_ELEFANTE_API, formato_hint="leituras")
    res = orchestrator.aplicar_arquivo(
        db, escola, arq, usuario_id=None, recalcular=True, contexto=_contexto(escola.id))

    assert res["qtd_alunos"] == 1
    leit = db.execute(
        select(Leitura).join(Livro, Leitura.livro_id == Livro.id)
        .where(Leitura.aluno_id == ana.id)).scalars().first()
    assert leit is not None
    assert (leit.data.year, leit.data.month, leit.data.day) == (2026, 6, 26)


def test_orquestrador_resolve_ator_admin_da_escola(db, escola_completa):
    from app.sync import orchestrator
    escola = escola_completa["escola"]
    # scheduler (usuario_id=None) resolve um admin/coordenador ATIVO da escola
    ator = orchestrator._resolver_ator(db, escola.id, None)
    assert ator is not None and ator.escola_id == escola.id
    assert ator.cargo in ("admin", "coordenador")


# --------------------------------------------------------------------------
# Motor de execução (fila, ciclo de vida, retry, agenda)
# --------------------------------------------------------------------------
from app.sync.interfaces import Conector, ErroConector, ResultadoValidacao


class ConectorFake(Conector):
    plataforma = "matific"
    versao = "9.9.9"
    estrategia = Estrategia.NAVEGADOR

    def __init__(self, arquivos=None, erro=None):
        self._arqs = arquivos or []
        self._erro = erro

    async def testar_credenciais(self, cred, ctx):
        return ResultadoValidacao(True, "ok", "ok")

    async def localizar_relatorios(self, cred, ctx):
        return []

    async def obter(self, cred, rel, ctx):
        raise NotImplementedError

    async def sincronizar(self, cred, ctx):
        ctx.log("download", "info", "baixando (fake)")
        if self._erro:
            raise self._erro
        return self._arqs


def _analise_ana():
    from app.services import importacao as svc
    a = svc.Analise(plataforma="matific", formato="resumo", turma_detectada="")
    a.linhas = [svc.LinhaImportacao(numero=1, nome="Ana Beatriz Souza",
                dados={"atividades": 10, "estrelas": 3, "pontuacao_media": 70.0})]
    return a, "xlsx"


def test_enfileirar_e_idempotente(db, escola_completa):
    from app.sync import service
    e = escola_completa["escola"].id
    a = service.enfileirar(db, e, "matific", origem="manual")
    b = service.enfileirar(db, e, "matific", origem="manual")  # não duplica
    assert a.id == b.id and a.status == "fila"


def test_executar_sucesso_cria_snapshot_e_logs(db, escola_completa, monkeypatch):
    from app.models.plataformas import SnapshotMatific
    from app.models.sincronizacao import SincronizacaoLog
    from app.sync import connectors, orchestrator, service, vault
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]

    vault.salvar_credencial(db, escola.id, "matific", Credenciais(usuario="u", senha="p"))
    arq = ArquivoObtido(conteudo=b"PKx", nome_arquivo="m.xlsx", plataforma="matific")
    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorFake(arquivos=[arq]))
    monkeypatch.setattr(orchestrator, "_parsear", lambda a: _analise_ana())

    ex = service.enfileirar(db, escola.id, "matific", origem="manual")
    service.executar(db, ex)

    assert ex.status == "concluida" and ex.qtd_alunos == 1 and ex.qtd_arquivos == 1
    assert db.query(SnapshotMatific).filter_by(escola_id=escola.id, aluno_id=ana.id).first()
    assert db.query(SincronizacaoLog).filter_by(execucao_id=ex.id).count() > 0
    # sucesso marca a credencial como válida
    assert vault.obter_linha(db, escola.id, "matific").status == "valida"


def test_executar_erro_recuperavel_reenfileira_com_backoff(db, escola_completa, monkeypatch):
    from app.models.sincronizacao import SincronizacaoAlerta, SincronizacaoExecucao
    from app.sync import connectors, service, vault
    escola = escola_completa["escola"]
    vault.salvar_credencial(db, escola.id, "matific", Credenciais(usuario="u", senha="p"))
    erro = ErroConector("timeout", codigo="timeout", recuperavel=True)
    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorFake(erro=erro))

    ex = service.enfileirar(db, escola.id, "matific", origem="scheduler")
    service.executar(db, ex)

    assert ex.status == "erro"
    # abriu alerta de timeout
    assert db.query(SincronizacaoAlerta).filter_by(escola_id=escola.id, tipo="timeout").first()
    # re-enfileirou uma tentativa 2 com disponivel_em no futuro (backoff)
    retry = db.query(SincronizacaoExecucao).filter_by(
        escola_id=escola.id, tentativa=2, status="fila").first()
    assert retry is not None and retry.disponivel_em is not None


def test_executar_senha_invalida_marca_credencial_e_nao_reenfileira(db, escola_completa, monkeypatch):
    from app.models.sincronizacao import SincronizacaoExecucao
    from app.sync import connectors, service, vault
    escola = escola_completa["escola"]
    vault.salvar_credencial(db, escola.id, "matific", Credenciais(usuario="u", senha="p"))
    erro = ErroConector("senha ruim", codigo="senha_invalida", recuperavel=False)
    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorFake(erro=erro))

    ex = service.enfileirar(db, escola.id, "matific", origem="scheduler")
    service.executar(db, ex)

    assert ex.status == "erro"
    assert vault.obter_linha(db, escola.id, "matific").status == "invalida"
    # não recuperável: nenhuma tentativa 2
    assert db.query(SincronizacaoExecucao).filter_by(
        escola_id=escola.id, tentativa=2).first() is None


def test_calcular_proxima_cadencias(db, escola_completa):
    from datetime import datetime
    from app.models.sincronizacao import SincronizacaoConfig
    from app.sync import service
    base = datetime(2026, 7, 11, 10, 0, 0)  # naive
    manual = SincronizacaoConfig(escola_id=1, plataforma="matific",
                                 ativo=True, cadencia="manual")
    assert service.calcular_proxima(manual, base) is None
    diaria = SincronizacaoConfig(escola_id=1, plataforma="matific",
                                 ativo=True, cadencia="diaria", hora_local="03:00")
    prox = service.calcular_proxima(diaria, base)
    assert prox.hour == 3 and prox.day == 12  # próximo dia às 03:00


# --------------------------------------------------------------------------
# API — isolamento multi-tenant e RBAC
# --------------------------------------------------------------------------
def test_api_isola_escola_e_exige_credencial(cliente, escola_completa):
    escola_id = escola_completa["escola"].id
    # status da própria escola: 200
    assert cliente.get(f"/api/v1/escolas/{escola_id}/sync/status").status_code == 200
    # escola de OUTREM (id+999): escola_autorizada barra (403/404)
    r = cliente.get(f"/api/v1/escolas/{escola_id + 999}/sync/status")
    assert r.status_code in (403, 404)
    # sincronizar sem credencial configurada -> 400 claro
    r2 = cliente.post(f"/api/v1/escolas/{escola_id}/sync/agora")
    assert r2.status_code == 400


def test_api_salvar_credenciais_valida_e_status(cliente, escola_completa, monkeypatch):
    from app.sync import connectors, service
    e = escola_completa["escola"].id
    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorFake())
    monkeypatch.setattr(service, "disparar_em_thread", lambda _id: None)

    r = cliente.put(f"/api/v1/escolas/{e}/sync/credenciais/matific",
                    json={"usuario": "prof@x", "senha": "segredo"})
    assert r.status_code == 200 and r.json()["ok"] is True

    st = cliente.get(f"/api/v1/escolas/{e}/sync/status").json()
    matific = next(p for p in st["plataformas"] if p["plataforma"] == "matific")
    assert matific["credencial_status"] == "valida" and matific["conectada"] is True

    # agora /agora enfileira (thread mockada) e devolve a execução
    ag = cliente.post(f"/api/v1/escolas/{e}/sync/agora?plataforma=matific")
    assert ag.status_code == 200 and ag.json()[0]["plataforma"] == "matific"
    # aparece no histórico
    hist = cliente.get(f"/api/v1/escolas/{e}/sync/historico").json()
    assert any(x["plataforma"] == "matific" for x in hist)


def test_api_salvar_credenciais_nunca_500_em_erro_de_navegador(
        cliente, escola_completa, monkeypatch):
    """Regressão do 500 em produção: quando a validação do login estoura no
    navegador (seletor mudou/timeout), o PUT responde 200 com ok=False e
    mensagem clara — a credencial FICA salva, sem vazar a senha, sem 500."""
    from app.sync import connectors, service

    e = escola_completa["escola"].id

    class NavegadorQuebra(NavegadorFake):
        async def ir_para(self, url):
            raise RuntimeError("net::ERR_TIMED_OUT ao abrir a página de login")

    ConectorReal = type(connectors.obter("matific"))    # conector REAL, browser fake
    monkeypatch.setitem(connectors._REGISTRO, "matific",
                        ConectorReal(_fabrica(NavegadorQuebra())))
    monkeypatch.setattr(service, "disparar_em_thread", lambda _id: None)

    r = cliente.put(f"/api/v1/escolas/{e}/sync/credenciais/matific",
                    json={"usuario": "prof@x", "senha": "senha-secreta"})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["ok"] is False
    assert corpo["codigo"] == "erro_navegador"
    assert "senha-secreta" not in (corpo["mensagem"] or "")

    # a credencial FOI gravada (fica como configurada/invalida, revalidável)
    st = cliente.get(f"/api/v1/escolas/{e}/sync/status").json()
    matific = next(p for p in st["plataformas"] if p["plataforma"] == "matific")
    assert matific["credencial_status"] == "invalida"
    assert st["integracao_configurada"] is True


def test_api_salvar_credenciais_conector_fora_do_contrato_nao_da_500(
        cliente, escola_completa, monkeypatch):
    """Rede de segurança do endpoint: mesmo um conector que viole o contrato e
    estoure em testar_credenciais não pode virar 500."""
    from app.sync import connectors

    e = escola_completa["escola"].id

    class ConectorEstoura(ConectorFake):
        async def testar_credenciais(self, cred, ctx):
            raise RuntimeError("boom inesperado")

    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorEstoura())
    r = cliente.put(f"/api/v1/escolas/{e}/sync/credenciais/matific",
                    json={"usuario": "u", "senha": "p"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False


def test_api_config_agenda_calcula_proxima(cliente, escola_completa):
    e = escola_completa["escola"].id
    r = cliente.put(f"/api/v1/escolas/{e}/sync/config/matific",
                    json={"ativo": True, "cadencia": "diaria", "hora_local": "03:00"})
    assert r.status_code == 200 and r.json()["proxima_execucao"] is not None


def test_api_logs_e_alertas(cliente, escola_completa, db):
    from app.sync import service
    e = escola_completa["escola"].id
    ex = service.enfileirar(db, e, "matific", origem="manual")
    service.registrar_log(db, ex, "download", "info", "baixando teste")
    service.abrir_alerta(db, e, "matific", "timeout", "demorou")
    db.commit()

    logs = cliente.get(f"/api/v1/escolas/{e}/sync/logs?execucao_id={ex.id}").json()
    assert any("baixando teste" in x["mensagem"] for x in logs)
    al = cliente.get(f"/api/v1/escolas/{e}/sync/alertas?resolvido=false").json()
    assert len(al) == 1 and al[0]["tipo"] == "timeout"
    assert cliente.post(f"/api/v1/escolas/{e}/sync/alertas/{al[0]['id']}/resolver").status_code == 204
    assert cliente.get(f"/api/v1/escolas/{e}/sync/alertas?resolvido=false").json() == []


def test_api_dashboard_exige_global(cliente, escola_completa):
    # o admin da escola NÃO é global -> 403 no painel cross-escola
    assert cliente.get("/api/v1/sync/dashboard").status_code == 403


def test_api_status_onboarding(cliente, escola_completa, monkeypatch):
    from app.sync import connectors, service
    e = escola_completa["escola"].id
    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorFake())
    monkeypatch.setattr(service, "disparar_em_thread", lambda _id: None)
    st = cliente.get(f"/api/v1/escolas/{e}/sync/status").json()
    assert st["lista_piloto_importada"] is True    # escola_completa já tem turma
    assert st["integracao_configurada"] is False   # sem credencial ainda
    cliente.put(f"/api/v1/escolas/{e}/sync/credenciais/matific",
                json={"usuario": "u", "senha": "p"})
    st2 = cliente.get(f"/api/v1/escolas/{e}/sync/status").json()
    assert st2["integracao_configurada"] is True   # Etapa 4: marcada


def test_scheduler_desligado_por_padrao():
    from app.sync import scheduler
    assert scheduler.iniciar() is False   # SYNC_SCHEDULER_ENABLED=False nos testes
    assert scheduler.ativo() is False


def test_uma_rodada_orquestra_agenda_e_fila(monkeypatch):
    from app.sync import scheduler, service
    chamou = {"agendados": 0, "executou": [], "reaper": 0}
    monkeypatch.setattr(service, "recuperar_execucoes_travadas",
                        lambda db: chamou.__setitem__("reaper", 1))
    monkeypatch.setattr(service, "enfileirar_agendados", lambda db: chamou.__setitem__("agendados", 1))

    class _FakeEx:
        id = 42
    monkeypatch.setattr(service, "proximas_da_fila", lambda db, limite: [_FakeEx()])
    monkeypatch.setattr(service, "executar_por_id", lambda eid: chamou["executou"].append(eid))
    scheduler._uma_rodada()
    assert chamou["agendados"] == 1 and chamou["executou"] == [42]


def test_orquestrador_sem_linhas_retorna_sem_dados(db, escola_completa, monkeypatch):
    from app.services import importacao as svc
    from app.sync import orchestrator
    escola = escola_completa["escola"]
    vazia = svc.Analise(plataforma="matific", formato="resumo")
    monkeypatch.setattr(orchestrator, "_parsear", lambda a: (vazia, "xlsx"))
    arq = ArquivoObtido(conteudo=b"PK", nome_arquivo="m.xlsx", plataforma="matific")
    res = orchestrator.aplicar_arquivo(db, escola, arq, usuario_id=None,
                                       recalcular=False, contexto=_contexto(escola.id))
    assert res["sem_dados"] is True and res["qtd_alunos"] == 0


def test_orquestrador_sem_ator_levanta_erro(db, monkeypatch):
    from app.models import Escola
    from app.services import importacao as svc
    from app.sync import orchestrator
    escola = Escola(nome="SEM ADMIN", ano_letivo_ativo=2026)
    db.add(escola)
    db.flush()
    a = svc.Analise(plataforma="matific", formato="resumo")
    a.linhas = [svc.LinhaImportacao(numero=1, nome="Fulano", dados={})]
    monkeypatch.setattr(orchestrator, "_parsear", lambda x: (a, "xlsx"))
    monkeypatch.setattr(orchestrator.imp, "_guardar_temporario", lambda *a, **k: None)
    import pytest
    with pytest.raises(RuntimeError):
        orchestrator.aplicar_arquivo(db, escola, ArquivoObtido(
            conteudo=b"PK", nome_arquivo="m.xlsx", plataforma="matific"),
            usuario_id=None, recalcular=False, contexto=_contexto(escola.id))


# --- conectores: localizar/obter, login não-confirmado, SSO, download vazio ---
def test_matific_localizar_e_obter(_=None):
    from app.sync.connectors.matific import ConectorMatific
    cred = Credenciais(usuario="a", senha="b")
    rels = asyncio.run(ConectorMatific(_fabrica(NavegadorFake())).localizar_relatorios(cred, _contexto()))
    assert len(rels) == 1 and rels[0].plataforma == "matific"
    arq = asyncio.run(ConectorMatific(_fabrica(NavegadorFake(conteudo=b"PKm")))
                      .obter(cred, rels[0], _contexto()))
    assert arq.conteudo == b"PKm" and arq.plataforma == "matific"


def test_login_nao_confirmado_e_recuperavel():
    from app.sync.connectors.matific import ConectorMatific
    # sem sucesso e sem erro visível -> falha_auth recuperável
    r = asyncio.run(ConectorMatific(_fabrica(NavegadorFake(logado=False, erro_login=False)))
                    .testar_credenciais(Credenciais(usuario="a", senha="b"), _contexto()))
    assert not r.ok and r.codigo == "falha_auth"


def test_elefante_sso_google_bloqueia_com_mensagem():
    from app.sync.connectors.elefante import ConectorElefante
    r = asyncio.run(ConectorElefante(_fabrica(NavegadorFake()))
                    .testar_credenciais(Credenciais(usuario="a", senha="b", extra={"sso": "google"}), _contexto()))
    assert not r.ok and "Google" in r.mensagem


def test_download_vazio_vira_erro():
    from app.sync.connectors.matific import ConectorMatific, _URL_LEADERBOARD
    from app.sync.interfaces import RelatorioDisponivel
    rel = RelatorioDisponivel(plataforma="matific", tipo="leaderboard", identificador=_URL_LEADERBOARD)
    r = asyncio.run(ConectorMatific(_fabrica(NavegadorFake())).testar_credenciais(
        Credenciais(usuario="a", senha="b"), _contexto()))
    assert r.ok  # login ok
    import pytest
    with pytest.raises(ErroConector):
        asyncio.run(ConectorMatific(_fabrica(NavegadorFake(conteudo=b"")))
                    .obter(Credenciais(usuario="a", senha="b"), rel, _contexto()))


# --- API: testar/remover/detalhe/sincronizar ---
def test_api_testar_remover_e_detalhe(cliente, escola_completa, monkeypatch):
    from app.sync import connectors, service
    e = escola_completa["escola"].id
    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorFake())
    monkeypatch.setattr(service, "disparar_em_thread", lambda _id: None)
    # testar sem credencial -> 400
    assert cliente.post(f"/api/v1/escolas/{e}/sync/credenciais/matific/testar").status_code == 400
    # salva -> testar -> 200
    cliente.put(f"/api/v1/escolas/{e}/sync/credenciais/matific",
                json={"usuario": "u", "senha": "p"})
    assert cliente.post(f"/api/v1/escolas/{e}/sync/credenciais/matific/testar").json()["ok"] is True
    # sincronizar agora enfileira
    rp = cliente.post(f"/api/v1/escolas/{e}/sync/agora?plataforma=matific")
    assert rp.status_code == 200
    exec_id = rp.json()[0]["id"]
    # detalhe da própria execução: 200; de id inexistente: 404
    assert cliente.get(f"/api/v1/escolas/{e}/sync/execucoes/{exec_id}").status_code == 200
    assert cliente.get(f"/api/v1/escolas/{e}/sync/execucoes/999999").status_code == 404
    # remover credencial: 204
    assert cliente.delete(f"/api/v1/escolas/{e}/sync/credenciais/matific").status_code == 204


def test_scheduler_liga_e_desliga(monkeypatch):
    from app.core.config import settings
    from app.sync import scheduler
    monkeypatch.setattr(settings, "SYNC_SCHEDULER_ENABLED", True)
    monkeypatch.setattr(settings, "SYNC_POLL_S", 1)
    monkeypatch.setattr(scheduler, "_uma_rodada", lambda: None)  # não toca banco real
    try:
        assert scheduler.iniciar() is True
        assert scheduler.ativo() is True
    finally:
        scheduler.parar(timeout=2)
    assert scheduler.ativo() is False


def test_enfileirar_agendados_enfileira_vencidos(db, escola_completa):
    from datetime import datetime
    from app.models.sincronizacao import SincronizacaoConfig, SincronizacaoExecucao
    from app.sync import service
    e = escola_completa["escola"].id
    db.add(SincronizacaoConfig(escola_id=e, plataforma="matific", ativo=True,
                               cadencia="diaria", hora_local="03:00",
                               proxima_execucao=datetime(2020, 1, 1)))
    db.commit()
    assert service.enfileirar_agendados(db) == 1
    assert db.query(SincronizacaoExecucao).filter_by(escola_id=e, origem="scheduler").first()


def test_calcular_proxima_semanal(db):
    from datetime import datetime
    from app.models.sincronizacao import SincronizacaoConfig
    from app.sync import service
    cfg = SincronizacaoConfig(escola_id=1, plataforma="matific", ativo=True,
                              cadencia="semanal", hora_local="03:00", dia_semana=0)
    prox = service.calcular_proxima(cfg, datetime(2026, 7, 11, 10, 0, 0))  # sábado
    assert prox is not None and prox.weekday() == 0  # segunda-feira


def test_executar_lento_abre_alerta(db, escola_completa, monkeypatch):
    from app.core.config import settings
    from app.models.sincronizacao import SincronizacaoAlerta
    from app.sync import connectors, orchestrator, service, vault
    monkeypatch.setattr(settings, "SYNC_LENTO_S", 0)  # qualquer duração vira "lento"
    escola = escola_completa["escola"]
    vault.salvar_credencial(db, escola.id, "matific", Credenciais(usuario="u", senha="p"))
    arq = ArquivoObtido(conteudo=b"PK", nome_arquivo="m.xlsx", plataforma="matific")
    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorFake(arquivos=[arq]))
    monkeypatch.setattr(orchestrator, "_parsear", lambda a: _analise_ana())
    ex = service.enfileirar(db, escola.id, "matific", origem="manual")
    service.executar(db, ex)
    assert db.query(SincronizacaoAlerta).filter_by(escola_id=escola.id, tipo="lento").first()


def test_dashboard_global_ok(db, escola_completa):
    from fastapi.testclient import TestClient
    from app.core.security import hash_senha
    from app.main import app
    from app.models import Usuario
    db.add(Usuario(escola_id=escola_completa["escola"].id, nome="Global",
                   email="global@teste.local", senha_hash=hash_senha("s3nh4g"),
                   cargo="admin", is_global=True))
    db.commit()
    c = TestClient(app)
    login = c.post("/api/v1/auth/login",
                   data={"username": "global@teste.local", "password": "s3nh4g"})
    c.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    r = c.get("/api/v1/sync/dashboard")
    assert r.status_code == 200 and "escolas_total" in r.json()


# --------------------------------------------------------------------------
# Concorrência, retry-limite, credencial ilegível, isolamento e cascata
# --------------------------------------------------------------------------
def test_indice_unico_barra_duas_execucoes_ativas(db, escola_completa):
    """Garantia de banco: no máximo UMA execução ativa por (escola, plataforma).
    Dois INSERTs ativos concorrentes → IntegrityError (o segundo perde)."""
    from sqlalchemy.exc import IntegrityError
    from app.models.sincronizacao import SincronizacaoExecucao
    e = escola_completa["escola"].id
    db.add(SincronizacaoExecucao(escola_id=e, plataforma="matific",
                                 origem="manual", status="fila"))
    db.flush()
    db.add(SincronizacaoExecucao(escola_id=e, plataforma="matific",
                                 origem="scheduler", status="executando"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_reexecutar_execucao_ja_finalizada_nao_reprocessa(db, escola_completa, monkeypatch):
    """Claim atômico: chamar executar() de novo na MESMA execução (já não está
    em 'fila') não reprocessa — rowcount 0 e nenhum log/arquivo novo."""
    from app.models.sincronizacao import SincronizacaoLog
    from app.sync import connectors, orchestrator, service, vault
    escola = escola_completa["escola"]
    vault.salvar_credencial(db, escola.id, "matific", Credenciais(usuario="u", senha="p"))
    arq = ArquivoObtido(conteudo=b"PK", nome_arquivo="m.xlsx", plataforma="matific")
    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorFake(arquivos=[arq]))
    monkeypatch.setattr(orchestrator, "_parsear", lambda a: _analise_ana())
    ex = service.enfileirar(db, escola.id, "matific", origem="manual")
    service.executar(db, ex)
    assert ex.status == "concluida"
    logs1 = db.query(SincronizacaoLog).filter_by(execucao_id=ex.id).count()
    service.executar(db, ex)              # 2ª vez: claim WHERE status='fila' falha
    logs2 = db.query(SincronizacaoLog).filter_by(execucao_id=ex.id).count()
    assert logs1 == logs2                 # não reprocessou


def test_retry_para_no_limite_de_tentativas(db, escola_completa, monkeypatch):
    """Na ÚLTIMA tentativa (SYNC_MAX_TENTATIVAS), um erro recuperável não
    re-enfileira — a execução simplesmente termina em 'erro'."""
    from app.core.config import settings
    from app.models.sincronizacao import SincronizacaoExecucao
    from app.sync import connectors, service, vault
    e = escola_completa["escola"].id
    vault.salvar_credencial(db, e, "matific", Credenciais(usuario="u", senha="p"))
    erro = ErroConector("timeout", codigo="timeout", recuperavel=True)
    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorFake(erro=erro))
    ex = service.enfileirar(db, e, "matific", origem="scheduler",
                            tentativa=settings.SYNC_MAX_TENTATIVAS)
    service.executar(db, ex)
    assert ex.status == "erro"
    assert db.query(SincronizacaoExecucao).filter_by(
        escola_id=e, tentativa=settings.SYNC_MAX_TENTATIVAS + 1).first() is None


def test_credencial_indecifravel_vira_none(db, escola_completa):
    """SECRET_KEY trocada / segredo corrompido: obter_credencial devolve None em
    vez de estourar — o segredo ilegível nunca vira um crash."""
    e = escola_completa["escola"].id
    linha = vault.salvar_credencial(db, e, "matific", Credenciais(usuario="u", senha="p"))
    linha.segredo_cifrado = "isto-nao-decifra"   # simula rotação de chave
    db.flush()
    assert vault.obter_credencial(db, e, "matific") is None


def test_executar_credencial_ilegivel_marca_invalida(db, escola_completa, monkeypatch):
    """Execução com credencial ilegível falha de forma limpa (senha_invalida,
    não recuperável) e marca a credencial como inválida — sem retry infinito."""
    from app.models.sincronizacao import SincronizacaoExecucao
    from app.sync import connectors, service, vault
    e = escola_completa["escola"].id
    linha = vault.salvar_credencial(db, e, "matific", Credenciais(usuario="u", senha="p"))
    linha.segredo_cifrado = "corrompido"
    db.flush()
    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorFake(arquivos=[]))
    ex = service.enfileirar(db, e, "matific", origem="scheduler")
    service.executar(db, ex)
    assert ex.status == "erro"
    assert vault.obter_linha(db, e, "matific").status == "invalida"
    assert db.query(SincronizacaoExecucao).filter_by(
        escola_id=e, tentativa=2).first() is None   # não recuperável


def test_erro_generico_nao_vaza_segredo(db, escola_completa, monkeypatch):
    """Uma exceção INESPERADA (não ErroConector) é logada só pelo tipo — nunca
    com a mensagem crua, que poderia carregar segredo/PII."""
    from app.models.sincronizacao import SincronizacaoLog
    from app.sync import connectors, service, vault
    e = escola_completa["escola"].id
    vault.salvar_credencial(db, e, "matific", Credenciais(usuario="u", senha="p"))
    boom = ValueError("stacktrace com senha=TOPSECRET e aluno João")
    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorFake(erro=boom))
    ex = service.enfileirar(db, e, "matific", origem="manual")
    service.executar(db, ex)
    assert ex.status == "erro"
    assert "TOPSECRET" not in (ex.erro_resumo or "")
    msgs = [x.mensagem for x in db.query(SincronizacaoLog).filter_by(execucao_id=ex.id)]
    assert all("TOPSECRET" not in m for m in msgs)


def test_enfileirar_agendados_multi_escola(db, escola_completa):
    """Duas escolas com agenda vencida → cada uma enfileira a SUA execução, sem
    interferência entre tenants."""
    from datetime import datetime
    from app.models import Escola
    from app.models.sincronizacao import SincronizacaoConfig, SincronizacaoExecucao
    from app.sync import service
    e1 = escola_completa["escola"].id
    outra = Escola(nome="OUTRA ESCOLA", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    for eid in (e1, outra.id):
        db.add(SincronizacaoConfig(escola_id=eid, plataforma="matific", ativo=True,
                                   cadencia="diaria", hora_local="03:00",
                                   proxima_execucao=datetime(2020, 1, 1)))
    db.commit()
    assert service.enfileirar_agendados(db) == 2
    assert db.query(SincronizacaoExecucao).filter_by(
        escola_id=e1, origem="scheduler").count() == 1
    assert db.query(SincronizacaoExecucao).filter_by(
        escola_id=outra.id, origem="scheduler").count() == 1


def test_agora_sem_plataforma_pula_quem_nao_tem_credencial(cliente, escola_completa, monkeypatch):
    """/agora sem plataforma cobre todas as automatizáveis, mas pula em silêncio
    as que não têm credencial (só Matific configurada → só Matific enfileira)."""
    from app.sync import connectors, service
    e = escola_completa["escola"].id
    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorFake())
    monkeypatch.setattr(service, "disparar_em_thread", lambda _id: None)
    cliente.put(f"/api/v1/escolas/{e}/sync/credenciais/matific",
                json={"usuario": "u", "senha": "p"})
    r = cliente.post(f"/api/v1/escolas/{e}/sync/agora")   # sem ?plataforma
    assert r.status_code == 200
    assert {x["plataforma"] for x in r.json()} == {"matific"}


def test_config_desativar_limpa_proxima_execucao(cliente, escola_completa):
    """Desligar a agenda zera proxima_execucao — o worker não a pega mais."""
    e = escola_completa["escola"].id
    r1 = cliente.put(f"/api/v1/escolas/{e}/sync/config/matific",
                     json={"ativo": True, "cadencia": "diaria", "hora_local": "03:00"})
    assert r1.json()["proxima_execucao"] is not None
    r2 = cliente.put(f"/api/v1/escolas/{e}/sync/config/matific",
                     json={"ativo": False, "cadencia": "manual", "hora_local": "03:00"})
    assert r2.json()["proxima_execucao"] is None


def test_ondelete_execucao_cascata_logs_e_solta_alerta(db, escola_completa):
    """ON DELETE da execução: logs somem (CASCADE) e o alerta preserva o
    histórico com execucao_id em NULL (SET NULL)."""
    from app.models.sincronizacao import (
        SincronizacaoAlerta, SincronizacaoExecucao, SincronizacaoLog)
    from app.sync import service
    e = escola_completa["escola"].id
    ex = service.enfileirar(db, e, "matific", origem="manual")
    service.registrar_log(db, ex, "download", "info", "linha de log")
    service.abrir_alerta(db, e, "matific", "timeout", "erro", execucao_id=ex.id)
    db.commit()
    alerta = db.query(SincronizacaoAlerta).filter_by(escola_id=e).one()
    assert db.query(SincronizacaoLog).filter_by(execucao_id=ex.id).count() == 1
    db.delete(db.get(SincronizacaoExecucao, ex.id))
    db.commit()
    assert db.query(SincronizacaoLog).filter_by(execucao_id=ex.id).count() == 0
    db.refresh(alerta)
    assert alerta.execucao_id is None


def test_reaper_recupera_execucao_travada_e_reenfileira(db, escola_completa, monkeypatch):
    """Retomada após crash: uma execução presa em 'executando' além de
    SYNC_TRAVADA_S (worker morto/redeploy) é finalizada como 'erro' e
    re-enfileirada — a escola não fica travada pela exclusão mútua."""
    from datetime import datetime, timedelta, timezone
    from app.core.config import settings
    from app.models.sincronizacao import SincronizacaoAlerta, SincronizacaoExecucao
    from app.sync import service
    monkeypatch.setattr(settings, "SYNC_TRAVADA_S", 1800)
    e = escola_completa["escola"].id
    velho = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=3600)
    ex = service.enfileirar(db, e, "matific", origem="scheduler")
    ex.status = "executando"
    ex.iniciada_em = velho
    db.commit()

    assert service.recuperar_execucoes_travadas(db) == 1
    db.refresh(ex)
    assert ex.status == "erro"
    # re-enfileirou uma nova execução na fila (retomada)
    nova = db.query(SincronizacaoExecucao).filter_by(
        escola_id=e, status="fila", tentativa=2).first()
    assert nova is not None
    assert db.query(SincronizacaoAlerta).filter_by(
        escola_id=e, tipo="interrompida").first() is not None


def test_reaper_ignora_execucao_recente(db, escola_completa):
    """Uma execução que começou agora (viva) NÃO é recuperada — só as órfãs."""
    from app.sync import service
    e = escola_completa["escola"].id
    ex = service.enfileirar(db, e, "matific", origem="manual")
    ex.status = "executando"
    ex.iniciada_em = service._agora()   # começou agora
    db.commit()
    assert service.recuperar_execucoes_travadas(db) == 0
    db.refresh(ex)
    assert ex.status == "executando"    # intacta


def test_enfileirar_perde_corrida_do_reaper_ainda_honra_o_pedido(db, escola_completa, monkeypatch):
    """TOCTOU: se o reaper concorrente reivindica a órfã entre o SELECT e o
    UPDATE de enfileirar (na ÚLTIMA tentativa, sem re-enfileiramento), enfileirar
    NÃO pode devolver a órfã morta — precisa re-checar e criar a execução pedida,
    senão o clique do admin some em silêncio."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import update
    from app.core.config import settings
    from app.models.sincronizacao import SincronizacaoExecucao
    from app.sync import service
    monkeypatch.setattr(settings, "SYNC_TRAVADA_S", 1800)
    e = escola_completa["escola"].id
    orfa = service.enfileirar(db, e, "matific", origem="scheduler",
                              tentativa=settings.SYNC_MAX_TENTATIVAS)
    orfa.status = "executando"
    orfa.iniciada_em = (datetime.now(timezone.utc).replace(tzinfo=None)
                        - timedelta(seconds=3600))
    db.commit()

    # Simula o reaper concorrente vencendo a corrida: marca a órfã como 'erro' e
    # devolve False (ESTE chamador perdeu o claim atômico).
    def reaper_venceu(_db, ex):
        _db.execute(update(SincronizacaoExecucao)
                    .where(SincronizacaoExecucao.id == ex.id).values(status="erro"))
        _db.flush()
        return False
    monkeypatch.setattr(service, "_finalizar_travada", reaper_venceu)

    nova = service.enfileirar(db, e, "matific", origem="manual")
    assert nova.id != orfa.id and nova.status == "fila"   # pedido honrado, não perdido


def test_enfileirar_auto_cura_execucao_travada(db, escola_completa, monkeypatch):
    """enfileirar() auto-cura: se a 'ativa' é uma órfã presa em 'executando',
    ela é liberada e uma nova entra na fila (o botão volta a funcionar sem
    esperar o scheduler)."""
    from datetime import datetime, timedelta, timezone
    from app.core.config import settings
    from app.sync import service
    monkeypatch.setattr(settings, "SYNC_TRAVADA_S", 1800)
    e = escola_completa["escola"].id
    travada = service.enfileirar(db, e, "matific", origem="manual")
    travada.status = "executando"
    travada.iniciada_em = (datetime.now(timezone.utc).replace(tzinfo=None)
                           - timedelta(seconds=3600))
    db.commit()

    nova = service.enfileirar(db, e, "matific", origem="manual")
    assert nova.id != travada.id and nova.status == "fila"
    db.refresh(travada)
    assert travada.status == "erro"


def test_ondelete_escola_purga_todas_as_tabelas_sync(db):
    """Apagar a escola remove TODAS as 5 tabelas do módulo (CASCADE por
    escola_id) — sem deixar credencial/histórico órfão de outro tenant."""
    from app.models import Escola
    from app.models.sincronizacao import (
        PlataformaCredencial, SincronizacaoAlerta, SincronizacaoConfig,
        SincronizacaoExecucao, SincronizacaoLog)
    from app.sync import service, vault
    escola = Escola(nome="PURGE", ano_letivo_ativo=2026)
    db.add(escola)
    db.flush()
    eid = escola.id
    vault.salvar_credencial(db, eid, "matific", Credenciais(usuario="u", senha="p"))
    db.add(SincronizacaoConfig(escola_id=eid, plataforma="matific"))
    ex = service.enfileirar(db, eid, "matific", origem="manual")
    service.registrar_log(db, ex, "download", "info", "x")
    service.abrir_alerta(db, eid, "matific", "timeout", "y")
    db.commit()
    db.delete(db.get(Escola, eid))
    db.commit()
    for Modelo in (PlataformaCredencial, SincronizacaoConfig, SincronizacaoExecucao,
                   SincronizacaoLog, SincronizacaoAlerta):
        assert db.query(Modelo).filter_by(escola_id=eid).count() == 0
