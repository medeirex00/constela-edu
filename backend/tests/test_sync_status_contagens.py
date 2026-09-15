"""Status da integração com contagens HONESTAS (item 4): GET /sync/status
devolve, por plataforma, quantos alunos têm dado, quantos não têm nenhum,
quantos usam o Elefante e ainda não produziram (zero legítimo) e de quando é o
dado mais recente; e, por escola, as pendências de correspondência dos últimos
30 dias. Cada número é um COUNT do banco — escola vazia → zeros, nada inventado.

Universo das contagens: alunos ATIVOS matriculados no ano letivo ativo (o mesmo
que o motor pontua). Arquivado ou matriculado em outro ano não entra.
"""
from datetime import datetime, timedelta, timezone

from app.models import (
    Aluno,
    Escola,
    Importacao,
    LogAuditoria,
    Matricula,
    SnapshotElefante,
    SnapshotMatific,
)

API = "/api/v1"


def _status(cliente, escola_id):
    r = cliente.get(f"{API}/escolas/{escola_id}/sync/status")
    assert r.status_code == 200, r.text
    return r.json()


def _plat(st, nome):
    return next(p for p in st["plataformas"] if p["plataforma"] == nome)


def _imp(db, escola_id):
    imp = Importacao(escola_id=escola_id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    return imp


def _dia(d, m):
    return datetime(2026, m, d, 12, 0, tzinfo=timezone.utc)


def test_escola_vazia_devolve_zeros(cliente_global, db):
    esc = Escola(nome="Escola Vazia", ano_letivo_ativo=2026)
    db.add(esc)
    db.commit()
    st = _status(cliente_global, esc.id)
    assert {p["plataforma"] for p in st["plataformas"]} >= {"elefante", "matific"}
    for nome in ("elefante", "matific"):
        p = _plat(st, nome)
        assert p["alunos_com_dados"] == 0
        assert p["alunos_sem_dados"] == 0
        assert p["dado_mais_recente_em"] is None
    assert _plat(st, "elefante")["alunos_com_zero_registros"] == 0
    assert _plat(st, "matific")["alunos_com_zero_registros"] is None   # não se aplica
    assert st["pendencias_correspondencia_30d"] == 0


def test_escola_sem_snapshots_conta_todos_como_sem_dados(cliente, escola_completa):
    st = _status(cliente, escola_completa["escola"].id)
    for nome in ("elefante", "matific"):
        p = _plat(st, nome)
        assert p["alunos_com_dados"] == 0
        assert p["alunos_sem_dados"] == 3
        assert p["dado_mais_recente_em"] is None
    assert _plat(st, "elefante")["alunos_com_zero_registros"] == 0


def test_contagens_elefante_e_matific(cliente, db, escola_completa):
    esc = escola_completa["escola"]
    turma = escola_completa["turma"]
    ana, joao, sofia = escola_completa["alunos"]
    imp = _imp(db, esc.id)

    # ELEFANTE — Ana: snapshot antigo zerado + ATUAL com livros (não é "zero");
    # João: só um snapshot zerado (zero legítimo); Sofia: nenhum.
    db.add(SnapshotElefante(escola_id=esc.id, aluno_id=ana.id, importacao_id=imp.id,
                            data_referencia=_dia(1, 3), livros_unicos=0))
    db.add(SnapshotElefante(escola_id=esc.id, aluno_id=ana.id, importacao_id=imp.id,
                            data_referencia=_dia(10, 4), livros_unicos=3,
                            livros_por_nivel={"D": 3}))
    db.add(SnapshotElefante(escola_id=esc.id, aluno_id=joao.id, importacao_id=imp.id,
                            data_referencia=_dia(5, 4), livros_unicos=0))
    # MATIFIC — Ana e Sofia têm; João não.
    for a in (ana, sofia):
        db.add(SnapshotMatific(escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
                               data_referencia=_dia(8, 4), atividades=10, estrelas=20,
                               pontuacao_media=2.0))
    # Fora do universo: aluno ARQUIVADO com snapshot e aluno de OUTRO ano letivo.
    arquivado = Aluno(escola_id=esc.id, nome="Arquivado Com Dado", status="arquivado")
    outro_ano = Aluno(escola_id=esc.id, nome="Aluno De 2025", status="ativo")
    db.add_all([arquivado, outro_ano])
    db.flush()
    db.add(Matricula(escola_id=esc.id, aluno_id=arquivado.id, turma_id=turma.id, ano_letivo=2026))
    db.add(Matricula(escola_id=esc.id, aluno_id=outro_ano.id, turma_id=turma.id, ano_letivo=2025))
    # Datas MAIS RECENTES que as do universo (01/05): se o frescor olhasse a
    # escola inteira, o "dado mais recente" viraria 01/05 — o teste distingue.
    for a in (arquivado, outro_ano):
        db.add(SnapshotElefante(escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
                                data_referencia=_dia(1, 5), livros_unicos=0))
        db.add(SnapshotMatific(escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
                               data_referencia=_dia(1, 5), atividades=1, estrelas=1,
                               pontuacao_media=1.0))
    db.commit()

    st = _status(cliente, esc.id)
    ele = _plat(st, "elefante")
    assert ele["alunos_com_dados"] == 2          # Ana e João
    assert ele["alunos_sem_dados"] == 1          # Sofia
    assert ele["alunos_com_zero_registros"] == 1  # só João (o ATUAL da Ana tem livros)
    assert ele["dado_mais_recente_em"].startswith("2026-04-10")

    mat = _plat(st, "matific")
    assert mat["alunos_com_dados"] == 2          # Ana e Sofia
    assert mat["alunos_sem_dados"] == 1          # João
    assert mat["alunos_com_zero_registros"] is None
    assert mat["dado_mais_recente_em"].startswith("2026-04-08")

    # Os totais por plataforma fecham com o universo (3 alunos ativos do ano).
    assert ele["alunos_com_dados"] + ele["alunos_sem_dados"] == 3
    assert mat["alunos_com_dados"] + mat["alunos_sem_dados"] == 3
    assert st["qtd_alunos"] == 4                 # ativos da escola (inclui o de 2025)


def test_frescor_ignora_snapshot_fora_do_universo(cliente, db, escola_completa):
    """Só um aluno ARQUIVADO tem snapshot (e recente): para os alunos pontuados
    não há dado nenhum — o frescor é None, não a data do arquivado."""
    esc = escola_completa["escola"]
    turma = escola_completa["turma"]
    imp = _imp(db, esc.id)
    arquivado = Aluno(escola_id=esc.id, nome="Arquivado Recente", status="arquivado")
    db.add(arquivado)
    db.flush()
    db.add(Matricula(escola_id=esc.id, aluno_id=arquivado.id, turma_id=turma.id, ano_letivo=2026))
    db.add(SnapshotElefante(escola_id=esc.id, aluno_id=arquivado.id, importacao_id=imp.id,
                            data_referencia=_dia(1, 5), livros_unicos=2))
    db.add(SnapshotMatific(escola_id=esc.id, aluno_id=arquivado.id, importacao_id=imp.id,
                           data_referencia=_dia(1, 5), atividades=3, estrelas=6,
                           pontuacao_media=2.0))
    db.commit()
    st = _status(cliente, esc.id)
    for nome in ("elefante", "matific"):
        p = _plat(st, nome)
        assert p["alunos_com_dados"] == 0
        assert p["alunos_sem_dados"] == 3
        assert p["dado_mais_recente_em"] is None


def test_plataforma_sem_tabela_de_snapshot_devolve_none(cliente, db, escola_completa,
                                                        monkeypatch):
    """Não dá para contar (plataforma sem tabela de snapshot) → None, nunca 0.
    Hoje todo conector sincronizável tem tabela; o ramo é exercitado tirando o
    Matific do mapa de modelos."""
    from app.sync import router as sync_router

    esc = escola_completa["escola"]
    monkeypatch.setattr(sync_router, "_SNAPSHOT_DA_PLATAFORMA",
                        {"elefante": SnapshotElefante})
    st = _status(cliente, esc.id)
    mat = _plat(st, "matific")
    assert mat["alunos_com_dados"] is None
    assert mat["alunos_sem_dados"] is None
    assert mat["alunos_com_zero_registros"] is None
    assert mat["dado_mais_recente_em"] is None
    # A plataforma que tem tabela segue contando normalmente (0 legítimo ≠ None).
    ele = _plat(st, "elefante")
    assert ele["alunos_com_dados"] == 0 and ele["alunos_sem_dados"] == 3


def test_escola_sem_ano_letivo_ativo_devolve_none(db, escola_completa):
    """`Escola.ano_letivo_ativo` é NOT NULL (default 2026), então o ramo "sem ano"
    não chega pela API; a função de contagem é exercitada diretamente para
    travar a semântica: sem ano não dá para contar → None, nunca 0."""
    from app.sync import router as sync_router

    esc = escola_completa["escola"]
    for plataforma in ("elefante", "matific"):
        campos = sync_router._contagens_plataforma(db, esc.id, None, plataforma)
        assert campos == {
            "alunos_com_dados": None,
            "alunos_sem_dados": None,
            "alunos_com_zero_registros": None,
            "dado_mais_recente_em": None,
        }


def test_pendencia_de_correspondencia_conta_so_os_ultimos_30_dias(cliente, db, escola_completa):
    esc = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    assert _status(cliente, esc.id)["pendencias_correspondencia_30d"] == 0

    # Uma linha SEM aluno vinculado no /importacoes/confirmar gera a pendência
    # (auditoria `importacao.linha_ignorada`) — e ela aparece no status.
    r = cliente.post(f"{API}/escolas/{esc.id}/importacoes/confirmar", json={
        "plataforma": "elefante", "formato": "resumo", "tipo": "texto",
        "permitir_criar_turma": False,
        "linhas": [
            {"nome": ana.nome, "aluno_id": ana.id, "dados": {"livros_unicos": 1}},
            {"nome": "Fulano Sem Vinculo", "dados": {"livros_unicos": 4}},
        ]})
    assert r.status_code == 200, r.text
    assert _status(cliente, esc.id)["pendencias_correspondencia_30d"] == 1

    agora = datetime.now(timezone.utc)
    # Antiga (40 dias): fora da janela. Recente da outra ação relevante: conta.
    # Ação não relacionada (recente): não conta. Outra escola: não conta.
    outra = Escola(nome="Outra Escola", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    db.add_all([
        LogAuditoria(escola_id=esc.id, acao="aluno.revisao_necessaria", entidade="aluno",
                     detalhes={}, created_at=agora - timedelta(days=40)),
        LogAuditoria(escola_id=esc.id, acao="aluno.revisao_necessaria", entidade="aluno",
                     detalhes={}, created_at=agora - timedelta(days=1)),
        LogAuditoria(escola_id=esc.id, acao="pesos.alterados", entidade="configuracao",
                     detalhes={}, created_at=agora - timedelta(days=1)),
        LogAuditoria(escola_id=outra.id, acao="importacao.linha_ignorada", entidade="aluno",
                     detalhes={}, created_at=agora - timedelta(days=1)),
    ])
    db.commit()
    assert _status(cliente, esc.id)["pendencias_correspondencia_30d"] == 2
