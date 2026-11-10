"""O "Nº bimestre" é do ANO LETIVO da escola, não do ano do relógio
(achados PERIODOS-2 e RANKINGS-10).

``periodos._bimestre`` fazia ``numero, ano = int(pedido), hoje.year`` e ``resolver``
nem lhe passava o ``ano_letivo`` que recebe. Em janeiro de 2027, com a escola ainda no
ano letivo 2026 (a troca é manual), a coordenação pedia o "4º bimestre" para a
cerimônia e recebia 01/10/2027 a 31/12/2027 — uma janela FUTURA: pódio vazio nas
Premiações e no Ranking, relatório zerado, Placar do Matific pedindo datas de 2027.
O preset "Ano letivo" da MESMA lista já usava o ano da escola.

Agora o bimestre numerado sai do calendário do ano letivo da escola, e o rótulo diz o
ano quando ele não é o do calendário de hoje. Dados fictícios.
"""
from datetime import date, datetime

import pytest

from app.models import Leitura, Livro
from app.services import periodos
from app.services import relatorios_periodo as rp
from app.sync import aovivo

JANEIRO_2027 = date(2027, 1, 15)


def test_bimestre_4_em_janeiro_com_a_escola_ainda_em_2026():
    ini, fim, rotulo = periodos.resolver("bimestre_4", JANEIRO_2027, 2026)
    assert (ini.date(), fim.date()) == (date(2026, 10, 5), date(2026, 12, 31)), rotulo
    assert rotulo == "4º bimestre de 2026 (05/10 a 31/12)"
    # O mesmo ano que o preset "Ano letivo" usa na mesma tela.
    ano_i, ano_f, _ = periodos.resolver("ano_letivo", JANEIRO_2027, 2026)
    assert ano_i.date() <= ini.date() and fim.date() <= ano_f.date()


@pytest.mark.parametrize("numero,esperado", [
    (1, (date(2026, 2, 2), date(2026, 4, 22))),
    (2, (date(2026, 4, 23), date(2026, 7, 23))),
    (3, (date(2026, 7, 24), date(2026, 10, 4))),
    (4, (date(2026, 10, 5), date(2026, 12, 31))),
])
def test_todos_os_numerados_sao_do_ano_letivo(numero, esperado):
    ini, fim, _ = periodos.resolver(f"bimestre_{numero}", date(2027, 1, 20), 2026)
    assert (ini.date(), fim.date()) == esperado


def test_no_mesmo_ano_o_rotulo_nao_muda():
    _, _, rotulo = periodos.resolver("bimestre_3", date(2026, 10, 1), 2026)
    assert rotulo == "3º bimestre (24/07 a 04/10)"


def test_escola_atrasada_em_ano_sem_calendario_usa_a_aproximacao_do_ano_dela():
    """Escola ainda em 2025 consultada em 2026: o 2º bimestre é o de 2025 (sem
    calendário oficial → aproximado, e o rótulo diz de que ano), não o de 2026."""
    ini, fim, rotulo = periodos.resolver("bimestre_2", date(2026, 5, 10), 2025)
    assert (ini.date(), fim.date()) == (date(2025, 5, 1), date(2025, 7, 31))
    assert rotulo == "2º bimestre (aproximado: sem calendário oficial de 2025)"


def _leitura_de_novembro(db, escola_completa):
    escola, aluno = escola_completa["escola"], escola_completa["alunos"][0]
    livro = Livro(escola_id=escola.id, titulo="Livro Fictício", nivel_codigo="D")
    db.add(livro)
    db.flush()
    db.add(Leitura(escola_id=escola.id, aluno_id=aluno.id, livro_id=livro.id,
                   data=datetime(2026, 11, 10, 9, 30), tempo_leitura_min=20))
    db.commit()
    return escola, aluno


def test_premiacoes_e_ranking_do_4o_bimestre_pedidos_em_janeiro(
        cliente, db, escola_completa, monkeypatch):
    escola, aluno = _leitura_de_novembro(db, escola_completa)
    import app.routers.rankings as rr
    monkeypatch.setattr(rr, "hoje_br", lambda: JANEIRO_2027)
    base = f"/api/v1/escolas/{escola.id}"

    def mais_livros(periodo):
        r = cliente.get(f"{base}/premiacoes?periodo={periodo}")
        assert r.status_code == 200, r.text
        dados = r.json()
        cat = next(c for c in dados["categorias"] if c["chave"] == "mais_livros")
        return [i["valor"] for i in cat["podio"]], dados["periodo"]

    assert mais_livros("ano_letivo")[0] == [1]
    quarto, per = mais_livros("bimestre_4")
    assert quarto == [1], f"4º bimestre pedido em 15/01/2027 → {per}"
    assert per["inicio"].startswith("2026-10-05"), per

    r = cliente.get(f"{base}/ranking/leitura?periodo=bimestre_4")
    assert r.status_code == 200, r.text
    linhas = [x for x in r.json() if x.get("aluno_id") == aluno.id]
    assert linhas and linhas[0]["livros"] == 1, r.json()


def test_relatorio_por_periodo_do_4o_bimestre_em_janeiro(db, escola_completa):
    escola, _ = _leitura_de_novembro(db, escola_completa)
    dados = rp.gerar(db, escola.id, preset="bimestre_4", plataformas=["elefante"],
                     hoje=JANEIRO_2027)
    assert dados["periodo"]["inicio"].startswith("2026-10-05"), dados["periodo"]
    assert dados["periodo"]["fim"].startswith("2026-12-31"), dados["periodo"]


def test_placar_ao_vivo_do_4o_bimestre_em_janeiro_pede_as_datas_de_2026():
    filtro, rotulo, di, df = aovivo.mapa_filtro("bimestre_4", None, None, 2026, JANEIRO_2027)
    assert filtro == "start_date=2026-10-05&end_date=2026-12-31", rotulo
    assert (di, df) == (date(2026, 10, 5), date(2026, 12, 31))


def test_panorama_da_rede_em_janeiro_e_a_evolucao_por_bimestre_batem(
        db, cliente_global, monkeypatch):
    """A aba de plataformas da Secretaria com "Nº bimestre" em janeiro de 2027 (rede
    em 2026) mede o bimestre de 2026 — o mesmo que a evolução por bimestre mostra.
    Antes, a aba ia para out–dez de 2027 e a evolução contornava o defeito sozinha."""
    from tests.test_analise_base import mundo_plataformas

    mundo = mundo_plataformas(db)
    monkeypatch.setattr("app.routers.analise.hoje_br", lambda: date(2027, 1, 10))
    rede = mundo["rede"].id
    r = cliente_global.get(f"/api/v1/redes/{rede}/analise/plataformas/evolucao")
    assert r.status_code == 200, r.text
    evo = r.json()
    assert evo["ano_letivo"] == 2026 and [b["numero"] for b in evo["bimestres"]] == [1, 2, 3, 4]
    for b in evo["bimestres"]:
        r = cliente_global.get(f"/api/v1/redes/{rede}/analise/plataformas",
                               params={"periodo": f"bimestre_{b['numero']}"})
        assert r.status_code == 200, r.text
        plat = r.json()
        assert (plat["janela"]["inicio"], plat["janela"]["fim"]) == (b["inicio"], b["fim"]), (
            b["numero"], plat["janela"])
        assert b["inicio"].startswith("2026-")
        assert b["rede"]["escolas_com_dado"] == plat["rede"]["escolas_com_dado"]
