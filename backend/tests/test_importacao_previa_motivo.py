"""A prévia (``/analisar``) manda o MOTIVO da correspondência que a tela usa (T1).

Revisão final: a tela de Importações decide pelo ``correspondencia.motivo`` se a
linha vai para Revisões de identidade (nome abreviado, duas contas com o mesmo
nome, possível duplicata…) em vez de "Criar". O motor monta o motivo
(``services.importacao._correspondencia``), mas ``CorrespondenciaOut`` não tinha o
campo e o Pydantic o descartava: com o backend real, a linha "Zefa Q" chegava como
``{status: "revisar"}`` sem motivo, a tela oferecia "Criar aluno novo…", contava a
linha como aluno novo — e o backend abria a pendência sem criar a ficha. Os testes
da tela passavam porque o mock montado à mão trazia o motivo.

Aqui o JSON é o da rota real, e o contrato confere cada campo que a interface
``Correspondencia`` do front (``packages/core/src/tipos.ts``) declara. O mesmo JSON
fica gravado para o teste da tela (``apps/web/src/test/fixtures/importacoes/``),
que o consome sem adaptação — como os exemplos da análise educacional
(``test_analise_fixtures``). Há um exemplo por caso (``EXEMPLOS``): o relatório
colado com o nome abreviado e o Placar do Matific com duas contas de mesmo nome.
Para regravar:
``GERAR_FIXTURES_IMPORTACAO=1 python -m pytest tests/test_importacao_previa_motivo.py``.
Dados fictícios.
"""
import json
import os
import pathlib
import re

import pytest

API = "/api/v1"
RAIZ = pathlib.Path(__file__).resolve().parents[2]
PASTA_EXEMPLOS_WEB = RAIZ / "apps" / "web" / "src" / "test" / "fixtures" / "importacoes"
EXEMPLO_WEB = PASTA_EXEMPLOS_WEB / "analise_matific_motivos.json"
GERAR = os.environ.get("GERAR_FIXTURES_IMPORTACAO") == "1"

TEXTO = """Relatório Matific — Turma 3º Ano A
Nome do aluno\tAtividades finalizadas\tPontuação média\tEstrelas
Ana Beatriz Souza\t42\t85,5\t120
Zefa Q\t10\t70\t35
Crianca Ficticia Sem Ficha\t11\t71\t36
Total\t63\t\t191
"""

# Placar do Matific (JSON da API interna) com DUAS CONTAS de mesmo nome, mesma sala e
# nenhuma ficha (motivo contas_repetidas_no_relatorio): o backend abre UMA pendência
# por conta, e a prévia da tela tem de contar as duas (Importacoes.tsx não junta
# numa linha só as contas de uuid diferente).
PLACAR_DUAS_CONTAS = json.dumps({"fonte": "matific-placar", "turma": "3º Ano A", "alunos": [
    {"nome": "Ana Beatriz Souza", "uuid": "uuid-ficticio-ana", "estrelas": 5, "atividades": 1},
    {"nome": "Crianca Ficticia Repetida", "uuid": "uuid-ficticio-1", "estrelas": 10,
     "atividades": 3},
    {"nome": "Crianca Ficticia Repetida", "uuid": "uuid-ficticio-2", "estrelas": 20,
     "atividades": 4},
]}, ensure_ascii=False)

# Exemplo gravado para a tela → texto enviado ao /analisar.
EXEMPLOS = {
    "analise_matific_motivos.json": TEXTO,
    "analise_matific_duas_contas.json": PLACAR_DUAS_CONTAS,
}

TIPOS_TS = RAIZ / "packages" / "core" / "src" / "tipos.ts"


def _analise(cliente, escola_id, texto: str = TEXTO) -> dict:
    r = cliente.post(f"{API}/escolas/{escola_id}/importacoes/analisar", data={"texto": texto})
    assert r.status_code == 200, r.text
    return r.json()


def _analisar(cliente, escola_id):
    return {linha["nome"]: linha["correspondencia"]
            for linha in _analise(cliente, escola_id)["linhas"]}


