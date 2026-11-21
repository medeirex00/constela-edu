"""Expurgo de retenção por categoria — DESLIGADO por padrão (LGPD, achado 4 de 20/10).

Todas as categorias nascem com prazo 0 (= não expurga). Nada acontece até alguém
definir um prazo — pelo ambiente (``RETENCAO_*_DIAS``) ou aqui (``--dias``) — e o
prazo é decisão jurídica do dono/controlador, não deste script (ver
docs/lgpd/RETENCAO-TECNICA.md). ``--dry-run`` só CONTA, não apaga nada.

    python -m scripts.expurgar_retencao --dry-run
    python -m scripts.expurgar_retencao --dry-run --dias auditoria_quest=365
    python -m scripts.expurgar_retencao --dias auditoria_quest=365   # apaga

Categorias: auditoria_acesso, auditoria_quest, auditoria_alunos, auditoria_demais,
sincronizacao_logs, notificacoes. As provas do esquecimento (aluno.excluido_permanente
etc.) nunca entram. Registros de acesso abaixo de 183 dias exigem
``--abaixo-do-piso`` (Marco Civil, art. 15). O resultado só traz contagens.
"""
import argparse
import sys

from app.core.database import SessionLocal
from app.services.audit import CATEGORIAS, expurgar_retencao
from scripts._saida import forcar_saida_utf8


def _prazos(pares: list[str]) -> dict[str, int]:
    prazos: dict[str, int] = {}
    for par in pares:
        categoria, sep, dias = par.partition("=")
        if not sep or categoria not in CATEGORIAS or not dias.strip().isdigit():
            raise SystemExit(f"--dias inválido: {par!r} (use categoria=N, N inteiro ≥ 0; "
                             f"categorias: {', '.join(CATEGORIAS)})")
        prazos[categoria] = int(dias)
    return prazos


def main(argv: list[str] | None = None) -> int:
    forcar_saida_utf8()
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="só conta o que seria apagado (não apaga nada)")
    parser.add_argument("--dias", action="append", default=[], metavar="CATEGORIA=N",
                        help="prazo em dias para a categoria nesta execução (0 = desligada)")
    parser.add_argument("--abaixo-do-piso", action="store_true",
                        help="aceita prazo de auditoria_acesso menor que 183 dias")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        resultado = expurgar_retencao(db, simular=args.dry_run, prazos=_prazos(args.dias),
                                      aceitar_abaixo_do_piso=args.abaixo_do_piso)
        if not args.dry_run:
            db.commit()
    except ValueError as erro:
        db.rollback()
        print(f"Recusado: {erro}", file=sys.stderr)
        return 2
    finally:
        db.close()

    verbo = "seriam apagadas" if args.dry_run else "apagadas"
    ligadas = 0
    for categoria in CATEGORIAS:
        r = resultado[categoria]
        if not r["dias"]:
            print(f"{categoria}: desligada (prazo 0)")
            continue
        ligadas += 1
        reduzidas = r.get("reduzidas") or 0
        extra = (f"; {reduzidas} reduzida(s) aos ids, sem dado pessoal (ligação da fusão)"
                 if reduzidas else "")
        print(f"{categoria}: prazo {r['dias']} dias, antes de {r['corte']} — "
              f"{r['linhas']} linha(s) {verbo}{extra}")
    if not ligadas:
        print("Nenhuma categoria com prazo definido: nada a fazer.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
