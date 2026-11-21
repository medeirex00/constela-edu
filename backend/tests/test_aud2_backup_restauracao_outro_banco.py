"""REV2-BACKUP-1 (G_LGPD-4) — a restauração só religa a fila de revisões à linha que o
arquivo PROVA ser a mesma, não à que só tem o mesmo número.

A restauração reaponta o que fica FORA do arquivo (a memória da decisão humana
``aluno_escolhido_id``, os candidatos das pendências, ``turma_id`` e ``importacao_id``
das revisões, ``importacao_id`` das execuções da sincronização) para a linha recriada:
id de hoje -> ``_id`` do arquivo -> id novo. A premissa "o mesmo id é a mesma linha"
só vale para o arquivo do MESMO banco. O arquivo levado para outro banco (caso que o
próprio módulo contempla em ``REFERENCIAS_A_USUARIO``), ou a recuperação de desastre com
um pg_dump antigo e um JSON mais novo, traz ``_id`` que coincidem com ids de OUTRAS
crianças daqui: a memória "a conta U é a Ana" passava a apontar para o Bruno do outro
banco, e a coleta seguinte associava a conta da Ana à ficha do Bruno pela via
"revisao". O mesmo valia no SQLite de desenvolvimento, que reaproveita o id da linha
apagada depois do arquivo.

O certo: a linha do arquivo só é a mesma quando também tem o mesmo ``created_at`` (que
sai no arquivo e a restauração repõe como veio). Sem essa prova o vínculo fica NULL e a
candidata sai da lista, contado em ``sem_equivalente`` — o seguro, como antes de
reapontar. ``test_aud2_backup_restauracao_revisoes.py`` prova que o arquivo do mesmo
banco continua reapontando (memória D10, linhagem, candidatos). A variante em
PostgreSQL está em ``test_aud2_backup_restauracao_outro_banco_pg.py``.

Dados 100% fictícios (escolas e crianças inventadas); sem rede.
"""
import json
from datetime import datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import (
    Aluno,
    Escola,
    Importacao,
    LogAuditoria,
    Matricula,
    RevisaoIdentidade,
    SincronizacaoExecucao,
    Turma,
)
from app.services import backup as svc_backup
from app.services import identidade_aluno as ida

U = "u-ficticia-rev2-outro-banco"
ANA, DAVI = "Ana Ficticia Rev2 Destino", "Davi Ficticio Rev2 Destino"
BRUNO, CARLA = "Bruno Ficticio Rev2 Outro Banco", "Carla Ficticia Rev2 Outro Banco"
TURMA = "3º Ano A"
# Quando cada linha nasceu (explícito para o teste não depender do relógio): as do
# outro banco e as daqui nasceram em momentos diferentes, como na vida real.
NASCEU_NO_OUTRO_BANCO = datetime(2025, 3, 10, 8, 0, 0)
NASCEU_AQUI = datetime(2026, 2, 2, 9, 30, 0)


def _povoar(db, nome_escola, criancas, criado_em):
    """Escola com uma turma, uma importação e as ``criancas`` matriculadas, nesta
    ordem (os ids saem 1, 2, ... num banco novo)."""
    escola = Escola(nome=nome_escola, ano_letivo_ativo=2026)
    db.add(escola)
    db.flush()
    turma = Turma(escola_id=escola.id, nome=TURMA, ano_escolar="3º Ano", ano_letivo=2026,
                  created_at=criado_em)
    imp = Importacao(escola_id=escola.id, plataforma="matific", tipo="texto",
                     created_at=criado_em)
    db.add_all([turma, imp])
    db.flush()
    fichas = []
    for nome in criancas:
        ficha = Aluno(escola_id=escola.id, nome=nome, created_at=criado_em)
        db.add(ficha)
        db.flush()
        db.add(Matricula(escola_id=escola.id, aluno_id=ficha.id, turma_id=turma.id,
                         ano_letivo=2026))
        fichas.append(ficha)
    db.commit()
    return escola, turma, imp, fichas


def _arquivo_de_outro_banco() -> dict:
    """O backup de uma escola exportado num banco À PARTE (SQLite em memória): a
    turma, a importação e as fichas dele têm os mesmos ids das daqui, mas são outras."""
    import app.quest.models  # noqa: F401  (o metadata completo, como no app)

    outro = create_engine("sqlite://", poolclass=StaticPool,
                          connect_args={"check_same_thread": False})
    Base.metadata.create_all(outro)
    try:
        with Session(outro) as db2:
            escola, _t, _i, _f = _povoar(db2, "ESCOLA FICTICIA REV2 OUTRO BANCO",
                                         (BRUNO, CARLA), NASCEU_NO_OUTRO_BANCO)
            # Como o arquivo baixado: JSON de verdade.
            return json.loads(json.dumps(svc_backup.exportar(db2, escola.id)))
    finally:
        outro.dispose()


