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
from app.core.security import (
    cifrar_senha_visivel,
    decifrar_senha_visivel,
    hash_senha,
    validar_forca_senha,
)
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

# Sem "visitante": quem não é gestão/professor acessa apenas o painel PÚBLICO
# (link/QR compartilhado pelo admin ou coordenador — ex.: telão da escola).
CARGOS = {"admin", "coordenador", "professor"}

MSG_ULTIMO_ADMIN = (
    "Este é o único administrador ativo da escola. Crie ou reative outro "
    "administrador antes de desativar, rebaixar ou excluir este."
)


# --- Usuários (PRD §18) -------------------------------------------------------

# Nome de usuário do login (estilo @ do Instagram): minúsculas, números,
# ponto e sublinhado — único na rede toda.
_RE_USERNAME = r"^[a-z0-9._]{3,30}$"


def _normalizar_username(valor: str | None) -> str | None:
    if valor is None:
        return None
    limpo = valor.strip().lstrip("@").lower()
    if not limpo:
        return None
    import re
    if not re.fullmatch(_RE_USERNAME, limpo):
        raise ValueError("Nome de usuário inválido: use de 3 a 30 caracteres "
                         "entre letras minúsculas, números, ponto e “_”.")
    return limpo


class UsuarioCreate(BaseModel):
    nome: str = Field(min_length=2, max_length=200)
    email: EmailStr
    username: str | None = None
    senha: str = Field(min_length=8, max_length=100)
    cargo: str = "professor"

    @field_validator("senha")
    @classmethod
    def _forca(cls, valor: str, info) -> str:
        erro = validar_forca_senha(valor, info.data.get("email"))
        if erro:
            raise ValueError(erro)
        return valor

    @field_validator("username")
    @classmethod
    def _username(cls, valor: str | None) -> str | None:
        return _normalizar_username(valor)


class UsuarioUpdate(BaseModel):
    nome: str | None = None
    username: str | None = None
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

    @field_validator("username")
    @classmethod
    def _username(cls, valor: str | None) -> str | None:
        return _normalizar_username(valor)


def _username_em_uso(db: Session, username: str, exceto_id: int | None = None) -> bool:
    consulta = select(Usuario).where(Usuario.username == username)
    if exceto_id is not None:
        consulta = consulta.where(Usuario.id != exceto_id)
    return db.execute(consulta).scalar_one_or_none() is not None


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
    usuario: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db),
):
    """Admin vê todos; coordenador vê a si e aos professores (para gerar as
    senhas deles); professor vê apenas a própria conta. A GESTÃO (criar,
    editar, excluir) continua exclusiva do admin."""
    consulta = select(Usuario).where(Usuario.escola_id == escola_id)
    e_admin = usuario.is_global or usuario.cargo == "admin"
    if not (e_admin and incluir_excluidos):
        consulta = consulta.where(Usuario.status != "excluido")
    if not e_admin:
        if usuario.cargo == "coordenador":
            consulta = consulta.where(
                (Usuario.id == usuario.id) | (Usuario.cargo == "professor"))
        else:
            consulta = consulta.where(Usuario.id == usuario.id)
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
    if dados.username and _username_em_uso(db, dados.username):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"O nome de usuário “@{dados.username}” já está em uso.")

    novo = Usuario(escola_id=escola_id, nome=dados.nome.strip(), email=email,
                   username=dados.username,
                   senha_hash=hash_senha(dados.senha),
                   senha_visivel=cifrar_senha_visivel(dados.senha),
                   cargo=dados.cargo)
    db.add(novo)
    try:
        db.flush()
        registrar(db, "usuario.criado", escola_id=escola_id, usuario_id=usuario.id,
                  entidade="usuario", entidade_id=novo.id,
                  detalhes={"email": email, "cargo": dados.cargo})
        db.commit()
    except IntegrityError:
        # Corrida com outra gravação simultânea: o índice único decide.
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "E-mail ou nome de usuário já está em uso.")
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
    if dados.nome is not None and dados.nome.strip() != alvo.nome:
        alvo.nome = dados.nome.strip()
        alteracoes["nome"] = alvo.nome
    if "username" in enviados and dados.username != alvo.username:
        if dados.username and _username_em_uso(db, dados.username, exceto_id=alvo.id):
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"O nome de usuário “@{dados.username}” já está em uso.")
        alteracoes["username"] = {"de": alvo.username, "para": dados.username}
        alvo.username = dados.username
    if dados.cargo is not None:
        alteracoes["cargo"] = {"de": alvo.cargo, "para": dados.cargo}
        alvo.cargo = dados.cargo
    if dados.status is not None:
        alteracoes["status"] = {"de": alvo.status, "para": dados.status}
        alvo.status = dados.status
    if dados.senha is not None:
        alvo.senha_hash = hash_senha(dados.senha)
        alvo.senha_visivel = cifrar_senha_visivel(dados.senha)
        # Invalida as sessões abertas do usuário (tokens antigos param de
        # valer) — protege conta comprometida. Na PRÓPRIA conta a sessão
        # continua: trocar a própria senha não pode deslogar o autor na hora.
        if alvo.id != usuario.id:
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
    try:
        db.commit()
    except IntegrityError:
        # Corrida com outra gravação simultânea: o índice único decide.
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "E-mail ou nome de usuário já está em uso.")
    db.refresh(alvo)
    return alvo


