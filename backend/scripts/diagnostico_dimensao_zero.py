"""Diagnóstico READ-ONLY: quantos alunos aparecem com UMA dimensão em 0 por AUSÊNCIA
de snapshot (o retrato do bug HELOISA/TAUFIK) e quantos é 0 legítimo.

NÃO grava nada. NÃO chama plataforma. Só lê o banco: para cada aluno ATIVO
matriculado no ANO LETIVO ATIVO, verifica se existe SnapshotMatific e SnapshotElefante.

As três semânticas do zero (spec §12.4):
  * AMBAS ausentes      -> aluno sem nenhuma plataforma (0/0 legítimo);
  * SÓ Matific presente -> Leitura 0 é ausência (candidato ao bug se ele LÊ no Elefante);
  * SÓ Elefante presente-> Matific 0 é ausência (candidato ao bug — é o caso HELOISA);
  * AMBAS presentes     -> completo.

O "candidato ao bug" (uma dimensão presente, outra ausente) é o que a correção do
pipeline ataca: nome do export que é SUBCONJUNTO do nome da Lista Piloto ia a REVISÃO e
o snapshot daquela dimensão nunca era criado. Para saber QUAL desses é atividade-real-
não-importada (bug) vs nunca-usou-a-plataforma (legítimo), rode a análise do import
(prévia) sobre o arquivo/relatório da plataforma — este script mostra a ESCALA e a
LISTA de afetados por turma, para o dono validar com dado real (sem inventar número).

Uso (produção, read-only):
    python -m scripts.diagnostico_dimensao_zero                 # todas as escolas
    python -m scripts.diagnostico_dimensao_zero --escola 42     # uma escola
    python -m scripts.diagnostico_dimensao_zero --rede 3        # uma rede
    python -m scripts.diagnostico_dimensao_zero --escola 42 --listar 40  # + lista
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Aluno, Escola, LogAuditoria, Matricula, SnapshotElefante, SnapshotMatific, Turma,
)


def _subconjuntos_vinculados(db, escola_id: int) -> list[tuple]:
    """Lista os vínculos automáticos por SUBCONJUNTO (correspondencia="parcial") —
    exatamente os que a correção nova cria. É a LISTA para o dono validar/reverter:
    cada um casou o nome de plataforma (subconjunto) ao ÚNICO candidato da turma."""
    logs = db.execute(
        select(LogAuditoria).where(LogAuditoria.acao == "aluno.vinculado_auto",
                                   LogAuditoria.escola_id == escola_id)
        .order_by(LogAuditoria.created_at.desc())
    ).scalars().all()
    out = []
    for lg in logs:
        d = lg.detalhes or {}
        if d.get("correspondencia") == "parcial":
            out.append((d.get("origem"), d.get("aluno"), d.get("turma"),
                        lg.entidade_id, lg.created_at))
    return out


def _ids_com_snapshot(db, escola_id: int, modelo) -> set[int]:
    return set(db.execute(
        select(modelo.aluno_id).where(modelo.escola_id == escola_id).distinct()
    ).scalars().all())


def _diagnostico_escola(db, escola_id: int, nome: str, ano: int, listar: int) -> dict:
    # alunos ATIVOS matriculados no ano ativo (o conjunto PONTUADO do ranking)
    linhas = db.execute(
        select(Aluno.id, Aluno.nome, Turma.nome)
        .join(Matricula, Matricula.aluno_id == Aluno.id)
        .join(Turma, Turma.id == Matricula.turma_id)
        .where(Aluno.escola_id == escola_id, Aluno.status == "ativo",
               Matricula.ano_letivo == ano)
    ).all()
    com_mat = _ids_com_snapshot(db, escola_id, SnapshotMatific)
    com_ele = _ids_com_snapshot(db, escola_id, SnapshotElefante)

    total = len(linhas)
    so_matific, so_elefante, ambas, nenhuma = [], [], 0, 0
    for aid, anome, tnome in linhas:
        m, e = aid in com_mat, aid in com_ele
        if m and e:
            ambas += 1
        elif m and not e:
            so_matific.append((anome, tnome))       # Leitura 0 (ausente)
        elif e and not m:
            so_elefante.append((anome, tnome))       # Matific 0 (ausente) — caso HELOISA
        else:
            nenhuma += 1

    print(f"\n== Escola {escola_id} — {nome} (ano {ano}) ==")
    print(f"  alunos ativos matriculados ........ {total}")
    print(f"  com Matific (aferido matemática) .. {len(com_mat & {l[0] for l in linhas})}")
    print(f"  com Elefante (aferido leitura) .... {len(com_ele & {l[0] for l in linhas})}")
    print(f"  AMBAS as dimensões ................ {ambas}")
    print(f"  SÓ Matific  -> Leitura 0 (ausente) . {len(so_matific)}")
    print(f"  SÓ Elefante -> Matific 0 (ausente) . {len(so_elefante)}   <- retrato do caso HELOISA")
    print(f"  nenhuma dimensão (0/0) ............ {nenhuma}")
    afetados = len(so_matific) + len(so_elefante)
    print(f"  --> UMA dimensão presente, outra AUSENTE (candidatos ao bug): {afetados}")

    if listar:
        def _amostra(rotulo, itens):
            if not itens:
                return
            print(f"  {rotulo} (até {listar}):")
            for anome, tnome in sorted(itens)[:listar]:
                print(f"     - {anome}  [{tnome}]")
        _amostra("SÓ Elefante (Matific 0)", so_elefante)
        _amostra("SÓ Matific (Leitura 0)", so_matific)

    return {"total": total, "ambas": ambas, "so_matific": len(so_matific),
            "so_elefante": len(so_elefante), "nenhuma": nenhuma}


def main() -> int:
    p = argparse.ArgumentParser(description="Diagnóstico read-only de dimensão 0 por ausência de snapshot.")
    p.add_argument("--escola", type=int, default=None)
    p.add_argument("--rede", type=int, default=None)
    p.add_argument("--listar", type=int, default=0, help="listar até N nomes por categoria")
    p.add_argument("--subconjunto", action="store_true",
                   help="listar os vínculos automáticos por SUBCONJUNTO (para validar/reverter)")
    args = p.parse_args()

    db = SessionLocal()
    try:
        consulta = select(Escola.id, Escola.nome, Escola.ano_letivo_ativo).order_by(Escola.id)
        if args.escola is not None:
            consulta = consulta.where(Escola.id == args.escola)
        elif args.rede is not None:
            consulta = consulta.where(Escola.rede_id == args.rede)
        escolas = db.execute(consulta).all()

        tot = {"total": 0, "ambas": 0, "so_matific": 0, "so_elefante": 0, "nenhuma": 0}
        total_subconj = 0
        for escola_id, nome, ano in escolas:
            r = _diagnostico_escola(db, escola_id, nome, ano or 0, args.listar)
            for k in tot:
                tot[k] += r[k]
            if args.subconjunto:
                subs = _subconjuntos_vinculados(db, escola_id)
                total_subconj += len(subs)
                if subs:
                    print(f"  vínculos por SUBCONJUNTO (validar/reverter): {len(subs)}")
                    for origem, aluno, turma, aid, quando in subs:
                        print(f"     - '{origem}' -> '{aluno}' [{turma}] aluno_id={aid} ({quando})")

        print("\n===== TOTAL =====")
        print(f"  alunos ................ {tot['total']}")
        print(f"  AMBAS ................. {tot['ambas']}")
        print(f"  SÓ Matific (Leit. 0) .. {tot['so_matific']}")
        print(f"  SÓ Elefante (Mat. 0) .. {tot['so_elefante']}")
        print(f"  nenhuma ............... {tot['nenhuma']}")
        print(f"  candidatos ao bug ..... {tot['so_matific'] + tot['so_elefante']}")
        if args.subconjunto:
            print(f"  vínculos p/ subconjunto {total_subconj}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
