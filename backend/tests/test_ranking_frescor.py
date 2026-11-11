"""DADO VELHO NÃO PODE PARECER ATUAL — o frescor que acompanha os rankings.

O motor ranqueia pelo retrato MAIS RECENTE de cada aluno sem olhar a idade dele
(``scoring._carregar_contexto``). Uma coleta parada há três semanas produzia um
ranking com a mesma cara de um ranking de ontem. ``services.frescor_ranking``
declara a idade do dado — sem mudar nenhum número — e as respostas de ranking a
carregam:

* ``GET /escolas/{id}/ranking/frescor`` (as listas ``/ranking``,
  ``/ranking/leitura`` e ``/ranking/matematica`` não podem ganhar envelope sem
  quebrar web, app e telão);
* ``frescor`` embutido em ``/premiacoes`` e ``/ranking/turmas`` (objetos);
* ``snapshot_em`` por aluno em ``/ranking?dimensao=`` (já existia) e em
  ``/ranking/matematica``;
* ``GET /redes/{id}/ranking/frescor`` — por escola, para o ranking da rede.

O limite (7 dias) é uma constante nomeada e viaja na resposta (``limite_dias``).
"""
from datetime import datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.core.tempo import hoje_br
from app.main import app
from app.models import (
    Aluno,
    Escola,
    Importacao,
    Matricula,
    ModuloRede,
    Professor,
    Rede,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
    Usuario,
)
from app.models.sincronizacao import SincronizacaoExecucao
from app.services import frescor_ranking, scoring
from tests._ano_letivo import ANO, escola_no_ano_de_hoje  # noqa: F401 — fixture

API = "/api/v1"


@pytest.fixture(autouse=True)
def _relogio(relogio_no_ano_letivo):
    """Os retratos daqui são de "N dias atrás" (até 20) contados de ``hoje_br`` e o Matific
    é contador DO ANO: nas primeiras semanas de janeiro o retrato de N dias atrás seria do
    ano passado, e o selo diria, com razão, "sem dados" (PERIODOS-9). O relógio fica no
    ano letivo da escola com folga para trás — e, autouse, antes de qualquer login."""
    return relogio_no_ano_letivo


def _dia(dias_atras: int) -> datetime:
    """Meio da manhã de N dias atrás (dia de Brasília, igual ao `hoje_br`)."""
    return datetime.combine(hoje_br() - timedelta(days=dias_atras), time(10, 0))