def test_nome_abreviado_chega_com_o_motivo_que_manda_para_a_revisao(cliente, escola_completa):
    corr = _analisar(cliente, escola_completa["escola"].id)
    assert corr["Zefa Q"]["status"] == "revisar"
    assert corr["Zefa Q"]["motivo"] == "nome_incompleto", corr["Zefa Q"]
    # Os outros casos também trazem o motivo (e o "via" do vínculo).
    assert corr["Ana Beatriz Souza"]["status"] == "exato"
    assert corr["Ana Beatriz Souza"]["via"] == "exato"
    assert corr["Crianca Ficticia Sem Ficha"]["status"] == "nao_encontrado"
    assert corr["Crianca Ficticia Sem Ficha"]["motivo"] == "novo"


def _campos_da_interface(fonte: str, nome: str) -> set[str]:
    corpo = re.search(r"export interface %s \{(.*?)\n\}" % nome, fonte, re.S)
    assert corpo, f"interface {nome} não encontrada em tipos.ts"
    return set(re.findall(r"^\s*(\w+)\??:", corpo.group(1), re.M))


@pytest.mark.skipif(not TIPOS_TS.exists(), reason="sem o front no checkout")
def test_contrato_cada_campo_que_o_front_le_vem_na_resposta(cliente, escola_completa):
    """Cada campo da interface ``Correspondencia`` do front vem no JSON real, em
    todos os status desta prévia (vínculo, revisão e aluno novo)."""
    campos = _campos_da_interface(TIPOS_TS.read_text(encoding="utf-8"), "Correspondencia")
    assert {"status", "motivo", "alternativas"} <= campos, campos
    for nome, corr in _analisar(cliente, escola_completa["escola"].id).items():
        faltam = campos - set(corr)
        assert not faltam, f"{nome}: o /analisar não manda {sorted(faltam)}"


def test_bloquear_o_criar_da_tela_vai_para_a_revisao(cliente, db, escola_completa):
    """O lado do backend do que a tela conta com a política 'bloquear'
    (Importacoes.test, "política 'bloquear'"): o corpo que ela manda com os destinos
    padrão — vínculo, "Deixar para a Revisão" e "Criar", as duas últimas com a turma —
    vincula 1, não cria ficha e abre 2 pendências. A tela diz "1 de 3 serão
    importados; 2 vão para Revisões"."""
    from sqlalchemy import func, select

    from app.models import Aluno
    from app.services import politica_sync

    eid, turma = escola_completa["escola"].id, escola_completa["turma"].id
    politica_sync.definir(db, eid, "bloquear")
    db.commit()
    analise = _analise(cliente, eid)
    assert analise["criacao_bloqueada_por_politica"] is True
    linhas = []
    for linha in analise["linhas"]:
        corr = linha["correspondencia"]
        vinculo = corr["aluno_id"] if corr["status"] in ("exato", "vinculado") else None
        linhas.append({"nome": linha["nome"], "dados": linha["dados"], "aluno_id": vinculo,
                       "criar_em_turma_id": None if vinculo else turma})
    antes = db.scalar(select(func.count()).select_from(Aluno).where(Aluno.escola_id == eid))
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/confirmar", json={
        "plataforma": analise["plataforma"], "formato": analise["formato"], "tipo": "texto",
        "recalcular": False, "linhas": linhas, "data_referencia": "2026-08-14T12:00:00"})
    assert r.status_code == 200, r.text
    assert (r.json()["qtd_alunos"], r.json()["qtd_revisoes"]) == (1, 2), r.json()
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Aluno)
                     .where(Aluno.escola_id == eid)) == antes


