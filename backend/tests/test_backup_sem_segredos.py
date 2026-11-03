"""Backup por escola sem segredos e sem reabrir acesso — lacuna L1 do e97.

Antes: ``GET /admin/backup`` (admin da escola) exportava ``configuracoes`` inteira —
o token do painel público em texto, a chave de IA e a sessão do Matific cifradas —
e restaurar um backup anterior à troca do link REATIVAVA o link antigo do painel
(nomes de crianças num endereço sem senha) e devolvia cifras mortas depois da
rotação da DEK. Agora esses campos não saem no arquivo e a restauração deixa as
configurações de segredo/acesso como estão, inclusive com backups antigos.

Chaves, tokens e nomes aqui são fictícios, gerados em memória e nunca impressos.
"""
import json
import secrets
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.core import security
from app.core.config import settings
from app.models import Configuracao
from app.routers import publico
from app.services import assistente, backup


def _chave(prefixo: str) -> str:
    return f"{prefixo}-{secrets.token_urlsafe(48)}"


DEK0, DEK1 = _chave("dek0"), _chave("dek1")


def _linha(db, escola_id: int, namespace: str) -> Configuracao | None:
    db.expire_all()
    return db.execute(select(Configuracao).where(
        Configuracao.escola_id == escola_id,
        Configuracao.namespace == namespace)).scalar_one_or_none()


def _resolve(db, token: str) -> bool:
    publico._cache_tokens.clear()
    return publico._escola_pelo_token(db, token) is not None


@pytest.fixture()
def escola_com_segredos(db, escola_completa, monkeypatch):
    """Painel público ativo, chave de IA e sessão do Matific — todos com a DEK0."""
    escola = escola_completa["escola"]
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", DEK0)
    token = secrets.token_urlsafe(9)
    db.add(Configuracao(escola_id=escola.id, namespace="painel_publico", chave="valores",
                        valor={"ativo": True, "token": token, "intervalo_s": 20,
                               "anonimizar": True}))
    assistente.salvar_config_assistente(db, escola.id, "anthropic", "chave-ia-ficticia", None)
    db.add(Configuracao(escola_id=escola.id, namespace="matific_sessao", chave="matific",
                        valor={"cifrado": security.cifrar_segredo('{"cookies": []}'),
                               "salvo_em": datetime.now(timezone.utc).isoformat()}))
    db.commit()
    publico._cache_tokens.clear()
    return {"escola": escola, "token": token}


def _backup_antigo(db, escola_id: int, monkeypatch) -> dict:
    """O arquivo como o código ANTERIOR o gerava (configurações inteiras)."""
    with monkeypatch.context() as m:
        m.setattr(backup, "SEGREDOS_DE_CONFIGURACAO", {}, raising=False)
        return json.loads(json.dumps(backup.exportar(db, escola_id)))


# --- Exportação -------------------------------------------------------------------

def test_exportacao_nao_leva_token_cifras_nem_sessao(db, escola_com_segredos):
    escola_id = escola_com_segredos["escola"].id
    arquivo = backup.exportar(db, escola_id)
    texto = json.dumps(arquivo)
    assert escola_com_segredos["token"] not in texto
    assert "api_key_cifrada" not in texto
    cfgs = arquivo["tabelas"]["configuracoes"]
    assert not [c for c in cfgs if c["namespace"] == "matific_sessao"]
    painel = next(c for c in cfgs if c["namespace"] == "painel_publico")
    assert painel["valor"] == {"ativo": True, "intervalo_s": 20, "anonimizar": True}
    ia = next(c for c in cfgs if c["namespace"] == "assistente")
    assert ia["valor"]["provedor"] == "anthropic"
    assert any(c["namespace"] == "pesos.matific" for c in cfgs)   # o resto continua


def test_rota_de_backup_nao_entrega_o_link_do_painel(cliente, escola_com_segredos):
    escola_id = escola_com_segredos["escola"].id
    r = cliente.get(f"/api/v1/escolas/{escola_id}/backup")
    assert r.status_code == 200, r.text
    assert escola_com_segredos["token"] not in r.text
    assert "api_key_cifrada" not in r.text and "matific_sessao" not in r.text


# --- Restauração de backup ANTIGO (com os segredos) -------------------------------

