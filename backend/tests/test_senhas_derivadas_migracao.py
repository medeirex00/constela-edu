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
    REDE SEM ESCOLA Secretaria sem escola_id                     → NUNCA tocada: listada
    SEM ESCOLA      professor sem escola_id                        em "sem escola"
                                                                   (recuperação manual
                                                                   pelo admin global)
    OUTRA ESCOLA    conta da escola B com `--escola` da A        → intacta

E as garantias: nada é apagado, ninguém é bloqueado (status intacto), sessão só
cai de quem foi invalidado, cada invalidação é auditada, nenhuma senha (nem
hash) aparece na saída nem na auditoria, `--aplicar` só grava com o
`--esperado` certo, a gravação é compare-and-set e tudo cabe numa transação.

Os hashes sintéticos usam bcrypt com custo baixo (o verificador lê o custo do
próprio hash): a etapa confere ~10 candidatos por conta e, no custo de
produção, cada execução do teste levaria minutos.
"""
import sys
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core.security import pwd_context, verificar_senha
from app.models import Escola, LogAuditoria, Rede, Usuario

_hash_rapido = pwd_context.handler("bcrypt").using(rounds=4).hash

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
    "orfa": "OrfaSint123",             # @ na caixa original + 123
    "outra": "beatrizoutra123",
    "excluido": "hugoexcluido123",
}

ORIGEM = "scripts/senhas_derivadas"
MSG_SEM_ESCOLA = ("sem escola: recuperação manual pelo admin global "
                  "(scripts/link_redefinicao.py)")


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
                    senha_hash=senha_hash or _hash_rapido(SENHAS[chave]), **kw)
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
        "orfa": conta("orfa", "Orfa Sint", "OrfaSint").id,
    }
    db.add(LogAuditoria(escola_id=esc.id, usuario_id=ids["log"], acao="login"))
    db.get(Usuario, ids["rede_sem"]).escola_id = None     # conta de rede sem escola
    db.get(Usuario, ids["orfa"]).escola_id = None         # professor sem escola
    outra = Escola(nome="ESCOLA_MIGRACAO_OUTRA_SINT", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    o = Usuario(escola_id=outra.id, nome="Beatriz Sint Outra", username="BeatrizOutra",
                email="beatrizoutra@sint.local", cargo="professor",
                senha_hash=_hash_rapido(SENHAS["outra"]))
    db.add(o)
    db.flush()
    ids["outra"], ids["escola_a"], ids["rede_id"] = o.id, esc.id, rede_sint.id
    db.commit()
    db.close()
    return Sessao, ids


# As 9 contas COM escola e senha derivada (as únicas que a etapa pode tocar).
DERIVADAS_COM_ESCOLA = ("nunca", "antiga", "usada", "visto", "log", "coord",
                        "excluido", "rede", "outra")
NUNCA_USADAS = ("nunca", "antiga", "coord", "excluido", "rede", "outra")


def _retrato(Sessao):
    with Sessao() as db:
        return {u.id: (u.senha_hash, u.token_version or 0, u.status)
                for u in db.execute(select(Usuario)).scalars()}


def _invalidacoes(Sessao):
    with Sessao() as db:
        return db.execute(select(LogAuditoria).where(
            LogAuditoria.acao == "usuario.senha_derivada_invalidada")).scalars().all()


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
    assert "derivada do nome: 9 (6 nunca usadas, 1 já usadas, 2 indeterminadas)" in saida
    assert "(EXCLUÍDA)" in saida
    assert f"(REDE {ids['rede_id']}: link só pelo admin global)" in saida
    assert "hash não pôde ser conferido (fora da etapa): 1" in saida
    assert f"usuario_id={ids['hash']}" in saida
    assert "ADMINISTRAÇÃO GLOBAL com senha derivada (troca MANUAL, fora da etapa): 1" in saida
    assert f"usuario_id={ids['global']}" in saida
    assert "coordenador" in saida                     # a promovida entra
    assert f"usuario_id={ids['escolhida']} " not in saida
    # resumo por escola ANTES da lista, com a contagem por uso/cargo/status
    assert saida.index("resumo por escola:") < saida.index("contas:")
    assert (f"escola {ids['escola_a']} (ESCOLA_MIGRACAO_SINT): 8 — uso: indeterminada 2, "
            "nunca_usada 5, usada 1 · cargo: coordenador 2, professor 6 · "
            "status: ativo 7, excluido 1") in saida
    # as SEM escola saem à parte, com o caminho da recuperação manual
    assert f"{MSG_SEM_ESCOLA} — fora da etapa: 2" in saida
    trecho_sem_escola = saida[saida.index(MSG_SEM_ESCOLA):]
    assert f"usuario_id={ids['rede_sem']} " in trecho_sem_escola
    assert f"usuario_id={ids['orfa']} " in trecho_sem_escola
    # o N que o operador passa no --esperado
    assert "alvos: --aplicar → 9; --aplicar --so-nunca-usadas → 6" in saida
    assert "nada foi gravado" in saida
    assert _retrato(Sessao) == antes
    assert _invalidacoes(Sessao) == []
    _sem_segredo_na_saida(saida, antes)


def test_so_nunca_usadas_toca_apenas_quem_nunca_entrou(banco, monkeypatch, capsys):
    Sessao, ids = banco
    antes = _retrato(Sessao)
    codigo, saida = _rodar(monkeypatch, capsys, Sessao, "--aplicar", "--so-nunca-usadas",
                           "--esperado", "6")
    assert codigo == 0
    assert "invalidadas: 6 de 9" in saida
    depois = _retrato(Sessao)

    alvos = {ids[k] for k in NUNCA_USADAS}
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
    logs = _invalidacoes(Sessao)
    assert sorted(l.entidade_id for l in logs) == sorted(alvos)
    assert all(l.detalhes == {"uso": "nunca_usada", "origem": ORIGEM} for l in logs)
    _sem_segredo_na_saida(saida, antes)


def test_aplicar_sem_filtro_tira_todas_as_derivadas_e_poupa_o_resto(banco, monkeypatch,
                                                                     capsys):
    Sessao, ids = banco
    antes = _retrato(Sessao)
    codigo, saida = _rodar(monkeypatch, capsys, Sessao, "--aplicar", "--esperado", "9")
    assert codigo == 0
    assert "invalidadas: 9 de 9" in saida
    depois = _retrato(Sessao)
    derivadas = {ids[k] for k in DERIVADAS_COM_ESCOLA}
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


def test_conta_sem_escola_nunca_e_tocada_e_sai_listada(banco, monkeypatch, capsys):
    """Sem escola, nenhuma tela de escola gera o link de volta: a etapa não as
    invalida (nem a Secretaria sem escola, nem o professor órfão) — lista para a
    recuperação manual pelo admin global."""
    Sessao, ids = banco
    antes = _retrato(Sessao)
    codigo, saida = _rodar(monkeypatch, capsys, Sessao, "--aplicar", "--esperado", "9")
    assert codigo == 0
    depois = _retrato(Sessao)
    for chave in ("rede_sem", "orfa"):
        assert depois[ids[chave]] == antes[ids[chave]], chave
    assert MSG_SEM_ESCOLA in saida
    auditadas = {l.entidade_id for l in _invalidacoes(Sessao)}
    assert ids["rede_sem"] not in auditadas and ids["orfa"] not in auditadas
    with Sessao() as db:
        assert verificar_senha(SENHAS["orfa"], db.get(Usuario, ids["orfa"]).senha_hash)


def test_esperado_divergente_aborta_sem_gravar(banco, monkeypatch, capsys):
    Sessao, _ = banco
    antes = _retrato(Sessao)
    import scripts.senhas_derivadas as etapa
    for args in (("--aplicar", "--esperado", "8"),
                 ("--aplicar", "--so-nunca-usadas", "--esperado", "9")):
        codigo, saida = _rodar(monkeypatch, capsys, Sessao, *args)
        assert codigo == etapa.SAIDA_ESPERADO_DIVERGENTE, args
        assert "ABORTADO" in saida and "Nada foi gravado" in saida
        assert "invalidadas:" not in saida
        assert _retrato(Sessao) == antes
        assert _invalidacoes(Sessao) == []


def test_senha_trocada_entre_classificar_e_gravar_nao_e_sobrescrita(banco, monkeypatch,
                                                                    capsys):
    """Compare-and-set: o professor trocou a senha (pelo link) DEPOIS da leitura
    e ANTES da gravação. A etapa não pode apagar a senha nova dele."""
    Sessao, ids = banco
    from app.services import professores
    original = professores.classificar_senhas_derivadas
    nova = "minha-senha-nova-de-verdade-91"

    def classificar_e_concorrer(db, escola_id=None):
        resultado = original(db, escola_id)
        with Sessao() as outra:          # outra conexão, outra transação
            outra.execute(update(Usuario).where(Usuario.id == ids["nunca"])
                          .values(senha_hash=_hash_rapido(nova)))
            outra.commit()
        return resultado

    monkeypatch.setattr(professores, "classificar_senhas_derivadas", classificar_e_concorrer)
    antes = _retrato(Sessao)
    codigo, saida = _rodar(monkeypatch, capsys, Sessao, "--aplicar", "--esperado", "9")
    assert codigo == 0
    assert "invalidadas: 8 de 9" in saida
    assert "senha trocada durante a execução — não tocada: 1" in saida
    assert f"usuario_id={ids['nunca']} " in saida.split("não tocada: 1")[1]
    with Sessao() as db:
        conta = db.get(Usuario, ids["nunca"])
        assert verificar_senha(nova, conta.senha_hash)          # a senha nova vale
        assert (conta.token_version or 0) == antes[ids["nunca"]][1]  # sessão intacta
        assert not verificar_senha(SENHAS["antiga"], db.get(Usuario, ids["antiga"]).senha_hash)
    assert ids["nunca"] not in {l.entidade_id for l in _invalidacoes(Sessao)}


def test_falha_no_meio_desfaz_tudo(banco, monkeypatch, capsys):
    """Transação única: se a 3ª gravação falhar, as duas primeiras também
    voltam — nenhuma conta fica pela metade."""
    Sessao, _ = banco
    import app.services.audit as audit
    original = audit.registrar
    chamadas = {"n": 0}

    def registrar_que_falha(*a, **kw):
        chamadas["n"] += 1
        if chamadas["n"] == 3:
            raise RuntimeError("falha simulada no meio da etapa")
        return original(*a, **kw)

    monkeypatch.setattr(audit, "registrar", registrar_que_falha)
    antes = _retrato(Sessao)
    with pytest.raises(RuntimeError, match="falha simulada"):
        _rodar(monkeypatch, capsys, Sessao, "--aplicar", "--esperado", "9")
    assert chamadas["n"] == 3
    assert _retrato(Sessao) == antes
    assert _invalidacoes(Sessao) == []


def test_rodar_de_novo_nao_acha_mais_nada(banco, monkeypatch, capsys):
    """Idempotente: depois de aplicada, a etapa não encontra senha derivada."""
    Sessao, _ = banco
    _rodar(monkeypatch, capsys, Sessao, "--aplicar", "--esperado", "9")
    antes = _retrato(Sessao)
    codigo, saida = _rodar(monkeypatch, capsys, Sessao, "--aplicar", "--esperado", "0")
    assert codigo == 0
    assert "senha derivada do nome: 0 " in saida
    assert "invalidadas: 0 de 0" in saida
    assert _retrato(Sessao) == antes
    # a global e as sem escola continuam listadas para a troca manual — e intactas
    assert "ADMINISTRAÇÃO GLOBAL com senha derivada" in saida
    assert MSG_SEM_ESCOLA in saida


def test_escola_isola_a_execucao(banco, monkeypatch, capsys):
    """`--aplicar --escola A` (o rollout controlado que o script recomenda) não
    toca conta de outra escola: hash, sessão e auditoria intactos."""
    Sessao, ids = banco
    antes = _retrato(Sessao)
    codigo, saida = _rodar(monkeypatch, capsys, Sessao, "--aplicar", "--esperado", "7",
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
    auditadas = {l.entidade_id for l in _invalidacoes(Sessao)}
    assert ids["outra"] not in auditadas and ids["nunca"] in auditadas
    assert ids["rede"] not in auditadas
    _sem_segredo_na_saida(saida, antes)


def test_conta_excluida_restaurada_nao_volta_com_a_senha_do_nome(banco, monkeypatch, capsys):
    """A exclusão é lógica: depois da etapa, restaurar a conta não devolve a
    senha calculável — o caminho é o link de redefinição."""
    Sessao, ids = banco
    _rodar(monkeypatch, capsys, Sessao, "--aplicar", "--so-nunca-usadas", "--esperado", "6")
    with Sessao() as db:
        hugo = db.get(Usuario, ids["excluido"])
        hugo.status = "ativo"                  # o que a restauração faz
        db.commit()
        assert not verificar_senha(SENHAS["excluido"], hugo.senha_hash)


@pytest.mark.parametrize("args, trecho", [
    (["--so-nunca-usadas"], "--so-nunca-usadas só vale junto com --aplicar"),
    (["--esperado", "3"], "--esperado só vale junto com --aplicar"),
    (["--aplicar"], "--aplicar exige --esperado N"),
    (["--aplicar", "--so-nunca-usadas"], "--aplicar exige --esperado N"),
    (["--aplicar", "--esperado", "-1"], "--esperado não pode ser negativo"),
])
def test_argparse_recusa_combinacoes_invalidas(args, trecho, capsys, monkeypatch):
    """Recusa ANTES de abrir o banco: nenhuma sessão é criada."""
    import scripts.senhas_derivadas as etapa

    def sem_banco():
        raise AssertionError("não deveria abrir o banco")

    monkeypatch.setattr(etapa, "SessionLocal", sem_banco)
    with pytest.raises(SystemExit) as saida:
        etapa.main(args)
    assert saida.value.code == 2
    assert trecho in capsys.readouterr().err


def test_diagnostico_no_postgres_abre_transacao_somente_leitura():
    """No Postgres, o diagnóstico começa com SET TRANSACTION READ ONLY; nos
    outros dialetos (o SQLite dos testes) a instrução não existe e não é enviada."""
    import scripts.senhas_derivadas as etapa

    class _Dialeto:
        def __init__(self, nome):
            self.name = nome

    class _Bind:
        def __init__(self, nome):
            self.dialect = _Dialeto(nome)

    class _SessaoFalsa:
        def __init__(self, nome):
            self._bind, self.executadas = _Bind(nome), []

        def get_bind(self):
            return self._bind

        def execute(self, instrucao):
            self.executadas.append(str(instrucao))

    pg = _SessaoFalsa("postgresql")
    etapa._abrir_somente_leitura(pg)
    assert pg.executadas == ["SET TRANSACTION READ ONLY"]
    lite = _SessaoFalsa("sqlite")
    etapa._abrir_somente_leitura(lite)
    assert lite.executadas == []


def test_somente_leitura_vem_antes_de_tudo_e_so_no_diagnostico(banco, monkeypatch, capsys):
    """A instrução READ ONLY é a PRIMEIRA da transação do diagnóstico — antes da
    classificação — e não é usada no --aplicar."""
    Sessao, _ = banco
    import scripts.senhas_derivadas as etapa
    ordem = []
    monkeypatch.setattr(etapa, "_abrir_somente_leitura", lambda db: ordem.append("ro"))
    from app.services import professores
    original = professores.classificar_senhas_derivadas

    def classificar(db, escola_id=None):
        ordem.append("classificar")
        return original(db, escola_id)

    monkeypatch.setattr(professores, "classificar_senhas_derivadas", classificar)
    _rodar(monkeypatch, capsys, Sessao)
    assert ordem == ["ro", "classificar"]
    ordem.clear()
    _rodar(monkeypatch, capsys, Sessao, "--aplicar", "--esperado", "9")
    assert ordem == ["classificar"]
