"""Ranking de Leitura sem recorte de datas soma o agregado do Elefante — como as
Premiações — qualquer que seja o TEXTO do preset.

`periodos.resolver` devolve (None, None, "Todo o histórico") para `tudo`, para
`personalizado` ainda sem datas (o estado da tela logo depois de escolher
"Período personalizado": `periodoParaQuery` manda só `periodo=personalizado`) e
para preset desconhecido. `/ranking/leitura` decidia pelo TEXTO
(`periodo == "tudo"`) e só nesse caso somava o `SnapshotElefante`;
`premiacoes._leitura_no_periodo` decide por `inicio is None and fim is None`.
O mesmo pedido dava lista vazia numa tela e a criança na outra. Achado
RANKINGS-11. Dados fictícios.
"""
from datetime import datetime

import pytest

from app.models import Importacao, SnapshotElefante

API = "/api/v1"


@pytest.mark.parametrize("periodo", ["personalizado", "TUDO", "preset-que-nao-existe"])
def test_sem_datas_soma_o_agregado_como_tudo_e_como_as_premiacoes(
        cliente, db, escola_completa, periodo):
    esc = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    imp = Importacao(escola_id=esc.id, plataforma="elefante", tipo="seed")
    db.add(imp)
    db.flush()
    # Só o relatório da TURMA (agregado, sem leitura datada por livro).
    db.add(SnapshotElefante(escola_id=esc.id, aluno_id=ana.id, importacao_id=imp.id,
                            data_referencia=datetime(2026, 9, 20), livros_unicos=6,
                            tempo_leitura_min=90, livros_por_nivel={"D": 6}))
    db.commit()
    base = f"{API}/escolas/{esc.id}"

    def _lista(params):
        r = cliente.get(f"{base}/ranking/leitura", params=params)
        assert r.status_code == 200, r.text
        return [(i["aluno_id"], i["posicao"], i["pontos"], i["livros"],
                 i["tempo_leitura_min"]) for i in r.json()]

    tudo = _lista({"periodo": "tudo"})
    assert [a for a, *_ in tudo] == [ana.id]          # controle: o agregado conta
    assert _lista({"periodo": periodo}) == tudo, periodo

    pr = cliente.get(f"{base}/premiacoes", params={"periodo": periodo})
    assert pr.status_code == 200, pr.text
    assert pr.json()["periodo"]["inicio"] is None and pr.json()["periodo"]["fim"] is None
    melhor = next(c for c in pr.json()["categorias"] if c["chave"] == "melhor_leitor")
    assert [(i["aluno_id"], i["valor"]) for i in melhor["podio"]] == [
        (a, p) for a, _, p, *_ in tudo]
