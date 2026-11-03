"""Escola externa: achados da revisão adversarial e95 (frente escola) corrigidos.

Cada teste FALHA no 3127008 (ramo antes desta correção) e passa depois:

  A1  a credencial de OUTRA escola na 1ª coleta (todas as contas já efetivas na
      escola dona) não fixa o vínculo da escola externa da outra — e a escola
      dona não fica bloqueada (Elefante e Matific);
  J   Matific: o ``school_id`` que o próprio corpo do Placar declara tem de ser o
      pedido (sync pelo navegador e caminho HTTP do placar ao vivo);
  K   com vínculo gravado, o serviço recusa a escola detectada diferente dele,
      venha de onde vier (defesa em profundidade; hoje nenhum conector chega lá).

O que depende da plataforma é suposição registrada em docs/SINCRONIZACAO.md
(o corpo do ``school_student`` traz ``school_id``: MATIFIC_API §4.1). Sem o campo
no corpo, o código segue como antes (não inventa garantia). Ficam para decisão
do dono, sem teste aqui: B, V e E (ver o relatório da Etapa 3). A2 e A3 viraram
as decisões D8 e D9 (``test_sync_escola_externa_decisoes.py``): a coleta em que
TODAS as contas já são de outra escola é recusada antes de aplicar (o A1 daqui
passa a valer para a coleta mista), e o nome divergente da escola externa impede
o aprendizado automático do vínculo.

Dados 100% fictícios; conectores reais com navegador falso; sem rede. Os mesmos
cenários rodam no PostgreSQL local em ``test_sync_escola_cruzada_revisao_pg.py``.
"""
import re

import httpx
import pytest
from sqlalchemy import select

from app.models.nota import LogAuditoria
from app.sync import escola_externa
from app.sync.connectors import elefante as con_elefante
from app.sync.connectors import matific as con_matific
from app.sync.interfaces import ErroConector
from tests._sync_nucleo_fakes import PlacarFake, alertas_abertos, contagens, credencial, rodar
from tests.test_sync_escola_cruzada import (
    CID_A, CID_B, CID_C, ESC_A, OUTRA_UUID, NavEl, NavMt, _fabrica, _nova_escola, _placar,
    _turmas, instalar_navs)


def _auditoria(db, acao):
    return db.execute(select(LogAuditoria).where(LogAuditoria.acao == acao)).scalars().all()


# ---------------------------------------------------------------------------
# A1. Credencial trocada na 1ª coleta depois da implantação (sem vínculo)
# ---------------------------------------------------------------------------
def test_a1_elefante_conta_de_outra_escola_na_1a_coleta_nao_fixa_o_vinculo(
        db, escola_completa, monkeypatch):
    """Escola 1 = dona de ESC_A, com dados e identidades de antes da implantação
    (sem vínculo). A escola 2 cadastrou, por engano, a conta da escola 1 e
    sincroniza PRIMEIRO. Antes: a 2 aprendia ESC_A e a 1, com a própria conta,
    terminava 'erro/escola_externa_em_outra_escola'. Com a decisão D8, como TODAS
    as contas são da escola 1, a coleta da 2 é recusada antes de aplicar (nem o
    vínculo nem revisão); a coleta mista está em ``test_a1_coleta_mista…``."""
    e1 = escola_completa["escola"].id
    credencial(db, e1, "elefante")
    turmas = _turmas(escola_completa)
    del turmas[CID_B]
    instalar_navs(monkeypatch, elefante=NavEl(turmas, escola_da_turma={CID_A: ESC_A}))
    ex0, _ = rodar(db, e1, "elefante")
    assert ex0.status == "concluida", (ex0.status, ex0.motivo)
    escola_externa.remover(db, e1, "elefante")          # estado de antes da implantação
    db.commit()
    escola2, _t, _a = _nova_escola(db, com_alunos=["Criança Ficticia Da Segunda Escola"])
    e2 = escola2.id
    credencial(db, e2, "elefante")
    antes_e2 = contagens(db, e2)
    ex2, erro = rodar(db, e2, "elefante")               # a conta da escola 1, na 2
    assert erro is None
    assert (ex2.status, ex2.motivo) == ("erro", "contas_de_outra_escola")
    assert escola_externa.obter(db, e2, "elefante") is None, ex2.motivo
    assert contagens(db, e2)["alunos"] == antes_e2["alunos"]      # nenhuma ficha nasce
    assert contagens(db, e2)["revisoes"] == antes_e2["revisoes"]  # nem revisão (D8)
    assert "contas_de_outra_escola" in alertas_abertos(db, e2, "elefante")
    assert _auditoria(db, "sync.escola_externa_desfeita") == []   # nada aprendido
    ex1, _ = rodar(db, e1, "elefante")                  # a dona, com a conta dela
    assert (ex1.status, ex1.motivo) != ("erro", "escola_externa_em_outra_escola")
    assert ex1.status in ("concluida", "sem_atualizacao"), (ex1.status, ex1.motivo)
    assert escola_externa.obter(db, e1, "elefante")["id"] == str(ESC_A)


