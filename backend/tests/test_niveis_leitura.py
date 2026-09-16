"""Distribuição de leitura por faixa de dificuldade: cálculo, entrada e import.

Os pontos saem da FONTE ÚNICA de dificuldade (``dificuldade_livro``, regra v1
global): a escola da fixture é padrão, turma 3º Ano (fator 1,20); as faixas da
fixture são ``pre_leitor`` [AA, BB] e ``nivel_2`` [D, E]. Chave por FAIXA vale o
centro da faixa (pre_leitor=pos 1,5 → 1,40; nivel_2=pos 10 → 3,36 no 3º ano)."""
import pytest
from sqlalchemy import select

from app.models import Importacao, NivelDificuldade, SnapshotElefante
from app.services import dificuldade_livro as dl
from app.services import importacao as svc
from app.services import scoring


def _url(escola_id: int, sufixo: str = "") -> str:
    return f"/api/v1/escolas/{escola_id}/elefante{sufixo}"


def _v(chave: str, serie: str = "3º Ano") -> float:
    return dl.RegraV1().valor_tipico(chave, serie)


# --- Serviço de distribuição --------------------------------------------------

def test_distribuicao_por_faixa(db, escola_completa):
    escola = escola_completa["escola"]
    dist = scoring.distribuicao_niveis(
        db, escola.id, {"pre_leitor": 8, "nivel_2": 3}, "3º Ano")

    faixas = {f["codigo"]: f for f in dist["faixas"]}
    assert faixas["pre_leitor"]["quantidade"] == 8
    assert faixas["pre_leitor"]["pontos"] == pytest.approx(8 * _v("pre_leitor"), abs=0.02)   # 8 × 1,40
    assert faixas["pre_leitor"]["pontos_por_livro"] == pytest.approx(_v("pre_leitor"), abs=0.01)
    assert faixas["nivel_2"]["quantidade"] == 3
    assert faixas["nivel_2"]["pontos"] == pytest.approx(3 * _v("nivel_2"), abs=0.02)         # 3 × 3,36
    assert dist["total_livros"] == 11
    assert dist["pontos_dificuldade"] == pytest.approx(8 * _v("pre_leitor") + 3 * _v("nivel_2"), abs=0.03)
    assert dist["faixa_predominante"] == "Pré-Leitor"
    assert faixas["pre_leitor"]["percentual"] == 72.7


def test_distribuicao_agrega_codigos_de_letra(db, escola_completa):
    """Livros informados por código de letra caem na faixa certa — e cada letra
    vale o SEU degrau na A3 (AA=1,00; BB=1,11; D=2,06 × 1,20 da série)."""
    escola = escola_completa["escola"]
    dist = scoring.distribuicao_niveis(
        db, escola.id, {"AA": 2, "BB": 1, "D": 5}, "3º Ano")
    faixas = {f["codigo"]: f for f in dist["faixas"]}
    assert faixas["pre_leitor"]["quantidade"] == 3    # AA + BB
    assert faixas["nivel_2"]["quantidade"] == 5        # D
    esperado = 2 * _v("AA") + 1 * _v("BB") + 5 * _v("D")
    assert dist["pontos_dificuldade"] == pytest.approx(esperado, abs=0.03)
    assert faixas["pre_leitor"]["pontos"] == pytest.approx(2 * _v("AA") + _v("BB"), abs=0.02)


def test_distribuicao_usa_o_valor_proprio_dos_livros_itemizados(cliente, db, escola_completa):
    """Com ``aluno_id``, o card usa as leituras ITEMIZADAS do aluno: um livro do
    catálogo vale o seu valor (wordCount), não só o típico — e o total do card é o
    MESMO número da nota (uma fonte)."""
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    r = cliente.post(f"/api/v1/escolas/{escola.id}/importacoes/confirmar", json={
        "plataforma": "elefante", "formato": "leituras", "tipo": "texto",
        "linhas": [{"nome": ana.nome, "aluno_id": ana.id,
                    "dados": {"livro": "Curiosidades 6", "nivel": "D", "data": "2026-07-01T09:00:00"}}]})
    assert r.status_code == 200, r.text
    regra = dl.RegraV1()
    proprio = regra.valor_livro("D", "Curiosidades 6", "3º Ano")   # 183 palavras > mediana 139
    assert proprio > regra.valor_tipico("D", "3º Ano")
    dist = scoring.distribuicao_niveis(db, escola.id, {"D": 1}, "3º Ano", aluno_id=ana.id)
    assert dist["pontos_dificuldade"] == pytest.approx(proprio, abs=0.02)
    sem_aluno = scoring.distribuicao_niveis(db, escola.id, {"D": 1}, "3º Ano")
    assert sem_aluno["pontos_dificuldade"] == pytest.approx(regra.valor_tipico("D", "3º Ano"), abs=0.02)


