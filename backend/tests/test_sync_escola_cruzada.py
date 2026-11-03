"""Proteção contra dados de OUTRA escola na sincronização (Etapa 3, frente escola).

Cenários NEGATIVOS (nada é aplicado, alerta crítico, código próprio) e controles
POSITIVOS, com os conectores REAIS (Elefante e Matific) sobre navegador FALSO e o
serviço real (enfileirar → executar → orquestrador → confirmar). Dados 100%
fictícios; sem rede; sem login real. Regras em ``app/sync/escola_externa.py`` e
em docs/SINCRONIZACAO.md ("Escola externa").
"""
import re

from sqlalchemy import func, select

from app.core.security import hash_senha
from app.models import Aluno, Configuracao, Escola, Matricula, Turma, Usuario
from app.models.nota import LogAuditoria
from app.models.plataformas import SnapshotElefante, SnapshotMatific
from app.models.sincronizacao import SincronizacaoAlerta
from app.services import scoring
from app.sync import connectors, escola_externa, orchestrator, vault
from app.sync.connectors import elefante as con_elefante
from app.sync.connectors import matific as con_matific
from tests._sync_nucleo_fakes import (
    API, SCHOOL_UUID, NavElefante, NavMatific, PlacarFake, aluno_el, alertas_abertos,
    contagens, credencial, livro, logs, rodar)

ESC_A, NOME_A = 23952, "EMEF ESCOLA TESTE"          # a escola desta conta (fictícia)
ESC_B, NOME_B = 23953, "EMEF OUTRA UNIDADE FICTICIA"
CID_A, CID_B, CID_C = 511434, 611434, 711434
K = "3 ANO A (300396804)"
OUTRA_UUID = "e92e92e9-0000-0000-0000-0000000000bb"


# ---------------------------------------------------------------------------
# Navegadores falsos com ESCOLAS
# ---------------------------------------------------------------------------
class NavEl(NavElefante):
    """Elefante com escolas: ``ativas`` [(id, nome)] em /school/active-schools;
    ``escola_da_turma`` {course_id: schoolId | None} no roster (ausente/None =
    turma sem ``schoolId``); a API direta (``?schoolId=``) devolve as turmas da
    escola pedida; ``trafego=False``: o SPA não dispara o roster sozinho."""

    def __init__(self, turmas, *, ativas=((ESC_A, NOME_A),), escola_da_turma=None,
                 trafego=True, **kw):
        super().__init__(turmas, **kw)
        self.ativas = list(ativas)
        self.escola_da_turma = dict(escola_da_turma or {})
        self.trafego = trafego
        self.rosters = []          # schoolId pedido na API direta ('' = sem)

    def _cursos(self, escola=None):
        nomes = dict(self.ativas)
        saida = []
        for c in super()._cursos():
            sid = self.escola_da_turma.get(c["id"])
            if sid is not None:
                c = {**c, "schoolId": sid, "schoolName": nomes.get(sid, NOME_B)}
            if escola is None or "schoolId" not in c or str(c["schoolId"]) == str(escola):
                saida.append(c)
        return saida

    async def coletar_respostas(self, url, timeout_s=25):
        base = "https://prod-ecs-apiadmin.elefanteletrado.com.br"
        caps = [{"url": f"{base}/school/active-schools",
                 "json": [{"id": i, "fantasyName": n} for i, n in self.ativas],
                 "req_auth": "Bearer FICTICIO"}]
        cursos = self._cursos()
        if self.trafego and cursos:
            caps.append({"url": f"{base}/course/get-courses-students", "json": cursos})
        return caps

    async def avaliar(self, expressao):
        if "fetch(" in expressao and "get-courses-students" in expressao:
            m = re.search(r"schoolId=(\d+)", expressao)
            self.rosters.append(m.group(1) if m else "")
            corpo = self._cursos(m.group(1) if m else None)
            return {"ok": True, "status": 200, "tipo": "list", "n": len(corpo), "body": corpo}
        return await super().avaliar(expressao)


class NavMt(NavMatific):
    """Matific com escola: ``school_id`` do accounts/current ('' = não informa) e
    ``trafego`` = school_ids nas requisições que a página do Placar dispara."""

    def __init__(self, placar, *, school_id=SCHOOL_UUID, trafego=()):
        super().__init__(placar)
        self.school_id = school_id
        self.trafego = list(trafego)
        self.pedidos_ss = []       # school_id pedido no school_student

    async def coletar_respostas(self, url, timeout_s=25):
        return [{"url": "https://www.matific.com/api/v2/reports/leaderboard/school_student/"
                        f"?duration=this-year&school_id={s}"} for s in self.trafego]

    async def avaliar(self, expr):
        if "accounts/current" in expr:
            return {"ok": True, "status": 200,
                    "body": {"school_id": self.school_id} if self.school_id else {}}
        if "school_student" in expr:
            m = re.search(r"school_id=([0-9a-f-]{36})", expr)
            self.pedidos_ss.append(m.group(1) if m else "")
        return await super().avaliar(expr)


