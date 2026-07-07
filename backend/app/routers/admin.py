"""Administração (PRD §18): usuários, backup/restauração e aparência.

Tudo aqui exige papel de administrador. Regras de proteção:
  * ninguém desativa, rebaixa ou EXCLUI a própria conta (evita lockout);
  * o último administrador ativo da escola é intocável até existir outro;
  * excluir é LÓGICO por padrão (status "excluido") — histórico, logs e
    importações permanecem intactos; a remoção física é exclusiva de
    administradores globais e exige confirmação extra;
  * usuários nunca entram no backup de dados (restaurar um arquivo antigo
    não pode reverter senhas nem reativar contas desligadas).
"""
import json
import logging

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DataError, IntegrityError, StatementError
from sqlalchemy.orm import Session

logger = logging.getLogger("constela.admin")
TAMANHO_MAXIMO_BACKUP = 25 * 1024 * 1024  # 25 MB

from app.core.database import get_db
from app.core.deps import escola_autorizada, exigir_papeis, get_usuario_atual
from app.core.security import hash_senha, validar_forca_senha
from app.models import (
    Configuracao,
    ConversaIA,
    DispositivoMovel,
    Importacao,
    LogAuditoria,
    MensagemIA,
    Usuario,
)
from app.schemas import UsuarioOut
from app.services import backup as svc_backup
from app.services import scoring
from app.services.audit import registrar

router = APIRouter(prefix="/escolas/{escola_id}", tags=["Administração"])

CARGOS = {"admin", "coordenador", "professor", "visitante"}

MSG_ULTIMO_ADMIN = (
    "Este é o único administrador ativo da escola. Crie ou reative outro "
    "administrador antes de desativar, rebaixar ou excluir este."
)


# --- Usuários (PRD §18) -------------------------------------------------------

class UsuarioCreate(BaseModel):
    nome: str = Field(min_length=2, max_length=200)
    email: EmailStr
    senha: str = Field(min_length=8, max_length=100)
    cargo: str = "visitante"

    @field_validator("senha")
    @classmethod
    def _forca(cls, valor: str, info) -> str:
        erro = validar_forca_senha(valor, info.data.get("email"))
        if erro:
            raise ValueError(erro)
        return valor


class UsuarioUpdate(BaseModel):
    nome: str | None = None
    cargo: str | None = None
    status: str | None = Field(default=None, pattern="^(ativo|inativo)$")
    senha: str | None = Field(default=None, min_length=8, max_length=100)

    @field_validator("senha")
    @classmethod
    def _forca(cls, valor: str | None) -> str | None:
        if valor is not None:
            erro = validar_forca_senha(valor)
            if erro:
                raise ValueError(erro)
        return valor


def _usuario_alvo(db: Session, escola_id: int, usuario_id: int,
                  ator: Usuario) -> Usuario:
    alvo = db.get(Usuario, usuario_id)
    if alvo is None or alvo.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuário não encontrado.")
    if alvo.is_global and not ator.is_global:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Somente administradores globais podem gerenciar "
                            "contas globais.")
    return alvo


def _e_ultimo_admin_ativo(db: Session, escola_id: int, alvo: Usuario) -> bool:
    """O alvo é o único admin ativo da escola? (proteção contra lockout)

    Contas globais ficam fora da conta: elas administram todas as escolas
    e não substituem o administrador local da escola.
    """
    if alvo.cargo != "admin" or alvo.status != "ativo" or alvo.is_global:
        return False
    ativos = db.execute(
        select(func.count()).select_from(Usuario).where(
            Usuario.escola_id == escola_id,
            Usuario.cargo == "admin",
            Usuario.status == "ativo",
            Usuario.is_global.is_(False),
        )
    ).scalar_one()
    return ativos <= 1