# --- Entrada manual por faixa -------------------------------------------------

def test_informar_niveis_pela_api(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]

    resposta = cliente.put(_url(escola.id, f"/{ana.id}/niveis"),
                           json={"faixas": {"pre_leitor": 8, "nivel_2": 3},
                                 "motivo": "dados informados pela professora"})
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["livros_unicos"] == 11

    # snapshot gravado com a distribuição por faixa
    snap = db.execute(
        select(SnapshotElefante).where(SnapshotElefante.aluno_id == ana.id)
        .order_by(SnapshotElefante.id.desc())
    ).scalars().first()
    assert snap.livros_por_nivel == {"pre_leitor": 8, "nivel_2": 3}

    # a ficha do aluno traz o gráfico/estatísticas
    perfil = cliente.get(f"/api/v1/escolas/{escola.id}/alunos/{ana.id}/perfil").json()
    niveis = perfil["leitura_niveis"]
    assert niveis["total_livros"] == 11
    assert niveis["pontos_dificuldade"] == pytest.approx(8 * _v("pre_leitor") + 3 * _v("nivel_2"), abs=0.03)
    assert niveis["faixa_predominante"] == "Pré-Leitor"


def test_informar_niveis_recusa_faixa_desconhecida(cliente, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    resposta = cliente.put(_url(escola.id, f"/{ana.id}/niveis"),
                           json={"faixas": {"nivel_99": 5},
                                 "motivo": "dados informados pela professora"})
    assert resposta.status_code == 400
    assert "desconhecida" in resposta.json()["detail"]


# --- Importação por colunas de faixa ------------------------------------------

def test_import_reconhece_colunas_de_faixa():
    texto = (
        "Elefante Letrado — livros por nível\n"
        "Aluno;Pré-Leitor;Nível 2\n"
        "Ana Beatriz Souza;8;3\n"
        "João Pedro Barbosa;2;0\n"
    )
    analise = svc.analisar_texto(texto, plataforma="elefante")
    assert analise.formato == "resumo"
    ana = next(l for l in analise.linhas if "Ana" in l.nome)
    assert ana.dados["livros_por_nivel"] == {"pre_leitor": 8, "nivel_2": 3}


def test_import_faixas_confirmado_pontua_por_dificuldade(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    confirmacao = cliente.post(
        f"/api/v1/escolas/{escola.id}/importacoes/confirmar",
        json={"plataforma": "elefante", "formato": "resumo", "tipo": "texto",
              "linhas": [{"nome": ana.nome,
                          "dados": {"livros_por_nivel": {"pre_leitor": 4, "nivel_2": 6}},
                          "aluno_id": ana.id}]})
    assert confirmacao.status_code == 200, confirmacao.text

    perfil = cliente.get(f"/api/v1/escolas/{escola.id}/alunos/{ana.id}/perfil").json()
    assert perfil["leitura_niveis"]["pontos_dificuldade"] == pytest.approx(
        4 * _v("pre_leitor") + 6 * _v("nivel_2"), abs=0.03)
    assert perfil["leitura_niveis"]["total_livros"] == 10


def test_leitura_dificil_pontua_mais_que_leitura_facil(db, escola_completa):
    """Menos livros porém mais difíceis rendem mais pontos de dificuldade.

    Na régua A3 o degrau Pré-Leitor→Nível 2 é curto (~2,4×), então o cenário usa
    Nível 3 (K–R, centro pos 17,5 → ~7,3 pts no 3º ano): 8 livros de Nível 3
    (≈58) batem 20 do Pré-Leitor (≈28). Farming de livros fáceis não compensa."""
    escola = escola_completa["escola"]
    db.add(NivelDificuldade(escola_id=escola.id, nome="Nível 3", codigo="nivel_3",
                            codigos=["K", "L", "M", "N", "O", "P", "Q", "R"],
                            pontos_padrao=8.0, ordem=2))
    db.commit()
    facil = scoring.distribuicao_niveis(db, escola.id, {"pre_leitor": 20}, "3º Ano")
    dificil = scoring.distribuicao_niveis(db, escola.id, {"nivel_3": 8}, "3º Ano")
    assert facil["total_livros"] > dificil["total_livros"]        # 20 > 8
    assert dificil["pontos_dificuldade"] > facil["pontos_dificuldade"]  # ~58 > ~28
    assert facil["pontos_dificuldade"] == pytest.approx(20 * _v("pre_leitor"), abs=0.05)
