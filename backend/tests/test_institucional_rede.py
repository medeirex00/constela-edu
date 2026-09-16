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


def test_nota_com_regua_antiga_e_pendente_sem_mudar_o_que_a_rede_agrega(db, escola_completa):
    """Nota CALCULADA por uma régua anterior (carimbo v1, vigente v2) é pendente
    de recálculo — a MESMA regra de `scripts.recalcular_institucional --pendentes`,
    agora também no painel da rede — mas continua AGREGADA: é número calculado,
    não ausência de cálculo. Trocar a versão da régua não recalcula nada sozinho."""
    esc = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    livro = Livro(escola_id=esc.id, titulo="Curiosidades 7", nivel_codigo="D")
    db.add(livro)
    db.flush()
    db.add(Leitura(escola_id=esc.id, aluno_id=ana.id, livro_id=livro.id, tempo_leitura_min=10))
    db.commit()
    scoring.recalcular_escola(db, esc.id)
    medias = svc_rede._medias_por_plataforma
    antes = medias(db, [esc.id], SnapshotElefante, Nota.nota_elefante_institucional)[esc.id]
    assert antes[0] == 1 and antes[1] > 0
    assert svc_rede._pendentes_recalculo(db, [esc.id]) == {}   # carimbo vigente: nada pendente

    nota = db.execute(select(Nota).where(Nota.aluno_id == ana.id)).scalars().one()
    nota.detalhes = {**nota.detalhes, "regua_institucional": {
        "versao_dificuldade": dl.VERSAO_V1, "perfil_local": "institucional"}}
    db.commit()

    # 1) passa a contar como pendente (era invisível: só a falta de carimbo contava)
    assert svc_rede._pendentes_recalculo(db, [esc.id]) == {esc.id: 1}
    assert esc.id in svc_rede.escolas_com_notas_pendentes(db)
    # 2) o AGREGADO não muda — a nota v1 continua entrando na média da rede
    assert medias(db, [esc.id], SnapshotElefante, Nota.nota_elefante_institucional)[esc.id] == antes
    # 3) e nada foi recalculado em silêncio
    db.refresh(nota)
    assert nota.detalhes["regua_institucional"]["versao_dificuldade"] == dl.VERSAO_V1

    scoring.recalcular_escola(db, esc.id)          # ação EXPLÍCITA do Admin Global
    assert svc_rede._pendentes_recalculo(db, [esc.id]) == {}   # idempotente


def test_dashboard_da_rede_nao_muda_nenhum_numero_quando_a_nota_vira_v1(db, escola_completa):
    """RECONFERÊNCIA do ajuste 4, no PAINEL inteiro (não só no helper privado).

    Carimbar a nota com uma régua anterior só pode mexer no bloco OPERACIONAL
    (`recalculo_pendente`). Todo o resto do `dashboard_rede` — cartões, médias,
    adoção, índice, totais, lista de atenção — tem de sair byte a byte igual: a
    rede continua agregando a nota v1 (é número calculado, não ausência), e nada
    é recalculado sozinho."""
    from app.models import Rede

    esc = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    rede = Rede(nome="Rede de Teste", uf="SP", status="ativa")
    db.add(rede)
    db.flush()
    esc.rede_id = rede.id
    livro = Livro(escola_id=esc.id, titulo="Curiosidades 8", nivel_codigo="D")
    db.add(livro)
    db.flush()
    db.add(Leitura(escola_id=esc.id, aluno_id=ana.id, livro_id=livro.id, tempo_leitura_min=10))
    db.commit()
    scoring.recalcular_escola(db, esc.id)

    antes = svc_rede.dashboard_rede(db, rede.id)
    assert antes["recalculo_pendente"]["total"] == 0

    nota = db.execute(select(Nota).where(Nota.aluno_id == ana.id)).scalars().one()
    nota.detalhes = {**nota.detalhes, "regua_institucional": {
        "versao_dificuldade": dl.VERSAO_V1, "perfil_local": "institucional"}}
    db.commit()
    depois = svc_rede.dashboard_rede(db, rede.id)

    # 1) o bloco operacional acusa a régua antiga...
    assert depois["recalculo_pendente"]["total"] == 1
    assert depois["recalculo_pendente"]["por_escola"] == {str(esc.id): 1}
    # 2) ...e TUDO o mais é idêntico (comparação total, não campo a campo escolhido)
    assert json.dumps({k: v for k, v in depois.items() if k != "recalculo_pendente"},
                      sort_keys=True, default=str) ==         json.dumps({k: v for k, v in antes.items() if k != "recalculo_pendente"},
                   sort_keys=True, default=str)


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