@router.get("/usuarios", response_model=list[UsuarioOut])
def listar_usuarios(
    escola_id: int = Depends(escola_autorizada),
    incluir_excluidos: bool = Query(default=False),
    usuario: Usuario = Depends(exigir_papeis("admin")),
    db: Session = Depends(get_db),
):
    consulta = select(Usuario).where(Usuario.escola_id == escola_id)
    if not incluir_excluidos:
        consulta = consulta.where(Usuario.status != "excluido")
    return db.execute(consulta.order_by(Usuario.nome)).scalars().all()


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
    alvo = _usuario_alvo(db, escola_id, usuario_id, usuario)
    enviados = dados.model_dump(exclude_unset=True)
    if alvo.status == "excluido" and enviados != {"status": "ativo"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Usuário excluído — restaure a conta (situação "
                            "“ativo”) antes de editá-la.")
    if dados.cargo is not None and dados.cargo not in CARGOS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Cargos válidos: {', '.join(sorted(CARGOS))}.")
    if alvo.id == usuario.id and (
        dados.status == "inativo" or (dados.cargo and dados.cargo != "admin")
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Você não pode desativar nem rebaixar a própria conta.")
    remove_admin = (dados.status == "inativo"
                    or (dados.cargo is not None and dados.cargo != "admin"))
    if remove_admin and _e_ultimo_admin_ativo(db, escola_id, alvo):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, MSG_ULTIMO_ADMIN)

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
        # Invalida todas as sessões abertas do usuário (tokens antigos param
        # de valer). Protege o caso de conta comprometida.
        alvo.token_version = (alvo.token_version or 0) + 1
        alteracoes["senha"] = "redefinida"

    # Nome da ação no log espelha o que de fato aconteceu (PRD §17)
    if set(alteracoes) == {"status"}:
        de, para = alteracoes["status"]["de"], alteracoes["status"]["para"]
        if para == "inativo":
            acao = "usuario.desativado"
        elif de == "excluido":
            acao = "usuario.restaurado"
        else:
            acao = "usuario.reativado"
    elif set(alteracoes) == {"senha"}:
        acao = "usuario.senha_redefinida"
    elif "cargo" in alteracoes and len(alteracoes) == 1:
        acao = "usuario.permissoes_alteradas"
    else:
        acao = "usuario.atualizado"
    registrar(db, acao, escola_id=escola_id, usuario_id=usuario.id,
              entidade="usuario", entidade_id=alvo.id,
              detalhes={**alteracoes, "email": alvo.email})
    db.commit()
    db.refresh(alvo)
    return alvo


@router.delete("/usuarios/{usuario_id}", response_model=dict)
def excluir_usuario(
    usuario_id: int,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin")),
    db: Session = Depends(get_db),
):
    """Exclusão LÓGICA: a conta é marcada como excluída e perde o acesso,
    mas histórico, logs, importações e registros vinculados permanecem."""
    alvo = _usuario_alvo(db, escola_id, usuario_id, usuario)
    if alvo.id == usuario.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Você não pode excluir a própria conta.")
    if alvo.status == "excluido":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Este usuário já está excluído.")
    if _e_ultimo_admin_ativo(db, escola_id, alvo):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, MSG_ULTIMO_ADMIN)

    alvo.status = "excluido"
    registrar(db, "usuario.excluido", escola_id=escola_id, usuario_id=usuario.id,
              entidade="usuario", entidade_id=alvo.id,
              detalhes={"tipo": "exclusao_logica", "email": alvo.email,
                        "nome": alvo.nome, "cargo": alvo.cargo})
    db.commit()
    return {"mensagem": f"Usuário “{alvo.nome}” excluído. O histórico de ações "
                        "e importações foi preservado."}


@router.delete("/usuarios/{usuario_id}/permanente", response_model=dict)
def excluir_usuario_permanente(
    usuario_id: int,
    confirmacao: str = Query(default=""),
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin")),
    db: Session = Depends(get_db),
):
    """Remoção FÍSICA do usuário — exclusiva de administradores globais.

    Importações e logs de auditoria são preservados (a autoria fica em
    branco); conversas de IA e dispositivos do usuário são removidos.
    `confirmacao` deve ser o e-mail exato do alvo — a confirmação extra.
    """
    if not usuario.is_global:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "A exclusão permanente é exclusiva de "
                            "administradores globais.")
    alvo = _usuario_alvo(db, escola_id, usuario_id, usuario)
    if alvo.id == usuario.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Você não pode excluir a própria conta.")
    if confirmacao.lower().strip() != alvo.email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Confirmação incorreta: digite o e-mail do usuário "
                            "para confirmar a exclusão permanente.")
    if _e_ultimo_admin_ativo(db, escola_id, alvo):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, MSG_ULTIMO_ADMIN)

    # Preserva a história institucional; apaga somente o que é pessoal
    db.execute(update(Importacao).where(Importacao.usuario_id == alvo.id)
               .values(usuario_id=None))
    db.execute(update(LogAuditoria).where(LogAuditoria.usuario_id == alvo.id)
               .values(usuario_id=None))
    conversas = select(ConversaIA.id).where(ConversaIA.usuario_id == alvo.id)
    db.execute(delete(MensagemIA).where(MensagemIA.conversa_id.in_(conversas)))
    db.execute(delete(ConversaIA).where(ConversaIA.usuario_id == alvo.id))
    db.execute(delete(DispositivoMovel).where(DispositivoMovel.usuario_id == alvo.id))

    registro = {"tipo": "exclusao_permanente", "email": alvo.email,
                "nome": alvo.nome, "cargo": alvo.cargo}
    nome = alvo.nome
    db.delete(alvo)
    registrar(db, "usuario.excluido_permanente", escola_id=escola_id,
              usuario_id=usuario.id, entidade="usuario", entidade_id=usuario_id,
              detalhes=registro)
    db.commit()
    return {"mensagem": f"Usuário “{nome}” removido permanentemente do banco "
                        "de dados. Logs e importações foram preservados sem autoria."}


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
    conteudo = await arquivo.read()
    if len(conteudo) > TAMANHO_MAXIMO_BACKUP:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            "Arquivo de backup acima do tamanho máximo (25 MB).")
    try:
        dados = json.loads(conteudo.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "O arquivo não é um backup JSON válido.")
    if not isinstance(dados, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "O arquivo não é um backup JSON válido.")

    try:
        contagem = svc_backup.restaurar(db, escola_id, dados)
    except (ValueError, TypeError) as erro:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(erro))
    except (IntegrityError, DataError, StatementError):
        db.rollback()
        logger.exception("Restauração de backup falhou (escola %s)", escola_id)
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "O arquivo de backup contém dados inconsistentes ou duplicados.")

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
