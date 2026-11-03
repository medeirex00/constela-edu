"""Administração (PRD §18): usuários, backup/restauração e aparência.

Tudo aqui exige papel de administrador. Regras de proteção:
  * ninguém desativa, rebaixa ou EXCLUI a própria conta (evita lockout);
  * o último administrador ativo da escola é intocável até existir outro;
  * excluir é LÓGICO por padrão (status "excluido") — histórico, logs e
    importações permanecem intactos; a remoção física é exclusiva de
    administradores globais e exige confirmação extra;
  * usuários nunca entram no backup de dados (restaurar um arquivo antigo
    não pode reverter senhas nem reativar contas desligadas);
  * RESTAURAR backup é exclusivo do Admin Global (substitui livros, leituras,
    faixas, pesos e parâmetros de pontuação); baixar continua com o admin da
    escola.
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

from app.core.config import email_reservado_ao_dono, settings
from app.core.database import get_db
from app.core.deps import (
    escola_autorizada,
    exigir_admin_global,
    exigir_papeis,
    get_usuario_atual,
    negar_secretaria,
)
from app.core.rate_limit import limitador_conta
from app.core.security import (
    gerar_token_reset,
    hash_senha,
    hash_token,
    validar_forca_senha,
    verificar_senha,
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
from app.services import identidade_efetiva
from app.services import professores as prof_svc
from app.services import push as svc_push
from app.services import scoring
from app.services.audit import registrar

# A Secretaria (rede vinculada, não-global) é barrada na RAIZ deste router —
# leitura e escrita, hoje e em qualquer rota que venha a ser acrescentada aqui.
# Motivo: `escola_autorizada` libera GET em QUALQUER escola da rede para ela e
# `exigir_papeis("admin")` só olha o cargo — então `GET /backup` entregava o
# JSON completo da escola (nome civil, data_nascimento e `observacoes`, campo
# livre onde entram laudos) de crianças de qualquer escola do município. Esta
# era a ÚNICA rota de PII de escola fora de `negar_secretaria`; administrar
# usuários, aparência e backup de uma escola é operação DA ESCOLA (mesma régua
# de importacoes/sync/relatorios em main.py). A dependência fica no PRÓPRIO
# router — não no include — para não se perder num futuro re-registro.
router = APIRouter(prefix="/escolas/{escola_id}", tags=["Administração"],
                   dependencies=[Depends(negar_secretaria)])

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
    # O EmailStr aceita até 254 caracteres; a coluna tem 200 (acima disso o
    # PostgreSQL recusava no commit com 500).
    email: EmailStr = Field(max_length=200)
    username: str | None = None
    senha: str = Field(min_length=8, max_length=100)
    cargo: str = "professor"

    @field_validator("senha")
    @classmethod
    def _forca(cls, valor: str, info) -> str:
        erro = validar_forca_senha(valor, info.data.get("email"),
                                   nome=info.data.get("nome"),
                                   usuario=info.data.get("username"))
        if erro:
            raise ValueError(erro)
        return valor

    @field_validator("username")
    @classmethod
    def _username(cls, valor: str | None) -> str | None:
        return _normalizar_username(valor)


class UsuarioUpdate(BaseModel):
    nome: str | None = Field(default=None, max_length=200)  # = coluna e UsuarioCreate
    username: str | None = None
    cargo: str | None = None
    status: str | None = Field(default=None, pattern="^(ativo|inativo)$")
    senha: str | None = Field(default=None, min_length=8, max_length=100)
    # Exigida só quando a conta editada é a de quem pede e vem `senha`
    # (ver `_exigir_senha_atual`). Nunca é gravada nem vai para o log.
    senha_atual: str | None = Field(default=None, max_length=100)

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


class ReautenticacaoIn(BaseModel):
    """Corpo (opcional) do pedido de link de redefinição: a senha ATUAL, exigida
    só quando a pessoa gera o link para a PRÓPRIA conta."""
    senha_atual: str | None = Field(default=None, max_length=100)


class TurmasDoProfessor(BaseModel):
    """Ids das turmas designadas a um professor (vínculo do RBAC por turma)."""
    turma_ids: list[int] = Field(default_factory=list)


class CorrigirDuplicados(BaseModel):
    """Ids dos professores (os que SAEM) das fusões que o gestor confirmou."""
    loser_ids: list[int] = Field(default_factory=list)


def _username_em_uso(db: Session, username: str, exceto_id: int | None = None) -> bool:
    # Comparação CASE-INSENSÍVEL: o @ das professoras é guardado em CamelCase
    # (ex.: "TelmaTestelli") e o login casa por minúsculas — sem isto, um admin
    # poderia criar "telmatestelli" ao lado de "TelmaTestelli" e o login veria
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
    # Conta de REDE (Secretaria) hospedada nesta escola: a promoção em
    # `/redes/{id}/usuarios` mantém o `escola_id` de origem, então a conta
    # institucional do município ficava dentro da lista de usuários de UMA
    # escola. Sem esta condição, o administrador local trocava a senha dela
    # (ou gerava link de redefinição, ou a excluía) e passava a LER dashboard,
    # ranking e boletim de TODAS as escolas do município — exatamente o
    # isolamento que `exigir_rede` existe para impedir. Mesma régua de
    # `is_global`: alcance maior que o do ator só o admin global administra.
    # Conta com o e-mail RESERVADO ao dono (ADMIN_GLOBAL_EMAIL) ainda não
    # promovida (o boot a promove a `is_global`): quem trocasse a senha dela,
    # gerasse o link de redefinição ou mudasse o cargo viraria admin global no
    # reboot seguinte. Mesma régua de `is_global`.
    if email_reservado_ao_dono(alvo.email) and not ator.is_global:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Somente administradores globais podem gerenciar "
                            "esta conta.")
    if alvo.rede_id is not None and not ator.is_global:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Esta conta pertence à Secretaria da rede — "
                            "somente administradores globais podem gerenciá-la.")
    return alvo


def _e_ultimo_admin_ativo(db: Session, escola_id: int, alvo: Usuario) -> bool:
    """O alvo é o único admin ativo da escola? (proteção contra lockout)

    Contas globais E contas de REDE (Secretaria) ficam fora da conta: ambas
    têm alcance maior que a escola e não substituem o administrador local —
    contar a Secretaria como "o outro admin" deixaria a escola sem nenhum
    gestor capaz de operá-la (a Secretaria não escreve em escola nenhuma).
    """
    if (alvo.cargo != "admin" or alvo.status != "ativo"
            or alvo.is_global or alvo.rede_id is not None):
        return False
    ativos = db.execute(
        select(func.count()).select_from(Usuario).where(
            Usuario.escola_id == escola_id,
            Usuario.cargo == "admin",
            Usuario.status == "ativo",
            Usuario.is_global.is_(False),
            Usuario.rede_id.is_(None),
        )
    ).scalar_one()
    return ativos <= 1


def _exigir_senha_atual(db: Session, ator: Usuario, senha_atual: str | None) -> None:
    """Trocar a PRÓPRIA senha (PATCH com ``senha`` ou link de redefinição para
    si) exige a senha atual. Sem isto, quem achasse uma sessão aberta (o
    computador compartilhado da sala dos professores) trocava a senha da dona e
    transformava as 8 h do token em posse permanente da conta.

    As falhas contam no limitador da CONTA — o mesmo do /auth/login, pela mesma
    chave (o e-mail) —, então a rota não vira um oráculo de força bruta fora do
    teto do login: com o teto estourado responde 429 sem conferir a senha.

    Chamar ANTES de qualquer alteração no alvo: a falha vai para a auditoria com
    commit."""
    identidade = ator.email
    if limitador_conta.bloqueado(identidade):
        espera = limitador_conta.segundos_restantes(identidade)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"Muitas tentativas. Aguarde {max(1, espera // 60)} "
                            "minuto(s) e tente novamente.")
    if not senha_atual:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Para trocar a sua própria senha, informe a senha atual.")
    if not verificar_senha(senha_atual, ator.senha_hash):
        limitador_conta.registrar_falha(identidade)
        registrar(db, "usuario.reautenticacao_falhou", escola_id=ator.escola_id,
                  usuario_id=ator.id, entidade="usuario", entidade_id=ator.id,
                  detalhes={"email": ator.email})   # a senha digitada NUNCA vai ao log
        db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Senha atual incorreta.")


def _invalidar_links_pendentes(db: Session, usuario_id: int, agora: datetime) -> int:
    """Marca como usados os links de redefinição ainda pendentes da conta.
    Devolve quantos eram."""
    return db.execute(
        update(TokenResetSenha)
        .where(TokenResetSenha.usuario_id == usuario_id,
               TokenResetSenha.usado_em.is_(None))
        .values(usado_em=agora)).rowcount


def _invalidar_links_emitidos(db: Session, criador_id: int, agora: datetime) -> int:
    """Marca como usados os links de redefinição ainda pendentes que a conta
    GEROU para OUTRAS contas (``criado_por``). Devolve quantos eram.

    ``auth._criador_ainda_pode`` só SUSPENDE esses links enquanto o autor está
    inativo, excluído, com outro cargo ou na Secretaria: sem esta invalidação,
    reativar, restaurar ou devolver o cargo ao autor dentro da validade
    (``RESET_SENHA_EXPIRA_MIN``) fazia o MESMO link voltar a definir a senha da
    outra conta — inclusive um link gerado numa sessão roubada, que o admin
    achava ter derrubado ao desativar a conta. O link que a conta gerou para si
    fica com ``_invalidar_links_pendentes``."""
    return db.execute(
        update(TokenResetSenha)
        .where(TokenResetSenha.criado_por == criador_id,
               TokenResetSenha.usuario_id != criador_id,
               TokenResetSenha.usado_em.is_(None))
        .values(usado_em=agora)).rowcount


def _revogar_acessos(db: Session, alvo: Usuario) -> dict:
    """Derruba as sessões abertas (``token_version``), os links de redefinição
    pendentes da conta e os que ela gerou para outras contas — na troca de senha
    pelo admin, em toda mudança de situação (desativar, reativar, restaurar) e na
    exclusão lógica. Sem isto, reativar a conta ressuscitava os JWT emitidos
    antes (válidos até o ``exp``) e os links que ela tinha gerado, e um link
    entregue por engano seguia valendo depois de o admin definir a senha direto
    ou desativar a conta. Mesmas revogações da promoção a Secretaria
    (``rede.py``). Devolve as contagens para a auditoria.

    Conta que SAI de "ativo" (desativada ou excluída — o status já vem trocado
    por quem chama) perde também os aparelhos registrados para push
    (``dispositivos_removidos``): sem isto, o celular de quem perdeu o acesso
    seguia recebendo os avisos da escola, inclusive o primeiro nome da criança.
    Reativar não traz o aparelho de volta; o app registra de novo no login."""
    agora = datetime.now(timezone.utc)
    alvo.token_version = (alvo.token_version or 0) + 1
    revogacao = {
        "sessoes_encerradas": True,
        "links_pendentes_invalidados": _invalidar_links_pendentes(db, alvo.id, agora),
        "links_emitidos_invalidados": _invalidar_links_emitidos(db, alvo.id, agora)}
    if alvo.status != "ativo":
        revogacao["dispositivos_removidos"] = svc_push.remover_aparelhos_da_conta(
            db, alvo.id)
    return revogacao


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
    # A conta do DONO da plataforma (ADMIN_GLOBAL_EMAIL) é promovida a
    # `is_global` no boot: criá-la a partir de UMA escola seria reivindicar o
    # acesso a todas as redes com uma senha escolhida pelo atacante.
    if email_reservado_ao_dono(email) and not usuario.is_global:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Este e-mail é reservado à administração da "
                            "plataforma.")
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
    if dados.senha is not None and alvo.id == usuario.id:
        _exigir_senha_atual(db, usuario, dados.senha_atual)

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
    cargo_mudou = dados.cargo is not None and dados.cargo != alvo.cargo
    if dados.cargo is not None:
        alteracoes["cargo"] = {"de": alvo.cargo, "para": dados.cargo}
        alvo.cargo = dados.cargo
    revogar = False
    if dados.status is not None:
        alteracoes["status"] = {"de": alvo.status, "para": dados.status}
        # Qualquer TRANSIÇÃO (desativar, reativar, restaurar) revoga: sem isto,
        # reativar a conta ressuscitava os JWT emitidos antes da desativação.
        revogar = dados.status != alvo.status
        alvo.status = dados.status
    if dados.senha is not None:
        # Com o nome/@ JÁ atualizados acima: a convenção antiga é a do dono.
        erro = validar_forca_senha(dados.senha, alvo.email, nome=alvo.nome,
                                   usuario=alvo.username)
        if erro:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, erro)
        alvo.senha_hash = hash_senha(dados.senha)
        # Trocar a senha invalida TODAS as sessões abertas da conta — inclusive a
        # PRÓPRIA e um eventual token roubado. Sem isto, "troquei a senha" não
        # revogava as outras sessões e o invasor mantinha acesso por até 8h.
        # Quem trocou re-entra com a nova senha (mesmo comportamento da
        # redefinição por link, que também rotaciona o token_version). O link de
        # redefinição pendente também morre: senão quem o tivesse sobrescrevia a
        # senha que o admin acabou de entregar.
        revogar = True
        alteracoes["senha"] = "redefinida"
    revogacao: dict = {}
    if revogar:
        revogacao = _revogar_acessos(db, alvo)
    elif cargo_mudou:
        # O cargo é o que dava o poder de gerar os links (``_pode_redefinir_senha``):
        # mudou, os links que a conta gerou morrem de vez — senão voltavam a valer
        # quando o cargo antigo fosse devolvido.
        revogacao = {"links_emitidos_invalidados": _invalidar_links_emitidos(
            db, alvo.id, datetime.now(timezone.utc))}

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
              detalhes={**alteracoes, "email": alvo.email, **revogacao})
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
    link NÃO revela senha — apenas deixa o dono da conta escolher uma nova.
    Para si, a rota ainda exige a senha atual (``_exigir_senha_atual``)."""
    if ator.id == alvo.id:
        return True
    if ator.is_global or ator.cargo == "admin":
        return True
    return ator.cargo == "coordenador" and alvo.cargo == "professor"


