"""Trava contra QUEDA do acumulado do Matific na coleta automática.

O Placar ``duration=this-year`` é um contador do ANO por aluno: atividades e
estrelas só sobem dentro do ano. Antes, um relatório mais novo com total menor
(correção da plataforma, conta zerada, resposta parcial, identidade errada)
sobrescrevia o retrato e REBAIXAVA o aluno em silêncio — no ranking, na
premiação e no certificado. Agora a linha fica retida para revisão humana.
"""
import json
from datetime import date, datetime

import pytest
from sqlalchemy import select

from app.models import IdentidadeExterna, LogAuditoria, SnapshotMatific
from app.models.plataformas import Importacao
from app.sync import connectors, fuso, orchestrator, service, vault
from app.sync.interfaces import (ArquivoObtido, Conector, Contexto, Credenciais,
                                 Estrategia, ResultadoValidacao)


@pytest.fixture(autouse=True)
def _relogio_em_outubro_de_2026(monkeypatch):
    """A trava compara com o ano da COLETA (relógio de Brasília): fixa o relógio
    no ano letivo dos cenários, para o resultado não depender de quando roda."""
    monkeypatch.setattr(fuso, "hoje_local", lambda agora=None: date(2026, 10, 20))


def _ctx(escola_id):
    return Contexto(escola_id=escola_id, execucao_id=None, log=lambda *a: None)


def _placar(aluno, uuid, *, estrelas, atividades, periodo=None):
    payload = {"turma": "3 ANO A",
               "alunos": [{"nome": aluno.nome, "uuid": uuid, "turma": "3 ANO A",
                           "estrelas": estrelas, "atividades": atividades}]}
    inicio = fim = None
    if periodo:
        payload["periodo_inicio"], payload["periodo_fim"] = periodo
        inicio = datetime.fromisoformat(periodo[0])
        fim = datetime.fromisoformat(periodo[1])
    return ArquivoObtido(conteudo=json.dumps(payload).encode("utf-8"),
                         nome_arquivo="matific_3-ano-a.json", plataforma="matific",
                         content_type=orchestrator.CT_MATIFIC_API, formato_hint="resumo",
                         periodo_inicio=inicio, periodo_fim=fim)


def _base(db, escola, aluno, *, estrelas=300, atividades=100,
          quando=datetime(2026, 10, 1, 6, 0)):
    """Aluno com a identidade do Matific já vinculada e um retrato gravado."""
    db.add(IdentidadeExterna(escola_id=escola.id, aluno_id=aluno.id,
                             plataforma="matific", id_externo="uuid-ana"))
    imp = Importacao(escola_id=escola.id, plataforma="matific", tipo="texto",
                     status="concluida")
    db.add(imp)
    db.flush()
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                           data_referencia=quando, atividades=atividades,
                           estrelas=estrelas, pontuacao_media=3.0))
    db.commit()


def _atual(db, escola, aluno):
    return db.execute(
        select(SnapshotMatific).where(SnapshotMatific.escola_id == escola.id,
                                      SnapshotMatific.aluno_id == aluno.id)
        .order_by(SnapshotMatific.data_referencia.desc(), SnapshotMatific.id.desc())
        .limit(1)).scalars().one()


def _aplicar(db, escola, arquivo, monkeypatch):
    monkeypatch.setattr(orchestrator.imp, "_guardar_temporario", lambda *a, **k: None)
    return orchestrator.aplicar_arquivo(db, escola, arquivo, usuario_id=None,
                                        recalcular=False, contexto=_ctx(escola.id))


def test_total_menor_no_mesmo_ano_nao_rebaixa_o_aluno(db, escola_completa, monkeypatch):
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    _base(db, escola, ana, estrelas=300, atividades=100)

    res = _aplicar(db, escola, _placar(ana, "uuid-ana", estrelas=250, atividades=90),
                   monkeypatch)

    atual = _atual(db, escola, ana)
    assert (atual.estrelas, atual.atividades) == (300, 100)   # o gravado ficou
    assert res["retidos_queda"] == 1 and res["verificou_queda"] is True
    assert res["sem_dados"] is True                     # nada aplicado nesta turma
    audit = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "sync.matific_queda_retida")).scalars().one()
    assert audit.entidade_id == ana.id
    assert audit.detalhes["estrelas"] == {"gravado": 300, "recebido": 250}
    assert audit.detalhes["atividades"] == {"gravado": 100, "recebido": 90}
    assert ana.nome not in json.dumps(audit.detalhes)    # sem nome na auditoria


def test_so_uma_metrica_menor_tambem_retem(db, escola_completa, monkeypatch):
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    _base(db, escola, ana, estrelas=300, atividades=100)
    res = _aplicar(db, escola, _placar(ana, "uuid-ana", estrelas=320, atividades=99),
                   monkeypatch)
    assert res["retidos_queda"] == 1
    assert _atual(db, escola, ana).estrelas == 300


def test_total_maior_ou_igual_entra_normalmente(db, escola_completa, monkeypatch):
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    _base(db, escola, ana, estrelas=300, atividades=100)
    res = _aplicar(db, escola, _placar(ana, "uuid-ana", estrelas=310, atividades=100),
                   monkeypatch)
    assert res["retidos_queda"] == 0 and res["qtd_alunos"] == 1
    assert _atual(db, escola, ana).estrelas == 310


