"""MÉDIO-1 do RC: a execução da sincronização NÃO pode segurar uma transação
de banco aberta durante o FETCH externo do conector — em Postgres gerenciado,
idle-in-transaction derruba a conexão no meio da coleta.

Prova: com um conector fake, no INÍCIO do fetch e APÓS um log de fetch, a sessão
não tem transação aberta; e a persistência segue transacional.
"""
from sqlalchemy import func, select, update

from app.models.sincronizacao import SincronizacaoExecucao, SincronizacaoLog
from app.sync import service, vault
from app.sync.interfaces import Credenciais


def test_contexto_fetch_autonomo_nao_segura_transacao(db, escola_completa):
    escola = escola_completa["escola"]
    ex = service.enfileirar(db, escola.id, "matific", origem="teste")
    db.commit()

    # Log da fase de fetch COMMITA — não deixa transação aberta durante a I/O.
    service._contexto(db, ex, autonomo=True).log("download", "info", "baixando")
    assert not db.in_transaction()

    assert db.execute(
        select(func.count()).select_from(SincronizacaoLog)
        .where(SincronizacaoLog.mensagem == "baixando")).scalar_one() == 1


def test_contexto_persistencia_participa_da_transacao(db, escola_completa):
    escola = escola_completa["escola"]
    ex = service.enfileirar(db, escola.id, "matific", origem="teste")
    db.commit()

    # Log da fase de persistência é transacional (atomicidade da importação).
    service._contexto(db, ex, autonomo=False).log("parser", "info", "lendo")
    assert db.in_transaction()
    db.rollback()


def test_executar_nao_deixa_transacao_aberta_durante_o_fetch(
        db, escola_completa, monkeypatch):
    escola = escola_completa["escola"]
    vault.salvar_credencial(db, escola.id, "matific",
                            Credenciais(usuario="prof@x", senha="s3nh4"))
    ex = service.enfileirar(db, escola.id, "matific", origem="teste")
    db.commit()

    vistos: dict[str, bool] = {}

    class ConectorFake:
        plataforma = "matific"
        versao = "test"

        async def sincronizar(self, cred, contexto):
            # No início do fetch NÃO pode haver transação aberta (o pre-commit
            # a fechou e o contexto foi construído antes, sem reabri-la).
            vistos["no_inicio"] = db.in_transaction()
            contexto.log("download", "info", "coletando")
            # Log de fetch é autônomo → não reabre transação presa.
            vistos["apos_log"] = db.in_transaction()
            return []  # sem arquivos → status sem_dados

    monkeypatch.setattr(service.connectors, "obter", lambda _p: ConectorFake())

    res = service.executar(db, ex)

    assert vistos["no_inicio"] is False
    assert vistos["apos_log"] is False
    assert res.status == "sem_dados"


def test_finalizar_orfas_no_boot_libera_execucao_presa(db, escola_completa):
    """Um redeploy no MEIO de uma sync deixa a execução presa em 'executando' e
    trava a escola (uq_sync_exec_ativa). No boot, finalizar_orfas_no_boot marca a
    órfã como 'erro' na hora — sem esperar o timeout de 30 min — e uma nova
    sincronização já pode ser enfileirada (instância única: nada roda ao subir)."""
    escola = escola_completa["escola"]
    ex = service.enfileirar(db, escola.id, "elefante", origem="teste")
    # Simula a sync que começou e cujo worker morreu no restart (fica órfã).
    db.execute(
        update(SincronizacaoExecucao)
        .where(SincronizacaoExecucao.id == ex.id)
        .values(status="executando", iniciada_em=service._agora()))
    db.commit()

    liberadas = service.finalizar_orfas_no_boot(db)
    assert liberadas == 1

    db.refresh(ex)
    assert ex.status == "erro"

    # Trava liberada: dá para enfileirar de novo (execução NOVA, não a órfã).
    nova = service.enfileirar(db, escola.id, "elefante", origem="teste")
    assert nova.id != ex.id
    assert nova.status == "fila"


def test_finalizar_orfas_no_boot_sem_orfas_e_noop(db, escola_completa):
    """Sem execuções presas, o boot não mexe em nada (idempotente/barato)."""
    escola = escola_completa["escola"]
    ex = service.enfileirar(db, escola.id, "elefante", origem="teste")  # fica 'fila'
    db.commit()

    assert service.finalizar_orfas_no_boot(db) == 0

    db.refresh(ex)
    assert ex.status == "fila"  # a fila NÃO é órfã — não pode ser tocada
