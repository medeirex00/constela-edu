"""Custo das rotas de RANKING em consultas ao banco — sem N+1.

Conta as consultas (``before_cursor_execute``) de cada rota de ranking numa
escola PEQUENA e numa escola com o QUÁDRUPLO de alunos e de turmas. Rota sem
N+1 custa o MESMO número de consultas nos dois tamanhos: o volume só pode
mudar o tamanho das linhas devolvidas, nunca a quantidade de idas ao banco.

Dados inventados ("Aluno Teste N"); nenhum nome em saída de benchmark.
"""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.core.security import hash_senha
from app.main import app
from app.models import (
    Aluno,
    Configuracao,
    Escola,
    Importacao,
    Leitura,
    Livro,
    Matricula,
    Rede,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
    Usuario,
)
from app.services import scoring

API = "/api/v1"

ROTAS_ESCOLA = [
    ("ranking", {}),
    ("ranking", {"dimensao": "leitura"}),
    ("ranking", {"dimensao": "matematica", "turno": "manha"}),
    ("ranking/leitura", {}),
    ("ranking/leitura", {"periodo": "mes"}),
    ("ranking/matematica", {}),
    ("ranking/leitura/turnos", {}),
    ("premiacoes", {"periodo": "ano_letivo", "turnos": True}),
    ("ranking-evolucao", {}),
    ("ranking-evolucao", {"dimensao": "leitura"}),
    ("ranking/turmas", {"dimensao": "leitura"}),
    ("ranking/frescor", {}),
    ("nao-aferidos", {}),
    ("dashboard", {}),
]


def _escola(db, rede, nome, n_turmas, por_turma):
    escola = Escola(nome=nome, ano_letivo_ativo=2026, rede_id=rede.id, status="ativa")
    db.add(escola)
    db.flush()
    for ns, valores in scoring.PESOS_PADRAO.items():
        db.add(Configuracao(escola_id=escola.id, namespace=ns, chave="valores", valor=valores))
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(imp)
    livros = [Livro(escola_id=escola.id, titulo=f"Livro Teste {nome} {i}", nivel_codigo="D")
              for i in range(3)]
    db.add_all(livros)
    db.flush()
    agora = datetime.now().replace(microsecond=0)
    k = 0
    for t in range(n_turmas):
        turma = Turma(escola_id=escola.id, nome=f"{t % 5 + 1}º Ano {t}",
                      ano_escolar=f"{t % 5 + 1}º Ano", ano_letivo=2026,
                      turno="manha" if t % 2 else "tarde", status="ativa")
        db.add(turma)
        db.flush()
        for _ in range(por_turma):
            k += 1
            a = Aluno(escola_id=escola.id, nome=f"Aluno Teste {k}", status="ativo")
            db.add(a)
            db.flush()
            db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id,
                             ano_letivo=2026))
            for dias, fator in ((20, 1), (2, 2)):
                quando = agora - timedelta(days=dias)
                db.add(SnapshotElefante(escola_id=escola.id, aluno_id=a.id, importacao_id=imp.id,
                                        data_referencia=quando, livros_unicos=k % 4 * fator,
                                        tempo_leitura_min=10 * fator,
                                        livros_por_nivel={"D": k % 4 * fator}))
                db.add(SnapshotMatific(escola_id=escola.id, aluno_id=a.id, importacao_id=imp.id,
                                       data_referencia=quando, atividades=k % 5 * fator,
                                       estrelas=2 * (k % 5) * fator, pontuacao_media=2.0))
            db.add(Leitura(escola_id=escola.id, aluno_id=a.id, livro_id=livros[k % 3].id,
                           data=agora - timedelta(days=3), tempo_leitura_min=15,
                           nivel_codigo="D"))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    return escola


@pytest.fixture()
def mundo(db, escola_completa):
    rede = Rede(nome="Rede Teste Custo", status="ativa")
    db.add(rede)
    db.flush()
    pequena = _escola(db, rede, "ESCOLA PEQUENA", n_turmas=2, por_turma=4)
    grande = _escola(db, rede, "ESCOLA GRANDE", n_turmas=8, por_turma=8)
    db.add(Usuario(escola_id=None, nome="Admin Global Custo", email="global@custo.local",
                   senha_hash=hash_senha("s3nh4"), cargo="admin", is_global=True))
    db.commit()
    cli = TestClient(app)
    r = cli.post(f"{API}/auth/login", data={"username": "global@custo.local", "password": "s3nh4"})
    assert r.status_code == 200, r.text
    cli.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return {"cli": cli, "rede": rede, "pequena": pequena.id, "grande": grande.id}


def _contar(db, chamada):
    engine, n = db.get_bind(), [0]

    def _conta(*_a, **_k):
        n[0] += 1

    event.listen(engine, "before_cursor_execute", _conta)
    try:
        resposta = chamada()
    finally:
        event.remove(engine, "before_cursor_execute", _conta)
    assert resposta.status_code == 200, resposta.text
    return n[0]


@pytest.mark.parametrize("rota,params", ROTAS_ESCOLA)
def test_rota_de_ranking_da_escola_nao_cresce_com_alunos_nem_turmas(db, mundo, rota, params):
    cli = mundo["cli"]
    pequena = _contar(db, lambda: cli.get(f"{API}/escolas/{mundo['pequena']}/{rota}",
                                          params=params))
    grande = _contar(db, lambda: cli.get(f"{API}/escolas/{mundo['grande']}/{rota}",
                                         params=params))
    print(f"\n{rota} {params}: 8 alunos/2 turmas = {pequena}; 64 alunos/8 turmas = {grande}")
    assert grande == pequena, (rota, params, pequena, grande)


@pytest.mark.parametrize("rota", ["ranking", "ranking/frescor", "dashboard"])
def test_rotas_de_ranking_da_rede_nao_crescem_com_escolas(db, mundo, rota):
    cli = mundo["cli"]
    rede_id = mundo["rede"].id
    duas = _contar(db, lambda: cli.get(f"{API}/redes/{rede_id}/{rota}"))
    # Mais duas escolas na mesma rede.
    for i in range(2):
        _escola(db, mundo["rede"], f"ESCOLA EXTRA {i}", n_turmas=2, por_turma=4)
    quatro = _contar(db, lambda: cli.get(f"{API}/redes/{rede_id}/{rota}"))
    print(f"\n/redes/{{id}}/{rota}: 2 escolas = {duas}; 4 escolas = {quatro}")
    assert quatro == duas, (rota, duas, quatro)
