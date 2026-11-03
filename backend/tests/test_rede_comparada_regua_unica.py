"""UMA régua só para tudo o que COMPARA escolas da rede.

A correção anterior tirou a escola em que só a Educação Infantil usa a
plataforma da equidade, do índice e da média da rede
(``rede.tem_dado_de_quem_concorre``). Quem lia a LISTA de cartões, porém, não
sabia do recorte: ``dashboard_rede`` numerava todos os cartões, o Boletim
publicava o "Ranking das escolas" com todos e o painel web filtrava por
``alunos_com_dados > 0`` (cobertura, que conta as Fases). O mesmo PDF dizia
"pior escola 1000 · diferença 0" e, logo abaixo, "2º · Índice 0,0".

E a média geral da rede tinha duas fórmulas: o painel da Secretaria só pondera
as escolas comparadas, o Panorama Global ponderava todos os cartões — a mesma
rede aparecia com 60 para a Secretaria e 20 para o Admin Global.

Escolas, redes e alunos FICTÍCIOS (sobrenomes inventados).
"""
import pytest

from app.models import Rede
from app.services import rede as svc
from app.services import relatorios as svc_relatorios
from tests.test_rede import _escola_com_notas
from tests.test_rede_percapita_fases import _escola

FUNDAMENTAL = "ESCOLA FUNDAMENTAL TESTELLI"
SO_FASE = "ESCOLA SO FASE TESTELLI"


def _rede(db, nome):
    rede = Rede(nome=nome, status="ativa")
    db.add(rede)
    db.flush()
    return rede


def _rede_com_escola_so_fase(db):
    rede = _rede(db, "Rede Ficticia Comparada")
    _escola(db, rede, FUNDAMENTAL, fundamental=[(5, 10)], fase=[])
    # Adoção 100% (as duas crianças da Fase usam), nenhum aluno que concorre.
    _escola(db, rede, SO_FASE, fundamental=[], fase=[(30, 20), (20, 10)])
    db.commit()
    return rede


# --- (a) a marca `comparada` e a posição -------------------------------------

def test_painel_marca_quem_e_comparado_e_so_numera_as_comparadas(db):
    rede = _rede_com_escola_so_fase(db)
    painel = svc.dashboard_rede(db, rede.id)
    por_nome = {c["nome"]: c for c in painel["escolas"]}
    fund, so_fase = por_nome[FUNDAMENTAL], por_nome[SO_FASE]

    assert fund["comparada"] is True and fund["posicao"] == 1
    # Fora da comparação: sem posição (não é "2º lugar com índice 0") e no fim.
    assert so_fase["comparada"] is False
    assert so_fase["posicao"] is None
    assert painel["escolas"][-1]["nome"] == SO_FASE
    # A COBERTURA continua no cartão dela: as Fases seguem contadas.
    assert so_fase["alunos_com_dados"] == 2 and so_fase["adocao"] == 100.0
    assert painel["totais"]["escolas"] == 2 and painel["totais"]["alunos_com_dados"] == 3


def test_posicao_do_painel_e_a_do_ranking_da_rede_mesmo_no_empate(db):
    """Empate no índice 0 entre uma escola COMPARADA (o aluno usa e leu 0) e a
    escola só com a Fase, com a mesma adoção: o nome decidia, e a só-Fase saía
    em 2º no painel/Boletim enquanto o Ranking da Rede dava o 2º à comparada."""
    rede = _rede(db, "Rede Ficticia Empate")
    _escola(db, rede, "ESCOLA A SO FASE SINTETICA", fundamental=[], fase=[(30, 20)])
    _escola(db, rede, "ESCOLA B ZERADA SINTETICA", fundamental=[(0, 0)], fase=[])
    _escola(db, rede, "ESCOLA C LEITORA SINTETICA", fundamental=[(5, 10)], fase=[])
    db.commit()

    painel = {c["nome"]: c["posicao"] for c in svc.dashboard_rede(db, rede.id)["escolas"]}
    ranking = {c["nome"]: c["posicao"]
               for c in svc.ranking_escolas(db, rede.id, metrica="indice_geral")}
    assert ranking == {"ESCOLA C LEITORA SINTETICA": 1, "ESCOLA B ZERADA SINTETICA": 2}
    assert {n: p for n, p in painel.items() if p is not None} == ranking
    assert painel["ESCOLA A SO FASE SINTETICA"] is None


# --- (a) o Boletim lê a marca ------------------------------------------------

def test_boletim_ranqueia_so_as_comparadas_e_lista_a_outra_a_parte(db):
    rede = _rede_com_escola_so_fase(db)
    dados = svc.dashboard_rede(db, rede.id)

    # Base da reserva fpdf: só quem é comparado, com a posição do painel.
    _, linhas = svc_relatorios.linhas_boletim_rede(dados)
    assert [(linha[0], linha[1]) for linha in linhas] == [(1, FUNDAMENTAL)]

    html = svc_relatorios._shell_boletim_rede("Rede Ficticia Comparada", dados)
    ranking = html.split("Ranking das escolas", 1)[1].split("</table>", 1)[0]
    assert FUNDAMENTAL in ranking and "1º" in ranking
    assert SO_FASE not in ranking and "2º" not in ranking
    # Ela não some do documento: vai à parte, só com a cobertura.
    assert "Escolas fora da comparação" in html
    fora = html.split("Escolas fora da comparação", 1)[1].split("</table>", 1)[0]
    assert SO_FASE in fora and "100,0%" in fora


