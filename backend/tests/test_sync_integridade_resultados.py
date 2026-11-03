"""Integridade dos RESULTADOS depois da sincronização (frente C, 22/10/2026).

Dados 100% fictícios. Dois defeitos achados pela auditoria e90 (regressões
``test_11_leitura_todo_historico_nao_restringe_a_uma_turma``,
``test_t2_tudo_com_leitura_restringe`` e
``test_c1_merito_de_ativo_desvinculado_imprime_posicao_congelada``), que falhavam
no 34f1a23 e no c5e78d3:

1. ``/ranking/leitura?periodo=tudo`` sem filtro de turma só mostrava UMA turma
   quando havia ao menos uma leitura itemizada: o laço das leituras reusava o
   nome ``turma_id`` do parâmetro da rota, e o filtro do total do Elefante
   passava a recortar pela turma da última leitura do laço.
2. O certificado de Mérito de uma criança ATIVA que perdeu a matrícula do ano
   imprimia a posição CONGELADA da Nota antiga — a mesma posição que o ranking
   vigente dá a outra criança.
"""
from datetime import datetime

from sqlalchemy import select

from app.models import (Aluno, Importacao, Leitura, Livro, Matricula, Nota,
                        SnapshotElefante, SnapshotMatific, Turma)
from app.services import scoring

API = "/api/v1"
RECENTE = datetime(2026, 10, 19, 10, 54)


def _imp(db, escola_id):
    imp = Importacao(escola_id=escola_id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    return imp


def _turma(db, escola, nome, rotulo):
    t = Turma(escola_id=escola.id, nome=nome, ano_escolar=rotulo,
              ano_letivo=escola.ano_letivo_ativo, status="ativa")
    db.add(t)
    db.flush()
    return t


def _aluno(db, escola, turma, nome):
    a = Aluno(escola_id=escola.id, nome=nome, status="ativo", da_lista_piloto=True)
    db.add(a)
    db.flush()
    if turma is not None:
        db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id,
                         ano_letivo=escola.ano_letivo_ativo))
        db.flush()
    return a


def _snap(db, escola, imp, aluno, livros, atividades, quando=RECENTE):
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                            data_referencia=quando, livros_unicos=livros,
                            livros_por_nivel={"D": livros}, tempo_leitura_min=livros * 7,
                            questoes_tentativas=livros * 3, questoes_acertos=livros * 2))
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                           data_referencia=quando, atividades=atividades,
                           estrelas=atividades * 2, pontuacao_media=3.5))


def _cenario_tres_turmas(db, escola_completa):
    """3º Ano (fixture) + 4º e 5º Ano, todos com retrato; só uma criança do 3º
    Ano tem leitura ITEMIZADA (a condição que disparava o defeito)."""
    escola = escola_completa["escola"]
    t3 = escola_completa["turma"]
    imp = _imp(db, escola.id)
    t4 = _turma(db, escola, "4º Ano B", "4º Ano")
    t5 = _turma(db, escola, "5º Ano C", "5º Ano")
    a3 = escola_completa["alunos"][0]
    a4 = _aluno(db, escola, t4, "Crianca Ficticia Quatro")
    a5 = _aluno(db, escola, t5, "Crianca Ficticia Cinco")
    for aluno, livros in ((a3, 6), (a4, 9), (a5, 12)):
        _snap(db, escola, imp, aluno, livros, 10 * livros)
    livro = Livro(escola_id=escola.id, titulo="Livro Ficticio Unico", nivel_codigo="D")
    db.add(livro)
    db.flush()
    db.add(Leitura(escola_id=escola.id, aluno_id=a3.id, livro_id=livro.id,
                   data=datetime(2026, 10, 1, 10, 0), tempo_leitura_min=9))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    db.commit()
    return {"escola": escola, "t3": t3, "t4": t4, "t5": t5, "a3": a3, "a4": a4, "a5": a5}


# ---------------------------------------------------------------------------
# 1. "Todo o histórico" não restringe o agregado a uma turma
# ---------------------------------------------------------------------------
def test_leitura_todo_historico_sem_filtro_traz_todas_as_turmas(db, cliente, escola_completa):
    c = _cenario_tres_turmas(db, escola_completa)
    r = cliente.get(f"{API}/escolas/{c['escola'].id}/ranking/leitura?periodo=tudo")
    assert r.status_code == 200, r.text
    por_aluno = {i["aluno_id"]: i for i in r.json()}
    assert {c["a3"].id, c["a4"].id, c["a5"].id} <= set(por_aluno), \
        "o total do Elefante (retrato) de TODAS as turmas entra sem filtro de turma"
    # O agregado do retrato é o total autoritativo (o maior entre retrato e itens).
    assert por_aluno[c["a5"].id]["livros"] == 12
    assert por_aluno[c["a4"].id]["livros"] == 9
    assert por_aluno[c["a3"].id]["livros"] == 6
    assert [i["aluno_id"] for i in r.json()][:3] == [c["a5"].id, c["a4"].id, c["a3"].id]


