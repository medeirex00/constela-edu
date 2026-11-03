"""S16 — credencial ilegível não aparece como conectada/'valida' (regressão da e92 c03).

Achado: depois de trocar a chave de cifra (DATA_ENCRYPTION_KEY, ou a SECRET_KEY para as
cifras legadas) sem recifrar, ``vault.obter_credencial`` devolve None, mas o /sync/status
lia só a coluna ``status`` gravada: a integração seguia "conectada" e 'valida', o botão
"Sincronizar" ficava habilitado e o "Testar conexão" respondia "Nenhuma credencial
configurada". O certo: ``credencial_status='ilegivel'``, ``conectada=False``, sem exceção
e sem detalhe da falha da cifra — e a tela pede o recadastro.

Dados 100% fictícios; chaves geradas em memória e nunca impressas.
"""
import json
import secrets

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.core.security import cifrar_segredo
from app.main import app
from app.models.sincronizacao import PlataformaCredencial
from app.sync import router as sync_router
from app.sync import service, vault
from app.sync.interfaces import Credenciais

SENHA_FICTICIA = "senha-ficticia-s16"


def _chave(prefixo: str) -> str:
    return f"{prefixo}-{secrets.token_urlsafe(40)}"


def _status(cli, eid, plataforma="elefante"):
    r = cli.get(f"/api/v1/escolas/{eid}/sync/status")
    assert r.status_code == 200, r.text
    return next(p for p in r.json()["plataformas"] if p["plataforma"] == plataforma), r.text


def _credencial_valida(db, eid, plataforma="elefante"):
    vault.salvar_credencial(db, eid, plataforma,
                            Credenciais(usuario="robo@escola.invalid", senha=SENHA_FICTICIA))
    vault.marcar_status(db, vault.obter_linha(db, eid, plataforma), "valida")
    db.commit()


def test_c03_credencial_ilegivel_nao_aparece_como_valida(db, escola_completa, monkeypatch):
    """A e92 c03, adaptada: rotação da SECRET_KEY com a cifra no legado (sem DEK)."""
    eid = escola_completa["escola"].id
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", "")
    _credencial_valida(db, eid)
    monkeypatch.setattr(service, "disparar_em_thread", lambda i: None)
    monkeypatch.setattr(settings, "SECRET_KEY", _chave("sk-nova"))
    assert vault.obter_credencial(db, eid, "elefante") is None      # ficou ilegível

    cli = TestClient(app)
    tok = cli.post("/api/v1/auth/login", data={"username": "admin@teste.local",
                                                 "password": "s3nh4"}).json()["access_token"]
    cli.headers["Authorization"] = f"Bearer {tok}"
    ele, corpo = _status(cli, eid)
    assert not (ele["conectada"] and ele["credencial_status"] == "valida")
    assert ele["credencial_status"] == "ilegivel"
    assert ele["conectada"] is False
    assert SENHA_FICTICIA not in corpo and "InvalidToken" not in corpo


def test_rotacao_da_dek_sem_recifrar_mostra_ilegivel_e_nao_grava(cliente, db, escola_completa,
                                                                 monkeypatch):
    eid = escola_completa["escola"].id
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", _chave("dek0"))
    _credencial_valida(db, eid)
    antes, _ = _status(cliente, eid)
    assert antes["credencial_status"] == "valida" and antes["conectada"] is True

    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", _chave("dek1"))   # sem recifrar
    ele, corpo = _status(cliente, eid)
    assert ele["credencial_status"] == "ilegivel" and ele["conectada"] is False
    assert SENHA_FICTICIA not in corpo
    # Derivado na leitura: a coluna gravada não muda (a chave antiga de volta = 'valida').
    db.expire_all()
    assert vault.obter_linha(db, eid, "elefante").status == "valida"


