"""Fundir duplicatas em lote: a falha de um par vai para o log e não culpa os dados.

O DEFEITO (OBSERVABILIDADE-2). Em ``alunos_dedup.aplicar_deduplicacao`` cada par
roda num SAVEPOINT e o ``except Exception`` só punha na resposta
"erro ao fundir (dados inconsistentes)": nenhum log, nenhum tipo do erro, nada
para o Sentry (a rota responde 200, a rede de segurança do middleware não vê). Um
defeito de código, um lock_timeout ou um deadlock virava "culpa dos dados da
criança" e ninguém conseguia diagnosticar.

O CONSERTO: ``logger.exception`` com só os ids (escola, ficha que fica, ficha que
sai) e um motivo que não culpa os dados. Dados fictícios.
"""
import logging

from app.models import Aluno, Matricula
from app.services import alunos_fusao

API = "/api/v1"


def _aluno(db, escola_id, nome, turma_id):
    a = Aluno(escola_id=escola_id, nome=nome, status="ativo", ficha={})
    db.add(a)
    db.flush()
    db.add(Matricula(escola_id=escola_id, aluno_id=a.id, turma_id=turma_id, ano_letivo=2026))
    db.commit()
    return a


def test_falha_da_fusao_no_lote_vai_para_o_log_sem_culpar_os_dados(
        cliente, db, escola_completa, monkeypatch, caplog):
    escola_id = escola_completa["escola"].id
    turma_id = escola_completa["turma"].id
    curto = _aluno(db, escola_id, "Yasmin Cecilia Testelli", turma_id)
    longo = _aluno(db, escola_id, "Yasmin Cecilia Testelli Ficticio Sintoni", turma_id)

    def quebra(*_a, **_k):   # defeito de CÓDIGO no meio da fusão (não é dado ruim)
        raise AttributeError("'NoneType' object has no attribute 'escola_id'")

    monkeypatch.setattr(alunos_fusao, "fundir_par", quebra)
    caplog.set_level(logging.DEBUG)
    r = cliente.post(f"{API}/escolas/{escola_id}/alunos/duplicados/corrigir",
                     json={"loser_ids": [curto.id], "confirmacao": "FUNDIR"})
    registros = [(rec.name, rec.levelname, rec.getMessage(), bool(rec.exc_info))
                 for rec in caplog.records]
    print("STATUS", r.status_code, "CORPO", r.json())
    print("REGISTROS_DE_LOG", registros)
    assert r.status_code == 200, r.text

    falhas = r.json()["falhas"]
    assert [f["loser_id"] for f in falhas] == [curto.id]
    assert "dados inconsistentes" not in falhas[0]["motivo"]
    assert "tente de novo" in falhas[0]["motivo"]

    erros = [rec for rec in caplog.records
             if rec.levelno >= logging.WARNING and rec.exc_info]
    assert erros, "a falha da fusão não deixou nenhum log com o erro"
    registro = erros[0]
    assert registro.getMessage() == "fusao_em_lote_falhou"
    assert registro.exc_info[0] is AttributeError
    assert (registro.escola_id, registro.manter_id, registro.remover_id) == (
        escola_id, longo.id, curto.id)
    # Só ids: o nome da criança não vai para o log.
    assert "Yasmin" not in registro.getMessage()
    assert not any("Yasmin" in str(getattr(registro, campo, ""))
                   for campo in ("escola_id", "manter_id", "remover_id"))
