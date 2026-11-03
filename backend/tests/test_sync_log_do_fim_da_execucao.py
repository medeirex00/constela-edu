"""Uma linha no log da APLICAÇÃO por execução de sincronização encerrada.

Lente OBSERVABILIDADE (27/10): o desfecho de cada execução ficava só no banco
(``sincronizacao_logs``, alertas) e nas métricas. Sucesso, 'sem_dados' e as falhas
esperadas do conector (login recusado, HTTP != 200 do Matific, credencial,
timeout, download) não escreviam NENHUMA linha no log de produção; só a exceção
inesperada aparecia. Agora ``service.executar`` escreve, depois do commit final,
``sync_execucao_finalizada``: INFO para 'concluida' com aluno aplicado, WARNING
para o resto, com ids, status, motivo (código), duração e contagem no ``extra``.
Sem PII, sem URL e sem dado da credencial.

Dados FICTÍCIOS, sem rede: conector REAL do Matific com navegador falso
(``tests/_sync_nucleo_fakes``), serviço real (enfileirar → executar).
"""
from __future__ import annotations

import json
import logging

import pytest

from app.core.observabilidade import FormatadorJson
from app.sync import service
from app.sync.connectors import matific as con_matific
from tests._sync_nucleo_fakes import NavMatific, PlacarFake, credencial, instalar, rodar

EVENTO = "sync_execucao_finalizada"
TURMA = "3 ANO A (300396804)"
# Os valores fictícios que ``credencial`` grava no cofre: não podem ir para o log.
USUARIO, SENHA = "robo-ficticio", "valor-ficticio-local"


class NavMatificSenhaRecusada(NavMatific):
    """O Matific mostra o formulário e, depois do envio, a mensagem de erro do login:
    a plataforma recusou a senha (``senha_invalida``)."""

    async def esperar(self, s, timeout_s=20):
        return "logout" not in s                 # o formulário aparece; a área logada não

    async def url_atual(self):
        return "https://www.matific.com/bra/pt-br/login/"

    async def visivel(self, s):
        if "recaptcha" in s or "challenge" in s:
            return False                         # sem CAPTCHA
        return "password" in s.lower() or "login-error" in s


def _linhas_do_fim(caplog, execucao_id):
    return [r for r in caplog.records
            if r.name == "constela.sync" and r.getMessage().startswith(EVENTO)
            and getattr(r, "execucao_id", None) == execucao_id]


# cenário → (status, motivo, nível, alunos aplicados)
CENARIOS = {
    "sucesso": ("concluida", None, logging.INFO, 3),
    "vazio200": ("sem_dados", None, logging.WARNING, 0),
    "http503": ("erro", "falha_download", logging.WARNING, 0),
    "login": ("erro", "senha_invalida", logging.WARNING, 0),
}


@pytest.mark.parametrize("cenario", list(CENARIOS))
def test_fim_de_cada_execucao_deixa_uma_linha_no_log(db, escola_completa, monkeypatch,
                                                     caplog, cenario):
    ec = escola_completa
    eid = ec["escola"].id
    nomes = [a.nome for a in ec["alunos"]]
    credencial(db, eid, "matific")
    placar = PlacarFake()
    if cenario != "vazio200":
        placar.linhas = [(f"u-{i}", nome, TURMA, 40 + i, 10 + i)
                         for i, nome in enumerate(nomes)]
    if cenario == "http503":
        placar.status_ss = 503
    registro = instalar(monkeypatch, placar=placar)
    if cenario == "login":
        registro["matific"] = con_matific.ConectorMatific(
            _fabrica_de(NavMatificSenhaRecusada(placar)))

    with caplog.at_level(logging.INFO, logger="constela.sync"):
        ex, erro = rodar(db, eid, "matific")
    status, motivo, nivel, alunos = CENARIOS[cenario]
    assert erro is None
    assert (ex.status, ex.motivo) == (status, motivo), ex.erro_resumo

    linhas = _linhas_do_fim(caplog, ex.id)
    assert len(linhas) == 1, f"esperava UMA linha {EVENTO} para a execução {ex.id}"
    r = linhas[0]
    assert r.levelno == nivel
    assert r.getMessage() == (f"{EVENTO} execucao={ex.id} escola={eid} plataforma=matific "
                              f"status={status} motivo={motivo or '-'}")
    assert (r.escola_id, r.plataforma, r.status, r.motivo) == (eid, "matific", status, motivo)
    assert r.duracao_ms == ex.duracao_ms and r.duracao_ms is not None
    assert r.alunos_aplicados == alunos

    # Sem PII, sem URL e sem dado da credencial — nem no texto, nem no JSON do Railway.
    saida = r.getMessage() + "\n" + FormatadorJson().format(r)
    json.loads(saida.split("\n", 1)[1])
    proibidos = [USUARIO, SENHA, "http", "matific.com", ec["escola"].nome, TURMA, *nomes,
                 *(n.split()[0] for n in nomes)]
    if ex.erro_resumo:
        proibidos.append(ex.erro_resumo)
    for proibido in proibidos:
        assert proibido not in saida, proibido


def test_falha_ao_escrever_a_linha_nao_afeta_a_execucao(db, escola_completa, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    credencial(db, eid, "matific")
    placar = PlacarFake()
    placar.linhas = [(f"u-{i}", a.nome, TURMA, 40, 10) for i, a in enumerate(ec["alunos"])]
    instalar(monkeypatch, placar=placar)

    def _quebra(*_a, **_kw):
        raise RuntimeError("log quebrado (simulado)")

    monkeypatch.setattr(service.logger, "log", _quebra)
    ex, erro = rodar(db, eid, "matific")
    assert erro is None and ex.status == "concluida" and ex.qtd_alunos == 3
    assert ex.finalizada_em is not None


def _fabrica_de(nav):
    async def fab(**_kw):
        return nav
    return fab
