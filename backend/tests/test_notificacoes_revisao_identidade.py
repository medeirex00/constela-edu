"""Sino × fila de revisão de identidade.

As pendências de identidade (correspondência insegura, linha sem aluno vinculado)
viram aviso no sino. Antes o aviso abria /alunos ou /importacoes — nunca a tela
onde a pendência se resolve, /revisoes-identidade. Agora:

* a pendência gravada NA FILA (a auditoria traz o ``revisao_id``) aponta para
  /revisoes-identidade; a da Lista Piloto, que não vai para a fila (o gestor
  resolve em Alunos › Fundir duplicatas), segue em /alunos;
* quem não abre a fila (o professor: a guarda RotaEscolaOp o manda de volta à
  página inicial; o backend responde 403 em ``/importacoes/revisoes``) recebe o
  aviso do aluno dele SEM o link.

Dados fictícios (fixture escola_completa).
"""
from sqlalchemy import select

from app.models import Notificacao
from app.services import audit
from tests.test_notificacoes import _cenario, _login


def _rotas(db, escola_id, tipo):
    return [n.rota for n in db.execute(select(Notificacao).where(
        Notificacao.escola_id == escola_id, Notificacao.tipo == tipo)).scalars()]


def test_linha_sem_vinculo_da_importacao_leva_as_revisoes(cliente, db, escola_completa):
    """Caminho real: a importação grava as linhas na fila e o aviso aponta para ela."""
    escola = escola_completa["escola"]
    r = cliente.post(f"/api/v1/escolas/{escola.id}/importacoes/confirmar", json={
        "plataforma": "elefante", "formato": "resumo", "tipo": "texto",
        "permitir_criar_turma": False,
        "linhas": [{"nome": "Fulano Sem Vinculo Ficticio", "dados": {"livros_unicos": 4}}]})
    assert r.status_code == 200, r.text
    assert r.json()["qtd_revisoes"] == 1
    assert _rotas(db, escola.id, "importacao.linha_ignorada") == ["/revisoes-identidade"]


def test_correspondencia_insegura_na_fila_leva_as_revisoes_e_a_da_lista_piloto_a_alunos(
        db, escola_completa):
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    audit.registrar(db, "aluno.revisao_necessaria", escola_id=escola.id,
                    entidade="aluno", entidade_id=aluno.id,
                    detalhes={"decisao": "REVIEW_REQUIRED", "revisao_id": 41})
    audit.registrar(db, "aluno.revisao_necessaria", escola_id=escola.id,
                    entidade="aluno", entidade_id=aluno.id,
                    detalhes={"decisao": "REVIEW_REQUIRED", "fonte": "importacao_matriculas"})
    db.commit()
    assert _rotas(db, escola.id, "aluno.revisao_necessaria") == [
        "/revisoes-identidade", "/alunos"]


def test_professor_recebe_o_aviso_sem_o_link_e_a_gestao_com_o_link(db, escola_completa):
    ids = _cenario(db, escola_completa)
    for acao in ("aluno.revisao_necessaria", "importacao.linha_ignorada"):
        audit.registrar(db, acao, escola_id=ids["escola"], entidade="aluno",
                        entidade_id=ids["aluno_prof"],
                        detalhes={"decisao": "REVIEW_REQUIRED", "revisao_id": 7})
    db.commit()

    gestao = {n["tipo"]: n["rota"]
              for n in _login("admin@teste.local").get("/api/v1/notificacoes").json()}
    assert gestao == {"aluno.revisao_necessaria": "/revisoes-identidade",
                      "importacao.linha_ignorada": "/revisoes-identidade"}

    prof = {n["tipo"]: n["rota"]
            for n in _login("prof@notif.local").get("/api/v1/notificacoes").json()}
    # O aviso do aluno dele continua chegando — só sem o link que o expulsaria.
    assert prof == {"aluno.revisao_necessaria": None, "importacao.linha_ignorada": None}


def test_ficha_criada_pela_fila_avisa_com_o_link_da_ficha(cliente, db, escola_completa):
    """"Criar novo aluno" na fila registra ``aluno.criado`` com o ``revisao_id`` (a
    origem). O aviso "Novo aluno cadastrado" leva à ficha nova — não à lista de
    pendências, onde essa revisão já resolvida nem aparece (e que a professora da turma
    não abre: ela ficava sem link para a ficha da criança dela)."""
    from app.services import politica_sync
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    politica_sync.definir(db, escola.id, "bloquear")     # a linha sem ficha vai para a fila
    db.commit()
    r = cliente.post(f"/api/v1/escolas/{escola.id}/importacoes/confirmar", json={
        "plataforma": "elefante", "formato": "resumo", "tipo": "texto", "recalcular": False,
        "linhas": [{"nome": "Crianca Ficticia Da Fila", "criar_em_turma_id": turma.id,
                    "dados": {"elefante_student_id": "81004", "livros_unicos": 2}}]})
    assert r.status_code == 200, r.text
    assert r.json()["qtd_revisoes"] == 1
    [rev] = cliente.get(f"/api/v1/escolas/{escola.id}/importacoes/revisoes").json()
    r = cliente.post(f"/api/v1/escolas/{escola.id}/importacoes/revisoes/{rev['id']}/resolver",
                     json={"criar_em_turma_id": turma.id})
    assert r.status_code == 200, r.text
    novo = r.json()["aluno_id"]
    db.expire_all()
    assert _rotas(db, escola.id, "aluno.criado") == [f"/alunos/{novo}"]
    # A pendência que abriu a fila continua levando às Revisões.
    assert set(_rotas(db, escola.id, "aluno.revisao_necessaria")
               + _rotas(db, escola.id, "importacao.linha_ignorada")) == {"/revisoes-identidade"}


def test_professor_nao_recebe_link_antigo_para_importacoes(db, escola_completa):
    """Aviso gravado antes (rota /importacoes, que o professor também não abre)."""
    ids = _cenario(db, escola_completa)
    audit.registrar(db, "importacao.linha_ignorada", escola_id=ids["escola"],
                    entidade="aluno", entidade_id=ids["aluno_prof"])
    db.commit()
    assert _rotas(db, ids["escola"], "importacao.linha_ignorada") == ["/importacoes"]
    feed = _login("prof@notif.local").get("/api/v1/notificacoes").json()
    assert [(n["tipo"], n["rota"]) for n in feed] == [("importacao.linha_ignorada", None)]
    # A gestão continua com o link de antes.
    feed_admin = _login("admin@teste.local").get("/api/v1/notificacoes").json()
    assert [n["rota"] for n in feed_admin] == ["/importacoes"]
