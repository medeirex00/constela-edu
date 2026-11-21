"""Escola cadastrada sem ano letivo nasce no ano CORRENTE (Brasília), não em 2026.

``EscolaCreate.ano_letivo_ativo`` e ``Escola.ano_letivo_ativo`` tinham o padrão
literal 2026. A tela Escolas cria a escola só com nome, cidade e estado, então o
padrão sempre valia: a partir de 2027, a escola nova nasceria no ano letivo 2026 —
ranking de Matemática, premiações, cartões e janela do Matific medidos no ano
errado, sem aviso.

O relógio é o de Brasília (``app.core.tempo.hoje_br``), como todo "hoje" de
decisão do sistema. Achado TESTES-3 da auditoria. Dados fictícios.
"""
from datetime import date

from app.core import tempo
from app.models import Escola

API = "/api/v1"


def test_escola_nova_sem_ano_nasce_no_ano_corrente(cliente_global, monkeypatch):
    monkeypatch.setattr(tempo, "hoje_br", lambda: date(2027, 2, 15))
    r = cliente_global.post(f"{API}/escolas", json={
        "nome": "EMEF FICTICIA ANO CORRENTE", "cidade": "Cidade Ficticia", "estado": "SP"})
    assert r.status_code in (200, 201), r.text
    assert r.json()["ano_letivo_ativo"] == 2027, \
        f"escola nova nasceu com ano_letivo_ativo={r.json()['ano_letivo_ativo']}"


def test_escola_nova_com_ano_informado_respeita_o_ano(cliente_global, monkeypatch):
    monkeypatch.setattr(tempo, "hoje_br", lambda: date(2027, 2, 15))
    r = cliente_global.post(f"{API}/escolas", json={
        "nome": "EMEF FICTICIA ANO INFORMADO", "ano_letivo_ativo": 2026})
    assert r.status_code in (200, 201), r.text
    assert r.json()["ano_letivo_ativo"] == 2026


def test_modelo_sem_ano_tambem_usa_o_ano_corrente(db, monkeypatch):
    monkeypatch.setattr(tempo, "hoje_br", lambda: date(2027, 2, 15))
    escola = Escola(nome="ESCOLA FICTICIA SEM ANO")
    db.add(escola)
    db.flush()
    assert escola.ano_letivo_ativo == 2027
