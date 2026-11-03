"""DOURADO do GET /sync/status e do POST /sync/agora de escola DE REDE (e97x, 28/10).

A trava de contrato (módulo fora do plano da rede não é coletado nem envelhece)
fazia o /status reler ``modulos_rede`` uma vez por plataforma com agenda e o
/agora reler a escola e o contrato — 2 idas a mais que a escola avulsa no /status
e 1 no /agora, ~0,2 s cada em produção. O orçamento (rede = avulsa) está em
``test_sync_rede_orcamento.py``; este teste prende o CONTRATO das respostas.

Estados:
  * /status: cada cenário de ``sync_status_cenarios`` com a escola numa rede que
    contratou tudo (deve dizer o mesmo que a avulsa), e os dados velhos / a fila
    parada numa rede sem Leitura ou sem Matemática (fecha o alerta do módulo fora);
  * /agora: cria e depois reaproveita; rede sem Matemática (sem plataforma = só o
    Elefante; o Matific pedido = 403); credencial ilegível e ausente (400); coleta
    por período — avulsa, rede com tudo e rede sem Matemática.
As respostas foram gravadas em ``sync_rede_dourado.json`` com o código de antes
(6251075). O ``created_at`` das execuções que os próprios pedidos do teste criam é o
relógio real e sai trocado por um marcador; o resto é comparado campo a campo.

Mudança INTENCIONAL na resposta: regravar com ``REGRAVAR_DOURADO_REDE=1``.
"""
import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from app.models import Escola
from app.models.rede import ModuloRede, Rede
from app.models.sincronizacao import PlataformaCredencial, SincronizacaoExecucao
from app.sync import service
from tests import sync_status_cenarios as cenarios

ARQUIVO = Path(__file__).resolve().parent / "sync_rede_dourado.json"
REGRAVAR = os.environ.get("REGRAVAR_DOURADO_REDE") == "1"
CRIADA_AGORA = "<criada por um pedido do teste>"

REDES = {
    "avulsa": None,
    "rede_toda": (),
    "rede_sem_leitura": ("leitura",),
    "rede_sem_matematica": ("matematica",),
}


def na_rede(db, escola_id: int, rede: str) -> None:
    """Põe a escola na rede pedida (ou tira de qualquer rede: ``avulsa``)."""
    escola = db.get(Escola, escola_id)
    desligados = REDES[rede]
    if desligados is None:
        escola.rede_id = None
    else:
        r = Rede(nome=f"Rede Ficticia {rede}", uf="SP")
        db.add(r)
        db.flush()
        for modulo in desligados:
            db.add(ModuloRede(rede_id=r.id, modulo=modulo, ativo=False))
        escola.rede_id = r.id
    db.commit()


def _gravado() -> dict:
    return json.loads(ARQUIVO.read_text(encoding="utf-8")) if ARQUIVO.exists() else {}


def _conferir(chave: str, respostas: list) -> None:
    if REGRAVAR:
        dados = _gravado()
        dados[chave] = respostas
        ARQUIVO.write_text(json.dumps(dados, ensure_ascii=False, indent=1, sort_keys=True)
                           + "\n", encoding="utf-8", newline="\n")
        pytest.skip("regravado")
    assert chave in _gravado(), f"estado {chave} sem resposta gravada: regravar"
    assert respostas == _gravado()[chave]


# ---------------------------------------------------------------------------
# GET /status
# ---------------------------------------------------------------------------
_JA_TEM_REDE = {"configurada_em_dia", "fora_do_plano"}   # no dourado do /status
STATUS = {f"{nome}@rede_toda": (nome, "rede_toda")
          for nome in cenarios.CENARIOS if nome not in _JA_TEM_REDE}
STATUS.update({
    "configurada_em_dia@avulsa": ("configurada_em_dia", "avulsa"),
    "configurada_em_dia@rede_sem_leitura": ("configurada_em_dia", "rede_sem_leitura"),
    "dados_velhos@rede_sem_leitura": ("dados_velhos", "rede_sem_leitura"),
    "dados_velhos@rede_sem_matematica": ("dados_velhos", "rede_sem_matematica"),
    "fila_parada@rede_sem_matematica": ("fila_parada", "rede_sem_matematica"),
    "agendador_ligado@rede_sem_matematica": ("agendador_ligado", "rede_sem_matematica"),
})


