import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.database import get_db, leitura_sem_transacao
from app.core.deps import get_usuario_atual
from app.core.rate_limit import (
    alerta_global_login,
    chave_conta_ip,
    ip_do_cliente,
    liberar_conta,
    limitador_conta,
    limitador_global_falha_login,
    limitador_ip_falha_login,
    limitador_login,
    mascarar_ip,
    rede_para_limite,
)
from app.core.security import (
    criar_token,
    hash_senha,
    hash_token,
    validar_forca_senha,
    verificar_senha,
    verificar_senha_dummy,
)
from app.models import TokenResetSenha, Usuario
from app.schemas import LoginOut, UsuarioOut
from app.services import push as svc_push
from app.services.audit import registrar

router = APIRouter(prefix="/auth", tags=["Autenticação"])
logger = logging.getLogger("constela.auth")

# Maior identificador que uma conta pode ter (colunas: e-mail ≤ 200, @usuário ≤ 30).
_TETO_IDENTIFICADOR = 200
_DESCARTADO = "[descartado]"
# O que o log de auditoria (permanente) guarda do texto digitado quando a conta NÃO
# existe: só o que tem forma de e-mail ou de @usuário. A senha digitada no campo
# errado (com símbolo) não entra na trilha; a trilha de força bruta por e-mail fica.
_FORMA_DE_IDENTIFICADOR = re.compile(
    r"[a-z0-9._%+\-]+@[a-z0-9\-]+(?:\.[a-z0-9\-]+)+|[a-z0-9._\-]{1,30}")


def _identificador_para_log(entrada: str) -> str:
    if len(entrada) <= _TETO_IDENTIFICADOR and _FORMA_DE_IDENTIFICADOR.fullmatch(entrada):
        return entrada
    return _DESCARTADO


# --- Tetos de FALHAS por IP e GLOBAL do login ---------------------------------
# A camada que os limites por (conta, IP) e por conta não veem: a PULVERIZAÇÃO de
# senhas — um IP (ou vários) testando poucas senhas em MUITAS contas, cada uma
# abaixo do seu teto. Conferida ANTES de procurar a conta, com a mesma resposta
# exista a conta ou não (sem oráculo de enumeração). Só FALHAS contam: o login
# certo não soma nem zera o teto do IP (senão uma conta válida conhecida "lavaria"
# o IP a cada acerto), e o 429 não realimenta o contador (o bloqueio acaba com a
# janela). Teto e janela: ``limitador_ip_falha_login`` e
# ``limitador_global_falha_login`` (app.core.rate_limit), configuráveis pelas
# variáveis EDU_LOGIN_TETO_IP_* e EDU_LOGIN_TETO_GLOBAL_* (config.py); as duas
# camadas abaixo leem sempre do limitador, então nunca divergem.
#
# Duas camadas com o MESMO teto e janela, como no login do Quest: a memória barra a
# rajada sem ir ao banco, e o banco faz o teto valer entre os workers e sobreviver
# ao deploy. O banco é a tabela de limites que o Quest já usa
# (``quest_limites_acesso``, migração 0037, serviço app.quest.services.limites) —
# nenhuma tabela nova —, com dimensões PRÓPRIAS do Edu (prefixo ``edu_login_``),
# que nunca se misturam com as do Quest. O IP vai para o banco só como HMAC
# (``limites.chave``), nunca em texto.
_DIM_IP_FALHA = "edu_login_ip_falha"
_DIM_GLOBAL_FALHA = "edu_login_global_falha"
_GLOBAL = "*"   # valor único da dimensão global (vale para a API inteira)

ERRO_MUITAS_GLOBAL = ("O acesso está temporariamente limitado por excesso de "
                      "tentativas na plataforma. Aguarde {minutos} minuto(s) e "
                      "tente novamente.")


def _erro_muitas(espera_s: int) -> str:
    """O texto do 429 por (conta, IP), por conta e por IP (o mesmo de sempre)."""
    return (f"Muitas tentativas. Aguarde {max(1, espera_s // 60) } minuto(s) e "
            "tente novamente.")