def test_testar_conexao_com_credencial_ilegivel_pede_recadastro(cliente, db, escola_completa,
                                                                monkeypatch):
    eid = escola_completa["escola"].id
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", _chave("dek0"))
    _credencial_valida(db, eid)
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", _chave("dek1"))
    chamado = []
    monkeypatch.setattr(service, "disparar_em_thread", lambda i: chamado.append(i))

    r = cliente.post(f"/api/v1/escolas/{eid}/sync/credenciais/elefante/testar")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is False and d["codigo"] == sync_router.CODIGO_CREDENCIAL_ILEGIVEL
    assert "Nenhuma credencial configurada" not in d["mensagem"]
    assert "Salvar e validar" in d["mensagem"]
    # O texto do /testar é o do aviso do formulário (router), NÃO o do vault que o
    # "Sincronizar agora" usa — o docs/SINCRONIZACAO.md descreve os dois assim
    # (integração 3 do e97, esquemas-sync-docs achado 1).
    assert d["mensagem"] == sync_router.MENSAGEM_CREDENCIAL_ILEGIVEL
    assert d["mensagem"] != vault.mensagem_credencial_ilegivel(["elefante"])
    assert SENHA_FICTICIA not in r.text and "InvalidToken" not in r.text
    db.expire_all()
    assert vault.obter_linha(db, eid, "elefante").status == "valida"   # nada gravado
    assert chamado == []


def test_testar_sem_credencial_continua_400(cliente, escola_completa):
    eid = escola_completa["escola"].id
    r = cliente.post(f"/api/v1/escolas/{eid}/sync/credenciais/elefante/testar")
    assert r.status_code == 400
    assert "Nenhuma credencial configurada" in r.json()["detail"]


