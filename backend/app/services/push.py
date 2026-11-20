"""Notificações push via Expo Push Service.

Decisão: o app mobile é Expo/React Native, então usamos o serviço de push
do Expo — um único endpoint HTTPS cobre Android (FCM) e iOS (APNs) sem a
escola precisar de contas no Firebase/Apple. O envio é SEMPRE melhor
esforço: falha de push jamais derruba a operação principal (importação,
recálculo etc.).
"""
from __future__ import annotations

import logging
import re

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import impressao_da_chave_de_sessao
from app.models import Configuracao, DispositivoMovel, Escola, Usuario
from app.services import permissoes
from app.services.audit import registrar

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
TAMANHO_LOTE = 100  # limite documentado do Expo por requisição

# Formato do token que o app recebe de ``Notifications.getExpoPushTokenAsync``:
# ``ExponentPushToken[...]`` (ou a grafia nova ``ExpoPushToken[...]``), sem espaço
# nem colchete dentro. ``/dispositivos`` só aceita isto; texto fora do formato não
# identifica aparelho nenhum — não vai ao Expo e sai do banco (``notificar_escola``).
PADRAO_TOKEN_EXPO = r"^Expo(?:nent)?PushToken\[[^\[\]\s]+\]$"
_TOKEN_EXPO = re.compile(PADRAO_TOKEN_EXPO)


def token_expo_valido(token: str | None) -> bool:
    """True se o texto tem o formato de token do Expo (``PADRAO_TOKEN_EXPO``)."""
    return bool(token) and _TOKEN_EXPO.fullmatch(token) is not None


def montar_lotes(tokens: list[str], titulo: str, corpo: str,
                 dados: dict | None = None) -> list[list[dict]]:
    """Mensagens em lotes de até 100, no formato aceito pelo Expo."""
    mensagens = [
        {"to": token, "title": titulo, "body": corpo, "sound": "default",
         **({"data": dados} if dados else {})}
        for token in tokens
    ]
    return [
        mensagens[inicio:inicio + TAMANHO_LOTE]
        for inicio in range(0, len(mensagens), TAMANHO_LOTE)
    ]


def primeiro_nome(nome: str | None) -> str:
    """Só o primeiro nome, com caixa de nome próprio ("MARIA EDUARDA" → "Maria")."""
    partes = (nome or "").split()
    return partes[0].title() if partes else ""


def corpo_dados_atualizados(nome_aluno: str | None) -> str:
    """Texto do push "dados da plataforma atualizados" de UMA criança.

    Só o PRIMEIRO nome (LGPD/minimização): o push aparece na tela BLOQUEADA do
    celular do professor e trafega pelo Expo e pelo FCM/APNs, fora do sistema —
    o nome completo de um menor não precisa sair para o aviso fazer sentido; quem
    abre o app vê a ficha inteira, com login. Sem nome, o aviso continua útil."""
    nome = primeiro_nome(nome_aluno)
    sujeito = nome if nome else "Um aluno"
    return (f"{sujeito} teve os dados da plataforma atualizados. "
            "As notas já foram recalculadas.")


def _enviar_lotes(lotes: list[list[dict]]) -> list[str]:
    """Envia os lotes e devolve os tokens rejeitados como não registrados.

    Cada lote é INDEPENDENTE: um lote com erro (timeout, 5xx, 400 do pedido
    inteiro, resposta ilegível) vira um aviso no log com o número dele e o envio
    segue para os próximos. Antes, a exceção saía do laço: os lotes seguintes
    nunca eram enviados e os ``DeviceNotRegistered`` já reportados pelos lotes
    anteriores se perdiam (o token morto ficava no banco)."""
    import httpx

    invalidos: list[str] = []
    for numero, lote in enumerate(lotes, start=1):
        try:
            resposta = httpx.post(EXPO_PUSH_URL, json=lote, timeout=15.0)
            resposta.raise_for_status()
            resultados = resposta.json().get("data", [])
            mortos = [
                mensagem["to"]
                for mensagem, resultado in zip(lote, resultados)
                if (resultado.get("details") or {}).get("error") == "DeviceNotRegistered"
            ]
        except Exception:  # noqa: BLE001 — um lote com erro não cala os demais
            logger.warning("Falha no lote %s de %s do push (%s aparelhos); "
                           "seguindo com os demais", numero, len(lotes), len(lote),
                           exc_info=True)
            continue
        invalidos.extend(mortos)
    return invalidos