def _tetos_de_falha(rede: str):
    """(dimensão, valor, limitador) dos tetos de falha, na ordem da CONTAGEM: o
    global por último — a linha mais disputada fica travada só do UPDATE dela até
    o commit, e todas as transações travam as linhas na mesma ordem."""
    return ((_DIM_IP_FALHA, rede, limitador_ip_falha_login),
            (_DIM_GLOBAL_FALHA, _GLOBAL, limitador_global_falha_login))


def _exigir_tetos_de_falha_livres(db: Session, rede: str, entrada: str,
                                  ip_log: str) -> None:
    """429 se o IP (ou a API inteira) já estourou o teto de falhas. Roda ANTES de
    procurar a conta: a resposta é a mesma para conta existente ou não."""
    from app.quest.services import limites

    estourado: tuple[str, int] | None = None
    for dimensao, valor, limitador in reversed(_tetos_de_falha(rede)):  # global 1º
        if limitador.bloqueado(valor):
            estourado = (dimensao, limitador.segundos_restantes(valor))
            break
    if estourado is None:
        chaves = {d: limites.chave(d, v) for d, v, _ in _tetos_de_falha(rede)}
        if limites.bloqueado(db, list(chaves.values())):
            # Bloqueado só no banco (outro worker, ou antes de um reinício): o
            # bloqueio dura uma janela inteira, que é o teto da espera.
            global_ = limites.bloqueado(db, [chaves[_DIM_GLOBAL_FALHA]])
            limitador = (limitador_global_falha_login if global_
                         else limitador_ip_falha_login)
            estourado = (_DIM_GLOBAL_FALHA if global_ else _DIM_IP_FALHA,
                         limitador.janela_s)
    if estourado is None:
        return
    dimensao, espera = estourado
    e_global = dimensao == _DIM_GLOBAL_FALHA
    registrar(db, "login.bloqueado",
              detalhes={"email": _identificador_para_log(entrada), "ip": ip_log,
                        "motivo": "teto_global" if e_global else "teto_ip"})
    db.commit()
    raise HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        ERRO_MUITAS_GLOBAL.format(minutos=max(1, espera // 60)) if e_global
        else _erro_muitas(espera))


def _contar_falha_nos_tetos(db: Session, rede: str) -> None:
    """Conta 1 falha no teto do IP e no global, nas duas camadas. NÃO commita:
    chamar por último, colado no commit do caminho de erro."""
    from app.quest.services import limites

    falhas_globais = 0
    for dimensao, valor, limitador in _tetos_de_falha(rede):
        limitador.registrar_falha(valor)
        falhas = limites.registrar_falha(
            db, limites.chave(dimensao, valor),
            max_tentativas=limitador.max_tentativas, janela_s=limitador.janela_s)
        if dimensao == _DIM_GLOBAL_FALHA:
            falhas_globais = falhas
    if (falhas_globais >= limitador_global_falha_login.max_tentativas
            or limitador_global_falha_login.bloqueado(_GLOBAL)):
        _alertar_teto_global(falhas_globais)


def _alertar_teto_global(falhas: int) -> None:
    """Log de ALERTA estruturado quando o teto global é atingido (no máximo um por
    janela em cada processo). Sem IP nem conta: o ataque é distribuído."""
    if alerta_global_login.bloqueado(_GLOBAL):
        return
    alerta_global_login.registrar_falha(_GLOBAL)
    logger.warning("login_limite_global_atingido", extra={
        "evento": "login.limite_global_atingido",
        "alerta": "seguranca",
        "falhas_na_janela": falhas,
        "teto": limitador_global_falha_login.max_tentativas,
        "janela_s": limitador_global_falha_login.janela_s,
        "efeito": ("o /auth/login responde 429 a todas as contas até o fim do "
                   "bloqueio; as sessões já abertas seguem valendo"),
    })


@router.post("/login", response_model=LoginOut)
def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    # Aceita e-mail OU nome de usuário (com ou sem o "@" na frente).
    entrada = form.username.lower().strip().lstrip("@")
    if len(entrada) > _TETO_IDENTIFICADOR:
        # Nenhuma conta tem identificador assim. O texto não vira chave dos
        # limitadores (memória) nem linha do log (banco): o multipart aceita ~1 MB
        # por campo e um anônimo mandava um valor novo a cada pedido.
        entrada = _DESCARTADO
    ip = ip_do_cliente(request)         # completo: chave do limitador (precisão)
    ip_log = mascarar_ip(ip)             # mascarado: log de auditoria (LGPD)
    rede = rede_para_limite(ip)          # IPv6 em /64: chave do teto de falhas por IP

    # Tetos de falha por IP e global ANTES de procurar a conta: a mesma resposta
    # para conta existente ou não (ver ``_exigir_tetos_de_falha_livres``).
    _exigir_tetos_de_falha_livres(db, rede, entrada, ip_log)

    usuario = db.execute(
        select(Usuario).where(Usuario.email == entrada)
    ).scalar_one_or_none()
    if usuario is None:
        # Case-insensitive: o @ é guardado em CamelCase (ex.: "TelmaTestelli"),
        # mas a pessoa digita de qualquer jeito — `entrada` já vem em minúsculas.
        # `.first()` com ordem determinística NUNCA estoura 500 se, por dado
        # legado, houver duas variações de caixa do mesmo @ (a criação já barra).
        usuario = db.execute(
            select(Usuario).where(func.lower(Usuario.username) == entrada)
            .order_by(Usuario.id)
        ).scalars().first()

    # O limitador conta pela CONTA (e-mail canônico): tentar pelo e-mail e
    # pelo @username soma no MESMO contador — dois identificadores não podem
    # dobrar o orçamento de força bruta contra a mesma vítima.
    identidade = usuario.email if usuario is not None else entrada
    # Para o LOG: conta inexistente nunca grava o texto cru (``_identificador_para_log``).
    identidade_log = (usuario.email if usuario is not None
                      else _identificador_para_log(entrada))
    chave = chave_conta_ip(identidade, ip)

    # Duas camadas: por (conta, IP) — freio fino — e por CONTA (sem IP) —
    # freio contra força-bruta distribuída (vários IPs) contra a mesma conta.
    # A espera é a do bloqueio que vale: o limitador que não bloqueia dá 0.
    if limitador_login.bloqueado(chave) or limitador_conta.bloqueado(identidade):
        espera = max(limitador_login.segundos_restantes(chave),
                     limitador_conta.segundos_restantes(identidade))
        registrar(db, "login.bloqueado", detalhes={"email": identidade_log, "ip": ip_log})
        db.commit()
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, _erro_muitas(espera))

    if usuario is None:
        # Equaliza o tempo de resposta para não revelar se a conta existe.
        verificar_senha_dummy()
        limitador_login.registrar_falha(chave)
        limitador_conta.registrar_falha(identidade)
        registrar(db, "login.falhou",
                  detalhes={"email": identidade_log, "ip": ip_log,
                            "motivo": "conta_inexistente"})
        _contar_falha_nos_tetos(db, rede)   # por último, colado no commit
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "E-mail/usuário ou senha incorretos.")

    if not verificar_senha(form.password, usuario.senha_hash):
        limitador_login.registrar_falha(chave)
        limitador_conta.registrar_falha(identidade)
        registrar(db, "login.falhou", escola_id=usuario.escola_id, usuario_id=usuario.id,
                  detalhes={"email": identidade, "ip": ip_log, "motivo": "senha_incorreta"})
        _contar_falha_nos_tetos(db, rede)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "E-mail/usuário ou senha incorretos.")

    if _senha_da_convencao_antiga(form.password, usuario):
        # A senha confere, mas é a da convenção abolida (nome/@ + "123"): quem
        # sabe o nome da pessoa sabe a senha. A invalidação das contas antigas é
        # uma etapa manual de deploy (scripts/senhas_derivadas.py); esta trava
        # fecha o login sem depender dela. Conta como falha no limitador.
        limitador_login.registrar_falha(chave)
        limitador_conta.registrar_falha(identidade)
        registrar(db, "login.falhou", escola_id=usuario.escola_id, usuario_id=usuario.id,
                  detalhes={"email": identidade, "ip": ip_log,
                            "motivo": "senha_convencao_antiga"})
        _contar_falha_nos_tetos(db, rede)
        db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Senha expirada: peça um link de redefinição ao "
                            "administrador.")

    if usuario.status != "ativo":
        registrar(db, "login.falhou", escola_id=usuario.escola_id, usuario_id=usuario.id,
                  detalhes={"email": identidade, "ip": ip_log, "motivo": "conta_desativada"})
        db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Usuário desativado.")

    limitador_login.limpar(chave)
    limitador_conta.limpar(identidade)
    usuario.ultimo_acesso = datetime.now(timezone.utc)
    registrar(db, "login", escola_id=usuario.escola_id, usuario_id=usuario.id)
    db.commit()

    return LoginOut(
        access_token=criar_token(usuario.id, usuario.token_version),
        usuario=_com_modulos(db, usuario),
    )


