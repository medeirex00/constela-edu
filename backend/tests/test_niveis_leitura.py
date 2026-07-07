"""Distribuição de leitura por faixa de dificuldade: cálculo, entrada e import."""
from sqlalchemy import select

from app.models import Importacao, SnapshotElefante
from app.services import importacao as svc
from app.services import scoring


def _url(escola_id: int, sufixo: str = "") -> str:
    return f"/api/v1/escolas/{escola_id}/elefante{sufixo}"


# --- Serviço de distribuição --------------------------------------------------

def test_distribuicao_por_faixa(db, escola_completa):
    escola = escola_completa["escola"]
    # fixture tem Pré-Leitor (pre_leitor, 1 pt) e Nível 2 (nivel_2, 4 pts)
    dist = scoring.distribuicao_niveis(
        db, escola.id, {"pre_leitor": 8, "nivel_2": 3}, "3º Ano")

    faixas = {f["codigo"]: f for f in dist["faixas"]}
    assert faixas["pre_leitor"]["quantidade"] == 8
    assert faixas["pre_leitor"]["pontos"] == 8.0     # 8 × 1
    assert faixas["nivel_2"]["quantidade"] == 3
    assert faixas["nivel_2"]["pontos"] == 12.0        # 3 × 4
    assert dist["total_livros"] == 11
    assert dist["pontos_dificuldade"] == 20.0
    assert dist["faixa_predominante"] == "Pré-Leitor"
    assert faixas["pre_leitor"]["percentual"] == 72.7


def test_distribuicao_agrega_codigos_de_letra(db, escola_completa):
    """Livros informados por código de letra caem na faixa certa."""
    escola = escola_completa["escola"]
    dist = scoring.distribuicao_niveis(
        db, escola.id, {"AA": 2, "BB": 1, "D": 5}, "3º Ano")
    faixas = {f["codigo"]: f for f in dist["faixas"]}
    assert faixas["pre_leitor"]["quantidade"] == 3    # AA + BB
    assert faixas["nivel_2"]["quantidade"] == 5        # D
    assert dist["pontos_dificuldade"] == 3 * 1 + 5 * 4  # 23


# --- Entrada manual por faixa -------------------------------------------------

def test_informar_niveis_pela_api(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]

    resposta = cliente.put(_url(escola.id, f"/{ana.id}/niveis"),
                           json={"faixas": {"pre_leitor": 8, "nivel_2": 3}})
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
    assert niveis["pontos_dificuldade"] == 20.0
    assert niveis["faixa_predominante"] == "Pré-Leitor"


def test_informar_niveis_recusa_faixa_desconhecida(cliente, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    resposta = cliente.put(_url(escola.id, f"/{ana.id}/niveis"),
                           json={"faixas": {"nivel_99": 5}})
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
    assert perfil["leitura_niveis"]["pontos_dificuldade"] == 4 * 1 + 6 * 4  # 28
    assert perfil["leitura_niveis"]["total_livros"] == 10


def test_leitura_dificil_pontua_mais_que_leitura_facil(db, escola_completa):
    """Menos livros porém mais difíceis rendem mais pontos de dificuldade."""
    escola = escola_completa["escola"]
    facil = scoring.distribuicao_niveis(db, escola.id, {"pre_leitor": 20}, "3º Ano")
    dificil = scoring.distribuicao_niveis(db, escola.id, {"nivel_2": 8}, "3º Ano")
    assert facil["total_livros"] > dificil["total_livros"]        # 20 > 8
    assert dificil["pontos_dificuldade"] > facil["pontos_dificuldade"]  # 32 > 20