@pytest.mark.parametrize("estado", list(STATUS))
def test_status_de_escola_de_rede_devolve_o_json_gravado(estado, db, escola_completa,
                                                         cliente_global, monkeypatch):
    cenario, rede = STATUS[estado]
    cenarios.congelar(monkeypatch)
    eid = cenarios.CENARIOS[cenario](db, escola_completa, monkeypatch)
    na_rede(db, eid, rede)
    _conferir(f"status/{estado}", _duas_leituras_status(cliente_global, eid))


def _duas_leituras_status(cliente, eid: int) -> list:
    respostas = []
    for _ in range(2):
        r = cliente.get(f"/api/v1/escolas/{eid}/sync/status")
        assert r.status_code == 200, r.text
        respostas.append(r.json())
    return respostas


# ---------------------------------------------------------------------------
# POST /agora
# ---------------------------------------------------------------------------
def preparar_agora(db, base, monkeypatch, caso: str) -> int:
    """Escola do fixture com credencial legível nas duas plataformas (ou não, nos
    casos de credencial), sem execução ativa; nenhuma thread dispara."""
    cenarios.congelar(monkeypatch)
    monkeypatch.setattr(service, "disparar_em_thread", lambda _id: None)
    eid = base["escola"].id
    if caso == "ilegivel":
        cenarios._cred(db, eid, "elefante", legivel=False)
        cenarios._cred(db, eid, "matific", legivel=False)
    elif caso != "sem_credencial":
        cenarios._cred(db, eid, "elefante")
        cenarios._cred(db, eid, "matific")
    cenarios._execucao(db, eid, "elefante", "concluida", horas=26, qtd_alunos=3)
    cenarios._execucao(db, eid, "matific", "concluida", horas=30, qtd_alunos=3)
    db.commit()
    return eid


AGORA_CASOS = {
    "cria_e_reaproveita": ("", 2),
    "matific_pedido": ("?plataforma=matific", 1),
    "periodo": ("?inicio=2026-10-01&fim=2026-10-07", 1),
    "ilegivel": ("", 1),
    "sem_credencial": ("", 1),
}
AGORA = {f"{caso}@{rede}": (caso, rede) for caso in AGORA_CASOS
         for rede in ("avulsa", "rede_toda", "rede_sem_matematica")}


def _normalizar(corpo):
    """Toda execução devolvida foi criada por um pedido do teste (o preparo não deixa
    nenhuma ativa): o ``created_at`` dela vem do relógio real e vira um marcador,
    depois de conferir que é uma data."""
    if not isinstance(corpo, list):
        return corpo
    saida = []
    for item in corpo:
        item = dict(item)
        datetime.fromisoformat(item["created_at"])
        item["created_at"] = CRIADA_AGORA
        saida.append(item)
    return saida


def pedir_agora(cliente, eid: int, sufixo: str = ""):
    return cliente.post(f"/api/v1/escolas/{eid}/sync/agora{sufixo}")


@pytest.mark.parametrize("estado", list(AGORA))
def test_agora_de_escola_de_rede_devolve_o_json_gravado(estado, db, escola_completa,
                                                        cliente_global, monkeypatch):
    caso, rede = AGORA[estado]
    sufixo, vezes = AGORA_CASOS[caso]
    eid = preparar_agora(db, escola_completa, monkeypatch, caso)
    na_rede(db, eid, rede)
    respostas = []
    for _ in range(vezes):
        r = pedir_agora(cliente_global, eid, sufixo)
        respostas.append([r.status_code, _normalizar(r.json())])
    # O que ficou no banco também é o mesmo: as execuções e os parâmetros delas.
    db.expire_all()
    banco = [[ex.plataforma, ex.status, ex.origem, ex.parametros]
             for ex in db.query(SincronizacaoExecucao).filter_by(escola_id=eid)
             .order_by(SincronizacaoExecucao.id)]
    credenciais = sorted(c.plataforma for c in db.query(PlataformaCredencial)
                         .filter_by(escola_id=eid))
    _conferir(f"agora/{estado}", respostas + [banco, credenciais])
