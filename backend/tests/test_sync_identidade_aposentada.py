"""Conta da plataforma que a escola APOSENTOU: descarte com motivo próprio.

Achado 5 da revisão e95 (decisão D4; A2 §3.4). A criança tinha DUAS contas na
plataforma e a escola escolheu qual vale; a outra ficou aposentada. A plataforma
continua mandando a conta aposentada, e cada coleta:

  * contava a linha em 'sem_vinculo' e em ``ignorados`` — a integração nunca
    chegava a "nada mudou" (sempre 'correspondencia_pendente' com "0 contas"), a
    verificação não avançava;
  * desfazia o cursor da CRIANÇA, porque o nome da conta aposentada é o dela.

Agora a linha é descartada com o motivo 'identidade_aposentada', fora de
``ignorados`` e de 'sem_vinculo', e não conta como defeito. Uma coleta que só
traz contas aposentadas não confere a escola (forma C): não é "em dia".

Dados 100% fictícios; conectores reais com navegador falso; sem rede. Os
cenários de ponta a ponta rodam também no PostgreSQL local em
``test_sync_identidade_aposentada_pg.py``.
"""
from datetime import datetime, timezone

from sqlalchemy import select

from app.models import IdentidadeExterna, RevisaoIdentidade
from app.models.sincronizacao import SincronizacaoAlerta
from app.services import politica_sync
from app.sync import service
from tests._sync_nucleo_fakes import (
    API, NavElefante, aluno_el, credencial, instalar, livro, rodar)

K = "3 ANO A (300396804)"
CID_A = 511434
SID_A, SID_DUP = 9100001, 9100009


def _agora():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _alerta(db, eid, tipo, plataforma="elefante"):
    return db.execute(select(SincronizacaoAlerta).where(
        SincronizacaoAlerta.escola_id == eid, SincronizacaoAlerta.plataforma == plataforma,
        SincronizacaoAlerta.tipo == tipo,
        SincronizacaoAlerta.resolvido.is_(False))).scalars().first()


def _status(cliente, eid, plataforma="elefante"):
    r = cliente.get(f"{API}/escolas/{eid}/sync/status")
    assert r.status_code == 200, r.text[:300]
    return next(p for p in r.json()["plataformas"] if p["plataforma"] == plataforma)


def _da_escola(ec, livros_a=1):
    a, b, c = ec["alunos"]
    return {CID_A: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        aluno_el(SID_A, a.nome, [livro(f"Livro Ficticio A{i}", "D",
                                       f"2026-09-0{i + 1}T10:00:00")
                                 for i in range(livros_a)]),
        aluno_el(9100002, b.nome, [livro("Livro Ficticio Dois", "E", "2026-09-05T10:00:00")]),
        aluno_el(9100003, c.nome, [livro("Livro Ficticio Tres", "D", "2026-09-06T10:00:00")])]}}


def _aposentar_duplicata(db, eid, aluno_id):
    db.add(IdentidadeExterna(escola_id=eid, aluno_id=aluno_id, plataforma="elefante",
                             id_externo=str(SID_DUP), status="aposentada",
                             aposentada_em=_agora(),
                             motivo_aposentadoria="conta duplicada (teste ficticio)"))
    db.commit()


def _cena(db, escola_completa, monkeypatch):
    """1ª coleta vincula as três crianças; a escola então aposenta a conta
    duplicada da criança A, que a plataforma passa a mandar junto."""
    eid = escola_completa["escola"].id
    a = escola_completa["alunos"][0]
    politica_sync.definir(db, eid, "bloquear")
    db.commit()
    credencial(db, eid, "elefante")
    nav = NavElefante(_da_escola(escola_completa))
    instalar(monkeypatch, nav_elefante=nav)
    ex1, _ = rodar(db, eid, "elefante")
    assert ex1.status == "concluida"
    _aposentar_duplicata(db, eid, a.id)
    nav.turmas[CID_A]["alunos"].append(aluno_el(SID_DUP, a.nome, [livro("Livro Ficticio Um")]))
    return eid, a, nav


def test_conta_aposentada_nao_vira_pendencia_permanente(db, cliente, escola_completa,
                                                       monkeypatch):
    """Sonda e95 s3 invertida: antes ex2 e ex3 = sem_atualizacao/
    correspondencia_pendente com 0 contas na fila, e a verificação parada."""
    eid, _a, _nav = _cena(db, escola_completa, monkeypatch)
    ex2, _ = rodar(db, eid, "elefante")
    ex3, _ = rodar(db, eid, "elefante")
    for ex in (ex2, ex3):
        assert (ex.status, ex.motivo) == ("sem_atualizacao", "nada_mudou"), (ex.status, ex.motivo)
        assert ex.qtd_em_revisao == 0
        assert ex.qtd_erros == 0
    assert _alerta(db, eid, "correspondencia_pendente") is None
    assert _alerta(db, eid, "coleta_parcial") is None
    p = _status(cliente, eid)
    assert p["ultima_verificacao_em"] is not None
    # Nenhuma pendência nasceu da conta aposentada.
    assert db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == eid)).scalars().first() is None


