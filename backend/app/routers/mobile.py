"""Endpoints de apoio ao app mobile: dispositivos push e sincronização.

Decisões:
  * `/sincronizacao` devolve TUDO que o app precisa em UMA viagem de rede
    (dashboard, ranking, evolução, alertas e mural) + carimbo `gerado_em`.
    No celular, menos round-trips = menos bateria e melhor uso de redes
    ruins; o app guarda o pacote em cache e o reexibe offline.
  * Dispositivos são upsert pelo token: o mesmo aparelho que troca de
    conta passa a pertencer ao novo usuário/escola. Só token no formato do
    Expo, e no máximo `MAX_APARELHOS_POR_CONTA` aparelhos por conta.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import escola_autorizada, get_usuario_atual
from app.core.rate_limit import LimitadorTentativas, ip_do_cliente
from app.models import DispositivoMovel, Escola, Usuario
from app.models.base import agora
from app.routers.rankings import _ranking, montar_dashboard
from app.services import elegibilidade, evolucao, gamificacao, insights, permissoes
from app.services import push as svc_push
from app.services.audit import registrar

router = APIRouter(prefix="/escolas/{escola_id}", tags=["Mobile"])


# --- Dispositivos (notificações push) -------------------------------------------

# Teto de aparelhos por conta. Uma pessoa usa o celular e, às vezes, um tablet; o
# app se registra a cada abertura. Sem teto, qualquer conta da escola (até um
# professor) gravava milhares de tokens por script, e cada aviso da escola passava
# a fazer N/100 chamadas ao Expo dentro da requisição que o disparou.
MAX_APARELHOS_POR_CONTA = 5


class DispositivoIn(BaseModel):
    # O token que o app recebe de getExpoPushTokenAsync (push.PADRAO_TOKEN_EXPO).
    token_push: str = Field(min_length=10, max_length=200,
                            pattern=svc_push.PADRAO_TOKEN_EXPO)
    plataforma: str = Field(pattern="^(android|ios)$")


def _aparelhos_alem_do_teto(db: Session, usuario_id: int, manter_id: int) -> list[int]:
    """Ids dos aparelhos da conta que passam do teto, sem contar ``manter_id`` (o
    que acabou de se registrar). Sai quem está há mais tempo sem se registrar
    (``updated_at``; o registro renova a data), depois o de id menor."""
    return list(db.execute(
        select(DispositivoMovel.id)
        .where(DispositivoMovel.usuario_id == usuario_id,
               DispositivoMovel.id != manter_id)
        .order_by(DispositivoMovel.updated_at.desc(), DispositivoMovel.id.desc())
        .offset(MAX_APARELHOS_POR_CONTA - 1)
    ).scalars().all())


@router.post("/dispositivos")
def registrar_dispositivo(
    dados: DispositivoIn,
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    dispositivo = db.execute(
        select(DispositivoMovel).where(DispositivoMovel.token_push == dados.token_push)
    ).scalar_one_or_none()
    if dispositivo is None:
        dispositivo = DispositivoMovel(
            escola_id=escola_id, usuario_id=usuario.id,
            token_push=dados.token_push, plataforma=dados.plataforma,
        )
        db.add(dispositivo)
        registrar(db, "dispositivo.registrado", escola_id=escola_id,
                  usuario_id=usuario.id, detalhes={"plataforma": dados.plataforma})
    else:
        # O aparelho trocou de dono/escola: atualiza o vínculo. O token_push é
        # um segredo do app da vítima (só quem tem o aparelho o conhece), mas a
        # TROCA DE DONO fica registrada na auditoria para ser rastreável.
        dono_anterior = dispositivo.usuario_id
        dispositivo.escola_id = escola_id
        dispositivo.usuario_id = usuario.id
        dispositivo.plataforma = dados.plataforma
        # Registrar de novo = o aparelho está em uso: conta como o mais recente no
        # teto por conta (sem isto, o updated_at só mudava se algum campo mudasse).
        dispositivo.updated_at = agora()
        if dono_anterior != usuario.id:
            registrar(db, "dispositivo.reassociado", escola_id=escola_id,
                      usuario_id=usuario.id,
                      detalhes={"plataforma": dados.plataforma,
                                "dono_anterior": dono_anterior})
    db.flush()
    excedentes = _aparelhos_alem_do_teto(db, usuario.id, dispositivo.id)
    if excedentes:
        db.execute(delete(DispositivoMovel).where(DispositivoMovel.id.in_(excedentes)))
        registrar(db, "dispositivo.excedente_removido", escola_id=escola_id,
                  usuario_id=usuario.id,
                  detalhes={"removidos": len(excedentes),
                            "limite": MAX_APARELHOS_POR_CONTA})
    db.commit()
    db.refresh(dispositivo)
    return {"id": dispositivo.id, "plataforma": dispositivo.plataforma}


class DispositivoRemover(BaseModel):
    token_push: str = Field(min_length=10, max_length=200)


@router.post("/dispositivos/remover")
def remover_dispositivo(
    dados: DispositivoRemover,
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Chamado no logout do app — o aparelho para de receber push."""
    dispositivo = db.execute(
        select(DispositivoMovel).where(
            DispositivoMovel.token_push == dados.token_push,
            DispositivoMovel.usuario_id == usuario.id,
        )
    ).scalar_one_or_none()
    if dispositivo is not None:
        db.delete(dispositivo)
        db.commit()
    return {"mensagem": "Dispositivo removido."}