def _senha_da_convencao_antiga(senha: str, usuario: Usuario) -> bool:
    """A senha digitada é uma das que as convenções antigas de professor dariam a
    esta conta (o @ ou o primeiro nome + "123", em qualquer caixa)? Só compara
    strings com o nome/@ ATUAIS da conta — nenhum bcrypt extra no login."""
    # Import tardio: o serviço de professores puxa modelos e segurança.
    from app.services.professores import _senhas_da_convencao_antiga

    candidatas = _senhas_da_convencao_antiga(usuario.nome or "", usuario.username)
    return senha.casefold() in {c.casefold() for c in candidatas}


def _com_modulos(db: Session, usuario: Usuario) -> UsuarioOut:
    """UsuarioOut + os módulos contratados que valem para ele — o frontend monta
    menu/abas/telas a partir disto, sem uma chamada extra no boot."""
    from app.services import modulos as svc_modulos

    saida = UsuarioOut.model_validate(usuario)
    saida.modulos = sorted(svc_modulos.modulos_do_usuario(db, usuario))
    return saida


@router.get("/me", response_model=UsuarioOut)
@leitura_sem_transacao
def me(usuario: Usuario = Depends(get_usuario_atual),
       db: Session = Depends(get_db)):
    return _com_modulos(db, usuario)


