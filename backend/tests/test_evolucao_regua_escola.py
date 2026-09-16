"""MELHOR EVOLUÇÃO — a régua é a da ESCOLA INTEIRA (decisão do dono, 2026-09-15).

Turma, série, turno e professor são filtros de POPULAÇÃO: mudam quem aparece na
lista, nunca a régua. A mesma criança, com os mesmos dados, tem a mesma nota de
evolução com e sem filtro. E a série do Matific (contadores DO ANO) não usa um
snapshot do ano anterior como base; a do Elefante (contadores de vida inteira)
continua usando.
"""
from datetime import datetime

from app.models import (
    Aluno,
    Configuracao,
    Escola,
    Importacao,
    Leitura,
    Livro,
    Matricula,
    NivelDificuldade,
    ReferenciaNormalizacao,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
)
from app.services import dificuldade_livro as dl
from app.services import evolucao as svc
from app.services import scoring

INI, FIM = datetime(2026, 8, 1), datetime(2026, 8, 31, 23, 59, 59)
BASE, ATUAL = datetime(2026, 7, 20), datetime(2026, 8, 20)

# (nome, turma, crescimento na matemática, crescimento na leitura)
MANHA = [("Manha 1", 10, 2), ("Manha 2", 20, 4), ("Manha 3", 30, 6)]
TARDE = [("Tarde 1", 100, 10), ("Tarde 2", 150, 14), ("Tarde 3", 200, 18),
         ("Tarde 4", 250, 22), ("Tarde 5", 300, 26), ("Tarde 6", 350, 30),
         ("Tarde 7", 400, 34)]


def _escola(db, nome):
    escola = Escola(nome=nome, ano_letivo_ativo=2026, status="ativa")
    db.add(escola)
    db.flush()
    for namespace, valores in scoring.PESOS_PADRAO.items():
        db.add(Configuracao(escola_id=escola.id, namespace=namespace,
                            chave="valores", valor=valores))
    db.add(NivelDificuldade(escola_id=escola.id, nome="Nível 2", codigo="nivel_2",
                            codigos=["D", "E"], pontos_padrao=4.0, ordem=1))
    db.add(ReferenciaNormalizacao(escola_id=escola.id, modo="auto"))
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    return escola, imp


def _turma(db, escola, nome, serie, turno):
    turma = Turma(escola_id=escola.id, nome=nome, ano_escolar=serie, ano_letivo=2026,
                  turno=turno, status="ativa")
    db.add(turma)
    db.flush()
    return turma


def _aluno(db, escola, turma, nome):
    aluno = Aluno(escola_id=escola.id, nome=nome, status="ativo")
    db.add(aluno)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id, turma_id=turma.id,
                     ano_letivo=2026))
    return aluno


def _matific(db, escola, imp, aluno, quando, atividades, estrelas, media=3.0):
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                           data_referencia=quando, atividades=atividades,
                           estrelas=estrelas, pontuacao_media=media))


def _elefante(db, escola, imp, aluno, quando, livros):
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                            data_referencia=quando, livros_unicos=livros,
                            tempo_leitura_min=livros * 10, questoes_tentativas=livros * 2,
                            questoes_acertos=livros, livros_por_nivel={"D": livros}))


def _popular(db, escola, imp, turma, alunos):
    criados = {}
    for nome, ativ, livros in alunos:
        aluno = _aluno(db, escola, turma, nome)
        _matific(db, escola, imp, aluno, BASE, 0, 0)
        _matific(db, escola, imp, aluno, ATUAL, ativ, ativ * 3)
        _elefante(db, escola, imp, aluno, BASE, 0)
        _elefante(db, escola, imp, aluno, ATUAL, livros)
        criados[aluno.id] = nome
    return criados


def _por_nome(itens):
    return {item.nome: item for item in itens}


