"""Simulador alinhado ao motor: a MESMA régua de ``scoring.recalcular_escola``.

O furo: o Simulador (Métricas → Simulador) lia os pesos da CONFIGURAÇÃO LOCAL
(``obter_pesos``) enquanto o motor, no perfil institucional (padrão), ignora a
config local e usa a régua fixa da rede. O mesmo aluno aparecia com uma nota no
simulador e outra na premiação/ranking.

O que estes testes travam — sem segunda fórmula (o simulador chama as mesmas
funções do motor):
  * perfil INSTITUCIONAL com pesos locais 20/60/20 (e demais namespaces
    divergentes) e referência MANUAL gravada: o simulador devolve exatamente a
    nota que o recálculo grava para um aluno com os mesmos dados, com os pesos
    institucionais e a referência automática;
  * perfil PERSONALIZADO: o simulador usa a config local — e continua batendo
    com o recálculo;
  * a resposta diz qual régua usou (``perfil``);
  * ``pontuacao_media`` na escala do Matific (0–5).
"""
from datetime import date, datetime, time
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import (
    Configuracao,
    Importacao,
    Leitura,
    Livro,
    Nota,
    ReferenciaNormalizacao,
    SnapshotElefante,
    SnapshotMatific,
)
from app.services import scoring

# Config LOCAL deliberadamente diferente da institucional em TODOS os namespaces.
PESOS_LOCAIS = {
    "pesos.matific": {"atividades": 20.0, "media": 60.0, "estrelas": 20.0},
    "pesos.elefante": {"livros": 10.0, "dificuldade": 10.0, "questoes": 10.0, "tempo": 70.0},
    "pesos.questoes": {"tentativas": 90.0, "acertos": 10.0},
    "pesos.geral": {"matific": 80.0, "elefante": 20.0},
}
REFS_MANUAIS = {"max_atividades": 100, "max_media": 5, "max_estrelas": 500}

# nome → (matific, elefante). Pontuação média na escala do Matific (0–5).
DADOS = {
    "Ana Beatriz Souza": (
        {"atividades": 60, "estrelas": 250, "pontuacao_media": 4.5},
        {"livros_unicos": 12, "tempo_leitura_min": 650, "questoes_tentativas": 30,
         "questoes_acertos": 27, "livros_por_nivel": {"AA": 8, "D": 4}}),
    "João Pedro Barbosa": (
        {"atividades": 30, "estrelas": 120, "pontuacao_media": 3.2},
        {"livros_unicos": 5, "tempo_leitura_min": 200, "questoes_tentativas": 20,
         "questoes_acertos": 12, "livros_por_nivel": {"AA": 2, "D": 3}}),
    "Sofia Almeida Duarte": (
        {"atividades": 10, "estrelas": 40, "pontuacao_media": 2.0},
        {"livros_unicos": 2, "tempo_leitura_min": 60, "questoes_tentativas": 5,
         "questoes_acertos": 3, "livros_por_nivel": {"AA": 2}}),
}
# O aluno do meio: nota longe de 0 e de 100, onde o peso muda o número.
ALVO = "João Pedro Barbosa"


def _montar(db, escola_completa, *, personalizado: bool):
    """Snapshots dos 3 alunos + config local divergente; recalcula pelo motor e
    devolve ``(escola, Nota do ALVO)``."""
    escola = escola_completa["escola"]
    importacao = Importacao(escola_id=escola.id, plataforma="matific", tipo="seed")
    db.add(importacao)
    db.flush()
    for aluno in escola_completa["alunos"]:
        matific, elefante = DADOS[aluno.nome]
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id,
                               importacao_id=importacao.id, **matific))
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id,
                                importacao_id=importacao.id, **elefante))
    for namespace, valores in PESOS_LOCAIS.items():
        linha = db.execute(select(Configuracao).where(
            Configuracao.escola_id == escola.id, Configuracao.namespace == namespace,
            Configuracao.chave == "valores")).scalar_one()
        linha.valor = dict(valores)
    referencia = db.execute(select(ReferenciaNormalizacao).where(
        ReferenciaNormalizacao.escola_id == escola.id)).scalar_one()
    referencia.modo = "manual"
    referencia.valores_manuais = dict(REFS_MANUAIS)
    if personalizado:
        db.add(Configuracao(escola_id=escola.id, namespace=scoring.PERFIL_SCORING_NS,
                            chave="modo", valor="personalizado"))
    db.commit()

    scoring.recalcular_escola(db, escola.id)
    db.expire_all()
    alvo = next(a for a in escola_completa["alunos"] if a.nome == ALVO)
    nota = db.execute(select(Nota).where(Nota.aluno_id == alvo.id)).scalar_one()
    return escola, nota


def _simular(cliente, escola_id: int) -> dict:
    """Aluno HIPOTÉTICO com exatamente os dados do ALVO (mesma série)."""
    matific, elefante = DADOS[ALVO]
    r = cliente.post(f"/api/v1/escolas/{escola_id}/simulador", json={
        "ano_escolar": "3º Ano", **matific, **{
            chave: valor for chave, valor in elefante.items() if chave != "livros_unicos"},
    })
    assert r.status_code == 200, r.text
    return r.json()


def _pesos(linhas: list[dict]) -> list[float]:
    return [linha["peso"] for linha in linhas]


