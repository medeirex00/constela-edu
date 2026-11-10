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

# Placar do Matific com um aluno por MOTIVO de revisão que a prévia pode mandar (os
# que um Placar consegue produzir; o RA não vem nele), além do vínculo e do aluno
# novo. A tela dá a cada motivo um rótulo próprio — não "Possível duplicata" para
# tudo. O cenário do banco é o de ``_preparar_motivos``.
PLACAR_MOTIVOS = json.dumps({"fonte": "matific-placar", "turma": "3º Ano A", "alunos": [
    {"nome": "Ana Beatriz Souza", "uuid": "uuid-ficticio-ana", "estrelas": 5, "atividades": 1},
    {"nome": "Sofia Almeida Durte", "uuid": "uuid-ficticio-s", "estrelas": 9, "atividades": 2},
    {"nome": "Davi Ficticio", "uuid": "uuid-ficticio-davi", "estrelas": 9, "atividades": 2},
    {"nome": "Lara Ficticia Brandao", "uuid": "uuid-ficticio-lara", "estrelas": 9,
     "atividades": 2},
    {"nome": "Teo Ficticio", "uuid": "uuid-ficticio-teo", "estrelas": 9, "atividades": 2},
    {"nome": "Heitor Fictorino Lemos", "uuid": "uuid-ficticio-h", "estrelas": 9,
     "atividades": 2},
    {"nome": "Iara Ficticia Neves", "uuid": "uuid-ficticio-iara", "estrelas": 9,
     "atividades": 2},
    {"nome": "Joao Pedro Barbosa", "uuid": "uuid-ficticio-jp", "estrelas": 9, "atividades": 2},
    {"nome": "Crianca Ficticia Um", "uuid": "uuid-ficticio-dup", "estrelas": 7, "atividades": 2},
    {"nome": "Crianca Ficticia Dois", "uuid": "uuid-ficticio-dup", "estrelas": 8,
     "atividades": 2},
    {"nome": "Bento Ficticio Moura", "uuid": "uuid-ficticio-outra-escola", "estrelas": 9,
     "atividades": 2},
    # O conector não achou o nome cheio: só o abreviado do Placar (marca nome_incompleto
    # nos dados, que a coluna Dados da tela não mostra).
    {"nome": "Zefa Q", "nome_abrev": "Zefa Q", "uuid": "uuid-ficticio-z", "estrelas": 9,
     "atividades": 2},
    {"nome": "Crianca Ficticia Repetida", "uuid": "uuid-ficticio-1", "estrelas": 10,
     "atividades": 3},
    {"nome": "Crianca Ficticia Repetida", "uuid": "uuid-ficticio-2", "estrelas": 20,
     "atividades": 4},
    {"nome": "Crianca Nova Ficticia", "uuid": "uuid-ficticio-nova", "estrelas": 9,
     "atividades": 2},
]}, ensure_ascii=False)

# O motivo que cada linha do PLACAR_MOTIVOS recebe (status "revisar", salvo o vínculo
# e o aluno novo).
MOTIVO_ESPERADO = {
    "Ana Beatriz Souza": ("exato", "exato"),
    "Sofia Almeida Durte": ("revisar", "correspondencia_insegura"),
    "Davi Ficticio": ("revisar", "candidatos_multiplos"),
    "Lara Ficticia Brandao": ("revisar", "homonimo_em_outra_sala"),
    "Teo Ficticio": ("revisar", "nome_casa_em_outra_sala"),
    "Heitor Fictorino Lemos": ("revisar", "ficha_inativa"),
    "Iara Ficticia Neves": ("revisar", "identidade_de_ficha_inativa"),
    "Joao Pedro Barbosa": ("revisar", "outra_identidade_na_plataforma"),
    "Crianca Ficticia Um": ("revisar", "id_externo_duplicado"),
    "Crianca Ficticia Dois": ("revisar", "id_externo_duplicado"),
    "Bento Ficticio Moura": ("revisar", "identidade_de_outra_escola"),
    "Zefa Q": ("revisar", "nome_incompleto"),
    "Crianca Ficticia Repetida": ("revisar", "contas_repetidas_no_relatorio"),
    "Crianca Nova Ficticia": ("nao_encontrado", "novo"),
}


