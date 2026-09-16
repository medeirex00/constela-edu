"""P2 — governança: restaurar backup por admin de escola não planta o perfil
`personalizado`; `ano_letivo_ativo` só muda pelo Admin Global e nunca para trás
de um ano com notas (histórico preservado)."""
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

def test_restaurar_backup_nao_planta_perfil_personalizado_para_admin_de_escola(cliente, db, escola_completa):
    esc = escola_completa["escola"]
    baixado = cliente.get(f"{_base(esc.id)}/backup")
    assert baixado.status_code == 200
    dados = json.loads(baixado.content)
    configs = dados["tabelas"]["configuracoes"]
    modelo = dict(configs[0])
    modelo.update({"_id": max(c["_id"] for c in configs) + 1, "namespace": scoring.PERFIL_SCORING_NS,
                   "chave": "modo", "valor": "personalizado"})
    configs.append(modelo)
    # admin DA ESCOLA não restaura (a restauração substitui livros, leituras e
    # parâmetros de pontuação): 403 e o perfil fica como estava
    r = cliente.post(f"{_base(esc.id)}/restaurar",
                     files={"arquivo": ("backup.json", json.dumps(dados).encode("utf-8"), "application/json")})
    assert r.status_code == 403, r.text
    assert cliente.get(f"{_base(esc.id)}/configuracoes/perfil-scoring").json()["modo"] == "institucional"
    assert not scoring._scoring_personalizado(db, esc.id)
    # e o Admin Global restaura o backup como está
    _login_global(cliente, db, esc.id)
    r = cliente.post(f"{_base(esc.id)}/restaurar",
                     files={"arquivo": ("backup.json", json.dumps(dados).encode("utf-8"), "application/json")})
    assert r.status_code == 200, r.text
    assert cliente.get(f"{_base(esc.id)}/configuracoes/perfil-scoring").json()["modo"] == "personalizado"


def test_troca_do_ano_letivo_ativo_so_admin_global_e_nunca_reescreve_historico(cliente, db, escola_completa):
    esc = escola_completa["escola"]
    scoring.recalcular_escola(db, esc.id)          # cria as Notas de 2026
    assert db.execute(select(Nota).where(Nota.escola_id == esc.id, Nota.ano_letivo == 2026)).first()
    # admin DA ESCOLA não muda o ano ativo
    r = cliente.patch(f"{_base(esc.id)}", json={"ano_letivo_ativo": 2027})
    assert r.status_code == 403
    assert db.get(Escola, esc.id).ano_letivo_ativo == 2026
    _login_global(cliente, db, esc.id)
    # voltar para um ano com notas é recusado (histórico protegido)
    r = cliente.patch(f"{_base(esc.id)}", json={"ano_letivo_ativo": 2025})
    assert r.status_code == 409, r.text
    # avançar é permitido ao Admin Global; as notas de 2026 continuam intactas
    notas_2026 = {n.aluno_id: n.nota_elefante for n in db.execute(
        select(Nota).where(Nota.escola_id == esc.id, Nota.ano_letivo == 2026)).scalars()}
    r = cliente.patch(f"{_base(esc.id)}", json={"ano_letivo_ativo": 2027})
    assert r.status_code == 200, r.text
    db.expire_all()
    scoring.recalcular_escola(db, esc.id)
    depois = {n.aluno_id: n.nota_elefante for n in db.execute(
        select(Nota).where(Nota.escola_id == esc.id, Nota.ano_letivo == 2026)).scalars()}
    assert depois == notas_2026
