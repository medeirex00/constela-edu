"""A métrica ``sync_credencial_status`` publica o status DERIVADO (rodada 3 do e97).

Achado (pacote de revisão do marco 1, §6 "Métrica de credencial"): o coletor lia só
a coluna ``status`` gravada. Depois de trocar a chave de cifra sem recifrar, o
/sync/status já mostrava 'ilegivel', mas o /metrics seguia publicando 'valida' — e a
regra sugerida ``status=~"invalida|expirada"`` só disparava depois que uma
sincronização falhada gravasse 'invalida'.

O certo: o mesmo critério do /sync/status (``vault.status_efetivo``), sem decifrar
mais que o necessário (cada cifra uma vez por processo e por anel de chaves) e
dentro do prazo total do coletor. Dados 100% fictícios; chaves geradas em memória e
nunca impressas; sem rede.
"""
from __future__ import annotations

import json
import secrets
import threading
import time
from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.security import cifrar_segredo
from app.models import Escola
from app.models.sincronizacao import PlataformaCredencial
from app.sync import metricas, vault
from app.sync.interfaces import Credenciais

T = datetime(2026, 10, 24, 12, 0, 0)
SENHA_FICTICIA = "senha-ficticia-metrica-e97c"


def _chave(prefixo: str) -> str:
    return f"{prefixo}-{secrets.token_urlsafe(40)}"


@pytest.fixture(autouse=True)
def _memo_limpo(monkeypatch):
    """Cada teste começa sem nenhuma legibilidade conferida."""
    monkeypatch.setattr(metricas, "_legibilidade", {}, raising=False)


def _coletor(db):
    return metricas.ColetorSync(fabrica=sessionmaker(bind=db.get_bind()),
                                relogio=lambda: T)


def _amostras(coletor) -> dict:
    saida = {}
    for familia in coletor.collect():
        for s in familia.samples:
            saida[(s.name, tuple(sorted(s.labels.items())))] = s.value
    return saida


def _credenciais_publicadas(amostras) -> dict:
    return {(dict(k[1])["escola_id"], dict(k[1])["plataforma"]): dict(k[1])["status"]
            for k, v in amostras.items() if k[0] == "sync_credencial_status" and v == 1}


def _cred(db, eid, plat, status="valida"):
    linha = vault.salvar_credencial(db, eid, plat, Credenciais(
        usuario="robo@escola.invalid", senha=SENHA_FICTICIA))
    vault.marcar_status(db, linha, status)
    db.flush()
    return linha


def _escola(db, nome):
    e = Escola(nome=nome, ano_letivo_ativo=2026)
    db.add(e)
    db.flush()
    return e.id


def test_credencial_ilegivel_sai_ilegivel_na_metrica_como_no_status(db, escola_completa,
                                                                    cliente):
    """Antes: as duas ilegíveis saíam 'valida' e 'invalida' (o gravado)."""
    e1 = escola_completa["escola"].id
    e2 = _escola(db, "ESCOLA FICTICIA METRICA DOIS")
    _cred(db, e1, "elefante", "valida")                          # legível
    _cred(db, e1, "matific", "valida").segredo_cifrado = "gAAAAA-isto-nao-e-um-token-fernet"
    _cred(db, e2, "matific", "invalida").segredo_cifrado = cifrar_segredo(
        json.dumps(["lista", "em vez de objeto"]))               # abre, fora do formato
    db.commit()

    publicadas = _credenciais_publicadas(_amostras(_coletor(db)))
    assert publicadas == {(str(e1), "elefante"): "valida",
                          (str(e1), "matific"): "ilegivel",
                          (str(e2), "matific"): "ilegivel"}
    # O MESMO critério do /sync/status: linha a linha, igual a vault.status_efetivo…
    for linha in db.execute(select(PlataformaCredencial)).scalars():
        assert publicadas[(str(linha.escola_id), linha.plataforma)] == \
            vault.status_efetivo(linha)
    # …e igual ao que a tela recebe.
    r = cliente.get(f"/api/v1/escolas/{e1}/sync/status")
    assert r.status_code == 200, r.text
    tela = {p["plataforma"]: p["credencial_status"] for p in r.json()["plataformas"]}
    assert tela["elefante"] == "valida" and tela["matific"] == "ilegivel"
    # Derivado na leitura: nada gravado.
    db.expire_all()
    assert vault.obter_linha(db, e1, "matific").status == "valida"


