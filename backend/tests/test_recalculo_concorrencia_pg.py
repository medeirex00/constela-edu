"""Corrida REAL do recálculo — só o PostgreSQL prova (P0).

O SQLite da suíte tem um escritor só: ele *esconde* a corrida em vez de provar
que ela não existe. Aqui rodam transações de verdade, em paralelo, contra o
banco de produção (Postgres), medindo as quatro consequências do
SELECT-then-INSERT sem trava em ``scoring.recalcular_escola``:

  1. ``uq_nota_aluno_ano`` violada (23505) → HTTP 500;
  2. DEADLOCK (40P01) quando as ordens de ranking divergem (a ordem dos
     INSERTs É a ordem do ranking);
  3. mais de uma nota por aluno/ano — que a constraint impede virando (1);
  4. CORRUPÇÃO SILENCIOSA: vence quem grava por último, e sem trava esse pode
     ser justamente quem LEU o estado mais velho. Não levanta erro nenhum: é o
     dano real, e só este arquivo o pega.

Como rodar::

    set TEST_DATABASE_URL_PG=postgresql+psycopg://postgres@127.0.0.1:5432/constela_teste
    pytest tests/test_recalculo_concorrencia_pg.py -m postgres

Sem ``TEST_DATABASE_URL_PG`` o módulo inteiro é pulado (a suíte normal não
precisa de Postgres).
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime

import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import Session

from app.core.database import Base, _NS_IMPORTACAO, _NS_RECALCULO
from app.models import (Aluno, Configuracao, Escola, Importacao, Matricula,
                        NivelDificuldade, Nota, ReferenciaNormalizacao,
                        SnapshotElefante, SnapshotMatific, Turma, Usuario)
from app.services import scoring

pytestmark = pytest.mark.postgres

URL_PG = os.environ.get("TEST_DATABASE_URL_PG", "")
if not URL_PG:
    pytest.skip("defina TEST_DATABASE_URL_PG para rodar a corrida real",
                allow_module_level=True)

ALUNOS = 60


@pytest.fixture(scope="module")
def motor_pg():
    motor = create_engine(URL_PG, pool_size=16, max_overflow=16,
                          pool_pre_ping=True)
    import app.quest.models  # noqa: F401 — registra o schema completo

    Base.metadata.create_all(motor)
    yield motor
    motor.dispose()


def _semear(motor, sufixo: str) -> dict:
    """Escola nova (isolada) com ALUNOS matriculados e snapshots determinísticos."""
    with Session(motor) as db:
        escola = Escola(nome=f"ESCOLA PG {sufixo}", ano_letivo_ativo=2026)
        db.add(escola)
        db.flush()
        admin = Usuario(escola_id=escola.id, nome="Admin PG",
                        email=f"pg-{escola.id}-{sufixo}@teste.local",
                        senha_hash="x", cargo="admin")
        db.add(admin)
        for ns, valores in scoring.PESOS_PADRAO.items():
            db.add(Configuracao(escola_id=escola.id, namespace=ns,
                                chave="valores", valor=valores))
        db.add(NivelDificuldade(escola_id=escola.id, nome="Pre-Leitor",
                                codigo="pre_leitor", codigos=["AA"],
                                pontos_padrao=1.0, ordem=0))
        db.add(NivelDificuldade(escola_id=escola.id, nome="Nivel 2",
                                codigo="nivel_2", codigos=["D"],
                                pontos_padrao=4.0, ordem=1))
        db.add(ReferenciaNormalizacao(escola_id=escola.id, modo="auto"))
        db.flush()
        imp = Importacao(escola_id=escola.id, usuario_id=admin.id,
                         plataforma="matific", tipo="seed")
        db.add(imp)
        turma = Turma(escola_id=escola.id, nome="3o Ano A", ano_escolar="3o Ano",
                      ano_letivo=2026, turno="manha")
        db.add(turma)
        db.flush()
        alunos = []
        for i in range(ALUNOS):
            a = Aluno(escola_id=escola.id, nome=f"Aluno PG {i:03d}")
            db.add(a)
            db.flush()
            alunos.append(a.id)
            db.add(Matricula(escola_id=escola.id, aluno_id=a.id,
                             turma_id=turma.id, ano_letivo=2026))
            db.add(SnapshotMatific(
                escola_id=escola.id, aluno_id=a.id, importacao_id=imp.id,
                data_referencia=datetime(2026, 3, 1),
                atividades=10 + i, estrelas=20 + 3 * i,
                pontuacao_media=1.0 + (i % 5)))
            db.add(SnapshotElefante(
                escola_id=escola.id, aluno_id=a.id, importacao_id=imp.id,
                data_referencia=datetime(2026, 3, 1),
                livros_unicos=i % 30, tempo_leitura_min=5 * i,
                questoes_tentativas=2 * i, questoes_acertos=i,
                livros_por_nivel={"AA": i % 7, "D": i % 4}))
        db.commit()
        return {"escola_id": escola.id, "importacao_id": imp.id,
                "usuario_id": admin.id, "alunos": alunos}


@pytest.fixture()
def escola_pg(motor_pg, request):
    return _semear(motor_pg, request.node.name[-28:])


def _importar_concorrente(motor, dados, *, deslocamento: int, dia: int) -> None:
    """COMMIT de uma importação vizinha: snapshots novos (mais recentes) que
    mudam as notas — e, com ``deslocamento`` diferente, também a ORDEM do
    ranking (é a ordem dos INSERTs em ``notas``)."""
    with Session(motor) as db:
        for k, aid in enumerate(dados["alunos"]):
            db.add(SnapshotMatific(
                escola_id=dados["escola_id"], aluno_id=aid,
                importacao_id=dados["importacao_id"],
                data_referencia=datetime(2026, 4, dia),
                atividades=1 + (k * 7 + deslocamento) % 400,
                estrelas=1 + (k * 13 + deslocamento) % 900,
                pontuacao_media=1.0 + ((k + deslocamento) % 5)))
            db.add(SnapshotElefante(
                escola_id=dados["escola_id"], aluno_id=aid,
                importacao_id=dados["importacao_id"],
                data_referencia=datetime(2026, 4, dia),
                livros_unicos=(k * 3 + deslocamento) % 60,
                tempo_leitura_min=(k * 17 + deslocamento) % 1200,
                questoes_tentativas=(k * 5 + deslocamento) % 300,
                questoes_acertos=(k * 2 + deslocamento) % 200,
                livros_por_nivel={"AA": (k + deslocamento) % 20,
                                  "D": (k * 2 + deslocamento) % 20}))
        db.commit()


def _notas(motor, escola_id: int) -> dict:
    with Session(motor) as db:
        return {n.aluno_id: (n.nota_matific, n.nota_elefante, n.nota_geral,
                             n.posicao)
                for n in db.execute(
                    select(Nota).where(Nota.escola_id == escola_id)).scalars()}


def _autoritativo(motor, escola_id: int) -> dict:
    """A VERDADE: recálculo isolado, sem concorrente nenhum."""
    with Session(motor) as db:
        scoring.recalcular_escola(db, escola_id)
    return _notas(motor, escola_id)


def _recalcular_em_thread(motor, escola_id, erros, nome, pronto=None):
    def _alvo():
        try:
            with Session(motor) as db:
                scoring.recalcular_escola(db, escola_id)
        except Exception as erro:  # noqa: BLE001 — é o que o teste mede
            erros.append(f"{type(erro).__name__}: {erro}"[:300])
        finally:
            if pronto is not None:
                pronto.set()

    t = threading.Thread(target=_alvo, name=nome)
    t.start()
    return t


# --------------------------------------------------------------------------
# 1. Concorrência crua: nada de 500, nada de duplicata.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("n_threads", [2, 4])
def test_recalculos_simultaneos_nao_estouram_e_deixam_uma_nota_por_aluno(
        motor_pg, escola_pg, n_threads):
    """Vários recálculos sobrepostos da MESMA escola com ``notas`` VAZIA (o
    estado logo após uma importação): sem trava, todos leem "não existe nota" e
    todos INSERTem a mesma chave — ``uq_nota_aluno_ano`` estoura em 23505 e
    vira HTTP 500 na cara do gestor.

    A sobreposição é FORÇADA no ponto exato do defeito (entre o SELECT das
    notas e a gravação, ``scoring.py``), não deixada ao acaso do escalonador:
    o teste tem de reprovar SEMPRE que a exclusão mútua sumir, não uma vez a
    cada tantas execuções."""
    escola_id = escola_pg["escola_id"]
    leu, soltar = threading.Event(), threading.Event()

    def _entre_ler_notas_e_gravar(conn, cursor, sql, params, contexto, muitos):
        if (threading.current_thread().name == "R0" and not leu.is_set()
                and sql.lstrip()[:6].upper() == "SELECT" and " notas" in sql):
            leu.set()
            assert soltar.wait(60)

    erros: list[str] = []
    event.listen(motor_pg, "after_cursor_execute", _entre_ler_notas_e_gravar)
    try:
        threads = [_recalcular_em_thread(motor_pg, escola_id, erros, "R0")]
        assert leu.wait(60), "o 1º recálculo nem chegou a ler as notas"
        threads += [_recalcular_em_thread(motor_pg, escola_id, erros, f"R{i}")
                    for i in range(1, n_threads)]
        time.sleep(0.5)      # sem trava, os outros gravam tudo enquanto R0 dorme
        soltar.set()
        for t in threads:
            t.join(120)
    finally:
        event.remove(motor_pg, "after_cursor_execute", _entre_ler_notas_e_gravar)

    assert erros == [], f"recálculo concorrente estourou: {erros}"
    with Session(motor_pg) as db:
        total = db.execute(
            select(func.count()).select_from(Nota)
            .where(Nota.escola_id == escola_id)).scalar_one()
        maior = db.execute(text(
            "SELECT COALESCE(MAX(c),0) FROM (SELECT COUNT(*) c FROM notas "
            "WHERE escola_id=:e GROUP BY aluno_id, ano_letivo) x"
        ), {"e": escola_id}).scalar_one()
    assert total == ALUNOS
    assert maior == 1, "mais de uma nota para o mesmo aluno/ano"


def test_ordens_de_ranking_divergentes_nao_geram_deadlock_nem_erro(
        motor_pg, escola_pg):
    """A ordem dos INSERTs em ``notas`` É a ordem do RANKING. Duas transações
    com rankings diferentes inserem em ordens diferentes — o par clássico de
    deadlock (40P01), que o Postgres resolve matando uma delas.

    Na prática a violação de unicidade (23505) costuma disparar antes de o
    ciclo de espera se fechar, então o erro observado varia. O que este teste
    exige é o mesmo nos dois casos: recálculos concorrentes com ordens
    divergentes não podem produzir erro NENHUM — e sob a trava não produzem,
    porque nunca há duas escrevendo em ``notas`` ao mesmo tempo."""
    escola_id = escola_pg["escola_id"]
    erros: list[str] = []

    for volta in range(3):
        with Session(motor_pg) as db:
            db.execute(text("DELETE FROM notas WHERE escola_id=:e"),
                       {"e": escola_id})
            db.commit()
        _importar_concorrente(motor_pg, escola_pg, deslocamento=volta * 37,
                              dia=1 + volta)
        threads = [_recalcular_em_thread(motor_pg, escola_id, erros, f"D{volta}{i}")
                   for i in range(4)]
        # Enquanto eles rodam, o ranking MUDA embaixo — as ordens divergem.
        _importar_concorrente(motor_pg, escola_pg, deslocamento=volta * 37 + 11,
                              dia=10 + volta)
        for t in threads:
            t.join(120)

    assert erros == [], f"deadlock/erro no recálculo concorrente: {erros}"


# --------------------------------------------------------------------------
# 2. O dano real: quem grava por último tem de ter lido por último.
# --------------------------------------------------------------------------
def test_quem_grava_por_ultimo_leu_por_ultimo(motor_pg, escola_pg, monkeypatch):
    """O ÚNICO teste que pega a corrupção silenciosa.

    Encenação (nada artificial: é sync automática + gestor clicando):
      * LENTO lê o estado e demora para gravar (escalonamento do SO, GC, disco);
      * enquanto isso uma importação COMITA dados novos e o RAPIDO recalcula.

    Sem trava, o RAPIDO grava certo e o LENTO grava por cima com o estado
    VELHO: nenhum erro, banco coerente, notas erradas. Com a trava, o RAPIDO
    espera o LENTO e relê — quem grava por último leu por último."""
    escola_id = escola_pg["escola_id"]
    with Session(motor_pg) as db:
        scoring.recalcular_escola(db, escola_id)   # estado inicial (UPDATE, não INSERT)

    leu = threading.Event()
    soltar = threading.Event()
    contexto_real = scoring._carregar_contexto

    def _contexto(db, eid):
        ctx = contexto_real(db, eid)
        if threading.current_thread().name == "LENTO":
            leu.set()
            assert soltar.wait(60)
        return ctx

    monkeypatch.setattr(scoring, "_carregar_contexto", _contexto)

    erros: list[str] = []
    t_lento = _recalcular_em_thread(motor_pg, escola_id, erros, "LENTO")
    assert leu.wait(60), "o LENTO nem chegou a ler"

    # A importação vizinha comita DEPOIS da leitura do LENTO.
    _importar_concorrente(motor_pg, escola_pg, deslocamento=101, dia=20)

    fim_rapido = threading.Event()
    t_rapido = _recalcular_em_thread(motor_pg, escola_id, erros, "RAPIDO",
                                     pronto=fim_rapido)

    # PROVA DIRETA da exclusão mútua: com a trava o RAPIDO NÃO consegue passar
    # enquanto o LENTO segura — ele fica bloqueado, não "corre por fora".
    passou_por_fora = fim_rapido.wait(3.0)
    soltar.set()
    t_lento.join(120)
    t_rapido.join(120)

    assert erros == [], erros
    assert not passou_por_fora, (
        "o 2º recálculo atravessou enquanto o 1º ainda não gravou — "
        "não há exclusão mútua")

    resultado = _notas(motor_pg, escola_id)
    assert resultado == _autoritativo(motor_pg, escola_id), (
        "as notas gravadas não são as do estado final dos dados — "
        "quem gravou por último leu um estado VELHO (corrupção silenciosa)")


# --------------------------------------------------------------------------
# 3. A trava é transacional: entra cedo, sai no commit.
# --------------------------------------------------------------------------
def _advisory(conexao, classid: int, objid: int) -> int:
    return conexao.execute(text(
        "SELECT count(*) FROM pg_locks WHERE locktype='advisory' "
        "AND classid=:c AND objid=:o"), {"c": classid, "o": objid}).scalar_one()


def test_trava_do_recalculo_e_solta_no_commit(motor_pg, escola_pg, monkeypatch):
    """Segurada durante o cálculo inteiro (senão não serializa nada) e solta
    sozinha no ``db.commit()`` do fim (senão vaza e trava a escola)."""
    escola_id = escola_pg["escola_id"]
    dentro: list[int] = []
    contexto_real = scoring._carregar_contexto

    def _contexto(db, eid):
        ctx = contexto_real(db, eid)
        with motor_pg.connect() as espia:      # OUTRA conexão: enxerga o lock
            dentro.append(_advisory(espia, _NS_RECALCULO, escola_id))
        return ctx

    monkeypatch.setattr(scoring, "_carregar_contexto", _contexto)

    with Session(motor_pg) as db:
        scoring.recalcular_escola(db, escola_id)

    assert dentro == [1], "a trava não estava segurada durante o cálculo"
    with motor_pg.connect() as espia:
        assert _advisory(espia, _NS_RECALCULO, escola_id) == 0, (
            "a trava sobreviveu ao commit — escola travada até a conexão morrer")


def test_hierarquia_nunca_pega_4713_segurando_4711(motor_pg, escola_pg,
                                                   monkeypatch):
    """A regra que impede DEADLOCK ENTRE TRAVAS: o recálculo (4713) nunca pode
    ser pedido por uma transação que ainda segura a de importação (4711).

    Prova no caminho real: ``importacoes.confirmar`` (que adquire 4711) até o
    recálculo do fim — inspecionando ``pg_locks`` DE DENTRO da transação."""
    from app.routers import importacoes as imp
    from app.schemas.importacao import ImportacaoConfirm

    escola_id = escola_pg["escola_id"]
    segurados: list[list[int]] = []
    contexto_real = scoring._carregar_contexto

    def _contexto(db, eid):
        segurados.append(sorted(db.execute(text(
            "SELECT DISTINCT classid FROM pg_locks WHERE locktype='advisory' "
            "AND pid = pg_backend_pid()")).scalars()))
        return contexto_real(db, eid)

    monkeypatch.setattr(scoring, "_carregar_contexto", _contexto)

    with Session(motor_pg) as db:
        usuario = db.get(Usuario, escola_pg["usuario_id"])
        aluno = db.get(Aluno, escola_pg["alunos"][0])
        imp.confirmar(
            dados=ImportacaoConfirm(
                plataforma="elefante", formato="resumo", tipo="pdf",
                recalcular=True,
                linhas=[{"nome": aluno.nome, "dados": {"livros_unicos": 9}}]),
            escola_id=escola_id, usuario=usuario, db=db)

    assert segurados, "o recálculo do /confirmar nem rodou"
    for travas in segurados:
        assert _NS_RECALCULO in travas, "o recálculo rodou SEM a trava 4713"
        assert _NS_IMPORTACAO not in travas, (
            "4713 pedida ainda segurando 4711 — hierarquia violada, "
            "duas travas em ordens opostas = deadlock entre travas")