def test_duas_contas_com_o_mesmo_nome_abrem_uma_pendencia_por_conta(cliente, db,
                                                                   escola_completa):
    """O lado do backend do que a tela conta com duas contas de mesmo nome
    (Importacoes.test, "duas contas com o mesmo nome"): a prévia mostra UMA linha por
    conta e diz "1 de 3 serão importados; 2 vão para Revisões"; o corpo que ela manda
    com os destinos padrão (vínculo e "Deixar para a Revisão", com a turma) vincula 1,
    não cria ficha e abre 2 pendências — uma por conta. Antes a tela juntava as duas
    contas numa linha (chave nome|turma) e dizia "1 vai para Revisões"."""
    from sqlalchemy import func, select

    from app.models import Aluno, RevisaoIdentidade

    eid, turma = escola_completa["escola"].id, escola_completa["turma"].id
    analise = _analise(cliente, eid, PLACAR_DUAS_CONTAS)
    repetidas = [linha for linha in analise["linhas"]
                 if linha["correspondencia"]["motivo"] == "contas_repetidas_no_relatorio"]
    assert sorted(linha["dados"]["matific_uuid"] for linha in repetidas) == [
        "uuid-ficticio-1", "uuid-ficticio-2"]
    linhas = []
    for linha in analise["linhas"]:
        corr = linha["correspondencia"]
        vinculo = corr["aluno_id"] if corr["status"] in ("exato", "vinculado") else None
        linhas.append({"nome": linha["nome"], "dados": linha["dados"], "aluno_id": vinculo,
                       "criar_em_turma_id": None if vinculo else turma})
    antes = db.scalar(select(func.count()).select_from(Aluno).where(Aluno.escola_id == eid))
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/confirmar", json={
        "plataforma": analise["plataforma"], "formato": analise["formato"], "tipo": "texto",
        "recalcular": False, "linhas": linhas, "data_referencia": "2026-08-14T12:00:00"})
    assert r.status_code == 200, r.text
    assert (r.json()["qtd_alunos"], r.json()["qtd_revisoes"]) == (1, len(repetidas)), r.json()
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Aluno)
                     .where(Aluno.escola_id == eid)) == antes
    contas = db.execute(select(RevisaoIdentidade.motivo, RevisaoIdentidade.id_externo)
                        .where(RevisaoIdentidade.escola_id == eid)).all()
    assert sorted(contas) == [("contas_repetidas_no_relatorio", "uuid-ficticio-1"),
                              ("contas_repetidas_no_relatorio", "uuid-ficticio-2")]


def _o_que_a_tela_le(analise: dict) -> list:
    """O que a tela lê de cada linha: o nome, os dados (turma do relatório e a conta
    da plataforma decidem como as linhas viram linhas da prévia) e a correspondência
    (status, motivo, via…). Ids de ficha ficam fora: dependem do banco."""
    return [(linha["nome"], linha["dados"],
             {k: v for k, v in linha["correspondencia"].items()
              if k not in ("aluno_id", "alternativas")})
            for linha in analise["linhas"]]


@pytest.mark.parametrize("arquivo", sorted(EXEMPLOS))
def test_exemplo_da_tela_e_a_resposta_real(cliente, escola_completa, arquivo):
    """O exemplo que o teste da tela usa é a resposta de agora do /analisar: as mesmas
    chaves no topo e, em cada linha, o mesmo nome, os mesmos dados e a mesma
    correspondência (status, motivo, via…)."""
    real = _analise(cliente, escola_completa["escola"].id, EXEMPLOS[arquivo])
    exemplo = PASTA_EXEMPLOS_WEB / arquivo
    if GERAR:
        exemplo.parent.mkdir(parents=True, exist_ok=True)
        exemplo.write_text(json.dumps(real, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8", newline="\n")
    if not exemplo.parent.parent.exists():
        pytest.skip("cópia sem apps/web: o exemplo da tela não está aqui")
    assert exemplo.exists(), "falta o exemplo da tela: regrave com GERAR_FIXTURES_IMPORTACAO=1"
    gravado = json.loads(exemplo.read_text(encoding="utf-8"))
    assert set(gravado) == set(real), sorted(set(gravado) ^ set(real))
    assert _o_que_a_tela_le(gravado) == _o_que_a_tela_le(real), (
        "o exemplo da tela está defasado: regrave com GERAR_FIXTURES_IMPORTACAO=1")
