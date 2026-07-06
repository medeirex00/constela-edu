"""Administração (PRD §18): usuários, backup/restauração e aparência.

Tudo aqui exige papel de administrador. Regras de proteção:
  * ninguém desativa ou rebaixa a própria conta (evita lockout);
  * usuários nunca entram no backup de dados (restaurar um arquivo antigo
    não pode reverter senhas nem reativar contas desligadas).
"""
import json

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import escola_autorizada, exigir_papeis, get_usuario_atual
from app.core.security import hash_senha
from app.models import Configuracao, Usuario
from app.schemas import UsuarioOut
from app.services import backup as svc_backup
from app.services import scoring
from app.services.audit import registrar

router = APIRouter(prefix="/escolas/{escola_id}", tags=["Administração"])

CARGOS = {"admin", "coordenador", "professor", "visitante"}


# --- Usuários (PRD §18) -------------------------------------------------------

class UsuarioCreate(BaseModel):
    nome: str = Field(min_length=2, max_length=200)
    email: EmailStr
    senha: str = Field(min_length=6, max_length=100)
    cargo: str = "visitante"


class UsuarioUpdate(BaseModel):
    nome: str | None = None
    cargo: str | None = None
    status: str | None = Field(default=None, pattern="^(ativo|inativo)$")
    senha: str | None = Field(default=None, min_length=6, max_length=100)


@router.get("/usuarios", response_model=list[UsuarioOut])
def listar_usuarios(
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin")),
    db: Session = Depends(get_db),
):
    return db.execute(
        select(Usuario).where(Usuario.escola_id == escola_id).order_by(Usuario.nome)
    ).scalars().all()


@router.post("/usuarios", response_model=UsuarioOut, status_code=status.HTTP_201_CREATED)
def criar_usuario(
    dados: UsuarioCreate,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin")),
    db: Session = Depends(get_db),
):
    if dados.cargo not in CARGOS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Cargos válidos: {', '.join(sorted(CARGOS))}.")
    email = dados.email.lower().strip()
    if db.execute(select(Usuario).where(Usuario.email == email)).scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "Já existe um usuário com este e-mail.")

    novo = Usuario(escola_id=escola_id, nome=dados.nome.strip(), email=email,
                   senha_hash=hash_senha(dados.senha), cargo=dados.cargo)
    db.add(novo)
    db.flush()
    registrar(db, "usuario.criado", escola_id=escola_id, usuario_id=usuario.id,
              entidade="usuario", entidade_id=novo.id,
              detalhes={"email": email, "cargo": dados.cargo})
    db.commit()
    db.refresh(novo)
    return novo


@router.patch("/usuarios/{usuario_id}", response_model=UsuarioOut)
def atualizar_usuario(
    usuario_id: int,
    dados: UsuarioUpdate,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin")),
    db: Session = Depends(get_db),
):
    alvo = db.get(Usuario, usuario_id)
    if alvo is None or alvo.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuário não encontrado.")
    if dados.cargo is not None and dados.cargo not in CARGOS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Cargos válidos: {', '.join(sorted(CARGOS))}.")
    if alvo.id == usuario.id and (
        dados.status == "inativo" or (dados.cargo and dados.cargo != "admin")
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Você não pode desativar nem rebaixar a própria conta.")

    alteracoes: dict = {}
    if dados.nome is not None:
        alvo.nome = dados.nome.strip()
        alteracoes["nome"] = alvo.nome
    if dados.cargo is not None:
        alteracoes["cargo"] = {"de": alvo.cargo, "para": dados.cargo}
        alvo.cargo = dados.cargo
    if dados.status is not None:
        alteracoes["status"] = {"de": alvo.status, "para": dados.status}
        alvo.status = dados.status
    if dados.senha is not None:
        alvo.senha_hash = hash_senha(dados.senha)
        alteracoes["senha"] = "redefinida"

    registrar(db, "usuario.atualizado", escola_id=escola_id, usuario_id=usuario.id,
              entidade="usuario", entidade_id=alvo.id, detalhes=alteracoes)
    db.commit()
    db.refresh(alvo)
    return alvo


# --- Backup e restauração (PRD §18) ------------------------------------------

@router.get("/backup")
def baixar_backup(
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin")),
    db: Session = Depends(get_db),
):
    dados = svc_backup.exportar(db, escola_id)
    registrar(db, "backup.gerado", escola_id=escola_id, usuario_id=usuario.id,
              detalhes={"tabelas": {n: len(l) for n, l in dados["tabelas"].items()}})
    db.commit()
    conteudo = json.dumps(dados, ensure_ascii=False, indent=1).encode("utf-8")
    return Response(
        content=conteudo,
        media_type="application/json",
        headers={"Content-Disposition":
                 f'attachment; filename="sgpe_backup_escola{escola_id}.json"'},
    )


@router.post("/restaurar")
async def restaurar_backup(
    arquivo: UploadFile = File(...),
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin")),
    db: Session = Depends(get_db),
):
    """Substitui TODOS os dados pedagógicos da escola pelos do backup."""
    try:
        dados = json.loads((await arquivo.read()).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "O arquivo não é um backup JSON válido.")

    try:
        contagem = svc_backup.restaurar(db, escola_id, dados)
    except ValueError as erro:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(erro))

    registrar(db, "backup.restaurado", escola_id=escola_id, usuario_id=usuario.id,
              detalhes={"tabelas": contagem})
    db.commit()
    scoring.recalcular_escola(db, escola_id)
    total = sum(contagem.values())
    return {"mensagem": f"Backup restaurado: {total} registros. Notas recalculadas.",
            "tabelas": contagem}


# --- Aparência (PRD §18) -------------------------------------------------------

class AparenciaUpdate(BaseModel):
    cor_primaria: str = Field(pattern="^#[0-9a-fA-F]{6}$")
    mostrar_fotos: bool = True


@router.get("/aparencia")
def obter_aparencia(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    valores = scoring.obter_config(db, escola_id, "aparencia", "valores", {})
    return {
        "cor_primaria": valores.get("cor_primaria", "#1B2A4A"),
        "mostrar_fotos": valores.get("mostrar_fotos", True),
    }


@router.put("/aparencia")
def salvar_aparencia(
    dados: AparenciaUpdate,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin")),
    db: Session = Depends(get_db),
):
    row = db.execute(
        select(Configuracao).where(
            Configuracao.escola_id == escola_id,
            Configuracao.namespace == "aparencia",
            Configuracao.chave == "valores",
        )
    ).scalar_one_or_none()
    if row is None:
        row = Configuracao(escola_id=escola_id, namespace="aparencia",
                           chave="valores", valor=dados.model_dump())
        db.add(row)
    else:
        row.valor = dados.model_dump()
    registrar(db, "aparencia.alterada", escola_id=escola_id, usuario_id=usuario.id,
              detalhes=dados.model_dump())
    db.commit()
    return dados.model_dump()