def remover_aparelhos_da_conta(db: Session, usuario_id: int) -> int:
    """Apaga os aparelhos (push) registrados pela conta e devolve quantos eram.

    Chamado quando a conta perde o acesso (desativar, excluir — ``admin.
    _revogar_acessos``), muda de alcance (promoção a Secretaria, ``rede.py``) e
    quando a senha é substituída (troca pelo admin, ``admin._revogar_acessos(
    senha_substituida=True)``, redefinição pelo link, ``auth.consumir_link_reset``, e
    a etapa de deploy que invalida a senha derivada do nome, ``professores.
    invalidar_senhas_derivadas``):
    o app não se descadastra sozinho no 401, e a conta revogada nem conseguiria
    chamar ``/dispositivos/remover``. Reativar a conta não traz o aparelho de
    volta — só um novo registro pelo app. Não comita: vai na transação de quem
    chama, junto da auditoria (``dispositivos_removidos``; a etapa de deploy não
    grava a contagem, a auditoria dela tem só ``uso`` e ``origem``)."""
    return db.execute(
        delete(DispositivoMovel).where(DispositivoMovel.usuario_id == usuario_id)
    ).rowcount or 0


# Impressão da chave de sessão com que os aparelhos da escola foram registrados
# (``security.impressao_da_chave_de_sessao``), guardada em ``configuracoes`` — uma linha
# por escola, sem migração. O aparelho não guarda nada da sessão que o registrou; quando
# a SECRET_KEY muda, todas as sessões caem, e a impressão diferente mostra que os
# aparelhos da escola também são de sessões que não valem mais.
NAMESPACE_CHAVE_DE_SESSAO = "push"
CHAVE_IMPRESSAO = "chave_de_sessao"


def conferir_chave_de_sessao(db: Session, escola_id: int, *,
                             sem_marca_apaga: bool = False) -> tuple[int, bool]:
    """Os aparelhos (push) saem com as sessões também na troca da SECRET_KEY.

    Compara a impressão gravada para a escola com a da chave atual. Diferente: apaga
    os aparelhos da escola (registrados com sessões que já dão 401 — inclusive uma
    sessão forjada com a chave exposta) e grava a atual; o app volta a se registrar
    no próximo login. Igual: nada. Sem impressão gravada: grava a atual e, só com
    ``sem_marca_apaga`` (o boot), apaga os aparelhos — não há como saber com que
    chave foram registrados.

    Devolve ``(aparelhos removidos, gravou algo)``. Não comita: vai na transação de
    quem chama. Só quem grava a nova impressão limpa os aparelhos da escola."""
    atual = impressao_da_chave_de_sessao()
    filtros = (
        Configuracao.escola_id == escola_id,
        Configuracao.namespace == NAMESPACE_CHAVE_DE_SESSAO,
        Configuracao.chave == CHAVE_IMPRESSAO,
    )
    consulta = select(Configuracao).where(*filtros).execution_options(populate_existing=True)
    marca = db.execute(consulta).scalar_one_or_none()
    if marca is not None and marca.valor == atual:
        return 0, False

    # Outra transação pode ter trocado a impressão entre a leitura e a limpeza.
    # Confira novamente sob a trava para preservar os aparelhos que ela registrou.
    if db.get_bind().dialect.name == "sqlite":
        # SQLite ignora FOR UPDATE. Uma instrução de escrita sem alterar a marca
        # abre a transação de escrita antes da releitura e do SAVEPOINT.
        db.execute(update(Configuracao).where(*filtros)
                   .values(updated_at=Configuracao.updated_at))
    consulta_travada = consulta.with_for_update()
    marca = db.execute(consulta_travada).scalar_one_or_none()
    apagar = sem_marca_apaga
    if marca is None:
        try:
            with db.begin_nested():
                db.add(Configuracao(escola_id=escola_id,
                                    namespace=NAMESPACE_CHAVE_DE_SESSAO,
                                    chave=CHAVE_IMPRESSAO, valor=atual))
        except IntegrityError:
            # A restrição única decide quem pode gravar a primeira impressão.
            marca = db.execute(consulta_travada).scalar_one_or_none()
            if marca is None:
                raise
    if marca is not None:
        if marca.valor == atual:
            return 0, False
        marca.valor = atual
        apagar = True

    removidos = 0
    if apagar:
        removidos = db.execute(
            delete(DispositivoMovel).where(DispositivoMovel.escola_id == escola_id)
        ).rowcount or 0
    if removidos:
        registrar(db, "dispositivo.chave_de_sessao_trocada", escola_id=escola_id,
                  detalhes={"removidos": removidos})
        logger.info("Push: %s aparelho(s) da escola %s removido(s): registrados com "
                    "sessões de outra chave de sessão (SECRET_KEY trocada)",
                    removidos, escola_id)
    return removidos, True


def conferir_chave_de_sessao_no_boot(db: Session) -> int:
    """No boot: confere a chave de sessão de cada escola que tem aparelho e apaga os
    registrados com outra chave — ou sem impressão gravada, de antes desta conferência
    existir (``conferir_chave_de_sessao(sem_marca_apaga=True)``). Comita. Devolve quantos
    aparelhos saíram."""
    escolas = db.execute(select(DispositivoMovel.escola_id).distinct()
                         .order_by(DispositivoMovel.escola_id)).scalars().all()
    removidos = 0
    for escola_id in escolas:
        removidos += conferir_chave_de_sessao(db, escola_id, sem_marca_apaga=True)[0]
    db.commit()
    return removidos


