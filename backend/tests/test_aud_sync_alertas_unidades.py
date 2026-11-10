"""O alerta "Coleta parcial" (cartão de Integrações) diz QUAL parte da coleta falhou
na língua de quem lê, nunca o código interno da unidade ("endpoint: 1", "lote: 1").

O A6 já traduzia o motivo das linhas com defeito (``resumo_descartes``); o resumo
das unidades com falha (``resumo_falhas``), no mesmo alerta e na mensagem de erro
"Nenhum dado aplicado…", ainda saía cru. Dados fictícios; conectores reais com
navegador falso.
"""
import re

from sqlalchemy import select

from app.models.sincronizacao import SincronizacaoAlerta
from app.sync import service
from tests._sync_nucleo_fakes import NavElefante, credencial, instalar, rodar
from tests.test_sync_integridade_nucleo import CID_B, _duas_turmas, _matific_http

CODIGOS = ("endpoint", "lote", "arquivo", "aluno")


def _mensagem(db, eid, plataforma, tipo="coleta_parcial"):
    return db.execute(select(SincronizacaoAlerta.mensagem).where(
        SincronizacaoAlerta.escola_id == eid, SincronizacaoAlerta.plataforma == plataforma,
        SincronizacaoAlerta.tipo == tipo, SincronizacaoAlerta.resolvido.is_(False))).scalar_one()


def _sem_codigo(msg):
    """Os códigos crus que aparecem como rótulo de unidade ("(lote: 1", ", aluno: 2")."""
    return re.findall(r"(?:\(|, )(" + "|".join(CODIGOS) + r"): \d", msg)


def test_matific_com_a_lista_de_nomes_recusada_diz_o_que_falhou(db, escola_completa,
                                                                 monkeypatch):
    eid, _a, ex, _ = _matific_http(db, escola_completa, monkeypatch, lb=403)
    assert ex.status == "parcial"
    msg = _mensagem(db, eid, "matific")
    assert not _sem_codigo(msg), msg
    assert "lista de nomes completos do Matific: 1" in msg, msg


def test_elefante_com_o_lote_de_livros_falhando_diz_o_que_falhou(db, escola_completa,
                                                                 monkeypatch):
    eid, _al, turmas = _duas_turmas(db, escola_completa)
    credencial(db, eid, "elefante")
    instalar(monkeypatch, nav_elefante=NavElefante(turmas, excecao_lote={CID_B}))
    ex, _ = rodar(db, eid, "elefante")
    assert ex.status == "parcial"
    msg = _mensagem(db, eid, "elefante")
    assert not _sem_codigo(msg), msg
    assert "livros lidos de uma turma: 1" in msg, msg


def test_elefante_com_os_livros_de_um_aluno_falhando_diz_o_que_falhou(db, escola_completa,
                                                                      monkeypatch):
    eid, _al, turmas = _duas_turmas(db, escola_completa)
    credencial(db, eid, "elefante")
    instalar(monkeypatch, nav_elefante=NavElefante(turmas, status_aluno={9200001: 500}))
    ex, _ = rodar(db, eid, "elefante")
    assert ex.status == "parcial"
    msg = _mensagem(db, eid, "elefante")
    assert not _sem_codigo(msg), msg
    assert "livros lidos de um aluno: 1" in msg, msg


def test_resumo_das_falhas_rotula_todas_as_unidades():
    ap = service._Apuracao()
    ap.falhas = [{"unidade": u, "id": "1", "codigo": "falha_download", "http": None}
                 for u in ("turma", "lote", "lote", "aluno", "endpoint", "arquivo",
                           "unidade_nova")]
    resumo = ap.resumo_falhas()
    assert not _sem_codigo(resumo), resumo
    assert "_" not in resumo, resumo
    for rotulo in ("turma: 1", "livros lidos de uma turma: 2", "livros lidos de um aluno: 1",
                   "lista de nomes completos do Matific: 1", "relatório de turma: 1",
                   "unidade nova: 1"):
        assert rotulo in resumo, resumo
