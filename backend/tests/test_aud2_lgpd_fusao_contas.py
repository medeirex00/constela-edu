"""ALUNOS-4: a fusão não mistura em silêncio os retratos de DUAS contas da mesma
plataforma.

O retrato (``SnapshotMatific``/``SnapshotElefante``) não guarda de qual conta veio.
``fundir_par`` levava todos os retratos da ficha absorvida e os DOIS vínculos da
mesma plataforma para a ficha que fica: a série passava a alternar entre as duas
contas, o ganho do período (``matific_destaque.ganho_no_periodo``) comparava a base
de uma com o atual da outra (a criança ia ao pódio com 495 atividades quando ganhou
2 a 5) e a coleta seguinte continuava gravando as duas contas na mesma ficha.

Sem a coluna da conta no retrato (migração: decisão do dono), a fusão de duas
fichas com contas DIFERENTES da mesma plataforma é recusada antes de qualquer
escrita (409 na fusão manual; falha do par no lote), e as prévias avisam antes.

Dados 100% fictícios; sem rede.
"""
from datetime import datetime

from sqlalchemy import func, select

from app.models import Aluno, IdentidadeExterna, Importacao, LogAuditoria, SnapshotMatific
from app.services import matific_destaque

API = "/api/v1"


def _snap(db, escola_id, imp_id, aluno_id, quando, atividades, estrelas):
    db.add(SnapshotMatific(escola_id=escola_id, aluno_id=aluno_id, importacao_id=imp_id,
                           data_referencia=quando, atividades=atividades,
                           estrelas=estrelas, pontuacao_media=4.0))


def _duas_contas(db, escola_completa, *, plataforma_remover="matific"):
    """Conta A na ficha que fica e conta B na que sai, coletadas cada uma na sua
    ficha (A: 10 → 12; B: 500 → 505; a terceira criança: 100 → 150)."""
    escola = escola_completa["escola"]
    manter, remover, outro = escola_completa["alunos"]
    imp = Importacao(escola_id=escola.id, plataforma="matific", tipo="seed")
    db.add(imp)
    db.flush()
    db.add(IdentidadeExterna(escola_id=escola.id, aluno_id=manter.id,
                             plataforma="matific", id_externo="conta-ficticia-A"))
    db.add(IdentidadeExterna(escola_id=escola.id, aluno_id=remover.id,
                             plataforma=plataforma_remover, id_externo="conta-ficticia-B"))
    if plataforma_remover == "matific":
        _snap(db, escola.id, imp.id, remover.id, datetime(2026, 10, 14, 3, 0), 500, 1500)
        _snap(db, escola.id, imp.id, remover.id, datetime(2026, 10, 31, 3, 5), 505, 1515)
    _snap(db, escola.id, imp.id, manter.id, datetime(2026, 10, 14, 3, 5), 10, 30)
    _snap(db, escola.id, imp.id, outro.id, datetime(2026, 10, 14, 3, 5), 100, 300)
    _snap(db, escola.id, imp.id, manter.id, datetime(2026, 10, 31, 3, 0), 12, 36)
    _snap(db, escola.id, imp.id, outro.id, datetime(2026, 10, 31, 3, 5), 150, 450)
    db.commit()
    return escola.id, manter.id, remover.id


def _ganho(db, aluno_id):
    serie = db.execute(select(SnapshotMatific).where(SnapshotMatific.aluno_id == aluno_id)
                       ).scalars().all()
    return matific_destaque.ganho_no_periodo(serie, datetime(2026, 10, 15),
                                             datetime(2026, 10, 31, 23, 59, 59), 2026)


def test_fusao_manual_de_fichas_com_contas_diferentes_no_matific_e_recusada(
        cliente, db, escola_completa):
    eid, manter_id, remover_id = _duas_contas(db, escola_completa)
    base = f"{API}/escolas/{eid}"
    previa = cliente.get(f"{base}/alunos/fundir/previa",
                         params={"manter_id": manter_id, "remover_id": remover_id}).json()

    r = cliente.post(f"{base}/alunos/fundir", json={
        "manter_id": manter_id, "remover_id": remover_id, "confirmacao": "FUNDIR"})
    db.expire_all()
    g = _ganho(db, manter_id)
    print("FUSÃO:", r.status_code, r.json().get("detail"), "| GANHO DA FICHA:", g)
    assert g.atividades <= 7, "a diferença entre as duas contas virou ganho no período"
    assert r.status_code == 409, r.text
    assert "contas diferentes no Matific" in r.json()["detail"]
    # Nada foi escrito: as duas fichas, cada conta e cada série no seu lugar.
    assert db.get(Aluno, remover_id) is not None
    contas = dict(db.execute(select(IdentidadeExterna.id_externo, IdentidadeExterna.aluno_id)
                             ).all())
    assert contas == {"conta-ficticia-A": manter_id, "conta-ficticia-B": remover_id}
    assert db.execute(select(func.count()).select_from(SnapshotMatific).where(
        SnapshotMatific.aluno_id == remover_id)).scalar_one() == 2
    assert db.execute(select(func.count()).select_from(LogAuditoria).where(
        LogAuditoria.acao == "aluno.fundido")).scalar_one() == 0
    # A prévia avisa antes, com o mesmo texto da recusa.
    assert previa["contas_em_conflito"] == ["matific"]
    assert previa["recusa"] == r.json()["detail"]