def _ve_a_crianca(db: Session, escola_id: int, ano: int | None, usuario: Usuario,
                  aluno_id: int) -> bool:
    """A mesma régua da API para abrir a ficha da criança
    (``permissoes.exigir_aluno_permitido``): a gestão da escola sempre; o professor
    só se ela está numa turma dele no ano ativo; a Secretaria nunca (``turmas_
    permitidas`` devolve lista vazia para ela)."""
    turmas = permissoes.turmas_permitidas(db, escola_id, usuario)
    if turmas is None:
        return True
    return aluno_id in permissoes.alunos_permitidos(db, escola_id, ano, turmas)


def notificar_escola(db: Session, escola_id: int, titulo: str, corpo: str,
                     dados: dict | None = None, *, aluno_id: int | None = None) -> int:
    """Push para os aparelhos da escola cujas contas estão ATIVAS. Retorna quantos
    foram alvo.

    Só conta ativa recebe: o aviso pode levar o primeiro nome de uma criança
    (``corpo_dados_atualizados``) e aparece na tela bloqueada. Conta desativada
    ou excluída perde a sessão e também o aviso — o filtro aqui cobre inclusive
    os aparelhos de contas desligadas antes de ``remover_aparelhos_da_conta``
    existir, sem migração.

    ``aluno_id``: o aviso é de UMA criança (leva o primeiro nome dela). Aí só recebe
    quem a enxerga pela API (``_ve_a_crianca``) — o professor de outra turma, que tem
    lista vazia e perfil 404 para ela, não recebe o nome na tela bloqueada. Sem
    ``aluno_id`` (aviso da escola inteira), todo aparelho ativo recebe.

    Melhor esforço: erros de rede são registrados em log e engolidos;
    tokens que o Expo reportar como mortos são removidos do banco.

    Token fora do formato do Expo (``token_expo_valido``) — só pode ter sido gravado
    antes de ``/dispositivos`` validar o formato — não é aparelho: não vai ao Expo
    (não ocupa lote nem chamada) e é apagado aqui. Antes ele só sairia se o Expo o
    devolvesse como ``DeviceNotRegistered`` — o que nada garante para um texto que
    nem é token (a resposta do Expo a ele não foi verificada).

    Transação: a lista de destinos é lida e a transação ENCERRADA antes da chamada
    ao Expo (até 15 s por lote); os tokens mortos são apagados numa transação curta,
    depois. Antes, a leitura deixava a transação da requisição aberta durante a rede
    e, no PostgreSQL, a conexão ficava presa ao pool ("idle in transaction").

    Chave de sessão trocada (``conferir_chave_de_sessao``): os aparelhos da escola
    registrados com a SECRET_KEY anterior saem antes da leitura dos destinos — a
    sessão que os registrou já não vale, e o aviso não vai a eles.
    """
    _, gravou_marca = conferir_chave_de_sessao(db, escola_id)
    linhas = db.execute(
        select(DispositivoMovel.token_push, Usuario)
        .join(Usuario, Usuario.id == DispositivoMovel.usuario_id)
        .where(DispositivoMovel.escola_id == escola_id, Usuario.status == "ativo")
    ).all()
    lixo = [token for token, _ in linhas if not token_expo_valido(token)]
    linhas = [(token, usuario) for token, usuario in linhas if token_expo_valido(token)]
    if lixo:
        db.execute(delete(DispositivoMovel).where(DispositivoMovel.token_push.in_(lixo)))
        logger.info("Push: %s aparelho(s) com token fora do formato do Expo removido(s) "
                    "da escola %s", len(lixo), escola_id)
    if aluno_id is None:
        tokens = [token for token, _ in linhas]
    else:
        escola = db.get(Escola, escola_id)
        ano = escola.ano_letivo_ativo if escola is not None else None
        tokens = [token for token, usuario in linhas
                  if _ve_a_crianca(db, escola_id, ano, usuario, aluno_id)]
    if not tokens:
        if lixo or gravou_marca:
            db.commit()
        return 0

    # Fecha a transação que as leituras acima abriram (autobegin) ANTES da rede: a
    # conexão volta ao pool enquanto o Expo responde. Quem chama já comitou o próprio
    # trabalho (``importacoes._pos_commit_importacao``): aqui só houve leitura e, se
    # havia, a limpeza do lixo. É COMMIT, e não rollback, para nunca descartar algo
    # que um chamador deixasse pendente — o mesmo que a limpeza dos tokens mortos,
    # abaixo, já fazia.
    db.commit()
    try:
        invalidos = _enviar_lotes(montar_lotes(list(tokens), titulo, corpo, dados))
        if invalidos:
            db.execute(delete(DispositivoMovel)
                       .where(DispositivoMovel.token_push.in_(invalidos)))
            db.commit()
    except Exception:  # noqa: BLE001 — push nunca derruba a operação principal
        logger.warning("Falha ao enviar push para a escola %s", escola_id,
                       exc_info=True)
    return len(tokens)