def test_conta_aposentada_nao_desfaz_o_cursor_da_crianca(db, escola_completa, monkeypatch):
    """O nome da conta aposentada é o da criança: antes o cursor DELA era
    desfeito em toda coleta (a próxima incremental a buscava de novo, sempre)."""
    eid, _a, nav = _cena(db, escola_completa, monkeypatch)
    assert service._carregar_contadores(db, eid, "elefante")[str(SID_A)] == 1
    # A criança A lê mais um livro: a coleta aplica e o cursor dela AVANÇA.
    nav.turmas[CID_A]["alunos"][0] = _da_escola(escola_completa, livros_a=2)[CID_A]["alunos"][0]
    ex2, _ = rodar(db, eid, "elefante")
    assert ex2.status == "concluida", (ex2.status, ex2.motivo)
    assert service._carregar_contadores(db, eid, "elefante")[str(SID_A)] == 2


def test_so_contas_aposentadas_na_coleta_nao_e_em_dia(db, cliente, escola_completa,
                                                      monkeypatch):
    """Só veio a conta aposentada (nenhuma conta da escola conferida): nada a
    revisar, mas também não prova que o dado está em dia (forma C) — e não
    abre alerta de pendência que não existe."""
    eid, a, nav = _cena(db, escola_completa, monkeypatch)
    verificado_antes = _status(cliente, eid)["ultima_verificacao_em"]
    nav.turmas[CID_A]["alunos"] = [aluno_el(SID_DUP, a.nome, [livro("Livro Ficticio Um")])]
    ex2, _ = rodar(db, eid, "elefante")
    assert (ex2.status, ex2.motivo) == ("sem_atualizacao", service.MOTIVO_TUDO_EM_REVISAO)
    assert ex2.qtd_em_revisao == 0
    assert _alerta(db, eid, "correspondencia_pendente") is None
    assert _status(cliente, eid)["ultima_verificacao_em"] == verificado_antes


def test_importacao_manual_descarta_a_conta_aposentada_com_motivo_proprio(
        db, cliente, escola_completa):
    """O mesmo caminho do upload manual: a linha da conta aposentada não entra em
    ``ignorados`` nem em 'sem_vinculo' — fica no motivo próprio, com aviso."""
    eid = escola_completa["escola"].id
    a = escola_completa["alunos"][0]
    _aposentar_duplicata(db, eid, a.id)
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/confirmar", json={
        "plataforma": "elefante", "formato": "resumo", "tipo": "texto", "recalcular": False,
        "linhas": [{"nome": a.nome, "dados": {
            "elefante_student_id": str(SID_DUP), "turma_relatorio": K,
            "livros_unicos": 3, "tempo_leitura_min": 10}}]})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["linhas_descartadas"] == {"identidade_aposentada": 1}
    assert corpo["ignorados"] == []
    assert corpo["linhas_em_revisao"] == 0 and corpo["qtd_revisoes"] == 0
    assert any("APOSENTADA" in aviso for aviso in corpo["avisos"])


# ---------------------------------------------------------------------------
# A contabilidade (sem banco)
# ---------------------------------------------------------------------------
def test_decidir_status_com_descarte_decidido():
    ap = service._Apuracao
    # 3 contas conferidas + 1 linha de conta aposentada → nada mudou.
    assert service.decidir_status(ap(linhas=4, conferidos_sem_mudanca=3,
                                     descartes={"identidade_aposentada": 1})) == (
        "sem_atualizacao", "nada_mudou")
    # Dado novo + conta aposentada → concluída (não é "parcial": não é defeito).
    assert service.decidir_status(ap(linhas=4, aplicados={1},
                                     descartes={"identidade_aposentada": 1})) == (
        "concluida", None)
    # Só conta aposentada → nenhuma conta da escola conferida: não é em dia.
    assert service.decidir_status(ap(linhas=2, descartes={"identidade_aposentada": 2})) == (
        "sem_atualizacao", service.MOTIVO_TUDO_EM_REVISAO)
    # Conta aposentada + todo o resto com defeito → erro por linhas descartadas.
    assert service.decidir_status(ap(linhas=2, descartes={"identidade_aposentada": 1,
                                                          "sem_data": 1})) == (
        "erro", "linhas_descartadas")
    # Pendência real continua pendência.
    assert service.decidir_status(ap(linhas=3, conferidos_sem_mudanca=1, em_revisao=1,
                                     ignorados={"x"},
                                     descartes={"identidade_aposentada": 1})) == (
        "sem_atualizacao", "correspondencia_pendente")


def test_descarte_decidido_nao_e_defeito_nem_erro():
    ap = service._Apuracao(linhas=5, conferidos_sem_mudanca=3,
                           descartes={"identidade_aposentada": 2, "sem_vinculo": 0})
    assert ap.decididos == 2
    assert ap.defeitos == 0
    assert ap.qtd_erros == 0
    assert ap.resumo_descartes() == ""
    com_defeito = service._Apuracao(linhas=5, descartes={"identidade_aposentada": 1,
                                                         "sem_data": 2})
    assert com_defeito.defeitos == 2
    assert com_defeito.resumo_descartes() == "sem_data: 2"
