"""Número gigante ou texto longo demais num relatório não vira "Erro interno".

A prévia aceitava qualquer valor e o /confirmar gravava sem conferir o tamanho das
colunas: uma contagem acima do ``integer`` (o RA ou o telefone caído na coluna de
atividades), um nome com mais de 200 caracteres, uma conta da plataforma com mais de
80 ou uma turma com mais de 100 davam 500 no PostgreSQL (o SQLite dos testes aceita
tudo e escondia). Agora a prévia mostra o valor como ilegível (número) ou a linha com
erro (texto), e a confirmação recusa o número com 400 e ignora a linha de texto longo,
com aviso — nada é gravado pela metade. As mesmas regras rodam no PostgreSQL em
``test_aud_imp_valores_fora_da_coluna_pg.py``. Dados fictícios.
"""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import app
from app.models import Aluno, IdentidadeExterna, Importacao, Turma

API = "/api/v1"
CABECALHO = ("Relatório Matific — Turma 3º Ano A\n"
             "Nome do aluno\tAtividades finalizadas\tPontuação média\tEstrelas\n")
NOME_LONGO = "Crianca " + " ".join(["Ficticiaxx"] * 20)          # 228 caracteres
CONTA_LONGA = "u" * 100
TURMA_LONGA = "Turma " + " ".join(["Ficticiaxx"] * 11)           # 126 caracteres


def _cliente_sem_excecao(cliente) -> TestClient:
    c = TestClient(app, raise_server_exceptions=False)
    c.headers.update(cliente.headers)
    return c


def _previa(cliente, escola_id, texto):
    r = _cliente_sem_excecao(cliente).post(
        f"{API}/escolas/{escola_id}/importacoes/analisar", data={"texto": texto})
    assert r.status_code == 200, r.text[:300]
    return r.json()


def test_previa_mostra_numero_gigante_como_ilegivel(cliente, escola_completa):
    eid = escola_completa["escola"].id
    linha = _previa(cliente, eid, CABECALHO + "Ana Beatriz Souza\t12345678901\t85\t120\n"
                    )["linhas"][0]
    assert "atividades" not in linha["dados"]
    assert any("ilegível" in a for a in linha["avisos"]), linha["avisos"]
    assert linha["dados"]["estrelas"] == 120


@pytest.mark.parametrize("valor", ["NaN", "inf", "-inf", "1e400"])
def test_previa_mostra_valor_nao_finito_como_ilegivel(cliente, escola_completa, valor):
    eid = escola_completa["escola"].id
    linha = _previa(cliente, eid, CABECALHO + f"Ana Beatriz Souza\t42\t{valor}\t120\n"
                    )["linhas"][0]
    assert "pontuacao_media" not in linha["dados"]
    assert linha["dados"]["atividades"] == 42


@pytest.mark.parametrize("valor", ["12345678901", "Infinity", "1e400"])
def test_previa_do_placar_nao_aceita_contagem_absurda(cliente, escola_completa, valor):
    eid = escola_completa["escola"].id
    texto = ('{"fonte": "matific-placar", "turma": "3º Ano A", "alunos": [{"nome": '
             f'"Ana Beatriz Souza", "uuid": "uuid-ana", "estrelas": 7, "atividades": {valor}}}]}}')
    analise = _previa(cliente, eid, texto)
    linha = analise["linhas"][0]
    assert "atividades" not in linha["dados"]
    assert linha["dados"]["estrelas"] == 7


@pytest.mark.parametrize("valor", [12345678901, float("inf"), "1e400"])
def test_confirmar_recusa_contagem_absurda_com_400(cliente, db, escola_completa, valor):
    eid = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    corpo = {
        "plataforma": "matific", "formato": "resumo", "tipo": "texto",
        "data_referencia": "2026-08-14T12:00:00", "recalcular": False,
        "linhas": [{"nome": ana.nome, "aluno_id": ana.id,
                    "dados": {"atividades": valor, "estrelas": 3}}]}
    # json.dumps escreve ``Infinity`` (o json.loads do servidor o aceita); o httpx não.
    r = _cliente_sem_excecao(cliente).post(
        f"{API}/escolas/{eid}/importacoes/confirmar", content=json.dumps(corpo),
        headers={"Content-Type": "application/json"})
    assert r.status_code == 400, r.text[:300]
    assert "valor numérico inválido" in r.json()["detail"]
    db.expire_all()
    assert db.execute(select(func.count()).select_from(Importacao)).scalar_one() == 0


def _placar(nome=None, conta=None, turma=None) -> str:
    aluno = {"nome": nome or "Crianca Ficticia Nova", "uuid": conta or "uuid-fict-nova",
             "estrelas": 1, "atividades": 1}
    return json.dumps({"fonte": "matific-placar", "turma": turma or "3º Ano A",
                       "alunos": [aluno]})


CASOS_LONGOS = {
    "nome": ({"nome": NOME_LONGO}, "Nome"),
    "conta": ({"conta": CONTA_LONGA}, "conta"),
    "turma": ({"turma": TURMA_LONGA}, "turma"),
}


@pytest.mark.parametrize("caso", sorted(CASOS_LONGOS))
def test_previa_marca_a_linha_com_texto_longo_demais(cliente, escola_completa, caso):
    eid = escola_completa["escola"].id
    campos, palavra = CASOS_LONGOS[caso]
    analise = _previa(cliente, eid, _placar(**campos))
    linha = analise["linhas"][0]
    assert linha["erros"], linha
    assert any(palavra in e for e in linha["erros"]), linha["erros"]
    assert analise["total_erros"] == 1


@pytest.mark.parametrize("caso", sorted(CASOS_LONGOS))
def test_confirmar_ignora_a_linha_com_texto_longo_demais(cliente, db, escola_completa,
                                                         caso):
    eid = escola_completa["escola"].id
    turma = escola_completa["turma"]
    campos, _palavra = CASOS_LONGOS[caso]
    nome = campos.get("nome", "Crianca Ficticia Nova")
    dados = {"estrelas": 1, "atividades": 1,
             "matific_uuid": campos.get("conta", "uuid-fict-nova"),
             "turma_relatorio": campos.get("turma", "3º Ano A")}
    linha = {"nome": nome, "dados": dados, "aluno_id": None,
             "criar_em_turma_id": None if caso == "turma" else turma.id,
             "criar_em_turma_nome": TURMA_LONGA if caso == "turma" else None}
    r = _cliente_sem_excecao(cliente).post(f"{API}/escolas/{eid}/importacoes/confirmar", json={
        "plataforma": "matific", "formato": "resumo", "tipo": "texto",
        "data_referencia": "2026-08-14T12:00:00", "recalcular": False,
        "linhas": [linha, {"nome": "Ana Beatriz Souza",
                           "aluno_id": escola_completa["alunos"][0].id,
                           "dados": {"atividades": 4, "estrelas": 9}}]})
    assert r.status_code == 200, r.text[:300]
    corpo = r.json()
    assert corpo["qtd_alunos"] == 1                   # a linha válida entrou
    assert any("ignorada" in a for a in corpo["avisos"]), corpo["avisos"]
    db.expire_all()
    assert db.execute(select(Aluno).where(Aluno.nome == nome)).first() is None
    assert db.execute(select(IdentidadeExterna).where(
        func.length(IdentidadeExterna.id_externo) > 80)).first() is None
    assert db.execute(select(Turma).where(func.length(Turma.nome) > 100)).first() is None
