"""Minimização de dados do aluno (LGPD): a ficha guarda só o RA; categorias
sensíveis (raça/cor, SUS) e documentos (CPF, RG) não são coletados nem ficam
retidos. Cobre a criação manual, a allowlist e a purga da migração 0014.
"""
import importlib.util
from pathlib import Path

from sqlalchemy import select

from app.models import Aluno


def _base(escola_id: int) -> str:
    return f"/api/v1/escolas/{escola_id}"


def test_rotulos_ficha_so_tem_ra():
    """A allowlist do que pode entrar na ficha é apenas o RA."""
    from app.services.lista_piloto import ROTULOS_FICHA
    assert set(ROTULOS_FICHA) == {"ra"}


def test_criar_aluno_descarta_campos_sensiveis(cliente, db, escola_completa):
    """Ao criar um aluno, campos sensíveis enviados na ficha são IGNORADOS —
    só o RA persiste."""
    escola_id = escola_completa["escola"].id
    turma = escola_completa["turma"]
    r = cliente.post(f"{_base(escola_id)}/alunos", json={
        "nome": "Novo Aluno Teste", "turma_id": turma.id,
        "ficha": {"ra": "999.111.222-3", "cpf": "111.222.333-44",
                  "raca_cor": "parda", "sus": "700000", "responsavel": "Fulana"},
    })
    assert r.status_code == 201, r.text
    aluno = db.execute(select(Aluno).where(
        Aluno.nome == "Novo Aluno Teste")).scalar_one()
    assert aluno.ficha == {"ra": "999.111.222-3"}   # só o RA sobreviveu


def test_migracao_0014_purga_ficha_sensivel():
    """A função de purga da migração 0014 remove tudo da ficha exceto o RA."""
    caminho = (Path(__file__).resolve().parent.parent
               / "alembic" / "versions" / "0014_minimizar_ficha_lgpd.py")
    spec = importlib.util.spec_from_file_location("mig0014", caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    suja = {"ra": "123", "cpf": "999", "raca_cor": "x", "sus": "y",
            "rg": "z", "responsavel": "w", "endereco": "e"}
    assert mod._limpar(suja) == {"ra": "123"}
    assert mod._limpar({"cpf": "só sensível"}) == {}   # sem RA → fica vazia
    assert mod._limpar({}) == {}
    assert mod._limpar(None) == {}
    # Aceita ficha guardada como texto JSON (alguns bancos).
    assert mod._limpar('{"ra": "1", "cpf": "2"}') == {"ra": "1"}
