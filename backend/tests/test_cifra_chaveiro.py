"""Chaveiro da cifra em repouso — rotação PLANEJADA (A1 §3.2, lacunas L3 e "chaveiro").

Antes: nenhuma chave anterior era aceita — girar a DATA_ENCRYPTION_KEY (ou a SECRET_KEY,
nas cifras legadas) deixava ilegível tudo o que ela cifrou, e a DEK vazia, curta ou igual
à SECRET_KEY caía no legado sem aviso. Agora:

* ``DATA_ENCRYPTION_KEYS_ANTERIORES`` e ``CHAVE_CIFRA_LEGADA_ANTERIOR`` entram no anel
  SÓ para decifrar (e conferir o hash do código do Quest); a cifra sai sempre com a atual;
* NENHUMA delas valida JWT (aceitar a SECRET_KEY antiga aceitaria token forjado);
* ``situacao_da_cifra``/``recifrar`` dizem e corrigem a chave de cada cifra sem expor nada;
* o /sistema/diagnostico e o log do boot dizem se a DEK está ativa, longa e distinta.

Letras do §3.2 cobertas aqui: (a) (b) (c) (f) (g) (h) (k) (m); (d) (e) (i) (j) em
test_recifrar_segredos.py. Chaves e códigos 100% fictícios, gerados em memória e nunca
impressos.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.core import security
from app.core.config import Settings, settings
from app.main import app
from app.quest.services import credenciais as quest
from tests._infra_comum import BOOT, ambiente, rodar, sqlite_url  # noqa: F401 — fixture


def _chave(prefixo: str) -> str:
    return f"{prefixo}-{secrets.token_urlsafe(40)}"


SK0, SK1 = _chave("sk0"), _chave("sk1")
DEK0, DEK1 = _chave("dek0"), _chave("dek1")


def _config(monkeypatch, *, sk: str, dek: str = "", anteriores: str = "",
            legada: str = "") -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", sk)
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", dek)
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEYS_ANTERIORES", anteriores)
    monkeypatch.setattr(settings, "CHAVE_CIFRA_LEGADA_ANTERIOR", legada)


def _cifrar(monkeypatch, valor: str, **chaves) -> str:
    _config(monkeypatch, **chaves)
    return security.cifrar_segredo(valor)


def _so_com(segredo: str, token: str) -> str:
    """Decifra com UMA chave isolada (fora do app): prova qual chave cifrou."""
    return Fernet(security._derivar_fernet(segredo)).decrypt(token.encode()).decode()


# --- (a) o anel abre o legado e a DEK antiga -----------------------------------------

def test_a_anel_abre_o_legado_e_a_dek_antiga(monkeypatch):
    legado = _cifrar(monkeypatch, "valor-legado", sk=SK0)              # antes da DEK
    com_dek0 = _cifrar(monkeypatch, "valor-dek0", sk=SK0, dek=DEK0)

    # Rotação das duas, SEM anteriores: tudo ilegível (o defeito de antes).
    _config(monkeypatch, sk=SK1, dek=DEK1)
    assert security.decifrar_segredo(legado) is None
    assert security.decifrar_segredo(com_dek0) is None

    # Com as anteriores, abre — e a situação diz que a cifra está numa anterior.
    _config(monkeypatch, sk=SK1, dek=DEK1, anteriores=DEK0, legada=SK0)
    assert security.decifrar_segredo(legado) == "valor-legado"
    assert security.decifrar_segredo(com_dek0) == "valor-dek0"
    assert security.situacao_da_cifra(legado) == security.CIFRA_ANTERIOR
    assert security.situacao_da_cifra(com_dek0) == security.CIFRA_ANTERIOR

    # Só a DEK anterior não abre o legado; só a legada não abre a DEK0.
    _config(monkeypatch, sk=SK1, dek=DEK1, anteriores=DEK0)
    assert security.decifrar_segredo(legado) is None
    _config(monkeypatch, sk=SK1, dek=DEK1, legada=SK0)
    assert security.decifrar_segredo(com_dek0) is None


def test_a_cifra_nova_sai_sempre_com_a_atual(monkeypatch):
    _config(monkeypatch, sk=SK1, dek=DEK1, anteriores=f"{DEK0}", legada=SK0)
    novo = security.cifrar_segredo("valor-novo")
    assert _so_com(DEK1, novo) == "valor-novo"
    for anterior in (DEK0, SK0, SK1):
        with pytest.raises(Exception):
            _so_com(anterior, novo)
    assert security.situacao_da_cifra(novo) == security.CIFRA_PRIMARIA
    assert security.segredos_da_cifra() == [DEK1, DEK0, SK1, SK0]

    # Sem DEK: a primária continua sendo a SECRET_KEY (comportamento de sempre).
    _config(monkeypatch, sk=SK1, anteriores=DEK0)
    assert security.segredos_da_cifra()[0] == SK1
    assert _so_com(SK1, security.cifrar_segredo("x")) == "x"


# --- (b) nenhuma chave anterior valida JWT ------------------------------------------

def _forjar(segredo: str, **claims) -> str:
    agora = datetime.now(timezone.utc)
    return pyjwt.encode({"iat": agora, "exp": agora + timedelta(hours=8), **claims},
                        segredo, algorithm="HS256")


def test_b_jwt_assinado_com_chave_anterior_e_recusado(monkeypatch, cliente, db, escola_completa):
    admin = escola_completa["admin"]
    sk_atual = settings.SECRET_KEY
    _config(monkeypatch, sk=sk_atual, dek=DEK1, anteriores=DEK0, legada=SK0)
    claims = {"sub": str(admin.id), "ver": admin.token_version or 0}

    assert security.decodificar_token(_forjar(sk_atual, **claims)) is not None   # controle
    for segredo in (SK0, DEK0, DEK1):
        forjado = _forjar(segredo, **claims)
        assert security.decodificar_token(forjado) is None
        r = TestClient(app).get("/api/v1/auth/me",
                                headers={"Authorization": f"Bearer {forjado}"})
        assert r.status_code == 401
    assert cliente.get("/api/v1/auth/me").status_code == 200                    # sessão de verdade


def test_b_jwt_do_quest_com_chave_anterior_e_recusado(monkeypatch, db, escola_completa):
    sk_atual = settings.SECRET_KEY
    _config(monkeypatch, sk=sk_atual, dek=DEK1, anteriores=DEK0, legada=SK0)
    escola, aluno = escola_completa["escola"], escola_completa["alunos"][0]
    cred = quest.garantir_credencial_aluno(db, escola.id, aluno)["credencial"]
    db.commit()
    claims = {"sub": str(cred.id), "papel": "aluno", "ver": cred.token_version or 0}

    valido = TestClient(app).get("/api/v1/quest/perfil", headers={
        "Authorization": f"Bearer {quest.criar_token_aluno(cred)}"})
    assert valido.status_code != 401, valido.text                               # controle
    for segredo in (SK0, DEK0):
        forjado = _forjar(segredo, **claims)
        r = TestClient(app).get("/api/v1/quest/perfil",
                                headers={"Authorization": f"Bearer {forjado}"})
        assert r.status_code == 401


# --- (c) o rotate converge ----------------------------------------------------------

def test_c_recifrar_leva_para_a_primaria_e_converge(monkeypatch):
    legado = _cifrar(monkeypatch, "senha-ficticia-1", sk=SK0)
    com_dek0 = _cifrar(monkeypatch, "senha-ficticia-2", sk=SK0, dek=DEK0)
    _config(monkeypatch, sk=SK1, dek=DEK1, anteriores=DEK0, legada=SK0)

    novos = [security.recifrar(t) for t in (legado, com_dek0)]
    assert [security.situacao_da_cifra(t) for t in novos] == [security.CIFRA_PRIMARIA] * 2
    de_novo = [security.recifrar(t) for t in novos]
    assert [security.situacao_da_cifra(t) for t in de_novo] == [security.CIFRA_PRIMARIA] * 2

    # Depois de recifrar, só as chaves NOVAS bastam (as anteriores podem sair).
    _config(monkeypatch, sk=SK1, dek=DEK1)
    for lote in (novos, de_novo):
        assert [security.decifrar_segredo(t) for t in lote] == ["senha-ficticia-1",
                                                               "senha-ficticia-2"]
    assert security.decifrar_segredo(legado) is None


# --- (f) cifra corrompida vira "ilegível" sem exceção ---------------------------------

@pytest.mark.parametrize("token", ["gAAAAA-nao-e-fernet", "x", "ção-não-ascii", "gAAAAAB" + "A" * 80])
def test_f_token_corrompido_vira_ilegivel_sem_excecao(monkeypatch, token):
    _config(monkeypatch, sk=SK1, dek=DEK1, anteriores=DEK0, legada=SK0)
    assert security.situacao_da_cifra(token) == security.CIFRA_ILEGIVEL
    assert security.recifrar(token) is None
    assert security.decifrar_segredo(token) is None


def test_f_vazio_e_cifra_de_chave_desconhecida(monkeypatch):
    estranho = _cifrar(monkeypatch, "x", sk=_chave("outra"), dek=_chave("outra-dek"))
    _config(monkeypatch, sk=SK1, dek=DEK1, anteriores=DEK0, legada=SK0)
    assert security.situacao_da_cifra(None) == security.CIFRA_VAZIA
    assert security.situacao_da_cifra("") == security.CIFRA_VAZIA
    assert security.recifrar(None) is None and security.recifrar("") is None
    assert security.situacao_da_cifra(estranho) == security.CIFRA_ILEGIVEL
    assert security.recifrar(estranho) is None


# --- (g) anterior vazia ou igual à primária: ignorada (e recusada em produção) --------

def test_g_anel_ignora_vazias_repetidas_e_iguais_a_atual(monkeypatch):
    _config(monkeypatch, sk=SK1, dek=DEK1,
            anteriores=f" , {DEK1} ,, {DEK0} ,{DEK0}, {SK1} ", legada="   ")
    assert security.segredos_da_cifra() == [DEK1, DEK0, SK1]
    for legada in (f"  {SK1}  ", DEK1, f" {DEK1}"):
        _config(monkeypatch, sk=SK1, dek=DEK1, legada=legada)
        assert security.segredos_da_cifra() == [DEK1, SK1]
    d = security.diagnostico_cifra()
    assert d["anteriores_configuradas"] == 0 and d["legada_anterior_configurada"] is False
    # DEK só com espaços ou igual à SECRET_KEY: a primária é a SECRET_KEY.
    for dek in ("   ", f" {SK1} "):
        _config(monkeypatch, sk=SK1, dek=dek, anteriores=DEK0)
        assert security.segredos_da_cifra() == [SK1, DEK0]


_PRODUCAO = {"_env_file": None, "ENV": "producao",
             "DATABASE_URL": "postgresql+psycopg://app@127.0.0.1:55432/cifra_test"}


@pytest.mark.parametrize("campo,valor", [
    ("DATA_ENCRYPTION_KEYS_ANTERIORES", "{dek}"),
    ("DATA_ENCRYPTION_KEYS_ANTERIORES", "{outra}, {dek}"),
    ("DATA_ENCRYPTION_KEYS_ANTERIORES", "{sk}"),
    ("CHAVE_CIFRA_LEGADA_ANTERIOR", "{sk}"),
    ("CHAVE_CIFRA_LEGADA_ANTERIOR", " {dek} "),
])
def test_g_producao_recusa_anterior_igual_a_atual(campo, valor):
    sk, dek, outra = _chave("sk"), _chave("dek"), _chave("outra")
    valor = valor.format(sk=sk, dek=dek, outra=outra)
    with pytest.raises(RuntimeError) as erro:
        Settings(**_PRODUCAO, SECRET_KEY=sk, DATA_ENCRYPTION_KEY=dek, **{campo: valor})
    for segredo in (sk, dek, outra):
        assert segredo not in str(erro.value)            # a mensagem não leva valor


def test_g_producao_aceita_anteriores_distintas_e_dev_so_avisa():
    sk, dek = _chave("sk"), _chave("dek")
    s = Settings(**_PRODUCAO, SECRET_KEY=sk, DATA_ENCRYPTION_KEY=dek,
                 DATA_ENCRYPTION_KEYS_ANTERIORES=f"{DEK0},{DEK1}",
                 CHAVE_CIFRA_LEGADA_ANTERIOR=SK0)
    assert s.DATA_ENCRYPTION_KEYS_ANTERIORES == f"{DEK0},{DEK1}"
    with pytest.warns(UserWarning, match="ANTERIOR"):
        Settings(_env_file=None, ENV="dev", SECRET_KEY=sk, DATA_ENCRYPTION_KEY=dek,
                 DATA_ENCRYPTION_KEYS_ANTERIORES=dek)


def test_secret_key_efemera_e_calculada_nunca_lida_do_ambiente(monkeypatch):
    with pytest.warns(UserWarning, match="efêmera"):
        efemera = Settings(_env_file=None, ENV="dev", SECRET_KEY="curta")
    assert efemera.SECRET_KEY_EFEMERA is True
    monkeypatch.setenv("SECRET_KEY_EFEMERA", "true")
    assert Settings(_env_file=None, ENV="dev", SECRET_KEY=_chave("sk")).SECRET_KEY_EFEMERA is False


# --- (k) hash do Quest feito com uma anterior entra pelo índice e é regravado --------

def _cartao(db, escola_completa, indice: int):
    escola, aluno = escola_completa["escola"], escola_completa["alunos"][indice]
    cred = quest.garantir_credencial_aluno(db, escola.id, aluno)["credencial"]
    db.commit()
    return cred


def test_k_hash_do_quest_de_uma_anterior_entra_pelo_indice(db, escola_completa, monkeypatch,
                                                           caplog):
    monkeypatch.setattr(quest, "_FALLBACK_TEXTO_CLARO", False)   # o futuro sem a coluna
    _config(monkeypatch, sk=SK0, dek=DEK0)
    com_dek0 = _cartao(db, escola_completa, 0)
    _config(monkeypatch, sk=SK0)
    sem_dek = _cartao(db, escola_completa, 1)                     # produção sem DEK: SK0
    h_dek0, h_sk0 = com_dek0.codigo_login_hash, sem_dek.codigo_login_hash

    # Rotação das duas SEM anteriores e sem fallback: o cartão não entra (o defeito).
    _config(monkeypatch, sk=SK1, dek=DEK1)
    assert quest.buscar_por_codigo(db, com_dek0.codigo_login) is None
    assert quest.buscar_por_codigo(db, sem_dek.codigo_login) is None

    _config(monkeypatch, sk=SK1, dek=DEK1, anteriores=DEK0, legada=SK0)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="constela.quest"):
        assert quest.buscar_por_codigo(db, com_dek0.codigo_login).id == com_dek0.id
        assert quest.buscar_por_codigo(db, sem_dek.codigo_login).id == sem_dek.id
    assert not caplog.records                                     # índice, não fallback
    assert com_dek0.codigo_login_hash == quest.hash_codigo(com_dek0.codigo_login) != h_dek0
    assert sem_dek.codigo_login_hash == quest.hash_codigo(sem_dek.codigo_login) != h_sk0
    db.commit()

    # Regravados na DEK1: as anteriores já podem sair.
    _config(monkeypatch, sk=SK1, dek=DEK1)
    assert quest.buscar_por_codigo(db, com_dek0.codigo_login).id == com_dek0.id
    assert quest.contar_hashes_divergentes(db) == 0


def test_k_preencher_hashes_regrava_todos_na_primaria(db, escola_completa, monkeypatch):
    _config(monkeypatch, sk=SK0, dek=DEK0)
    cartoes = [_cartao(db, escola_completa, i) for i in range(3)]
    _config(monkeypatch, sk=SK1, dek=DEK1)
    assert quest.contar_hashes_divergentes(db) == 3         # sem anteriores: trancados
    _config(monkeypatch, sk=SK1, dek=DEK1, anteriores=DEK0)
    assert quest.contar_hashes_divergentes(db) == 0         # com elas: entram pelo índice
    assert quest.preencher_hashes_ausentes(db) == 3         # e o lote regrava na DEK1
    db.commit()
    assert quest.preencher_hashes_ausentes(db) == 0
    assert all(c.codigo_login_hash == quest.hash_codigo(c.codigo_login) for c in cartoes)
    _config(monkeypatch, sk=SK1, dek=DEK1)
    assert quest.contar_hashes_divergentes(db) == 0         # as anteriores já podem sair


# --- L3: diagnóstico e aviso do boot -------------------------------------------------

def test_diagnostico_da_cifra_por_cenario(monkeypatch):
    _config(monkeypatch, sk=SK1)
    d = security.diagnostico_cifra()
    assert d["dedicada_ativa"] is False and d["dek_tamanho_ok"] is False
    assert d["dek_distinta_da_secret_key"] is False and d["anteriores_configuradas"] == 0
    _config(monkeypatch, sk=SK1, dek="curta-mas-distinta")
    d = security.diagnostico_cifra()
    assert d["dedicada_ativa"] is True and d["dek_tamanho_ok"] is False
    assert d["dek_distinta_da_secret_key"] is True
    _config(monkeypatch, sk=SK1, dek=SK1)
    assert security.diagnostico_cifra()["dedicada_ativa"] is False
    _config(monkeypatch, sk=SK1, dek=DEK1, anteriores=f"{DEK0}, {_chave('x')}", legada=SK0)
    d = security.diagnostico_cifra()
    assert d["dedicada_ativa"] and d["dek_tamanho_ok"] and d["dek_distinta_da_secret_key"]
    assert d["anteriores_configuradas"] == 3 and d["legada_anterior_configurada"] is True
    assert all(isinstance(v, (bool, int)) for v in d.values())


@pytest.mark.parametrize("dek,trecho", [
    ("", "vazia"), ("   ", "vazia"), ("SK", "igual à SECRET_KEY"), ("curta", "menos de 32"),
])
def test_aviso_no_boot_quando_a_dek_esta_vazia_curta_ou_igual(monkeypatch, caplog, dek, trecho):
    _config(monkeypatch, sk=SK1, dek=dek.replace("SK", SK1))
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="constela"):
        assert security.registrar_avisos_da_cifra(logging.getLogger("constela")) == 1
    assert trecho in caplog.text and SK1 not in caplog.text


def test_boot_do_app_escreve_o_aviso_sem_valor(sqlite_url):  # noqa: F811
    """O aviso sai no boot de verdade (``import app.main`` num processo novo)."""
    anterior = _chave("dek-anterior")
    p = rodar(BOOT + "import app.main\n", ambiente(
        sqlite_url, False, DATA_ENCRYPTION_KEY="", DATA_ENCRYPTION_KEYS_ANTERIORES=anterior))
    log = p.stdout + p.stderr
    assert p.returncode == 0, log[-3000:]
    assert "Cifra em repouso" in log and "DATA_ENCRYPTION_KEY vazia" in log
    assert "ANTERIOR" in log and anterior not in log

    dek = _chave("dek-boa")
    p = rodar(BOOT + "import app.main\n", ambiente(sqlite_url, False, DATA_ENCRYPTION_KEY=dek))
    log = p.stdout + p.stderr
    assert p.returncode == 0, log[-3000:]
    assert "Cifra em repouso" not in log and dek not in log


def test_aviso_no_boot_quando_a_dek_tem_virgula(monkeypatch, caplog):
    """A DEK com vírgula funciona como atual, mas na rotação documentada (a que saiu vai
    para DATA_ENCRYPTION_KEYS_ANTERIORES, lista separada por vírgula) vira dois pedaços
    inúteis e o que ela cifrou fica ilegível. O boot (inclusive o de produção, que não
    recusa) avisa, sem nenhum pedaço da chave."""
    parte_a, parte_b = _chave("dek-a"), _chave("dek-b")
    dek_com_virgula = f"{parte_a},{parte_b}"
    _config(monkeypatch, sk=SK1, dek=dek_com_virgula)
    cifra = security.cifrar_segredo("segredo-ficticio-virgula")
    _config(monkeypatch, sk=SK1, dek=DEK1, anteriores=dek_com_virgula)
    assert security.situacao_da_cifra(cifra) == security.CIFRA_ILEGIVEL   # o motivo

    _config(monkeypatch, sk=SK1, dek=dek_com_virgula)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="constela"):
        assert security.registrar_avisos_da_cifra(logging.getLogger("constela")) == 1
    assert "vírgula" in caplog.text
    assert parte_a not in caplog.text and parte_b not in caplog.text
    assert Settings(**_PRODUCAO, SECRET_KEY=SK1,
                    DATA_ENCRYPTION_KEY=dek_com_virgula).em_producao   # só aviso: não recusa


def test_sem_aviso_com_a_dek_boa(monkeypatch, caplog):
    _config(monkeypatch, sk=SK1, dek=DEK1)
    with caplog.at_level(logging.WARNING, logger="constela"):
        assert security.registrar_avisos_da_cifra(logging.getLogger("constela")) == 0
    assert security.avisos_da_cifra() == []


# --- (h) nenhum valor no log ---------------------------------------------------------

def test_h_nenhuma_chave_nem_segredo_no_log(monkeypatch, caplog):
    legado = _cifrar(monkeypatch, "segredo-ficticio-h", sk=SK0)
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        _config(monkeypatch, sk=SK1, dek="curta", anteriores=DEK0, legada=SK0)
        security.registrar_avisos_da_cifra(logging.getLogger("constela"))
        security.situacao_da_cifra(legado)
        security.recifrar(legado)
        security.situacao_da_cifra("gAAAA-corrompido")
    texto = caplog.text
    assert caplog.records                                          # houve aviso
    for valor in (SK0, SK1, DEK0, "curta", "segredo-ficticio-h", legado):
        assert valor not in texto


# --- (m) o diagnóstico nunca devolve o valor das chaves -------------------------------

def test_m_diagnostico_nao_devolve_chave(cliente_global, db, escola_completa, monkeypatch):
    from app.sync import vault
    from app.sync.interfaces import Credenciais

    sk_atual = settings.SECRET_KEY
    _config(monkeypatch, sk=sk_atual, dek=DEK0)
    vault.salvar_credencial(db, escola_completa["escola"].id, "elefante",
                            Credenciais("robo@x.invalid", "senha-ficticia-m"))
    db.commit()
    _config(monkeypatch, sk=sk_atual, dek=DEK1, anteriores=f"{DEK0},{_chave('dek-x')}",
            legada=SK0)
    monkeypatch.setattr(settings, "SECRET_KEY_EFEMERA", True)
    assert cliente_global.get("/api/v1/sistema/diagnostico").json()["cifra"][
        "secret_key_efemera"] is True
    monkeypatch.setattr(settings, "SECRET_KEY_EFEMERA", False)
    r = cliente_global.get("/api/v1/sistema/diagnostico")
    assert r.status_code == 200, r.text
    cifra = r.json()["cifra"]
    assert cifra["dedicada_ativa"] is True and cifra["dek_tamanho_ok"] is True
    assert cifra["dek_distinta_da_secret_key"] is True
    assert cifra["anteriores_configuradas"] == 3
    assert cifra["secret_key_efemera"] is False
    assert set(cifra["contagens"]) == {"plataforma_credenciais", "configuracoes.assistente",
                                       "configuracoes.matific_sessao"}
    assert cifra["contagens"]["plataforma_credenciais"] == {
        "primaria": 0, "anterior": 1, "ilegivel": 0, "vazio": 0}
    assert cifra["pendentes"] == 1
    for valor in (sk_atual, DEK1, DEK0, SK0, security._derivar_fernet(DEK1).decode(),
                  "senha-ficticia-m", "robo@x.invalid"):
        assert valor not in r.text


def test_m_diagnostico_continua_so_do_admin_global(cliente):
    assert cliente.get("/api/v1/sistema/diagnostico").status_code == 403
    assert TestClient(app).get("/api/v1/sistema/diagnostico").status_code == 401