def test_arquivo_de_outro_banco_nao_religa_a_fila_a_outras_criancas(db):
    arquivo = _arquivo_de_outro_banco()
    ids_no_arquivo = {linha["_id"] for linha in arquivo["tabelas"]["alunos"]}

    escola, turma, imp, (ana, davi) = _povoar(db, "ESCOLA FICTICIA REV2 DESTINO",
                                              (ANA, DAVI), NASCEU_AQUI)
    eid = escola.id
    # A premissa da prova: os números do arquivo são os das crianças daqui.
    assert {ana.id, davi.id} == ids_no_arquivo
    chave = ida.chave_identidade_da_conta("matific", U)
    resolvida = RevisaoIdentidade(
        escola_id=eid, chave="rev2-k1", chave_identidade=chave, plataforma="matific",
        id_externo=U, nome_recebido=ANA, motivo="identidade", status="resolvida",
        aluno_escolhido_id=ana.id, turma_id=turma.id, importacao_id=imp.id,
        candidatos=[{"aluno_id": ana.id, "nome": ANA, "status": "ativo", "turma": TURMA}],
        resolucao={"acao": "associar", "aluno_id": ana.id, "automatica": False})
    pendente = RevisaoIdentidade(
        escola_id=eid, chave="rev2-k2", chave_identidade="rev2-ci2", plataforma="matific",
        id_externo="u-ficticia-rev2-outra", nome_recebido="Davi F.", motivo="homonimo",
        turma_id=turma.id, importacao_id=imp.id,
        candidatos=[{"aluno_id": davi.id, "nome": DAVI, "status": "ativo", "turma": TURMA}])
    execucao = SincronizacaoExecucao(escola_id=eid, plataforma="matific", origem="manual",
                                     status="concluida", importacao_id=imp.id)
    db.add_all([resolvida, pendente, execucao])
    db.commit()
    rid, pid, xid = resolvida.id, pendente.id, execucao.id

    reapontadas: dict = {}
    db.expunge_all()    # a restauração chega numa sessão nova, como na rota
    svc_backup.restaurar(db, eid, arquivo, reapontadas=reapontadas)
    db.commit()
    db.expire_all()

    vivas = {a.id: a.nome for a in db.execute(
        select(Aluno).where(Aluno.escola_id == eid)).scalars()}
    assert sorted(vivas.values()) == [BRUNO, CARLA]
    r = db.get(RevisaoIdentidade, rid)
    assert r.aluno_escolhido_id is None, (
        "a memória 'a conta U é a Ana' passou a apontar para OUTRA criança: "
        f"{vivas.get(r.aluno_escolhido_id)}")
    assert r.candidatos == []
    assert (r.turma_id, r.importacao_id) == (None, None), (
        "a decisão passou a citar a turma e a importação de outro banco")
    p = db.get(RevisaoIdentidade, pid)
    assert p.candidatos == [], (
        "a pendência passou a oferecer uma criança de outro banco no lugar do Davi: "
        f"{[vivas.get(c.get('aluno_id')) for c in p.candidatos]}")
    assert (p.turma_id, p.importacao_id) == (None, None)
    assert db.get(SincronizacaoExecucao, xid).importacao_id is None, (
        "a execução da sincronização passou a citar a importação de outro banco")
    assert reapontadas == {
        "revisoes_identidade.aluno_escolhido_id": {"reapontadas": 0, "sem_equivalente": 1},
        "revisoes_identidade.importacao_id": {"reapontadas": 0, "sem_equivalente": 2},
        "revisoes_identidade.turma_id": {"reapontadas": 0, "sem_equivalente": 2},
        "sincronizacao_execucoes.importacao_id": {"reapontadas": 0, "sem_equivalente": 1},
        "revisoes_identidade.candidatos": {"reapontadas": 0, "sem_equivalente": 2},
    }

    # A coleta seguinte traz a conta U com o nome da Ana: nenhuma ficha daqui é a Ana,
    # então o motor não pode associá-la a ninguém — muito menos pela memória da decisão.
    ctx = ida.carregar_contexto(db, eid)
    assert chave not in ctx.resolvidas
    decisao = ida.decidir(ctx, ida.LinhaIdentidade(
        nome=ANA, plataforma="matific", id_externo=U, turma_nome=TURMA))
    assert decisao.acao != ida.ASSOCIAR, (
        f"a conta da Ana foi associada a {vivas.get(decisao.aluno_id)} (via {decisao.via})")