def test_restaurar_backup_antigo_nao_reativa_link_nem_devolve_cifra_morta(
        db, escola_com_segredos, monkeypatch):
    escola_id = escola_com_segredos["escola"].id
    token_antigo = escola_com_segredos["token"]
    arquivo = _backup_antigo(db, escola_id, monkeypatch)
    assert token_antigo in json.dumps(arquivo)                     # é mesmo o formato antigo

    # Rotação: link novo do painel, DEK nova, chave de IA e sessão recadastradas.
    painel = _linha(db, escola_id, "painel_publico")
    token_novo = secrets.token_urlsafe(9)
    painel.valor = {"ativo": True, "token": token_novo, "intervalo_s": 20, "anonimizar": True}
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", DEK1)
    assistente.salvar_config_assistente(db, escola_id, "anthropic", "chave-ia-nova", None)
    sessao = _linha(db, escola_id, "matific_sessao")
    sessao_atual = {"cifrado": security.cifrar_segredo('{"cookies": [1]}'),
                    "salvo_em": datetime.now(timezone.utc).isoformat()}
    sessao.valor = sessao_atual
    db.commit()

    contagem = backup.restaurar(db, escola_id, arquivo)
    db.commit()

    assert not _resolve(db, token_antigo)                  # antes: o link antigo voltava
    assert _resolve(db, token_novo)
    ia = _linha(db, escola_id, "assistente")
    assert security.decifrar_segredo(ia.valor["api_key_cifrada"]) == "chave-ia-nova"
    assert _linha(db, escola_id, "matific_sessao").valor == sessao_atual
    linhas_puladas = sum(1 for c in arquivo["tabelas"]["configuracoes"]
                         if c["namespace"] in backup.SEGREDOS_DE_CONFIGURACAO)
    assert linhas_puladas == 3
    assert contagem["configuracoes"] == len(arquivo["tabelas"]["configuracoes"]) - 3


def test_restaurar_nao_reabre_painel_desativado_depois_do_backup(db, escola_com_segredos,
                                                                monkeypatch):
    """Desativar o painel GUARDA o token: repor o ``ativo`` do arquivo reabriria o
    link antigo — por isso a linha do painel fica inteira como está."""
    escola_id = escola_com_segredos["escola"].id
    token = escola_com_segredos["token"]
    arquivo = _backup_antigo(db, escola_id, monkeypatch)
    painel = _linha(db, escola_id, "painel_publico")
    painel.valor = {**painel.valor, "ativo": False}       # como a rota de configuração faz
    db.commit()
    assert not _resolve(db, token)

    backup.restaurar(db, escola_id, arquivo)
    db.commit()

    assert not _resolve(db, token)
    assert _linha(db, escola_id, "painel_publico").valor["ativo"] is False


def test_restaurar_nao_cria_painel_que_a_escola_nao_tem(db, escola_com_segredos,
                                                       monkeypatch):
    escola_id = escola_com_segredos["escola"].id
    arquivo = backup.exportar(db, escola_id)              # formato novo (sem token)
    db.delete(_linha(db, escola_id, "painel_publico"))
    db.delete(_linha(db, escola_id, "matific_sessao"))
    db.commit()

    backup.restaurar(db, escola_id, arquivo)
    db.commit()

    assert _linha(db, escola_id, "painel_publico") is None
    assert _linha(db, escola_id, "matific_sessao") is None
    assert not _resolve(db, escola_com_segredos["token"])


def test_rota_restaurar_backup_antigo_mantem_o_link_atual(db, cliente_global,
                                                          escola_com_segredos, monkeypatch):
    escola_id = escola_com_segredos["escola"].id
    token_antigo = escola_com_segredos["token"]
    arquivo = _backup_antigo(db, escola_id, monkeypatch)
    painel = _linha(db, escola_id, "painel_publico")
    token_novo = secrets.token_urlsafe(9)
    painel.valor = {**painel.valor, "token": token_novo}
    db.commit()

    r = cliente_global.post(f"/api/v1/escolas/{escola_id}/restaurar",
                            files={"arquivo": ("backup.json", json.dumps(arquivo).encode(),
                                               "application/json")})

    assert r.status_code == 200, r.text
    assert not _resolve(db, token_antigo)
    assert _resolve(db, token_novo)