def _fabrica(nav):
    async def fab(**_kw):
        return nav
    return fab


def instalar_navs(monkeypatch, *, elefante=None, matific=None):
    monkeypatch.setattr(con_elefante, "_SETTLE_S", 0)
    registro = {}
    if elefante is not None:
        registro["elefante"] = con_elefante.ConectorElefante(_fabrica(elefante))
    if matific is not None:
        registro["matific"] = con_matific.ConectorMatific(_fabrica(matific))
    original = connectors.obter
    monkeypatch.setattr(connectors, "obter", lambda p: registro.get(p) or original(p))
    monkeypatch.setattr(orchestrator.imp, "_guardar_temporario", lambda *a, **k: None)
    return registro


def _turmas(ec, *, com_c=False):
    a, b, c = ec["alunos"]
    turmas = {CID_A: {"nome": "3 ANO A", "escola": NOME_A, "alunos": [
        aluno_el(7001, a.nome, [livro("Livro A1")]),
        aluno_el(7002, b.nome, [livro("Livro B1")])]},
        CID_B: {"nome": "3 ANO A", "escola": NOME_B, "alunos": [
            aluno_el(8001, "Criança Ficticia Da Outra Escola", [livro("Livro O1")])]}}
    if com_c:
        turmas[CID_C] = {"nome": "3 ANO A", "escola": NOME_A, "alunos": [
            aluno_el(7003, c.nome, [livro("Livro C1")])]}
    return turmas


def _placar(ec):
    a, b, c = ec["alunos"]
    p = PlacarFake()
    p.linhas = [("u-a", a.nome, K, 40, 10), ("u-b", b.nome, K, 30, 8),
                ("u-c", c.nome, K, 20, 5)]
    return p


def _alerta(db, eid, tipo):
    return db.execute(select(SincronizacaoAlerta).where(
        SincronizacaoAlerta.escola_id == eid, SincronizacaoAlerta.tipo == tipo,
        SincronizacaoAlerta.resolvido.is_(False))).scalars().first()


def _nova_escola(db, nome="ESCOLA SEGUNDA FICTICIA", com_alunos=()):
    escola = Escola(nome=nome, ano_letivo_ativo=2026)
    db.add(escola)
    db.flush()
    db.add(Usuario(escola_id=escola.id, nome="Admin 2", email=f"admin{escola.id}@teste.local",
                   senha_hash=hash_senha("s3nh4"), cargo="admin"))
    for namespace, valores in scoring.PESOS_PADRAO.items():
        db.add(Configuracao(escola_id=escola.id, namespace=namespace, chave="valores",
                            valor=valores))
    turma = Turma(escola_id=escola.id, nome="3º Ano A", ano_escolar="3º Ano", ano_letivo=2026)
    db.add(turma)
    db.flush()
    alunos = []
    for nome_aluno in com_alunos:
        al = Aluno(escola_id=escola.id, nome=nome_aluno)
        db.add(al)
        db.flush()
        db.add(Matricula(escola_id=escola.id, aluno_id=al.id, turma_id=turma.id, ano_letivo=2026))
        alunos.append(al)
    db.commit()
    return escola, turma, alunos


def _sem_retrato_do_dia(c: dict) -> dict:
    """Contagens sem os retratos do Elefante e as importações. A 2ª coleta é a
    recoleta COMPLETA semanal (não havia marca) e o importador de leituras grava um
    retrato a mais NO MESMO DIA, com os mesmos números — comportamento que já
    existe no 5e388b6 (sonda em e95/escola), fora do escopo desta frente. O resto
    (fichas, matrículas, turmas, identidades, leituras, eventos, revisões, notas)
    não pode mudar; a 3ª coleta compara tudo."""
    return {k: v for k, v in c.items() if k not in ("snap_el", "importacoes")}


def _da_escola(c: dict) -> dict:
    """Contagens POR ESCOLA ('livros' é o catálogo global, de todas)."""
    return {k: v for k, v in c.items() if k != "livros"}


def _n(db, modelo, eid):
    return db.scalar(select(func.count()).select_from(modelo).where(modelo.escola_id == eid))


