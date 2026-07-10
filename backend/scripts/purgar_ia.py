"""Purga de retenção das conversas do assistente (LGPD, direito ao esquecimento).

Apaga conversas de `mensagens_ia`/`conversas_ia` mais antigas que
`IA_RETENCAO_DIAS` (padrão 90). Também roda no boot (garantir_dados_base) como
garantia mínima; agende ESTE comando diariamente para cadência regular entre
deploys (Railway Cron / sidecar do compose / cron do SO):

    python -m scripts.purgar_ia
"""
from app.core.database import SessionLocal
from app.services.assistente import purgar_conversas_ia_expiradas


def main() -> None:
    db = SessionLocal()
    try:
        removidas = purgar_conversas_ia_expiradas(db)
        print(f"Retenção IA: {removidas} conversa(s) expirada(s) removida(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