def test_leitura_todo_historico_com_filtro_de_turma_continua_recortando(db, cliente,
                                                                       escola_completa):
    c = _cenario_tres_turmas(db, escola_completa)
    eid = c["escola"].id
    r = cliente.get(f"{API}/escolas/{eid}/ranking/leitura?periodo=tudo&turma_id={c['t4'].id}")
    assert r.status_code == 200, r.text
    assert [i["aluno_id"] for i in r.json()] == [c["a4"].id]
    # A turma DA LEITURA (3º Ano) não pode virar filtro de ninguém.
    r = cliente.get(f"{API}/escolas/{eid}/ranking/leitura?periodo=tudo&turma_id={c['t3'].id}")
    ids = {i["aluno_id"] for i in r.json()}
    assert c["a3"].id in ids and not ({c["a4"].id, c["a5"].id} & ids)


# ---------------------------------------------------------------------------
# 2. Mérito não imprime posição congelada
# ---------------------------------------------------------------------------
def _capturar_certificado(monkeypatch):
    from app.routers import relatorios as rel
    capturado: dict = {}

    def _falso(**kw):
        capturado.update(kw)
        return b"%PDF-ficticio"
    monkeypatch.setattr(rel.svc, "gerar_certificado", _falso)
    return capturado


def test_merito_de_ativo_sem_matricula_no_ano_e_recusado(db, cliente, escola_completa,
                                                         monkeypatch):
    c = _cenario_tres_turmas(db, escola_completa)
    eid = c["escola"].id
    alvo = c["a5"]
    pos_antes = db.execute(select(Nota.posicao).where(Nota.aluno_id == alvo.id)).scalar_one()
    assert pos_antes == 1
    for m in db.execute(select(Matricula).where(Matricula.aluno_id == alvo.id)).scalars():
        db.delete(m)
    db.commit()
    scoring.recalcular_escola(db, eid)
    db.commit()
    vigentes = sorted(i["posicao"] for i in cliente.get(f"{API}/escolas/{eid}/ranking").json())
    assert pos_antes in vigentes, "a posição congelada já pertence a outra criança"
    capturado = _capturar_certificado(monkeypatch)

    r = cliente.get(f"{API}/escolas/{eid}/certificados/{alvo.id}")
    assert r.status_code == 409, r.text
    assert "matrícula" in r.text and str(c["escola"].ano_letivo_ativo) in r.text
    assert capturado == {}, "nenhum PDF de Mérito foi montado"


def test_merito_de_turma_sem_serie_reconhecida_e_recusado(db, cliente, escola_completa,
                                                          monkeypatch):
    """Turma com rótulo em branco não concorre (o motor a tira da população):
    a Nota dela também é antiga."""
    escola = escola_completa["escola"]
    sem_serie = _turma(db, escola, "Turma Sem Serie", "")
    a = _aluno(db, escola, sem_serie, "Crianca Ficticia Sem Serie")
    db.add(Nota(escola_id=escola.id, aluno_id=a.id, ano_letivo=escola.ano_letivo_ativo,
                nota_geral=70.0, nota_elefante=70.0, nota_matific=70.0,
                aferido_leitura=True, aferido_matematica=True, posicao=1))
    db.commit()
    capturado = _capturar_certificado(monkeypatch)
    r = cliente.get(f"{API}/escolas/{escola.id}/certificados/{a.id}")
    assert r.status_code == 409, r.text
    assert capturado == {}


def test_merito_de_quem_concorre_sai_com_a_posicao_vigente(db, cliente, escola_completa,
                                                           monkeypatch):
    c = _cenario_tres_turmas(db, escola_completa)
    eid = c["escola"].id
    ranking = {i["aluno_id"]: i for i in cliente.get(f"{API}/escolas/{eid}/ranking").json()}
    capturado = _capturar_certificado(monkeypatch)
    r = cliente.get(f"{API}/escolas/{eid}/certificados/{c['a4'].id}")
    assert r.status_code == 200, r.text
    assert capturado["posicao"] == ranking[c["a4"].id]["posicao"]


def test_arte_de_participacao_sem_matricula_continua_saindo(db, cliente, escola_completa,
                                                           monkeypatch):
    """Contrato antigo preservado (``test_certificado_plataforma``): a arte da
    plataforma não imprime nota nem posição, então a guarda nova não vale nela."""
    from app.routers import relatorios as rel
    escola = escola_completa["escola"]
    a = _aluno(db, escola, None, "Crianca Ficticia Sem Matricula")
    db.commit()
    monkeypatch.setattr(rel.svc, "gerar_certificado_plataforma",
                        lambda *a_, **k: b"%PDF-arte")
    r = cliente.get(f"{API}/escolas/{escola.id}/certificados/{a.id}?modelo=elefante")
    assert r.status_code == 200, r.text