# ===========================================================================
# ELEFANTE
# ===========================================================================
def test_elefante_conta_de_uma_escola_aprende_o_vinculo_e_coleta(db, escola_completa,
                                                                monkeypatch):
    """Controle positivo: conta que enxerga EXATAMENTE uma escola → o vínculo é
    aprendido na 1ª coleta e a coleta segue normal; repetir não duplica nada."""
    eid = escola_completa["escola"].id
    credencial(db, eid, "elefante")
    turmas = _turmas(escola_completa)
    del turmas[CID_B]
    nav = NavEl(turmas, escola_da_turma={CID_A: ESC_A})
    instalar_navs(monkeypatch, elefante=nav)
    ex1, e1 = rodar(db, eid, "elefante")
    assert e1 is None and ex1.status == "concluida", (ex1.status, ex1.motivo, ex1.erro_resumo)
    vinculo = escola_externa.obter(db, eid, "elefante")
    assert vinculo["id"] == str(ESC_A) and vinculo["nome"] == NOME_A
    assert vinculo["origem"] == "aprendido"
    assert db.scalar(select(func.count()).select_from(LogAuditoria).where(
        LogAuditoria.acao == "sync.escola_externa_aprendida")) == 1
    assert nav.course_reports == [CID_A]
    antes = contagens(db, eid)
    ex2, _ = rodar(db, eid, "elefante")
    assert (ex2.status, ex2.motivo) == ("sem_atualizacao", "nada_mudou")
    depois = contagens(db, eid)
    assert _sem_retrato_do_dia(depois) == _sem_retrato_do_dia(antes)
    ex3, _ = rodar(db, eid, "elefante")
    assert (ex3.status, ex3.motivo) == ("sem_atualizacao", "nada_mudou")
    assert {k: v for k, v in contagens(db, eid).items() if k != "importacoes"} == \
        {k: v for k, v in depois.items() if k != "importacoes"}
    assert escola_externa.obter(db, eid, "elefante")["definido_em"] == vinculo["definido_em"]


def test_elefante_conta_com_duas_escolas_sem_vinculo_e_erro_e_nada_aplicado(
        db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "elefante")
    nav = NavEl(_turmas(escola_completa), ativas=((ESC_A, NOME_A), (ESC_B, NOME_B)),
                escola_da_turma={CID_A: ESC_A, CID_B: ESC_B})
    instalar_navs(monkeypatch, elefante=nav)
    antes = contagens(db, eid)
    ex, erro = rodar(db, eid, "elefante")
    assert erro is None
    assert (ex.status, ex.motivo) == ("erro", "conta_multiescola")
    assert str(ESC_A) in ex.erro_resumo and str(ESC_B) in ex.erro_resumo
    assert contagens(db, eid) == antes                 # nada aplicado
    assert nav.course_reports == []                    # nenhum dado de turma pedido
    alerta = _alerta(db, eid, "conta_multiescola")
    assert alerta is not None and alerta.severidade == "critico"
    assert escola_externa.obter(db, eid, "elefante") is None
    # A credencial NÃO é dada como válida nem como recusada (o login funcionou).
    assert vault.obter_linha(db, eid, "elefante").status not in ("valida", "invalida")


def test_elefante_conta_com_duas_escolas_com_vinculo_explicito_coleta_so_a_vinculada(
        db, escola_completa, cliente_global, monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "elefante")
    # O vínculo explícito é gravado pelo Admin Global (revisão e97).
    r = cliente_global.put(f"{API}/escolas/{eid}/sync/escola-externa/elefante",
                           json={"id_externo": str(ESC_A), "nome": NOME_A})
    assert r.status_code == 200, r.text
    assert r.json()["origem"] == "explicito"
    nav = NavEl(_turmas(escola_completa), ativas=((ESC_A, NOME_A), (ESC_B, NOME_B)),
                escola_da_turma={CID_A: ESC_A, CID_B: ESC_B})
    instalar_navs(monkeypatch, elefante=nav)
    ex, erro = rodar(db, eid, "elefante")
    assert erro is None and ex.status == "concluida", (ex.status, ex.motivo, ex.erro_resumo)
    assert nav.course_reports == [CID_A]               # a turma da outra escola: nunca pedida
    nomes = {a.nome for a in db.execute(select(Aluno).where(Aluno.escola_id == eid)).scalars()}
    assert "Criança Ficticia Da Outra Escola" not in nomes
    assert any("turma(s) de outra(s) escola(s)" in m for _e, _n2, m in logs(db, ex.id))
    assert escola_externa.obter(db, eid, "elefante")["origem"] == "explicito"


def test_elefante_vinculo_explicito_sem_turma_dela_no_trafego_pede_a_lista_por_escola(
        db, escola_completa, cliente, monkeypatch):
    """O painel abriu as turmas da OUTRA escola da conta: a lista da vinculada vem
    da API direta pedida com o schoolId dela (nunca a chamada sem escola)."""
    eid = escola_completa["escola"].id
    credencial(db, eid, "elefante")
    escola_externa.salvar(db, eid, "elefante", str(ESC_A), NOME_A, origem="explicito")
    db.commit()
    turmas = _turmas(escola_completa)

    class _SoOutraNoTrafego(NavEl):
        async def coletar_respostas(self, url, timeout_s=25):
            caps = await super().coletar_respostas(url, timeout_s)
            for c in caps:
                if "get-courses-students" in c["url"]:
                    c["json"] = [x for x in c["json"] if x.get("schoolId") == ESC_B]
            return caps

    nav = _SoOutraNoTrafego(turmas, ativas=((ESC_A, NOME_A), (ESC_B, NOME_B)),
                            escola_da_turma={CID_A: ESC_A, CID_B: ESC_B})
    instalar_navs(monkeypatch, elefante=nav)
    ex, _ = rodar(db, eid, "elefante")
    assert ex.status == "concluida", (ex.status, ex.motivo, ex.erro_resumo)
    assert "" not in nav.rosters and set(nav.rosters) == {str(ESC_A)}
    assert nav.course_reports == [CID_A]