def _conferir_paridade(corpo: dict, nota: Nota) -> None:
    """O simulador devolve o que o motor gravou — nota e explicação."""
    assert corpo["matific"]["nota"] == pytest.approx(nota.nota_matific, abs=1e-9)
    assert corpo["elefante"]["nota"] == pytest.approx(nota.nota_elefante, abs=1e-9)
    assert corpo["geral"]["nota"] == pytest.approx(nota.nota_geral, abs=1e-9)
    assert corpo["modo_normalizacao"] == nota.detalhes["modo_normalizacao"]
    assert corpo["referencias"] == pytest.approx(nota.detalhes["referencias"])
    assert _pesos(corpo["matific"]["indicadores"]) == _pesos(
        nota.detalhes["matific"]["indicadores"])
    assert _pesos(corpo["elefante"]["indicadores"]) == _pesos(
        nota.detalhes["elefante"]["indicadores"])
    assert corpo["geral"]["pesos"] == nota.detalhes["geral"]["pesos"]


def test_institucional_bate_com_o_recalculo_e_ignora_a_config_local(cliente, db, escola_completa):
    escola, nota = _montar(db, escola_completa, personalizado=False)

    corpo = _simular(cliente, escola.id)

    assert corpo["perfil"] == "institucional"
    _conferir_paridade(corpo, nota)
    # Pesos INSTITUCIONAIS, não os locais (20/60/20 etc.).
    assert _pesos(corpo["matific"]["indicadores"]) == [40.0, 35.0, 25.0]
    assert _pesos(corpo["elefante"]["indicadores"]) == [35.0, 30.0, 30.0, 5.0]
    assert corpo["elefante"]["questoes"]["tentativas"]["peso"] == 30.0
    assert corpo["elefante"]["questoes"]["acertos"]["peso"] == 70.0
    assert corpo["geral"]["pesos"] == {"matific": 50.0, "elefante": 50.0}
    # Referência MANUAL gravada é ignorada: régua automática (máximo, < 8 alunos).
    assert corpo["modo_normalizacao"] == "auto"
    assert corpo["referencias"]["max_atividades"] == 60

    # O teste discrimina: com os pesos LOCAIS a nota seria outra.
    locais = PESOS_LOCAIS["pesos.matific"]
    fracoes = {chave: valor / 100.0 for chave, valor in locais.items()}
    com_locais, _ = scoring.calcular_matific(
        SimpleNamespace(**DADOS[ALVO][0]), corpo["referencias"], fracoes, locais, {})
    assert abs(com_locais - nota.nota_matific) > 1.0


def test_personalizado_usa_a_config_local_e_bate_com_o_recalculo(cliente, db, escola_completa):
    escola, nota = _montar(db, escola_completa, personalizado=True)

    corpo = _simular(cliente, escola.id)

    assert corpo["perfil"] == "personalizado"
    _conferir_paridade(corpo, nota)
    assert _pesos(corpo["matific"]["indicadores"]) == [20.0, 60.0, 20.0]
    assert _pesos(corpo["elefante"]["indicadores"]) == [10.0, 10.0, 10.0, 70.0]
    assert corpo["geral"]["pesos"] == {"matific": 80.0, "elefante": 20.0}
    assert corpo["modo_normalizacao"] == "manual"
    assert corpo["referencias"]["max_atividades"] == 100


def test_personalizado_com_bonus_de_leitura_na_escola_bate_com_o_recalculo(
        cliente, db, escola_completa):
    """Bônus de "livro lido NA ESCOLA" (só no perfil personalizado): o motor soma
    esse bônus em ``pontos_dif`` ANTES de calcular as referências. O simulador tem
    de usar a MESMA soma — senão normaliza a dificuldade por uma régua menor que a
    do motor e devolve outra nota de Leitura para o mesmo aluno.

    Quem lê na escola aqui é OUTRA aluna (Ana): o aluno simulado (o ALVO, sem
    leituras) continua com exatamente os dados dele — o que muda é a RÉGUA.
    """
    escola = escola_completa["escola"]
    escola_completa["turma"].turno = "manha"          # janela 07–13h, seg–sex
    ana = next(a for a in escola_completa["alunos"] if a.nome == "Ana Beatriz Souza")
    segunda = date(2026, 7, 6)
    assert segunda.weekday() == 0
    for i in range(4):
        livro = Livro(escola_id=escola.id, titulo=f"Livro da escola {i}", nivel_codigo="D")
        db.add(livro)
        db.flush()
        db.add(Leitura(escola_id=escola.id, aluno_id=ana.id, livro_id=livro.id,
                       data=datetime.combine(segunda, time(9, 0))))
    db.add(Configuracao(escola_id=escola.id, namespace="pesos.elefante_extra",
                        chave="valores", valor={"ativo": True, "pontos_por_livro": 10.0}))
    db.commit()

    escola, nota = _montar(db, escola_completa, personalizado=True)

    corpo = _simular(cliente, escola.id)

    assert corpo["perfil"] == "personalizado"
    _conferir_paridade(corpo, nota)
    # A régua de dificuldade CONTÉM o bônus (4 livros × 10 pontos na janela do
    # turno): sem ele a referência seria só a dos snapshots (24,0).
    assert corpo["referencias"]["max_pontos_dificuldade"] == pytest.approx(64.0)


def test_pontuacao_media_na_escala_do_matific(cliente, escola_completa):
    url = f"/api/v1/escolas/{escola_completa['escola'].id}/simulador"
    assert cliente.post(url, json={"ano_escolar": "3º Ano",
                                   "pontuacao_media": 5}).status_code == 200
    assert cliente.post(url, json={"ano_escolar": "3º Ano",
                                   "pontuacao_media": 5.1}).status_code == 422
