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
from datetime import datetime, timedelta, timezone

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

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import escola_autorizada, exigir_papeis, get_usuario_atual
from app.core.security import (
    gerar_token_reset,
    hash_senha,
    hash_token,
    validar_forca_senha,
)
from app.models import (
    Configuracao,
    ConversaIA,
    DispositivoMovel,
    Importacao,
    LogAuditoria,
    MensagemIA,
    Professor,
    TokenResetSenha,
    Turma,
    Usuario,
)
from app.schemas import UsuarioOut
from app.services import backup as svc_backup
from app.services import professores as prof_svc
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


class TurmasDoProfessor(BaseModel):
    """Ids das turmas designadas a um professor (vínculo do RBAC por turma)."""
    turma_ids: list[int] = Field(default_factory=list)


class CorrigirDuplicados(BaseModel):
    """Ids dos professores (os que SAEM) das fusões que o gestor confirmou."""
    loser_ids: list[int] = Field(default_factory=list)


def _username_em_uso(db: Session, username: str, exceto_id: int | None = None) -> bool:
    # Comparação CASE-INSENSÍVEL: o @ das professoras é guardado em CamelCase
    # (ex.: "PaulaNogueira") e o login casa por minúsculas — sem isto, um admin
    # poderia criar "paulanogueira" ao lado de "PaulaNogueira" e o login veria
    # DUAS contas (MultipleResultsFound → 500). `username` já vem normalizado.
    consulta = select(Usuario).where(func.lower(Usuario.username) == username.lower())
    if exceto_id is not None:
        consulta = consulta.where(Usuario.id != exceto_id)
    return db.execute(consulta).first() is not None


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
        # Trocar a senha invalida TODAS as sessões abertas da conta — inclusive a
        # PRÓPRIA e um eventual token roubado. Sem isto, "troquei a senha" não
        # revogava as outras sessões e o invasor mantinha acesso por até 8h.
        # Quem trocou re-entra com a nova senha (mesmo comportamento da
        # redefinição por link, que também rotaciona o token_version).
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


def _pode_redefinir_senha(ator: Usuario, alvo: Usuario) -> bool:
    """Quem pode gerar um link de redefinição para `alvo`: admin, para todos da
    escola; coordenador, para si e para professores; professor, só para si. O
    link NÃO revela senha — apenas deixa o dono da conta escolher uma nova."""
    if ator.id == alvo.id:
        return True
    if ator.is_global or ator.cargo == "admin":
        return True
    return ator.cargo == "coordenador" and alvo.cargo == "professor"


@router.post("/usuarios/{usuario_id}/redefinir-senha", response_model=dict)
def redefinir_senha(
    usuario_id: int,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db),
):
    """Gera um LINK de redefinição de senha (uso único, com validade) e o
    devolve UMA vez para ser entregue ao usuário. Nenhuma senha é exibida nem
    armazenada em texto — o próprio usuário escolhe a nova senha ao abrir o
    link. Links anteriores ainda não usados são invalidados."""
    alvo = _usuario_alvo(db, escola_id, usuario_id, usuario)
    if not _pode_redefinir_senha(usuario, alvo):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Sem permissão para redefinir a senha deste usuário.")
    if alvo.status == "excluido":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Usuário excluído — restaure a conta antes.")

    agora = datetime.now(timezone.utc)
    # Invalida links pendentes do mesmo usuário: só o mais novo vale.
    db.execute(
        update(TokenResetSenha)
        .where(TokenResetSenha.usuario_id == alvo.id,
               TokenResetSenha.usado_em.is_(None))
        .values(usado_em=agora))

    token = gerar_token_reset()
    expira = agora + timedelta(minutes=settings.RESET_SENHA_EXPIRA_MIN)
    db.add(TokenResetSenha(usuario_id=alvo.id, token_hash=hash_token(token),
                           expira_em=expira, criado_por=usuario.id))
    registrar(db, "usuario.reset_solicitado", escola_id=escola_id,
              usuario_id=usuario.id, entidade="usuario", entidade_id=alvo.id,
              detalhes={"email": alvo.email})  # o token NUNCA vai para o log
    db.commit()

    link = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/redefinir-senha?token={token}"
    return {
        "link": link,
        "token": token,
        "expira_em": expira.isoformat(),
        "validade_min": settings.RESET_SENHA_EXPIRA_MIN,
        "mensagem": "Link de redefinição gerado. Entregue-o ao usuário — vale "
                    "uma única vez e expira em "
                    f"{settings.RESET_SENHA_EXPIRA_MIN} minutos.",
    }


