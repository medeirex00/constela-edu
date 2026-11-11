"""Limpa os eventos de leitura DUPLICADOS que as fusões antigas deixaram — SIMULAÇÃO por padrão.

Antes do conserto da fusão (achado ALUNOS-3), a mesma linha do relatório gravada
nas duas fichas virava dois eventos na ficha que ficou, e a coleta seguinte da
mesma conta gravava mais um. A linha do tempo, o espelho e os "Registros de
leitura" do Relatório por Período contavam a mais. O código já não duplica; este
script tira o que ficou gravado.

Sem ``--aplicar`` só CONTA (nada é apagado). Com ``--aplicar``, em cada grupo de
cópias fica a que veio da ficha absorvida (a evidência da restauração histórica)
e cada remoção vai para o log de auditoria da ficha
(``aluno.eventos_duplicados_removidos``). A saída só traz contagens.

    python -m scripts.deduplicar_eventos_por_conteudo                 # simulação
    python -m scripts.deduplicar_eventos_por_conteudo --escola 11     # simulação, 1 escola
    python -m scripts.deduplicar_eventos_por_conteudo --aplicar       # apaga

Rodar em produção é decisão do dono: primeiro a simulação, depois o backup, só
então ``--aplicar``.
"""
import argparse
import sys

from app.core.database import SessionLocal
from app.services.eventos import deduplicar_eventos_por_conteudo
from scripts._saida import forcar_saida_utf8


def main(argv: list[str] | None = None) -> int:
    forcar_saida_utf8()
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--aplicar", action="store_true",
                        help="apaga as cópias repetidas (sem isto, só conta)")
    parser.add_argument("--escola", type=int, default=None, metavar="ID",
                        help="só a escola com este id (padrão: todas)")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        resultado = deduplicar_eventos_por_conteudo(db, escola_id=args.escola,
                                                    aplicar=args.aplicar)
        if args.aplicar:
            db.commit()
        else:
            db.rollback()
    finally:
        db.close()

    alvo = f"escola {args.escola}" if args.escola is not None else "todas as escolas"
    if args.aplicar:
        print(f"APLICADO ({alvo}): {resultado['eventos_duplicados']} evento(s) "
              f"repetido(s) apagado(s) em {resultado['alunos']} ficha(s).")
    else:
        print(f"SIMULAÇÃO ({alvo}) — nada foi apagado: {resultado['eventos_duplicados']} "
              f"evento(s) repetido(s) em {resultado['alunos']} ficha(s). "
              "Use --aplicar para apagar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
