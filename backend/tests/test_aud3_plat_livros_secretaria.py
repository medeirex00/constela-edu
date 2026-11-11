"""O catálogo de livros da escola não sai para a Secretaria (S_G_GRUPO-2).

O acervo da escola nasce da coleta, a partir das leituras das crianças, e o
``GET /escolas/{id}/livros`` devolve ``total``, os títulos e ``leituras`` por
livro. Numa escola em que só 1 (ou 2) crianças leram, isso é o histórico de
leitura delas — justamente o que o cartão da rede esconde pelo grupo pequeno.

DECISÃO TÉCNICA: a rota fica com quem é da escola (``deps.negar_secretaria``,
403, como as telas operacionais e nominais). A coordenação da escola e o Admin
Global seguem recebendo o catálogo inteiro, com as contagens. Dados fictícios.
"""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import Aluno, Leitura, Livro, Matricula, Rede, Turma, Usuario

API = "/api/v1"
SENHA = "s3nh4"
N_LIVROS = 37
LIDO_EM = datetime(2026, 9, 10, 10, 0)


def _login(email: str) -> TestClient:
    c = TestClient(app)
    r = c.post(f"{API}/auth/login", data={"username": email, "password": SENHA})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _escola_com_leitoras(db, escola_completa, leitoras: int) -> dict:
    """20 matriculados; só ``leitoras`` crianças leram (a 1ª, os 37 livros; as
    demais, os 5 primeiros). Secretaria nos dois cargos, coordenação da escola e
    Admin Global."""
    escola = escola_completa["escola"]
    ano = escola.ano_letivo_ativo
    turma = Turma(escola_id=escola.id, nome="4º Ano Ficticio", ano_escolar="4º Ano",
                  ano_letivo=ano)
    db.add(turma)
    db.flush()
    alunos = []
    for i in range(20):
        a = Aluno(escola_id=escola.id, nome=f"CRIANCA FICTICIA {i:02d}")
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id,
                         ano_letivo=ano))
        alunos.append(a)
    livros = [Livro(escola_id=escola.id, titulo=f"TITULO INVENTADO {j:02d}",
                    nivel_codigo="D") for j in range(N_LIVROS)]
    db.add_all(livros)
    db.flush()
    for k in range(leitoras):
        for livro in (livros if k == 0 else livros[:5]):
            db.add(Leitura(escola_id=escola.id, aluno_id=alunos[k].id, livro_id=livro.id,
                           data=LIDO_EM, tempo_leitura_min=10, nivel_codigo="D"))
    rede = Rede(nome="REDE FICTICIA DO CATALOGO", status="ativa")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    db.add_all([
        Usuario(escola_id=None, nome="SEC COORD", email="sec.coord@catalogo.local",
                senha_hash=hash_senha(SENHA), cargo="coordenador", rede_id=rede.id),
        Usuario(escola_id=None, nome="SEC ADMIN", email="sec.admin@catalogo.local",
                senha_hash=hash_senha(SENHA), cargo="admin", rede_id=rede.id),
        Usuario(escola_id=escola.id, nome="COORD", email="coord@catalogo.local",
                senha_hash=hash_senha(SENHA), cargo="coordenador"),
        Usuario(escola_id=escola.id, nome="GLOBAL", email="global@catalogo.local",
                senha_hash=hash_senha(SENHA), cargo="admin", is_global=True),
    ])
    db.commit()
    return {"escola_id": escola.id,
            "leituras": N_LIVROS + 5 * (leitoras - 1)}


@pytest.mark.parametrize("leitoras", [1, 2])
@pytest.mark.parametrize("email", ["sec.coord@catalogo.local", "sec.admin@catalogo.local"])
def test_secretaria_nao_recebe_o_catalogo_da_escola(db, escola_completa, leitoras, email):
    cena = _escola_com_leitoras(db, escola_completa, leitoras)
    url = f"{API}/escolas/{cena['escola_id']}/livros"
    sec = _login(email)
    for params in ({"por_pagina": 100}, {"busca": "INVENTADO", "por_pagina": 8},
                   {"divergentes": "true"}):
        r = sec.get(url, params=params)
        assert r.status_code == 403, (
            f"a Secretaria recebeu o catálogo da escola ({params}): {r.status_code} "
            f"{r.text[:300]}")
        corpo = r.json()
        assert "itens" not in corpo and "total" not in corpo, corpo
        assert "TITULO INVENTADO" not in r.text


@pytest.mark.parametrize("leitoras", [1, 2])
@pytest.mark.parametrize("email", ["coord@catalogo.local", "global@catalogo.local"])
def test_gestao_da_escola_e_admin_global_seguem_com_o_catalogo(db, escola_completa,
                                                               leitoras, email):
    cena = _escola_com_leitoras(db, escola_completa, leitoras)
    r = _login(email).get(f"{API}/escolas/{cena['escola_id']}/livros",
                          params={"por_pagina": 100})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["total"] == N_LIVROS
    assert len(corpo["itens"]) == N_LIVROS
    assert sum(i["leituras"] for i in corpo["itens"]) == cena["leituras"]