def test_nota_de_evolucao_identica_com_turma_serie_turno_e_professor(db):
    escola, imp = _escola(db, "EM REGUA ESCOLA")
    manha = _turma(db, escola, "3º A", "3º Ano", "manha")
    tarde = _turma(db, escola, "4º A", "4º Ano", "tarde")
    ids_manha = _popular(db, escola, imp, manha, MANHA)
    _popular(db, escola, imp, tarde, TARDE)
    db.commit()

    completo = _por_nome(svc.ranking_evolucao(db, escola.id, INI, FIM, base_no_periodo=True))
    assert len(completo) == 10

    recortes = {
        "turma": {"turma_id": manha.id},
        "serie": {"ano_escolar": "3º Ano"},
        "turno": {"turno": "manha"},
        "professor": {"turma_ids": [manha.id]},
    }
    for rotulo, filtro in recortes.items():
        itens = svc.ranking_evolucao(db, escola.id, INI, FIM, base_no_periodo=True, **filtro)
        assert {i.aluno_id for i in itens} == set(ids_manha), rotulo
        for item in itens:
            referencia = completo[item.nome]
            assert item.notas == referencia.notas, (rotulo, item.nome)
            assert item.nota_evolucao == referencia.nota_evolucao, (rotulo, item.nome)
            assert item.ganhos == referencia.ganhos, (rotulo, item.nome)
        # A POSIÇÃO continua numerada dentro do recorte (semântica de sempre).
        assert sorted(i.posicao for i in itens) == [1, 2, 3], rotulo
        assert {i.n_aferidos["matematica"] for i in itens} == {3}, rotulo
        assert sorted(i.posicao_dimensao["leitura"] for i in itens) == [1, 2, 3], rotulo

    # Prova de que a régua NÃO é a da turma: numa escola que só tivesse a manhã
    # (a régua que o filtro antigo recalculava), as notas seriam outras.
    so_manha, imp2 = _escola(db, "EM SO A MANHA")
    turma2 = _turma(db, so_manha, "3º A", "3º Ano", "manha")
    _popular(db, so_manha, imp2, turma2, MANHA)
    db.commit()
    isolada = _por_nome(svc.ranking_evolucao(db, so_manha.id, INI, FIM, base_no_periodo=True))
    assert any(isolada[nome].notas != completo[nome].notas for nome, _, _ in MANHA)


def test_secretaria_sem_turmas_recebe_lista_vazia(db):
    escola, imp = _escola(db, "EM SEM TURMAS PERMITIDAS")
    turma = _turma(db, escola, "3º A", "3º Ano", "manha")
    _popular(db, escola, imp, turma, MANHA)
    db.commit()
    assert svc.ranking_evolucao(db, escola.id, INI, FIM, turma_ids=[],
                                base_no_periodo=True) == []


