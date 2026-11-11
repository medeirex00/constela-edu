"""Slides do painel público: sem repetição e com teto — na gravação E na leitura.

`PainelConfigIn.slides` era `list[str]` sem `max_length` e `salvar_config` só
filtrava os valores válidos, sem deduplicar: `["ranking"] * 50000` era gravado
na Configuracao (e no detalhe da auditoria), o telão SEM login devolvia a lista
inteira a cada consulta (~500 KB) e o carrossel ficava com 50 mil slides
iguais; `_assinatura_config` montava a tupla inteira a cada requisição.
Agora a entrada tem teto (o número de slides que existem), a gravação guarda
os válidos sem repetição, e a leitura saneia uma config já gravada. Achado
API_SEGURANCA-7 (sonda S9). Dados fictícios.
"""
from fastapi.testclient import TestClient
from sqlalchemy.orm.attributes import flag_modified

from app.main import app
from app.models import Configuracao

API = "/api/v1"


def _rota(escola_id):
    return f"{API}/escolas/{escola_id}/painel-publico"


def test_lista_gigante_e_recusada(cliente, escola_completa):
    eid = escola_completa["escola"].id
    r = cliente.put(_rota(eid), json={"ativo": True, "slides": ["ranking"] * 50_000})
    assert r.status_code == 422, r.text[:200]
    # Nada foi gravado: o painel continua no padrão (desligado).
    assert cliente.get(_rota(eid)).json()["ativo"] is False


def test_repeticao_e_valor_invalido_nao_sao_gravados(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    r = cliente.put(_rota(eid), json={"ativo": True,
                                      "slides": ["mural", "ranking", "mural", "xyz"]})
    assert r.status_code == 200, r.text
    assert r.json()["slides"] == ["mural", "ranking"]          # ordem de quem escolheu
    row = db.query(Configuracao).filter_by(escola_id=eid, namespace="painel_publico").one()
    db.refresh(row)
    assert row.valor["slides"] == ["mural", "ranking"]
    token = r.json()["url"].rsplit("/", 1)[1]
    publico = TestClient(app).get(f"{API}/publico/{token}/painel")
    assert publico.status_code == 200, publico.text
    assert publico.json()["slides"] == ["mural", "ranking"]


def test_config_ja_gravada_com_repeticao_e_saneada_na_leitura(cliente, db, escola_completa):
    """Uma config gravada antes da correção (com a lista repetida) não pode
    continuar servindo 50 mil slides ao telão — nem travar a tela de gestão,
    que reenvia a lista que recebeu."""
    eid = escola_completa["escola"].id
    r = cliente.put(_rota(eid), json={"ativo": True, "slides": ["ranking"]})
    assert r.status_code == 200, r.text
    token = r.json()["url"].rsplit("/", 1)[1]
    row = db.query(Configuracao).filter_by(escola_id=eid, namespace="painel_publico").one()
    row.valor = {**row.valor, "slides": ["ranking"] * 50_000 + ["xyz", "evolucao"]}
    flag_modified(row, "valor")
    db.commit()

    publico = TestClient(app).get(f"{API}/publico/{token}/painel")
    assert publico.status_code == 200, publico.text
    assert publico.json()["slides"] == ["ranking", "evolucao"]
    assert len(publico.content) < 50_000, len(publico.content)

    gestao = cliente.get(_rota(eid))
    assert gestao.status_code == 200
    assert gestao.json()["slides"] == ["ranking", "evolucao"]
    # A tela reenvia o que recebeu (mais um slide marcado): passa no teto.
    r = cliente.put(_rota(eid), json={"ativo": True,
                                      "slides": gestao.json()["slides"] + ["mural"]})
    assert r.status_code == 200, r.text
    assert r.json()["slides"] == ["ranking", "evolucao", "mural"]
