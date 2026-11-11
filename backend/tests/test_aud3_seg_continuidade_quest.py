"""O inventário do cofre (docs/CONTINUIDADE.md §2) diz o que acontece de verdade com
os códigos do Quest quando a DATA_ENCRYPTION_KEY se perde (S_G_ROTACAO-2).

A linha da DEK dizia que, perdida a chave, "os códigos do Quest gravados com ela
deixam de conferir". Isso descreve o estado FUTURO, depois da remoção das colunas em
texto (``codigo_login``/``qr_token``). Hoje ``_FALLBACK_TEXTO_CLARO`` está ligado: o
login não acha pelo hash, confere pelo texto e regrava o hash com a chave nova. Quem
lesse o inventário planejaria reimprimir os cartões de todas as turmas sem precisar —
e acharia que a DEK protege os cartões, quando um dump do banco já dá acesso.

Dados fictícios; chaves geradas na hora.
"""
import secrets

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import BASE_DIR, settings
from app.main import app
from app.quest.models import QuestCredencialAluno
from app.quest.services import credenciais

API = "/api/v1"
PROJECT_ROOT = BASE_DIR.parent


def _linha_da_dek() -> str:
    texto = (PROJECT_ROOT / "docs" / "CONTINUIDADE.md").read_text(encoding="utf-8")
    inventario = texto.split("## 2.", 1)[1].split("## 3.", 1)[0]
    linhas = [linha for linha in inventario.splitlines()
              if linha.startswith("|") and "DATA_ENCRYPTION_KEY" in linha.split("|")[2]]
    assert len(linhas) == 1, linhas
    return linhas[0]


def _chave(rotulo: str) -> str:
    return f"teste-{rotulo}-" + secrets.token_urlsafe(32)


def _usar_chaves(monkeypatch, sk: str, dek: str) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", sk)
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", dek)
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEYS_ANTERIORES", "")
    monkeypatch.setattr(settings, "CHAVE_CIFRA_LEGADA_ANTERIOR", "")


def test_linha_da_dek_diz_o_que_acontece_com_os_codigos_hoje():
    dek = _linha_da_dek()
    if credenciais._FALLBACK_TEXTO_CLARO:
        assert "deixam de conferir" not in dek, (
            "com o texto claro ainda conferido, o código do Quest NÃO deixa de entrar "
            "quando a DEK se perde")
        assert "continua entrando" in dek
        # E a DEK não protege os cartões enquanto as colunas em texto existirem.
        assert "dump" in dek and "RETENCAO-TECNICA.md" in dek and "§2.4" in dek
    else:  # depois da remoção das colunas em texto: aí sim deixa de conferir
        assert "deixa de conferir" in dek
    # Os termos que o inventário do cofre já exigia continuam (test_config_producao).
    for termo in ("Cofre", "obrigatória", "ilegíveis", "DATA_ENCRYPTION_KEYS_ANTERIORES",
                  "python -m scripts.recifrar_segredos --executar"):
        assert termo in dek, termo


def test_codigo_do_quest_entra_com_a_dek_perdida_enquanto_ha_texto_claro(
        db, escola_completa, monkeypatch):
    """O comportamento que a linha descreve: cartões gerados com uma DEK, a DEK
    perdida (nenhuma anterior no anel) — o código continua entrando e o hash é
    regravado com a chave nova."""
    _usar_chaves(monkeypatch, _chave("sk0"), _chave("dek0"))
    cliente = TestClient(app)
    r = cliente.post(f"{API}/auth/login",
                     data={"username": "admin@teste.local", "password": "s3nh4"})
    assert r.status_code == 200, r.text
    cliente.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    eid, tid = escola_completa["escola"].id, escola_completa["turma"].id
    r = cliente.post(f"{API}/escolas/{eid}/quest/turmas/{tid}/cartoes")
    assert r.status_code == 200, r.text
    db.expire_all()
    cred = db.execute(select(QuestCredencialAluno).where(
        QuestCredencialAluno.aluno_id == escola_completa["alunos"][0].id)).scalar_one()
    codigo, hash_antigo = cred.codigo_login, cred.codigo_login_hash

    _usar_chaves(monkeypatch, _chave("sk0b"), _chave("dek1"))     # DEK perdida
    r = TestClient(app).post(f"{API}/quest/auth/entrar", json={"codigo": codigo})
    db.expire_all()
    novo = db.execute(select(QuestCredencialAluno.codigo_login_hash).where(
        QuestCredencialAluno.id == cred.id)).scalar_one()
    if credenciais._FALLBACK_TEXTO_CLARO:
        assert r.status_code == 200, r.text
        assert novo != hash_antigo
    else:
        assert r.status_code == 401, r.text
