"""Consolidação das fichas-sombra num PostgreSQL REAL.

O SQLite da suíte não tem ``FOR UPDATE``, advisory lock nem transação
``READ ONLY``: as três defesas da consolidação só existem de verdade aqui.
Este módulo prova, contra o banco de produção (Postgres):

  1. ``planejar`` + ``aplicar`` ponta a ponta — o padrão consolida, os gêmeos
     ficam para revisão, os dados vão para a oficial, a nota é recalculada e a
     segunda execução não acha nada;
  2. duas aplicações CONCORRENTES do mesmo plano fundem o par UMA vez: a trava
     de importação da escola serializa, e a segunda reconfere o par no banco
     atual (compare-and-set) e o pula — sem erro, sem fundir duas vezes;
  3. a simulação do script roda numa transação que o próprio banco confirma ser
     somente leitura, e não grava nada;
  4. o compare-and-set enxerga a mudança gravada por OUTRA transação mesmo com
     as fichas ainda vivas no identity map de quem aplica;
  5. se o recálculo cai, o rollback desfaz as fusões — elas e as notas são uma
     transação só;
  6. a CONTINUIDADE da conta (iteração 2) com os tipos do Postgres: datas de
     snapshot e ``max`` de timestamp de evento comparadas por dia, e a
     evidência gravada no JSON da auditoria;
  7. (iteração 3) o histórico reenviado pela conta não DOBRA os eventos na
     fusão e a próxima coleta não os grava de novo — a identidade do evento
     (minuto de ``ocorrido_em`` como o Postgres devolve) e a chave recalculada
     para a oficial batem com as do importador; a oficial zerada e a sombra
     com dado próprio de antes do limite seguem CONFLITO;
  8. (iteração 4) no Elefante só a IGUALDADE do limite prova a mesma conta: o
     1º retrato da sombra repetindo o último da oficial nos quatro contadores
     (com queda DENTRO da série da oficial) consolida e a evidência dos quatro
     vai para o JSON da auditoria; um contador diferente, ou o limite
     crescendo, é CONFLITO ``contadores_diferentes_no_limite``.

Como rodar::

    set TEST_DATABASE_URL_PG=postgresql+psycopg://constela_teste@127.0.0.1:5433/constela_teste
    pytest tests/test_consolidacao_sombras_pg.py -m postgres

Sem ``TEST_DATABASE_URL_PG`` o módulo inteiro é pulado. Nomes FICTÍCIOS.
"""
from __future__ import annotations

import os
import sys
import threading

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models import (Aluno, Configuracao, Escola, IdentidadeExterna, Importacao,
                        LogAuditoria, Matricula, NivelDificuldade, Nota,
                        ReferenciaNormalizacao, SnapshotElefante, SnapshotMatific,
                        Turma, Usuario)
from app.services import consolidacao_sombras as cs
from app.services import scoring

pytestmark = pytest.mark.postgres

URL_PG = os.environ.get("TEST_DATABASE_URL_PG", "")
if not URL_PG:
    pytest.skip("defina TEST_DATABASE_URL_PG para rodar no PostgreSQL real",
                allow_module_level=True)

OFICIAL = "ZULEICA RAMONA TEODORO DA CUNHA"
SOMBRA = "ZULEICA R"


@pytest.fixture(scope="module")
def motor_pg():
    motor = create_engine(URL_PG, pool_size=8, max_overflow=8, pool_pre_ping=True)
    import app.quest.models  # noqa: F401 — registra o schema completo

    Base.metadata.create_all(motor)
    yield motor
    motor.dispose()


