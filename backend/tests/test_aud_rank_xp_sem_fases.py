"""AS FASES NÃO CONCORREM também no Ranking de XP (página Conquistas).

`gamificacao.ranking_xp` listava todos os ativos matriculados, sem o corte de
`services.elegibilidade` (ranking e premiação são do 1º ao 5º ano). As crianças
da 1ª e da 2ª Fase apareciam em 1º e 2º, com medalha, e o Fundamental começava
em 3º — enquanto o mural da MESMA página já as excluía
(`tests/test_mural_web_sem_fases.py`). Achado RANKINGS-6.

Cenário de `tests/test_ranking_fases_cobertura.py`: a Fase tem o MAIOR volume
de tudo, então, sem o corte, ela é a primeira. Dados fictícios.
"""
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import Professor, Usuario
from tests.test_ranking_fases_cobertura import cenario  # noqa: F401 (fixture)

API = "/api/v1"


def _sem_fase_e_numerado(itens, cenario):  # noqa: F811
    ids = [i["aluno_id"] for i in itens]
    assert not set(ids) & cenario["fases"], f"criança da Fase no Ranking de XP: {itens}"
    assert [i["posicao"] for i in itens] == list(range(1, len(itens) + 1))


def test_ranking_xp_da_gestao_sem_a_fase(cliente, cenario):  # noqa: F811
    r = cliente.get(f"{API}/escolas/{cenario['escola'].id}/gamificacao/ranking-xp")
    assert r.status_code == 200, r.text
    itens = r.json()
    # Não é uma lista vazia: quem concorre continua no ranking.
    assert cenario["do_fund"] <= {i["aluno_id"] for i in itens}
    _sem_fase_e_numerado(itens, cenario)


def test_ranking_xp_da_professora_da_fase_e_do_fundamental(db, cenario):  # noqa: F811
    """O escopo de acesso não muda (ela continua vendo as duas turmas no resto do
    sistema); no ranking só concorre o Fundamental, numerado 1..N."""
    escola = cenario["escola"]
    prof = Professor(escola_id=escola.id, nome="Professora Teste", email="prof@xp.local")
    db.add(prof)
    db.flush()
    cenario["fund"].professor_id = prof.id
    cenario["fase"].professor_id = prof.id
    db.add(Usuario(escola_id=escola.id, nome="Professora Teste", email="prof@xp.local",
                   senha_hash=hash_senha("s3nh4"), cargo="professor"))
    db.commit()
    cli = TestClient(app)
    r = cli.post(f"{API}/auth/login", data={"username": "prof@xp.local", "password": "s3nh4"})
    assert r.status_code == 200, r.text
    cli.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

    r = cli.get(f"{API}/escolas/{escola.id}/gamificacao/ranking-xp")
    assert r.status_code == 200, r.text
    itens = r.json()
    assert {i["aluno_id"] for i in itens} == cenario["do_fund"]
    _sem_fase_e_numerado(itens, cenario)
