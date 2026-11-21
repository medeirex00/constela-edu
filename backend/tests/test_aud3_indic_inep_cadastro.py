"""Cadastro do código INEP da escola (PATCH /redes/escolas/{id}) — auditoria
S_G_INDICADORES-4. Tudo SINTÉTICO (INEPs 3599010x inventados).

O código INEP tem 8 dígitos. Antes, o cadastro passava o texto digitado por
``normalizar_inep`` (que corta para os 8 últimos dígitos, completa com zeros e ignora
letras), gravava o resultado e respondia 200: '350123456' (um dígito a mais) virava
'50123456', '3501234S' virava '03501234' e 'INEP?' APAGAVA o código da escola. Agora o
que não tem 8 dígitos é recusado com 400 e o código anterior fica; "" continua limpando,
e o cadastro antigo com o '0' à esquerda (9 dígitos) e o '.0' da planilha continuam aceitos.
"""
import pytest

from app.models import Escola
from app.services import avaliacoes

ANTERIOR = "35990103"


@pytest.fixture()
def escola(db):
    e = Escola(nome="EMEF Sintética Três", ano_letivo_ativo=2026, codigo_inep=ANTERIOR)
    db.add(e)
    db.commit()
    return e


@pytest.mark.parametrize("digitado", ["350123456", "3501234S", "INEP?", "3501234",
                                      "35012345.00", "35012345,0", "0035012345"])
def test_codigo_sem_8_digitos_e_recusado_e_o_anterior_fica(db, cliente_global, escola,
                                                           digitado):
    r = cliente_global.patch(f"/api/v1/redes/escolas/{escola.id}",
                             json={"codigo_inep": digitado})
    assert r.status_code == 400, (digitado, r.status_code, r.text)
    assert "8 dígitos" in r.json()["detail"]
    db.expire_all()
    assert db.get(Escola, escola.id).codigo_inep == ANTERIOR


@pytest.mark.parametrize("digitado,gravado", [
    ("35990104", "35990104"),
    (" 35990104 ", "35990104"),
    ("035990104", "35990104"),       # cadastro antigo: o '0' à esquerda (9 dígitos)
    ("35990104.0", "35990104"),      # número do Excel colado ('.0' no fim)
    ("35.990.104", "35990104"),      # com pontuação
    ("", None),                      # "" limpa
])
def test_codigo_de_8_digitos_e_gravado_como_foi_digitado(db, cliente_global, escola,
                                                         digitado, gravado):
    r = cliente_global.patch(f"/api/v1/redes/escolas/{escola.id}",
                             json={"codigo_inep": digitado})
    assert r.status_code == 200, r.text
    assert r.json()["codigo_inep"] == gravado
    db.expire_all()
    assert db.get(Escola, escola.id).codigo_inep == gravado


def test_inep_digitado_nunca_corta_nem_completa():
    assert avaliacoes.inep_digitado("35990104") == "35990104"
    assert avaliacoes.inep_digitado("035990104") == "35990104"
    for errado in ("350123456", "3501234S", "INEP?", "3501234", "", None, "135990104"):
        assert avaliacoes.inep_digitado(errado) is None, errado
