"""Concorrência da fila de sincronização — prova da escala horizontal.

A afirmação de arquitetura é: vários workers/réplicas apontando para o MESMO
banco podem processar a fila sem duplicar sync, porque cada execução é
reivindicada por um UPDATE atômico condicional (compare-and-swap no status).
Estes testes provam a semântica do claim de forma determinística.

NOTA de fidelidade: o SQLite dos testes serializa escritas, então isto valida a
LÓGICA do claim (CAS), não a contenção real do Postgres sob paralelismo. A
medição de throughput/contended sob Postgres é feita pelo harness de carga
(scripts/carga_sync.py) rodado contra o staging.
"""
from sqlalchemy import func, select, update

from app.models import SincronizacaoExecucao
from app.sync import service


def _claim(db, execucao_id: int) -> int:
    """Reproduz o claim atômico de service.executar (linhas 249-258)."""
    n = db.execute(
        update(SincronizacaoExecucao)
        .where(SincronizacaoExecucao.id == execucao_id,
               SincronizacaoExecucao.status == "fila")
        .values(status="executando", iniciada_em=service._agora())).rowcount
    db.commit()
    return n


def test_claim_atomico_tem_um_unico_vencedor(db, escola_completa):
    """Dois workers tentam a MESMA execução: só um reivindica; o outro sai sem
    executar (não duplica a sincronização da escola)."""
    escola = escola_completa["escola"]
    ex = service.enfileirar(db, escola.id, "elefante", origem="teste")
    db.commit()

    assert _claim(db, ex.id) == 1      # 1º worker vence
    assert _claim(db, ex.id) == 0      # 2º worker: não está mais 'fila' → desiste
    db.refresh(ex)
    assert ex.status == "executando"   # exatamente uma execução em andamento


def test_enfileirar_e_idempotente_nao_duplica_tarefa(db, escola_completa):
    """Enfileirar a MESMA escola+plataforma várias vezes (clique duplo, scheduler
    + manual, múltiplas réplicas) NÃO cria execuções duplicadas — resolve a
    'duplicação de tarefas'. Garantido por índice único parcial no banco."""
    escola = escola_completa["escola"]
    for _ in range(5):
        service.enfileirar(db, escola.id, "matific", origem="teste")
    db.commit()

    ativas = db.execute(
        select(func.count()).select_from(SincronizacaoExecucao)
        .where(SincronizacaoExecucao.escola_id == escola.id,
               SincronizacaoExecucao.plataforma == "matific",
               SincronizacaoExecucao.status.in_(("fila", "executando")))).scalar_one()
    assert ativas == 1                     # 5 tentativas → 1 execução ativa


def test_claim_distribui_sem_sobreposicao(db, escola_completa):
    """Várias execuções distintas na fila são reivindicadas por K workers sem
    que nenhuma seja executada duas vezes (distribuição sem sobreposição)."""
    escola = escola_completa["escola"]
    # Duas execuções distintas (o dedup impede repetir a mesma escola+plataforma).
    ids = {service.enfileirar(db, escola.id, "matific", origem="t").id,
           service.enfileirar(db, escola.id, "elefante", origem="t").id}
    db.commit()

    vencidas: list[int] = []
    for _ in range(4):                                  # 4 workers varrem a fila
        for candidato in service.proximas_da_fila(db, limite=100):
            if _claim(db, candidato.id) == 1:
                vencidas.append(candidato.id)

    assert sorted(vencidas) == sorted(ids)              # cada uma 1x, sem duplicar
    assert len(set(vencidas)) == len(ids)
    restantes = db.execute(
        select(func.count()).select_from(SincronizacaoExecucao)
        .where(SincronizacaoExecucao.status == "fila")).scalar_one()
    assert restantes == 0