# --- Redefinição de senha por token (público: a pessoa não consegue entrar) ---

def _expirado(momento: datetime) -> bool:
    """Compara com o instante atual tolerando datas ingênuas do banco (o SQLite
    não guarda fuso — trata como UTC)."""
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento < datetime.now(timezone.utc)


def _token_valido(db: Session, token_bruto: str | None) -> TokenResetSenha | None:
    """Registro do token se existir, não tiver sido usado e não estiver expirado."""
    if not token_bruto:
        return None
    registro = db.execute(
        select(TokenResetSenha).where(
            TokenResetSenha.token_hash == hash_token(token_bruto))
    ).scalar_one_or_none()
    if (registro is None or registro.usado_em is not None
            or _expirado(registro.expira_em)):
        return None
    return registro


def _criador_ainda_pode(db: Session, registro: TokenResetSenha, alvo: Usuario) -> bool:
    """O link gerado por OUTRA pessoa só vale enquanto ela AINDA poderia gerá-lo.

    A permissão é conferida quando o link é gerado; sem esta segunda conferência
    no uso, um link ainda pendente sobrevivia a uma mudança da conta-alvo (virou
    admin, Secretaria ou global): quem o gerou definia a senha da conta já
    promovida e entrava com o alcance novo. Mesmas regras da geração
    (``admin._usuario_alvo`` e ``admin._pode_redefinir_senha``).

    Sem autor (``criado_por`` nulo) o link não vale: toda geração grava o autor,
    e o nulo só aparece quando a conta de quem gerou foi apagada de vez
    (``ON DELETE SET NULL``) — aceitá-lo devolveria a validade a um link que a
    conferência acima já tinha derrubado."""
    if registro.criado_por is None:
        return False
    if registro.criado_por == alvo.id:
        return True
    from app.core.config import email_reservado_ao_dono
    from app.routers.admin import _pode_redefinir_senha

    criador = db.get(Usuario, registro.criado_por)
    if criador is None or criador.status != "ativo":
        return False
    if criador.is_global:
        return True
    if criador.rede_id is not None or criador.escola_id != alvo.escola_id:
        return False
    if alvo.is_global or alvo.rede_id is not None or email_reservado_ao_dono(alvo.email):
        return False
    return _pode_redefinir_senha(criador, alvo)