def _preparar_motivos(db, escola_completa) -> None:
    """O banco que faz cada linha do PLACAR_MOTIVOS cair no seu motivo (fictício)."""
    from app.models import Aluno, Escola, IdentidadeExterna, Matricula, Turma

    escola, turma = escola_completa["escola"], escola_completa["turma"]
    outra_turma = Turma(escola_id=escola.id, nome="4º Ano B", ano_escolar="4º Ano",
                        ano_letivo=2026)
    db.add(outra_turma)
    db.flush()

    def ficha(nome, sala, status="ativo"):
        aluno = Aluno(escola_id=escola.id, nome=nome, status=status)
        db.add(aluno)
        db.flush()
        db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id, turma_id=sala.id,
                         ano_letivo=2026))
        return aluno

    ficha("Davi Ficticio Rocha", turma)                      # candidatos_multiplos
    ficha("Davi Ficticio Lima", turma)
    ficha("Lara Ficticia Brandao", outra_turma)              # homonimo_em_outra_sala
    ficha("Teo Ficticio Andrade", outra_turma)               # nome_casa_em_outra_sala
    ficha("Heitor Fictorino Lemos", turma, "arquivado")      # ficha_inativa
    iara = ficha("Iara Ficticia Neves", turma, "arquivado")  # identidade_de_ficha_inativa
    db.add(IdentidadeExterna(escola_id=escola.id, aluno_id=iara.id, plataforma="matific",
                             id_externo="uuid-ficticio-iara"))
    joao = next(a for a in escola_completa["alunos"] if a.nome == "João Pedro Barbosa")
    db.add(IdentidadeExterna(escola_id=escola.id, aluno_id=joao.id, plataforma="matific",
                             id_externo="uuid-ficticio-jp-antiga"))  # outra conta
    outra = Escola(nome="OUTRA ESCOLA FICTICIA", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    bento = Aluno(escola_id=outra.id, nome="Bento Ficticio Moura")
    db.add(bento)
    db.flush()
    db.add(IdentidadeExterna(escola_id=outra.id, aluno_id=bento.id, plataforma="matific",
                             id_externo="uuid-ficticio-outra-escola"))
    db.commit()


# Exemplo gravado para a tela → (texto enviado ao /analisar, cenário do banco).
EXEMPLOS = {
    "analise_matific_motivos.json": (TEXTO, None),
    "analise_matific_duas_contas.json": (PLACAR_DUAS_CONTAS, None),
    "analise_matific_placar_motivos.json": (PLACAR_MOTIVOS, _preparar_motivos),
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


def test_placar_traz_um_aluno_por_motivo(cliente, db, escola_completa):
    """O exemplo dos motivos cobre o que diz cobrir: cada linha cai no seu motivo."""
    _preparar_motivos(db, escola_completa)
    analise = _analise(cliente, escola_completa["escola"].id, PLACAR_MOTIVOS)
    obtido = {linha["nome"]: (linha["correspondencia"]["status"],
                              linha["correspondencia"]["motivo"])
              for linha in analise["linhas"]}
    assert obtido == MOTIVO_ESPERADO


def test_cada_motivo_do_backend_tem_rotulo_na_tela():
    """Contrato: cada motivo de revisão do backend (``identidade_aluno.MOTIVOS``) tem
    rótulo e explicação próprios na prévia de Importações (``MOTIVO_REVISAO`` em
    Importacoes.tsx). Um motivo novo sem rótulo voltaria a aparecer como "Requer
    revisão", sem dizer o porquê."""
    from app.services.identidade_aluno import MOTIVOS

    tela = RAIZ / "apps" / "web" / "src" / "pages" / "Importacoes.tsx"
    if not tela.exists():
        pytest.skip("cópia sem apps/web")
    bloco = re.search(r"const MOTIVO_REVISAO[^=]*= \{(.*?)\n\};", tela.read_text(encoding="utf-8"),
                      re.S)
    assert bloco, "MOTIVO_REVISAO não encontrado em Importacoes.tsx"
    na_tela = set(re.findall(r"^  (\w+): \{", bloco.group(1), re.M))
    assert not set(MOTIVOS) - na_tela, sorted(set(MOTIVOS) - na_tela)


@pytest.mark.parametrize("arquivo", sorted(EXEMPLOS))
def test_exemplo_da_tela_e_a_resposta_real(cliente, db, escola_completa, arquivo):
    """O exemplo que o teste da tela usa é a resposta de agora do /analisar: as mesmas
    chaves no topo e, em cada linha, o mesmo nome, os mesmos dados e a mesma
    correspondência (status, motivo, via…)."""
    texto, preparar = EXEMPLOS[arquivo]
    if preparar is not None:
        preparar(db, escola_completa)
    real = _analise(cliente, escola_completa["escola"].id, texto)
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