@router.post("/usuarios/{usuario_id}/redefinir-senha", response_model=dict)
def redefinir_senha(
    usuario_id: int,
    dados: ReautenticacaoIn | None = None,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db),
):
    """Gera um LINK de redefinição de senha (uso único, com validade) e o
    devolve UMA vez para ser entregue ao usuário. Nenhuma senha é exibida nem
    armazenada em texto — o próprio usuário escolhe a nova senha ao abrir o
    link. Links anteriores ainda não usados são invalidados. O link para a
    PRÓPRIA conta exige ``senha_atual`` no corpo."""
    alvo = _usuario_alvo(db, escola_id, usuario_id, usuario)
    if not _pode_redefinir_senha(usuario, alvo):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Sem permissão para redefinir a senha deste usuário.")
    if alvo.status == "excluido":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Usuário excluído — restaure a conta antes.")
    if alvo.status != "ativo":
        # O link de conta inativa não vale no consumo (auth.py) e a reativação
        # o invalidaria: gerá-lo só entregaria um link morto.
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Usuário inativo — reative a conta antes de gerar o link.")
    if alvo.id == usuario.id:
        _exigir_senha_atual(db, usuario, dados.senha_atual if dados else None)

    agora = datetime.now(timezone.utc)
    # Invalida links pendentes do mesmo usuário: só o mais novo vale.
    _invalidar_links_pendentes(db, alvo.id, agora)

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
    # Sessões e links pendentes (os da conta e os que ela gerou) morrem já:
    # restaurar a conta depois não pode devolver a validade a um JWT ou link
    # emitido antes da exclusão.
    revogacao = _revogar_acessos(db, alvo)
    registrar(db, "usuario.excluido", escola_id=escola_id, usuario_id=usuario.id,
              entidade="usuario", entidade_id=alvo.id,
              detalhes={"tipo": "exclusao_logica", "email": alvo.email,
                        "nome": alvo.nome, "cargo": alvo.cargo, **revogacao})
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