def _imp(db, escola_id):
    imp = Importacao(escola_id=escola_id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    return imp


def _snap_e(db, escola_id, imp, aluno_id, dias_atras, livros=3):
    db.add(SnapshotElefante(escola_id=escola_id, aluno_id=aluno_id, importacao_id=imp.id,
                            data_referencia=_dia(dias_atras), livros_unicos=livros,
                            tempo_leitura_min=10 * livros, livros_por_nivel={"D": livros}))


def _snap_m(db, escola_id, imp, aluno_id, quando, estrelas=20):
    db.add(SnapshotMatific(escola_id=escola_id, aluno_id=aluno_id, importacao_id=imp.id,
                           data_referencia=quando, atividades=10, estrelas=estrelas,
                           pontuacao_media=2.0))


def _sync(db, escola_id, plataforma, dias_atras, status="concluida"):
    db.add(SincronizacaoExecucao(escola_id=escola_id, plataforma=plataforma,
                                 origem="manual", status=status,
                                 finalizada_em=_dia(dias_atras)))


def _frescor(cliente, escola_id):
    r = cliente.get(f"{API}/escolas/{escola_id}/ranking/frescor")
    assert r.status_code == 200, r.text
    return r.json()


def test_limite_e_constante_nomeada_e_volta_na_resposta(cliente, escola_completa):
    assert frescor_ranking.LIMITE_DIAS_DADO_ATUAL == 7
    corpo = _frescor(cliente, escola_completa["escola"].id)
    assert corpo["limite_dias"] == frescor_ranking.LIMITE_DIAS_DADO_ATUAL
    assert corpo["hoje"] == hoje_br().isoformat()


def test_sem_dado_e_sem_dados_nunca_zero(cliente, escola_completa):
    corpo = _frescor(cliente, escola_completa["escola"].id)
    assert corpo["estado"] == "sem_dados"
    for dimensao in ("leitura", "matematica"):
        bloco = corpo["dimensoes"][dimensao]
        assert bloco["contratada"] is True
        assert bloco["estado"] == "sem_dados"
        assert bloco["dado_mais_recente_em"] is None
        assert bloco["dias_desde_dado"] is None
        assert bloco["alunos_com_dado"] == 0


def test_retrato_antigo_e_desatualizado_mesmo_com_sincronizacao_ok_hoje(
        cliente, db, escola_completa):
    """O caso do achado: todos os retratos têm 20 dias. Uma sincronização
    "concluída" hoje que não trouxe retrato novo NÃO torna o dado atual — o
    estado é decidido pela data do dado, e a sincronização vem ao lado."""
    escola = escola_completa["escola"]
    imp = _imp(db, escola.id)
    for aluno in escola_completa["alunos"]:
        _snap_e(db, escola.id, imp, aluno.id, dias_atras=20)
        _snap_m(db, escola.id, imp, aluno.id, _dia(20))
    _sync(db, escola.id, "elefante", dias_atras=0)
    _sync(db, escola.id, "matific", dias_atras=1, status="erro")   # falha não conta
    db.commit()
    scoring.recalcular_escola(db, escola.id)

    corpo = _frescor(cliente, escola.id)
    assert corpo["estado"] == "desatualizado"
    leitura, matematica = corpo["dimensoes"]["leitura"], corpo["dimensoes"]["matematica"]
    assert leitura["estado"] == matematica["estado"] == "desatualizado"
    assert leitura["dado_mais_recente_em"] == _dia(20).date().isoformat()
    assert leitura["dias_desde_dado"] == 20
    assert leitura["alunos_com_dado"] == 3 and leitura["alunos_com_dado_antigo"] == 3
    assert leitura["ultima_sincronizacao_ok_em"].startswith(_dia(0).date().isoformat())
    assert leitura["dias_desde_sincronizacao_ok"] == 0
    assert matematica["ultima_sincronizacao_ok_em"] is None   # só houve erro

    # O ranking por dimensão continua devolvendo os mesmos números (nada muda no
    # cálculo) e a data do retrato de cada aluno viaja na linha.
    itens = cliente.get(f"{API}/escolas/{escola.id}/ranking",
                        params={"dimensao": "leitura"}).json()
    assert len(itens) == 3
    assert {i["snapshot_em"] for i in itens} == {_dia(20).date().isoformat()}


def test_limite_exato_ainda_esta_em_dia(cliente, db, escola_completa):
    """"Mais de 7 dias" é desatualizado; exatamente 7 ainda não."""
    escola = escola_completa["escola"]
    imp = _imp(db, escola.id)
    for aluno in escola_completa["alunos"]:
        _snap_e(db, escola.id, imp, aluno.id, dias_atras=7)
    db.commit()
    leitura = _frescor(cliente, escola.id)["dimensoes"]["leitura"]
    assert leitura["estado"] == "em_dia"
    assert leitura["dias_desde_dado"] == 7 and leitura["alunos_com_dado_antigo"] == 0


def test_coleta_parcial_aparece_como_parcial(cliente, db, escola_completa):
    """A última coleta trouxe dois alunos; o terceiro ficou com o retrato de 15
    dias atrás — a nota dele é antiga, e o selo precisa dizer."""
    escola = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    imp = _imp(db, escola.id)
    _snap_e(db, escola.id, imp, ana.id, dias_atras=15)
    _snap_e(db, escola.id, imp, ana.id, dias_atras=1, livros=5)     # o atual é este
    _snap_e(db, escola.id, imp, joao.id, dias_atras=1)
    _snap_e(db, escola.id, imp, sofia.id, dias_atras=15)
    db.commit()
    leitura = _frescor(cliente, escola.id)["dimensoes"]["leitura"]
    assert leitura["estado"] == "parcial"
    assert leitura["dado_mais_recente_em"] == _dia(1).date().isoformat()
    assert leitura["dado_mais_antigo_em"] == _dia(15).date().isoformat()
    assert leitura["alunos_com_dado"] == 3
    assert leitura["alunos_com_dado_antigo"] == 1      # só a Sofia: a Ana tem o novo


def test_quem_nao_concorre_nao_deixa_a_escola_em_dia(cliente, db, escola_completa):
    """A população é a do ranking: o retrato recente de uma criança da Fase, de
    um aluno transferido ou de outra escola não pode fazer o dado parecer atual."""
    escola = escola_completa["escola"]
    imp = _imp(db, escola.id)
    for aluno in escola_completa["alunos"]:
        _snap_e(db, escola.id, imp, aluno.id, dias_atras=30)
    fase = Turma(escola_id=escola.id, nome="1ª Fase Z", ano_escolar="1ª Fase",
                 ano_letivo=escola.ano_letivo_ativo)
    db.add(fase)
    db.flush()
    crianca = Aluno(escola_id=escola.id, nome="Crianca Fase Z", status="ativo")
    saiu = Aluno(escola_id=escola.id, nome="Aluno Transferido Z", status="transferido")
    db.add_all([crianca, saiu])
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=crianca.id, turma_id=fase.id,
                     ano_letivo=escola.ano_letivo_ativo))
    db.add(Matricula(escola_id=escola.id, aluno_id=saiu.id,
                     turma_id=escola_completa["turma"].id,
                     ano_letivo=escola.ano_letivo_ativo))
    _snap_e(db, escola.id, imp, crianca.id, dias_atras=0)
    _snap_e(db, escola.id, imp, saiu.id, dias_atras=0)
    db.commit()

    leitura = _frescor(cliente, escola.id)["dimensoes"]["leitura"]
    assert leitura["estado"] == "desatualizado"
    assert leitura["dias_desde_dado"] == 30
    assert leitura["alunos_com_dado"] == 3