def test_elefante_escola_externa_que_muda_entre_coletas_e_erro(db, escola_completa,
                                                               monkeypatch):
    """Credencial trocada pela de outra escola depois do vínculo aprendido."""
    eid = escola_completa["escola"].id
    credencial(db, eid, "elefante")
    turmas = _turmas(escola_completa)
    del turmas[CID_B]
    nav = NavEl(turmas, escola_da_turma={CID_A: ESC_A})
    instalar_navs(monkeypatch, elefante=nav)
    ex1, _ = rodar(db, eid, "elefante")
    assert ex1.status == "concluida"
    # Agora a conta é a de OUTRA escola (com números novos para as mesmas crianças).
    for al in turmas[CID_A]["alunos"]:
        al["total"] += 5
    nav.ativas = [(ESC_B, NOME_B)]
    nav.escola_da_turma = {CID_A: ESC_B}
    nav.course_reports.clear()
    antes = contagens(db, eid)
    ex2, erro = rodar(db, eid, "elefante")
    assert erro is None
    assert (ex2.status, ex2.motivo) == ("erro", "escola_externa_trocada")
    assert contagens(db, eid) == antes and nav.course_reports == []
    assert _alerta(db, eid, "escola_externa_trocada").severidade == "critico"
    assert escola_externa.obter(db, eid, "elefante")["id"] == str(ESC_A)
    assert vault.obter_linha(db, eid, "elefante").status != "invalida"


def test_elefante_curso_de_outra_escola_no_relatorio(db, escola_completa, monkeypatch):
    """active-schools lista UMA escola, mas o roster traz uma turma com o
    schoolId de outra: sem vínculo, a conta enxerga duas (recusa); com o vínculo
    aprendido, a turma da outra escola fica de fora e o resto é coletado."""
    eid = escola_completa["escola"].id
    credencial(db, eid, "elefante")
    nav = NavEl(_turmas(escola_completa), escola_da_turma={CID_A: ESC_A, CID_B: ESC_B})
    instalar_navs(monkeypatch, elefante=nav)
    ex1, _ = rodar(db, eid, "elefante")
    assert (ex1.status, ex1.motivo) == ("erro", "conta_multiescola")
    assert nav.course_reports == []
    escola_externa.salvar(db, eid, "elefante", str(ESC_A), NOME_A, origem="aprendido")
    db.commit()
    ex2, _ = rodar(db, eid, "elefante")
    assert ex2.status == "concluida", (ex2.status, ex2.motivo, ex2.erro_resumo)
    assert nav.course_reports == [CID_A]


def test_elefante_curso_sem_school_id_em_conta_de_varias_escolas_e_recusado(
        db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "elefante")
    escola_externa.salvar(db, eid, "elefante", str(ESC_A), NOME_A, origem="explicito")
    db.commit()
    turmas = _turmas(escola_completa, com_c=True)
    del turmas[CID_B]
    # CID_C vem SEM schoolId numa conta que enxerga duas escolas.
    nav = NavEl(turmas, ativas=((ESC_A, NOME_A), (ESC_B, NOME_B)),
                escola_da_turma={CID_A: ESC_A})
    instalar_navs(monkeypatch, elefante=nav)
    c = escola_completa["alunos"][2]
    ex, _ = rodar(db, eid, "elefante")
    assert (ex.status, ex.motivo) == ("parcial", "coleta_parcial"), (ex.status, ex.motivo)
    assert nav.course_reports == [CID_A]               # a turma sem escola: recusada
    assert ex.qtd_falhas == 1
    assert db.execute(select(SnapshotElefante).where(
        SnapshotElefante.aluno_id == c.id)).first() is None
    assert "coleta_parcial" in alertas_abertos(db, eid, "elefante")
    # TODAS as turmas sem schoolId → nada a coletar: erro com código próprio.
    nav.escola_da_turma = {}
    nav.course_reports.clear()
    antes = contagens(db, eid)
    ex2, _ = rodar(db, eid, "elefante")
    assert (ex2.status, ex2.motivo) == ("erro", "escola_nao_identificada")
    assert nav.course_reports == [] and contagens(db, eid) == antes


def test_elefante_sem_escola_identificavel_e_erro(db, escola_completa, monkeypatch):
    """Sem active-schools e sem schoolId nas turmas (a suposição sobre a
    plataforma deixou de valer): recusa — sem saber a escola, nada é aplicado."""
    eid = escola_completa["escola"].id
    credencial(db, eid, "elefante")
    turmas = _turmas(escola_completa)
    del turmas[CID_B]
    nav = NavEl(turmas, ativas=())
    instalar_navs(monkeypatch, elefante=nav)
    antes = contagens(db, eid)
    ex, _ = rodar(db, eid, "elefante")
    assert (ex.status, ex.motivo) == ("erro", "escola_nao_identificada")
    assert contagens(db, eid) == antes and nav.course_reports == []
    assert _alerta(db, eid, "escola_nao_identificada").severidade == "critico"