# Recusa da restauração: quem não é Admin Global precisa entender POR QUE não
# pode e a quem pedir — "sem permissão" genérico não diz nada ao gestor.
MSG_RESTAURACAO_SO_ADMIN_GLOBAL = (
    "A restauração de backup substitui os livros, as leituras, as faixas de "
    "dificuldade, os pesos e os parâmetros de pontuação da escola pelos do "
    "arquivo, por isso é exclusiva do Admin Global. Peça a restauração a ele."
)


def exigir_admin_global_para_restaurar(
    usuario: Usuario = Depends(get_usuario_atual),
) -> Usuario:
    """``core.deps.exigir_admin_global`` (a REGRA é a de lá — fonte única), só com
    a mensagem que explica o que a restauração substitui."""
    try:
        return exigir_admin_global(usuario)
    except HTTPException as negado:
        raise HTTPException(negado.status_code, MSG_RESTAURACAO_SO_ADMIN_GLOBAL) from None


@router.post("/restaurar")
async def restaurar_backup(
    arquivo: UploadFile = File(...),
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_admin_global_para_restaurar),
    db: Session = Depends(get_db),
):
    """Substitui TODOS os dados pedagógicos da escola pelos do backup.

    EXCLUSIVA DO ADMIN GLOBAL: o arquivo carrega livros, leituras, faixas de
    dificuldade, pesos e parâmetros de pontuação (inclusive o perfil de scoring).
    Restaurá-lo é trocar a régua que decide nota, ranking e premiação — decisão
    que não é do admin da escola, do coordenador, do professor nem da Secretaria
    (esta já barrada na raiz do router). Baixar o backup (GET /backup) continua
    com o admin da escola.

    Não toca nos segredos nem nas travas da sincronização (política de criação de
    aluno e vínculo da escola externa: ``backup.PRESERVADAS_NA_RESTAURACAO``).
    ``avisos`` traz o aviso do D10 quando alguma conta restaurada passou a valer
    também aqui sendo efetiva em outra escola (``identidade_efetiva.
    conferir_restauracao``) e o aviso de quantas crianças excluídas
    permanentemente depois do backup, em qualquer escola, ficaram de fora
    (``backup.restaurar``, LGPD art. 18); lista vazia nos demais casos. Isso vale
    também para o arquivo gerado antes de outra restauração (que troca os ids das
    fichas): ``backup.restaurado`` grava o mapa {id novo: id do arquivo} das fichas
    (só números; preservado do expurgo), e a próxima restauração, nesta ou em outra
    escola, segue essa linhagem. A ficha que o arquivo de outra escola criou aqui é a
    mesma criança: excluída de vez lá, a daqui não volta com um backup gerado antes da
    exclusão (e vice-versa); o aviso diz "nesta ou em outra escola". O backup gerado
    depois da exclusão traz a ficha viva daqui como estava ("depois" pela marca do log
    inteiro, ``log_ate``).
    Ressalva: restauração registrada sem o mapa (anterior a ele) quebra a linhagem — a
    criança excluída depois dela pode voltar sem aviso; confira a exclusão à mão.
    """
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

    # GOVERNANÇA do perfil de scoring (`scoring.perfil`): antes, um admin DE ESCOLA
    # podia restaurar e esta rota preservava o perfil vigente (o backup não podia
    # "plantar" `personalizado`). Com a rota exclusiva do Admin Global esse ramo
    # ficou inalcançável e saiu; o Admin Global restaura o backup como está,
    # perfil incluído — o mesmo comportamento que ele sempre teve.
    # LGPD (art. 18): a criança excluída de vez depois do backup não volta; o aviso
    # (sem nome) vai em ``avisos``, ao lado do D10.
    avisos_lgpd: list[str] = []
    mapa_alunos: dict[int, int] = {}
    try:
        contagem = svc_backup.restaurar(db, escola_id, dados, avisos=avisos_lgpd,
                                        mapa_alunos=mapa_alunos)
    except svc_backup.RestauracaoBloqueada as bloqueio:
        # C-06: a operação destruiria dado que o arquivo não repõe (perfis do
        # Quest, responsáveis, ou tabelas ausentes num backup antigo). Recusar é
        # o comportamento correto — nada foi apagado. 409 e não 400: o arquivo
        # está íntegro; o conflito é com o estado atual da escola.
        db.rollback()
        registrar(db, "backup.restauracao_bloqueada", escola_id=escola_id,
                  usuario_id=usuario.id, detalhes={"perdas": bloqueio.perdas})
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, str(bloqueio))
    except (ValueError, TypeError) as erro:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(erro))
    except (IntegrityError, DataError, StatementError):
        db.rollback()
        logger.exception("Restauração de backup falhou (escola %s)", escola_id)
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "O arquivo de backup contém dados inconsistentes ou duplicados.")

    # D10: a restauração recria fichas e identidades do arquivo — uma ficha
    # excluída depois do backup, cuja conta outra escola vinculou nesse meio-tempo,
    # volta a valer aqui e a conta fica efetiva nas DUAS escolas. A rota já é só do
    # Admin Global, então segue: auditoria própria por conta (sem nome) e o aviso
    # em ``avisos`` (campo novo; lista vazia nos demais casos).
    avisos = avisos_lgpd + list(identidade_efetiva.conferir_restauracao(
        db, escola_id, usuario_id=usuario.id))
    # A linhagem das fichas (só ids): sem ela, um arquivo anterior a ESTA restauração
    # traria de volta a criança excluída de vez depois dela (LGPD art. 18).
    registrar(db, "backup.restaurado", escola_id=escola_id, usuario_id=usuario.id,
              detalhes={"tabelas": contagem, svc_backup.CHAVE_MAPA_ALUNOS: {
                  str(novo): antigo for novo, antigo in mapa_alunos.items()}})
    db.commit()
    scoring.recalcular_escola(db, escola_id)
    total = sum(contagem.values())
    return {"mensagem": f"Backup restaurado: {total} registros. Notas recalculadas.",
            "tabelas": contagem, "avisos": avisos}


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
        # Vazios = só a marca Constela (não há logo de cidade embutido).
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
# Só os formatos que a tela oferece (accept do input). O Image.open sem lista
# tenta TODOS os decodificadores do Pillow (TIFF, EPS, PSD, ICO, PCX…), que são
# a superfície das falhas de segurança do Pillow; com a lista, o resto é recusado
# antes de qualquer decodificação.
_LOGO_FORMATOS = ("PNG", "JPEG", "WEBP")
# Teto de pixels conferido pelo cabeçalho, ANTES de decodificar: 3 MB comprimidos
# podem virar gigabytes na memória (bomba de descompressão). PNG e JPEG: o
# Image.open só lê o cabeçalho. WEBP: o Image.open já cria o decodificador, que
# aloca o canvas declarado — por isso o cabeçalho do WEBP é lido antes, à mão.
_LOGO_MAX_LADO = 4096
_LOGO_GRANDE_DEMAIS = f"Imagem grande demais (máximo {_LOGO_MAX_LADO} × {_LOGO_MAX_LADO} pixels)."