def test_cifra_corrompida_e_conteudo_fora_do_formato_viram_ilegivel_sem_excecao(
        cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    _credencial_valida(db, eid, "elefante")
    _credencial_valida(db, eid, "matific")
    ele = vault.obter_linha(db, eid, "elefante")
    ele.segredo_cifrado = "gAAAAA-isto-nao-e-um-token-fernet"
    mat = vault.obter_linha(db, eid, "matific")
    mat.segredo_cifrado = cifrar_segredo(json.dumps(["lista", "em vez de objeto"]))
    db.commit()

    assert vault.obter_credencial(db, eid, "elefante") is None
    assert vault.obter_credencial(db, eid, "matific") is None          # antes: AttributeError
    for plataforma in ("elefante", "matific"):
        p, _ = _status(cliente, eid, plataforma)
        assert p["credencial_status"] == "ilegivel" and p["conectada"] is False


def test_credencial_legivel_continua_como_estava(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    _credencial_valida(db, eid)
    linha = vault.obter_linha(db, eid, "elefante")
    assert vault.credencial_legivel(linha) is True
    assert vault.status_efetivo(linha) == "valida"
    assert vault.status_efetivo(None) == "nao_configurada"
    p, _ = _status(cliente, eid)
    assert p["credencial_status"] == "valida" and p["conectada"] is True
    m, _ = _status(cliente, eid, "matific")
    assert m["credencial_status"] == "nao_configurada" and m["conectada"] is False


def test_recadastro_com_a_chave_nova_sai_do_ilegivel(cliente, db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", _chave("dek0"))
    _credencial_valida(db, eid)
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", _chave("dek1"))
    assert _status(cliente, eid)[0]["credencial_status"] == "ilegivel"

    vault.salvar_credencial(db, eid, "elefante",
                            Credenciais(usuario="robo@escola.invalid", senha="outra-ficticia"))
    db.commit()
    p, _ = _status(cliente, eid)
    assert p["credencial_status"] == "nao_validada" and p["conectada"] is False
    linhas = db.execute(select(PlataformaCredencial)).scalars().all()
    assert len(linhas) == 1 and vault.credencial_legivel(linhas[0])


# ---------------------------------------------------------------------------
# Rodada 3 do e97: as AÇÕES com credencial ilegível não dizem "não configurada"
# (POST /sync/agora e o diagnóstico do Elefante). Antes: 'Nenhuma plataforma com
# credencial configurada' e 'As credenciais do Elefante não estão configuradas'.
# ---------------------------------------------------------------------------
def _execucoes(db, eid):
    from app.models.sincronizacao import SincronizacaoExecucao

    db.expire_all()
    return db.execute(select(SincronizacaoExecucao).where(
        SincronizacaoExecucao.escola_id == eid)).scalars().all()


def _sem_detalhe_interno(texto: str) -> None:
    for proibido in (SENHA_FICTICIA, "InvalidToken", "Fernet", "DATA_ENCRYPTION_KEY",
                     "SECRET_KEY", "Traceback"):
        assert proibido not in texto, proibido


def test_sincronizar_agora_com_credencial_ilegivel_pede_recadastro(cliente, db,
                                                                   escola_completa,
                                                                   monkeypatch):
    eid = escola_completa["escola"].id
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", _chave("dek0"))
    _credencial_valida(db, eid)
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", _chave("dek1"))   # sem recifrar
    disparadas = []
    monkeypatch.setattr(service, "disparar_em_thread", lambda i: disparadas.append(i))

    for caminho in (f"/api/v1/escolas/{eid}/sync/agora",
                    f"/api/v1/escolas/{eid}/sync/agora?plataforma=elefante"):
        r = cliente.post(caminho)
        assert r.status_code == 400, r.text
        detalhe = r.json()["detail"]
        assert "Nenhuma plataforma com credencial configurada" not in detalhe
        assert "senha salva do Elefante não pode mais ser lida" in detalhe
        assert "recadastrada" in detalhe and "Salvar e validar" in detalhe
        _sem_detalhe_interno(r.text)
    assert _execucoes(db, eid) == [] and disparadas == []
    assert vault.obter_linha(db, eid, "elefante").status == "valida"     # nada gravado


def test_sincronizar_agora_sem_credencial_continua_nao_configurada(cliente, escola_completa):
    eid = escola_completa["escola"].id
    r = cliente.post(f"/api/v1/escolas/{eid}/sync/agora")
    assert r.status_code == 400
    assert r.json()["detail"] == "Nenhuma plataforma com credencial configurada."


def test_sincronizar_agora_roda_a_legivel_e_pula_a_ilegivel(cliente, db, escola_completa,
                                                            monkeypatch):
    """Uma legível e uma ilegível: a legível roda (o card da outra mostra 'ilegivel')."""
    eid = escola_completa["escola"].id
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", _chave("dek0"))
    _credencial_valida(db, eid, "elefante")
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", _chave("dek1"))
    _credencial_valida(db, eid, "matific")                 # cifrada com a chave nova
    monkeypatch.setattr(service, "disparar_em_thread", lambda i: None)
    r = cliente.post(f"/api/v1/escolas/{eid}/sync/agora")
    assert r.status_code == 200, r.text
    assert [x["plataforma"] for x in r.json()] == ["matific"]
    assert _status(cliente, eid)[0]["credencial_status"] == "ilegivel"


def test_diagnostico_do_elefante_com_credencial_ilegivel_pede_recadastro(cliente, db,
                                                                       escola_completa,
                                                                       monkeypatch):
    from app.sync import connectors
    from app.sync import diagnostico_elefante as diag
    from app.sync.interfaces import ErroConector

    eid = escola_completa["escola"].id
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", _chave("dek0"))
    _credencial_valida(db, eid)
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", _chave("dek1"))

    def _nao_chama(_plataforma):
        raise AssertionError("o robô não pode rodar sem credencial legível")

    monkeypatch.setattr(connectors, "obter", _nao_chama)
    try:
        diag.executar(db, eid)
    except ErroConector as exc:
        assert exc.codigo == vault.CODIGO_CREDENCIAL_ILEGIVEL
        assert "não estão configuradas" not in str(exc)
        assert "recadastrada" in str(exc)
    else:
        raise AssertionError("o diagnóstico rodou com a credencial ilegível")

    r = cliente.post(f"/api/v1/escolas/{eid}/sync/elefante/diagnostico")
    assert r.status_code == 400, r.text
    detalhe = r.json()["detail"]
    assert "não estão configuradas" not in detalhe
    assert "senha salva do Elefante não pode mais ser lida" in detalhe
    _sem_detalhe_interno(r.text)


def test_diagnostico_sem_credencial_continua_nao_configurada(db, escola_completa):
    from app.sync import diagnostico_elefante as diag
    from app.sync.interfaces import ErroConector

    try:
        diag.executar(db, escola_completa["escola"].id)
    except ErroConector as exc:
        assert exc.codigo == "sem_credencial" and "não estão configuradas" in str(exc)
    else:
        raise AssertionError("esperava ErroConector sem_credencial")


# ---------------------------------------------------------------------------
# Resíduo do e97 (marco 2, §3): o PLACAR AO VIVO do Matific com credencial ilegível
# dizia "As credenciais do Matific não estão configuradas" — a credencial existe e
# só precisa ser recadastrada (o mesmo texto do /sync/agora).
# ---------------------------------------------------------------------------
def test_placar_ao_vivo_com_credencial_ilegivel_pede_recadastro(cliente, db, escola_completa,
                                                                monkeypatch):
    from app.sync import aovivo, connectors
    from app.sync.interfaces import ErroConector

    eid = escola_completa["escola"].id
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", _chave("dek0"))
    _credencial_valida(db, eid, "matific")
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", _chave("dek1"))   # sem recifrar
    aovivo._cache.clear()

    def _nao_chama(_plataforma):
        raise AssertionError("o Matific não pode ser consultado sem credencial legível")

    monkeypatch.setattr(connectors, "obter", _nao_chama)
    try:
        aovivo.placar_matific(db, eid, periodo="semana", inicio=None, fim=None, forcar=True)
    except ErroConector as exc:
        assert exc.codigo == vault.CODIGO_CREDENCIAL_ILEGIVEL
        assert exc.recuperavel is False
        assert "não estão configuradas" not in str(exc)
        assert str(exc) == vault.mensagem_credencial_ilegivel(["matific"])
    else:
        raise AssertionError("o placar ao vivo rodou com a credencial ilegível")

    r = cliente.get(f"/api/v1/escolas/{eid}/sync/matific/placar-ao-vivo?periodo=semana"
                    "&forcar=true")
    assert r.status_code == 400, r.text
    detalhe = r.json()["detail"]
    assert "não estão configuradas" not in detalhe
    assert "senha salva do Matific não pode mais ser lida" in detalhe
    assert "recadastrada" in detalhe and "Salvar e validar" in detalhe
    _sem_detalhe_interno(r.text)
    db.expire_all()
    assert vault.obter_linha(db, eid, "matific").status == "valida"      # nada gravado
    aovivo._cache.clear()


def test_placar_ao_vivo_sem_credencial_continua_nao_configurada(cliente, escola_completa):
    from app.sync import aovivo

    aovivo._cache.clear()
    eid = escola_completa["escola"].id
    r = cliente.get(f"/api/v1/escolas/{eid}/sync/matific/placar-ao-vivo?periodo=semana"
                    "&forcar=true")
    assert r.status_code == 400, r.text
    assert "não estão configuradas" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Resíduo do e97 (marco 2, §3): a EXECUÇÃO que falhava por credencial ilegível saía
# 'senha_invalida' e regravava a credencial como 'invalida' — a plataforma não
# recusou nada. Agora: motivo próprio 'credencial_ilegivel', texto honesto, o status
# gravado fica como estava (o /status deriva 'ilegivel').
# ---------------------------------------------------------------------------
class _ConectorQueNaoPodeRodar:
    plataforma = "elefante"
    versao = "teste"

    def __init__(self, validacao=None):
        self.validacao = validacao
        self.sincronizou = 0

    async def sincronizar(self, cred, contexto):
        self.sincronizou += 1
        raise AssertionError("a coleta não pode rodar sem credencial legível")

    async def testar_credenciais(self, cred, contexto):
        return self.validacao


def _alertas(db, eid, plataforma="elefante"):
    from app.models.sincronizacao import SincronizacaoAlerta

    db.expire_all()
    return db.execute(select(SincronizacaoAlerta).where(
        SincronizacaoAlerta.escola_id == eid,
        SincronizacaoAlerta.plataforma == plataforma)).scalars().all()


def _executar_com_credencial_ilegivel(db, eid, monkeypatch, conector):
    from app.sync import connectors

    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", _chave("dek0"))
    _credencial_valida(db, eid)
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", _chave("dek1"))   # sem recifrar
    monkeypatch.setattr(connectors, "obter", lambda _p: conector)
    monkeypatch.setattr(service, "agendador_ligado", lambda: True)        # retry possível
    ex = service.enfileirar(db, eid, "elefante", origem="scheduler")
    db.commit()
    service.executar(db, ex)
    return ex


def test_execucao_com_credencial_ilegivel_nao_regrava_invalida(cliente, db, escola_completa,
                                                               monkeypatch):
    eid = escola_completa["escola"].id
    conector = _ConectorQueNaoPodeRodar()
    ex = _executar_com_credencial_ilegivel(db, eid, monkeypatch, conector)

    assert conector.sincronizou == 0
    assert ex.status == "erro"
    assert ex.motivo == vault.CODIGO_CREDENCIAL_ILEGIVEL
    assert ex.erro_resumo == vault.mensagem_credencial_ilegivel(["elefante"])
    _sem_detalhe_interno(ex.erro_resumo)
    db.expire_all()
    linha = vault.obter_linha(db, eid, "elefante")
    assert linha.status == "valida"                    # antes: regravada 'invalida'
    assert linha.ultimo_erro is None
    assert _execucoes(db, eid)[-1].tentativa == 1 and len(_execucoes(db, eid)) == 1  # sem retry
    [alerta] = [a for a in _alertas(db, eid) if not a.resolvido]
    assert (alerta.tipo, alerta.severidade) == ("credencial_ilegivel", "critico")

    ele, corpo = _status(cliente, eid)
    assert ele["credencial_status"] == "ilegivel" and ele["conectada"] is False
    assert ele["falha_categoria"] == "configuracao"    # não "a plataforma recusou"
    _sem_detalhe_interno(corpo)


def test_execucao_sem_credencial_continua_nao_configurada(db, escola_completa, monkeypatch):
    from app.sync import connectors

    eid = escola_completa["escola"].id
    monkeypatch.setattr(connectors, "obter", lambda _p: _ConectorQueNaoPodeRodar())
    ex = service.enfileirar(db, eid, "elefante", origem="scheduler")
    db.commit()
    service.executar(db, ex)
    assert (ex.status, ex.motivo) == ("erro", "senha_invalida")
    assert ex.erro_resumo == "Credenciais não configuradas."
    assert vault.obter_linha(db, eid, "elefante") is None


def test_recadastro_fecha_o_alerta_de_credencial_ilegivel(cliente, db, escola_completa,
                                                          monkeypatch):
    """Salvar a senha de novo tira a causa do alerta, mesmo que o login falhe por
    outro motivo (que abre o alerta próprio dele)."""
    from app.sync.interfaces import ResultadoValidacao

    eid = escola_completa["escola"].id
    conector = _ConectorQueNaoPodeRodar(
        validacao=ResultadoValidacao(False, "A página não respondeu.", "erro_navegador"))
    _executar_com_credencial_ilegivel(db, eid, monkeypatch, conector)
    assert [a.tipo for a in _alertas(db, eid) if not a.resolvido] == ["credencial_ilegivel"]

    r = cliente.put(f"/api/v1/escolas/{eid}/sync/credenciais/elefante",
                    json={"usuario": "robo@escola.invalid", "senha": "outra-ficticia"})
    assert r.status_code == 200 and r.json()["ok"] is False, r.text
    abertos = [a.tipo for a in _alertas(db, eid) if not a.resolvido]
    assert abertos == ["erro_navegador"]
    assert _status(cliente, eid)[0]["credencial_status"] == "nao_validada"


def test_login_que_funciona_fecha_o_alerta_de_credencial_ilegivel(db, escola_completa):
    eid = escola_completa["escola"].id
    service.abrir_alerta(db, eid, "elefante", "credencial_ilegivel", "senha salva ilegível",
                         severidade="critico")
    db.commit()
    assert "credencial_ilegivel" in service.TIPOS_ACESSO
    service.resolver_alertas(db, eid, "elefante", service.TIPOS_ACESSO)
    db.commit()
    assert [a for a in _alertas(db, eid) if not a.resolvido] == []