def test_credencial_de_outra_escola_elefante_nao_aplica_na_segunda(db, escola_completa,
                                                                   monkeypatch):
    """A escola 1 aprendeu a escola externa; a escola 2 cadastra (por engano) a
    MESMA conta: recusa na 2, sem tocar na 1."""
    e1 = escola_completa["escola"].id
    credencial(db, e1, "elefante")
    turmas = _turmas(escola_completa)
    del turmas[CID_B]
    nav = NavEl(turmas, escola_da_turma={CID_A: ESC_A})
    instalar_navs(monkeypatch, elefante=nav)
    ex1, _ = rodar(db, e1, "elefante")
    assert ex1.status == "concluida"
    nomes = [a.nome for a in escola_completa["alunos"]]
    escola2, _t2, _a2 = _nova_escola(db, com_alunos=nomes)
    e2 = escola2.id
    credencial(db, e2, "elefante")
    antes1, antes2 = contagens(db, e1), contagens(db, e2)
    nav.course_reports.clear()
    ex2, _ = rodar(db, e2, "elefante")
    assert (ex2.status, ex2.motivo) == ("erro", "escola_externa_em_outra_escola")
    assert contagens(db, e2) == antes2 and contagens(db, e1) == antes1
    assert nav.course_reports == []
    assert escola_externa.obter(db, e2, "elefante") is None
    assert _alerta(db, e2, "escola_externa_em_outra_escola").severidade == "critico"


def test_elefante_nome_da_escola_divergente_so_avisa(db, escola_completa, monkeypatch):
    """Com o vínculo gravado, o nome divergente é só aviso: a coleta segue. (Sem
    vínculo, o nome divergente impede o aprendizado — decisão D9, em
    ``test_sync_escola_externa_decisoes.py``.)"""
    eid = escola_completa["escola"].id
    credencial(db, eid, "elefante")
    turmas = _turmas(escola_completa)
    del turmas[CID_B]
    turmas[CID_A]["escola"] = "EMEF NOME TOTALMENTE DIFERENTE"
    nav = NavEl(turmas, ativas=((ESC_A, "EMEF NOME TOTALMENTE DIFERENTE"),))
    instalar_navs(monkeypatch, elefante=nav)
    escola_externa.salvar(db, eid, "elefante", str(ESC_A), origem="explicito")
    db.commit()
    ex, _ = rodar(db, eid, "elefante")
    assert ex.status == "concluida", (ex.status, ex.motivo, ex.erro_resumo)
    avisos = [m for _e, nivel, m in logs(db, ex.id) if "nome da escola" in m]
    assert avisos and all("Só um aviso" in m for m in avisos)
    assert not any(t.startswith("escola_externa") or t == "conta_multiescola"
                   for t in alertas_abertos(db, eid))


def test_escola_atual_sem_vinculo_aprende_na_primeira_coleta_e_nao_duplica(
        db, escola_completa, monkeypatch):
    """As 5 escolas atuais têm dados e identidades e nenhum vínculo: a 1ª coleta
    depois da implantação aprende o vínculo e segue como antes (sem duplicar)."""
    eid = escola_completa["escola"].id
    credencial(db, eid, "elefante")
    turmas = _turmas(escola_completa)
    del turmas[CID_B]
    nav = NavEl(turmas, escola_da_turma={CID_A: ESC_A})
    instalar_navs(monkeypatch, elefante=nav)
    assert rodar(db, eid, "elefante")[0].status == "concluida"
    # Estado "antes da implantação": dados e identidades gravados, sem vínculo.
    escola_externa.remover(db, eid, "elefante")
    db.commit()
    antes = contagens(db, eid)
    ex2, _ = rodar(db, eid, "elefante")
    assert (ex2.status, ex2.motivo) == ("sem_atualizacao", "nada_mudou")
    assert escola_externa.obter(db, eid, "elefante")["id"] == str(ESC_A)
    assert _sem_retrato_do_dia(contagens(db, eid)) == _sem_retrato_do_dia(antes)
    meio = contagens(db, eid)
    ex3, _ = rodar(db, eid, "elefante")
    assert (ex3.status, ex3.motivo) == ("sem_atualizacao", "nada_mudou")
    depois = contagens(db, eid)
    assert {k: v for k, v in depois.items() if k != "importacoes"} == \
        {k: v for k, v in meio.items() if k != "importacoes"}


# ===========================================================================
# MATIFIC
# ===========================================================================
def test_matific_conta_de_uma_escola_aprende_o_vinculo_e_repetir_nao_duplica(
        db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "matific")
    nav = NavMt(_placar(escola_completa))
    instalar_navs(monkeypatch, matific=nav)
    ex1, _ = rodar(db, eid, "matific")
    assert ex1.status == "concluida", (ex1.status, ex1.motivo, ex1.erro_resumo)
    assert escola_externa.obter(db, eid, "matific")["id"] == SCHOOL_UUID
    n_snaps = _n(db, SnapshotMatific, eid)
    ex2, _ = rodar(db, eid, "matific")
    assert (ex2.status, ex2.motivo) == ("sem_atualizacao", "nada_mudou")
    assert _n(db, SnapshotMatific, eid) == n_snaps


