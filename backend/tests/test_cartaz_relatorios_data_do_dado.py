"""Cartaz do Ranking Geral pela tela Relatórios imprime a DATA DO DADO.

fa5947a pôs no cartaz de ``GET /escolas/{id}/ranking/cartaz`` a linha "Dados das
plataformas: ..." (``dados_em``, ``relatorios.legenda_data_dos_dados``). O MESMO
pôster também sai por ``GET /escolas/{id}/relatorios/ranking?formato=pdf`` (botão
"PDF" do Ranking Geral na tela Relatórios) — e esse é o ÚNICO caminho do cartaz
para o PROFESSOR, que leva 403 em ``/ranking/cartaz``. Esse caminho chamava
``gerar_cartaz_ranking`` sem ``dados_em``: o pôster saía sem a data do dado
(revisão de integração 5, exportacoes-notificacoes, prova 503).

Regra travada aqui: a gestão recebe a MESMA legenda de ``/ranking/cartaz`` (a
escola inteira); o professor recebe a legenda do frescor que ELE vê
(``/ranking/frescor``, só as turmas dele). Dados fictícios, sem rede.
"""
from datetime import datetime, timedelta, timezone

from app.models import Importacao, SnapshotMatific
from app.services import relatorios as svc_relatorios
from tests.test_permissoes import _cliente_como, cenario_professor  # noqa: F401 — fixture

_DIMENSOES = ["leitura", "matematica"]


def _espiar(monkeypatch):
    """Troca o gerador do cartaz por um espião que guarda o ``dados_em``."""
    chamadas: list[str | None] = []

    def falso(*args, **kwargs):
        chamadas.append(kwargs.get("dados_em"))
        return b"%PDF-falso"

    monkeypatch.setattr(svc_relatorios, "gerar_cartaz_ranking", falso)
    return chamadas


def _retrato_matific(db, escola_id, aluno_id, dias_atras):
    imp = Importacao(escola_id=escola_id, plataforma="matific", tipo="seed")
    db.add(imp)
    db.flush()
    agora = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(SnapshotMatific(escola_id=escola_id, aluno_id=aluno_id, importacao_id=imp.id,
                           data_referencia=agora - timedelta(days=dias_atras),
                           atividades=10, estrelas=30, pontuacao_media=3.0))
    db.commit()


def test_gestao_cartaz_pela_tela_relatorios_tem_a_mesma_data_de_ranking_cartaz(
        cliente, escola_completa, monkeypatch):
    escola_id = escola_completa["escola"].id
    chamadas = _espiar(monkeypatch)

    r1 = cliente.get(f"/api/v1/escolas/{escola_id}/ranking/cartaz")
    r2 = cliente.get(f"/api/v1/escolas/{escola_id}/relatorios/ranking",
                     params={"formato": "pdf"})
    assert r1.status_code == 200 and r2.status_code == 200, (r1.text, r2.text)
    assert len(chamadas) == 2
    assert chamadas[0], "controle: o cartaz da tela Ranking declara a data do dado"
    assert chamadas[1] == chamadas[0], \
        "o cartaz da tela Relatórios saiu sem (ou com outra) data do dado"


def test_professor_cartaz_tem_a_data_do_frescor_das_turmas_dele(
        cenario_professor, monkeypatch):  # noqa: F811
    c = cenario_professor
    base = f"/api/v1/escolas/{c['escola'].id}"
    chamadas = _espiar(monkeypatch)

    assert c["professor"].get(f"{base}/ranking/cartaz").status_code == 403
    r = c["professor"].get(f"{base}/relatorios/ranking", params={"formato": "pdf"})
    assert r.status_code == 200, r.text
    frescor = c["professor"].get(f"{base}/ranking/frescor")
    assert frescor.status_code == 200, frescor.text
    esperado = svc_relatorios.legenda_data_dos_dados(frescor.json(), _DIMENSOES)
    assert esperado, "o frescor do professor tem o que declarar"
    assert chamadas[-1] == esperado, \
        "o cartaz do professor saiu sem a linha 'Dados das plataformas: ...'"


def test_professor_cartaz_recorta_o_frescor_pelas_turmas_dele(
        cenario_professor, db, monkeypatch):  # noqa: F811
    """A turma do professor tem retrato velho; a outra turma, recente. A data no
    cartaz do professor é a das turmas DELE, não a da escola inteira."""
    c = cenario_professor
    escola_id = c["escola"].id
    base = f"/api/v1/escolas/{escola_id}"
    _retrato_matific(db, escola_id, c["aluno_da_turma"].id, dias_atras=12)
    _retrato_matific(db, escola_id, c["aluno_fora"].id, dias_atras=2)
    chamadas = _espiar(monkeypatch)

    r_prof = c["professor"].get(f"{base}/relatorios/ranking", params={"formato": "pdf"})
    r_coord = c["coordenador"].get(f"{base}/relatorios/ranking", params={"formato": "pdf"})
    assert r_prof.status_code == 200 and r_coord.status_code == 200, \
        (r_prof.text, r_coord.text)
    legenda_prof, legenda_coord = chamadas[-2], chamadas[-1]

    esperado_prof = svc_relatorios.legenda_data_dos_dados(
        c["professor"].get(f"{base}/ranking/frescor").json(), _DIMENSOES)
    esperado_coord = svc_relatorios.legenda_data_dos_dados(
        c["coordenador"].get(f"{base}/ranking/frescor").json(), _DIMENSOES)
    assert legenda_prof == esperado_prof
    assert legenda_coord == esperado_coord
    assert legenda_prof != legenda_coord, \
        "o professor recebeu a data da escola inteira, não a das turmas dele"
