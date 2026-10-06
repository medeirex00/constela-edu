"""Etapa de deploy `scripts/senhas_derivadas.py` rodada de verdade num BANCO
DESCARTÁVEL — um SQLite em arquivo temporário criado só para o teste (nunca o
banco de desenvolvimento, nunca produção).

Contas sintéticas em todas as situações que a etapa precisa distinguir:

    NUNCA USADA     senha derivada, nenhum sinal de login        → invalidada sempre
    USADA           senha derivada, tem `ultimo_acesso`          → só sem --so-nunca-usadas
    INDETERMINADA   senha derivada, presença ou auditoria de login
                    sem `ultimo_acesso` (dados divergentes)      → só sem --so-nunca-usadas
    PROMOVIDA       nasceu professor, hoje coordenadora, senha derivada → tratada igual
    ESCOLHIDA       senha que o professor escolheu               → nunca
    NÃO VERIFICÁVEL hash em formato desconhecido                 → nunca (listada à parte)
    GLOBAL          admin global com senha derivada              → listada à parte, NUNCA tocada
    EXCLUÍDA        professor excluído (pode ser restaurado)     → tratada igual
    DE REDE         Secretaria (rede_id) hospedada na escola A, como
                    `PUT /redes/{id}/usuarios` a deixa           → tratada igual na
                    execução completa; FORA do `--escola A`
    REDE SEM ESCOLA Secretaria sem escola_id                     → tratada igual (sem quebrar)
    OUTRA ESCOLA    conta da escola B com `--escola` da A        → intacta

E as garantias: nada é apagado, ninguém é bloqueado (status intacto), sessão só
cai de quem foi invalidado, cada invalidação é auditada e nenhuma senha (nem
hash) aparece na saída nem na auditoria.
"""
import sys
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core.security import hash_senha, verificar_senha
from app.models import Escola, LogAuditoria, Rede, Usuario

SENHAS = {
    "nunca": "ananunca123",            # @ em minúsculas + 123
    "antiga": "Gil123",                # convenção mais antiga: primeiro nome + 123
    "usada": "biausada123",
    "visto": "caiovisto123",
    "log": "doralog123",
    "escolhida": "uma-senha-escolhida-77",
    "coord": "coordsint123",
    "global": "gabiglobal123",
    "rede": "secsint123",
    "rede_sem": "rosasemescola123",
    "outra": "beatrizoutra123",
    "excluido": "hugoexcluido123",
}


