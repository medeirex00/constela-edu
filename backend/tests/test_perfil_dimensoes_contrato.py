"""Perfil do aluno × tela: o desempenho POR DIMENSÃO viaja na resposta.

A ficha da web (``apps/web/src/pages/PerfilAluno.tsx``) decide entre "—" e o
número pelo ``aferido`` de ``perfil.dimensoes`` (``notaDaMateria``). A rota
``GET /alunos/{id}/perfil`` declarava o campo no schema mas nunca o preenchia:
chegava ``[]`` e a ficha mostrava 0,0 em Matemática para a criança que nunca
abriu o Matific (a coluna ``nota_matific`` é 0,0 para quem não tem snapshot).

Aqui fica travado: cada dimensão contratada vem com ``aferido``; sem dado →
``aferido=False`` e ``nota=None``; o zero legítimo (tem snapshot, ainda não
produziu) continua 0,0 com ``aferido=True``; e quem tem dado recebe a MESMA nota
de antes. Dados fictícios (fixtures escola_completa e cenario_professor).
"""
from app.models import Nota
from tests.test_permissoes import cenario_professor  # noqa: F401  (fixture)


def _por_dimensao(resposta: dict) -> dict:
    return {b["dimensao"]: b for b in resposta["dimensoes"]}


def test_sem_dado_vem_aferido_false_e_zero_legitimo_segue_zero(cliente, escola_completa, db):
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    # Leitura: tem snapshot e ainda não produziu (zero legítimo). Matemática: sem
    # snapshot nenhum — a coluna é 0,0, mas NÃO é desempenho.
    db.add(Nota(escola_id=escola.id, aluno_id=aluno.id, ano_letivo=2026,
                nota_elefante=0.0, aferido_leitura=True, posicao_leitura=3,
                nota_matific=0.0, aferido_matematica=False,
                nota_geral=0.0, posicao=3))
    db.commit()

    r = cliente.get(f"/api/v1/escolas/{escola.id}/alunos/{aluno.id}/perfil")
    assert r.status_code == 200, r.text
    corpo = r.json()
    dims = _por_dimensao(corpo)
    assert set(dims) == {"leitura", "matematica"}          # as duas contratadas
    assert dims["matematica"]["aferido"] is False
    assert dims["matematica"]["nota"] is None              # a tela mostra "—"
    assert dims["leitura"]["aferido"] is True
    assert dims["leitura"]["nota"] == 0.0                  # zero legítimo continua 0,0
    assert dims["leitura"]["posicao"] == 3
    # As notas de plataforma (legado) não mudam: o "—" vem do `aferido`.
    assert corpo["nota_matific"] == 0.0 and corpo["nota_elefante"] == 0.0
    assert corpo["adocao"]["com_dados"] == ["leitura"]


def test_quem_tem_dado_recebe_a_mesma_nota(cliente, escola_completa, db):
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][1]
    db.add(Nota(escola_id=escola.id, aluno_id=aluno.id, ano_letivo=2026,
                nota_elefante=72.5, aferido_leitura=True,
                nota_matific=64.0, aferido_matematica=True,
                nota_geral=68.25, posicao=1))
    db.commit()

    corpo = cliente.get(f"/api/v1/escolas/{escola.id}/alunos/{aluno.id}/perfil").json()
    dims = _por_dimensao(corpo)
    assert dims["leitura"]["nota"] == corpo["nota_elefante"] == 72.5
    assert dims["matematica"]["nota"] == corpo["nota_matific"] == 64.0
    assert dims["leitura"]["aferido"] and dims["matematica"]["aferido"]


def test_sem_nota_calculada_nenhuma_dimensao_e_aferida(cliente, escola_completa):
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][2]
    corpo = cliente.get(f"/api/v1/escolas/{escola.id}/alunos/{aluno.id}/perfil").json()
    assert [(b["dimensao"], b["aferido"], b["nota"]) for b in corpo["dimensoes"]] == [
        ("leitura", False, None), ("matematica", False, None)]


def test_professor_recebe_o_aferido_sem_a_posicao_da_escola(cenario_professor, escola_completa, db):  # noqa: F811
    c = cenario_professor
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    db.add(Nota(escola_id=escola.id, aluno_id=aluno.id, ano_letivo=2026,
                nota_elefante=50.0, aferido_leitura=True, posicao_leitura=40,
                nota_matific=0.0, aferido_matematica=False,
                nota_geral=50.0, posicao=40))
    db.commit()

    r = c["professor"].get(f"/api/v1/escolas/{escola.id}/alunos/{aluno.id}/perfil")
    assert r.status_code == 200, r.text
    dims = _por_dimensao(r.json())
    assert dims["matematica"]["aferido"] is False and dims["matematica"]["nota"] is None
    assert dims["leitura"]["aferido"] is True and dims["leitura"]["nota"] == 50.0
    # A posição do bloco é a da escola inteira, não a das turmas dele.
    assert dims["leitura"]["posicao"] is None
