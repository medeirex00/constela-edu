"""Exclusão permanente (LGPD) × a coleta seguinte da plataforma (G_LGPD-1).

O DEFEITO. O Admin Global atende o pedido de esquecimento ("Excluir para sempre"),
mas a conta da criança continua no Matific (a escola não a encerra na hora). A
exclusão apagava as identidades externas sem deixar memória de que aquela conta era
de uma criança esquecida. Na coleta seguinte, a porta única de identidade
(``identidade_aluno.decidir``) via uma conta desconhecida: com a política padrão
("permitir") a ficha voltava inteira — nome, conta, retrato, ranking — e o log
gravava o nome de novo (``aluno.criado_auto``); com "bloquear", o nome voltava para
a fila de revisões e para o log (``aluno.revisao_necessaria``).

O CONSERTO. A exclusão permanente grava no ``aluno.excluido_permanente`` de cada
criança a marca das contas dela (plataforma + HMAC do id externo com a chave do
servidor — sem nome nem id em claro): as vinculadas à ficha e as das revisões dela
(a segunda conta que a coleta mandou para a fila). ``decidir`` ignora a linha de
conta marcada antes de qualquer passo, com o motivo ``conta_esquecida``.

Base: a sonda do auditor (``test_sonda_exclusao_e_coleta_seguinte.py``). Dados 100%
fictícios; sem rede (o núcleo do /confirmar com os parâmetros da sync).
"""
import json
import re
from dataclasses import replace

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models import (Aluno, Escola, IdentidadeExterna, Matricula, Notificacao,
                        RevisaoIdentidade, SnapshotMatific, Turma)
from app.models.nota import LogAuditoria
from app.routers.importacoes import _confirmar_sem_commit
from app.schemas.importacao import ImportacaoConfirm, LinhaConfirmacao
from app.services import exclusao_aluno, politica_sync
from app.services import identidade_aluno as ida

API = "/api/v1"
NOME = "QUITERIA ESQUECIDA FICTICIA"
CONTA = "uuid-ficticio-esquecida-9001"
OUTRA_CONTA = "uuid-ficticio-esquecida-9002"


def _linha(nome, conta, turma_nome, atividades=5):
    return LinhaConfirmacao(nome=nome, criar_em_turma_nome=turma_nome, dados={
        "matific_uuid": conta, "turma_relatorio": turma_nome,
        "atividades": atividades, "estrelas": 12, "pontuacao_media": 80})


def _coleta(db, escola, admin, linhas):
    """A mesma chamada que ``sync/orchestrator`` faz ao /confirmar (sync=True,
    nunca cria turma, ``permitir_criar_aluno`` = política da escola)."""
    corpo = ImportacaoConfirm(
        plataforma="matific", formato="resumo", tipo="texto", linhas=linhas,
        recalcular=False, sincronizar_turma=True, permitir_criar_turma=False,
        permitir_criar_aluno=politica_sync.pode_criar_aluno(db, escola.id))
    r = _confirmar_sem_commit(dados=corpo, escola_id=escola.id, usuario=admin, db=db)
    db.commit()
    return r


def _rastros(db, eid, nome=NOME):
    db.expire_all()
    fichas = db.execute(select(Aluno.id).where(Aluno.escola_id == eid,
                                               Aluno.nome == nome)).scalars().all()
    contas = db.execute(select(IdentidadeExterna.id_externo).where(
        IdentidadeExterna.escola_id == eid,
        IdentidadeExterna.id_externo.in_([CONTA, OUTRA_CONTA]))).scalars().all()
    snaps = db.execute(select(func.count()).select_from(SnapshotMatific).where(
        SnapshotMatific.aluno_id.in_(fichas or [-1]))).scalar_one()
    revs = [r.id for r in db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == eid)).scalars()
        if nome in json.dumps({"n": r.nome_recebido, "l": r.linhas, "c": r.contexto,
                               "k": r.candidatos}, ensure_ascii=False, default=str)]
    logs = [(lg.id, lg.acao) for lg in db.execute(select(LogAuditoria)).scalars()
            if nome in json.dumps(lg.detalhes or {}, ensure_ascii=False, default=str)]
    avisos = [n.id for n in db.execute(select(Notificacao).where(
        Notificacao.escola_id == eid)).scalars()
        if nome in (n.titulo or "")]
    return {"fichas": fichas, "contas": contas, "snapshots": snaps,
            "revisoes_com_nome": revs, "logs_com_nome": logs, "avisos_com_nome": avisos}


