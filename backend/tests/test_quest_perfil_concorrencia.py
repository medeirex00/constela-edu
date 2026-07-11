"""Concorrência na criação do perfil do Quest (achado MÉDIO): dois pedidos
sobrepostos para o mesmo aluno não podem estourar 500 nem duplicar perfil, e
uma colisão de codigo_amigo re-sorteia — mesmo padrão de _inserir_credencial_nova.
"""
from sqlalchemy import func, select

from app.quest.models import QuestPerfil
from app.quest.services import perfis


def test_inserir_perfil_reresolve_em_colisao_de_aluno(db, escola_completa):
    """INSERT concorrente do MESMO aluno bate no unique aluno_id → re-resolve
    para o perfil existente, sem 500 e sem duplicar."""
    aluno = escola_completa["alunos"][0]
    p1 = perfis.obter_ou_criar_perfil(db, aluno)
    db.commit()

    p2 = perfis._inserir_perfil_novo(db, aluno)
    assert p2.id == p1.id
    total = db.execute(
        select(func.count()).select_from(QuestPerfil)
        .where(QuestPerfil.aluno_id == aluno.id)).scalar_one()
    assert total == 1


def test_inserir_perfil_reensorteia_codigo_amigo_em_colisao(
        db, escola_completa, monkeypatch):
    """Colisão só no codigo_amigo (unique) faz a próxima volta sortear outro —
    o perfil é criado sem erro."""
    a0, a1 = escola_completa["alunos"][0], escola_completa["alunos"][1]
    p0 = perfis.obter_ou_criar_perfil(db, a0)
    db.commit()

    # 1º sorteio colide com um código já usado; o 2º é livre.
    seq = iter([p0.codigo_amigo, "COSMO-ZZ99"])
    monkeypatch.setattr(perfis, "gerar_codigo_amigo", lambda _db: next(seq))

    p1 = perfis._inserir_perfil_novo(db, a1)
    assert p1.aluno_id == a1.id
    assert p1.codigo_amigo == "COSMO-ZZ99"