def test_matific_escola_da_conta_muda_entre_coletas_e_erro(db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "matific")
    placar = _placar(escola_completa)
    nav = NavMt(placar)
    instalar_navs(monkeypatch, matific=nav)
    assert rodar(db, eid, "matific")[0].status == "concluida"
    nav.school_id = OUTRA_UUID
    placar.linhas = [(u, n, k, e + 9, a + 3) for u, n, k, e, a in placar.linhas]
    nav.pedidos_ss.clear()
    antes = contagens(db, eid)
    ex, _ = rodar(db, eid, "matific")
    assert (ex.status, ex.motivo) == ("erro", "escola_externa_trocada")
    assert contagens(db, eid) == antes and nav.pedidos_ss == []
    assert _alerta(db, eid, "escola_externa_trocada").severidade == "critico"


def test_credencial_de_outra_escola_matific_nao_aplica_na_segunda(db, escola_completa,
                                                                  monkeypatch):
    e1 = escola_completa["escola"].id
    credencial(db, e1, "matific")
    nav = NavMt(_placar(escola_completa))
    instalar_navs(monkeypatch, matific=nav)
    assert rodar(db, e1, "matific")[0].status == "concluida"
    escola2, _t, _a = _nova_escola(db, com_alunos=[a.nome for a in escola_completa["alunos"]])
    credencial(db, escola2.id, "matific")
    antes1, antes2 = contagens(db, e1), contagens(db, escola2.id)
    ex, _ = rodar(db, escola2.id, "matific")
    assert (ex.status, ex.motivo) == ("erro", "escola_externa_em_outra_escola")
    assert contagens(db, escola2.id) == antes2 and contagens(db, e1) == antes1


def test_matific_varias_escolas_no_trafego_sem_vinculo_e_erro_com_vinculo_usa_a_vinculada(
        db, escola_completa, monkeypatch):
    """accounts/current sem school_id e o tráfego da página com DUAS escolas: antes
    ia "a primeira"; agora, sem vínculo, recusa; com o vínculo, pede a vinculada."""
    eid = escola_completa["escola"].id
    credencial(db, eid, "matific")
    nav = NavMt(_placar(escola_completa), school_id="", trafego=(OUTRA_UUID, SCHOOL_UUID))
    instalar_navs(monkeypatch, matific=nav)
    antes = contagens(db, eid)
    ex1, _ = rodar(db, eid, "matific")
    assert (ex1.status, ex1.motivo) == ("erro", "conta_multiescola")
    assert contagens(db, eid) == antes and nav.pedidos_ss == []
    escola_externa.salvar(db, eid, "matific", SCHOOL_UUID, origem="explicito")
    db.commit()
    ex2, _ = rodar(db, eid, "matific")
    assert ex2.status == "concluida", (ex2.status, ex2.motivo, ex2.erro_resumo)
    assert set(nav.pedidos_ss) == {SCHOOL_UUID}


def test_matific_placar_ao_vivo_recusa_conta_de_outra_escola(db, escola_completa,
                                                             monkeypatch):
    """O placar ao vivo mostraria NOMES de crianças: com o vínculo, a conta de
    outra escola é recusada nos dois caminhos (HTTP direto e navegador)."""
    import httpx
    import pytest

    from app.sync import aovivo
    from app.sync.interfaces import Credenciais, ErroConector
    from tests.test_matific_aovivo import SCHOOL, NavFake, _FakeResp, _fake_httpx_client, _payloads

    aovivo._cache.clear()
    eid = escola_completa["escola"].id
    ss, sl = _payloads({"u-ana": "Ana Beatriz Souza"})
    # 1) HTTP direto: o accounts/current diz outra escola.
    monkeypatch.setattr(httpx, "Client", _fake_httpx_client({
        "student-leaderboard": _FakeResp(sl["body"]), "school_student": _FakeResp(ss["body"]),
        "accounts/current": _FakeResp({"school_id": SCHOOL}),
        "competition-v2": _FakeResp([{"id": "c1", "is_live": True}])}))
    con = con_matific.ConectorMatific(_fabrica(NavFake(ss, sl)))
    estado = {"cookies": [{"name": "sessionid", "value": "abc", "domain": ".matific.com"}]}
    with pytest.raises(ErroConector) as exc:
        con.coletar_via_http(estado, "duration=week", escola_esperada=OUTRA_UUID)
    assert exc.value.codigo == "escola_externa_trocada"
    assert con.coletar_via_http(estado, "duration=week", escola_esperada=SCHOOL)  # controle
    # Sem vínculo, mas a escola da conta já alimenta OUTRA escola do Constela.
    with pytest.raises(ErroConector) as exc_outra:
        con.coletar_via_http(estado, "duration=week", escolas_recusadas=frozenset({SCHOOL}))
    assert exc_outra.value.codigo == "escola_externa_em_outra_escola"
    # 2) Ponta a ponta pelo serviço (o fetch no navegador é o caminho final).
    monkeypatch.setattr(connectors, "obter", lambda p: con if p == "matific" else None)
    vault.salvar_credencial(db, eid, "matific", Credenciais(usuario="u", senha="p"))
    escola_externa.salvar(db, eid, "matific", OUTRA_UUID, origem="explicito")
    db.commit()
    monkeypatch.setattr(httpx, "Client", _fake_httpx_client({}))   # HTTP recusado
    with pytest.raises(ErroConector) as exc2:
        aovivo.placar_matific(db, eid, periodo="semana", inicio=None, fim=None, forcar=True)
    assert exc2.value.codigo == "escola_externa_trocada"
    aovivo._cache.clear()