def _excluir(cliente_global, eid, aluno_id):
    r = cliente_global.post(f"{API}/escolas/{eid}/alunos/excluir-permanente",
                            json={"aluno_ids": [aluno_id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text


def _ficha_pela_coleta(db, escola_completa, conta=CONTA):
    escola, turma, admin = (escola_completa["escola"], escola_completa["turma"],
                            escola_completa["admin"])
    _coleta(db, escola, admin, [_linha(NOME, conta, turma.nome)])
    antes = _rastros(db, escola.id)
    assert len(antes["fichas"]) == 1 and antes["contas"] == [conta], antes
    return antes["fichas"][0]


@pytest.mark.parametrize("politica", ["permitir", "bloquear"])
def test_a_coleta_seguinte_nao_traz_de_volta_a_crianca_esquecida(
        db, escola_completa, cliente_global, politica):
    escola, turma, admin = (escola_completa["escola"], escola_completa["turma"],
                            escola_completa["admin"])
    aluno_id = _ficha_pela_coleta(db, escola_completa)
    if politica == "bloquear":
        politica_sync.definir(db, escola.id, "bloquear")
        db.commit()

    _excluir(cliente_global, escola.id, aluno_id)
    depois_exclusao = _rastros(db, escola.id)
    assert depois_exclusao == {"fichas": [], "contas": [], "snapshots": 0,
                               "revisoes_com_nome": [], "logs_com_nome": [],
                               "avisos_com_nome": []}, depois_exclusao

    # A plataforma manda a mesma conta, com o mesmo nome, na coleta seguinte.
    _coleta(db, escola, admin, [_linha(NOME, CONTA, turma.nome, atividades=9)])
    depois_coleta = _rastros(db, escola.id)
    print(f"\n[{politica}] depois da coleta seguinte: {depois_coleta}")
    assert depois_coleta["fichas"] == [], (
        f"[{politica}] a coleta seguinte recriou a ficha da criança esquecida: "
        f"{depois_coleta}")
    assert depois_coleta["contas"] == [] and depois_coleta["snapshots"] == 0
    assert depois_coleta["revisoes_com_nome"] == [], (
        f"[{politica}] o nome voltou para a fila de revisões: {depois_coleta}")
    assert depois_coleta["logs_com_nome"] == [], (
        f"[{politica}] o nome voltou para o log permanente: {depois_coleta}")
    assert depois_coleta["avisos_com_nome"] == []


def test_a_marca_nao_guarda_nome_nem_id_em_claro(db, escola_completa, cliente_global):
    eid = escola_completa["escola"].id
    aluno_id = _ficha_pela_coleta(db, escola_completa)
    _excluir(cliente_global, eid, aluno_id)
    db.expire_all()
    exclusao = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "aluno.excluido_permanente",
        LogAuditoria.entidade_id == aluno_id)).scalars().one()
    marcas = exclusao.detalhes["contas_esquecidas"]
    assert [m["plataforma"] for m in marcas] == ["matific"]
    assert all(re.fullmatch(r"[0-9a-f]{64}", m["marca"]) for m in marcas)
    assert exclusao.detalhes["tipo"] == "exclusao_permanente"
    # Nem o id externo nem o nome em claro, em entrada nenhuma do log.
    todos = json.dumps([lg.detalhes for lg in db.execute(select(LogAuditoria)).scalars()],
                       ensure_ascii=False, default=str)
    assert CONTA not in todos and NOME not in todos


def test_a_segunda_conta_que_estava_na_fila_tambem_e_esquecida(
        db, escola_completa, cliente_global):
    """A criança tinha duas contas no Matific: a coleta vinculou uma e mandou a
    outra para a fila (``outra_identidade_na_plataforma``). A exclusão apaga a
    pendência — e a outra conta não pode recriar a ficha na coleta seguinte."""
    escola, turma, admin = (escola_completa["escola"], escola_completa["turma"],
                            escola_completa["admin"])
    aluno_id = _ficha_pela_coleta(db, escola_completa)
    _coleta(db, escola, admin, [_linha(NOME, OUTRA_CONTA, turma.nome)])
    pendente = db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == escola.id,
        RevisaoIdentidade.id_externo == OUTRA_CONTA)).scalars().one()
    assert pendente.motivo == "outra_identidade_na_plataforma"

    _excluir(cliente_global, escola.id, aluno_id)
    exclusao = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "aluno.excluido_permanente")).scalars().one()
    assert len(exclusao.detalhes["contas_esquecidas"]) == 2

    _coleta(db, escola, admin, [_linha(NOME, OUTRA_CONTA, turma.nome),
                                _linha(NOME, CONTA, turma.nome)])
    depois = _rastros(db, escola.id)
    assert depois["fichas"] == [] and depois["contas"] == [], depois
    assert depois["revisoes_com_nome"] == [] and depois["logs_com_nome"] == [], depois


