"""As recusas por senha salva ilegível (e por credencial ausente) mandam a coordenação à
tela que existe: "Integrações", botão "Configurar conexão".

Antes diziam "...em Sincronização automática...", o nome da tela antes da limpeza de
set/2026 (docs/limpeza-ux-2026-09.md: "Integrações (antiga Sincronização automática)").
O menu não tem mais esse item. O texto chega ao topo de Integrações ("Sincronizar
agora"), ao Ranking de Matemática (placar ao vivo), ao diagnóstico do Elefante e ao
alerta da execução.

Dados 100% fictícios; chaves geradas em memória e nunca impressas.
"""
import secrets

import pytest

from app.core.config import settings
from app.sync import aovivo, connectors, service, vault
from app.sync import diagnostico_elefante as diag
from app.sync.interfaces import Credenciais, ErroConector

API = "/api/v1"
TELA_ANTIGA = "Sincronização automática"


def _chave(prefixo: str) -> str:
    return f"{prefixo}-{secrets.token_urlsafe(40)}"


@pytest.fixture(autouse=True)
def _sem_cache_e_sem_robo(monkeypatch):
    aovivo._cache.clear()
    monkeypatch.setattr(service, "disparar_em_thread", lambda _i: None)
    yield
    aovivo._cache.clear()


def _aponta_a_tela_de_hoje(texto: str) -> None:
    assert TELA_ANTIGA not in texto, texto
    assert "Integrações" in texto and "“Configurar conexão”" in texto, texto


def _credenciais_ilegiveis(db, eid, monkeypatch, *plataformas):
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", _chave("dek0"))
    for plataforma in plataformas:
        vault.salvar_credencial(db, eid, plataforma,
                                Credenciais(usuario="robo@escola.invalid",
                                            senha="senha-ficticia"))
    db.commit()
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", _chave("dek1"))   # sem recifrar


def test_mensagem_da_senha_ilegivel_aponta_integracoes():
    for plataformas in (["elefante"], ["matific"], ["matific", "elefante"]):
        texto = vault.mensagem_credencial_ilegivel(plataformas)
        _aponta_a_tela_de_hoje(texto)
        assert "Salvar e validar" in texto


def test_sincronizar_agora_com_senha_ilegivel_aponta_integracoes(cliente, db,
                                                                 escola_completa,
                                                                 monkeypatch):
    eid = escola_completa["escola"].id
    _credenciais_ilegiveis(db, eid, monkeypatch, "matific", "elefante")
    r = cliente.post(f"{API}/escolas/{eid}/sync/agora")
    assert r.status_code == 400, r.text
    _aponta_a_tela_de_hoje(r.json()["detail"])


def test_placar_ao_vivo_aponta_integracoes(cliente, db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    url = f"{API}/escolas/{eid}/sync/matific/placar-ao-vivo?periodo=semana&forcar=true"
    sem = cliente.get(url)
    assert sem.status_code == 400, sem.text
    assert "não estão configuradas" in sem.json()["detail"]
    _aponta_a_tela_de_hoje(sem.json()["detail"])

    _credenciais_ilegiveis(db, eid, monkeypatch, "matific")
    ilegivel = cliente.get(url)
    assert ilegivel.status_code == 400, ilegivel.text
    _aponta_a_tela_de_hoje(ilegivel.json()["detail"])


def test_diagnostico_do_elefante_aponta_integracoes(db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    monkeypatch.setattr(connectors, "obter", lambda _p: pytest.fail("o robô não roda"))
    with pytest.raises(ErroConector) as sem:
        diag.executar(db, eid)
    assert sem.value.codigo == "sem_credencial"
    _aponta_a_tela_de_hoje(str(sem.value))

    _credenciais_ilegiveis(db, eid, monkeypatch, "elefante")
    with pytest.raises(ErroConector) as ilegivel:
        diag.executar(db, eid)
    assert ilegivel.value.codigo == vault.CODIGO_CREDENCIAL_ILEGIVEL
    _aponta_a_tela_de_hoje(str(ilegivel.value))