def _semear(motor, sufixo: str) -> dict:
    """Escola NOVA (isolada das outras execuções) com o padrão real e os gêmeos."""
    with Session(motor) as db:
        escola = Escola(nome=f"ESCOLA SOMBRAS PG {sufixo}", ano_letivo_ativo=2026)
        db.add(escola)
        db.flush()
        admin = Usuario(escola_id=escola.id, nome="Admin PG",
                        email=f"sombras-{escola.id}-{sufixo}@teste.local",
                        senha_hash="x", cargo="admin")
        db.add(admin)
        for ns, valores in scoring.PESOS_PADRAO.items():
            db.add(Configuracao(escola_id=escola.id, namespace=ns,
                                chave="valores", valor=valores))
        db.add(NivelDificuldade(escola_id=escola.id, nome="Nivel 2", codigo="nivel_2",
                                codigos=["D"], pontos_padrao=4.0, ordem=0))
        db.add(ReferenciaNormalizacao(escola_id=escola.id, modo="auto"))
        db.flush()
        imp = Importacao(escola_id=escola.id, usuario_id=admin.id,
                         plataforma="matific", tipo="seed")
        turma = Turma(escola_id=escola.id, nome="2o Ano B", ano_escolar="2o Ano",
                      ano_letivo=2026)
        db.add_all([imp, turma])
        db.flush()

        def aluno(nome, lp):
            a = Aluno(escola_id=escola.id, nome=nome, da_lista_piloto=lp)
            db.add(a)
            db.flush()
            db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id,
                             ano_letivo=2026))
            return a

        oficial = aluno(OFICIAL, True)
        sombra = aluno(SOMBRA, False)
        aluno("MARIA ALICE ALVES PEREIRA", True)
        aluno("MARIA ALINE ALVES PEREIRA", True)
        gemea = aluno("MARIA A", False)
        db.add(IdentidadeExterna(escola_id=escola.id, aluno_id=sombra.id,
                                 plataforma="matific", id_externo=f"u-{sufixo}"))
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=sombra.id,
                               importacao_id=imp.id, atividades=40, estrelas=150,
                               pontuacao_media=3.75))
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=oficial.id,
                                importacao_id=imp.id, livros_unicos=12,
                                tempo_leitura_min=300, livros_por_nivel={"D": 2}))
        db.commit()
        return {"escola_id": escola.id, "oficial": oficial.id, "sombra": sombra.id,
                "gemea": gemea.id}


@pytest.fixture()
def cena(motor_pg, request):
    return _semear(motor_pg, request.node.name[-24:])


def test_planejar_e_aplicar_no_postgres(motor_pg, cena):
    with Session(motor_pg) as db:
        plano = cs.planejar(db, cena["escola_id"])
        assert plano.item_da_sombra(cena["sombra"]).classe == cs.CONSOLIDAR
        gemea = plano.item_da_sombra(cena["gemea"])
        assert (gemea.classe, gemea.motivo) == (cs.REVISAR, "varias_oficiais")
        res = cs.aplicar(db, plano, usuario_id=None, origem="teste_pg")
        assert [x["sombra_id"] for x in res["consolidados"]] == [cena["sombra"]]

    with Session(motor_pg) as db:
        assert db.get(Aluno, cena["sombra"]) is None
        assert db.get(Aluno, cena["gemea"]) is not None
        assert db.execute(select(IdentidadeExterna.aluno_id).where(
            IdentidadeExterna.escola_id == cena["escola_id"])).scalars().all() == [
            cena["oficial"]]
        assert db.execute(select(SnapshotMatific.aluno_id).where(
            SnapshotMatific.escola_id == cena["escola_id"])).scalars().all() == [
            cena["oficial"]]
        nota = db.execute(select(Nota).where(Nota.aluno_id == cena["oficial"])).scalar_one()
        assert nota.aferido_matematica and nota.aferido_leitura
        assert db.execute(select(func.count()).select_from(Nota).where(
            Nota.escola_id == cena["escola_id"])).scalar_one() == 4   # sem a sombra
        assert db.execute(select(func.count()).select_from(LogAuditoria).where(
            LogAuditoria.escola_id == cena["escola_id"],
            LogAuditoria.acao == "aluno.consolidado_automatico")).scalar_one() == 1
        # Idempotente: a segunda execução não acha nada.
        assert cs.planejar(db, cena["escola_id"]).consolidar == []


