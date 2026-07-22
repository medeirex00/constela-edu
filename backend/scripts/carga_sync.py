"""Teste de carga/concorrência da FILA de sincronização.

Simula N escolas com execuções na fila e K workers concorrentes reivindicando-as,
para medir sob o banco REAL (Postgres do staging): throughput, contenção do claim
atômico e — o mais importante — DUPLICAÇÃO (que precisa ser ZERO).

Mede a mecânica da FILA (enfileirar → claim → concluir), não o download em si
(que envolve navegador/HTTP externo e não deve tocar Matific/Elefante num teste
de carga). É a camada onde a escala municipal vive ou morre.

USO (aponte para o STAGING, NUNCA para produção):
    DATABASE_URL="postgresql+psycopg://.../staging" \
      python backend/scripts/carga_sync.py --escolas 50 --workers 4 --go

Segurança:
  * cria escolas descartáveis com prefixo CARGA_TESTE_ e as APAGA no fim
    (só mexe no que criou);
  * exige --go; sem a flag, só imprime o que faria;
  * RECUSA rodar se o banco tiver escolas de verdade além das de carga, a menos
    que --permitir-dados-reais seja passado (proteção contra apontar p/ produção).
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

# Permite rodar como `python backend/scripts/carga_sync.py` (coloca backend/ no path).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, func, select, update  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models import Escola, SincronizacaoExecucao  # noqa: E402

PREFIXO = "CARGA_TESTE_"


def _agora():
    return datetime.now(timezone.utc)


def _semear(n_escolas: int) -> list[int]:
    """Cria N escolas descartáveis, cada uma com 1 execução na fila. Devolve os
    ids das execuções."""
    db = SessionLocal()
    exec_ids: list[int] = []
    try:
        for i in range(n_escolas):
            escola = Escola(nome=f"{PREFIXO}{i:04d}", ano_letivo_ativo=2026)
            db.add(escola)
            db.flush()
            ex = SincronizacaoExecucao(
                escola_id=escola.id, plataforma="matific",
                origem="scheduler", status="fila")
            db.add(ex)
            db.flush()
            exec_ids.append(ex.id)
        db.commit()
    finally:
        db.close()
    return exec_ids


def _limpar() -> int:
    """Apaga TODAS as escolas de carga (cascata leva as execuções)."""
    db = SessionLocal()
    try:
        ids = [e.id for e in db.execute(
            select(Escola).where(Escola.nome.like(f"{PREFIXO}%"))).scalars()]
        if ids:
            db.execute(delete(SincronizacaoExecucao)
                       .where(SincronizacaoExecucao.escola_id.in_(ids)))
            db.execute(delete(Escola).where(Escola.id.in_(ids)))
            db.commit()
        return len(ids)
    finally:
        db.close()


def _worker(claimed: list[int], lock: threading.Lock) -> None:
    """Reivindica execuções até a fila esvaziar. Cada claim é o UPDATE atômico
    condicional de service.executar."""
    db = SessionLocal()
    try:
        while True:
            candidatos = db.execute(
                select(SincronizacaoExecucao.id)
                .where(SincronizacaoExecucao.status == "fila")
                .order_by(SincronizacaoExecucao.id).limit(5)).scalars().all()
            if not candidatos:
                return
            for eid in candidatos:
                venceu = db.execute(
                    update(SincronizacaoExecucao)
                    .where(SincronizacaoExecucao.id == eid,
                           SincronizacaoExecucao.status == "fila")
                    .values(status="concluida", iniciada_em=_agora(),
                            finalizada_em=_agora())).rowcount
                db.commit()
                if venceu:
                    with lock:
                        claimed.append(eid)
    finally:
        db.close()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--escolas", type=int, default=10)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--go", action="store_true", help="executa de fato")
    p.add_argument("--permitir-dados-reais", action="store_true",
                   help="NÃO usar em produção — desativa a proteção")
    args = p.parse_args()

    db = SessionLocal()
    reais = db.execute(
        select(func.count()).select_from(Escola)
        .where(~Escola.nome.like(f"{PREFIXO}%"))).scalar_one()
    db.close()

    print(f"[carga] escolas={args.escolas} workers={args.workers} "
          f"| escolas reais no banco={reais}")
    if reais > 0 and not args.permitir_dados_reais:
        print("[carga] ABORTADO: há escolas REAIS neste banco. Aponte para o "
              "STAGING (banco descartável) ou use --permitir-dados-reais se tiver "
              "CERTEZA de que não é produção.")
        return 2
    if not args.go:
        print("[carga] simulação (sem --go): nada foi criado. Rode com --go.")
        return 0

    _limpar()  # começa limpo
    try:
        t0 = time.monotonic()
        esperados = _semear(args.escolas)
        t_semear = time.monotonic() - t0

        claimed: list[int] = []
        lock = threading.Lock()
        t0 = time.monotonic()
        threads = [threading.Thread(target=_worker, args=(claimed, lock))
                   for _ in range(args.workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        t_proc = time.monotonic() - t0

        duplicadas = len(claimed) - len(set(claimed))
        faltando = set(esperados) - set(claimed)
        vazao = len(esperados) / t_proc if t_proc else 0
        print("\n===== RESULTADO =====")
        print(f"execuções enfileiradas : {len(esperados)}")
        print(f"reivindicadas          : {len(claimed)}")
        print(f"DUPLICADAS             : {duplicadas}  (precisa ser 0)")
        print(f"não processadas        : {len(faltando)}  (precisa ser 0)")
        print(f"tempo p/ enfileirar    : {t_semear:.2f}s")
        print(f"tempo p/ processar     : {t_proc:.2f}s")
        print(f"vazão                  : {vazao:.0f} execuções/s")
        ok = duplicadas == 0 and not faltando
        print(f"\nVEREDITO: {'PASSOU' if ok else 'FALHOU'}")
        return 0 if ok else 1
    finally:
        n = _limpar()
        print(f"[carga] limpeza: {n} escola(s) de teste removida(s).")


if __name__ == "__main__":
    sys.exit(main())