# Descadastro SEM login: tentativas por IP numa janela (todas contam, achando ou não
# o aparelho). Folgado para a escola inteira atrás de um IP só saindo do app; curto
# para quem tentasse adivinhar tokens (que, de todo modo, são aleatórios e longos).
limitador_descadastro = LimitadorTentativas(max_tentativas=30, janela_s=600)


@router.post("/dispositivos/descadastrar")
def descadastrar_dispositivo(
    dados: DispositivoRemover,
    request: Request,
    escola_id: int,
    db: Session = Depends(get_db),
):
    """Tira o aparelho do push SEM pedir login — o "Sair" do app que não alcançou o
    ``/remover``.

    O ``/remover`` exige a sessão. No "Sair da conta" sem rede (ou com a API fora) a
    chamada falhava e o app apagava o JWT logo depois, então nenhuma nova tentativa
    se autenticava; na sessão expirada (401) nem dava para tentar. O aparelho seguia
    cadastrado para uma conta ativa e recebia, na tela bloqueada, o primeiro nome da
    criança (``push.corpo_dados_atualizados``). Aqui basta o ``token_push``: é o
    segredo do próprio aparelho (só o app dele o conhece; quem o tem já poderia
    mandar push a ele direto pelo Expo), e o efeito é só PARAR de avisar. O app
    chama na hora e repete quando a rede voltar.

    ``escola_id`` é a escola que o app tinha aberta; o aparelho sai de onde estiver
    cadastrado (o token é único — como no ``/remover``), porque o app troca de
    escola sem cadastrar de novo. A resposta é a mesma exista o token ou não: a rota
    não diz quais aparelhos estão cadastrados."""
    chave = ip_do_cliente(request)
    if limitador_descadastro.bloqueado(chave):
        espera = limitador_descadastro.segundos_restantes(chave)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Muitas tentativas. Aguarde {max(1, espera // 60)} minuto(s) e "
            "tente novamente.",
            headers={"Retry-After": str(max(1, espera))})
    limitador_descadastro.registrar_falha(chave)
    dispositivo = db.execute(
        select(DispositivoMovel).where(DispositivoMovel.token_push == dados.token_push)
    ).scalar_one_or_none()
    if dispositivo is not None:
        registrar(db, "dispositivo.descadastrado", escola_id=dispositivo.escola_id,
                  detalhes={"plataforma": dispositivo.plataforma,
                            "dono": dispositivo.usuario_id, "sem_login": True})
        db.delete(dispositivo)
        db.commit()
    return {"mensagem": "Dispositivo removido."}


# --- Sincronização (offline-first) -----------------------------------------------

SINCRONIZACAO_SEM_SECRETARIA = (
    "No aplicativo, os números de cada escola são de quem trabalha nela. A Secretaria "
    "acompanha a rede pelo Panorama da Rede, na versão web.")


@router.get("/sincronizacao")
def sincronizar(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Pacote consolidado para o app hidratar todas as telas de uma vez.

    Mesmo escopo por papel da web: admin/coordenador enxergam a escola inteira;
    professor recebe SOMENTE as turmas dele (`turmas_permitidas`). Sem isso, o
    sync vazaria nomes e notas de toda a escola para um professor restrito.

    A Secretaria leva 403 com a explicação. ``turmas_permitidas`` é vazia para ela
    de propósito (nunca vê nome de criança), e o pacote recorta TUDO por ela —
    inclusive os números do painel (``montar_dashboard(turma_ids=[])``): o app
    mostrava a escola com 0 alunos, média 0,0, 0 livros e 0 turmas, como se fossem
    os números dela. Na web a Secretaria nunca vê este painel (vai para o Panorama
    da Rede); uma visão da rede dentro do app é decisão de produto, não deste pacote.
    """
    if permissoes.e_secretaria(usuario):
        raise HTTPException(status.HTTP_403_FORBIDDEN, SINCRONIZACAO_SEM_SECRETARIA)
    escola = db.get(Escola, escola_id)
    permitidas = permissoes.turmas_permitidas(db, escola_id, usuario)
    # AS FASES NÃO CONCORREM: a evolução e o mural do app recortam as turmas
    # premiáveis, como o telão e a web (`routers/evolucao.ranking_evolucao`). O
    # escopo do professor não muda (interseção); a régua segue a da escola.
    premiaveis = elegibilidade.turmas_premiaveis(db, escola_id, escola.ano_letivo_ativo)
    concorrem = set(premiaveis)
    recorte = (premiaveis if permitidas is None
               else [t for t in permitidas if t in concorrem])

    # Carrega UMA vez as varreduras caras (séries de snapshot + dificuldade) e
    # injeta em todos os consumidores desta request (alertas, mural, evolução) —
    # antes, cada um relia as tabelas de snapshot (~3x cada por request). Mesma
    # estratégia do mural/M4.
    serie_m, serie_e, mapa_dif = evolucao.series_e_dificuldade(db, escola_id)

    alertas = insights.alertas_da_escola(db, escola_id, serie_m=serie_m, serie_e=serie_e)
    if permitidas is None:
        # Acesso total (admin/coordenador): mural da vitrine da escola inteira.
        eventos_mural = gamificacao.mural(
            db, escola_id, serie_m=serie_m, serie_e=serie_e, mapa_dif=mapa_dif,
            turma_ids=premiaveis)["eventos"]
    else:
        # Professor restrito: sem mural (é vitrine da escola inteira, como no
        # web, que o bloqueia com negar_restrito) e alertas só das turmas dele.
        eventos_mural = []
        alunos = permissoes.alunos_permitidos(db, escola_id,
                                              escola.ano_letivo_ativo, permitidas)
        alertas = permissoes.filtrar_por_aluno(alertas, alunos)

    ranking = _ranking(db, escola_id, escola.ano_letivo_ativo, turma_ids=permitidas)
    if permitidas is not None:
        # Professor: posição RELATIVA às turmas dele (1..N), como a web
        # (`rankings.ranking_geral`) e o Top 10 deste mesmo pacote
        # (`montar_dashboard`) — a aba "Ranking Geral" e o Painel do app não
        # podem dar duas posições à mesma criança. Gestão: a posição global.
        for posicao, item in enumerate(ranking, start=1):
            item.posicao = posicao

    return {
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "dashboard": montar_dashboard(db, escola_id, turma_ids=permitidas),
        "ranking": ranking,
        "evolucao": [
            {
                "posicao": item.posicao,
                "aluno_id": item.aluno_id,
                "nome": item.nome,
                "turma": item.turma,
                "nota_evolucao": item.nota_evolucao,
            }
            # Régua JUSTA (`base_no_periodo=True`), a mesma da web
            # (`routers/evolucao.ranking_evolucao`) e do telão: sem retrato
            # anterior à janela, o acumulado de vida não vira "evolução" — só
            # quem cresceu de verdade nos 30 dias sobe.
            for item in evolucao.ranking_evolucao(
                db, escola_id, dias=30, turma_ids=recorte, base_no_periodo=True,
                serie_m=serie_m, serie_e=serie_e, mapa_dif=mapa_dif)[:20]
        ],
        "alertas": alertas,
        "mural": eventos_mural,
    }