# --- Vínculo professor ↔ turmas (PRD §18) -------------------------------------

def _professor_do_usuario(db: Session, escola_id: int, alvo: Usuario,
                          criar: bool = False) -> Professor | None:
    """O registro Professor cujo e-mail casa com o do usuário — é o vínculo que
    o RBAC por turma usa (``permissoes.turmas_permitidas`` faz o mesmo join por
    e-mail). Cria o Professor sob demanda quando a conta foi cadastrada à mão
    (as contas criadas pela importação já vêm com o Professor emparelhado)."""
    email = (alvo.email or "").strip().lower()
    if not email:
        return None
    prof = db.execute(
        select(Professor).where(Professor.escola_id == escola_id,
                                func.lower(Professor.email) == email)
    ).scalars().first()
    if prof is None and criar:
        prof = Professor(escola_id=escola_id, nome=alvo.nome, email=alvo.email)
        db.add(prof)
        db.flush()
    return prof


@router.get("/usuarios/{usuario_id}/turmas", response_model=dict)
def turmas_do_professor(
    usuario_id: int,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Ids das turmas atualmente designadas ao professor (marca as caixas)."""
    alvo = _usuario_alvo(db, escola_id, usuario_id, usuario)
    prof = _professor_do_usuario(db, escola_id, alvo)
    if prof is None:
        return {"turma_ids": []}
    ids = db.execute(
        select(Turma.id).where(Turma.escola_id == escola_id,
                               Turma.professor_id == prof.id)
    ).scalars().all()
    return {"turma_ids": list(ids)}


@router.put("/usuarios/{usuario_id}/turmas", response_model=dict)
def definir_turmas_do_professor(
    usuario_id: int,
    dados: TurmasDoProfessor,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Designa ao professor EXATAMENTE as turmas enviadas: as que saíram da
    lista ficam sem titular. Uma turma tem um titular por vez, mas um professor
    pode ter VÁRIAS turmas. Coordenador da própria escola e admin podem definir;
    a Secretaria (rede) fica de fora (só leitura, barrada em escola_autorizada)."""
    alvo = _usuario_alvo(db, escola_id, usuario_id, usuario)
    if alvo.cargo != "professor":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Só professores precisam de turmas designadas — coordenadores e "
            "administradores já enxergam todas as turmas da escola.")

    pedidos = set(dados.turma_ids)
    # Só turmas REAIS desta escola entram (barra id de outra escola/inexistente).
    validas = set(db.execute(
        select(Turma.id).where(Turma.escola_id == escola_id,
                               Turma.id.in_(pedidos))
    ).scalars().all()) if pedidos else set()
    if pedidos - validas:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Uma ou mais turmas não pertencem a esta escola.")

    # Cria o Professor só se houver turma a designar; para esvaziar, basta o
    # que já existe (se não existe, não há nada a soltar).
    prof = _professor_do_usuario(db, escola_id, alvo, criar=bool(validas))
    atuais = set(db.execute(
        select(Turma.id).where(Turma.escola_id == escola_id,
                               Turma.professor_id == prof.id)
    ).scalars().all()) if prof else set()

    if prof is not None:
        entram, saem = validas - atuais, atuais - validas
        if entram:
            db.execute(update(Turma).where(Turma.id.in_(entram))
                       .values(professor_id=prof.id))
        if saem:
            db.execute(update(Turma).where(Turma.id.in_(saem))
                       .values(professor_id=None))

    registrar(db, "professor.turmas_designadas", escola_id=escola_id,
              usuario_id=usuario.id, entidade="usuario", entidade_id=alvo.id,
              detalhes={"turma_ids": sorted(validas), "email": alvo.email})
    db.commit()
    return {"turma_ids": sorted(validas),
            "mensagem": (f"{len(validas)} turma(s) designada(s) a {alvo.nome}."
                         if validas else
                         f"{alvo.nome} ficou sem turmas designadas.")}


