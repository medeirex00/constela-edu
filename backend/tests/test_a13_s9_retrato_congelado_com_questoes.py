"""A13 × S9: a coleta em que a plataforma NÃO mandou as questões não encerra a
pendência cujo retrato guardado TEM questões.

Cenário (revisão de integração, 10/11): a ficha da criança tem a conta 801 do
Elefante e um retrato de 10 dias atrás (100 questões, 80 certas). Há 5 dias, o
relatório da turma, importado à mão com a data dele, trouxe "IARA F" (nome
abreviado, sem a conta) com 120/90: sem candidato na sala do relatório, a linha foi
para a fila por NOME (A2, ``nome_incompleto``), guardando esse retrato. Hoje a
sincronização traz a conta 801 com o mesmo nome, mas a API deixou de mandar
``responses``/``approvedResponses`` (S9).

Antes: a linha da conta respondia a pendência por nome (A13) e
``_linha_substitui_o_congelado`` só olhava o tipo de dado e a data — encerrava a
pendência sem aplicar o retrato guardado. Com ``sem_retrato_repetido`` nada novo
era gravado (livros e tempo iguais), e a medida de 120/90 sumia: o Relatório por
Período do intervalo ficava sem número, quando dava para medir 20 questões.

Agora a linha que não traz as questões não substitui um retrato guardado que as
traz: a pendência continua na fila e, resolvida pelo gestor, o retrato entra.
Dados FICTÍCIOS.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import Importacao, RevisaoIdentidade, SnapshotElefante
from app.models.plataformas import IMPORTACAO_SEM_QUESTOES
from app.services import relatorios_periodo as rp
from app.sync import fuso, orchestrator
from app.sync.interfaces import ArquivoObtido
from tests.sync_integridade_comum import (aluno, aplicar, elefante_resumo, sem_disco, turma,
                                          vincular)

K = "3 ANO A TARDE ANUAL (300396804)"   # a sala do Elefante: o 3º Ano A da escola
NOME = "Iara Fictoni Modesto"


def _arquivo_s9(alunos: list[dict]) -> ArquivoObtido:
    """O relatório da turma SEM ``responses``/``approvedResponses`` (S9)."""
    payload = {"courseId": 700001,
               "courseSchoolDescriptors": {"courseName": K, "schoolName": "ESCOLA FICTICIA"},
               "students": [{"totalReadTime": 600, **a} for a in alunos]}
    return ArquivoObtido(conteudo=json.dumps(payload).encode("utf-8"),
                         nome_arquivo="elefante_ficticio.json", plataforma="elefante",
                         content_type=orchestrator.CT_ELEFANTE_API, formato_hint="resumo")


def _cena(db, cliente, escola_completa) -> dict:
    """A ficha (no 3º Ano B, com a conta 801 e o retrato de 10 dias atrás) e a
    pendência por NOME aberta pela importação manual de 5 dias atrás."""
    esc = escola_completa["escola"]
    t_b = turma(db, esc.id, "3º Ano B", "3º Ano")
    iara = aluno(db, esc.id, t_b, NOME, da_lista_piloto=True)
    vincular(db, esc.id, iara.id, "elefante", "801")
    agora = datetime.now(timezone.utc).replace(microsecond=0)
    d10 = agora - timedelta(days=10)
    imp = Importacao(escola_id=esc.id, usuario_id=None, plataforma="elefante", tipo="pdf",
                     arquivo_original=None, qtd_alunos=1, qtd_erros=0, tempo_ms=0,
                     created_at=d10.replace(tzinfo=None), status="concluida")
    db.add(imp)
    db.flush()
    db.add(SnapshotElefante(escola_id=esc.id, aluno_id=iara.id, importacao_id=imp.id,
                            data_referencia=d10.replace(tzinfo=None), livros_unicos=3,
                            tempo_leitura_min=10, questoes_tentativas=100,
                            questoes_acertos=80, livros_por_nivel={}))
    db.commit()

    # O relatório da turma, à mão, com a data dele: "IARA F" sem a conta.
    d5 = agora - timedelta(days=5)
    r = cliente.post(f"/api/v1/escolas/{esc.id}/importacoes/confirmar", json={
        "plataforma": "elefante", "formato": "resumo", "tipo": "texto",
        "data_referencia": d5.isoformat(), "recalcular": False,
        "linhas": [{"nome": "IARA F", "dados": {
            "turma_relatorio": K, "livros_unicos": 3, "tempo_leitura_min": 10,
            "questoes_tentativas": 120, "questoes_acertos": 90}}]})
    assert r.status_code == 200, r.text
    db.expire_all()
    [rev] = db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == esc.id,
        RevisaoIdentidade.status == "pendente")).scalars().all()
    # Pendência por NOME (sem a conta), sem outra ficha como candidata: a que o A13
    # deixa a linha com a conta encerrar.
    assert rev.id_externo is None and rev.chave_identidade.startswith("elefante|nome:")
    assert all(c.get("aluno_id") in (None, iara.id) for c in rev.candidatos or [])
    assert rev.linhas[0]["questoes_tentativas"] == 120
    return {"escola": esc, "iara": iara.id, "rev": rev.id, "d10": d10}


def _retratos(db, aluno_id):
    return db.execute(
        select(SnapshotElefante.livros_unicos, SnapshotElefante.questoes_tentativas,
               SnapshotElefante.questoes_acertos, Importacao.status)
        .join(Importacao, Importacao.id == SnapshotElefante.importacao_id)
        .where(SnapshotElefante.aluno_id == aluno_id)
        .order_by(SnapshotElefante.data_referencia, SnapshotElefante.id)).all()


@pytest.mark.parametrize("livros", [3, 4], ids=["nada_novo_gravado", "livro_novo"])
def test_coleta_sem_questoes_nao_encerra_a_pendencia_com_questoes(
        cliente, db, escola_completa, monkeypatch, livros):
    sem_disco(monkeypatch)
    c = _cena(db, cliente, escola_completa)

    res = aplicar(db, c["escola"], _arquivo_s9([
        {"studentId": 801, "studentName": "IARA F", "totalBooksRead": livros}]))

    assert db.get(Importacao, res["importacao_id"]).status == IMPORTACAO_SEM_QUESTOES
    rev = db.get(RevisaoIdentidade, c["rev"])
    assert rev.status == "pendente", (
        "a coleta sem as questões encerrou a pendência e descartou o retrato guardado "
        f"(120/90): {rev.resolucao}")
    assert rev.linhas[0]["questoes_tentativas"] == 120


def test_resolvida_depois_a_medida_guardada_entra_no_relatorio(
        cliente, db, escola_completa, monkeypatch):
    """O caminho inteiro: coleta S9 sem nada novo (o retrato não é repetido), o
    gestor resolve a pendência e o Relatório por Período mede as 20 questões entre o
    retrato de 10 dias atrás e o guardado na pendência."""
    sem_disco(monkeypatch)
    c = _cena(db, cliente, escola_completa)
    esc = c["escola"]
    aplicar(db, esc, _arquivo_s9([
        {"studentId": 801, "studentName": "IARA F", "totalBooksRead": 3}]))
    assert _retratos(db, c["iara"]) == [(3, 100, 80, "concluida")]   # nada repetido

    r = cliente.post(f"/api/v1/escolas/{esc.id}/importacoes/revisoes/{c['rev']}/resolver",
                     json={"aluno_id": c["iara"]})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert _retratos(db, c["iara"]) == [(3, 100, 80, "concluida"), (3, 120, 90, "concluida")]

    hoje = fuso.hoje_local()
    rel = rp.gerar(db, esc.id, preset="personalizado", plataformas=("elefante",),
                   inicio=fuso.para_local(c["d10"]).date(), fim=hoje, hoje=hoje)["elefante"]
    assert (rel["questoes_tentativas"], rel["questoes_acertos"]) == (20, 10)


def test_coleta_com_as_questoes_continua_encerrando_a_pendencia(
        cliente, db, escola_completa, monkeypatch):
    """Controle: a coleta que TRAZ as questões (de hoje, mais nova que a guardada)
    substitui o retrato guardado e encerra a pendência por nome, como sempre (A13)."""
    sem_disco(monkeypatch)
    c = _cena(db, cliente, escola_completa)
    aplicar(db, c["escola"], elefante_resumo(K, [
        {"studentId": 801, "studentName": "IARA F", "totalBooksRead": 4,
         "responses": 130, "approvedResponses": 95}]))
    rev = db.get(RevisaoIdentidade, c["rev"])
    assert rev.status == "resolvida" and rev.aluno_escolhido_id == c["iara"]
    assert rev.resolucao["automatica"] is True and rev.resolucao["pendencia_por_nome"] is True
    assert _retratos(db, c["iara"])[-1] == (4, 130, 95, "concluida")