def test_a1_coleta_mista_aprende_e_desfaz_o_vinculo(db, escola_completa, monkeypatch):
    """A1 na coleta MISTA (o D8 não recusa): a escola 1 tem uma criança nova
    (conta 7003) que ainda não é de ninguém no Constela. A coleta da escola 2 com
    a conta da escola 1 segue (política 'bloquear': nenhuma ficha nasce), as
    contas da 1 vão para a revisão e o vínculo aprendido é desfeito no fim."""
    from app.services import politica_sync

    e1 = escola_completa["escola"].id
    credencial(db, e1, "elefante")
    turmas = _turmas(escola_completa)
    del turmas[CID_B]
    nav = NavEl(turmas, escola_da_turma={CID_A: ESC_A})
    instalar_navs(monkeypatch, elefante=nav)
    assert rodar(db, e1, "elefante")[0].status == "concluida"
    escola_externa.remover(db, e1, "elefante")
    db.commit()
    nav.turmas = _turmas(escola_completa, com_c=True)
    del nav.turmas[CID_B]
    nav.escola_da_turma = {CID_A: ESC_A, CID_C: ESC_A}
    nav.course_reports.clear()
    # Nome PARECIDO com o da escola externa: o porteiro do nome (D9) deixa
    # aprender, e quem segura o vínculo errado é o A1.
    escola2, _t, _a = _nova_escola(db, nome="ESCOLA TESTE II",
                                   com_alunos=["Criança Ficticia Da Segunda Escola"])
    e2 = escola2.id
    politica_sync.definir(db, e2, "bloquear")
    db.commit()
    credencial(db, e2, "elefante")
    antes_e2 = contagens(db, e2)
    ex2, erro = rodar(db, e2, "elefante")
    assert erro is None
    assert ex2.motivo != "contas_de_outra_escola", (ex2.status, ex2.motivo)
    assert escola_externa.obter(db, e2, "elefante") is None, ex2.motivo
    assert contagens(db, e2)["alunos"] == antes_e2["alunos"]
    assert "identidade_de_outra_escola" in alertas_abertos(db, e2, "elefante")
    assert len(_auditoria(db, "sync.escola_externa_desfeita")) == 1
    ex1, _ = rodar(db, e1, "elefante")
    assert (ex1.status, ex1.motivo) != ("erro", "escola_externa_em_outra_escola")
    assert escola_externa.obter(db, e1, "elefante")["id"] == str(ESC_A)


def test_a1m_matific_conta_de_outra_escola_na_1a_coleta_nao_fixa_o_vinculo(
        db, escola_completa, monkeypatch):
    e1 = escola_completa["escola"].id
    credencial(db, e1, "matific")
    nav = NavMt(_placar(escola_completa))
    instalar_navs(monkeypatch, matific=nav)
    assert rodar(db, e1, "matific")[0].status == "concluida"
    escola_externa.remover(db, e1, "matific")
    db.commit()
    escola2, _t, _a = _nova_escola(db, com_alunos=["Criança Ficticia Da Segunda Escola"])
    e2 = escola2.id
    credencial(db, e2, "matific")
    ex2, erro = rodar(db, e2, "matific")
    assert erro is None
    assert (ex2.status, ex2.motivo) == ("erro", "contas_de_outra_escola")     # D8
    assert escola_externa.obter(db, e2, "matific") is None, ex2.motivo
    ex1, _ = rodar(db, e1, "matific")
    assert (ex1.status, ex1.motivo) != ("erro", "escola_externa_em_outra_escola")
    assert ex1.status in ("concluida", "sem_atualizacao"), (ex1.status, ex1.motivo)
    assert escola_externa.obter(db, e1, "matific") is not None


def test_a1_controle_primeira_coleta_da_propria_escola_aprende_o_vinculo(
        db, escola_completa, monkeypatch):
    """Controle: sem conta de outra escola na coleta, o vínculo continua aprendido
    na 1ª coleta (o que as 5 escolas fazem depois da implantação)."""
    e1 = escola_completa["escola"].id
    credencial(db, e1, "elefante")
    turmas = _turmas(escola_completa)
    del turmas[CID_B]
    instalar_navs(monkeypatch, elefante=NavEl(turmas, escola_da_turma={CID_A: ESC_A}))
    ex, _ = rodar(db, e1, "elefante")
    assert ex.status == "concluida", (ex.status, ex.motivo)
    assert escola_externa.obter(db, e1, "elefante")["id"] == str(ESC_A)
    assert _auditoria(db, "sync.escola_externa_desfeita") == []


