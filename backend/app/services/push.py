"""Notificações push via Expo Push Service.

Decisão: o app mobile é Expo/React Native, então usamos o serviço de push
do Expo — um único endpoint HTTPS cobre Android (FCM) e iOS (APNs) sem a
escola precisar de contas no Firebase/Apple. O envio é SEMPRE melhor
esforço: falha de push jamais derruba a operação principal (importação,
recálculo etc.).
"""
from __future__ import annotations

import logging

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import DispositivoMovel, Escola, Usuario
from app.services import permissoes

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
TAMANHO_LOTE = 100  # limite documentado do Expo por requisição


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
    _revogar_acessos``) ou muda de alcance (promoção a Secretaria, ``rede.py``):
    o app não se descadastra sozinho no 401, e a conta revogada nem conseguiria
    chamar ``/dispositivos/remover``. Reativar a conta não traz o aparelho de
    volta — só um novo registro pelo app. Não comita: vai na transação de quem
    chama, junto da auditoria (``dispositivos_removidos``)."""
    return db.execute(
        delete(DispositivoMovel).where(DispositivoMovel.usuario_id == usuario_id)
    ).rowcount or 0


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
    """
    linhas = db.execute(
        select(DispositivoMovel.token_push, Usuario)
        .join(Usuario, Usuario.id == DispositivoMovel.usuario_id)
        .where(DispositivoMovel.escola_id == escola_id, Usuario.status == "ativo")
    ).all()
    if aluno_id is None:
        tokens = [token for token, _ in linhas]
    else:
        escola = db.get(Escola, escola_id)
        ano = escola.ano_letivo_ativo if escola is not None else None
        tokens = [token for token, usuario in linhas
                  if _ve_a_crianca(db, escola_id, ano, usuario, aluno_id)]
    if not tokens:
        return 0

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
