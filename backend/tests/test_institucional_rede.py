"""P1 — a REDE agrega só notas carimbadas com a régua institucional vigente
(`detalhes.regua_institucional`); notas antigas contam como pendentes de recálculo
(`dashboard_rede["recalculo_pendente"]`, bloco operacional fora dos cartões de
métricas) em vez de entrarem como zero; recálculo idempotente."""
import json

import pytest
from sqlalchemy import select

from app.core.security import hash_senha
from app.models import Escola, Leitura, Livro, Nota, SnapshotElefante, Usuario
from app.services import dificuldade_livro as dl
from app.services import rede as svc_rede
from app.services import scoring


def _base(escola_id):
    return f"/api/v1/escolas/{escola_id}"


def _login_global(cliente, db, escola_id):
    db.add(Usuario(escola_id=escola_id, nome="Root", email="root@teste.local",
                   senha_hash=hash_senha("s3nh4"), cargo="admin", is_global=True))
    db.commit()
    r = cliente.post("/api/v1/auth/login", data={"username": "root@teste.local", "password": "s3nh4"})
    assert r.status_code == 200, r.text
    cliente.headers["Authorization"] = f"Bearer {r.json()['access_token']}"


def _desfazer_carimbo(db, escola_id):
    """Simula as linhas ANTERIORES à régua vigente (migração 0028 sem backfill):
    coluna institucional 0,0 e detalhes sem o carimbo."""
    for nota in db.execute(select(Nota).where(Nota.escola_id == escola_id)).scalars():
        det = dict(nota.detalhes or {})
        det.pop("regua_institucional", None)
        nota.detalhes = det
        nota.nota_elefante_institucional = 0.0
        nota.nota_matific_institucional = 0.0
    db.commit()


# --- P1: rede × carimbo institucional -------------------------------------------

def test_rede_nao_agrega_notas_sem_carimbo_como_zero_e_recalculo_as_inclui(cliente, db, escola_completa):
    esc = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    r = cliente.post(f"{_base(esc.id)}/importacoes/confirmar", json={
        "plataforma": "elefante", "formato": "resumo", "tipo": "texto",
        "linhas": [{"nome": ana.nome, "aluno_id": ana.id,
                    "dados": {"livros_unicos": 5, "tempo_leitura_min": 60, "livros_por_nivel": {"D": 5}}}]})
    assert r.status_code == 200, r.text
    # recém-recalculada: carimbada, institucional > 0 e agregada pela rede
    nota = db.execute(select(Nota).where(Nota.aluno_id == ana.id)).scalars().one()
    assert nota.detalhes["regua_institucional"]["versao_dificuldade"] == dl.VERSAO_VIGENTE
    assert nota.nota_elefante_institucional > 0
    assert svc_rede._medias_por_plataforma(db, [esc.id], SnapshotElefante, Nota.nota_elefante_institucional)[esc.id][0] == 1
    assert svc_rede._pendentes_recalculo(db, [esc.id]) == {}

    # linha legada (sem carimbo, institucional 0,0): FORA da média, contada como pendente
    _desfazer_carimbo(db, esc.id)
    medias = svc_rede._medias_por_plataforma(db, [esc.id], SnapshotElefante, Nota.nota_elefante_institucional)
    assert medias.get(esc.id, (0, 0.0)) == (0, 0.0)          # não é "média 0 de 1 aluno"
    # as 3 Notas da escola (todos os matriculados) perderam o carimbo → 3 pendentes
    assert svc_rede._pendentes_recalculo(db, [esc.id]) == {esc.id: 3}
    assert esc.id in svc_rede.escolas_com_notas_pendentes(db)

    # o recálculo institucional (idempotente) carimba e reincluí — sem zero indevido
    scoring.recalcular_escola(db, esc.id)
    db.expire_all()
    nota = db.execute(select(Nota).where(Nota.aluno_id == ana.id)).scalars().one()
    assert nota.nota_elefante_institucional > 0
    assert svc_rede._medias_por_plataforma(db, [esc.id], SnapshotElefante, Nota.nota_elefante_institucional)[esc.id][0] == 1
    assert svc_rede._pendentes_recalculo(db, [esc.id]) == {}
    assert esc.id not in svc_rede.escolas_com_notas_pendentes(db)
    antes = nota.detalhes
    scoring.recalcular_escola(db, esc.id)   # idempotente: mesmo conteúdo
    db.expire_all()
    assert db.execute(select(Nota).where(Nota.aluno_id == ana.id)).scalars().one().detalhes == antes


def test_rede_conta_aluno_com_leituras_sem_snapshot_como_dado_do_elefante(db, escola_completa):
    esc = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    livro = Livro(escola_id=esc.id, titulo="Curiosidades 6", nivel_codigo="D")
    db.add(livro); db.flush()
    db.add(Leitura(escola_id=esc.id, aluno_id=ana.id, livro_id=livro.id, tempo_leitura_min=10))
    db.commit()
    scoring.recalcular_escola(db, esc.id)
    n, media = svc_rede._medias_por_plataforma(db, [esc.id], SnapshotElefante, Nota.nota_elefante_institucional)[esc.id]
    assert n == 1 and media > 0


# --- P2: governança do perfil e do ano letivo -------------------------------------