# --- Professores duplicados (limpeza) -----------------------------------------

@router.get("/professores/duplicados", response_model=dict)
def professores_duplicados(
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin")),
    db: Session = Depends(get_db),
):
    """PRÉVIA (não altera nada): UMA linha por candidato a fusão — qual nome sai,
    em qual fica, a confiança (alta/revisar), o novo @/senha e as turmas movidas.
    O gestor marca quais confirmar antes de aplicar."""
    candidatos = prof_svc.plano_deduplicacao(db, escola_id)
    return {"candidatos": candidatos, "total": len(candidatos),
            "revisar": sum(1 for c in candidatos if c["confianca"] == "revisar")}


@router.post("/professores/duplicados/corrigir", response_model=dict)
def corrigir_professores_duplicados(
    dados: CorrigirDuplicados,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin")),
    db: Session = Depends(get_db),
):
    """Aplica SÓ as fusões confirmadas (``loser_ids``): mantém o nome completo,
    move as turmas, apaga as contas duplicadas e padroniza @/senha na convenção.
    Devolve a FOLHA DE CREDENCIAIS (nome · @ · senha) para o gestor entregar —
    a senha só trafega nesta resposta, nunca vai para o log."""
    folha = prof_svc.aplicar_deduplicacao(db, escola_id, dados.loser_ids)
    registrar(db, "professor.duplicados_corrigidos", escola_id=escola_id,
              usuario_id=usuario.id, entidade="escola", entidade_id=escola_id,
              detalhes={"fusoes": len(folha)})  # só a contagem — nunca a senha
    db.commit()
    return {"folha": folha, "corrigidos": len(folha),
            "mensagem": (f"{len(folha)} professor(es) unificado(s)." if folha
                         else "Nenhuma fusão aplicada.")}


@router.post("/professores/padronizar-usuarios", response_model=dict)
def padronizar_usuarios_professores(
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin")),
    db: Session = Depends(get_db),
):
    """Coloca o @ de TODAS as professoras na convenção (PrimeiroÚltimo, maiúsculas)
    — as contas antigas ficaram minúsculas. Conta já usada só re-caixa o @ (login
    é case-insensível, senha mantida); conta nunca usada regenera @ + senha.
    Devolve a folha de credenciais (senha só trafega aqui, nunca no log)."""
    folha = prof_svc.padronizar_usernames(db, escola_id)
    registrar(db, "professor.usuarios_padronizados", escola_id=escola_id,
              usuario_id=usuario.id, entidade="escola", entidade_id=escola_id,
              detalhes={"contas": len(folha)})  # só a contagem — nunca a senha
    db.commit()
    return {"folha": folha, "ajustados": len(folha),
            "mensagem": (f"{len(folha)} conta(s) padronizada(s)." if folha
                         else "Todos os @ já estão na convenção.")}


