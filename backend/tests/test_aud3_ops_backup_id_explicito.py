"""EXTRA-BACKUP-ID-EXPLICITO — a restauração ignora ``id`` e ``escola_id`` vindos
dentro das linhas do arquivo.

O backup sai sem essas colunas (``backup.IGNORADAS``): a restauração recria o id e põe
a escola de destino. Mas ``restaurar`` montava os campos com toda coluna do modelo
menos ``_id``, então um arquivo com ``"id": 4242`` numa linha gravava a linha com o id
4242. No PostgreSQL esse INSERT com id explícito não avança a sequência: mais tarde
outra inserção, de qualquer escola, recebia o mesmo número e caía com
``IntegrityError`` (``test_aud3_ops_backup_id_explicito_pg.py``). E ``"escola_id"``
na linha chegava duas vezes ao construtor do modelo (``TypeError``: erro interno).

Dados INVENTADOS; o arquivo é o do próprio export, só com o campo a mais.
"""
import json

from sqlalchemy import func, select

from app.models import Aluno, Escola
from app.services import backup as svc_backup

ID_DO_ARQUIVO = 4242


def _arquivo(db, escola_id):
    db.expire_all()
    return json.loads(json.dumps(svc_backup.exportar(db, escola_id), default=str))


def _alunos(db, escola_id):
    db.expire_all()
    return db.execute(select(Aluno).where(Aluno.escola_id == escola_id)
                      .order_by(Aluno.nome)).scalars().all()


def test_id_dentro_da_linha_do_arquivo_e_ignorado(db, escola_completa):
    eid = escola_completa["escola"].id
    dados = _arquivo(db, eid)
    antes = sorted(a["nome"] for a in dados["tabelas"]["alunos"])
    dados["tabelas"]["alunos"][0]["id"] = ID_DO_ARQUIVO

    contagem = svc_backup.restaurar(db, eid, dados)
    db.commit()

    assert contagem["alunos"] == len(antes)
    assert sorted(a.nome for a in _alunos(db, eid)) == antes
    # O id vem do banco (sequência), nunca do arquivo.
    assert db.get(Aluno, ID_DO_ARQUIVO) is None


def test_escola_id_dentro_da_linha_do_arquivo_e_ignorado(db, escola_completa):
    eid = escola_completa["escola"].id
    outra = Escola(nome="EMEF Fictícia Outra do Backup", ano_letivo_ativo=2026)
    db.add(outra)
    db.commit()
    dados = _arquivo(db, eid)
    n = len(dados["tabelas"]["alunos"])
    dados["tabelas"]["alunos"][0]["escola_id"] = outra.id

    contagem = svc_backup.restaurar(db, eid, dados)      # antes: TypeError (500)
    db.commit()

    assert contagem["alunos"] == n
    assert len(_alunos(db, eid)) == n                      # tudo na escola de destino
    assert db.execute(select(func.count()).select_from(Aluno)
                      .where(Aluno.escola_id == outra.id)).scalar_one() == 0
