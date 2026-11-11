"""Assistente depois da troca da DATA_ENCRYPTION_KEY sem recadastro (G_ROTACAO-3).

A chave de API salva pela tela continua gravada, mas nenhuma chave do anel a
abre: o assistente responde no modo local. O selo da tela do Assistente (que lê
``/assistente/status``) dizia "Claude (Anthropic)" e o "Testar" culpava a
variável de ambiente AI_API_KEY, quando o certo é informar a chave de novo.
Chaves 100% fictícias; nenhuma rede externa.
"""
import secrets

from app.core.config import settings
from app.services import assistente

API = "/api/v1"


def _trocar_dek_depois_de_salvar(cliente_global, escola_id, monkeypatch) -> None:
    dek0 = f"dek0-{secrets.token_urlsafe(40)}"
    dek1 = f"dek1-{secrets.token_urlsafe(40)}"
    monkeypatch.setattr(settings, "AI_API_KEY", "")
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", dek0)
    r = cliente_global.put(f"{API}/escolas/{escola_id}/assistente/config",
                           json={"provedor": "anthropic",
                                 "api_key": "sk-ant-ficticia-" + secrets.token_hex(4)})
    assert r.status_code == 200 and r.json()["chave_definida"] is True
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", dek1)       # DEK trocada


def test_status_mostra_o_modo_local_quando_a_chave_salva_nao_abre(
        cliente, cliente_global, db, escola_completa, monkeypatch):
    escola_id = escola_completa["escola"].id
    _trocar_dek_depois_de_salvar(cliente_global, escola_id, monkeypatch)

    status = cliente.get(f"{API}/escolas/{escola_id}/assistente/status")
    assert status.status_code == 200
    assert status.json()["provedor"] == "local", status.json()
    # E é de fato o modo local que responde.
    r = cliente.post(f"{API}/escolas/{escola_id}/assistente",
                     json={"pergunta": "Qual o panorama da escola?"})
    assert r.status_code == 200 and r.json()["provedor"] == assistente.CONTINGENCIA


def test_testar_diz_para_informar_a_chave_de_novo_e_nao_culpa_a_variavel(
        cliente_global, db, escola_completa, monkeypatch):
    escola_id = escola_completa["escola"].id
    _trocar_dek_depois_de_salvar(cliente_global, escola_id, monkeypatch)

    r = cliente_global.post(f"{API}/escolas/{escola_id}/assistente/config/testar")
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["ok"] is False
    assert "AI_API_KEY" not in corpo["erro"], corpo
    assert "não abre mais" in corpo["erro"] and "de novo" in corpo["erro"], corpo
    assert "sk-ant" not in r.text


def test_status_segue_o_provedor_externo_com_chave_utilizavel(
        cliente, cliente_global, db, escola_completa, monkeypatch):
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", f"dek-{secrets.token_urlsafe(40)}")
    escola_id = escola_completa["escola"].id
    r = cliente_global.put(f"{API}/escolas/{escola_id}/assistente/config",
                           json={"provedor": "anthropic", "api_key": "sk-ant-ficticia-ok",
                                 "modelo": "claude-ficticio"})
    assert r.status_code == 200
    status = cliente.get(f"{API}/escolas/{escola_id}/assistente/status").json()
    assert status == {"provedor": "anthropic", "modelo": "claude-ficticio"}


def test_status_do_ambiente_sem_chave_mostra_o_modo_local(
        cliente, db, escola_completa, monkeypatch):
    """Escola sem configuração própria que herda AI_PROVIDER=anthropic de um
    ambiente sem AI_API_KEY: também responde no modo local."""
    monkeypatch.setattr(settings, "AI_PROVIDER", "anthropic")
    monkeypatch.setattr(settings, "AI_API_KEY", "")
    escola_id = escola_completa["escola"].id
    status = cliente.get(f"{API}/escolas/{escola_id}/assistente/status").json()
    assert status["provedor"] == "local", status