def test_base_do_matific_ignora_snapshot_do_ano_anterior(db):
    escola, imp = _escola(db, "EM VIRADA DO ANO")
    turma = _turma(db, escola, "3º A", "3º Ano", "manha")
    aluno = _aluno(db, escola, turma, "Virada")
    # Matific: contadores DO ANO — dezembro/2025 alto, janeiro/2026 recomeça.
    _matific(db, escola, imp, aluno, datetime(2025, 12, 20), 400, 1800)
    _matific(db, escola, imp, aluno, datetime(2026, 1, 10), 5, 20)
    _matific(db, escola, imp, aluno, datetime(2026, 1, 28), 35, 150)
    _matific(db, escola, imp, aluno, datetime(2026, 8, 5), 50, 220)
    _matific(db, escola, imp, aluno, datetime(2026, 8, 25), 60, 260)
    # Elefante: contadores de VIDA INTEIRA — dezembro/2025 é base legítima.
    _elefante(db, escola, imp, aluno, datetime(2025, 12, 20), 10)
    _elefante(db, escola, imp, aluno, datetime(2026, 1, 28), 14)
    db.commit()
    jan_ini, jan_fim = datetime(2026, 1, 1), datetime(2026, 1, 31, 23, 59, 59)

    justo = svc.ranking_evolucao(db, escola.id, jan_ini, jan_fim, base_no_periodo=True)[0]
    # MUDOU (MAT-01): esperava (30, 130), com o 1º snapshot de 2026 (10/01) como
    # base de si mesmo. A janela COMEÇA no início do ano letivo e o contador do
    # Matific é DO ANO — parte de zero em 01/01 —, então não há acumulado
    # anterior a descontar: janeiro vale 35/150, o mesmo que "todo o histórico"
    # de 2026 dá. Dez/2025 continua descartado (era o ponto original do teste:
    # com ele como base o ganho seria max(0, 35 − 400) = 0).
    assert (justo.ganhos["atividades"], justo.ganhos["estrelas"]) == (35, 150)
    # Base do Elefante continua sendo dezembro/2025 (vida inteira): +4 livros.
    assert justo.ganhos["livros"] == 4

    # Sem base_no_periodo o número é o mesmo — a incoerência entre os dois modos
    # na janela que abre o ano desaparece.
    padrao = svc.ranking_evolucao(db, escola.id, jan_ini, jan_fim)[0]
    assert (padrao.ganhos["atividades"], padrao.ganhos["estrelas"]) == (35, 150)
    assert padrao.ganhos["livros"] == 4

    # `_janela` sem `ano_letivo` mantém o comportamento de sempre.
    serie = svc._series_por_aluno(db, escola.id, SnapshotMatific)[aluno.id]
    atual, base = svc._janela(serie, jan_ini, jan_fim, base_no_periodo=True)
    assert base.data_referencia == datetime(2025, 12, 20)
    atual, base = svc._janela(serie, jan_ini, jan_fim, base_no_periodo=True, ano_letivo=2026)
    assert base is None                                   # começa em 01/01: zero
    assert atual.data_referencia == datetime(2026, 1, 28)
    # Contraprova: janela que começa NO MEIO do ano mantém a regra de sempre — o
    # acumulado anterior não vira mérito de agosto. Com a série inteira, a base é
    # o último snapshot ANTES de 01/08 (o de janeiro).
    ago_ini, ago_fim = datetime(2026, 8, 1), datetime(2026, 8, 31, 23, 59, 59)
    atual8, base8 = svc._janela(serie, ago_ini, ago_fim,
                                base_no_periodo=True, ano_letivo=2026)
    assert (base8.data_referencia, atual8.data_referencia) == (
        datetime(2026, 1, 28), datetime(2026, 8, 25))
    assert atual8.atividades - base8.atividades == 25
    # E SEM nenhum snapshot antes da janela, a base justa continua sendo o 1º
    # snapshot DENTRO dela (é só no início do ano letivo que a base é zero).
    so_agosto = [snap for snap in serie if snap.data_referencia >= ago_ini]
    atual_so, base_so = svc._janela(so_agosto, ago_ini, ago_fim,
                                    base_no_periodo=True, ano_letivo=2026)
    assert base_so.data_referencia == datetime(2026, 8, 5)
    assert atual_so.atividades - base_so.atividades == 10


def test_ranking_de_evolucao_valora_o_livro_pelo_id_oficial(db):
    """REGUA-02 — o mesmo livro vale o MESMO número em qualquer tela.

    Livro do catálogo RENOMEADO na escola (título local, `elefante_id` oficial):
    a nota anual, o /ranking/leitura, as premiações e o histórico já o
    identificavam pelo id; o ranking de evolução o identificava só pelo título e
    caía no típico do nível — o mesmo livro valia dois números conforme a tela."""
    escola, _ = _escola(db, "EM LIVRO RENOMEADO")
    turma = _turma(db, escola, "3º A", "3º Ano", "manha")
    aluno = _aluno(db, escola, turma, "Leitor Renomeado")
    castelo = dl.catalogo().buscar("O Castelo Encantado", "Z")
    assert castelo is not None
    titulo_local = "Castelo (cópia da escola)"
    livro = Livro(escola_id=escola.id, titulo=titulo_local, nivel_codigo="Z",
                  elefante_id=castelo.id)
    db.add(livro)
    db.flush()
    db.add(Leitura(escola_id=escola.id, aluno_id=aluno.id, livro_id=livro.id,
                   data=datetime(2026, 8, 10, 9, 0), tempo_leitura_min=30))
    db.commit()

    # O item da leitura carrega a identidade oficial: (título, nível, tempo, id)
    # — o mesmo formato de 4 campos que os outros consumidores já passam.
    _, no_periodo = svc._leituras_no_periodo(db, escola.id, INI, FIM)
    assert no_periodo[aluno.id]["itens"] == [(titulo_local, "Z", 0, castelo.id)]

    regra = dl.regra_da_escola(db, escola.id)
    por_id = regra.valor_livro("Z", titulo_local, "3º Ano", elefante_id=castelo.id)
    por_titulo = regra.valor_livro("Z", titulo_local, "3º Ano")
    assert por_id != por_titulo                  # a divergência era mensurável
    item = svc.ranking_evolucao(db, escola.id, INI, FIM, base_no_periodo=True)[0]
    assert item.ganhos["pontos_dificuldade"] == round(por_id, 2)
