"""Recálculo institucional PÓS-DEPLOY — preenche as colunas `nota_*_institucional`.

Por que existe
--------------
A migração ``0028_nota_institucional`` acrescenta ``nota_elefante_institucional``
e ``nota_matific_institucional`` em ``notas`` com default 0.0 e SEM backfill
(aditiva, deploy sem efeito colateral). Enquanto uma escola não é recalculada,
a rede lê 0 para ela. Este script roda UMA vez depois do deploy e recalcula
TODAS as escolas, o que preenche as colunas institucionais (e também regrava as
notas locais com o perfil vigente de cada escola — padrão A3 ou personalizado).

Garantias
---------
* IDEMPOTENTE: ``scoring.recalcular_escola`` é determinístico e sobrescreve as
  linhas de ``notas``. Rodar duas vezes dá o mesmo resultado — seguro reexecutar.
* ISOLADO POR ESCOLA: cada escola tem seu próprio ``commit`` (dentro de
  ``recalcular_escola``). Uma escola com dado corrompido é registrada como falha
  e NÃO impede as demais de ficarem corretas.
* NÃO recalcula "a rede": a nota institucional é derivada por escola; a rede só
  agrega o que já está gravado. Não há passo de rede aqui.

Como executar (no ambiente de produção, após o deploy e a migração)
-------------------------------------------------------------------
    python -m scripts.recalcular_institucional            # todas as escolas
    python -m scripts.recalcular_institucional --rede 3   # só a rede 3
    python -m scripts.recalcular_institucional --escola 42  # só a escola 42
    python -m scripts.recalcular_institucional --dry-run   # só conta, não grava
    python -m scripts.recalcular_institucional --pendentes  # só quem falta (ver abaixo)

``--pendentes`` seleciona escolas com alguma Nota do ano ativo (aluno ativo e
matriculado) SEM carimbo institucional OU carimbada com uma versão de dificuldade
DIFERENTE da vigente (ex.: ``elefante_dificuldade_v1`` quando a vigente é a v2).
Trocar a versão da régua NUNCA recalcula nada sozinho: as notas antigas continuam
valendo (e agregadas pela rede) até este script ser rodado de forma explícita.

Recomendado rodar em janela de baixo tráfego: cada escola pega um lock
transacional curto (o mesmo do recálculo normal), então importações concorrentes
apenas esperam, não corrompem.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models import Aluno, Escola, Nota  # noqa: E402
from app.services import dificuldade_livro, rede, scoring  # noqa: E402


def escolas_com_versao_desatualizada(db: Session) -> list[int]:
    """Escolas com alguma Nota do ano ativo carimbada com versão de dificuldade
    DIFERENTE da vigente. Mesmo recorte de ``rede.escolas_com_notas_pendentes``
    (aluno ativo, matriculado no ano ativo): o recálculo só regrava essas linhas,
    então depois dele a escola sai da seleção (IDEMPOTENTE)."""
    carimbo = rede._CARIMBO_INSTITUCIONAL
    linhas = db.execute(
        select(Nota.escola_id).distinct()
        .join(Aluno, Aluno.id == Nota.aluno_id)
        .join(Escola, Escola.id == Nota.escola_id)
        .where(Nota.ano_letivo == Escola.ano_letivo_ativo,
               Aluno.status == "ativo",
               rede._matriculado_no_ano_ativo(),
               carimbo.isnot(None),
               carimbo != dificuldade_livro.VERSAO_VIGENTE)
    ).all()
    return sorted(int(escola_id) for (escola_id,) in linhas)


def escolas_pendentes(db: Session) -> list[int]:
    """Sem carimbo (``rede.escolas_com_notas_pendentes``) ∪ versão desatualizada."""
    return sorted(set(rede.escolas_com_notas_pendentes(db))
                  | set(escolas_com_versao_desatualizada(db)))


def main() -> int:
    parser = argparse.ArgumentParser(description="Recálculo institucional pós-deploy.")
    parser.add_argument("--rede", type=int, default=None, help="recalcular só as escolas desta rede")
    parser.add_argument("--escola", type=int, default=None, help="recalcular só esta escola")
    parser.add_argument("--dry-run", action="store_true", help="apenas listar, sem recalcular")
    parser.add_argument("--pendentes", action="store_true",
                        help="só escolas com alguma Nota do ano ativo SEM o carimbo institucional "
                             "(a rede não as agrega) ou carimbada com versão de dificuldade "
                             f"diferente da vigente ({dificuldade_livro.VERSAO_VIGENTE})")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        consulta = select(Escola.id, Escola.nome).order_by(Escola.id)
        if args.escola is not None:
            consulta = consulta.where(Escola.id == args.escola)
        elif args.rede is not None:
            consulta = consulta.where(Escola.rede_id == args.rede)
        if args.pendentes:
            # IDEMPOTENTE: depois de recalculada, a escola some desta seleção.
            # Sem carimbo institucional OU carimbada com versão ≠ da vigente.
            pendentes = escolas_pendentes(db)
            consulta = consulta.where(Escola.id.in_(pendentes or [-1]))
        escolas = db.execute(consulta).all()

        print(f"Escolas a recalcular: {len(escolas)}"
              + (" (DRY-RUN, nada será gravado)" if args.dry_run else ""))
        total_alunos = 0
        falhas: list[tuple[int, str, str]] = []
        for i, (escola_id, nome) in enumerate(escolas, start=1):
            if args.dry_run:
                print(f"  [{i}/{len(escolas)}] escola {escola_id} — {nome}")
                continue
            try:
                n = scoring.recalcular_escola(db, escola_id)
                total_alunos += n
                print(f"  [{i}/{len(escolas)}] escola {escola_id} — {nome}: {n} aluno(s)")
            except Exception as erro:  # noqa: BLE001 — uma escola ruim não derruba o lote
                db.rollback()
                falhas.append((escola_id, nome, str(erro)[:200]))
                print(f"  [{i}/{len(escolas)}] escola {escola_id} — {nome}: FALHOU ({erro})")

        print("\nResumo:")
        print(f"  escolas processadas: {len(escolas)}")
        print(f"  alunos recalculados: {total_alunos}")
        print(f"  falhas: {len(falhas)}")
        for escola_id, nome, erro in falhas:
            print(f"    - escola {escola_id} ({nome}): {erro}")
        return 1 if falhas else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