# ===========================================================================
# ROTAS: vínculo explícito e "Testar conexão"
# ===========================================================================
def test_rota_do_vinculo_valida_recusa_duplicata_audita_e_remove(db, escola_completa, cliente,
                                                                cliente_global):
    """O PUT é do Admin Global (revisão e97); GET e DELETE seguem com a escola."""
    eid = escola_completa["escola"].id
    base = f"{API}/escolas/{eid}/sync/escola-externa"
    glob = cliente_global
    assert cliente.get(f"{base}/elefante").json() == {
        "plataforma": "elefante", "vinculada": False, "id_externo": None, "nome": None,
        "origem": None, "definido_em": None}
    assert glob.put(f"{base}/elefante", json={"id_externo": "abc"}).status_code == 422
    assert glob.put(f"{base}/matific", json={"id_externo": "23952"}).status_code == 422
    assert glob.put(f"{base}/manual", json={"id_externo": "1"}).status_code == 404
    r = glob.put(f"{base}/elefante", json={"id_externo": " 23952 ", "nome": NOME_A})
    assert r.status_code == 200 and r.json()["id_externo"] == "23952"
    assert cliente.get(f"{base}/elefante").json()["vinculada"] is True
    # A mesma escola externa já é de outra escola do Constela → 409.
    escola2, _t, _a = _nova_escola(db)
    escola_externa.salvar(db, escola2.id, "elefante", "24000", "OUTRA")
    db.commit()
    assert glob.put(f"{base}/elefante", json={"id_externo": "24000"}).status_code == 409
    assert escola_externa.obter(db, eid, "elefante")["id"] == "23952"
    r = glob.put(f"{base}/matific", json={"id_externo": SCHOOL_UUID.upper()})
    assert r.status_code == 200 and r.json()["id_externo"] == SCHOOL_UUID
    assert db.scalar(select(func.count()).select_from(LogAuditoria).where(
        LogAuditoria.acao == "sync.escola_externa_definida")) == 2
    assert cliente.delete(f"{base}/elefante").status_code == 204
    assert cliente.get(f"{base}/elefante").json()["vinculada"] is False
    # O status da integração mostra o vínculo (sem segredo).
    st = cliente.get(f"{API}/escolas/{eid}/sync/status").json()
    por_plat = {p["plataforma"]: p for p in st["plataformas"]}
    assert por_plat["matific"]["escola_externa"]["id"] == SCHOOL_UUID
    assert por_plat["elefante"]["escola_externa"] is None


def test_rota_do_vinculo_exige_gestao(db, escola_completa):
    from fastapi.testclient import TestClient

    from app.main import app

    eid = escola_completa["escola"].id
    db.add(Usuario(escola_id=eid, nome="Prof", email="prof@teste.local",
                   senha_hash=hash_senha("s3nh4"), cargo="professor"))
    db.commit()
    c = TestClient(app)
    tok = c.post(f"{API}/auth/login", data={"username": "prof@teste.local",
                                            "password": "s3nh4"}).json()["access_token"]
    c.headers["Authorization"] = f"Bearer {tok}"
    r = c.put(f"{API}/escolas/{eid}/sync/escola-externa/elefante", json={"id_externo": "1"})
    assert r.status_code == 403
    assert escola_externa.obter(db, eid, "elefante") is None


def test_testar_conexao_mostra_a_escola_externa_sem_segredo(db, escola_completa, cliente,
                                                            monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "elefante")
    nav = NavEl(_turmas(escola_completa), ativas=((ESC_A, NOME_A), (ESC_B, NOME_B)),
                escola_da_turma={CID_A: ESC_A, CID_B: ESC_B})
    instalar_navs(monkeypatch, elefante=nav)
    url = f"{API}/escolas/{eid}/sync/credenciais/elefante/testar"
    r = cliente.post(url)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True
    assert {e["id"] for e in j["escolas_externas"]} == {str(ESC_A), str(ESC_B)}
    assert j["escola_vinculada"] is None and j["escola_confere"] is None
    assert "escolas" in j["aviso_escola"] and "escolha" in j["aviso_escola"]
    assert "valor-ficticio-local" not in r.text and "robo-ficticio" not in r.text
    assert nav.course_reports == []                    # testar não coleta dado de turma
    # Com o vínculo: confere; vínculo fora do alcance da conta: não confere.
    escola_externa.salvar(db, eid, "elefante", str(ESC_A), NOME_A, origem="explicito")
    db.commit()
    j = cliente.post(url).json()
    assert j["escola_confere"] is True and j["escola_vinculada"]["id"] == str(ESC_A)
    nav.ativas = [(ESC_B, NOME_B)]
    nav.escola_da_turma = {CID_A: ESC_B, CID_B: ESC_B}
    j = cliente.post(url).json()
    assert j["ok"] is True and j["escola_confere"] is False
    assert "recusada" in j["aviso_escola"]
    assert escola_externa.obter(db, eid, "elefante")["id"] == str(ESC_A)   # testar não grava


