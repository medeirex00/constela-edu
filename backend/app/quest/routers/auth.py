"""Entrada do aluno no Quest: código falável (SEM senha) ou QR do cartão.

Fluxo em duas etapas: a criança digita o código, vê o próprio nome/avatar
("É você?") e confirma — errar o código nunca a joga na conta de outra
pessoa sem perceber. O código é a credencial (decisão de produto, como no
Elefante Letrado); a defesa contra abuso é o limite de tentativas por código,
por (código, IP), por IP e GLOBAL — PERSISTENTE no banco (vale entre workers e
sobrevive ao restart), com uma camada em memória na frente que barra rajadas sem
ida ao banco. As duas camadas usam o MESMO teto/janela (os limitadores abaixo).

Teto GLOBAL (``limitador_global_falha``): os tetos por IP não veem a varredura
distribuída (cada IP fica abaixo do seu teto). Somando as falhas de TODOS os IPs
no /quem e no /entrar (o 403 de inativo só no 1º toque de cada (código, IP) na
janela), ao chegar a QUEST_LIMITE_GLOBAL_FALHAS na janela o login
por CÓDIGO da API inteira responde 429 até o fim do bloqueio (checado antes de
procurar o código: a mesma resposta para código válido ou não, sem oráculo) e sai
um log de alerta. Trade-off aceito: sob ataque, as crianças também esperam a
janela — por isso o teto fica muito acima das falhas de uso real, só FALHAS
contam (login certo não), o 429 não realimenta o contador (o bloqueio acaba com a
janela) e o QR do cartão (~192 bits, não adivinhável) fica fora do teto global e
segue entrando. Alternativa recusada: liberar IPs com login recente durante o
bloqueio — um único código válido conhecido "carimbaria" IPs novos e anularia o
teto.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rate_limit import (
    LimitadorTentativas,
    ip_do_cliente,
    mascarar_ip,
    rede_para_limite,
)
from app.quest import schemas
from app.quest.config import config_quest
from app.quest.deps import exigir_quest_aluno_habilitado
from app.quest.models import QuestCredencialAluno
from app.quest.services import credenciais as svc
from app.quest.services import limites
from app.quest.services import perfis as svc_perfis
from app.services.audit import registrar

router = APIRouter(prefix="/quest/auth", tags=["Quest — Autenticação"],
                   dependencies=[Depends(exigir_quest_aluno_habilitado)])
logger = logging.getLogger("constela.quest")

# Chaveado por (código, IP): o erro de digitação de uma criança nunca pune a
# turma inteira atrás do NAT da escola (um único IP público para 30 tablets).
limitador_codigo = LimitadorTentativas(max_tentativas=8, janela_s=300)
# Teto largo por IP para REVELAÇÃO de nome (/quem) — contra colheita em massa.
limitador_ip = LimitadorTentativas(max_tentativas=300, janela_s=300)
# Por CÓDIGO (sem IP): freia adivinhação de UM código específico mesmo com o
# atacante trocando de IP. Seguro: acertar o código já dá acesso (é a
# credencial), então travá-lo não é pior que o modelo de produto atual.
limitador_codigo_conta = LimitadorTentativas(max_tentativas=20, janela_s=900)
# Anti-ENUMERAÇÃO por IP: conta as tentativas com código INEXISTENTE (401, toda
# vez) e o 403 de aluno INATIVO só UMA vez por (código, IP) na janela
# (``_FALHA_INATIVO_PRIMEIRA``). Um ataque de adivinhação por força-bruta é quase
# 100% de erros (cada palpite toca um código distinto, escapando dos limitadores
# por-código), então esta é a rede que o barra a partir de um único IP —
# importante porque, na topologia real (API no Railway, sem nginx na frente), NÃO
# há limite de borda. Cada código inativo DIFERENTE continua custando 1 aqui; o
# mesmo cartão inativo tocado de novo não soma (não revela nada novo), para que
# algumas crianças inativas insistindo atrás do NAT da escola não esgotem o teto
# da sala. O teto é generoso para uma sala inteira com alguns erros de digitação,
# mas milhares de vezes menor que o espaço de códigos. Com a camada persistente,
# o teto vale para a API inteira (todos os workers) e não volta a zero num deploy.
limitador_ip_falha = LimitadorTentativas(max_tentativas=50, janela_s=300)
# GLOBAL (todos os IPs somados, uma chave só): freia a varredura distribuída que
# fica abaixo do teto de cada IP. Ver o docstring do módulo (trade-off).
limitador_global_falha = LimitadorTentativas(
    max_tentativas=config_quest.QUEST_LIMITE_GLOBAL_FALHAS,
    janela_s=config_quest.QUEST_LIMITE_GLOBAL_JANELA_S)
# Valor único da dimensão global (a "chave" dela vale para a API inteira).
_GLOBAL = "*"
# No máximo UM alerta por janela em cada processo: sob ataque, toda falha que
# passa do teto chegaria ao alerta.
_alerta_global = LimitadorTentativas(
    max_tentativas=1, janela_s=config_quest.QUEST_LIMITE_GLOBAL_JANELA_S)

# Dimensão persistente → limitador que define teto e janela dela.
_DIMENSOES = {
    "codigo_ip": limitador_codigo,
    "ip": limitador_ip,
    "codigo": limitador_codigo_conta,
    "ip_falha": limitador_ip_falha,
    "global_falha": limitador_global_falha,
}

# O código digitado não existe (401). Todas as dimensões contam numa instrução só,
# fora da transação da requisição (``_Tentativa.contar``).
_FALHA_CODIGO = ("codigo_ip", "codigo", "ip", "ip_falha", "global_falha")
# O código existe, mas o aluno está inativo (403). Antes o 403 não gastava
# orçamento nenhum e respondia "este código existe" de graça; agora:
# - o (código, IP) conta em TODO toque: o 9º toque do mesmo cartão no mesmo IP na
#   janela já é 429 ("Ufa, quantas tentativas", não um erro da criança);
# - o anti-enumeração por IP e o global contam só no PRIMEIRO 403 de cada
#   (código, IP) na janela do (código, IP) — quem é a "primeira" é o contador
#   persistente, atômico entre workers. Varrer códigos DIFERENTES custa 1 por
#   código, como o 401; repetir o mesmo cartão não soma. Sem isto, 7 crianças
#   inativas insistindo 8x cada atrás do NAT da escola (56 falhas) esgotavam o
#   teto do IP (50) e travavam a sala inteira, inclusive o QR dos colegas.
# Não conta no teto do código sozinho: não há conta a proteger num cartão que não
# entra. A ordem em que o banco trava as linhas é a de ``limites`` (a da chave), a
# mesma em todos os pedidos: sem deadlock.
_FALHA_INATIVO_SEMPRE = ("codigo_ip",)
_FALHA_INATIVO_PRIMEIRA = ("ip_falha", "global_falha")

ERRO_CODIGO = "Não encontrei esse código. Confira o cartão e tente de novo!"
ERRO_INATIVO = ("Seu cartão está descansando! Peça um cartão novo "
                "na sua escola.")
ERRO_MUITAS = "Ufa, quantas tentativas! Descanse um pouquinho e tente de novo."

# Prefixo da "conta" das tentativas por QR. O código normalizado só tem A–Z e 0–9,
# então nenhum valor com "|" coincide com ele: sem isto, mandar o CÓDIGO de uma
# criança como qr_token (aceito a partir de 8 caracteres) somava falhas na chave
# do código dela — e, com o limite persistente, travava o /quem e o /entrar dela
# na API inteira, sobrevivendo a deploys.
_CONTA_QR = "qr|"


class _Tentativa:
    """As chaves desta requisição nas duas camadas (memória e banco).

    ``conta`` é o código digitado (normalizado) ou ``_CONTA_QR`` + o prefixo do
    QR: identifica a conta-alvo, e as duas formas nunca se misturam. Nenhum valor
    vai em texto para o banco (limites.chave = HMAC).

    ``rede`` é o cliente nas dimensões por IP: o IPv4 inteiro (igual a antes) ou a
    rede /64 do IPv6 (``rede_para_limite``) — trocar de endereço dentro do mesmo
    /64 não renova o orçamento. ``ip`` (completo) só alimenta o log mascarado.

    ``com_global=False`` (só o QR) tira a requisição do teto global: nem é
    barrada por ele nem conta nele."""

    def __init__(self, request: Request, conta: str, *,
                 com_global: bool = True) -> None:
        self.ip = ip_do_cliente(request)
        self.rede = rede_para_limite(self.ip,
                                     config_quest.QUEST_LIMITE_PREFIXO_IPV6)
        self.conta = conta
        self.codigo_ip = f"{conta}|{self.rede}"
        self._valores = {"codigo_ip": self.codigo_ip, "ip": self.rede,
                         "codigo": conta, "ip_falha": self.rede,
                         "global_falha": _GLOBAL}
        self._dimensoes = tuple(d for d in _DIMENSOES
                                if com_global or d != "global_falha")

    def _chave(self, dimensao: str) -> str:
        return limites.chave(dimensao, self._valores[dimensao])

    def exigir_liberada(self, db: Session) -> None:
        """429 se QUALQUER dimensão estiver bloqueada — checado ANTES de procurar
        o código, e com a mesma resposta exista o código ou não (sem enumeração)."""
        em_memoria = any(_DIMENSOES[d].bloqueado(self._valores[d])
                         for d in self._dimensoes)
        if em_memoria or limites.bloqueado(
                db, [self._chave(d) for d in self._dimensoes]):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, ERRO_MUITAS)

    def contar(self, db: Session, *dimensoes: str) -> int:
        """Conta 1 tentativa nas dimensões dadas, nas duas camadas. Devolve as
        falhas da janela (no banco, já com esta) da ÚLTIMA dimensão contada (0 se
        nenhuma).

        No banco é UMA instrução para todas as dimensões, em AUTOCOMMIT e fora da
        transação da requisição (``limites.contar``): chamar DEPOIS do commit da
        sessão, sem ela segurar conexão. Antes cada dimensão era contada dentro da
        transação, e a linha ``global_falha`` (uma só para a API inteira) ficava presa
        até o commit: as falhas passavam em fila por ela (G_CARGA-1). Se uma linha
        estiver presa além do prazo, conta só na memória (e devolve o que a memória
        deste processo sabe)."""
        contadas = [d for d in dimensoes if d in self._dimensoes]
        if not contadas:
            return 0
        for dimensao in contadas:
            _DIMENSOES[dimensao].registrar_falha(self._valores[dimensao])
        try:
            no_banco = limites.contar(db, [
                limites.Limite(self._chave(d), _DIMENSOES[d].max_tentativas,
                               _DIMENSOES[d].janela_s) for d in contadas])
            falhas = {d: no_banco[self._chave(d)] for d in contadas}
        except limites.LimiteIndisponivel:
            falhas = {d: _DIMENSOES[d].falhas_na_janela(self._valores[d])
                      for d in contadas}
        if "global_falha" in falhas and (
                falhas["global_falha"] >= limitador_global_falha.max_tentativas
                or limitador_global_falha.bloqueado(_GLOBAL)):
            _alertar_limite_global(falhas["global_falha"])
        return falhas[contadas[-1]]

    def contar_inativo(self, db: Session) -> None:
        """Conta o 403 de aluno inativo, depois de commitar a sessão (a contagem é
        fora da transação, como no 401): ``_FALHA_INATIVO_SEMPRE`` em todo toque;
        ``_FALHA_INATIVO_PRIMEIRA`` só quando este é o 1º toque do (código, IP) na
        janela (o contador do banco voltou 1 — o incremento é atômico, só UM pedido
        vê o 1)."""
        db.commit()
        if self.contar(db, *_FALHA_INATIVO_SEMPRE) == 1:
            self.contar(db, *_FALHA_INATIVO_PRIMEIRA)

    def limpar_conta(self, db: Session) -> None:
        """Login certo zera os contadores da CONTA (não os do IP)."""
        limitador_codigo.limpar(self.codigo_ip)
        limitador_codigo_conta.limpar(self.conta)
        limites.limpar(db, [self._chave("codigo_ip"), self._chave("codigo")])


def _alertar_limite_global(falhas: int) -> None:
    """Log de ALERTA estruturado quando o teto global é atingido (no máximo um por
    janela em cada processo). Sem IP nem código: o ataque é distribuído, e o
    código digitado é credencial de menor."""
    if _alerta_global.bloqueado(_GLOBAL):
        return
    _alerta_global.registrar_falha(_GLOBAL)
    logger.warning("quest_limite_global_atingido", extra={
        "evento": "quest.limite_global_atingido",
        "alerta": "seguranca",
        "falhas_na_janela": falhas,
        "teto": limitador_global_falha.max_tentativas,
        "janela_s": limitador_global_falha.janela_s,
        "efeito": ("login por código (/quest/auth/quem e /entrar) responde 429 "
                   "até o fim do bloqueio; o QR do cartão segue entrando"),
    })


def _montar_perfil(credencial: QuestCredencialAluno, perfil,
                   aluno) -> schemas.PerfilOut:
    saida = schemas.PerfilOut.model_validate(perfil)
    saida.nome_exibicao = (perfil.nome_exibicao or "").strip()
    saida.nome = svc_perfis.nome_para_falas(perfil, aluno.nome)
    saida.codigo_login = svc.codigo_para_exibicao(credencial)
    if credencial.ultimo_acesso is not None:
        delta = datetime.now(timezone.utc) - credencial.ultimo_acesso.replace(
            tzinfo=credencial.ultimo_acesso.tzinfo or timezone.utc)
        saida.dias_sem_jogar = max(0, delta.days)
    return saida


def _checar_credencial(credencial: QuestCredencialAluno | None,
                       falha_conta, falha_inativo) -> QuestCredencialAluno:
    """401 para código inexistente; mensagem PRÓPRIA para aluno inativo — a
    criança que decorou o código não pode achar que errou ela: transferência/
    arquivamento não é culpa dela. As duas saídas contam tentativa (cada uma nas
    suas dimensões: ``_FALHA_CODIGO`` / ``_Tentativa.contar_inativo``)."""
    if credencial is None or credencial.aluno is None:
        falha_conta()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, ERRO_CODIGO)
    if credencial.aluno.status != "ativo":
        falha_inativo()
        raise HTTPException(status.HTTP_403_FORBIDDEN, ERRO_INATIVO)
    return credencial


def _sessao(db: Session, credencial: QuestCredencialAluno, request: Request,
            via: str) -> schemas.SessaoOut:
    aluno = credencial.aluno
    perfil = svc_perfis.obter_ou_criar_perfil(db, aluno)
    primeira_vez = credencial.ultimo_acesso is None
    saida_perfil = _montar_perfil(credencial, perfil, aluno)
    credencial.ultimo_acesso = datetime.now(timezone.utc)
    # IP da criança MASCARADO no log permanente (LGPD/minimização — §12 §9);
    # a criança já é identificada por entidade_id=aluno.id.
    registrar(db, "quest.login", escola_id=credencial.escola_id,
              entidade="aluno", entidade_id=aluno.id,
              detalhes={"via": via, "ip": mascarar_ip(ip_do_cliente(request))})
    db.commit()
    return schemas.SessaoOut(
        access_token=svc.criar_token_aluno(credencial),
        primeira_vez=primeira_vez,
        perfil=saida_perfil,
    )


@router.post("/quem", response_model=schemas.QuemOut)
def quem(dados: schemas.QuemIn, request: Request, db: Session = Depends(get_db)):
    """Etapa 1 — "É você?": devolve nome/avatar do dono do código."""
    tentativa = _Tentativa(request, svc.normalizar_codigo(dados.codigo))
    tentativa.exigir_liberada(db)

    def falhou():
        # código inexistente → conta também no anti-enumeração por IP. A contagem é
        # fora da transação: o commit antes solta a conexão da sessão.
        db.commit()
        tentativa.contar(db, *_FALHA_CODIGO)

    credencial = _checar_credencial(svc.buscar_por_codigo(db, tentativa.conta),
                                    falhou, lambda: tentativa.contar_inativo(db))
    perfil = svc_perfis.obter_ou_criar_perfil(db, credencial.aluno)
    saida = schemas.QuemOut(
        nome=svc_perfis.nome_para_falas(perfil, credencial.aluno.nome),
        apelido=perfil.apelido,
        avatar=perfil.avatar or {},
    )
    db.commit()
    # Anti-enumeração: revelar um nome conta contra o teto POR IP (limitador_ip).
    # Colher nomes em massa de um mesmo IP é barrado; a criança que confirma o
    # próprio código 1-2x não chega perto do teto. Depois do commit: a contagem é
    # fora da transação e a sessão não pode estar segurando conexão.
    tentativa.contar(db, "ip")
    return saida


@router.post("/entrar", response_model=schemas.SessaoOut)
def entrar(dados: schemas.EntrarIn, request: Request,
           db: Session = Depends(get_db)):
    """Etapa 2 — cria a sessão do aluno (o código é a credencial)."""
    tentativa = _Tentativa(request, svc.normalizar_codigo(dados.codigo))
    tentativa.exigir_liberada(db)

    def falhou():
        # NÃO gravar o código digitado (credencial de menor, near-miss) e
        # mascarar o IP no log permanente (LGPD/minimização — §12 §9/§15).
        registrar(db, "quest.login_falhou",
                  detalhes={"ip": mascarar_ip(tentativa.ip)})
        db.commit()
        # Depois do commit: a contagem é fora da transação (uma instrução só, em
        # AUTOCOMMIT), e a sessão não segura conexão enquanto ela roda.
        tentativa.contar(db, *_FALHA_CODIGO)

    credencial = _checar_credencial(svc.buscar_por_codigo(db, tentativa.conta),
                                    falhou, lambda: tentativa.contar_inativo(db))
    tentativa.limpar_conta(db)
    return _sessao(db, credencial, request, via="codigo")


@router.post("/entrar-qr", response_model=schemas.SessaoOut)
def entrar_qr(dados: schemas.EntrarQrIn, request: Request,
              db: Session = Depends(get_db)):
    # Fora do teto global: o QR não é adivinhável e é a porta que fica aberta
    # para as crianças enquanto o login por código estiver suspenso.
    tentativa = _Tentativa(request, _CONTA_QR + dados.qr_token[:16],
                           com_global=False)
    tentativa.exigir_liberada(db)

    credencial = svc.buscar_por_qr(db, dados.qr_token)
    if credencial is None or credencial.aluno is None:
        # Mesmas dimensões de antes da camada persistente (sem o anti-enumeração
        # por IP: o QR tem ~192 bits, palpite não é ameaça real).
        db.commit()
        tentativa.contar(db, "codigo_ip", "codigo", "ip")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "Esse QR não funcionou. Peça um cartão novo!")
    if credencial.aluno.status != "ativo":
        # Sem contar: o 403 só sai para quem já tem o QR (~192 bits) — não é
        # oráculo de adivinhação, ao contrário do código digitado.
        raise HTTPException(status.HTTP_403_FORBIDDEN, ERRO_INATIVO)
    return _sessao(db, credencial, request, via="qr")