def test_premiacao_do_periodo_nao_vira_diferenca_entre_contas(cliente, db, escola_completa):
    """A sonda do auditor pela tela: com a fusão recusada, a criança da conta A
    continua com o ganho real dela no período (2), não com 495."""
    eid, manter_id, remover_id = _duas_contas(db, escola_completa)
    base = f"{API}/escolas/{eid}"
    cliente.post(f"{base}/alunos/fundir", json={
        "manter_id": manter_id, "remover_id": remover_id, "confirmacao": "FUNDIR"})
    p = cliente.get(f"{base}/premiacoes", params={
        "periodo": "personalizado", "inicio": "2026-10-15", "fim": "2026-10-31", "limite": 50})
    assert p.status_code == 200, p.text
    cats = p.json()["categorias"]
    linhas = [linha for c in (cats if isinstance(cats, list) else cats.values())
              if isinstance(c, dict) for linha in (c.get("podio") or [])]
    da_ficha = [linha for linha in linhas if linha.get("aluno_id") == manter_id
                and "atividades" in linha]
    assert all(linha["atividades"] <= 7 for linha in da_ficha), da_ficha


def test_fusao_em_lote_recusa_o_par_e_segue(cliente, db, escola_completa):
    eid, manter_id, remover_id = _duas_contas(db, escola_completa)
    # O par do lote: as duas fichas com o mesmo nome completo na mesma turma.
    db.get(Aluno, remover_id).nome = db.get(Aluno, manter_id).nome
    db.get(Aluno, manter_id).da_lista_piloto = True
    db.commit()
    base = f"{API}/escolas/{eid}"
    cands = cliente.get(f"{base}/alunos/duplicados").json()["candidatos"]
    par = next(c for c in cands if c["loser_id"] == remover_id)
    assert par["manter_id"] == manter_id
    assert "Matific" in par["recusa"]

    r = cliente.post(f"{base}/alunos/duplicados/corrigir",
                     json={"loser_ids": [remover_id], "confirmacao": "FUNDIR"})
    assert r.status_code == 200, r.text
    assert r.json()["fundidos"] == 0
    assert r.json()["falhas"] == [{"loser_id": remover_id, "motivo": par["recusa"]}]
    db.expire_all()
    assert db.get(Aluno, remover_id) is not None


def test_contas_de_plataformas_diferentes_continuam_fundindo(cliente, db, escola_completa):
    """Controle: Matific numa ficha e Elefante na outra é o caso para o qual a
    fusão existe (os dados de uma criança vieram separados)."""
    eid, manter_id, remover_id = _duas_contas(db, escola_completa,
                                              plataforma_remover="elefante")
    base = f"{API}/escolas/{eid}"
    previa = cliente.get(f"{base}/alunos/fundir/previa",
                         params={"manter_id": manter_id, "remover_id": remover_id}).json()
    assert previa["recusa"] is None and previa["contas_em_conflito"] == []
    r = cliente.post(f"{base}/alunos/fundir", json={
        "manter_id": manter_id, "remover_id": remover_id, "confirmacao": "FUNDIR"})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert set(db.execute(select(IdentidadeExterna.plataforma).where(
        IdentidadeExterna.aluno_id == manter_id)).scalars()) == {"matific", "elefante"}


def test_conta_so_numa_ficha_continua_fundindo(cliente, db, escola_completa):
    """Controle: a ficha sem conta (o cadastro da Lista Piloto) absorve a da conta."""
    eid = escola_completa["escola"].id
    a, b = escola_completa["alunos"][0], escola_completa["alunos"][1]
    db.add(IdentidadeExterna(escola_id=eid, aluno_id=b.id, plataforma="matific",
                             id_externo="conta-ficticia-C"))
    db.commit()
    r = cliente.post(f"{API}/escolas/{eid}/alunos/fundir", json={
        "manter_id": a.id, "remover_id": b.id, "confirmacao": "FUNDIR"})
    assert r.status_code == 200, r.text


def test_duas_contas_no_elefante_tambem_recusa(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    a, b = escola_completa["alunos"][0], escola_completa["alunos"][1]
    db.add(IdentidadeExterna(escola_id=eid, aluno_id=a.id, plataforma="elefante",
                             id_externo="ele-ficticia-1"))
    db.add(IdentidadeExterna(escola_id=eid, aluno_id=b.id, plataforma="elefante",
                             id_externo="ele-ficticia-2"))
    db.commit()
    r = cliente.post(f"{API}/escolas/{eid}/alunos/fundir", json={
        "manter_id": a.id, "remover_id": b.id, "confirmacao": "FUNDIR"})
    assert r.status_code == 409, r.text
    assert "contas diferentes no Elefante Letrado" in r.json()["detail"]