def test_conta_de_quem_continua_na_escola_nunca_e_marcada(db, escola_completa,
                                                          cliente_global):
    """A revisão resolvida para a excluída cita uma conta que hoje é de OUTRA
    criança (vinculada à ficha dela): marcá-la a apagaria das coletas."""
    escola, turma, admin = (escola_completa["escola"], escola_completa["turma"],
                            escola_completa["admin"])
    fica = escola_completa["alunos"][1]
    aluno_id = _ficha_pela_coleta(db, escola_completa)
    db.add(IdentidadeExterna(escola_id=escola.id, aluno_id=fica.id, plataforma="matific",
                             id_externo="uuid-ficticio-de-quem-fica"))
    db.add(RevisaoIdentidade(
        escola_id=escola.id, chave="k-teste", chave_identidade="ci-teste",
        plataforma="matific", id_externo="uuid-ficticio-de-quem-fica",
        nome_recebido=NOME, motivo="correspondencia_insegura", status="resolvida",
        aluno_escolhido_id=aluno_id))
    db.commit()

    _excluir(cliente_global, escola.id, aluno_id)
    exclusao = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "aluno.excluido_permanente")).scalars().one()
    assert len(exclusao.detalhes["contas_esquecidas"]) == 1   # só a dela

    _coleta(db, escola, admin, [_linha(fica.nome, "uuid-ficticio-de-quem-fica",
                                       turma.nome)])
    db.expire_all()
    assert db.execute(select(func.count()).select_from(SnapshotMatific).where(
        SnapshotMatific.aluno_id == fica.id)).scalar_one() == 1


