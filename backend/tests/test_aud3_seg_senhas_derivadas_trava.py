"""``senhas_derivadas --aplicar`` não calcula bcrypt com as linhas das contas já
processadas travadas (S_G_SCRIPTS-3).

``professores.invalidar_senhas_derivadas`` montava cada UPDATE compare-and-set com
``senha_hash_sem_acesso()`` (bcrypt de custo 12, ~0,18 s) DENTRO do laço, depois de
já ter atualizado as contas anteriores. A trava de linha de cada conta só cai no
commit do script: a 1ª ficava presa por (N-1) x custo do bcrypt (N=60: ~11 s), e o
heartbeat ou o PATCH dessas contas esperava sem prazo, segurando conexão do pool e
thread do worker. Agora todos os hashes novos são gerados ANTES do 1º UPDATE; a
transação única e o compare-and-set continuam iguais.

Banco descartável (SQLite em arquivo temporário), contas sintéticas do teste da
etapa (test_senhas_derivadas_migracao.py).
"""
from sqlalchemy import event

from app.services import professores
from tests.test_senhas_derivadas_migracao import (  # noqa: F401 — fixture
    DERIVADAS_COM_ESCOLA,
    _rodar,
    banco,
)


def _registrar_ordem(monkeypatch, Sessao) -> list[str]:
    """Liga a gravação da ordem: 'hash' a cada bcrypt da senha sem acesso e
    'update' a cada UPDATE da tabela usuarios."""
    ordem: list[str] = []
    original = professores.hash_senha

    def hash_registrado(senha):
        ordem.append("hash")
        return original(senha)

    monkeypatch.setattr(professores, "hash_senha", hash_registrado)
    engine = Sessao.kw["bind"]

    @event.listens_for(engine, "before_cursor_execute")
    def _antes(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("UPDATE USUARIOS"):
            ordem.append("update")

    return ordem


def test_nenhum_bcrypt_depois_do_primeiro_update(banco, monkeypatch, capsys):
    Sessao, _ = banco
    ordem = _registrar_ordem(monkeypatch, Sessao)
    codigo, saida = _rodar(monkeypatch, capsys, Sessao, "--aplicar", "--esperado", "9")
    assert codigo == 0
    assert "invalidadas: 9 de 9" in saida
    assert ordem.count("update") == len(DERIVADAS_COM_ESCOLA)
    assert ordem.count("hash") == len(DERIVADAS_COM_ESCOLA)
    primeiro_update = ordem.index("update")
    assert "hash" not in ordem[primeiro_update:], (
        f"bcrypt calculado com contas já atualizadas (linhas travadas): {ordem}")


def test_so_nunca_usadas_tambem_gera_os_hashes_antes(banco, monkeypatch, capsys):
    Sessao, _ = banco
    ordem = _registrar_ordem(monkeypatch, Sessao)
    codigo, _ = _rodar(monkeypatch, capsys, Sessao, "--aplicar", "--so-nunca-usadas",
                       "--esperado", "6")
    assert codigo == 0
    assert ordem.count("update") == 6
    assert "hash" not in ordem[ordem.index("update"):], ordem


def test_cada_conta_recebe_um_hash_diferente(banco, monkeypatch, capsys):
    """Gerar antes não reaproveita: cada conta tem a própria senha aleatória."""
    from sqlalchemy import select

    from app.models import Usuario
    Sessao, ids = banco
    codigo, _ = _rodar(monkeypatch, capsys, Sessao, "--aplicar", "--esperado", "9")
    assert codigo == 0
    with Sessao() as db:
        hashes = [db.execute(select(Usuario.senha_hash).where(Usuario.id == ids[k]))
                  .scalar_one() for k in DERIVADAS_COM_ESCOLA]
    assert len(set(hashes)) == len(hashes)


def test_diagnostico_nao_gera_hash_nenhum(banco, monkeypatch, capsys):
    """Sem --aplicar, nenhum bcrypt de senha nova (só o diagnóstico)."""
    Sessao, _ = banco
    ordem = _registrar_ordem(monkeypatch, Sessao)
    codigo, _ = _rodar(monkeypatch, capsys, Sessao)
    assert codigo == 0
    assert ordem == []
