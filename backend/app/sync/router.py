"""API do Módulo de Sincronização (painel administrativo).

Isolamento multi-tenant: as rotas por-escola usam ``escola_autorizada`` (a
escola do path tem de bater com a do usuário; global vê todas) e exigem
admin/coordenador. O dashboard cross-escola exige usuário GLOBAL. Nenhuma
resposta jamais inclui senha (o cofre só devolve status).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger("constela.sync")

from app.core.database import get_db
from app.core.deps import (
    escola_autorizada,
    exigir_admin_global,
    exigir_modulo_da_escola,
    exigir_papeis,
    get_usuario_atual,
)
from app.models import (
    Aluno,
    Escola,
    LogAuditoria,
    Matricula,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
    Usuario,
)
from app.models.sincronizacao import (
    PlataformaCredencial,
    SincronizacaoAlerta,
    SincronizacaoConfig,
    SincronizacaoExecucao,
    SincronizacaoLog,
)
from app.services import modulos as svc_modulos
from app.services import permissoes, scoring
from app.services.audit import registrar
from app.sync import (
    aovivo,
    connectors,
    diagnostico_elefante,
    escola_externa,
    fuso,
    scheduler,
    service,
    vault,
)
from app.sync.connectors import matific as matific_conector
from app.sync.interfaces import Contexto, Credenciais, ErroConector, ResultadoValidacao
from app.sync.schemas import (
    AlertaOut,
    ConfigIn,
    CredenciaisIn,
    DashboardOut,
    EscolaExternaIn,
    EscolaExternaOut,
    EscolaOnboarding,
    EscolaStatus,
    ExecucaoAgoraOut,
    ExecucaoOut,
    LogOut,
    PlataformaStatus,
    ResultadoTeste,
)

router = APIRouter(prefix="/escolas/{escola_id}/sync", tags=["Sincronização"])
router_global = APIRouter(prefix="/sync", tags=["Sincronização"])


def _validar_plataforma(plataforma: str) -> None:
    if connectors.obter(plataforma) is None or plataforma == "manual":
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"Plataforma '{plataforma}' não é sincronizável.")


def _ctx_efemero(escola_id: int) -> Contexto:
    """Contexto sem persistência de log (para testes de credencial imediatos)."""
    return Contexto(escola_id=escola_id, execucao_id=None, log=lambda *a: None)


# Uma TENTATIVA é uma execução que terminou coletando (bem ou mal). Fila,
# em andamento e cancelada (substituída/órfã liberada) não são tentativa.
_STATUS_TENTATIVA = service.STATUS_TERMINAIS


def _execucoes_recentes(db: Session, escola_id: int) -> dict[str, tuple]:
    """``{plataforma: (última execução, última TENTATIVA)}`` da escola numa
    consulta só: a execução mais RECENTE, em qualquer estado (maior id), e a
    mais recente que terminou coletando (``_STATUS_TENTATIVA``). Plataforma sem
    execução não aparece."""
    E = SincronizacaoExecucao
    ultimas = select(func.max(E.id)).where(E.escola_id == escola_id).group_by(E.plataforma)
    tentativas = (select(func.max(E.id))
                  .where(E.escola_id == escola_id, E.status.in_(_STATUS_TENTATIVA))
                  .group_by(E.plataforma))
    por_plataforma: dict[str, tuple] = {}
    linhas = db.execute(select(E).where(E.id.in_(ultimas) | E.id.in_(tentativas))
                        .order_by(E.id)).scalars()
    for ex in linhas:   # crescente: a última de cada plataforma fica por cima
        _, tentativa = por_plataforma.get(ex.plataforma, (None, None))
        if ex.status in _STATUS_TENTATIVA:
            tentativa = ex
        por_plataforma[ex.plataforma] = (ex, tentativa)
    return por_plataforma


def _categoria_falha(plataforma: str, cred, tentativa, alertas_abertos) -> str | None:
    """Que TIPO de falha explica o estado atual: 'autenticacao' (a plataforma
    recusou o acesso), 'indisponibilidade_externa' (não respondeu / bloqueou /
    mudou), 'processamento' (erro do nosso lado), 'indisponivel' (este servidor
    não coleta) ou 'configuracao' (o pedido não é aceito: período inválido). None
    quando não há falha. Fonte: a credencial recusada, senão o
    alerta aberto pela ÚLTIMA tentativa com erro (o mapa único do serviço).

    ``alertas_abertos``: os alertas abertos da escola, do mais novo ao mais
    antigo (o /status os lê numa consulta só)."""
    if cred is not None and cred.status in ("invalida", "expirada"):
        return "autenticacao"
    if tentativa is None or tentativa.status != "erro":
        return None
    abertos = [(al.tipo, al.execucao_id) for al in alertas_abertos
               if al.plataforma == plataforma and not al.resolvido
               and al.tipo not in service.TIPOS_REGRA_PROPRIA]
    desta = [tipo for tipo, eid in abertos if eid == tentativa.id]
    for tipo in desta + [tipo for tipo, _ in abertos]:
        categoria = service.categoria_do_tipo(tipo)
        if categoria:
            return categoria
    return "processamento"   # falhou sem alerta que diga por quê: erro nosso


# ---------------------------------------------------------------------------
# Status por escola
# ---------------------------------------------------------------------------
# Contagens HONESTAS da cobertura dos dados (só leitura). A escola diagnostica a
# PRÓPRIA integração com números que o banco tem de fato: quantos alunos já
# têm dado de cada plataforma, quantos ainda não têm nenhum, quantos usam o
# Elefante e ainda não produziram (zero legítimo) e de quando é o dado mais
# recente. Escola vazia → zeros; nada é estimado.
_SNAPSHOT_DA_PLATAFORMA = {"elefante": SnapshotElefante, "matific": SnapshotMatific}
_ACOES_PENDENCIA_CORRESPONDENCIA = ("aluno.revisao_necessaria", "importacao.linha_ignorada")
_JANELA_PENDENCIAS = timedelta(days=30)
# Plataforma sem tabela de snapshot (ou escola sem ano ativo) NÃO DÁ PARA CONTAR:
# ``None`` — nunca ``0``, que afirmaria "ninguém tem dado".
_SEM_CONTAGEM = {
    "alunos_com_dados": None,
    "alunos_sem_dados": None,
    "alunos_com_zero_registros": None,
    "dado_mais_recente_em": None,
}


def _universo_alunos(escola_id: int, ano: int):
    """Ids (distintos) dos alunos ATIVOS matriculados no ano letivo ativo — o
    mesmo universo que o motor pontua e que os rankings exibem."""
    return (
        select(Aluno.id)
        .join(Matricula, (Matricula.aluno_id == Aluno.id) & (Matricula.ano_letivo == ano))
        .where(Aluno.escola_id == escola_id, Aluno.status == "ativo")
        .distinct()
    )


def _contagens_cobertura(db: Session, escola_id: int, ano: int | None,
                         plataformas: list[str]) -> dict[str, dict]:
    """Campos de cobertura de cada plataforma para ``PlataformaStatus``, numa
    consulta só (uma subconsulta escalar por número; o universo é contado uma
    vez). Com o ano definido e o universo vazio, as contagens são ``0``
    legítimos; sem ano ou sem tabela de snapshot, ``None`` (``_SEM_CONTAGEM``)."""
    saida = {p: dict(_SEM_CONTAGEM) for p in plataformas}
    contaveis = {p: _SNAPSHOT_DA_PLATAFORMA[p] for p in plataformas
                 if p in _SNAPSHOT_DA_PLATAFORMA}
    if ano is None or not contaveis:
        return saida
    universo = _universo_alunos(escola_id, ano)
    consultas = {"total": select(func.count()).select_from(universo.subquery())}
    for p, modelo in contaveis.items():
        consultas[f"com_dados_{p}"] = (
            select(func.count(func.distinct(modelo.aluno_id)))
            .where(modelo.escola_id == escola_id, modelo.aluno_id.in_(universo)))
        if modelo is SnapshotElefante:
            # "Atual" pela MESMA régua do scoring/ranking (fonte única): o snapshot
            # mais recente por (data_referencia, id) — um backfill antigo com
            # livros_unicos=0 não pode contar como estado atual.
            atuais = scoring.ids_snapshots_atuais(SnapshotElefante, escola_id)
            consultas[f"zero_{p}"] = (
                select(func.count(func.distinct(SnapshotElefante.aluno_id)))
                .where(SnapshotElefante.id.in_(atuais),
                       SnapshotElefante.livros_unicos == 0,
                       SnapshotElefante.aluno_id.in_(universo)))
        # Frescor do dado dos alunos PONTUADOS: mesmo universo de `com_dados`. Um
        # snapshot recente de aluno arquivado (ou de outro ano) não pode fazer a
        # integração parecer em dia para quem de fato entra na nota.
        consultas[f"recente_{p}"] = (
            select(func.max(modelo.data_referencia))
            .where(modelo.escola_id == escola_id, modelo.aluno_id.in_(universo)))
    linha = db.execute(select(*(consulta.scalar_subquery().label(nome)
                                for nome, consulta in consultas.items()))).one()._mapping
    total = linha["total"] or 0
    for p, modelo in contaveis.items():
        com_dados = linha[f"com_dados_{p}"] or 0
        saida[p] = {
            "alunos_com_dados": int(com_dados),
            "alunos_sem_dados": int(max(0, total - com_dados)),
            "alunos_com_zero_registros": ((linha[f"zero_{p}"] or 0)
                                          if modelo is SnapshotElefante else None),
            "dado_mais_recente_em": linha[f"recente_{p}"],
        }
    return saida


def _consulta_pendencias(escola_id: int, agora: datetime):
    """Quantas linhas de importação/sincronização ficaram SEM vínculo seguro nos
    últimos 30 dias (auditoria) — o que a escola precisa revisar."""
    return select(func.count(LogAuditoria.id)).where(
        LogAuditoria.escola_id == escola_id,
        LogAuditoria.acao.in_(_ACOES_PENDENCIA_CORRESPONDENCIA),
        LogAuditoria.created_at >= agora - _JANELA_PENDENCIAS)


# Idas ao banco: cada consulta custa uma ida e volta inteira (em produção, ~195 ms
# com a API e o banco em regiões diferentes) e a tela de Integrações relê o
# /status sem parar. Por isso ele lê tudo em poucas consultas AGRUPADAS (escola e
# contagens; credenciais; agendas; execuções; marcos; alertas abertos; vínculos;
# cobertura), não N consultas por plataforma, e só COMMITA quando gravou algo
# (alerta de frescor aberto/fechado). A forma da resposta não muda.
@router.get("/status", response_model=EscolaStatus)
def status_escola(escola_id: int = Depends(escola_autorizada),
                  usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
                  db: Session = Depends(get_db)):
    agora = service._agora()
    agendador = service.agendador_ligado()
    # Execução que só o agendador rodaria, com ele desligado, nunca vai rodar:
    # liberada aqui (com registro) para o card não dizer "Sincronizando" para
    # sempre — ver ``service.liberar_fila_sem_agendador``. Vem ANTES das leituras:
    # quando libera, ela commita, e o que já estivesse carregado seria relido.
    service.liberar_fila_sem_agendador(db, escola_id)

    alunos_ativos = select(func.count(Aluno.id)).where(
        Aluno.escola_id == escola_id, Aluno.status == "ativo").scalar_subquery()
    turmas = select(func.count(Turma.id)).where(Turma.escola_id == escola_id).scalar_subquery()
    pendencias = _consulta_pendencias(escola_id, agora).scalar_subquery()
    # O CONTRATO da rede vem na mesma consulta da escola (uma coluna por módulo):
    # antes, a escola de rede relia ``modulos_rede`` uma vez por plataforma com
    # agenda (``plataforma_no_plano``) — 2 idas a mais que a avulsa.
    linha = db.execute(select(Escola, alunos_ativos, turmas, pendencias,
                              *svc_modulos.colunas_do_contrato(Escola.rede_id))
                       .where(Escola.id == escola_id)).one_or_none()
    if linha is None:   # removida no meio da requisição: os números, sem a escola
        escola = None
        qtd_alunos, qtd_turmas, qtd_pendencias = db.execute(
            select(alunos_ativos, turmas, pendencias)).one()
        modulos = svc_modulos.modulos_da_escola(db, None)
    else:
        escola, qtd_alunos, qtd_turmas, qtd_pendencias, *desligados = linha
        modulos = svc_modulos.modulos_das_colunas(desligados)
    qtd_alunos, qtd_turmas = qtd_alunos or 0, qtd_turmas or 0
    escola_nome = escola.nome if escola else ""
    ano_ativo = escola.ano_letivo_ativo if escola else None

    creds = {c.plataforma: c for c in db.execute(select(PlataformaCredencial)
             .where(PlataformaCredencial.escola_id == escola_id)).scalars()}
    confs = {c.plataforma: c for c in db.execute(select(SincronizacaoConfig)
             .where(SincronizacaoConfig.escola_id == escola_id)).scalars()}

    conectores = [con for con in connectors.listar() if con.plataforma != "manual"]
    nomes = [con.plataforma for con in conectores]
    execucoes = _execucoes_recentes(db, escola_id)
    marcos = service.marcos_por_plataforma(db, escola_id)
    alertas_abertos = db.execute(
        select(SincronizacaoAlerta).where(SincronizacaoAlerta.escola_id == escola_id,
                                          SincronizacaoAlerta.resolvido.is_(False))
        .order_by(SincronizacaoAlerta.id.desc())).scalars().all()
    vinculos = escola_externa.obter_de_cada(db, escola_id, nomes)
    cobertura = _contagens_cobertura(db, escola_id, ano_ativo, nomes)

    plataformas = []
    gravou = False
    for con in conectores:
        cred = creds.get(con.plataforma)
        conf = confs.get(con.plataforma)
        ult, tentativa = execucoes.get(con.plataforma, (None, None))
        marco = marcos.get(con.plataforma) or service.MarcosDaIntegracao()
        ultimo_sucesso = marco.ultimo_sucesso_em
        # FRESCOR fora do agendador: a leitura do status abre/fecha o alerta
        # 'desatualizada' pelo ciclo de vida de sempre (regra única do serviço,
        # medida pela última coleta EM DIA — a 'parcial' não fecha o alerta).
        desatualizada, mudou = service.revisar_alerta_desatualizada(
            db, conf, agora=agora, ultimo=marco.ultimo_em_dia_em, ultimo_informado=True,
            abertos=[al for al in alertas_abertos
                     if al.plataforma == con.plataforma and al.tipo == "desatualizada"],
            no_plano=svc_modulos.plataforma_contratada(modulos, con.plataforma))
        gravou = gravou or mudou
        # A credencial gravada como 'valida' cuja cifra NÃO abre com as chaves deste
        # processo (rotação sem recifrar) não está conectada: 'ilegivel', e a tela
        # pede o recadastro. Só o "abre ou não" — nenhum detalhe da falha sai daqui.
        credencial_status = vault.status_efetivo(cred)
        plataformas.append(PlataformaStatus(
            plataforma=con.plataforma, estrategia=con.estrategia.value,
            conectada=credencial_status == "valida",
            credencial_status=credencial_status,
            validada_em=cred.validada_em if cred else None,
            ultimo_erro=cred.ultimo_erro if cred else None,
            agendada=bool(conf and conf.ativo),
            cadencia=conf.cadencia if conf else "manual",
            hora_local=conf.hora_local if conf else "03:00",
            dia_semana=conf.dia_semana if conf else None,
            proxima_execucao=conf.proxima_execucao if conf else None,
            ultima_execucao=ExecucaoOut.model_validate(ult) if ult else None,
            ultima_tentativa=ExecucaoOut.model_validate(tentativa) if tentativa else None,
            ultimo_sucesso_em=ultimo_sucesso,
            ultima_verificacao_em=marco.ultima_verificacao_em,
            ultimo_status=tentativa.status if tentativa else None,
            ultimo_motivo=tentativa.motivo if tentativa else None,
            recalculo_pendente=service.recalculo_pendente_lido(
                alertas_abertos, con.plataforma, marcado=marco.recalculo_marcado),
            periodo_um_dia_permitido=(con.plataforma == "matific"
                                      and matific_conector.periodo_um_dia_permitido()),
            desatualizada=desatualizada,
            **service.frescor(conf, ultimo_sucesso, agora),
            falha_categoria=_categoria_falha(con.plataforma, cred, tentativa, alertas_abertos),
            fila_parada=bool(ult is not None and not agendador
                             and service.so_o_agendador_roda(ult, agora=agora)),
            escola_externa=_publico(vinculos.get(con.plataforma)),
            **cobertura[con.plataforma]))

    if gravou:
        # Alerta de frescor aberto/fechado nesta leitura: a contagem relê o banco
        # (com a gravação) e a gravação é commitada. Sem gravação, nada a commitar
        # e os abertos são os que já foram lidos.
        abertos = db.scalar(select(func.count(SincronizacaoAlerta.id)).where(
            SincronizacaoAlerta.escola_id == escola_id,
            SincronizacaoAlerta.resolvido.is_(False))) or 0
        db.commit()
    else:
        abertos = len(alertas_abertos)
    return EscolaStatus(escola_id=escola_id, escola_nome=escola_nome,
                        qtd_alunos=qtd_alunos, qtd_turmas=qtd_turmas,
                        plataformas=plataformas, alertas_abertos=abertos,
                        lista_piloto_importada=qtd_turmas > 0,
                        integracao_configurada=len(creds) > 0,
                        agendador_ativo=agendador,
                        pendencias_correspondencia_30d=int(qtd_pendencias or 0))


@router.get("/onboarding", response_model=EscolaOnboarding)
def onboarding_escola(escola_id: int = Depends(escola_autorizada),
                      usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
                      db: Session = Depends(get_db)):
    """Só o sinal do "Comece aqui" que a barra lateral precisa a cada montagem —
    o mesmo ``lista_piloto_importada`` do /status (a escola já tem turmas), sem
    as demais consultas dele. Mesmo acesso do /status."""
    tem_turma = db.execute(select(Turma.id).where(Turma.escola_id == escola_id)
                           .limit(1)).first() is not None
    return EscolaOnboarding(lista_piloto_importada=tem_turma)


# ---------------------------------------------------------------------------
# Credenciais
# ---------------------------------------------------------------------------
CODIGO_CREDENCIAL_ILEGIVEL = vault.CODIGO_CREDENCIAL_ILEGIVEL
MENSAGEM_CREDENCIAL_ILEGIVEL = (
    "A senha salva desta plataforma não pode mais ser lida pelo servidor (a chave "
    "que a protegia foi trocada). Informe usuário e senha de novo e clique em "
    "“Salvar e validar”.")


def _registrar_validacao(db: Session, escola_id: int, plataforma: str, linha,
                         resultado: ResultadoValidacao) -> None:
    """Grava o resultado de uma validação de login (salvar ou testar credencial).

    Só a RECUSA da plataforma (senha inválida/expirada) marca a credencial como
    'invalida' — antes, qualquer falha (página que não abriu, navegador, CAPTCHA,
    timeout) também marcava, e a tela dizia "senha recusada" para um problema de
    caminho. Os demais casos ficam 'nao_validada' com o motivo. O alerta usa o
    MAPA ÚNICO de tipos do serviço (o mesmo da execução); um login que funcionou
    fecha todos os alertas de ACESSO da integração e o do navegador que não abriu.
    Uma recusa que veio da página de login (senha, CAPTCHA, 2FA…) também fecha o do
    navegador que não abriu antes de abrir o dela — ele abriu desta vez."""
    if resultado.ok:
        vault.marcar_status(db, linha, "valida", None)
        # Um login que funcionou também prova que o navegador deste servidor abre e
        # que a plataforma respondeu: o alerta crítico de quando o Chromium não subiu
        # (``navegador_indisponivel`` → 'plataforma_indisponivel'), aberto por um teste
        # ou por uma execução, perdeu a causa. Antes ficava aberto, com a credencial já
        # 'valida', até uma sincronização bem-sucedida — e o agendador está desligado.
        navegador, _ = service.alerta_do_codigo("navegador_indisponivel")
        service.resolver_alertas(db, escola_id, plataforma,
                                 service.TIPOS_ACESSO + (navegador,))
        return
    codigo = resultado.codigo or "falha_auth"
    recusada = codigo in service.CODIGOS_CREDENCIAL_RECUSADA
    vault.marcar_status(db, linha, "invalida" if recusada else "nao_validada",
                        resultado.mensagem)
    # A resposta da página de login (``service.CODIGOS_RESPOSTA_DO_LOGIN``, o mesmo
    # conjunto da execução) prova que o navegador abriu: o alerta crítico de quando o
    # Chromium não subia perdeu a causa e não fica na tela ao lado do novo. NÃO entram
    # o ``erro_navegador`` (pode ser o navegador que caiu no meio do teste) nem o
    # resultado SEM código (o ``falha_auth`` acima é só o tipo do alerta, não prova
    # que a página respondeu) — por isso a checagem usa o código cru.
    if resultado.codigo in service.CODIGOS_RESPOSTA_DO_LOGIN:
        navegador, _ = service.alerta_do_codigo("navegador_indisponivel")
        service.resolver_alertas(db, escola_id, plataforma, (navegador,))
    tipo, severidade = service.alerta_do_codigo(codigo)
    service.abrir_alerta(db, escola_id, plataforma, tipo, resultado.mensagem,
                         severidade=severidade)


# AS ROTAS DE CREDENCIAL SÃO ``async`` (o login na plataforma é um ``await`` longo), mas
# a sessão do banco é SÍNCRONA: o corpo de uma rota async roda na thread do event loop
# do worker, e cada consulta/commit ali parava o worker inteiro (todas as escolas e
# perfis que caem nele, inclusive o /api/health — ~0,2 s por ida ao banco em produção).
# Todo trabalho de banco delas roda no threadpool (``run_in_threadpool``), nas funções
# abaixo; no loop fica só o ``await`` do login. A sessão é usada por uma thread de cada
# vez (nunca ao mesmo tempo), como numa rota ``def``.
def _gravar_credencial(db: Session, escola_id: int, plataforma: str, cred: Credenciais,
                       usuario_id: int):
    """"Salvar e validar", antes do login: grava a credencial CIFRADA e commita."""
    linha = vault.salvar_credencial(db, escola_id, plataforma, cred)
    # A senha recém-cifrada abre com as chaves deste servidor: o alerta "senha
    # salva ilegível" de uma execução anterior perdeu a causa, qualquer que seja o
    # resultado do login abaixo (a recusa abre o alerta PRÓPRIO dela).
    service.resolver_alertas(db, escola_id, plataforma, ("credencial_ilegivel",))
    if plataforma == "matific":
        aovivo.limpar_sessao(db, escola_id)     # esquece sessão da credencial antiga
    registrar(db, "sync.credencial_salva", escola_id=escola_id, usuario_id=usuario_id,
              entidade="plataforma", detalhes={"plataforma": plataforma})  # sem senha
    db.commit()
    return linha


def _credencial_para_testar(db: Session, escola_id: int,
                            plataforma: str) -> tuple[Credenciais | None, bool]:
    """"Testar conexão", antes do login: ``(credencial decifrada, há linha gravada)``.
    Solta a conexão do pool antes do ``await`` de I/O longo (navegador)."""
    cred = vault.obter_credencial(db, escola_id, plataforma)
    gravada = cred is not None or vault.obter_linha(db, escola_id, plataforma) is not None
    db.rollback()
    return cred, gravada


def _concluir_validacao(db: Session, escola_id: int, plataforma: str,
                        resultado: ResultadoValidacao, *, linha_salva=None,
                        ligar_agenda: bool = False) -> ResultadoTeste:
    """Depois do login: grava o resultado da validação e monta a resposta."""
    # Relê a linha DEPOIS do await (I/O longo): não sobrescreve um status que
    # uma execução concorrente possa ter mudado nesse intervalo (lost update).
    linha = vault.obter_linha(db, escola_id, plataforma) or linha_salva
    if linha is not None:
        _registrar_validacao(db, escola_id, plataforma, linha, resultado)
    if ligar_agenda and resultado.ok:
        # Credencial válida → liga a sincronização DIÁRIA automática (se ainda não
        # houver cadência), para o banco local do ano ficar em dia sozinho.
        _garantir_agenda_diaria(db, escola_id, plataforma)
    db.commit()
    return ResultadoTeste(ok=resultado.ok, mensagem=resultado.mensagem,
                          codigo=resultado.codigo,
                          **_conferencia_da_escola(db, escola_id, plataforma, resultado))


@router.put("/credenciais/{plataforma}", response_model=ResultadoTeste)
async def salvar_credenciais(plataforma: str, dados: CredenciaisIn,
                             escola_id: int = Depends(escola_autorizada),
                             usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
                             db: Session = Depends(get_db)):
    """Grava a credencial CIFRADA e valida IMEDIATAMENTE, com erro claro."""
    _validar_plataforma(plataforma)
    cred = Credenciais(usuario=dados.usuario, senha=dados.senha, extra=dados.extra)
    linha = await run_in_threadpool(_gravar_credencial, db, escola_id, plataforma, cred,
                                    usuario.id)
    if plataforma == "matific":
        # O ranking ao vivo cacheado (em memória, sem banco) era da conta antiga.
        aovivo.invalidar_cache(escola_id)

    conector = connectors.obter(plataforma)
    try:
        resultado = await conector.testar_credenciais(cred, _ctx_efemero(escola_id))
    except Exception:  # noqa: BLE001 — validação NUNCA derruba o salvamento (500)
        # Rede de segurança: os conectores já tratam falhas internamente
        # (retornam ok=False), mas nenhuma exceção pode virar 500 aqui — a
        # credencial já foi gravada. Log técnico p/ diagnóstico, sem senha.
        logger.warning("Erro inesperado ao validar credenciais de %s (escola %s)",
                       plataforma, escola_id, exc_info=True)
        resultado = ResultadoValidacao(
            ok=False,
            mensagem=("Credenciais salvas, mas não foi possível validar o login "
                      "agora. Tente validar novamente mais tarde."),
            codigo="erro_navegador")
    return await run_in_threadpool(_concluir_validacao, db, escola_id, plataforma,
                                   resultado, linha_salva=linha, ligar_agenda=True)


@router.post("/credenciais/{plataforma}/testar", response_model=ResultadoTeste)
async def testar_credenciais(plataforma: str,
                             escola_id: int = Depends(escola_autorizada),
                             usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
                             db: Session = Depends(get_db)):
    _validar_plataforma(plataforma)
    cred, gravada = await run_in_threadpool(_credencial_para_testar, db, escola_id,
                                            plataforma)
    if cred is None:
        if gravada:
            # Há credencial, mas a cifra não abre (chaves trocadas sem recifrar):
            # nada a testar, e "nenhuma configurada" seria mentira. Não grava nada
            # (o /status já deriva 'ilegivel') e não diz por que a cifra falhou.
            return ResultadoTeste(ok=False, codigo=CODIGO_CREDENCIAL_ILEGIVEL,
                                  mensagem=MENSAGEM_CREDENCIAL_ILEGIVEL)
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Nenhuma credencial configurada para esta plataforma.")
    conector = connectors.obter(plataforma)
    resultado = await conector.testar_credenciais(cred, _ctx_efemero(escola_id))
    return await run_in_threadpool(_concluir_validacao, db, escola_id, plataforma, resultado)


@router.delete("/credenciais/{plataforma}", status_code=status.HTTP_204_NO_CONTENT)
def remover_credenciais(plataforma: str,
                        escola_id: int = Depends(escola_autorizada),
                        usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
                        db: Session = Depends(get_db)):
    _validar_plataforma(plataforma)
    vault.remover_credencial(db, escola_id, plataforma)
    if plataforma == "matific":
        aovivo.limpar_sessao(db, escola_id)
        aovivo.invalidar_cache(escola_id)  # não servir ranking da conta removida
    # Sem credencial não há coleta: as FALHAS dela perderam a causa — ficam no
    # histórico, resolvidas, em vez de abertas para sempre num card "Ainda não
    # configurada". O 'desatualizada' fica: com a agenda ativa, o dado continua
    # envelhecendo de verdade (a regra única do frescor decide).
    service.resolver_falhas_da_integracao(db, escola_id, plataforma,
                                          manter=("desatualizada",))
    registrar(db, "sync.credencial_removida", escola_id=escola_id,
              usuario_id=usuario.id, detalhes={"plataforma": plataforma})
    db.commit()


# ---------------------------------------------------------------------------
# Escola EXTERNA (vínculo: sync/escola_externa.py) — qual escola da plataforma
# esta escola é. Sem segredo: id e nome que a própria plataforma mostra.
# ---------------------------------------------------------------------------
def _vinculo_publico(db: Session, escola_id: int, plataforma: str) -> dict | None:
    return _publico(escola_externa.obter(db, escola_id, plataforma))


def _publico(vinculo: dict | None) -> dict | None:
    """O que o vínculo mostra à tela (sem ``definido_por``)."""
    if vinculo is None:
        return None
    return {"id": vinculo["id"], "nome": vinculo["nome"], "origem": vinculo["origem"],
            "definido_em": vinculo["definido_em"]}


def _conferencia_da_escola(db: Session, escola_id: int, plataforma: str,
                           resultado: ResultadoValidacao) -> dict:
    """"Testar conexão": a(s) escola(s) que a conta enxerga contra o vínculo — o
    que a próxima sincronização faria (aprender, coletar ou recusar) e o aviso de
    nome divergente. Só leitura: nada é gravado aqui."""
    vinculo = _vinculo_publico(db, escola_id, plataforma)
    escolas = resultado.escolas_externas if resultado.ok else None
    saida = {"escolas_externas": escolas, "escola_vinculada": vinculo,
             "escola_confere": None, "aviso_escola": None}
    if escolas is None:
        return saida
    nome_plat = "Matific" if plataforma == "matific" else "Elefante"
    ids = {str(e.get("id") or "").lower() for e in escolas}
    avisos: list[str] = []
    if not escolas:
        avisos.append(f"Não identifiquei a escola que esta conta enxerga no {nome_plat}: "
                      "a sincronização vai recusar a coleta até a escola ser identificada.")
    elif vinculo is not None:
        saida["escola_confere"] = vinculo["id"].lower() in ids
        if not saida["escola_confere"]:
            avisos.append(
                f"A conta enxerga {escola_externa.descrever(escolas)}, mas esta escola está "
                f"vinculada à escola {escola_externa.descrever([vinculo])} da plataforma: a "
                "sincronização vai ser recusada. Confira se a credencial é desta escola.")
    elif len(escolas) > 1:
        avisos.append(
            f"A conta enxerga {len(escolas)} escolas ({escola_externa.descrever(escolas)}): "
            "a escolha de qual delas é esta escola (vínculo da escola externa) é feita "
            "pelo Admin Global antes de sincronizar — sem isso, a coleta é recusada.")
    else:
        id_ext = escola_externa.normalizar_id(plataforma, escolas[0].get("id"))
        outras = escola_externa.escolas_com_o_mesmo_vinculo(db, plataforma, id_ext,
                                                            exceto=escola_id)
        if outras:
            saida["escola_confere"] = False
            avisos.append(
                f"A conta é da escola {escola_externa.descrever(escolas)} da plataforma, "
                "que já está vinculada a outra escola do Constela: a sincronização vai "
                "ser recusada. Confira se a credencial é desta escola.")
    escola = db.get(Escola, escola_id)
    nome_cadastro = escola.nome if escola else ""
    divergentes = escola_externa.nomes_divergentes([e.get("nome") for e in escolas],
                                                   nome_cadastro)
    if divergentes and vinculo is None and len(escolas) == 1 \
            and saida["escola_confere"] is not False:
        # D9: sem vínculo, o nome divergente impede o APRENDIZADO automático — a
        # coleta segue, mas o vínculo fica para o Admin Global gravar. Quando a
        # escola externa já é o vínculo de OUTRA escola do Constela, a coleta vai
        # ser recusada (aviso acima): dizer que ela "coleta" seria contraditório,
        # e o nome fica só como conferência (revisão e97b).
        avisos.append(f"Aviso: o nome na plataforma ({'; '.join(divergentes[:3])}) é "
                      f"diferente do cadastrado ({nome_cadastro}): a sincronização coleta, "
                      "mas NÃO grava sozinha o vínculo da escola externa. Confira se a "
                      "credencial é desta escola e peça ao Admin Global para gravar o vínculo.")
    elif divergentes:
        avisos.append(f"Aviso: o nome na plataforma ({'; '.join(divergentes[:3])}) é "
                      f"diferente do cadastrado ({nome_cadastro}) — só para conferência.")
    saida["aviso_escola"] = " ".join(avisos) or None
    return saida


def _escola_externa_out(db: Session, escola_id: int, plataforma: str) -> EscolaExternaOut:
    vinculo = _vinculo_publico(db, escola_id, plataforma)
    if vinculo is None:
        return EscolaExternaOut(plataforma=plataforma, vinculada=False)
    return EscolaExternaOut(plataforma=plataforma, vinculada=True,
                            id_externo=vinculo["id"], nome=vinculo["nome"],
                            origem=vinculo["origem"], definido_em=vinculo["definido_em"])


@router.get("/escola-externa/{plataforma}", response_model=EscolaExternaOut)
def obter_escola_externa(plataforma: str,
                         escola_id: int = Depends(escola_autorizada),
                         usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
                         db: Session = Depends(get_db)):
    _validar_plataforma(plataforma)
    return _escola_externa_out(db, escola_id, plataforma)


@router.put("/escola-externa/{plataforma}", response_model=EscolaExternaOut)
def definir_escola_externa(plataforma: str, dados: EscolaExternaIn,
                           escola_id: int = Depends(escola_autorizada),
                           usuario: Usuario = Depends(exigir_admin_global),
                           db: Session = Depends(get_db)):
    """Escolha EXPLÍCITA da escola da plataforma (conta que enxerga várias escolas,
    ou troca de conta de propósito). Recusa o id de uma escola da plataforma já
    vinculada a OUTRA escola do Constela (409): uma escola externa alimenta uma
    escola só. A próxima sincronização confere a escolha contra o que a conta
    enxerga.

    SÓ O ADMIN GLOBAL (revisão e97): o vínculo é estado GLOBAL — o id gravado aqui
    passa a ser recusado na coleta de qualquer outra escola. Aberto à coordenação,
    o gestor de uma escola reservava (sem credencial) o schoolId de outra e travava
    a sincronização dela. GET e DELETE seguem com a escola: ler o próprio vínculo
    ou desfazê-lo só libera."""
    _validar_plataforma(plataforma)
    id_ext = escola_externa.normalizar_id(plataforma, dados.id_externo)
    if not id_ext:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Identificador da escola fora do formato da plataforma (Elefante: o número "
            "schoolId; Matific: o uuid school_id), como o Testar conexão mostra.")
    if escola_externa.escolas_com_o_mesmo_vinculo(db, plataforma, id_ext, exceto=escola_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Esta escola da plataforma já está vinculada a outra escola do Constela. "
            "Desfaça o vínculo de lá antes.")
    anterior = escola_externa.obter(db, escola_id, plataforma)
    escola_externa.salvar(db, escola_id, plataforma, id_ext, dados.nome,
                          origem="explicito", usuario_id=usuario.id)
    registrar(db, "sync.escola_externa_definida", escola_id=escola_id, usuario_id=usuario.id,
              entidade="plataforma",
              detalhes={"plataforma": plataforma, "id_externo": id_ext,
                        "anterior": (anterior or {}).get("id")})
    db.commit()
    return _escola_externa_out(db, escola_id, plataforma)


@router.delete("/escola-externa/{plataforma}", status_code=status.HTTP_204_NO_CONTENT)
def remover_escola_externa(plataforma: str,
                           escola_id: int = Depends(escola_autorizada),
                           usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
                           db: Session = Depends(get_db)):
    """Desfaz o vínculo: a próxima coleta o reaprende (conta de uma escola só) ou
    recusa (conta de várias escolas) — nada é aplicado sem escola conferida."""
    _validar_plataforma(plataforma)
    anterior = escola_externa.obter(db, escola_id, plataforma)
    if escola_externa.remover(db, escola_id, plataforma):
        registrar(db, "sync.escola_externa_removida", escola_id=escola_id,
                  usuario_id=usuario.id, entidade="plataforma",
                  detalhes={"plataforma": plataforma, "anterior": (anterior or {}).get("id")})
    db.commit()


# ---------------------------------------------------------------------------
# Agenda (scheduler por escola/plataforma)
# ---------------------------------------------------------------------------
@router.put("/config/{plataforma}", response_model=dict)
def salvar_config(plataforma: str, dados: ConfigIn,
                  escola_id: int = Depends(escola_autorizada),
                  usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
                  db: Session = Depends(get_db)):
    _validar_plataforma(plataforma)
    conf = db.execute(select(SincronizacaoConfig).where(
        SincronizacaoConfig.escola_id == escola_id,
        SincronizacaoConfig.plataforma == plataforma)).scalars().first()
    if conf is None:
        conf = SincronizacaoConfig(escola_id=escola_id, plataforma=plataforma)
        db.add(conf)
    conf.ativo = dados.ativo
    conf.cadencia = dados.cadencia
    conf.hora_local = dados.hora_local
    conf.dia_semana = dados.dia_semana
    db.flush()
    conf.proxima_execucao = service.calcular_proxima(conf)
    # Se a agenda foi DESLIGADA (ou virou manual), fecha um eventual alerta de
    # obsolescência — mantê-lo aberto seria mentira (não há mais nada agendado
    # para envelhecer, e ele inflaria o painel para sempre).
    if not (conf.ativo and conf.cadencia in service.OBSOLETO_POR_CADENCIA):
        service.resolver_alertas(db, escola_id, plataforma, ("desatualizada",))
    db.commit()
    return {"proxima_execucao": conf.proxima_execucao}


def _garantir_agenda_diaria(db: Session, escola_id: int, plataforma: str) -> None:
    """Liga uma agenda DIÁRIA (03:00) na PRIMEIRA vez que a credencial é validada
    — assim o banco local do ano letivo fica em dia SOZINHO. Só cria quando NÃO
    existe configuração alguma: qualquer linha já gravada é escolha explícita do
    admin (inclusive 'desligado': ativo=False + manual) e é respeitada — nunca
    reativa uma sincronização que o admin desligou de propósito (opt-out/LGPD).
    Só roda de fato quando o servidor tem SYNC_SCHEDULER_ENABLED=true."""
    conf = db.execute(select(SincronizacaoConfig).where(
        SincronizacaoConfig.escola_id == escola_id,
        SincronizacaoConfig.plataforma == plataforma)).scalars().first()
    if conf is not None:
        return  # o admin já configurou (ligado OU desligado) — não mexe
    conf = SincronizacaoConfig(escola_id=escola_id, plataforma=plataforma,
                               ativo=True, cadencia="diaria", hora_local="03:00")
    db.add(conf)
    db.flush()
    conf.proxima_execucao = service.calcular_proxima(conf)


# ---------------------------------------------------------------------------
# Ações (botões)
# ---------------------------------------------------------------------------
def _enfileirar_agora(db: Session, escola_id: int, usuario: Usuario,
                      plataforma: str | None,
                      parametros: dict | None = None,
                      ) -> list[tuple[SincronizacaoExecucao, bool]]:
    """Enfileira (ou reaproveita a ativa de) cada plataforma pedida e dispara a
    thread de quem precisa. Devolve ``(execucao, reaproveitada)`` por plataforma."""
    alvos = ([plataforma] if plataforma
             else connectors.plataformas_automatizaveis())
    # CONTRATO antes da credencial: a plataforma de um módulo fora do plano não é
    # coletada (minimização — dado de criança de um produto que a rede não
    # assinou), mesmo com a credencial ainda guardada. Pedido EXPLÍCITO dela →
    # 403; no "Sincronizar agora" de todas, ela fica de fora como a sem credencial.
    # Escola e contrato numa consulta só: o objeto que ``escola_autorizada`` leu já
    # saiu do mapa de identidade, e o ``db.get`` relia a escola antes de ler
    # ``modulos_rede`` — a escola de rede pagava 1 ida a mais que a avulsa.
    modulos = svc_modulos.modulos_por_escola(db, (escola_id,))[escola_id]
    if plataforma:
        _validar_plataforma(plataforma)
        svc_modulos.exigir_plataforma(modulos, plataforma)
    contratadas = [p for p in alvos if svc_modulos.plataforma_contratada(modulos, p)]
    if alvos and not contratadas:
        svc_modulos.exigir_plataforma(modulos, alvos[0])
    execucoes, ocupadas, ilegiveis = [], [], []
    for plat in contratadas:
        _validar_plataforma(plat)
        if vault.obter_credencial(db, escola_id, plat) is None:
            # Sem credencial: pula (aparece no status). Com credencial cuja cifra
            # não abre (status 'ilegivel'), também pula — mas, se nada rodar, a
            # recusa diz isso em vez de "nenhuma configurada".
            if vault.obter_linha(db, escola_id, plat) is not None:
                ilegiveis.append(plat)
            continue
        # A janela de datas (coleta por período) só se aplica ao Matific.
        params = parametros if (parametros and plat == "matific") else None
        ex, reaproveitada = service.enfileirar_ou_reaproveitar(
            db, escola_id, plat, origem="manual", usuario_id=usuario.id,
            parametros=params)
        if (ex.parametros or {}) != (params or {}):
            # Já há uma execução EM ANDAMENTO com outro pedido (ex.: a coleta do
            # ano inteiro, e o clique agora é "coletar este período"): devolvê-la
            # como se fosse a pedida faria o pedido sumir em silêncio.
            if plataforma or params:
                # Pedido EXPLÍCITO desta plataforma (ou de um período): recusa.
                db.rollback()
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"Já há uma sincronização do {plat} em andamento com outro "
                    "período. Aguarde ela terminar e peça de novo.")
            # "Sincronizar agora" de TODAS: a ocupada fica de fora (não é
            # devolvida como se fosse a pedida) e as demais seguem. Antes, o 409
            # com rollback desfazia também as já enfileiradas neste laço — o
            # Elefante deixava de sincronizar porque o Matific coletava um período.
            ocupadas.append(plat)
            continue
        execucoes.append((ex, reaproveitada))
    if not execucoes and ocupadas:
        # Todas as que têm credencial estavam ocupadas: nada foi pedido de fato
        # (sem isto, o "nenhuma com credencial" da rota mentiria a causa).
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Já há uma sincronização do {', '.join(ocupadas)} em andamento com "
            "outro período. Aguarde ela terminar e peça de novo.")
    if not execucoes and ilegiveis:
        # Nada a rodar porque a senha salva não abre mais: antes a rota dizia
        # "Nenhuma plataforma com credencial configurada", e a credencial existe.
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            vault.mensagem_credencial_ilegivel(ilegiveis))
    db.commit()
    for ex, _reaproveitada in execucoes:
        # Thread só para quem ainda espera alguém que a rode: a já 'executando'
        # (coleta longa + clique repetido) ou a que já tem a thread dela neste
        # processo não ganham outra — ela só esperaria o semáforo para perder o
        # claim (episódio de 21/10: 11 threads esperando depois de 6 cliques).
        if service.precisa_de_thread(ex):
            service.disparar_em_thread(ex.id)  # roda já, sem bloquear o request
    return execucoes


_RE_DATA_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@router.post("/agora", response_model=list[ExecucaoAgoraOut])
def sincronizar_agora(escola_id: int = Depends(escola_autorizada),
                      usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
                      db: Session = Depends(get_db),
                      plataforma: str | None = Query(default=None),
                      inicio: str | None = Query(default=None),
                      fim: str | None = Query(default=None)):
    """Botões 'Sincronizar agora / Matific / Elefante': obtém e importa de novo,
    enfileirando e disparando. Sem ``plataforma`` cobre todas as automatizáveis
    com credencial. A idempotência do pipeline (Matific por período/leituras,
    dedup diário dos snapshots) garante que reexecutar não duplica dados — por
    isso não existe uma ação 'reprocessar' separada: sincronizar É reprocessar.

    ``inicio``/``fim`` (AAAA-MM-DD): coleta o MATIFIC POR PERÍODO (premiação por
    semana/mês/intervalo) — o Placar é buscado com start_date/end_date e importado
    como período; ignorado para as demais plataformas."""
    parametros = None
    if inicio or fim:
        if not (inicio and fim and _RE_DATA_ISO.match(inicio) and _RE_DATA_ISO.match(fim)):
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Informe início E fim no formato AAAA-MM-DD.")
        try:
            # O formato não basta: 2026-02-31 passava, o conector não lia a data e
            # o pipeline gravava os números do período como acumulado.
            datetime.strptime(inicio, "%Y-%m-%d")
            datetime.strptime(fim, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Data inexistente no período (ex.: 31/02).") from None
        if fim < inicio:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "A data final não pode ser antes da inicial.")
        if inicio > fuso.hoje_local().isoformat():
            # Período que ainda não começou (horário de Brasília): antes entrava e
            # morria num 400 interno da importação, e a execução saía "Falha
            # inesperada" (recuperável, "erro do nosso lado").
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "O início do período não pode ser depois de hoje.")
        if (fim == inicio and plataforma in (None, "matific")
                and not matific_conector.periodo_um_dia_permitido()):
            # Com início = fim, o fim do período decide tudo — e a semântica do
            # end_date do Matific não está confirmada (MATIFIC_END_DATE). Antes, o
            # pedido entrava e morria num 400 interno da importação.
            raise HTTPException(status.HTTP_400_BAD_REQUEST, matific_conector.MSG_UM_DIA)
        parametros = {"matific_start_date": inicio, "matific_end_date": fim}
    execucoes = _enfileirar_agora(db, escola_id, usuario, plataforma, parametros)
    if not execucoes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Nenhuma plataforma com credencial configurada.")
    return [ExecucaoAgoraOut.model_validate(e).model_copy(update={"reaproveitada": r})
            for e, r in execucoes]


# HTTP por código de erro do conector (o Matific é um upstream → 502 quando ele
# nega/bloqueia; 4xx quando o problema é a configuração; 409 quando ocupado).
_STATUS_ERRO = {
    "sem_credencial": status.HTTP_400_BAD_REQUEST,
    vault.CODIGO_CREDENCIAL_ILEGIVEL: status.HTTP_400_BAD_REQUEST,
    "periodo_invalido": status.HTTP_400_BAD_REQUEST,
    "escola": status.HTTP_404_NOT_FOUND,
    "sem_conector": status.HTTP_503_SERVICE_UNAVAILABLE,
    "navegador_indisponivel": status.HTTP_503_SERVICE_UNAVAILABLE,
    "ocupado": status.HTTP_409_CONFLICT,
    "timeout": status.HTTP_504_GATEWAY_TIMEOUT,
    # A rede ou o site da plataforma falhou no meio da consulta ao vivo (DNS,
    # conexão recusada, página que não abriu): é o upstream, não um erro interno.
    "indisponivel_externo": status.HTTP_502_BAD_GATEWAY,
}


@router.get("/matific/placar-ao-vivo",
            # Trava do CONTRATO no decorador: roda antes do corpo, ou seja, antes
            # de usar a credencial guardada e de consultar o Matific.
            dependencies=[Depends(exigir_modulo_da_escola("matematica"))])
def matific_placar_ao_vivo(
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db),
    periodo: str | None = Query(default=None),
    inicio: str | None = Query(default=None),
    fim: str | None = Query(default=None),
    forcar: bool = Query(default=False),
):
    """PREMIAR POR PERÍODO — consulta o Placar do Matific EM TEMPO REAL para o
    período pedido e devolve o ranking (nome, turma, estrelas, atividades, média)
    exatamente como o site mostra. Prioriza a API por HTTP (navegador só para
    autenticar). ``periodo`` ∈ hoje|ontem|semana|semana_anterior|mes|mes_anterior
    |bimestre|bimestre_anterior|personalizado; ``inicio``/``fim`` (AAAA-MM-DD) no
    personalizado. Resultado tem cache curto; ``forcar=true`` (botão Atualizar)
    ignora o cache.

    O PROFESSOR também consulta (usa a credencial da escola guardada — nunca a
    vê), mas o servidor filtra o resultado para SÓ os alunos das turmas dele, com
    a posição RELATIVA ao recorte (1..N) e ``total``/``com_link`` do recorte — como
    o Ranking Geral do professor. A gestão vê a posição da escola inteira."""
    try:
        resultado = aovivo.placar_matific(db, escola_id, periodo=periodo,
                                          inicio=inicio, fim=fim, forcar=forcar)
    except ErroConector as exc:
        raise HTTPException(
            _STATUS_ERRO.get(exc.codigo, status.HTTP_502_BAD_GATEWAY),
            str(exc)) from exc

    permitidas = permissoes.turmas_permitidas(db, escola_id, usuario)
    if permitidas is not None:  # professor: recorta para os alunos das turmas dele
        escola = db.get(Escola, escola_id)
        ids = permissoes.alunos_permitidos(
            db, escola_id, escola.ano_letivo_ativo if escola else 0, permitidas)
        # Renumera 1..N na ordem do Placar (a posição "3º" da escola inteira não é a
        # do professor, e o pódio exige a lista começando em 1). CÓPIAS das linhas:
        # ``resultado`` é o mesmo objeto do cache curto, que a gestão também lê.
        meus = (i for i in resultado.get("itens", []) if i.get("aluno_id") in ids)
        itens = [{**i, "posicao": n} for n, i in enumerate(meus, start=1)]
        resultado = {**resultado, "itens": itens, "total": len(itens),
                     "com_link": sum(1 for i in itens if i.get("aluno_id"))}
    return resultado


@router.post("/elefante/diagnostico")
def elefante_diagnostico(
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """DIAGNÓSTICO DA INTEGRAÇÃO ELEFANTE (auto-inventário) — roda a investigação
    com a SESSÃO AUTENTICADA do robô e devolve os endpoints, a estrutura (tipos e
    chaves, SEM dado de criança), os períodos, a paginação e o DIFF vs o último
    inventário (com avisos se a API mudou). Substitui crawler/F12; nada é público.

    Falha na coleta, sempre com mensagem honesta e sem detalhe interno (ele vai para o
    log), pelo critério único de ``navegador.classificar_falha_da_coleta``:

    * 503 ``navegador_indisponivel`` — o NOSSO navegador não abriu ou caiu no meio da
      consulta: o problema é do Constela, não do Elefante; log ERROR;
    * 502 ``indisponivel_externo`` — a rede ou o site do Elefante falhou no caminho
      (DNS, conexão recusada, TLS, página que não abriu); log WARNING;
    * 504 ``timeout`` — o tempo se esgotou esperando o Elefante; log WARNING;
    * quando o conector já sabe o que houve (CAPTCHA, senha recusada…), a mensagem do
      ``ErroConector`` dele, com o status do código em ``_STATUS_ERRO`` (502 se o
      código não estiver lá); sem credencial ou com a senha salva ilegível, 400;
    * 500 "Erro interno" — defeito nosso na coleta (KeyError, TypeError, JS ou
      seletor que nós mandamos, OSError de arquivo do servidor…); log ERROR."""
    try:
        return diagnostico_elefante.executar(db, escola_id)
    except ErroConector as exc:
        raise HTTPException(
            _STATUS_ERRO.get(exc.codigo, status.HTTP_502_BAD_GATEWAY),
            str(exc)) from exc


# ---------------------------------------------------------------------------
# Histórico, logs, alertas
# ---------------------------------------------------------------------------
@router.get("/historico", response_model=list[ExecucaoOut])
def historico(escola_id: int = Depends(escola_autorizada),
              usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
              db: Session = Depends(get_db),
              plataforma: str | None = Query(default=None),
              limite: int = Query(default=50, ge=1, le=200),
              antes_de: int | None = Query(default=None)):
    q = select(SincronizacaoExecucao).where(SincronizacaoExecucao.escola_id == escola_id)
    if plataforma:
        q = q.where(SincronizacaoExecucao.plataforma == plataforma)
    if antes_de:
        q = q.where(SincronizacaoExecucao.id < antes_de)
    q = q.order_by(SincronizacaoExecucao.id.desc()).limit(limite)
    return [ExecucaoOut.model_validate(e) for e in db.execute(q).scalars()]


@router.get("/execucoes/{execucao_id}", response_model=ExecucaoOut)
def execucao_detalhe(execucao_id: int,
                     escola_id: int = Depends(escola_autorizada),
                     usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
                     db: Session = Depends(get_db)):
    ex = db.get(SincronizacaoExecucao, execucao_id)
    if ex is None or ex.escola_id != escola_id:  # isolamento explícito
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execução não encontrada.")
    return ExecucaoOut.model_validate(ex)


@router.get("/logs", response_model=list[LogOut])
def logs(escola_id: int = Depends(escola_autorizada),
         usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
         db: Session = Depends(get_db),
         execucao_id: int | None = Query(default=None),
         etapa: str | None = Query(default=None),
         nivel: str | None = Query(default=None),
         q: str | None = Query(default=None),
         limite: int = Query(default=200, ge=1, le=1000)):
    consulta = select(SincronizacaoLog).where(SincronizacaoLog.escola_id == escola_id)
    if execucao_id:
        consulta = consulta.where(SincronizacaoLog.execucao_id == execucao_id)
    if etapa:
        consulta = consulta.where(SincronizacaoLog.etapa == etapa)
    if nivel:
        consulta = consulta.where(SincronizacaoLog.nivel == nivel)
    if q:
        consulta = consulta.where(SincronizacaoLog.mensagem.icontains(q, autoescape=True))
    consulta = consulta.order_by(SincronizacaoLog.id.desc()).limit(limite)
    return [LogOut.model_validate(x) for x in db.execute(consulta).scalars()]


@router.get("/alertas", response_model=list[AlertaOut])
def alertas(escola_id: int = Depends(escola_autorizada),
            usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
            db: Session = Depends(get_db),
            resolvido: bool | None = Query(default=None)):
    q = select(SincronizacaoAlerta).where(SincronizacaoAlerta.escola_id == escola_id)
    if resolvido is not None:
        q = q.where(SincronizacaoAlerta.resolvido.is_(resolvido))
    q = q.order_by(SincronizacaoAlerta.id.desc()).limit(200)
    return [AlertaOut.model_validate(a) for a in db.execute(q).scalars()]


@router.post("/alertas/{alerta_id}/resolver", status_code=status.HTTP_204_NO_CONTENT)
def resolver_alerta(alerta_id: int,
                    escola_id: int = Depends(escola_autorizada),
                    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
                    db: Session = Depends(get_db)):
    al = db.get(SincronizacaoAlerta, alerta_id)
    if al is None or al.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alerta não encontrado.")
    al.resolvido = True
    al.resolvido_em = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()


# ---------------------------------------------------------------------------
# Dashboard global (cross-escola) — só usuário GLOBAL
# ---------------------------------------------------------------------------
# Importado aqui (e não no topo) para a mudança ficar só no trecho do painel.
from app.sync import prerequisitos  # noqa: E402


class DashboardComPrerequisitosOut(DashboardOut):
    """O painel global + os pré-requisitos para religar o agendador (P3). Só o
    admin global chega aqui; o bloco é mínimo (id, ok, crítico, motivo — sem
    segredo nem nome de escola). None = a verificação não pôde rodar."""
    prerequisitos_agendador: prerequisitos.PrerequisitosAgendadorOut | None = None


def _prerequisitos_do_painel(db: Session):
    """Os pré-requisitos (só leitura) para o painel; uma falha aqui nunca
    derruba o painel inteiro."""
    try:
        return prerequisitos.para_painel(db, decisao=scheduler.decisao())
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("Painel global: pré-requisitos do agendador indisponíveis.")
        return None


@router_global.get("/dashboard", response_model=DashboardComPrerequisitosOut)
def dashboard(usuario: Usuario = Depends(get_usuario_atual),
              db: Session = Depends(get_db)):
    if not usuario.is_global:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Painel global exige usuário com acesso total.")
    # Idas ao banco: o painel é relido pelo polling da tela de Integrações do admin
    # global e cada consulta custa uma ida inteira (~195 ms em produção). Os dez
    # números saem de UMA instrução (uma subconsulta escalar cada, as mesmas
    # consultas de antes); as desatualizadas e os pré-requisitos têm idas fixas,
    # qualquer que seja o número de agendas. A forma da resposta não muda.
    E, A = SincronizacaoExecucao, SincronizacaoAlerta
    (escolas_total, escolas_config, em_andamento, fila, com_erro, sincronizadas, ultima,
     tempo_medio, dur_ultima, alertas_abertos) = db.execute(select(
        select(func.count(Escola.id)).scalar_subquery(),
        select(func.count(func.distinct(PlataformaCredencial.escola_id))).scalar_subquery(),
        select(func.count(E.id)).where(E.status == "executando").scalar_subquery(),
        select(func.count(E.id)).where(E.status == "fila").scalar_subquery(),
        # "Com erro" = FALHAS de execução (crítico) — exclui 'desatualizada', que tem
        # seu próprio contador; senão a mesma escola contaria nos dois (dupla contagem).
        select(func.count(func.distinct(A.escola_id))).where(
            A.resolvido.is_(False), A.severidade == "critico",
            A.tipo.notin_(service.TIPOS_REGRA_PROPRIA)).scalar_subquery(),
        # Sincronizada = ao menos uma execução que APLICOU dado (concluída, ou parcial
        # com aluno aplicado — ``service._filtro_aplicou_dado``; a parcial de 0 aluno
        # da D2(6) não trouxe dado). A coleta por período continua contando aqui.
        select(func.count(func.distinct(E.escola_id)))
        .where(service._filtro_aplicou_dado()).scalar_subquery(),
        select(func.max(E.finalizada_em)).where(service._filtro_aplicou_dado())
        .scalar_subquery(),
        select(func.avg(E.duracao_ms)).where(E.status == "concluida", E.duracao_ms > 0)
        .scalar_subquery(),
        select(E.duracao_ms).where(E.status == "concluida")
        .order_by(E.finalizada_em.desc()).limit(1).scalar_subquery(),
        select(func.count(A.id)).where(A.resolvido.is_(False)).scalar_subquery(),
    )).one()
    escolas_total, escolas_config = escolas_total or 0, escolas_config or 0
    em_andamento, fila, com_erro = em_andamento or 0, fila or 0, com_erro or 0
    sincronizadas, alertas_abertos = sincronizadas or 0, alertas_abertos or 0
    # Pela REGRA (a mesma do /status), não pelos alertas: o alerta só nasce quando
    # alguém lê o status ou uma execução termina — o painel não pode depender disso.
    desatualizadas = len(service.escolas_desatualizadas(db))
    return DashboardComPrerequisitosOut(
        escolas_total=escolas_total, escolas_configuradas=escolas_config,
        escolas_sincronizadas=sincronizadas, escolas_com_erro=com_erro,
        escolas_desatualizadas=desatualizadas,
        em_andamento=em_andamento, fila=fila,
        workers_ativos=(1 if scheduler.ativo() else 0),
        scheduler_ligado=scheduler.ativo(),
        ultima_sincronizacao=ultima,
        duracao_ultima_ms=int(dur_ultima) if dur_ultima else None,
        tempo_medio_ms=int(tempo_medio) if tempo_medio else None,
        alertas_abertos=alertas_abertos,
        prerequisitos_agendador=_prerequisitos_do_painel(db))
