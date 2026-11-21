"""DEC-19 no perfil: a criança sem nenhum dado não ganha posição no perfil, e não
empurra a posição de quem tem dado.

O Ranking Geral (web e app) e o Top 10 deixaram de listar a criança sem retrato de
plataforma nenhuma (``rankings._ranking(so_com_dado=True)``: ausência não é zero).
O perfil (``GET /alunos/{id}/perfil``, aberto pelo toque na linha do ranking)
seguia a régua antiga: o do professor numerava com ela na lista — com uma criança
sem dado no meio, a aba dizia 2º e o perfil, 3º —, e o da gestão mostrava a posição
carimbada de quem o ranking nem lista. Dados fictícios (fixtures escola_completa e
cenario_professor).
"""
from app.models import Nota
from tests.test_perfil_posicao_do_professor import _tres_visoes
from tests.test_permissoes import cenario_professor  # noqa: F401  (fixture)


def _notas_com_uma_sem_dado(db, escola, alunos, fora):
    """alunos[1] fica entre os outros dois na ordem carimbada, mas sem retrato
    nenhum (aferido_* falsos): o ranking não a lista."""
    posicoes = {alunos[0].id: 100, alunos[1].id: 101, alunos[2].id: 102, fora.id: 103}
    for aid, pos in posicoes.items():
        tem_dado = aid != alunos[1].id
        db.add(Nota(escola_id=escola.id, aluno_id=aid, ano_letivo=2026,
                    nota_geral=0.0, posicao=pos, aferido_leitura=tem_dado))
    db.commit()


def test_professor_a_crianca_sem_dado_nao_empurra_a_posicao_no_perfil(
        cenario_professor, escola_completa, db):  # noqa: F811
    c = cenario_professor
    escola, alunos = escola_completa["escola"], escola_completa["alunos"]
    _notas_com_uma_sem_dado(db, escola, alunos, c["aluno_fora"])
    base = f"/api/v1/escolas/{escola.id}"

    app, web, perfil = _tres_visoes(c["professor"], base)
    esperado = {alunos[0].id: 1, alunos[2].id: 2}
    assert app == esperado and web == esperado
    assert perfil == esperado                    # antes {…: 1, …: 3}
    sem_dado = c["professor"].get(f"{base}/alunos/{alunos[1].id}/perfil")
    assert sem_dado.status_code == 200, sem_dado.text
    assert sem_dado.json()["posicao"] is None    # antes 2


def test_gestao_a_crianca_sem_dado_fica_sem_posicao_no_perfil(
        cenario_professor, escola_completa, db):  # noqa: F811
    c = cenario_professor
    escola, alunos = escola_completa["escola"], escola_completa["alunos"]
    _notas_com_uma_sem_dado(db, escola, alunos, c["aluno_fora"])
    base = f"/api/v1/escolas/{escola.id}"

    app, web, perfil = _tres_visoes(c["coordenador"], base)
    esperado = {alunos[0].id: 100, alunos[2].id: 102, c["aluno_fora"].id: 103}
    assert app == web == perfil == esperado
    sem_dado = c["coordenador"].get(f"{base}/alunos/{alunos[1].id}/perfil")
    assert sem_dado.status_code == 200, sem_dado.text
    assert sem_dado.json()["posicao"] is None    # antes 101, a posição de quem não é listado
