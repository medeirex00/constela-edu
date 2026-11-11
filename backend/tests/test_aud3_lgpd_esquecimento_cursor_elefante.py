"""Exclusão permanente (LGPD): o id da conta da criança no Elefante sai também do
cursor da sincronização incremental — e, com ele, do arquivo de backup (S_G_LGPD-2).

O DEFEITO. O cursor do incremental do Elefante fica em ``configuracoes`` (namespace
``sync_incremental``, chave ``elefante``) como ``{studentId: total de livros}``. A
exclusão apagava ``identidades_externas`` mas não tocava no cursor: o número da conta
da criança na plataforma (um pseudônimo, reidentificável por quem tem o painel do
Elefante da escola), com a quantidade de livros, ficava no banco para sempre e saía
em todo backup da escola. O RETENCAO-TECNICA §2.3 promete as identidades externas
apagadas, e o ``test_exclusao_alcance_total`` só procurava o nome e o id da ficha.

Dados 100% fictícios; sem rede (navegador falso do Elefante, conectores reais,
serviço real de sincronização).
"""
import json

from sqlalchemy import JSON, String, Text, select

from app.core.database import Base
from app.models import Aluno, Configuracao, IdentidadeExterna, Matricula
from app.services import exclusao_aluno
from app.sync import service
from tests._sync_nucleo_fakes import NavElefante, aluno_el, credencial, instalar, livro, rodar

API = "/api/v1"
NOME = "LIVIA FICTICIA ESQUECIDA DO CURSOR"
SID = 7700001
CID = 600002
LIVROS = [livro("Livro Ficticio Cursor Um", data="2026-03-10T10:00:00"),
          livro("Livro Ficticio Cursor Dois", data="2026-04-11T10:00:00"),
          livro("Livro Ficticio Cursor Tres", data="2026-05-12T10:00:00")]


def _turmas(ec):
    a, b, c = ec["alunos"]
    return {CID: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        aluno_el(9200001, a.nome, [livro("Livro Ficticio A", data="2026-04-01T10:00:00")]),
        aluno_el(9200002, b.nome, []), aluno_el(9200003, c.nome, []),
        aluno_el(SID, NOME, LIVROS)]}}


def _varrer(db, alvo: str):
    """(tabela, coluna) de TODA coluna de texto/JSON que contém ``alvo``."""
    achados = []
    for tabela in Base.metadata.sorted_tables:
        colunas = [c for c in tabela.columns if isinstance(c.type, (String, Text, JSON))]
        if not colunas:
            continue
        for linha in db.execute(select(*colunas)).all():
            for col, valor in zip(colunas, linha):
                texto = valor if isinstance(valor, str) else json.dumps(
                    valor, ensure_ascii=False, default=str)
                if valor is not None and alvo in texto:
                    achados.append((tabela.name, col.name))
    return achados


def _cursor(db, eid):
    db.expire_all()
    linha = db.execute(select(Configuracao).where(
        Configuracao.escola_id == eid, Configuracao.namespace == service._NS_INCREMENTAL,
        Configuracao.chave == "elefante")).scalar_one_or_none()
    return dict(linha.valor) if linha is not None else None


def test_o_namespace_do_cursor_e_o_da_sincronizacao():
    assert exclusao_aluno.NAMESPACE_CURSOR_DA_SINCRONIZACAO == service._NS_INCREMENTAL


def test_exclusao_tira_o_studentId_do_cursor_e_do_backup(
        db, escola_completa, cliente, cliente_global, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    credencial(db, eid, "elefante")
    instalar(monkeypatch, nav_elefante=NavElefante(_turmas(ec)))
    rodar(db, eid, "elefante")
    ids = db.execute(select(Aluno.id).where(Aluno.escola_id == eid, Aluno.nome == NOME)
                     ).scalars().all()
    assert len(ids) == 1
    antes = _cursor(db, eid)
    assert antes is not None and str(SID) in antes
    assert ("configuracoes", "valor") in _varrer(db, str(SID))

    r = cliente_global.post(f"{API}/escolas/{eid}/alunos/excluir-permanente",
                            json={"aluno_ids": ids, "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text

    db.expire_all()
    sobras = _varrer(db, str(SID))
    assert not sobras, (
        f"o id da conta da criança no Elefante ({SID}) sobrevive à exclusão: {sobras}")
    # O cursor das outras crianças fica como estava (o incremental delas segue).
    depois = _cursor(db, eid)
    assert depois == {k: v for k, v in antes.items() if k != str(SID)}
    backup = cliente.get(f"{API}/escolas/{eid}/backup")
    assert backup.status_code == 200, backup.text
    assert str(SID) not in json.dumps(backup.json()["tabelas"]["configuracoes"], default=str)


def test_exclusao_de_turma_com_alunos_tambem_tira_do_cursor(
        db, escola_completa, cliente_global, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    credencial(db, eid, "elefante")
    instalar(monkeypatch, nav_elefante=NavElefante(_turmas(ec)))
    rodar(db, eid, "elefante")
    turma_id = ec["turma"].id
    contas = dict(db.execute(
        select(IdentidadeExterna.aluno_id, IdentidadeExterna.id_externo)
        .join(Matricula, Matricula.aluno_id == IdentidadeExterna.aluno_id)
        .where(Matricula.turma_id == turma_id,
               IdentidadeExterna.plataforma == "elefante")).all())
    assert contas and set(contas.values()) <= set(_cursor(db, eid))
    r = cliente_global.delete(f"{API}/escolas/{eid}/turmas/{turma_id}?com_alunos=true")
    assert r.status_code == 200, r.text
    db.expire_all()
    assert not any(db.get(Aluno, aid) for aid in contas)
    assert not set(_cursor(db, eid) or {}) & set(contas.values())