def test_duas_aplicacoes_concorrentes_fundem_o_par_uma_vez(motor_pg, cena):
    with Session(motor_pg) as db:
        plano = cs.planejar(db, cena["escola_id"])
    assert len(plano.consolidar) == 1

    largada = threading.Barrier(2)
    resultados: list[dict] = []
    erros: list[BaseException] = []

    def rodar():
        try:
            with Session(motor_pg) as db:
                largada.wait(timeout=30)
                resultados.append(cs.aplicar(db, plano, usuario_id=None,
                                             origem="corrida_pg"))
        except BaseException as exc:  # noqa: BLE001 — o teste inspeciona
            erros.append(exc)

    threads = [threading.Thread(target=rodar) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert erros == []
    assert sorted(len(r["consolidados"]) for r in resultados) == [0, 1]
    assert sorted(len(r["pulados"]) for r in resultados) == [0, 1]
    [pulado] = [p for r in resultados for p in r["pulados"]]
    assert pulado["motivo_atual"] == "ficha_inexistente"
    with Session(motor_pg) as db:
        assert db.get(Aluno, cena["sombra"]) is None
        acoes = db.execute(select(LogAuditoria.acao).where(
            LogAuditoria.escola_id == cena["escola_id"],
            LogAuditoria.acao.in_(("aluno.consolidado_automatico", "aluno.fundido")))
        ).scalars().all()
        assert sorted(acoes) == ["aluno.consolidado_automatico", "aluno.fundido"]


def test_mudanca_de_outra_transacao_com_fichas_vivas_na_memoria_pula(motor_pg, cena):
    """Quem aplica ainda segura as fichas que o plano leu (identity map da
    sessão) e OUTRA transação dá à sombra um nº de chamada divergente do da
    oficial e grava. O compare-and-set relê do banco: o par é pulado."""
    with Session(motor_pg, autoflush=False) as a:
        a.get(Aluno, cena["oficial"]).numero_chamada = 7
        a.commit()
        plano = cs.planejar(a, cena["escola_id"])
        vivas = (a.get(Aluno, cena["sombra"]), a.get(Aluno, cena["oficial"]))
        with Session(motor_pg) as b:
            b.get(Aluno, cena["sombra"]).numero_chamada = 3
            b.commit()
        res = cs.aplicar(a, plano, usuario_id=None, origem="teste_pg")
        assert res["consolidados"] == [] and len(vivas) == 2
        [pulado] = res["pulados"]
        assert (pulado["sombra_id"], pulado["motivo_atual"]) == (
            cena["sombra"], "identificador_divergente")
    with Session(motor_pg) as db:
        assert db.get(Aluno, cena["sombra"]) is not None


def test_falha_no_recalculo_nao_deixa_fusao_gravada_no_postgres(motor_pg, cena,
                                                                monkeypatch):
    """Fusões, auditoria e recálculo numa transação só: se o recálculo cai, o
    rollback de quem chamou desfaz a fusão — nenhuma ficha fica fundida com a
    nota velha."""
    def explode(*a, **k):
        raise RuntimeError("recálculo caiu")

    monkeypatch.setattr(cs, "_recalcular", explode)
    with Session(motor_pg) as db:
        plano = cs.planejar(db, cena["escola_id"])
        with pytest.raises(RuntimeError):
            cs.aplicar(db, plano, usuario_id=None, origem="teste_pg")
        db.rollback()
    with Session(motor_pg) as db:
        assert db.get(Aluno, cena["sombra"]) is not None
        assert db.execute(select(IdentidadeExterna.aluno_id).where(
            IdentidadeExterna.escola_id == cena["escola_id"])).scalars().all() == [
            cena["sombra"]]
        assert db.execute(select(func.count()).select_from(LogAuditoria).where(
            LogAuditoria.escola_id == cena["escola_id"])).scalar_one() == 0


def test_continuidade_da_conta_no_postgres(motor_pg, cena):
    """Iteração 2: a oficial com o Matific por NOME até 31/07 e a sombra com a
    conta de 01/08 em diante (contadores iguais no limite) consolidam; o mesmo
    par com um evento da oficial DEPOIS de a sombra começar (``func.max`` sobre
    timestamp no Postgres) é CONFLITO. A continuidade fica na auditoria (JSON)."""
    from datetime import datetime

    from app.models import EventoAluno

    with Session(motor_pg) as db:
        eid = cena["escola_id"]
        turma = db.execute(select(Turma).where(Turma.escola_id == eid)).scalar_one()
        imp = db.execute(select(Importacao).where(Importacao.escola_id == eid)).scalar_one()

        def par(nome_oficial, nome_sombra, conta):
            ids = []
            for nome, lp in ((nome_oficial, True), (nome_sombra, False)):
                a = Aluno(escola_id=eid, nome=nome, da_lista_piloto=lp)
                db.add(a)
                db.flush()
                db.add(Matricula(escola_id=eid, aluno_id=a.id, turma_id=turma.id,
                                 ano_letivo=2026))
                ids.append(a.id)
            db.add(IdentidadeExterna(escola_id=eid, aluno_id=ids[1], plataforma="matific",
                                     id_externo=conta))
            for aluno_id, dia, atividades, estrelas in (
                    (ids[0], "2026-06-30", 15, 48), (ids[0], "2026-07-31", 23, 70),
                    (ids[1], "2026-08-01", 23, 70), (ids[1], "2026-09-01", 31, 101)):
                db.add(SnapshotMatific(escola_id=eid, aluno_id=aluno_id, importacao_id=imp.id,
                                       data_referencia=datetime.fromisoformat(dia),
                                       atividades=atividades, estrelas=estrelas,
                                       pontuacao_media=3.0))
            return ids

        oficial, sombra = par("WALDIRENE SOFIA FAGUNDES SILVA", "WALDIRENE S",
                              f"u-w-{eid}")
        oficial_b, sombra_b = par("CLEMENTINA ROSA VASCONCELOS", "CLEMENTINA R",
                                  f"u-c-{eid}")
        db.add(EventoAluno(escola_id=eid, aluno_id=oficial_b, plataforma="matific",
                           tipo_evento="atividade", chave_natural=f"evt-{eid}",
                           ocorrido_em=datetime(2026, 8, 20, 14, 30)))
        db.commit()

        plano = cs.planejar(db, eid)
        item = plano.item_da_sombra(sombra)
        assert (item.classe, item.oficial_id) == (cs.CONSOLIDAR, oficial)
        assert item.evidencias["continuidade"]["matific"]["contadores"] == "iguais"
        outro = plano.item_da_sombra(sombra_b)
        assert (outro.classe, outro.motivo) == (cs.CONFLITO,
                                                "dados_simultaneos_mesma_plataforma")
        res = cs.aplicar(db, plano, usuario_id=None, origem="teste_pg")
        assert sombra in [x["sombra_id"] for x in res["consolidados"]]
        assert sombra_b not in [x["sombra_id"] for x in res["consolidados"]]

    with Session(motor_pg) as db:
        assert db.get(Aluno, sombra) is None and db.get(Aluno, sombra_b) is not None
        assert db.execute(select(func.count()).select_from(SnapshotMatific).where(
            SnapshotMatific.aluno_id == oficial)).scalar_one() == 4
        [detalhes] = db.execute(select(LogAuditoria.detalhes).where(
            LogAuditoria.escola_id == cena["escola_id"],
            LogAuditoria.acao == "aluno.consolidado_automatico",
            LogAuditoria.entidade_id == oficial)).scalars().all()
        assert detalhes["evidencias"]["continuidade"]["matific"] == {
            "ficha_anterior": "oficial", "ultimo_retrato_anterior": "2026-07-31",
            "primeiro_retrato_posterior": "2026-08-01", "dias_entre": 1,
            "contadores": "iguais",
            "contadores_anterior": {"atividades": 23, "estrelas": 70},
            "contadores_posterior": {"atividades": 23, "estrelas": 70}}


def test_historico_reenviado_nao_dobra_eventos_no_postgres(motor_pg, cena):
    """Iteração 3: a sombra de nome idêntico com o histórico da conta reenviado
    (cópias das leituras de julho da oficial, com o evento de cada uma, mais as
    de agosto) consolida SEM dobrar o evento de julho, e a próxima coleta da
    conta — agora da oficial — não grava nada de novo. No mesmo plano, a
    oficial zerada e a sombra com livros próprios de julho seguem CONFLITO."""
    from datetime import datetime

    from app.models import EventoAluno, Leitura, Livro
    from app.services.eventos import chave_evento, ingerir_eventos

    with Session(motor_pg) as db:
        eid = cena["escola_id"]
        turma = db.execute(select(Turma).where(Turma.escola_id == eid)).scalar_one()
        imp = db.execute(select(Importacao).where(Importacao.escola_id == eid)).scalar_one()

        def ficha(nome, lp, conta=None):
            a = Aluno(escola_id=eid, nome=nome, da_lista_piloto=lp)
            db.add(a)
            db.flush()
            db.add(Matricula(escola_id=eid, aluno_id=a.id, turma_id=turma.id, ano_letivo=2026))
            if conta:
                db.add(IdentidadeExterna(escola_id=eid, aluno_id=a.id, plataforma="elefante",
                                         id_externo=conta))
            return a.id

        def retratos(aluno_id, serie):
            for dia, livros, minutos in serie:
                db.add(SnapshotElefante(escola_id=eid, aluno_id=aluno_id, importacao_id=imp.id,
                                        data_referencia=datetime.fromisoformat(dia),
                                        livros_unicos=livros, tempo_leitura_min=minutos,
                                        livros_por_nivel={"D": livros}))

        def ler(aluno_id, titulo, quando):
            livro = db.execute(select(Livro).where(Livro.escola_id == eid,
                                                   Livro.titulo == titulo)).scalar_one_or_none()
            if livro is None:
                livro = Livro(escola_id=eid, titulo=titulo, nivel_codigo="D")
                db.add(livro)
                db.flush()
            db.add(Leitura(escola_id=eid, aluno_id=aluno_id, livro_id=livro.id, data=quando,
                           tempo_leitura_min=15, nivel_codigo="D"))
            db.add(EventoAluno(escola_id=eid, aluno_id=aluno_id, plataforma="elefante",
                               tipo_evento="leitura", ocorrido_em=quando, livro_id=livro.id,
                               conteudo_titulo=titulo, nivel_codigo="D",
                               chave_natural=chave_evento("elefante", "leitura", aluno_id,
                                                          titulo, quando)))

        nome = "LEOCADIA SOUZA BRAGA"
        oficial, sombra = ficha(nome, True), ficha(nome, False, f"44{eid}01")
        retratos(oficial, [("2026-07-13T03:10:00", 1, 20), ("2026-07-31T03:10:00", 3, 45)])
        retratos(sombra, [("2026-08-01T03:10:00", 3, 45), ("2026-08-20T03:10:00", 5, 70)])
        quandos = [datetime(2026, 7, 10, 14, 0, 37), datetime(2026, 7, 15, 14, 0),
                   datetime(2026, 7, 20, 14, 0), datetime(2026, 8, 5, 14, 0),
                   datetime(2026, 8, 12, 9, 30)]
        titulos = [f"LIVRO PG {i}" for i in range(5)]
        for t, q in zip(titulos[:3], quandos[:3]):
            ler(oficial, t, q)
            ler(sombra, t, q)                   # o histórico da conta, de novo
        for t, q in zip(titulos[3:], quandos[3:]):
            ler(sombra, t, q)

        zerada, nova = ficha("CLEMENTINA ROSA VASCONCELOS", True), ficha("CLEMENTINA R",
                                                                       False, f"44{eid}02")
        retratos(zerada, [("2026-07-13", 0, 0), ("2026-07-31", 0, 0)])
        retratos(nova, [("2026-08-01", 2, 10)])
        com_julho_oficial, com_julho = (ficha("HORTENSIA MARIA LIMA", True),
                                        ficha("HORTENSIA M", False, f"44{eid}03"))
        retratos(com_julho_oficial, [("2026-07-13", 8, 40), ("2026-07-31", 10, 60)])
        # O limite REPETE os contadores (iteração 4: a única forma de o limite
        # do Elefante passar) — a trava exercitada é o livro próprio de julho.
        retratos(com_julho, [("2026-08-01", 10, 60)])
        ler(com_julho, "LIVRO PG PROPRIO", datetime(2026, 7, 9, 15, 0))
        db.commit()

        plano = cs.planejar(db, eid)
        assert plano.item_da_sombra(sombra).classe == cs.CONSOLIDAR
        assert (plano.item_da_sombra(nova).classe, plano.item_da_sombra(nova).motivo) == (
            cs.CONFLITO, "contadores_zerados")
        assert (plano.item_da_sombra(com_julho).classe,
                plano.item_da_sombra(com_julho).motivo) == (
            cs.CONFLITO, "dados_simultaneos_mesma_plataforma")
        res = cs.aplicar(db, plano, usuario_id=None, origem="teste_pg")
        assert sombra in [x["sombra_id"] for x in res["consolidados"]]
        assert {nova, com_julho}.isdisjoint(x["sombra_id"] for x in res["consolidados"])

    with Session(motor_pg) as db:
        linhas = db.execute(select(EventoAluno.conteudo_titulo, EventoAluno.ocorrido_em,
                                   EventoAluno.chave_natural)
                            .where(EventoAluno.aluno_id == oficial)
                            .order_by(EventoAluno.ocorrido_em)).all()
        assert [(t, q) for t, q, _c in linhas] == list(zip(titulos, quandos))
        assert all(c == chave_evento("elefante", "leitura", oficial, t, q)
                   for t, q, c in linhas)
        [detalhes] = db.execute(select(LogAuditoria.detalhes).where(
            LogAuditoria.escola_id == eid, LogAuditoria.acao == "aluno.consolidado_automatico",
            LogAuditoria.entidade_id == oficial)).scalars().all()
        assert (len(detalhes["eventos_copia_descartados"]),
                len(detalhes["eventos_rechaveados"])) == (3, 2)
        novos = ingerir_eventos(db, oficial, "elefante", [
            {"escola_id": eid, "aluno_id": oficial, "plataforma": "elefante",
             "tipo_evento": "leitura", "ocorrido_em": q, "conteudo_titulo": t,
             "chave_natural": chave_evento("elefante", "leitura", oficial, t, q)}
            for t, q in zip(titulos, quandos)])
        db.rollback()
        assert novos == 0


def test_elefante_so_aceita_a_igualdade_do_limite_no_postgres(motor_pg, cena):
    """Iteração 4, com os tipos do Postgres (``data_referencia`` com hora da
    coleta, comparada por dia; evidência no JSON da auditoria). Medido em
    produção (12/10): os contadores do Elefante caem dentro da MESMA ficha, e
    nos pares reais o 1º retrato da sombra repete o último da oficial nos
    quatro contadores. Três pares na mesma escola:

      * a oficial CAI dentro da série dela e a sombra repete o último retrato
        nos quatro contadores → CONSOLIDA ("iguais", sem ``maximos_anterior``);
      * um contador só (questões acertadas) difere no limite → CONFLITO;
      * o limite CRESCE nos quatro → CONFLITO (a regra do maior aceitaria)."""
    from datetime import datetime

    campos = ("livros_unicos", "tempo_leitura_min", "questoes_tentativas",
              "questoes_acertos")
    limite = (38, 9, 64, 29)
    with Session(motor_pg) as db:
        eid = cena["escola_id"]
        turma = db.execute(select(Turma).where(Turma.escola_id == eid)).scalar_one()
        imp = db.execute(select(Importacao).where(Importacao.escola_id == eid)).scalar_one()

        def par(nome_oficial, nome_sombra, conta, serie_oficial, serie_sombra):
            ids = []
            for nome, lp in ((nome_oficial, True), (nome_sombra, False)):
                a = Aluno(escola_id=eid, nome=nome, da_lista_piloto=lp)
                db.add(a)
                db.flush()
                db.add(Matricula(escola_id=eid, aluno_id=a.id, turma_id=turma.id,
                                 ano_letivo=2026))
                ids.append(a.id)
            db.add(IdentidadeExterna(escola_id=eid, aluno_id=ids[1], plataforma="elefante",
                                     id_externo=conta))
            for aluno_id, serie in zip(ids, (serie_oficial, serie_sombra)):
                for dia, (livros, minutos, tentativas, acertos) in serie:
                    db.add(SnapshotElefante(
                        escola_id=eid, aluno_id=aluno_id, importacao_id=imp.id,
                        data_referencia=datetime.fromisoformat(dia),
                        livros_unicos=livros, tempo_leitura_min=minutos,
                        questoes_tentativas=tentativas, questoes_acertos=acertos,
                        livros_por_nivel={"D": livros}))
            return ids

        serie_oficial = [("2026-07-13T03:10:00", (52, 14, 90, 41)),
                         ("2026-07-31T03:10:00", limite)]
        oficial, sombra = par("ROSALVA MIRANDA PIRES", "ROSALVA M", f"45{eid}01",
                              serie_oficial,
                              [("2026-08-01T03:10:00", limite),
                               ("2026-08-20T03:10:00", (35, 8, 60, 27))])
        _of_um, um_diferente = par("TEODOMIRO SALES BRITO", "TEODOMIRO S", f"45{eid}02",
                                   serie_oficial,
                                   [("2026-08-01T03:10:00", (38, 9, 64, 30))])
        _of_cresce, crescente = par("BERENICE QUADROS LIMA", "BERENICE Q", f"45{eid}03",
                                    serie_oficial,
                                    [("2026-08-01T03:10:00", (40, 12, 70, 33))])
        db.commit()

        plano = cs.planejar(db, eid)
        item = plano.item_da_sombra(sombra)
        assert (item.classe, item.oficial_id) == (cs.CONSOLIDAR, oficial)
        ev = item.evidencias["continuidade"]["elefante"]
        assert ev["contadores"] == "iguais" and "maximos_anterior" not in ev
        for outro in (um_diferente, crescente):
            assert (plano.item_da_sombra(outro).classe, plano.item_da_sombra(outro).motivo) == (
                cs.CONFLITO, "contadores_diferentes_no_limite")
        res = cs.aplicar(db, plano, usuario_id=None, origem="teste_pg")
        assert sombra in [x["sombra_id"] for x in res["consolidados"]]
        assert {um_diferente, crescente}.isdisjoint(x["sombra_id"] for x in res["consolidados"])

    with Session(motor_pg) as db:
        assert db.get(Aluno, sombra) is None
        assert db.get(Aluno, um_diferente) is not None and db.get(Aluno, crescente) is not None
        assert db.execute(select(func.count()).select_from(SnapshotElefante).where(
            SnapshotElefante.aluno_id == oficial)).scalar_one() == 4
        [detalhes] = db.execute(select(LogAuditoria.detalhes).where(
            LogAuditoria.escola_id == eid, LogAuditoria.acao == "aluno.consolidado_automatico",
            LogAuditoria.entidade_id == oficial)).scalars().all()
        quatro = dict(zip(campos, limite))
        assert detalhes["evidencias"]["continuidade"]["elefante"] == {
            "ficha_anterior": "oficial", "ultimo_retrato_anterior": "2026-07-31",
            "primeiro_retrato_posterior": "2026-08-01", "dias_entre": 1,
            "contadores": "iguais", "contadores_anterior": quatro,
            "contadores_posterior": quatro}


def test_simulacao_do_script_e_somente_leitura_no_postgres(motor_pg, cena, monkeypatch,
                                                           capsys):
    import scripts.consolidar_sombras as etapa

    Sessao = sessionmaker(bind=motor_pg)
    vistos: list[bool] = []
    original = etapa._abrir_somente_leitura

    def conferir(db):
        ok = original(db)
        vistos.append(ok)
        return ok

    monkeypatch.setattr(etapa, "_abrir_somente_leitura", conferir)
    monkeypatch.setattr(etapa, "SessionLocal", Sessao)
    monkeypatch.setattr(sys, "argv", ["consolidar_sombras", "--escola",
                                      str(cena["escola_id"])])
    assert etapa.main() == 0
    saida = capsys.readouterr().out
    assert vistos == [True]                     # o banco confirmou: READ ONLY
    assert "CONSOLIDAR 1 · REVISAR 1" in saida and "nada foi gravado" in saida
    with Session(motor_pg) as db:
        assert db.get(Aluno, cena["sombra"]) is not None
        assert db.execute(select(func.count()).select_from(LogAuditoria).where(
            LogAuditoria.escola_id == cena["escola_id"])).scalar_one() == 0