def _so_o_admin_global_gera_link(alvo: Usuario | None) -> bool:
    """A conta é de REDE (Secretaria) ou global? Então só o Admin Global da
    plataforma gera o link dela: ``admin._usuario_alvo`` recusa o administrador da
    escola com 403, e a própria Secretaria não entra no router de administração
    (``deps.negar_secretaria``)."""
    return alvo is not None and (alvo.is_global or alvo.rede_id is not None)


def _link_invalido(alvo: Usuario | None) -> HTTPException:
    """400 do link inválido ou expirado, dizendo a QUEM pedir um novo — mandar a
    Secretaria pedir à escola a deixava sem saída (a escola recebe 403)."""
    quem = ("ao Administrador Global da plataforma (a equipe do Constela Edu)"
            if _so_o_admin_global_gera_link(alvo) else "ao administrador da escola")
    return HTTPException(status.HTTP_400_BAD_REQUEST,
                         f"Link inválido ou expirado. Peça um novo {quem}.")


def _dono_do_link(db: Session, token_bruto: str | None) -> Usuario | None:
    """A conta dona do link, mesmo vencido ou já usado (só para dizer a quem pedir
    outro; não autoriza nada). None se o token não existe."""
    if not token_bruto:
        return None
    registro = db.execute(
        select(TokenResetSenha).where(
            TokenResetSenha.token_hash == hash_token(token_bruto))
    ).scalar_one_or_none()
    return db.get(Usuario, registro.usuario_id) if registro is not None else None


class RedefinirSenhaIn(BaseModel):
    token: str = Field(min_length=8, max_length=200)
    nova_senha: str = Field(min_length=8, max_length=100)

    @field_validator("nova_senha")
    @classmethod
    def _forca(cls, valor: str) -> str:
        erro = validar_forca_senha(valor)
        if erro:
            raise ValueError(erro)
        return valor


@router.get("/redefinir-senha/{token}", response_model=dict)
def validar_link_reset(token: str, db: Session = Depends(get_db)):
    """Diz à tela se o link ainda vale (para mostrar o formulário ou avisar que
    expirou). Não revela nada além do primeiro nome, para a saudação."""
    registro = _token_valido(db, token)
    if registro is None:
        return {"valido": False}
    alvo = db.get(Usuario, registro.usuario_id)
    # Só conta ATIVA: o link de conta desativada/excluída não vale (a mudança de
    # situação já o invalida; esta conferência cobre o que escapar disso).
    if alvo is None or alvo.status != "ativo" or not _criador_ainda_pode(db, registro, alvo):
        return {"valido": False}
    # Só o PRIMEIRO nome, para a saudação: a rota é pública (basta o link).
    return {"valido": True, "nome": (alvo.nome or "").split(" ")[0]}