def test_virada_de_ano_o_acumulado_recomeca(db, escola_completa, monkeypatch):
    """Retrato de OUTRO ano letivo não é base de comparação: o primeiro do ano
    (ativo) entra mesmo menor — é a virada documentada."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    _base(db, escola, ana, estrelas=900, atividades=400, quando=datetime(2025, 11, 30, 6, 0))
    res = _aplicar(db, escola, _placar(ana, "uuid-ana", estrelas=12, atividades=4),
                   monkeypatch)
    assert res["retidos_queda"] == 0
    assert _atual(db, escola, ana).estrelas == 12


def test_janeiro_com_a_escola_ainda_no_ano_passado_nao_retem_o_recomeco(
        db, escola_completa, monkeypatch):
    """Jan/2027: o "this-year" do Matific recomeçou, mas a escola continua com
    ano_letivo_ativo=2026 até a gestão virar o ano. Antes, o retrato de dezembro
    servia de base e TODA linha ficava retida: coleta "sem dados", alerta para a
    escola inteira e nenhum retrato de janeiro gravado."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    assert escola.ano_letivo_ativo == 2026
    _base(db, escola, ana, estrelas=900, atividades=300, quando=datetime(2026, 12, 15, 6, 0))
    monkeypatch.setattr(fuso, "hoje_local", lambda agora=None: date(2027, 1, 12))

    res = _aplicar(db, escola, _placar(ana, "uuid-ana", estrelas=10, atividades=4),
                   monkeypatch)

    assert res["retidos_queda"] == 0 and res["sem_dados"] is False
    # O retrato de janeiro foi gravado (a data dele é a do relógio real do teste,
    # por isso a busca é pelos números, não pelo "mais recente").
    assert db.execute(select(SnapshotMatific).where(
        SnapshotMatific.aluno_id == ana.id, SnapshotMatific.estrelas == 10,
        SnapshotMatific.atividades == 4)).scalars().one()
    assert db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "sync.matific_queda_retida")).first() is None


def test_coleta_por_periodo_nao_e_conferida(db, escola_completa, monkeypatch):
    """Com start/end os números são do INTERVALO: menor que o acumulado é o normal."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    _base(db, escola, ana, estrelas=300, atividades=100)
    res = _aplicar(db, escola, _placar(ana, "uuid-ana", estrelas=20, atividades=5,
                                       periodo=("2026-09-01", "2026-09-30")), monkeypatch)
    assert res["retidos_queda"] == 0 and res["verificou_queda"] is False


def test_identidade_aposentada_nao_e_usada_na_comparacao(db, escola_completa, monkeypatch):
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    _base(db, escola, ana, estrelas=300, atividades=100)
    ident = db.execute(select(IdentidadeExterna)).scalars().one()
    ident.status = "aposentada"
    db.commit()
    linhas = [type("L", (), {"dados": {"matific_uuid": "uuid-ana", "estrelas": 1,
                                       "atividades": 1}})()]
    mantidas, n = orchestrator.reter_quedas_matific(db, escola, linhas, _ctx(escola.id))
    assert n == 0 and mantidas == linhas


class _ConectorPlacar(Conector):
    plataforma = "matific"
    versao = "teste"
    estrategia = Estrategia.NAVEGADOR

    def __init__(self, arquivo):
        self.arquivo = arquivo

    async def testar_credenciais(self, cred, ctx):
        return ResultadoValidacao(True, "ok", "ok")

    async def localizar_relatorios(self, cred, ctx):
        return []

    async def obter(self, cred, rel, ctx):
        raise NotImplementedError

    async def sincronizar(self, cred, ctx):
        return [self.arquivo]


def test_execucao_abre_alerta_de_revisao_e_fecha_quando_a_queda_some(
        db, escola_completa, monkeypatch):
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    _base(db, escola, ana, estrelas=300, atividades=100)
    vault.salvar_credencial(db, escola.id, "matific", Credenciais(usuario="u", senha="p"))
    db.commit()
    monkeypatch.setattr(orchestrator.imp, "_guardar_temporario", lambda *a, **k: None)

    monkeypatch.setitem(connectors._REGISTRO, "matific", _ConectorPlacar(
        _placar(ana, "uuid-ana", estrelas=250, atividades=90)))
    ex = service.enfileirar(db, escola.id, "matific", origem="manual")
    service.executar(db, ex)
    abertos = [a.tipo for a in
               db.query(service.SincronizacaoAlerta).filter_by(resolvido=False)]
    assert "queda_matific" in abertos
    assert _atual(db, escola, ana).estrelas == 300

    # A plataforma voltou a mandar o acumulado certo: aplica e fecha o alerta.
    monkeypatch.setitem(connectors._REGISTRO, "matific", _ConectorPlacar(
        _placar(ana, "uuid-ana", estrelas=305, atividades=101)))
    ex2 = service.enfileirar(db, escola.id, "matific", origem="manual")
    service.executar(db, ex2)
    assert ex2.status == "concluida"
    assert db.query(service.SincronizacaoAlerta).filter_by(
        tipo="queda_matific", resolvido=False).count() == 0
    assert _atual(db, escola, ana).estrelas == 305