# ---------------------------------------------------------------------------
# J. Matific: o school_id do CORPO do Placar
# ---------------------------------------------------------------------------
class PlacarOutraEscola(PlacarFake):
    """O school_student responde 200 com o corpo de OUTRA escola (school_id do
    corpo diferente do pedido)."""

    def school_student(self, expr):
        res = super().school_student(expr)
        if res.get("ok"):
            res["body"][0]["school_id"] = OUTRA_UUID
        return res


class PlacarEco(PlacarFake):
    """school_student que devolve no corpo o school_id PEDIDO (fiel ao §4.1)."""

    def school_student(self, expr):
        res = super().school_student(expr)
        m = re.search(r"school_id=([0-9a-f-]{36})", expr)
        if res.get("ok") and m:
            res["body"][0]["school_id"] = m.group(1)
        return res


def test_j_matific_corpo_do_placar_de_outra_escola_nao_e_aplicado(db, escola_completa,
                                                                  monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "matific")
    placar = PlacarOutraEscola()
    placar.linhas = list(_placar(escola_completa).linhas)
    instalar_navs(monkeypatch, matific=NavMt(placar))
    antes = contagens(db, eid)
    ex, _ = rodar(db, eid, "matific")
    assert (ex.status, ex.motivo) == ("erro", "escola_externa_trocada")
    assert contagens(db, eid)["snap_mt"] == antes["snap_mt"]
    assert "escola_externa_trocada" in alertas_abertos(db, eid, "matific")


def test_j_controle_corpo_com_a_escola_pedida_aplica(db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "matific")
    placar = PlacarEco()
    placar.linhas = list(_placar(escola_completa).linhas)
    instalar_navs(monkeypatch, matific=NavMt(placar))
    ex, _ = rodar(db, eid, "matific")
    assert ex.status == "concluida", (ex.status, ex.motivo, ex.erro_resumo)


def test_j_placar_ao_vivo_http_recusa_corpo_de_outra_escola(monkeypatch):
    """Caminho HTTP (também o do placar ao vivo, que mostraria nomes): a conta é da
    escola pedida, mas o corpo do school_student diz outra."""
    from tests.test_matific_aovivo import SCHOOL, NavFake, _FakeResp, _fake_httpx_client, _payloads

    ss, sl = _payloads({"u-ana": "Ana Beatriz Souza"})
    outro = {"ok": True, "status": 200,
             "body": [{**ss["body"][0], "school_id": OUTRA_UUID}]}
    estado = {"cookies": [{"name": "sessionid", "value": "abc", "domain": ".matific.com"}]}

    def _rotas(corpo_ss):
        return _fake_httpx_client({
            "student-leaderboard": _FakeResp(sl["body"]),
            "school_student": _FakeResp(corpo_ss["body"]),
            "accounts/current": _FakeResp({"school_id": SCHOOL}),
            "competition-v2": _FakeResp([{"id": "c1", "is_live": True}])})

    con = con_matific.ConectorMatific(_fabrica(NavFake(ss, sl)))
    monkeypatch.setattr(httpx, "Client", _rotas(outro))
    with pytest.raises(ErroConector) as exc:
        con.coletar_via_http(estado, "duration=week", escola_esperada=SCHOOL)
    assert exc.value.codigo == "escola_externa_trocada"
    monkeypatch.setattr(httpx, "Client", _rotas(ss))                    # controle
    assert con.coletar_via_http(estado, "duration=week", escola_esperada=SCHOOL)


# ---------------------------------------------------------------------------
# K. O serviço confere a escola detectada contra o vínculo gravado
# ---------------------------------------------------------------------------
def test_k_servico_recusa_escola_detectada_diferente_do_vinculo(db, escola_completa,
                                                                monkeypatch):
    """Teste sintético: um conector (ou caminho futuro) anota uma escola externa
    diferente da vinculada. Antes: 'concluida', aplicando o dado."""
    eid = escola_completa["escola"].id
    credencial(db, eid, "elefante")
    turmas = _turmas(escola_completa)
    del turmas[CID_B]
    instalar_navs(monkeypatch, elefante=NavEl(turmas, escola_da_turma={CID_A: ESC_A}))
    escola_externa.salvar(db, eid, "elefante", str(ESC_A), origem="explicito")
    db.commit()
    original = con_elefante.ConectorElefante.sincronizar

    async def sincronizar_desviado(self, cred, contexto):
        arquivos = await original(self, cred, contexto)
        contexto.coleta["escola_externa"] = {"id": "99999", "nome": "OUTRA FICTICIA"}
        return arquivos

    monkeypatch.setattr(con_elefante.ConectorElefante, "sincronizar", sincronizar_desviado)
    antes = contagens(db, eid)
    ex, _ = rodar(db, eid, "elefante")
    assert (ex.status, ex.motivo) == ("erro", "escola_externa_trocada")
    assert contagens(db, eid) == antes
    assert escola_externa.obter(db, eid, "elefante")["id"] == str(ESC_A)   # não troca