@router.post("/redefinir-senha", response_model=dict)
def consumir_link_reset(dados: RedefinirSenhaIn, db: Session = Depends(get_db)):
    """Define a nova senha a partir do token do link. O token é de USO ÚNICO
    (some assim que a senha é trocada) e todas as sessões antigas caem — a
    senha original nunca é recuperada, apenas substituída.

    Atomicidade com as revogações (desativar, excluir, trocar a senha pelo
    admin, promover a Secretaria, mexer no autor do link): elas gravam a linha
    do USUÁRIO e só depois marcam os tokens pendentes (``UPDATE ... WHERE
    usado_em IS NULL``). Aqui é a MESMA ordem: (1) trava a conta (``FOR
    UPDATE``), (2) marca o token com UPDATE condicional e exige 1 linha, (3) só
    então confere a situação da conta e o autor. Sem isso as conferências eram
    SELECTs comuns e a gravação vinha depois, por chave primária: a revogação
    que commitava nesse intervalo respondia 200 e não valia (a senha que o admin
    acabara de definir era sobrescrita pela do link), e dois consumos
    simultâneos do mesmo link respondiam 200 e 200. Travar o token antes do
    usuário inverteria a ordem das revogações (risco de deadlock no PG).

    No SQLite o ``FOR UPDATE`` não gera SQL (um escritor por vez); lá vale o
    UPDATE condicional. Recusa depois da marcação (conta indisponível, autor sem
    poder, senha fraca) não queima o link: a sessão fecha sem commit."""
    registro = _token_valido(db, dados.token)
    if registro is None:
        raise _link_invalido(_dono_do_link(db, dados.token))
    # O bcrypt (centenas de ms) fica FORA da trava: não depende da conta.
    novo_hash = hash_senha(dados.nova_senha)

    # (1) Trava a conta e relê do banco (``populate_existing``): uma revogação
    # em curso termina antes, e o que se confere abaixo é o estado já gravado.
    alvo = db.get(Usuario, registro.usuario_id, with_for_update=True,
                  populate_existing=True)
    if alvo is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Conta indisponível. Fale com o administrador.")
    # (2) Uso único de verdade: só um pedido marca o token. O que chegou depois
    # de outro consumo — ou de uma revogação, que também marca — recebe 0 linhas.
    marcado = db.execute(
        update(TokenResetSenha)
        .where(TokenResetSenha.id == registro.id,
               TokenResetSenha.usado_em.is_(None))
        .values(usado_em=datetime.now(timezone.utc))
        .execution_options(synchronize_session=False)).rowcount
    if marcado != 1:
        raise _link_invalido(alvo)
    # (3) Conferências DEPOIS da trava (conta desativada ou promovida no meio).
    if alvo.status != "ativo":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Conta indisponível. Fale com o administrador.")
    if not _criador_ainda_pode(db, registro, alvo):
        raise _link_invalido(alvo)
    # A regra que depende do DONO da conta (o validador do corpo não o conhece).
    erro = validar_forca_senha(dados.nova_senha, alvo.email, nome=alvo.nome,
                               usuario=alvo.username)
    if erro:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, erro)

    alvo.senha_hash = novo_hash
    # Lido sob a trava: nenhuma revogação concorrente perde o incremento.
    alvo.token_version = (alvo.token_version or 0) + 1  # derruba sessões antigas
    # Os aparelhos (push) saem com as sessões, como na troca pelo admin
    # (``admin._revogar_acessos``): o celular perdido, cuja sessão cai agora, não
    # segue recebendo os avisos da escola. O app registra de novo no login.
    removidos = svc_push.remover_aparelhos_da_conta(db, alvo.id)
    email = alvo.email
    registrar(db, "usuario.senha_redefinida_por_token", escola_id=alvo.escola_id,
              usuario_id=alvo.id, entidade="usuario", entidade_id=alvo.id,
              detalhes={"email": email, "dispositivos_removidos": removidos})
    db.commit()
    # "Já pode entrar" vale de verdade: quem errou a senha até travar o login
    # entra com a nova (o link prova a posse da conta, como o login certo).
    liberar_conta(email)
    return {"mensagem": "Senha redefinida. Você já pode entrar com a nova senha."}
