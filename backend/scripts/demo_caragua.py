"""Provisiona apenas o tenant da demonstração de Caraguatatuba."""
import argparse
import os
import sys
from collections.abc import Callable
from getpass import GetPassWarning, getpass
from warnings import catch_warnings, simplefilter

from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import email_reservado_ao_dono, settings
from app.core.database import SessionLocal, engine
from app.core.migracoes import estado_do_schema
from app.core.security import hash_senha, validar_forca_senha
from app.models import Escola, ModuloRede, Rede, Usuario
from app.services import demo_caragua as demo
from scripts._saida import forcar_saida_utf8

_CARGO = "coordenador"


def _serializar(db: Session) -> None:
    conexao = db.connection()
    if conexao.dialect.name == "postgresql":
        db.execute(text("SET LOCAL lock_timeout = '5s'"))
        db.execute(text("SELECT pg_advisory_xact_lock(1230197584, 20261127)"))
    elif conexao.dialect.name == "sqlite" and not conexao.connection.driver_connection.in_transaction:
        conexao.exec_driver_sql("BEGIN IMMEDIATE")


def _localizar(db: Session) -> tuple[Rede, Usuario, ModuloRede] | None:
    redes = db.scalars(select(Rede).where(
        func.lower(func.trim(Rede.nome)) == demo.NOME_REDE.lower(),
    )).all()
    marcadores = db.scalars(select(ModuloRede).where(ModuloRede.modulo == demo.MODULO)).all()
    redes_ids = {rede.id for rede in redes}
    redes_ids.update(marcador.rede_id for marcador in marcadores)
    contas = db.scalars(select(Usuario).where(or_(
        func.lower(Usuario.username) == demo.USERNAME,
        func.lower(Usuario.email) == demo.EMAIL,
        Usuario.rede_id.in_(redes_ids),
    ))).all()
    if not (redes or contas or marcadores):
        return None

    if len(redes) != 1 or len(contas) != 1 or len(marcadores) != 1:
        raise ValueError("Há colisão no cadastro reservado à demonstração.")

    rede, conta, marcador = redes[0], contas[0], marcadores[0]
    if (
        rede.nome != demo.NOME_REDE or rede.status != "ativa"
        or rede.codigo_ibge is not None or rede.codigo_municipio_estadual is not None
        or rede.token_publico is not None
        or conta.username != demo.USERNAME or conta.email != demo.EMAIL
        or conta.cargo != _CARGO or conta.escola_id is not None or conta.is_global
        or conta.rede_id != rede.id or marcador.rede_id != rede.id
        or db.scalar(select(Escola.id).where(Escola.rede_id == rede.id).limit(1)) is not None
    ):
        raise ValueError("O cadastro encontrado não é exclusivo da demonstração.")
    return rede, conta, marcador


def provisionar(db: Session, solicitar_senha: Callable[[], str]) -> bool:
    """Cria a rede vazia e a conta. Em nova execução, preserva o acesso existente."""
    _serializar(db)
    if email_reservado_ao_dono(demo.EMAIL):
        raise ValueError("O e-mail reservado ao administrador global coincide com o da demonstração.")
    existente = _localizar(db)
    if existente is not None:
        _, conta, marcador = existente
        if not marcador.ativo or conta.status != "ativo":
            raise ValueError("O acesso da demonstração está revogado.")
        return False

    senha = solicitar_senha()
    erro = validar_forca_senha(senha, demo.EMAIL, nome=demo.NOME_USUARIO, usuario=demo.USERNAME)
    if erro:
        raise ValueError(erro)

    rede = Rede(nome=demo.NOME_REDE)
    db.add(rede)
    db.flush()
    db.add_all([
        Usuario(
            nome=demo.NOME_USUARIO, email=demo.EMAIL, username=demo.USERNAME,
            senha_hash=hash_senha(senha), escola_id=None, rede_id=rede.id,
            cargo=_CARGO, is_global=False,
        ),
        ModuloRede(rede_id=rede.id, modulo=demo.MODULO, ativo=True),
    ])
    db.flush()
    return True


def revogar(db: Session) -> bool:
    """Desativa somente a conta e o marcador da demonstração."""
    _serializar(db)
    existente = _localizar(db)
    if existente is None:
        return False
    _, conta, marcador = existente
    if conta.status == "inativo" and not marcador.ativo:
        return False
    if conta.status not in {"ativo", "inativo"}:
        raise ValueError("O estado da conta de demonstração não permite revogação.")
    conta.status = "inativo"
    conta.token_version = (conta.token_version or 0) + 1
    marcador.ativo = False
    return True


def _ler_senha() -> str:
    if not sys.stdin.isatty():
        raise ValueError("Use um terminal interativo para criar a conta de demonstração.")
    with catch_warnings():
        simplefilter("error", GetPassWarning)
        senha = getpass("Senha da Secretaria de demonstração: ")
        if senha != getpass("Repita a senha: "):
            raise ValueError("A confirmação da senha não confere.")
    return senha


def main(argv: list[str] | None = None) -> int:
    forcar_saida_utf8()
    parser = argparse.ArgumentParser(description=__doc__)
    operacao = parser.add_mutually_exclusive_group(required=True)
    operacao.add_argument("--criar", action="store_true")
    operacao.add_argument("--revogar", action="store_true")
    parser.add_argument("--confirmar-producao", action="store_true",
                        help="confirma o uso do banco remoto ou de produção explicitamente configurado")
    args = parser.parse_args(argv)
    if not os.environ.get("DATABASE_URL", "").strip():
        parser.error("Defina DATABASE_URL explicitamente.")
    postgres_remoto = engine.url.get_backend_name() == "postgresql" and engine.url.host not in {
        None, "localhost", "127.0.0.1", "::1",
    }
    if (settings.em_producao or postgres_remoto) and not args.confirmar_producao:
        parser.error("O banco remoto ou de produção exige confirmação explícita.")

    try:
        with SessionLocal.begin() as db:
            if estado_do_schema(db.connection()).situacao != "em_dia":
                raise ValueError("O banco não está na revisão esperada pelo backend.")
            alterou = provisionar(db, _ler_senha) if args.criar else revogar(db)
    except ValueError as erro:
        print(f"Demonstração recusada: {erro}", file=sys.stderr)
        return 1
    except (SQLAlchemyError, GetPassWarning, EOFError, KeyboardInterrupt):
        print("Operação de demonstração interrompida.", file=sys.stderr)
        return 1

    if args.criar:
        print("Acesso de demonstração criado." if alterou else "O acesso de demonstração já existe.")
    else:
        print("Acesso de demonstração revogado." if alterou else "Não há acesso de demonstração ativo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
