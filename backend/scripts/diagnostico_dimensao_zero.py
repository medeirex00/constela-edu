"""Diagnóstico READ-ONLY: quantos alunos aparecem com UMA dimensão em 0 por AUSÊNCIA
de snapshot (o retrato do bug LIVIA/TOBIAS) e quantos é 0 legítimo.

NÃO grava nada. NÃO chama plataforma. Só lê o banco, com a MESMA regra do motor
(``scoring._carregar_contexto``, que o recálculo usa), para os números baterem com o
ranking e com ``Nota.detalhes['dimensoes'][*]['aferido']``:
  * população = as crianças que o motor PONTUA: ativas, matriculadas no ano letivo
    ativo, sem as Fases (Educação Infantil não concorre);
  * aferido em Matemática = retrato do Matific DENTRO do ano letivo (o contador é do
    ano: retrato só de outro ano é ausência);
  * aferido em Leitura = retrato do Elefante OU leituras itemizadas (o contador é
    vitalício; leitura sem retrato também afere);
  * dimensão de módulo que a rede NÃO contratou não existe para a escola: ninguém fica
    "ausente" nela.

As três semânticas do zero (spec §12.4):
  * AMBAS ausentes      -> aluno sem nenhuma plataforma (0/0 legítimo);
  * SÓ Matific presente -> Leitura 0 é ausência (candidato ao bug se ele LÊ no Elefante);
  * SÓ Elefante presente-> Matific 0 é ausência (candidato ao bug — é o caso LIVIA);
  * AMBAS presentes     -> completo.
Na rede com um módulo só, quem é aferido nele está completo, mas NÃO tem "as duas":
conta numa linha própria ("aferido no único módulo contratado"), também no TOTAL — senão
o "AMBAS" do total dizia que crianças de uma rede sem Matemática tinham as duas.

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
from app.models import Escola, LogAuditoria  # noqa: E402
from app.services import scoring  # noqa: E402
from scripts._saida import forcar_saida_utf8  # noqa: E402


# Contadores por escola e do TOTAL. "ambas" é só das escolas com os dois módulos;
# "so_contratado" é quem é aferido no único módulo de uma rede de um módulo só.
CHAVES = ("total", "ambas", "so_contratado", "so_matific", "so_elefante", "nenhuma")


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


def _diagnostico_escola(db, escola_id: int, nome: str, ano: int, listar: int) -> dict:
    # O conjunto PONTUADO e o "aferido" de cada dimensão saem do MESMO contexto que o
    # recálculo usa: regra própria aqui já divergiu do motor (Fases contadas, Matific de
    # outro ano como "aferido", leitura itemizada sem retrato como "Leitura 0").
    contexto = scoring._carregar_contexto(db, escola_id)
    if contexto is None:
        return dict.fromkeys(CHAVES, 0)
    escola, _ano, matriculas, matific, elefante, _pontos = contexto
    contratadas = scoring.dimensoes_contratadas(db, escola)
    duas_dimensoes = len(contratadas) == len(scoring.DIMENSOES)
    linhas = [(m.aluno_id, m.aluno.nome, t.nome) for m, t in matriculas]

    total = len(linhas)
    so_matific, so_elefante, ambas, so_contratado, nenhuma = [], [], 0, 0, 0
    for aid, anome, tnome in linhas:
        m, e = aid in matific, aid in elefante
        if not duas_dimensoes:
            # Um módulo só: a outra dimensão não existe aqui (o motor não afere
            # ninguém nela) — quem tem a contratada está completo, mas não tem "as
            # duas": conta à parte, para o TOTAL não somá-lo em "AMBAS".
            if m or e:
                so_contratado += 1
            else:
                nenhuma += 1
            continue
        if m and e:
            ambas += 1
        elif m and not e:
            so_matific.append((anome, tnome))       # Leitura 0 (ausente)
        elif e and not m:
            so_elefante.append((anome, tnome))       # Matific 0 (ausente) — caso LIVIA
        else:
            nenhuma += 1

    print(f"\n== Escola {escola_id} — {nome} (ano {ano}) ==")
    if not duas_dimensoes:
        print(f"  módulos contratados ............... {', '.join(contratadas)}"
              " (a outra dimensão não existe nesta escola)")
    print(f"  alunos pontuados (sem as Fases) ... {total}")
    print(f"  com Matific (aferido matemática) .. {len(matific)}")
    print(f"  com Elefante (aferido leitura) .... {len(elefante)}")
    if duas_dimensoes:
        print(f"  AMBAS as dimensões ................ {ambas}")
    else:
        print(f"  aferido no módulo contratado ...... {so_contratado}")
    print(f"  SÓ Matific  -> Leitura 0 (ausente) . {len(so_matific)}")
    print(f"  SÓ Elefante -> Matific 0 (ausente) . {len(so_elefante)}   <- retrato do caso LIVIA")
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

    return {"total": total, "ambas": ambas, "so_contratado": so_contratado,
            "so_matific": len(so_matific), "so_elefante": len(so_elefante),
            "nenhuma": nenhuma}


def main() -> int:
    forcar_saida_utf8()
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

        tot = dict.fromkeys(CHAVES, 0)
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
        # "AMBAS" é só das redes com os dois módulos; quem é aferido no único módulo
        # da rede dele fica na linha própria (não tem "as duas").
        print(f"  AMBAS ................. {tot['ambas']}")
        print(f"  aferido no único módulo contratado (rede de um módulo) .. {tot['so_contratado']}")
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