def test_rotacao_da_chave_sem_recifrar_vira_ilegivel_e_volta_com_a_chave(
        db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    k0 = _chave("dek0")
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", k0)
    _cred(db, eid, "elefante", "valida")
    db.commit()
    coletor = _coletor(db)
    assert _credenciais_publicadas(_amostras(coletor)) == {(str(eid), "elefante"): "valida"}

    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", _chave("dek1"))   # sem recifrar
    assert _credenciais_publicadas(_amostras(coletor)) == {(str(eid), "elefante"): "ilegivel"}

    # A chave antiga de volta: o "abre ou não" é por anel de chaves, não fica velho.
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", k0)
    assert _credenciais_publicadas(_amostras(coletor)) == {(str(eid), "elefante"): "valida"}


def test_cada_cifra_e_aberta_uma_vez_por_anel_de_chaves(db, escola_completa, monkeypatch):
    """Sem decifrar mais que o necessário: os scrapes seguintes reusam o resultado;
    só a cifra nova (recadastro) ou a troca de chave decifram de novo."""
    eid = escola_completa["escola"].id
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", _chave("dek0"))
    _cred(db, eid, "elefante")
    _cred(db, eid, "matific")
    db.commit()
    original = vault.credencial_legivel
    chamadas: list[int] = []

    def _contando(linha):
        chamadas.append(1)
        return original(linha)

    monkeypatch.setattr(metricas.vault, "credencial_legivel", _contando)
    coletor = _coletor(db)
    for _ in range(3):
        assert _credenciais_publicadas(_amostras(coletor)) == {
            (str(eid), "elefante"): "valida", (str(eid), "matific"): "valida"}
    assert len(chamadas) == 2                       # uma por credencial, não por scrape

    _cred(db, eid, "matific", "nao_validada")       # recadastro: cifra nova
    db.commit()
    assert _credenciais_publicadas(_amostras(coletor))[(str(eid), "matific")] == "nao_validada"
    assert len(chamadas) == 3

    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", _chave("dek1"))
    assert set(_credenciais_publicadas(_amostras(coletor)).values()) == {"ilegivel"}
    assert len(chamadas) == 5


def test_decifra_respeita_o_prazo_total_do_coletor(db, escola_completa, monkeypatch):
    """Prazo esgotado antes de decifrar: ``PrazoDoColetorEsgotado`` (o scrape vira
    ``sync_coletor_sucesso 0``, sem série parcial)."""
    eid = escola_completa["escola"].id
    _cred(db, eid, "elefante")
    db.commit()
    with pytest.raises(metricas.PrazoDoColetorEsgotado):
        metricas.coletar_familias(db, agora=T, fim=time.monotonic() - 1)


def test_decifra_lenta_vira_coletor_sem_sucesso_sem_serie_de_credencial(
        db, escola_completa, monkeypatch):
    """A decifra conta no prazo total do scrape: passou, ``sync_coletor_sucesso 0``
    e nenhuma série do banco (a leitura termina sozinha em segundo plano)."""
    eid = escola_completa["escola"].id
    _cred(db, eid, "elefante")
    db.commit()
    liberar = threading.Event()

    def _lenta(_linha):
        liberar.wait(10)          # teto folgado: o teste libera logo depois do scrape
        return True

    monkeypatch.setattr(metricas.vault, "credencial_legivel", _lenta)
    monkeypatch.setattr(metricas, "PRAZO_COLETOR_S", 0.3)
    coletor = _coletor(db)
    try:
        amostras = _amostras(coletor)
    finally:
        liberar.set()
        if coletor._em_curso is not None:
            coletor._em_curso.join(10)
    assert amostras[("sync_coletor_sucesso", ())] == 0
    assert not any(k[0] == "sync_credencial_status" for k in amostras)