def test_matific_de_outro_ano_letivo_e_sem_dados(cliente, db, escola_completa):
    """Contador do ANO: um retrato de dezembro do ano anterior não diz nada sobre o ano
    letivo (a mesma definição de aferido do motor) — sem dados no ano, nunca
    "desatualizado do ano passado" nem zero."""
    escola = escola_completa["escola"]
    imp = _imp(db, escola.id)
    for aluno in escola_completa["alunos"]:
        _snap_m(db, escola.id, imp, aluno.id,
                datetime(escola.ano_letivo_ativo - 1, 12, 10, 10, 0))
    db.commit()
    assert _frescor(cliente, escola.id)["dimensoes"]["matematica"]["estado"] == "sem_dados"


def test_modulo_nao_contratado_nao_existe_no_frescor(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    rede = Rede(nome="Rede So Leitura", status="ativa")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    db.add(ModuloRede(rede_id=rede.id, modulo="matematica", ativo=False))
    imp = _imp(db, escola.id)
    for aluno in escola_completa["alunos"]:
        _snap_e(db, escola.id, imp, aluno.id, dias_atras=1)
    db.commit()
    corpo = _frescor(cliente, escola.id)
    assert corpo["dimensoes"]["matematica"]["contratada"] is False
    assert corpo["dimensoes"]["matematica"]["estado"] is None
    # O estado geral só olha o que foi contratado: Leitura em dia = escola em dia.
    assert corpo["estado"] == "em_dia"


def test_premiacoes_e_ranking_de_turmas_trazem_o_frescor(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    imp = _imp(db, escola.id)
    for aluno in escola_completa["alunos"]:
        _snap_e(db, escola.id, imp, aluno.id, dias_atras=12)
        _snap_m(db, escola.id, imp, aluno.id, _dia(12))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    esperado = _frescor(cliente, escola.id)

    premios = cliente.get(f"{API}/escolas/{escola.id}/premiacoes",
                          params={"periodo": "ano_letivo"}).json()
    assert premios["frescor"] == esperado
    turmas = cliente.get(f"{API}/escolas/{escola.id}/ranking/turmas",
                         params={"dimensao": "leitura"}).json()
    assert turmas["frescor"] == esperado
    assert turmas["frescor"]["dimensoes"]["leitura"]["estado"] == "desatualizado"


def test_ranking_de_matematica_por_periodo_traz_a_data_do_retrato(cliente, db,
                                                                   escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    imp = _imp(db, escola.id)
    _snap_m(db, escola.id, imp, ana.id, _dia(9), estrelas=30)
    db.commit()
    itens = cliente.get(f"{API}/escolas/{escola.id}/ranking/matematica").json()
    assert [(i["aluno_id"], i["snapshot_em"]) for i in itens] == [
        (ana.id, _dia(9).date().isoformat())]


def test_professor_ve_o_frescor_das_turmas_dele(db, escola_completa):
    escola = escola_completa["escola"]
    imp = _imp(db, escola.id)
    for aluno in escola_completa["alunos"]:
        _snap_e(db, escola.id, imp, aluno.id, dias_atras=25)
    outra = Turma(escola_id=escola.id, nome="5º Ano Z", ano_escolar="5º Ano",
                  ano_letivo=escola.ano_letivo_ativo)
    db.add(outra)
    db.flush()
    vizinho = Aluno(escola_id=escola.id, nome="Aluno Vizinho Z", status="ativo")
    db.add(vizinho)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=vizinho.id, turma_id=outra.id,
                     ano_letivo=escola.ano_letivo_ativo))
    _snap_e(db, escola.id, imp, vizinho.id, dias_atras=0)
    prof = Professor(escola_id=escola.id, nome="Professora Z", email="prof@frescor.local")
    db.add(prof)
    db.flush()
    escola_completa["turma"].professor_id = prof.id
    db.add(Usuario(escola_id=escola.id, nome="Professora Z", email="prof@frescor.local",
                   senha_hash=hash_senha("s3nh4"), cargo="professor"))
    db.commit()
    cli = TestClient(app)
    r = cli.post(f"{API}/auth/login",
                 data={"username": "prof@frescor.local", "password": "s3nh4"})
    cli.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

    leitura = _frescor(cli, escola.id)["dimensoes"]["leitura"]
    # A turma DELA está parada há 25 dias; a coleta de ontem da outra turma não
    # muda o que ela vê.
    assert leitura["estado"] == "desatualizado" and leitura["alunos_com_dado"] == 3


# --------------------------------------------------------------------------
# Rede
# --------------------------------------------------------------------------
@pytest.fixture()
def rede_com_duas_escolas(db):
    rede = Rede(nome="Rede Frescor", status="ativa")
    db.add(rede)
    db.flush()
    escolas = []
    for nome, dias in (("ESCOLA RECENTE", 1), ("ESCOLA PARADA", 19)):
        esc = Escola(nome=nome, ano_letivo_ativo=ANO, rede_id=rede.id, status="ativa")
        db.add(esc)
        db.flush()
        turma = Turma(escola_id=esc.id, nome="2º Ano A", ano_escolar="2º Ano",
                      ano_letivo=ANO, status="ativa")
        db.add(turma)
        db.flush()
        imp = _imp(db, esc.id)
        for i in range(2):
            a = Aluno(escola_id=esc.id, nome=f"Aluno Teste {nome} {i}", status="ativo")
            db.add(a)
            db.flush()
            db.add(Matricula(escola_id=esc.id, aluno_id=a.id, turma_id=turma.id,
                             ano_letivo=ANO))
            _snap_e(db, esc.id, imp, a.id, dias_atras=dias)
            _snap_m(db, esc.id, imp, a.id, _dia(dias))
        escolas.append(esc)
    db.add(Usuario(rede_id=rede.id, nome="Secretaria Teste", email="sec@frescor.local",
                   senha_hash=hash_senha("s3nh4"), cargo="coordenador"))
    outra = Rede(nome="Outra Rede", status="ativa")
    db.add(outra)
    db.commit()
    return {"rede": rede, "outra": outra, "escolas": escolas}


def _login(email):
    cli = TestClient(app)
    r = cli.post(f"{API}/auth/login", data={"username": email, "password": "s3nh4"})
    assert r.status_code == 200, r.text
    cli.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return cli


def test_rede_recebe_o_frescor_de_cada_escola(rede_com_duas_escolas):
    cli = _login("sec@frescor.local")
    rede = rede_com_duas_escolas["rede"]
    r = cli.get(f"{API}/redes/{rede.id}/ranking/frescor")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["limite_dias"] == frescor_ranking.LIMITE_DIAS_DADO_ATUAL
    por_nome = {e["nome"]: e for e in corpo["escolas"]}
    assert por_nome["ESCOLA RECENTE"]["estado"] == "em_dia"
    assert por_nome["ESCOLA PARADA"]["estado"] == "desatualizado"
    assert por_nome["ESCOLA PARADA"]["dimensoes"]["leitura"]["dias_desde_dado"] == 19
    # Só agregados: nenhuma chave com nome de aluno.
    assert "Aluno Teste" not in r.text


def test_rede_alheia_nao_le_o_frescor(rede_com_duas_escolas):
    cli = _login("sec@frescor.local")
    outra = rede_com_duas_escolas["outra"]
    r = cli.get(f"{API}/redes/{outra.id}/ranking/frescor")
    assert r.status_code in (403, 404), r.text


def test_frescor_da_rede_tem_numero_fixo_de_consultas(db, rede_com_duas_escolas):
    """Uma rede com dezenas de escolas não pode virar N consultas por escola."""
    from sqlalchemy import event

    from app.services import rede as svc_rede

    # Recarregadas (como a rota faz): o objeto expirado pelo commit da fixture
    # faria um SELECT por escola só para reler os próprios atributos.
    escolas = svc_rede.escolas_da_rede(db, rede_com_duas_escolas["rede"].id)
    assert len(escolas) == 2
    contagem = []
    engine = db.get_bind()

    def _conta(*_a, **_k):
        contagem.append(1)

    event.listen(engine, "before_cursor_execute", _conta)
    try:
        frescor_ranking.frescor_das_escolas(db, escolas, hoje_br(),
                                            contratados={"leitura", "matematica"})
        duas = len(contagem)
        contagem.clear()
        frescor_ranking.frescor_das_escolas(db, escolas[:1], hoje_br(),
                                            contratados={"leitura", "matematica"})
        uma = len(contagem)
    finally:
        event.remove(engine, "before_cursor_execute", _conta)
    assert duas == uma, (uma, duas)
