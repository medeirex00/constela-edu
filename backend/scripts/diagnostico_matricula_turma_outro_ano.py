"""Diagnóstico SÓ LEITURA: matrículas do ano letivo ATIVO da escola que estão numa turma
de OUTRO ano letivo.

Esse estado vem de antes das travas de escrita: um "Transferir de turma" para uma turma
do ano passado, ou a correção do ano de uma turma que já tinha alunos. Nenhuma porta o
grava mais (cadastro, transferência, /resolver, consolidar e a edição do ano da turma
recusam com 409), mas o que foi gravado antes continua no banco. Os painéis (o cartão da
rede e a Visão da Escola) deixam essas crianças de fora; a escola não as vê em turma
nenhuma do ano. Este script mostra QUANTAS são e EM QUE TURMA, para o dono decidir o
saneamento (mudar a matrícula para a turma certa do ano é ação da escola, não daqui).

NÃO grava nada. NÃO chama plataforma. Só lê o banco. Não escreve o nome de nenhuma
criança: com ``--listar`` sai o id da ficha (para a escola achar a criança na tela).

Para ajudar a datar, cada turma mostra o que o log de auditoria tem dela: a última vez
que o ano letivo da turma foi mudado (``turma.atualizada`` com ``ano_letivo``) e a
última transferência de alunos para ela (``aluno.transferido``).

Uso (produção, só leitura):
    python -m scripts.diagnostico_matricula_turma_outro_ano               # todas as escolas
    python -m scripts.diagnostico_matricula_turma_outro_ano --escola 42   # uma escola
    python -m scripts.diagnostico_matricula_turma_outro_ano --rede 3      # uma rede
    python -m scripts.diagnostico_matricula_turma_outro_ano --listar      # + ids das fichas
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models import Aluno, Escola, LogAuditoria, Matricula, Turma  # noqa: E402
from scripts._saida import forcar_saida_utf8  # noqa: E402


def matriculas_em_turma_de_outro_ano(db, escola_ids: list[int] | None = None) -> list[tuple]:
    """(escola_id, escola, ano ativo, turma_id, turma, ano da turma, situação da turma,
    aluno_id, situação da ficha) de cada matrícula do ano ativo numa turma de outro ano."""
    consulta = (
        select(Escola.id, Escola.nome, Escola.ano_letivo_ativo, Turma.id, Turma.nome,
               Turma.ano_letivo, Turma.status, Matricula.aluno_id, Aluno.status)
        .join(Escola, Escola.id == Matricula.escola_id)
        .join(Turma, Turma.id == Matricula.turma_id)
        .join(Aluno, Aluno.id == Matricula.aluno_id)
        .where(Matricula.ano_letivo == Escola.ano_letivo_ativo,
               Turma.ano_letivo != Escola.ano_letivo_ativo)
        .order_by(Escola.id, Turma.id, Matricula.aluno_id)
    )
    if escola_ids is not None:
        consulta = consulta.where(Escola.id.in_(escola_ids))
    return list(db.execute(consulta).all())


def _rastros_da_turma(db, escola_id: int, turma_id: int) -> list[str]:
    """O que o log de auditoria diz da turma: a última mudança do ano letivo e a última
    transferência de alunos para ela."""
    rastros = []
    mudancas = db.execute(
        select(LogAuditoria.created_at, LogAuditoria.detalhes)
        .where(LogAuditoria.escola_id == escola_id, LogAuditoria.acao == "turma.atualizada",
               LogAuditoria.entidade == "turma", LogAuditoria.entidade_id == turma_id)
        .order_by(LogAuditoria.created_at.desc())
    ).all()
    for quando, detalhes in mudancas:
        if isinstance(detalhes, dict) and "ano_letivo" in detalhes:
            rastros.append(f"ano letivo mudado para {detalhes['ano_letivo']} em {quando:%Y-%m-%d}")
            break
    transferencias = db.execute(
        select(LogAuditoria.created_at, LogAuditoria.detalhes)
        .where(LogAuditoria.escola_id == escola_id, LogAuditoria.acao == "aluno.transferido")
        .order_by(LogAuditoria.created_at.desc())
    ).all()
    for quando, detalhes in transferencias:
        if isinstance(detalhes, dict) and detalhes.get("turma_id") == turma_id:
            rastros.append(f"última transferência de alunos para ela em {quando:%Y-%m-%d}")
            break
    return rastros


def main() -> int:
    forcar_saida_utf8()
    p = argparse.ArgumentParser(
        description="Diagnóstico só de leitura: matrícula do ano ativo em turma de outro ano.")
    p.add_argument("--escola", type=int, default=None)
    p.add_argument("--rede", type=int, default=None)
    p.add_argument("--listar", action="store_true",
                   help="listar os ids das fichas (nunca o nome da criança)")
    args = p.parse_args()

    db = SessionLocal()
    try:
        escola_ids = None
        if args.escola is not None:
            escola_ids = [args.escola]
        elif args.rede is not None:
            escola_ids = list(db.execute(
                select(Escola.id).where(Escola.rede_id == args.rede)).scalars())
        linhas = matriculas_em_turma_de_outro_ano(db, escola_ids)

        por_escola: dict[int, dict] = {}
        for eid, enome, ano, tid, tnome, tano, tstatus, aluno_id, astatus in linhas:
            escola = por_escola.setdefault(eid, {"nome": enome, "ano": ano, "turmas": {}})
            turma = escola["turmas"].setdefault(
                tid, {"nome": tnome, "ano": tano, "status": tstatus, "alunos": []})
            turma["alunos"].append((aluno_id, astatus))

        for eid, escola in por_escola.items():
            total = sum(len(t["alunos"]) for t in escola["turmas"].values())
            print(f"\n== Escola {eid} — {escola['nome']} (ano ativo {escola['ano']}): "
                  f"{total} matrícula(s) em turma de outro ano ==")
            for tid, turma in escola["turmas"].items():
                ativos = sum(1 for _a, situacao in turma["alunos"] if situacao == "ativo")
                print(f"  turma {tid} “{turma['nome']}” ({turma['ano']}, {turma['status']}): "
                      f"matrículas do ano ativo: {len(turma['alunos'])} "
                      f"({ativos} de aluno ativo)")
                for rastro in _rastros_da_turma(db, eid, tid):
                    print(f"     {rastro}")
                if args.listar:
                    ids = ", ".join(str(a) for a, _s in turma["alunos"])
                    print(f"     alunos (id): {ids}")

        print("\n===== TOTAL =====")
        if not linhas:
            print("  TOTAL: nenhuma matrícula do ano ativo em turma de outro ano.")
        else:
            print(f"  TOTAL: {len(linhas)} matrícula(s) do ano ativo em turma de outro ano, "
                  f"em {len(por_escola)} escola(s).")
            print("  Essas crianças ficam fora dos painéis da escola e da rede até a matrícula "
                  "ir para uma turma do ano ativo.")
        return 0
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