def _dimensoes_webp(conteudo: bytes) -> tuple[int, int] | None:
    """Largura e altura declaradas no cabeçalho de um WEBP, sem decodificar nada.
    None se não for WEBP (ou o cabeçalho for curto demais: o Pillow recusa depois)."""
    if len(conteudo) < 30 or conteudo[:4] != b"RIFF" or conteudo[8:12] != b"WEBP":
        return None
    bloco = conteudo[12:16]
    if bloco == b"VP8X":  # estendido/animado: o CANVAS (24 + 24 bits, menos 1)
        return (1 + int.from_bytes(conteudo[24:27], "little"),
                1 + int.from_bytes(conteudo[27:30], "little"))
    if bloco == b"VP8L":  # sem perda: 14 + 14 bits depois da assinatura 0x2f
        b = conteudo[21:25]
        return (1 + (((b[1] & 0x3F) << 8) | b[0]),
                1 + (((b[3] & 0x0F) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6)))
    if bloco == b"VP8 ":  # com perda: 14 bits cada, depois do código de início 9d 01 2a
        return (int.from_bytes(conteudo[26:28], "little") & 0x3FFF,
                int.from_bytes(conteudo[28:30], "little") & 0x3FFF)
    return None


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
    # No máximo o teto + 1 byte na memória: o arquivo inteiro fica no temporário.
    conteudo = await arquivo.read(_LOGO_MAX_BYTES + 1)
    if len(conteudo) > _LOGO_MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            "Imagem muito grande (máximo 3 MB).")
    if not (arquivo.content_type or "").startswith("image/"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Envie uma imagem PNG, JPG ou WEBP.")
    dimensoes_webp = _dimensoes_webp(conteudo)
    if dimensoes_webp and max(dimensoes_webp) > _LOGO_MAX_LADO:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, _LOGO_GRANDE_DEMAIS)
    import base64
    import io

    from PIL import Image
    try:
        imagem = Image.open(io.BytesIO(conteudo), formats=_LOGO_FORMATOS)
        largura, altura = imagem.size
        if largura > _LOGO_MAX_LADO or altura > _LOGO_MAX_LADO:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, _LOGO_GRANDE_DEMAIS)
        imagem = imagem.convert("RGBA")
        imagem.thumbnail((400, 400))
        buffer = io.BytesIO()
        # Sem o perfil ICC do arquivo enviado: ele passaria intacto para o PNG
        # (um JPEG de 16 px com 2 MB de perfil virava 2 MB no banco e em todo PDF).
        imagem.save(buffer, format="PNG", icc_profile=None)
        data_uri = ("data:image/png;base64,"
                    + base64.b64encode(buffer.getvalue()).decode("ascii"))
    except HTTPException:
        raise
    except Image.DecompressionBombError as exc:  # o Pillow recusou já no cabeçalho
        raise HTTPException(status.HTTP_400_BAD_REQUEST, _LOGO_GRANDE_DEMAIS) from exc
    except Exception as exc:  # noqa: BLE001 — não é PNG/JPG/WEBP válido
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Não foi possível ler a imagem enviada. "
                            "Envie uma imagem PNG, JPG ou WEBP.") from exc

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