def test_a_marca_vale_so_na_escola_que_excluiu(db, escola_completa, cliente_global):
    """Outra escola com a mesma conta vinculada (credencial que enxerga as duas,
    criança que mudou de escola) não perde a criança dela."""
    aluno_id = _ficha_pela_coleta(db, escola_completa)
    outra = Escola(nome="ESCOLA FICTICIA OUTRA", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    turma = Turma(escola_id=outra.id, nome="3º Ano A", ano_escolar="3º Ano", ano_letivo=2026)
    db.add(turma)
    db.flush()
    dela = Aluno(escola_id=outra.id, nome=NOME)
    db.add(dela)
    db.flush()
    db.add(Matricula(escola_id=outra.id, aluno_id=dela.id, turma_id=turma.id,
                     ano_letivo=2026))
    db.add(IdentidadeExterna(escola_id=outra.id, aluno_id=dela.id, plataforma="matific",
                             id_externo=CONTA))
    db.commit()
    _excluir(cliente_global, escola_completa["escola"].id, aluno_id)

    ctx = ida.carregar_contexto(db, outra.id)
    linha = ida.linha_de_dados(NOME, {"matific_uuid": CONTA}, plataforma="matific",
                               turma_nome="3º Ano A")
    decisao = ida.decidir(ctx, linha)
    assert (decisao.acao, decisao.aluno_id) == (ida.ASSOCIAR, dela.id)


def test_a_marca_continua_valendo_depois_da_troca_de_chave(db, escola_completa,
                                                           cliente_global, monkeypatch):
    """Rotação planejada: a chave nova grava, a anterior fica no anel e confere."""
    eid = escola_completa["escola"].id
    aluno_id = _ficha_pela_coleta(db, escola_completa)
    _excluir(cliente_global, eid, aluno_id)
    antiga = (settings.DATA_ENCRYPTION_KEY or "").strip()
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY",
                        "chave-nova-ficticia-de-teste-0123456789abcdef")
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEYS_ANTERIORES", antiga)
    ctx = ida.carregar_contexto(db, eid)
    linha = ida.linha_de_dados(NOME, {"matific_uuid": CONTA}, plataforma="matific",
                               turma_nome="3º Ano A")
    decisao = ida.decidir(ctx, linha)
    assert (decisao.acao, decisao.motivo) == (ida.IGNORAR, "conta_esquecida")


def test_decidir_ignora_a_conta_esquecida_antes_de_tudo(db, escola_completa):
    """Nem a escolha explícita de um humano associa a conta esquecida: com o
    vínculo, a coleta seguinte reabriria o que o esquecimento fechou. E o descarte
    é decisão já tomada (fora da pendência e da conta de defeitos)."""
    eid = escola_completa["escola"].id
    viva = escola_completa["alunos"][0]
    ctx = ida.carregar_contexto(db, eid)
    ctx.contas_esquecidas = {("matific", exclusao_aluno.marca_da_conta("matific", CONTA))}
    linha = ida.linha_de_dados(viva.nome, {"matific_uuid": CONTA}, plataforma="matific",
                               turma_nome="3º Ano A")
    for caso in (linha, replace(linha, aluno_id=viva.id),
                 replace(linha, nome_incompleto=True)):
        decisao = ida.decidir(ctx, caso)
        assert (decisao.acao, decisao.motivo) == (ida.IGNORAR, "conta_esquecida"), caso
    assert "conta_esquecida" in ida.MOTIVOS_DESCARTE_DECIDIDO
    # Linha sem a conta (só o nome) não é reconhecida: segue o caminho de sempre.
    sem_conta = ida.linha_de_dados(viva.nome, {}, plataforma="matific",
                                   turma_nome="3º Ano A")
    assert ida.decidir(ctx, sem_conta).acao == ida.ASSOCIAR


def test_exclusao_de_turma_com_alunos_nao_marca_contas(db, escola_completa, cliente_global):
    """Limpar uma turma não é pedido de esquecimento: as contas das crianças
    apagadas com ela não passam a ser ignoradas (decisão registrada para o dono)."""
    eid = escola_completa["escola"].id
    _ficha_pela_coleta(db, escola_completa)
    turma_id = escola_completa["turma"].id
    r = cliente_global.delete(f"{API}/escolas/{eid}/turmas/{turma_id}?com_alunos=true")
    assert r.status_code == 200, r.text
    db.expire_all()
    for log in db.execute(select(LogAuditoria).where(
            LogAuditoria.acao == "aluno.excluido_permanente")).scalars():
        assert "contas_esquecidas" not in log.detalhes
    assert exclusao_aluno.marcas_esquecidas(db, eid) == set()