@pytest.fixture()
def banco(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'descartavel.db'}")
    Base.metadata.create_all(engine)
    Sessao = sessionmaker(bind=engine)
    db = Sessao()
    rede_sint = Rede(nome="REDE_MIGRACAO_SINT")
    db.add(rede_sint)
    db.flush()
    esc = Escola(nome="ESCOLA_MIGRACAO_SINT", ano_letivo_ativo=2026, rede_id=rede_sint.id)
    db.add(esc)
    db.flush()
    agora = datetime.now(timezone.utc)

    def conta(chave, nome, username, *, senha_hash=None, cargo="professor", **kw):
        u = Usuario(escola_id=esc.id, nome=nome, username=username,
                    email=f"{username.lower()}@sint.local", cargo=cargo,
                    senha_hash=senha_hash or hash_senha(SENHAS[chave]), **kw)
        db.add(u)
        db.flush()
        return u

    ids = {
        "nunca": conta("nunca", "Ana Sint Nunca", "AnaNunca").id,
        "antiga": conta("antiga", "Gil Sint Antigo", "GilAntigo").id,
        "usada": conta("usada", "Bia Sint Usada", "BiaUsada", ultimo_acesso=agora,
                       token_version=3).id,
        "visto": conta("visto", "Caio Sint Visto", "CaioVisto", visto_em=agora).id,
        "log": conta("log", "Dora Sint Log", "DoraLog").id,
        "escolhida": conta("escolhida", "Eva Sint Propria", "EvaPropria").id,
        "hash": conta(None, "Fabio Sint Hash", "FabioHash",
                      senha_hash="hash-em-formato-desconhecido").id,
        "coord": conta("coord", "Coord Sint", "CoordSint", cargo="coordenador").id,
        "global": conta("global", "Gabi Sint Global", "GabiGlobal", cargo="admin",
                        is_global=True).id,
        "excluido": conta("excluido", "Hugo Sint Excluido", "HugoExcluido",
                          status="excluido").id,
        # a forma REAL da Secretaria: rede_id + o escola_id de onde foi promovida
        "rede": conta("rede", "Sec Sint", "SecSint", cargo="coordenador",
                      rede_id=rede_sint.id).id,
        "rede_sem": conta("rede_sem", "Rosa Sint", "RosaSemEscola", cargo="coordenador",
                          rede_id=rede_sint.id).id,
    }
    db.add(LogAuditoria(escola_id=esc.id, usuario_id=ids["log"], acao="login"))
    db.get(Usuario, ids["rede_sem"]).escola_id = None     # conta de rede sem escola
    outra = Escola(nome="ESCOLA_MIGRACAO_OUTRA_SINT", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    o = Usuario(escola_id=outra.id, nome="Beatriz Sint Outra", username="BeatrizOutra",
                email="beatrizoutra@sint.local", cargo="professor",
                senha_hash=hash_senha(SENHAS["outra"]))
    db.add(o)
    db.flush()
    ids["outra"], ids["escola_a"], ids["rede_id"] = o.id, esc.id, rede_sint.id
    db.commit()
    db.close()
    return Sessao, ids


def _retrato(Sessao):
    with Sessao() as db:
        return {u.id: (u.senha_hash, u.token_version or 0, u.status)
                for u in db.execute(select(Usuario)).scalars()}


def _rodar(monkeypatch, capsys, Sessao, *args):
    import scripts.senhas_derivadas as etapa
    monkeypatch.setattr(etapa, "SessionLocal", Sessao)
    monkeypatch.setattr(sys, "argv", ["senhas_derivadas", *args])
    codigo = etapa.main()
    return codigo, capsys.readouterr().out


def _sem_segredo_na_saida(saida, retrato):
    for senha in SENHAS.values():
        assert senha not in saida
    for senha_hash, _, _ in retrato.values():
        assert senha_hash not in saida


def test_diagnostico_classifica_e_nao_grava_nada(banco, monkeypatch, capsys):
    Sessao, ids = banco
    antes = _retrato(Sessao)
    codigo, saida = _rodar(monkeypatch, capsys, Sessao)
    assert codigo == 0
    assert "10 (7 nunca usadas, 1 já usadas, 2 indeterminadas)" in saida
    assert "(EXCLUÍDA)" in saida and "escola=-" in saida
    assert f"(REDE {ids['rede_id']}: link só pelo admin global)" in saida
    assert "hash não pôde ser conferido (fora da etapa): 1" in saida
    assert f"usuario_id={ids['hash']}" in saida
    assert "ADMINISTRAÇÃO GLOBAL com senha derivada (troca MANUAL, fora da etapa): 1" in saida
    assert f"usuario_id={ids['global']}" in saida
    assert "coordenador" in saida                     # a promovida entra
    assert f"usuario_id={ids['escolhida']} " not in saida
    assert "nada foi gravado" in saida
    assert _retrato(Sessao) == antes
    _sem_segredo_na_saida(saida, antes)


def test_so_nunca_usadas_toca_apenas_quem_nunca_entrou(banco, monkeypatch, capsys):
    Sessao, ids = banco
    antes = _retrato(Sessao)
    codigo, saida = _rodar(monkeypatch, capsys, Sessao, "--aplicar", "--so-nunca-usadas")
    assert codigo == 0
    assert "invalidadas: 7 de 10" in saida
    depois = _retrato(Sessao)

    alvos = {ids[k] for k in ("nunca", "antiga", "coord", "excluido", "rede", "rede_sem",
                              "outra")}
    for uid, (h, versao, estado) in depois.items():
        h0, versao0, estado0 = antes[uid]
        assert estado == estado0                      # ninguém bloqueado
        if uid in alvos:
            assert h != h0 and versao == versao0 + 1  # senha nova + sessões caem
        else:
            assert (h, versao) == (h0, versao0)       # intacto
    assert len(depois) == len(antes)                  # nada apagado
    with Sessao() as db:
        assert not verificar_senha(SENHAS["nunca"], db.get(Usuario, ids["nunca"]).senha_hash)
        assert not verificar_senha(SENHAS["antiga"], db.get(Usuario, ids["antiga"]).senha_hash)
        assert verificar_senha(SENHAS["usada"], db.get(Usuario, ids["usada"]).senha_hash)
        logs = db.execute(select(LogAuditoria).where(
            LogAuditoria.acao == "usuario.senha_derivada_invalidada")).scalars().all()
        assert sorted(l.entidade_id for l in logs) == sorted(alvos)
        assert all(l.detalhes == {"uso": "nunca_usada"} for l in logs)
    _sem_segredo_na_saida(saida, antes)


def test_aplicar_sem_filtro_tira_todas_as_derivadas_e_poupa_o_resto(banco, monkeypatch,
                                                                     capsys):
    Sessao, ids = banco
    antes = _retrato(Sessao)
    codigo, saida = _rodar(monkeypatch, capsys, Sessao, "--aplicar")
    assert codigo == 0
    assert "invalidadas: 10 de 10" in saida
    depois = _retrato(Sessao)
    derivadas = {ids[k] for k in ("nunca", "antiga", "usada", "visto", "log", "coord",
                                  "excluido", "rede", "rede_sem", "outra")}
    for uid in antes:
        mudou = depois[uid][0] != antes[uid][0]
        assert mudou == (uid in derivadas), uid
        assert depois[uid][2] == antes[uid][2]
    with Sessao() as db:
        assert db.execute(select(func.count(Usuario.id))).scalar() == len(antes)
        detalhes = [l.detalhes for l in db.execute(select(LogAuditoria)).scalars()]
    for senha in SENHAS.values():
        assert all(senha not in str(d) for d in detalhes)
    _sem_segredo_na_saida(saida, antes)


def test_rodar_de_novo_nao_acha_mais_nada(banco, monkeypatch, capsys):
    """Idempotente: depois de aplicada, a etapa não encontra senha derivada."""
    Sessao, _ = banco
    _rodar(monkeypatch, capsys, Sessao, "--aplicar")
    codigo, saida = _rodar(monkeypatch, capsys, Sessao, "--aplicar")
    assert codigo == 0
    assert "senha derivada do nome: 0 " in saida
    # a global continua listada para a troca manual — e intacta
    assert "ADMINISTRAÇÃO GLOBAL com senha derivada" in saida



def test_escola_isola_a_execucao(banco, monkeypatch, capsys):
    """`--aplicar --escola A` (o rollout controlado que o script recomenda) não
    toca conta de outra escola: hash, sessão e auditoria intactos."""
    Sessao, ids = banco
    antes = _retrato(Sessao)
    codigo, saida = _rodar(monkeypatch, capsys, Sessao, "--aplicar",
                           "--escola", str(ids["escola_a"]))
    assert codigo == 0
    depois = _retrato(Sessao)
    assert depois[ids["outra"]] == antes[ids["outra"]]
    # A Secretaria HOSPEDADA na escola A (escola_id = A, rede_id): fora do
    # rollout da escola — só o admin global devolveria o acesso dela.
    assert depois[ids["rede"]] == antes[ids["rede"]]
    assert depois[ids["rede_sem"]] == antes[ids["rede_sem"]]
    assert depois[ids["nunca"]] != antes[ids["nunca"]]
    assert f"usuario_id={ids['rede']} " not in saida
    with Sessao() as db:
        auditadas = {l.entidade_id for l in db.execute(select(LogAuditoria).where(
            LogAuditoria.acao == "usuario.senha_derivada_invalidada")).scalars()}
    assert ids["outra"] not in auditadas and ids["nunca"] in auditadas
    assert ids["rede"] not in auditadas
    _sem_segredo_na_saida(saida, antes)


def test_conta_excluida_restaurada_nao_volta_com_a_senha_do_nome(banco, monkeypatch, capsys):
    """A exclusão é lógica: depois da etapa, restaurar a conta não devolve a
    senha calculável — o caminho é o link de redefinição."""
    Sessao, ids = banco
    _rodar(monkeypatch, capsys, Sessao, "--aplicar", "--so-nunca-usadas")
    with Sessao() as db:
        hugo = db.get(Usuario, ids["excluido"])
        hugo.status = "ativo"                  # o que a restauração faz
        db.commit()
        assert not verificar_senha(SENHAS["excluido"], hugo.senha_hash)