# Palavras curtas e sem acento para senhas LEGÍVEIS (faladas por telefone
# sem confusão). TRÊS palavras distintas + 2 dígitos: 40×39×38×90 ≈ 5,3
# milhões de variações (~22 bits) — com o limitador de tentativas por conta
# no login, força bruta remota fica impraticável.
_PALAVRAS_SENHA = (
    "azul", "bosque", "brisa", "canoa", "cedro", "coral", "delta", "duna",
    "farol", "figo", "flor", "fogo", "gaita", "girassol", "ilha", "jade",
    "lago", "lima", "lousa", "lua", "mar", "menta", "monte", "neve",
    "ninho", "nuvem", "onda", "ouro", "pinho", "prata", "rio", "rocha",
    "sol", "trigo", "uva", "vale", "vento", "verde", "vila", "zebra",
)


def _gerar_senha_legivel() -> str:
    import secrets

    palavras: list[str] = []
    restantes = list(_PALAVRAS_SENHA)
    for _ in range(3):
        escolhida = secrets.choice(restantes)
        palavras.append(escolhida)
        restantes.remove(escolhida)
    return f"{'-'.join(palavras)}-{secrets.randbelow(90) + 10}"


def _pode_ver_senha(ator: Usuario, alvo: Usuario) -> bool:
    """Matriz de acesso: admin vê a de todos (da escola); coordenador a
    própria e as dos professores; professor apenas a própria."""
    if ator.id == alvo.id:
        return True
    if ator.is_global or ator.cargo == "admin":
        return True
    return ator.cargo == "coordenador" and alvo.cargo == "professor"


class SenhaVisivelIn(BaseModel):
    # Exigida quando o alvo é a PRÓPRIA conta: um token roubado não pode
    # transformar a sessão em credencial permanente sem provar a senha atual.
    senha_atual: str | None = None


@router.get("/usuarios/{usuario_id}/senha", response_model=dict)
def ver_senha(
    usuario_id: int,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db),
):
    """Mostra a senha ATUAL do usuário, sem trocar nada (matriz por cargo).

    Decisão do dono do produto: uma cópia CIFRADA da senha é guardada a cada
    definição, exclusivamente para esta tela. Senhas definidas antes do
    recurso não têm cópia — nesses casos a resposta indica indisponível e a
    interface oferece gerar uma nova. Toda visualização vai para o log de
    auditoria (sem a senha)."""
    alvo = _usuario_alvo(db, escola_id, usuario_id, usuario)
    if not _pode_ver_senha(usuario, alvo):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Sem permissão para ver a senha deste usuário.")
    if alvo.status == "excluido":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Usuário excluído — restaure a conta antes.")
    senha = decifrar_senha_visivel(alvo.senha_visivel)
    registrar(db, "usuario.senha_visualizada", escola_id=escola_id,
              usuario_id=usuario.id, entidade="usuario", entidade_id=alvo.id,
              detalhes={"email": alvo.email,
                        "disponivel": senha is not None})
    db.commit()
    if senha is None:
        return {"disponivel": False,
                "mensagem": "Esta senha foi definida antes do recurso de "
                            "visualização e não pode ser exibida. Gere uma "
                            "senha nova (ou altere-a) para que fique visível "
                            "daqui em diante."}
    return {"disponivel": True, "senha": senha}


@router.post("/usuarios/{usuario_id}/senha", response_model=dict)
def gerar_senha_visivel(
    usuario_id: int,
    dados: SenhaVisivelIn | None = None,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db),
):
    """Gera uma senha nova LEGÍVEL e a devolve UMA única vez.

    As senhas atuais não são armazenadas em texto — só o embaralhado
    irreversível (proteção padrão: nem o sistema conhece a senha). "Ver a
    senha" significa, portanto, gerar uma nova e mostrá-la na hora."""
    from app.core.security import verificar_senha

    alvo = _usuario_alvo(db, escola_id, usuario_id, usuario)
    if not _pode_ver_senha(usuario, alvo):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Sem permissão para ver a senha deste usuário.")
    if alvo.status == "excluido":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Usuário excluído — restaure a conta antes.")
    if alvo.id == usuario.id:
        senha_atual = (dados.senha_atual if dados else None) or ""
        if not verificar_senha(senha_atual, alvo.senha_hash):
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Informe a sua senha atual para gerar uma nova.")

    senha = _gerar_senha_legivel()
    alvo.senha_hash = hash_senha(senha)
    alvo.senha_visivel = cifrar_senha_visivel(senha)
    if alvo.id != usuario.id:
        # Sessões antigas do alvo caem (proteção). Na PRÓPRIA conta a sessão
        # atual continua — senão o clique em "ver senha" derrubaria o usuário.
        alvo.token_version = (alvo.token_version or 0) + 1
    registrar(db, "usuario.senha_gerada", escola_id=escola_id,
              usuario_id=usuario.id, entidade="usuario", entidade_id=alvo.id,
              detalhes={"email": alvo.email})  # a senha NUNCA vai para o log
    db.commit()
    return {"senha": senha,
            "mensagem": "Senha nova gerada. Anote agora — ela não poderá ser "
                        "vista depois."}


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
