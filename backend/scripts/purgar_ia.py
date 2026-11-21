"""Purga de retenção das conversas do assistente (LGPD, direito ao esquecimento).

Apaga conversas de `mensagens_ia`/`conversas_ia` mais antigas que
`IA_RETENCAO_DIAS` (padrão 90). Também roda no boot (garantir_dados_base) como
garantia mínima; agende ESTE comando diariamente para cadência regular entre
deploys (Railway Cron / sidecar do compose / cron do SO):

    python -m scripts.purgar_ia

``IA_RETENCAO_DIAS`` menor que 1 é recusado SEM apagar nada (0 não desliga a purga:
apagaria todas as conversas): o comando diz o que corrigir e sai com código 2, sem
traceback no log do cron.
"""
import sys

from app.core.database import SessionLocal
from app.services.assistente import purgar_conversas_ia_expiradas
from scripts._saida import forcar_saida_utf8


def main() -> None:
    forcar_saida_utf8()
    db = SessionLocal()
    try:
        try:
            removidas = purgar_conversas_ia_expiradas(db)
        except ValueError as erro:
            print(f"Retenção IA recusada, nada foi apagado: {erro}", file=sys.stderr)
            sys.exit(2)
        print(f"Retenção IA: {removidas} conversa(s) expirada(s) removida(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