def test_linhagem_com_numeros_de_outro_banco_nao_religa_a_outra_crianca(db):
    """A linhagem mistura números de bancos diferentes: a ficha daqui que veio de um
    arquivo de OUTRO banco (restaurado antes) fica ligada, no log, ao ``_id`` que ela
    tinha lá. Um arquivo de um terceiro banco com esse mesmo número, de outra criança,
    não pode herdar a decisão humana sobre ela."""
    arquivo = _arquivo_de_outro_banco()
    # Duas fichas de outra escola só para a Ana daqui não ter o número 1 nem o 2.
    outra = Escola(nome="ESCOLA FICTICIA REV2 OCUPA", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    db.add_all([Aluno(escola_id=outra.id, nome=f"Crianca Ficticia Rev2 Ocupa {n}")
                for n in (1, 2)])
    db.commit()
    escola, _turma, _imp, (ana,) = _povoar(db, "ESCOLA FICTICIA REV2 LINHAGEM", (ANA,),
                                           NASCEU_AQUI)
    eid, ana_id = escola.id, ana.id
    ids_no_arquivo = {linha["_id"] for linha in arquivo["tabelas"]["alunos"]}
    assert ana_id not in ids_no_arquivo
    # A Ana chegou aqui por uma restauração anterior, de um arquivo em que era o nº 1.
    db.add(LogAuditoria(acao="backup.restaurado", escola_id=eid, detalhes={
        svc_backup.CHAVE_MAPA_ALUNOS: {str(ana_id): 1}}))
    rev = RevisaoIdentidade(
        escola_id=eid, chave="rev2-k4", chave_identidade="rev2-ci4", plataforma="matific",
        id_externo="u-ficticia-rev2-linhagem", nome_recebido=ANA, motivo="identidade",
        status="resolvida", aluno_escolhido_id=ana_id,
        candidatos=[{"aluno_id": ana_id, "nome": ANA}],
        resolucao={"acao": "associar", "aluno_id": ana_id, "automatica": False})
    db.add(rev)
    db.commit()
    rev_id = rev.id

    db.expunge_all()    # a restauração chega numa sessão nova, como na rota
    svc_backup.restaurar(db, eid, arquivo)
    db.commit()
    db.expire_all()
    rev = db.get(RevisaoIdentidade, rev_id)
    escolhida = db.get(Aluno, rev.aluno_escolhido_id) if rev.aluno_escolhido_id else None
    assert escolhida is None, (
        f"a decisão sobre a Ana passou para {escolhida.nome}, pela linhagem de outro banco")
    assert rev.candidatos == []


def test_sqlite_linha_recriada_depois_do_arquivo_com_o_mesmo_id_nao_e_a_do_arquivo(db):
    """O SQLite de desenvolvimento reaproveita o id da linha apagada: a ficha apagada
    depois do arquivo e a ficha nova que ganhou o mesmo número são crianças diferentes.
    A decisão sobre a ficha nova não pode passar para a do arquivo."""
    if db.get_bind().dialect.name != "sqlite":
        pytest.skip("só o SQLite reaproveita o id da linha apagada")
    escola, _turma, _imp, (antiga,) = _povoar(db, "ESCOLA FICTICIA REV2 REUSO",
                                              ("Elisa Ficticia Rev2 Antiga",),
                                              NASCEU_NO_OUTRO_BANCO)
    eid, id_antigo = escola.id, antiga.id
    arquivo = json.loads(json.dumps(svc_backup.exportar(db, eid)))

    db.execute(Matricula.__table__.delete().where(Matricula.aluno_id == id_antigo))
    db.delete(antiga)
    db.commit()
    nova = Aluno(escola_id=eid, nome="Fabio Ficticio Rev2 Novo", created_at=NASCEU_AQUI)
    db.add(nova)
    db.commit()
    assert nova.id == id_antigo     # o SQLite reaproveitou o número
    rev = RevisaoIdentidade(
        escola_id=eid, chave="rev2-k3", chave_identidade="rev2-ci3", plataforma="matific",
        id_externo="u-ficticia-rev2-reuso", nome_recebido="Fabio Ficticio Rev2 Novo",
        motivo="identidade", status="resolvida", aluno_escolhido_id=nova.id,
        candidatos=[{"aluno_id": nova.id, "nome": "Fabio Ficticio Rev2 Novo"}],
        resolucao={"acao": "associar", "aluno_id": nova.id, "automatica": False})
    db.add(rev)
    db.commit()
    rev_id = rev.id

    db.expunge_all()    # a restauração chega numa sessão nova, como na rota
    svc_backup.restaurar(db, eid, arquivo)
    db.commit()
    db.expire_all()
    [volta] = db.execute(select(Aluno).where(Aluno.escola_id == eid)).scalars().all()
    assert volta.nome == "Elisa Ficticia Rev2 Antiga"
    rev = db.get(RevisaoIdentidade, rev_id)
    assert rev.aluno_escolhido_id is None, (
        "a decisão sobre o Fabio passou para a Elisa, que só tinha o mesmo número")
    assert rev.candidatos == []


def test_toda_tabela_reapontada_tem_a_prova_da_mesma_linha():
    """A prova (``PROVA_DA_MESMA_LINHA``) precisa existir em toda tabela do arquivo a que
    alguém de fora aponta: sem a coluna, a restauração não religaria nada nela (o seguro,
    mas a decisão humana da fila voltaria a se perder, o G_LGPD-4)."""
    import app.models  # noqa: F401  (popula o metadata)
    import app.quest.models  # noqa: F401

    alvos = {alvo for _t, _c, alvo in svc_backup._referencias_de_fora(Base.metadata)}
    alvos |= {"alunos"}       # os candidatos das revisões (JSON)
    sem_prova = sorted(alvo for alvo in alvos
                       if svc_backup.PROVA_DA_MESMA_LINHA not in Base.metadata.tables[alvo].c)
    assert not sem_prova, sem_prova
    assert alvos <= set(svc_backup.CHAVES_DE_LINHAGEM)
