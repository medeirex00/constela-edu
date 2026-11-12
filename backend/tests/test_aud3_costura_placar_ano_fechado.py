"""Placar AO VIVO do Matific (a Matemática por período da web) num período de ano letivo
ENCERRADO, consultado depois da virada: a linha da formanda continua abrindo a ficha dela
(S_G_VIRADA-2/ranking-matematica, REV3-PERIODO-3; costura da fase D).

A lista e as turmas vêm do Matific; só o vínculo da linha à ficha usava o ano letivo
ATIVO (``_fichas_da_escola(db, escola_id, escola.ano_letivo_ativo)``): na cerimônia de
2026 feita em fevereiro de 2027, a formanda do 5º ano (sem matrícula em 2027) saía sem
link, enquanto as Premiações, o Ranking de Leitura e o Relatório do mesmo período já a
mostram com a turma de 2026. Agora o vínculo usa a população do período
(``periodos.populacao_do_periodo``, a decisão técnica da fase D), e a resposta diz de que
ano é (``populacao``). Dados 100% fictícios; sem rede (a coleta é substituída).
"""
from datetime import datetime

import pytest

from app.models import Aluno, IdentidadeExterna, Matricula, Turma
from app.sync import aovivo, connectors, vault
from app.sync.interfaces import Credenciais

PERIODO = {"periodo": "personalizado", "inicio": "2026-10-01", "fim": "2026-12-15"}
K = "5 ANO A TARDE (300000005)"


@pytest.fixture(autouse=True)
def _limpar_cache_resultado():
    aovivo._cache.clear()
    yield
    aovivo._cache.clear()


def _linha(nome, uuid, estrelas, atividades):
    return {"nome": nome, "nome_abrev": nome, "uuid": uuid, "turma": K, "serie": "5",
            "estrelas": estrelas, "atividades": atividades}


@pytest.fixture()
def placar(db, escola_completa, monkeypatch):
    """2026: DORA (formanda, 5º ano) e ANA; 2027: só ANA. Contas do Matific vinculadas."""
    escola = escola_completa["escola"]
    assert escola.ano_letivo_ativo == 2026
    t5 = Turma(escola_id=escola.id, nome="5º Ano A", ano_escolar="5º Ano", ano_letivo=2026)
    t_novo = Turma(escola_id=escola.id, nome="5º Ano B", ano_escolar="5º Ano", ano_letivo=2027)
    db.add_all([t5, t_novo])
    db.flush()
    alunos = {}
    for nome, uuid in (("DORA FICTICIA MELO", "u-dora"), ("ANA FICTICIA SOUZA", "u-ana")):
        a = Aluno(escola_id=escola.id, nome=nome, status="ativo")
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=t5.id, ano_letivo=2026))
        db.add(IdentidadeExterna(escola_id=escola.id, aluno_id=a.id, plataforma="matific",
                                 id_externo=uuid, status="efetiva"))
        alunos[nome] = a
    db.add(Matricula(escola_id=escola.id, aluno_id=alunos["ANA FICTICIA SOUZA"].id,
                     turma_id=t_novo.id, ano_letivo=2027))
    linhas = [_linha("DORA FICTICIA MELO", "u-dora", 90, 20),
              _linha("ANA FICTICIA SOUZA", "u-ana", 40, 10)]

    class _Conector:
        def coletar_via_http(self, *a, **k):  # pragma: no cover - substituído abaixo
            raise AssertionError("não deve ser chamado")

    monkeypatch.setattr(connectors, "obter",
                        lambda plat: _Conector() if plat == "matific" else None)
    monkeypatch.setattr(aovivo, "_coletar_http_first",
                        lambda *a, **k: ([dict(x) for x in linhas], None))
    vault.salvar_credencial(db, escola.id, "matific", Credenciais(usuario="u", senha="p"))
    db.commit()

    def virar():
        escola.ano_letivo_ativo = 2027
        db.commit()
        aovivo._cache.clear()

    return {"escola": escola, "alunos": alunos, "virar": virar}


def _consultar(db, placar, agora):
    return aovivo.placar_matific(db, placar["escola"].id, forcar=True, agora=agora, **PERIODO)


def test_formanda_continua_com_link_no_placar_do_ano_fechado(db, placar):
    antes = _consultar(db, placar, datetime(2026, 12, 20, 15, 0))
    placar["virar"]()
    depois = _consultar(db, placar, datetime(2027, 2, 10, 15, 0))
    dora = placar["alunos"]["DORA FICTICIA MELO"].id
    ana = placar["alunos"]["ANA FICTICIA SOUZA"].id
    # Antes do conserto, depois da virada: [None, ana] — a formanda sem link.
    assert [i["aluno_id"] for i in depois["itens"]] == [dora, ana]
    assert [i["aluno_id"] for i in antes["itens"]] == [dora, ana]
    assert depois["com_link"] == 2
    assert depois["populacao"] == {"ano_letivo": 2026, "origem": "ano_do_periodo",
                                   "ano_letivo_ativo": 2027}
    assert antes["populacao"]["origem"] == "ano_ativo"


def test_periodo_do_ano_ativo_liga_as_criancas_de_agora(db, placar):
    """Controle: depois da virada, um período de 2027 só liga quem tem matrícula em 2027."""
    placar["virar"]()
    r = aovivo.placar_matific(db, placar["escola"].id, periodo="personalizado",
                              inicio="2027-02-01", fim="2027-02-09", forcar=True,
                              agora=datetime(2027, 2, 10, 15, 0))
    ana = placar["alunos"]["ANA FICTICIA SOUZA"].id
    assert [i["aluno_id"] for i in r["itens"]] == [None, ana]
    assert r["populacao"]["origem"] == "ano_ativo"
