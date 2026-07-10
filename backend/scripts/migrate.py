"""Migração de partida do container: Alembic + ajustes de dados.

Executado UMA vez pelo entrypoint, antes dos workers subirem — evita que os N
workers do uvicorn corram entre si aplicando DDL. Leva o banco à última
revisão (criando o schema em bancos novos, preservando os dados nos
existentes) e aplica as correções de dados idempotentes.
"""
from app.core.database import engine, garantir_dados_base
from app.core.migracoes import aplicar_migracoes


def main() -> None:
    aplicar_migracoes(engine)
    garantir_dados_base(engine)
    print("Migração concluída.")


if __name__ == "__main__":
    main()