def test_testar_conexao_avisa_credencial_de_escola_ja_vinculada_a_outra(
        db, escola_completa, cliente, monkeypatch):
    eid = escola_completa["escola"].id
    escola2, _t, _a = _nova_escola(db)
    escola_externa.salvar(db, escola2.id, "elefante", str(ESC_A), NOME_A)
    db.commit()
    credencial(db, eid, "elefante")
    instalar_navs(monkeypatch, elefante=NavEl(_turmas(escola_completa),
                                              escola_da_turma={CID_A: ESC_A, CID_B: ESC_A}))
    j = cliente.post(f"{API}/escolas/{eid}/sync/credenciais/elefante/testar").json()
    assert j["ok"] is True and j["escola_confere"] is False
    assert "outra escola do Constela" in j["aviso_escola"]


def test_testar_conexao_matific_mostra_a_escola_da_conta(db, escola_completa, cliente,
                                                         monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "matific")
    instalar_navs(monkeypatch, matific=NavMt(_placar(escola_completa)))
    r = cliente.post(f"{API}/escolas/{eid}/sync/credenciais/matific/testar")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["escolas_externas"] == [{"id": SCHOOL_UUID, "nome": ""}]
    assert j["aviso_escola"] is None


def test_previa_da_importacao_manual_avisa_nome_de_escola_divergente(db, escola_completa,
                                                                    cliente, monkeypatch):
    """Importação manual: a escola lida do relatório (``escola_detectada``) que não
    parece a cadastrada vira só AVISO na prévia — nunca bloqueia."""
    from app.routers import importacoes as rota
    from app.services import importacao as svc

    eid = escola_completa["escola"].id
    a = escola_completa["alunos"][0]

    def analise(escola):
        return lambda *_a, **_k: svc.Analise(
            plataforma="elefante", formato="resumo", escola_detectada=escola,
            linhas=[svc.LinhaImportacao(numero=1, nome=a.nome,
                                        dados={"livros_unicos": 3, "turma_relatorio": "3 ANO A"})])

    monkeypatch.setattr(rota.svc, "analisar_texto", analise("EMEF NOME TOTALMENTE DIFERENTE"))
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/analisar",
                     data={"texto": "qualquer", "plataforma": "elefante"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["escola_detectada"] == "EMEF NOME TOTALMENTE DIFERENTE"
    assert "Nomes variam" in j["aviso_escola"] and j["total_erros"] == 0
    monkeypatch.setattr(rota.svc, "analisar_texto", analise("EMEF Escola Teste"))
    j = cliente.post(f"{API}/escolas/{eid}/importacoes/analisar",
                     data={"texto": "qualquer", "plataforma": "elefante"}).json()
    assert j["aviso_escola"] == ""


# ===========================================================================
# Unidades: comparação de nome (só aviso) e id externo
# ===========================================================================
def test_nomes_compativeis_e_ids():
    assert escola_externa.nomes_compativeis("EMEF PROF. TEODORO FICTÍCIO",
                                            "Escola Municipal Professor Teodoro Fictício")
    assert escola_externa.nomes_compativeis("EMEI/EMEF ARISTEU FICTÍCIO DO OSÓRIO",
                                            "EMEI EMEF ARISTEU FICTICIO DO OSORIO")
    assert escola_externa.nomes_compativeis("", "QUALQUER")
    assert not escola_externa.nomes_compativeis("EMEF MARIA DAS DORES",
                                                "EMEF JOSE DE ANCHIETA")
    # Critério da D9 (porteiro do aprendizado): só "Maria" em comum não basta.
    assert not escola_externa.nomes_compativeis("EMEF MARIA DAS DORES", "EMEF Maria José")
    assert escola_externa.normalizar_id("elefante", 23952) == "23952"
    assert escola_externa.normalizar_id("elefante", "23a") == ""
    assert escola_externa.normalizar_id("matific", SCHOOL_UUID.upper()) == SCHOOL_UUID
    assert escola_externa.normalizar_id("matific", "x") == ""
    assert escola_externa.normalizar_id("elefante", True) == ""


def test_codigos_novos_cabem_nas_colunas():
    """O tipo do alerta é String(30) e o motivo da execução String(40): o código
    longo demais derrubava o registro da falha no PostgreSQL (a execução ficava
    'executando'); o SQLite não confere o tamanho."""
    from app.sync import service

    for codigo in escola_externa.CODIGOS:
        tipo, _sev = service.alerta_do_codigo(codigo)
        assert tipo == codigo and len(tipo) <= 30 and len(codigo) <= 40
