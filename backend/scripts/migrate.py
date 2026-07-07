"""Migração de partida: colunas/índices novos + criação do schema.

Executado UMA vez pelo entrypoint do container, antes dos workers subirem —
evita que os N workers do uvicorn corram entre si aplicando DDL.
"""
from app.core.database import Base, engine, migrar_colunas_novas


def main() -> None:
    migrar_colunas_novas(engine)
    Base.metadata.create_all(bind=engine)
    print("Migração concluída.")


if __name__ == "__main__":
    main()
