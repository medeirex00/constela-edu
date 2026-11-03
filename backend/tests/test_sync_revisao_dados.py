"""Revisão adversarial e93 (lente: dados) do fix/sync-integridade.

Reproduções do revisor (``scratchpad/e93/rev-dados``) com o comportamento
DECIDIDO na correção. Dados 100% fictícios, sem rede. A variante PostgreSQL
está em ``test_sync_revisao_pg.py``.
"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.models import Matricula, Nota, Turma
from app.models.nota import LogAuditoria
from app.models.plataformas import Importacao, SnapshotElefante, SnapshotMatific
from app.models.sincronizacao import SincronizacaoExecucao
from app.routers import importacoes as imp
from app.services import matriculas, scoring
from app.sync import service
from tests._sync_nucleo_fakes import (NavElefante, PlacarFake, aluno_el, alertas_abertos,
                                      credencial, instalar, livro, novo_aluno, rodar, vincular)
from tests.sync_integridade_comum import (aplicar, com_nome, dono, elefante_resumo, fichas,
                                          matific, pendentes, sem_disco, snap_matific, turma,
                                          turmas_de)

K_A = "3 ANO A (300396804)"
K_B = "4 ANO B (300396805)"
K_6 = "6 ANO B (300396806)"


def _snaps(db, aluno_id):
    return list(db.execute(select(SnapshotMatific).where(SnapshotMatific.aluno_id == aluno_id)
                           .order_by(SnapshotMatific.id)).scalars())


def _notas(db, ids):
    db.expire_all()
    return {i: (n.posicao, round(n.nota_geral, 3)) for i in ids
            for n in [db.execute(select(Nota).where(Nota.aluno_id == i)).scalars().first()]
            if n is not None}


def _turma_b(db, eid):
    t_b = Turma(escola_id=eid, nome="4º Ano B", ano_escolar="4º Ano", ano_letivo=2026)
    db.add(t_b)
    db.commit()
    return t_b


# ---------------------------------------------------------------------------
# Achado 5 — período do Matific em andamento repetido sem mudança.
# ---------------------------------------------------------------------------
def test_periodo_em_andamento_repetido_nao_empilha_retrato(db, escola_completa, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    a, b, c = ec["alunos"]
    credencial(db, eid, "matific")
    placar = PlacarFake()
    placar.linhas = [("u-a", a.nome, K_A, 40, 10), ("u-b", b.nome, K_A, 30, 8),
                     ("u-c", c.nome, K_A, 20, 5)]
    instalar(monkeypatch, placar=placar)
    hoje = date.today()
    par = {"matific_start_date": (hoje - timedelta(days=5)).isoformat(),
           "matific_end_date": (hoje + timedelta(days=5)).isoformat()}
    rodar(db, eid, "matific", parametros=dict(par))
    n1 = len(_snaps(db, a.id))
    ex2, _ = rodar(db, eid, "matific", parametros=dict(par))
    ex3, _ = rodar(db, eid, "matific", parametros=dict(par))
    assert (ex2.status, ex3.status) == ("sem_atualizacao", "sem_atualizacao")
    assert len(_snaps(db, a.id)) == n1


# ---------------------------------------------------------------------------
# Achado 4 — mesmo id em duas turmas da mesma coleta.
# ---------------------------------------------------------------------------
def test_mesmo_uuid_em_duas_turmas_com_numeros_diferentes_nao_aplica_nem_move(
        db, escola_completa, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    a, b, c = ec["alunos"]
    t_b = _turma_b(db, eid)
    d = novo_aluno(db, eid, t_b, "Crianca Ficticia Quarto Ano")
    vincular(db, eid, a.id, "matific", "u-a")
    vincular(db, eid, d.id, "matific", "u-d")
    db.commit()
    credencial(db, eid, "matific")
    placar = PlacarFake()
    placar.linhas = [("u-a", a.nome, K_A, 40, 10), ("u-b", b.nome, K_A, 30, 8),
                     ("u-d", d.nome, K_B, 20, 5), ("u-a", a.nome, K_B, 99, 50)]
    instalar(monkeypatch, placar=placar)
    ex1, _ = rodar(db, eid, "matific")
    tur = db.execute(select(Matricula.turma_id).where(Matricula.aluno_id == a.id)).scalar()
    assert tur == ec["turma"].id, "matrícula movida pela 2ª linha do mesmo uuid"
    assert _snaps(db, a.id) == []
    assert (ex1.status, ex1.motivo) == ("parcial", "linhas_descartadas")
    assert "coleta_parcial" in alertas_abertos(db, eid, "matific")


def test_mesmo_uuid_em_duas_turmas_com_mesmos_numeros_nao_vai_e_volta(db, escola_completa,
                                                                     monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    a, b, c = ec["alunos"]
    t_b = _turma_b(db, eid)
    d = novo_aluno(db, eid, t_b, "Crianca Ficticia Quarto Ano")
    vincular(db, eid, a.id, "matific", "u-a")
    vincular(db, eid, d.id, "matific", "u-d")
    db.commit()
    credencial(db, eid, "matific")
    placar = PlacarFake()
    placar.linhas = [("u-b", b.nome, K_A, 30, 8), ("u-d", d.nome, K_B, 20, 5),
                     ("u-a", a.nome, K_B, 40, 10), ("u-a", a.nome, K_A, 40, 10)]
    instalar(monkeypatch, placar=placar)
    for _ in range(3):
        rodar(db, eid, "matific")
    movs = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "matricula.turma_sincronizada",
        LogAuditoria.entidade_id == a.id)).scalars().all()
    assert movs == []
    assert [(s.estrelas, s.atividades) for s in _snaps(db, a.id)][-1] == (40, 10)


def test_mesmo_student_id_em_dois_cursos_com_numeros_diferentes_nao_aplica(
        db, escola_completa, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    a, b, c = ec["alunos"]
    t_b = _turma_b(db, eid)
    d = novo_aluno(db, eid, t_b, "Crianca Ficticia Quarto Ano")
    vincular(db, eid, a.id, "elefante", "9100001")
    db.commit()
    credencial(db, eid, "elefante")
    turmas = {
        511434: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
            aluno_el(9100001, a.nome, [livro("Livro Ficticio Um")], total=1, tempo=600),
            aluno_el(9100002, b.nome, [livro("Livro Ficticio Dois")])]},
        600001: {"nome": "4 ANO B TARDE ANUAL", "alunos": [
            aluno_el(9200001, d.nome, [livro("Livro Ficticio Quatro")]),
            aluno_el(9100001, a.nome, [livro("Livro Ficticio Um")], total=9, tempo=6000)]},
    }
    instalar(monkeypatch, nav_elefante=NavElefante(turmas))
    ex, _ = rodar(db, eid, "elefante")
    s = db.execute(select(SnapshotElefante).where(SnapshotElefante.aluno_id == a.id)).all()
    assert s == []
    assert ex.status == "parcial" and "coleta_parcial" in alertas_abertos(db, eid, "elefante")


def test_mesmo_student_id_em_dois_cursos_com_mesmos_numeros_aplica_uma_vez(
        db, escola_completa, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    a, b, c = ec["alunos"]
    t_b = _turma_b(db, eid)
    d = novo_aluno(db, eid, t_b, "Crianca Ficticia Quarto Ano")
    vincular(db, eid, a.id, "elefante", "9100001")
    db.commit()
    credencial(db, eid, "elefante")
    livros_a = [livro("Livro Ficticio Um")]
    turmas = {
        511434: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
            aluno_el(9100001, a.nome, livros_a, total=1, tempo=600),
            aluno_el(9100002, b.nome, [livro("Livro Ficticio Dois")])]},
        600001: {"nome": "4 ANO B TARDE ANUAL", "alunos": [
            aluno_el(9200001, d.nome, [livro("Livro Ficticio Quatro")]),
            aluno_el(9100001, a.nome, livros_a, total=1, tempo=600)]},
    }
    instalar(monkeypatch, nav_elefante=NavElefante(turmas))
    ex, _ = rodar(db, eid, "elefante")

    def retratos(aluno_id):
        return [x.livros_unicos for x in db.execute(select(SnapshotElefante).where(
            SnapshotElefante.aluno_id == aluno_id)).scalars()]
    # O mesmo que uma criança de UMA turma só (b): o dado entra uma vez.
    assert retratos(a.id) and set(retratos(a.id)) == {1}
    assert len(retratos(a.id)) == len(retratos(b.id))
    assert ex.status == "concluida" and ex.qtd_alunos == 3


# ---------------------------------------------------------------------------
# Achado 2 — uuid repetido no mesmo arquivo com uma linha abaixo do gravado.
# ---------------------------------------------------------------------------
def test_uuid_duplicado_na_mesma_turma_com_queda_vai_para_revisao(db, escola_completa,
                                                                   monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    a, b, c = ec["alunos"]
    credencial(db, eid, "matific")
    placar = PlacarFake()
    placar.linhas = [("u-a", a.nome, K_A, 40, 10), ("u-b", b.nome, K_A, 30, 8)]
    instalar(monkeypatch, placar=placar)
    rodar(db, eid, "matific")
    placar.linhas = [("u-a", a.nome, K_A, 30, 8), ("u-a", a.nome, K_A, 99, 50),
                     ("u-b", b.nome, K_A, 30, 8)]
    rodar(db, eid, "matific")
    s = _snaps(db, a.id)[-1]
    assert (s.estrelas, s.atividades) == (40, 10)
    assert any(p.motivo == "id_externo_duplicado" for p in pendentes(db, eid))


# ---------------------------------------------------------------------------
# Achado 1 (ALTA, regressão) — troca de turma sem número novo recalcula.
# ---------------------------------------------------------------------------
def test_troca_de_turma_sem_numero_novo_recalcula(db, escola_completa, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    a, b, c = ec["alunos"]
    t6 = Turma(escola_id=eid, nome="6º Ano B", ano_escolar="6º Ano", ano_letivo=2026)
    db.add(t6)
    db.commit()
    credencial(db, eid, "matific")
    placar = PlacarFake()
    placar.linhas = [("u-a", a.nome, K_A, 90, 20), ("u-b", b.nome, K_A, 30, 8),
                     ("u-c", c.nome, K_A, 20, 5)]
    instalar(monkeypatch, placar=placar)
    rodar(db, eid, "matific")
    placar.linhas[0] = ("u-a", a.nome, K_6, 90, 20)
    ex2, _ = rodar(db, eid, "matific")
    db.expire_all()
    tur = db.execute(select(Matricula.turma_id).where(Matricula.aluno_id == a.id)).scalar()
    depois_sync = _notas(db, [a.id, b.id, c.id])
    scoring.recalcular_escola(db, eid)
    db.commit()
    assert tur == t6.id
    assert (ex2.status, ex2.qtd_alunos) == ("concluida", 1)
    assert depois_sync == _notas(db, [a.id, b.id, c.id])


# ---------------------------------------------------------------------------
# Achado 3 (regressão de visibilidade) — o processo morre no recálculo.
# ---------------------------------------------------------------------------
def test_processo_que_morre_no_recalculo_deixa_a_marca(db, escola_completa, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    a, b, c = ec["alunos"]
    credencial(db, eid, "matific")
    placar = PlacarFake()
    placar.linhas = [("u-a", a.nome, K_A, 90, 20), ("u-b", b.nome, K_A, 30, 8),
                     ("u-c", c.nome, K_A, 20, 5)]
    instalar(monkeypatch, placar=placar)
    rodar(db, eid, "matific")
    placar.linhas[2] = ("u-c", c.nome, K_A, 500, 100)       # C passa a liderar
    orig = scoring.recalcular_escola

    def morre(*_a, **_k):
        raise SystemExit("processo encerrado no meio do recálculo (simulado)")
    monkeypatch.setattr(scoring, "recalcular_escola", morre)
    ex = service.enfileirar(db, eid, "matific", origem="manual")
    db.commit()
    exid = ex.id
    try:
        service.executar(db, ex)
    except BaseException:  # noqa: BLE001 — a "morte" do processo
        pass
    db.rollback()
    db.expire_all()
    monkeypatch.setattr(scoring, "recalcular_escola", orig)
    ex2 = db.get(SincronizacaoExecucao, exid)
    assert ex2.status == "concluida" and ex2.recalculo_pendente is True
    assert service.recalculo_pendente_aberto(db, eid)
    # A coleta seguinte, sem mudança, recalcula pela marca e a zera.
    ex3, _ = rodar(db, eid, "matific")
    assert ex3.status == "sem_atualizacao"
    assert not service.recalculo_pendente_aberto(db, eid)
    assert _notas(db, [c.id])[c.id][0] == 1


def test_recalculo_que_da_certo_zera_a_marca_da_propria_execucao(db, escola_completa,
                                                                 monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    a, b, c = ec["alunos"]
    credencial(db, eid, "matific")
    placar = PlacarFake()
    placar.linhas = [("u-a", a.nome, K_A, 90, 20)]
    instalar(monkeypatch, placar=placar)
    ex, _ = rodar(db, eid, "matific")
    assert ex.status == "concluida" and ex.recalculo_pendente is False


# ---------------------------------------------------------------------------
# Achados 8, 6 e 9 — ficha criada indevidamente.
# ---------------------------------------------------------------------------
def test_nome_de_um_token_nao_cria_ficha(db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    escola = escola_completa["escola"]
    aplicar(db, escola, matific("3 ANO A TARDE ANUAL (300396804)", [
        {"nome": "Anna", "nome_abrev": "ANNA E", "uuid": "u-novo", "estrelas": 4,
         "atividades": 2}]))
    aplicar(db, escola, elefante_resumo("3 ANO A TARDE ANUAL", [
        {"studentId": 9100999, "studentName": "Kauê", "totalBooksRead": 2}]))
    criadas = com_nome(db, escola.id, "Anna") + com_nome(db, escola.id, "Kauê")
    assert criadas == []
    motivos = sorted(p.motivo for p in pendentes(db, escola.id))
    assert motivos == ["nome_incompleto", "nome_incompleto"]


def test_nome_de_um_token_de_conta_ja_vinculada_continua_aplicando(db, escola_completa,
                                                                   monkeypatch):
    sem_disco(monkeypatch)
    escola = escola_completa["escola"]
    a = escola_completa["alunos"][0]
    vincular(db, escola.id, a.id, "elefante", "9100777")
    db.commit()
    aplicar(db, escola, elefante_resumo("3 ANO A TARDE ANUAL", [
        {"studentId": 9100777, "studentName": a.nome.split()[0], "totalBooksRead": 6}]))
    s = db.execute(select(SnapshotElefante).where(SnapshotElefante.aluno_id == a.id)
                   ).scalars().all()
    assert [x.livros_unicos for x in s] == [6]


def test_ano_nao_nasce_em_turma_de_fase_com_nome_normalizado(db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    escola = escola_completa["escola"]
    fase = turma(db, escola.id, matriculas.nome_turma_exibicao("Fase 1A"), "1ª Fase")
    db.commit()
    aplicar(db, escola, elefante_resumo("1 ANO A TARDE ANUAL", [
        {"studentId": 9100888, "studentName": "Crianca Nova Ficticia Silva",
         "totalBooksRead": 3}]))
    novas = com_nome(db, escola.id, "Crianca Nova Ficticia Silva")
    assert not any(fase.id in turmas_de(db, x.id) for x in novas)
    assert any(p.motivo == "turma_de_outra_etapa" for p in pendentes(db, escola.id))


def test_linha_sem_campo_essencial_nao_cria_ficha(db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    escola = escola_completa["escola"]
    a = escola_completa["alunos"][0]
    antes = fichas(db, escola.id)
    res = aplicar(db, escola, matific("3 ANO A TARDE ANUAL (300396804)", [
        {"nome": a.nome, "nome_abrev": "ANA S", "uuid": "u-a", "estrelas": 40, "atividades": 10},
        {"nome": "Crianca Nova Ficticia Souza", "nome_abrev": "CRIANCA S", "uuid": "u-nova",
         "estrelas": None, "atividades": 3}]))
    assert com_nome(db, escola.id, "Crianca Nova Ficticia Souza") == []
    assert fichas(db, escola.id) == antes
    assert dono(db, escola.id, "matific", "u-nova") is None
    assert pendentes(db, escola.id) == []
    assert res["descartadas"].get("campos_ausentes") == 1
    assert snap_matific(db, a.id).estrelas == 40


# ---------------------------------------------------------------------------
# Achado 7 — retrato reescrito no mesmo dia UTC leva a data nova.
# ---------------------------------------------------------------------------
class _Relogio(datetime):
    fixo = None

    @classmethod
    def now(cls, tz=None):
        return cls.fixo if tz is None else cls.fixo.astimezone(tz)


def test_reescrita_no_mesmo_dia_utc_leva_a_data_do_valor_novo(db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    escola = escola_completa["escola"]
    a, b, c = escola_completa["alunos"]
    k = "3 ANO A TARDE ANUAL (300396804)"

    def linhas(e):
        return [
            {"nome": a.nome, "nome_abrev": "ANA S", "uuid": "u-a", "estrelas": e,
             "atividades": 10},
            {"nome": b.nome, "nome_abrev": "JOAO B", "uuid": "u-b", "estrelas": 30,
             "atividades": 8},
            {"nome": c.nome, "nome_abrev": "SOFIA D", "uuid": "u-c", "estrelas": 20,
             "atividades": 5}]
    monkeypatch.setattr(imp, "datetime", _Relogio)
    _Relogio.fixo = datetime(2026, 10, 23, 0, 30, tzinfo=timezone.utc)   # 21h30 de 22/10 BRT
    aplicar(db, escola, matific(k, linhas(40)))
    _Relogio.fixo = datetime(2026, 10, 23, 16, 0, tzinfo=timezone.utc)   # 13h de 23/10 BRT
    aplicar(db, escola, matific(k, linhas(95)))
    s = snap_matific(db, a.id)
    # Importados aqui: o selo de frescor não existe no 34f1a23 (matriz de prova).
    from app.services import frescor_ranking
    from app.services import relatorios as svc_rel
    f = frescor_ranking.frescor_da_escola(db, escola, date(2026, 10, 23))
    legenda = svc_rel.legenda_data_dos_dados(f, ["matematica"])
    assert s.estrelas == 95
    assert s.data_referencia.replace(tzinfo=None) == datetime(2026, 10, 23, 16, 0)
    assert "23/10/2026" in legenda


# ---------------------------------------------------------------------------
# Achado 10 — a legenda impressa não esconde o estado "parcial".
# ---------------------------------------------------------------------------
def test_legenda_impressa_mostra_dado_antigo_de_parte_dos_alunos(db, escola_completa):
    escola = escola_completa["escola"]
    a, b, c = escola_completa["alunos"]
    imp_ = Importacao(escola_id=escola.id, usuario_id=escola_completa["admin"].id,
                      plataforma="elefante", tipo="pdf", status="concluida")
    db.add(imp_)
    db.flush()
    agora = datetime(2026, 10, 22, 15, 0)
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=a.id, data_referencia=agora,
                            importacao_id=imp_.id, livros_unicos=5, tempo_leitura_min=50))
    for x in (b, c):
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=x.id,
                                data_referencia=agora - timedelta(days=20),
                                importacao_id=imp_.id, livros_unicos=3, tempo_leitura_min=30))
    db.commit()
    from app.services import frescor_ranking
    from app.services import relatorios as svc_rel
    f = frescor_ranking.frescor_da_escola(db, escola, date(2026, 10, 22))
    assert f["dimensoes"]["leitura"]["estado"] == "parcial"
    legenda = svc_rel.legenda_data_dos_dados(f, ["leitura"])
    assert legenda == "Dados das plataformas: Leitura de 22/10/2026 (parte com dado de 02/10/2026)"
    assert legenda.encode("latin-1")