def test_reserva_fpdf_do_boletim_usa_a_mesma_tabela(db, monkeypatch):
    rede = _rede_com_escola_so_fase(db)
    dados = svc.dashboard_rede(db, rede.id)

    def _sem_navegador(_html):
        raise RuntimeError("sem chromium (teste)")

    capturado = {}

    def _gerar_pdf(_titulo, _rede_nome, _cor, cabecalho, linhas):
        capturado["linhas"] = linhas
        return b"%PDF-reserva"

    monkeypatch.setattr(svc_relatorios, "_relatorio_html_pdf", _sem_navegador)
    monkeypatch.setattr(svc_relatorios, "gerar_pdf", _gerar_pdf)
    assert svc_relatorios.gerar_boletim_rede("Rede Ficticia", dados) == b"%PDF-reserva"
    assert [linha[1] for linha in capturado["linhas"]] == [FUNDAMENTAL]


def test_boletim_de_dado_sem_a_marca_continua_listando(db):
    """Cartão montado fora do ``dashboard_rede`` (sem ``comparada``) segue na
    tabela como antes: a marca só tira quem o painel disse que está fora."""
    dados = {"escolas": [{"nome": "EM Alfa Ficticia", "posicao": 1, "total_alunos": 10,
                          "adocao": 90.0, "pontuacao_geral": 1000.0, "media_matific": 50.0,
                          "media_elefante": 50.0, "media_geral": 50.0}]}
    _, linhas = svc_relatorios.linhas_boletim_rede(dados)
    assert [linha[1] for linha in linhas] == ["EM Alfa Ficticia"]


# --- (b) a média geral tem UMA fórmula ---------------------------------------

def test_media_geral_do_panorama_global_e_a_do_painel_da_rede(db):
    rede = _rede(db, "Rede Ficticia Media")
    _escola_com_notas(db, rede.id, FUNDAMENTAL, [60.0])          # 1 aluno, média 60
    _escola(db, rede, SO_FASE, fundamental=[], fase=[(30, 20), (20, 10)])
    outra = _rede(db, "Rede Ficticia Outra")
    _escola_com_notas(db, outra.id, "ESCOLA OUTRA SINTETICA", [30.0])  # 1 aluno, média 30
    db.commit()

    da_rede = svc.dashboard_rede(db, rede.id)["totais"]["media_geral"]
    global_ = svc.dashboard_global(db)
    cartao = next(r for r in global_["redes"] if r["rede_id"] == rede.id)
    assert da_rede == 60.0
    # Antes: (60·1 + 0·2) ÷ 3 = 20 no Panorama Global para a MESMA rede.
    assert cartao["media_geral"] == da_rede
    # O total global pesa pelos alunos das escolas COMPARADAS: (60 + 30) ÷ 2.
    # Repesando a média de cada rede pelo `alunos_com_dados` do cartão (que conta
    # as Fases) daria (60·3 + 30·1) ÷ 4 = 52,5.
    assert global_["totais"]["media_geral"] == 45.0


def test_meta_de_media_geral_sem_escola_comparada_nao_esta_medida(db):
    """A base do "foi medida?" é a mesma da conta: só as Fases com dado = média
    0,0 por falta de peso, não um desempenho zero ("0,0 / 70")."""
    rede = _rede(db, "Rede Ficticia So Fase Meta")
    _escola(db, rede, SO_FASE, fundamental=[], fase=[(30, 20)])
    svc.definir_meta(db, rede.id, "media_geral", 70.0)
    db.commit()

    meta = next(m for m in svc.metas_com_progresso(db, rede.id) if m["metrica"] == "media_geral")
    assert meta["atual"] == 0.0
    assert meta["medida"] is False


@pytest.mark.parametrize("metrica, alvo", [("pontuacao_geral", 1.0), ("adocao", 1.0)])
def test_metas_x_de_y_escolas_contam_so_as_comparadas(db, metrica, alvo):
    """"X de Y escolas atingiram" (Índice e Engajamento) contava a escola em que só
    a Educação Infantil usa a plataforma: Y = 2 ao lado de uma equidade e de um
    ranking que só comparam 1. A base agora é a marca ``comparada``."""
    rede = _rede_com_escola_so_fase(db)
    svc.definir_meta(db, rede.id, metrica, alvo)
    db.commit()
    meta = next(m for m in svc.metas_com_progresso(db, rede.id) if m["metrica"] == metrica)
    assert meta["escolas_total"] == 1
    assert meta["escolas_atingiram"] == 1