@router.delete("/usuarios/{usuario_id}", response_model=dict)
def excluir_usuario(
    usuario_id: int,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Exclusão LÓGICA: a conta é marcada como excluída e perde o acesso,
    mas histórico, logs, importações e registros vinculados permanecem.
    Coordenador exclui a própria equipe; contas de administrador (e globais,
    já barradas em `_usuario_alvo`) só o administrador pode excluir."""
    alvo = _usuario_alvo(db, escola_id, usuario_id, usuario)
    if usuario.cargo != "admin" and not usuario.is_global and alvo.cargo == "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Apenas um administrador pode excluir a conta de "
                            "outro administrador.")
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
    logos = scoring.obter_config(db, escola_id, "aparencia", "logos", {})
    return {
        "cor_primaria": valores.get("cor_primaria", "#1B2A4A"),
        "mostrar_fotos": valores.get("mostrar_fotos", True),
        # Logos da cidade DESTA escola (data URIs) para o certificado/relatórios.
        # Vazios = usa o padrão do piloto (app/marca/) ou só a marca Constela.
        "brasao_data_uri": logos.get("brasao_data_uri", ""),
        "prefeitura_data_uri": logos.get("prefeitura_data_uri", ""),
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


# Logos institucionais POR ESCOLA (brasão da cidade + logo da prefeitura). Ficam
# numa chave SEPARADA ("logos") para que salvar a cor (chave "valores") nunca os
# apague. Entram no topo dos certificados/relatórios em PDF — automático por
# escola/cidade (relatorios.logos_da_escola / _cabecalho_logos).
_LOGO_MAX_BYTES = 3 * 1024 * 1024  # 3 MB no upload (antes de reduzir)


def _row_logos_aparencia(db: Session, escola_id: int) -> Configuracao:
    row = db.execute(
        select(Configuracao).where(
            Configuracao.escola_id == escola_id,
            Configuracao.namespace == "aparencia",
            Configuracao.chave == "logos",
        )
    ).scalar_one_or_none()
    if row is None:
        row = Configuracao(escola_id=escola_id, namespace="aparencia",
                           chave="logos", valor={})
        db.add(row)
    return row


@router.post("/aparencia/logo")
async def enviar_logo_aparencia(
    tipo: str = Query(pattern="^(brasao|prefeitura)$"),
    arquivo: UploadFile = File(...),
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin")),
    db: Session = Depends(get_db),
):
    """Envia o brasão da cidade ou o logo da prefeitura DESTA escola. A imagem é
    reduzida (máx. 400 px) e guardada como data URI, entrando no topo de
    certificados e relatórios em PDF. PNG com fundo transparente fica melhor."""
    conteudo = await arquivo.read()
    if len(conteudo) > _LOGO_MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            "Imagem muito grande (máximo 3 MB).")
    if not (arquivo.content_type or "").startswith("image/"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Envie um arquivo de imagem (PNG, JPG, WEBP…).")
    import base64
    import io

    from PIL import Image
    try:
        imagem = Image.open(io.BytesIO(conteudo)).convert("RGBA")
        imagem.thumbnail((400, 400))
        buffer = io.BytesIO()
        imagem.save(buffer, format="PNG")
        data_uri = ("data:image/png;base64,"
                    + base64.b64encode(buffer.getvalue()).decode("ascii"))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — arquivo não é imagem válida
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Não foi possível ler a imagem enviada.") from exc

    row = _row_logos_aparencia(db, escola_id)
    valor = dict(row.valor or {})
    valor[f"{tipo}_data_uri"] = data_uri
    row.valor = valor
    registrar(db, "aparencia.logo.enviado", escola_id=escola_id,
              usuario_id=usuario.id, detalhes={"tipo": tipo})
    db.commit()
    return {"tipo": tipo, "ok": True}


@router.delete("/aparencia/logo")
def remover_logo_aparencia(
    tipo: str = Query(pattern="^(brasao|prefeitura)$"),
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin")),
    db: Session = Depends(get_db),
):
    """Remove o logo da cidade desta escola (volta ao padrão do piloto/sem logo)."""
    row = _row_logos_aparencia(db, escola_id)
    valor = dict(row.valor or {})
    valor.pop(f"{tipo}_data_uri", None)
    row.valor = valor
    registrar(db, "aparencia.logo.removido", escola_id=escola_id,
              usuario_id=usuario.id, detalhes={"tipo": tipo})
    db.commit()
    return {"tipo": tipo, "removido": True}
