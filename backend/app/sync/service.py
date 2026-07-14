"""Motor de execução da sincronização — fila, ciclo de vida, retries, alertas.

Uma EXECUÇÃO (``SincronizacaoExecucao``) é a unidade de trabalho: enfileirada
(``fila``) → o worker a pega (``executando``) → conclui (``concluida`` /
``sem_dados`` / ``erro``). Idempotência/duplicidade: nunca há duas execuções
ativas para o mesmo (escola, plataforma). Erros recuperáveis re-enfileiram com
backoff exponencial até ``SYNC_MAX_TENTATIVAS``.

O conector (I/O de rede/navegador) é assíncrono; a aplicação no banco é
síncrona (reusa o pipeline). Rodamos o fetch com ``asyncio.run`` na mesma
thread do worker — o conector não toca o banco; só o ``log`` toca, sequencial.
"""
from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.escola import Escola
from app.models.sincronizacao import (
    SincronizacaoAlerta,
    SincronizacaoConfig,
    SincronizacaoExecucao,
    SincronizacaoLog,
)
from app.sync import connectors, vault
from app.sync import orchestrator
from app.sync.interfaces import Contexto, ErroConector


def _agora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --------------------------------------------------------------------------
# Logs e alertas (nunca com segredo)
# --------------------------------------------------------------------------
def registrar_log(db: Session, execucao: SincronizacaoExecucao, etapa: str,
                  nivel: str, mensagem: str) -> None:
    db.add(SincronizacaoLog(execucao_id=execucao.id, escola_id=execucao.escola_id,
                            etapa=etapa, nivel=nivel, mensagem=mensagem[:1000]))
    db.flush()


def abrir_alerta(db: Session, escola_id: int, plataforma: str | None, tipo: str,
                 mensagem: str, *, severidade: str = "warn",
                 execucao_id: int | None = None) -> None:
    """Abre um alerta se ainda não houver um IGUAL em aberto (evita spam)."""
    existe = db.execute(
        select(SincronizacaoAlerta).where(
            SincronizacaoAlerta.escola_id == escola_id,
            SincronizacaoAlerta.plataforma == plataforma,
            SincronizacaoAlerta.tipo == tipo,
            SincronizacaoAlerta.resolvido.is_(False),
        )
    ).scalars().first()
    if existe is not None:
        return
    db.add(SincronizacaoAlerta(
        escola_id=escola_id, plataforma=plataforma, tipo=tipo,
        severidade=severidade, mensagem=mensagem[:500], execucao_id=execucao_id))
    db.flush()


def resolver_alertas(db: Session, escola_id: int, plataforma: str,
                     tipos: tuple[str, ...]) -> None:
    """Fecha alertas de dado tipo (ex.: após uma sync bem-sucedida)."""
    for al in db.execute(
        select(SincronizacaoAlerta).where(
            SincronizacaoAlerta.escola_id == escola_id,
            SincronizacaoAlerta.plataforma == plataforma,
            SincronizacaoAlerta.tipo.in_(tipos),
            SincronizacaoAlerta.resolvido.is_(False),
        )
    ).scalars():
        al.resolvido = True
        al.resolvido_em = _agora()
    db.flush()


# --------------------------------------------------------------------------
# Fila
# --------------------------------------------------------------------------
def _execucao_ativa(db: Session, escola_id: int, plataforma: str):
    return db.execute(
        select(SincronizacaoExecucao).where(
            SincronizacaoExecucao.escola_id == escola_id,
            SincronizacaoExecucao.plataforma == plataforma,
            SincronizacaoExecucao.status.in_(("fila", "executando")),
        )
    ).scalars().first()


def _esta_travada(execucao: SincronizacaoExecucao) -> bool:
    """True se a execução está presa em 'executando' além de ``SYNC_TRAVADA_S``
    (worker morto/redeploy no meio) — órfã, precisa ser recuperada."""
    if execucao.status != "executando" or execucao.iniciada_em is None:
        return False
    limite = _agora() - timedelta(seconds=settings.SYNC_TRAVADA_S)
    return execucao.iniciada_em < limite


def _finalizar_travada(db: Session, execucao: SincronizacaoExecucao) -> bool:
    """Marca (atomicamente) uma execução órfã como 'erro'. Devolve True se ESTE
    chamador a reivindicou (para então re-enfileirar/limpar a exclusão mútua)."""
    reivindicou = db.execute(
        update(SincronizacaoExecucao)
        .where(SincronizacaoExecucao.id == execucao.id,
               SincronizacaoExecucao.status == "executando")
        .values(status="erro", finalizada_em=_agora(),
                erro_resumo="Interrompida (reinício do serviço ou timeout).")
    ).rowcount
    return reivindicou == 1


def enfileirar(db: Session, escola_id: int, plataforma: str, *, origem: str,
               usuario_id: int | None = None, tentativa: int = 1,
               disponivel_em: datetime | None = None,
               parametros: dict | None = None) -> SincronizacaoExecucao:
    """Cria uma execução na fila. IDEMPOTENTE / anti-duplicidade em DUAS camadas:
    (1) fast-path: se já houver uma ativa (fila/executando) para (escola,
    plataforma), devolve-a; (2) garantia forte: o índice único parcial
    ``uq_sync_exec_ativa`` no banco impede que dois enfileiramentos concorrentes
    (clique duplo, scheduler + manual, múltiplas réplicas) criem duas ativas —
    a corrida perdida cai no ``IntegrityError`` e devolve a existente."""
    ativa = _execucao_ativa(db, escola_id, plataforma)
    if ativa is not None:
        if not _esta_travada(ativa):
            return ativa
        # Órfã presa em 'executando' (worker morto/redeploy). Auto-cura: tenta
        # reivindicá-la e liberá-la para criar a nova — senão a exclusão mútua
        # (uq_sync_exec_ativa) travaria a escola até um reinício.
        if _finalizar_travada(db, ativa):
            abrir_alerta(db, escola_id, plataforma, "interrompida",
                         "Sincronização anterior foi interrompida e reprogramada.",
                         severidade="warn", execucao_id=ativa.id)
            db.flush()
        else:
            # Perdemos a corrida para o reaper concorrente: NÃO devolver a órfã
            # já morta (o pedido deste chamador se perderia). Re-checa o estado —
            # se o reaper re-enfileirou uma nova ativa, devolve-a; senão (ex.:
            # última tentativa, sem retry) cai adiante e cria a que foi pedida.
            ativa = _execucao_ativa(db, escola_id, plataforma)
            if ativa is not None:
                return ativa
    execucao = SincronizacaoExecucao(
        escola_id=escola_id, plataforma=plataforma, origem=origem,
        usuario_id=usuario_id, status="fila", tentativa=tentativa,
        disponivel_em=disponivel_em, parametros=parametros or {},
        conector_versao=getattr(connectors.obter(plataforma), "versao", None))
    try:
        with db.begin_nested():          # savepoint: só o INSERT rola em conflito
            db.add(execucao)
            db.flush()
    except IntegrityError:
        # Outro worker/clique criou a ativa entre o SELECT e o INSERT.
        existente = _execucao_ativa(db, escola_id, plataforma)
        if existente is not None:
            return existente
        raise
    return execucao


def proximas_da_fila(db: Session, limite: int = 10) -> list[SincronizacaoExecucao]:
    agora = _agora()
    return list(db.execute(
        select(SincronizacaoExecucao)
        .where(SincronizacaoExecucao.status == "fila",
               (SincronizacaoExecucao.disponivel_em.is_(None))
               | (SincronizacaoExecucao.disponivel_em <= agora))
        .order_by(SincronizacaoExecucao.id)
        .limit(limite)
    ).scalars())


# --------------------------------------------------------------------------
# Execução
# --------------------------------------------------------------------------
def _contexto(db: Session, execucao: SincronizacaoExecucao, *,
              autonomo: bool = False) -> Contexto:
    """autonomo=True: cada log COMMITA — usado na fase de FETCH externo, para
    não segurar uma transação aberta durante a I/O de rede/navegador
    (idle-in-transaction derrubaria a conexão em Postgres gerenciado).
    autonomo=False (padrão): o log participa da transação da execução
    (persistência atômica, com um único commit no fim)."""
    def log(etapa: str, nivel: str, mensagem: str) -> None:
        registrar_log(db, execucao, etapa, nivel, mensagem)
        if autonomo:
            db.commit()
    return Contexto(escola_id=execucao.escola_id, execucao_id=execucao.id,
                    log=log, timeout_s=settings.SYNC_TIMEOUT_S)


_NS_INCREMENTAL = "sync_incremental"   # namespace da Configuracao (KV) por escola


def _carregar_contadores(db: Session, escola_id: int, plataforma: str) -> dict:
    """{studentId: total_de_livros} da última sync bem-sucedida (por escola/
    plataforma). Base do incremental SEGURO por aluno: quem não mudou, o conector
    pula. Guardado na tabela Configuracao (KV genérico — sem migração)."""
    from app.models.configuracao import Configuracao

    row = db.execute(
        select(Configuracao).where(
            Configuracao.escola_id == escola_id,
            Configuracao.namespace == _NS_INCREMENTAL,
            Configuracao.chave == plataforma)
    ).scalar_one_or_none()
    return dict(row.valor) if row and isinstance(row.valor, dict) else {}


def _salvar_contadores(db: Session, escola_id: int, plataforma: str,
                       contadores: dict) -> None:
    """Persiste (fazendo MERGE) as contagens por aluno vistas nesta sync. O merge
    preserva as contagens de turmas que falharam nesta rodada (não vieram em
    ``contadores``) — assim uma falha parcial nunca zera o cursor de um aluno."""
    if not contadores:
        return
    from app.models.configuracao import Configuracao

    row = db.execute(
        select(Configuracao).where(
            Configuracao.escola_id == escola_id,
            Configuracao.namespace == _NS_INCREMENTAL,
            Configuracao.chave == plataforma)
    ).scalar_one_or_none()
    if row is None:
        row = Configuracao(escola_id=escola_id, namespace=_NS_INCREMENTAL,
                           chave=plataforma, valor={})
        db.add(row)
    atual = dict(row.valor) if isinstance(row.valor, dict) else {}
    for sid, total in contadores.items():
        try:
            atual[str(sid)] = int(total)
        except (TypeError, ValueError):
            continue
    row.valor = atual


def executar(db: Session, execucao: SincronizacaoExecucao) -> SincronizacaoExecucao:
    """Roda UMA execução do início ao fim. Atualiza status, contadores, logs e
    alertas. Em erro recuperável, re-enfileira com backoff."""
    # Claim ATÔMICO: garante que só UM worker pega a execução (vários uvicorn
    # workers/réplicas apontam para o mesmo banco). Quem perder a corrida sai.
    claim = db.execute(
        update(SincronizacaoExecucao)
        .where(SincronizacaoExecucao.id == execucao.id,
               SincronizacaoExecucao.status == "fila")
        .values(status="executando", iniciada_em=_agora()))
    db.commit()
    if claim.rowcount == 0:
        return execucao
    db.refresh(execucao)
    inicio = time.monotonic()
    contexto = _contexto(db, execucao)
    escola = db.get(Escola, execucao.escola_id)
    conector = connectors.obter(execucao.plataforma)

    try:
        if escola is None:
            raise ErroConector("Escola inexistente.", codigo="escola",
                               recuperavel=False)
        if conector is None:
            raise ErroConector(f"Sem conector para {execucao.plataforma}.",
                               codigo="parser_incompativel", recuperavel=False)
        cred = vault.obter_credencial(db, execucao.escola_id, execucao.plataforma)
        # Parâmetros DESTA execução (ex.: janela de datas do Matific) entram no
        # extra da credencial — o conector os lê (matific_start_date/end_date).
        if cred is not None and execucao.parametros:
            cred.extra = {**(cred.extra or {}), **execucao.parametros}
        if cred is None:
            raise ErroConector(
                "Credenciais não configuradas ou ilegíveis.",
                codigo="senha_invalida", recuperavel=False)

        registrar_log(db, execucao, "autenticacao", "info",
                      f"Conectando à {execucao.plataforma}…")
        # Não segurar uma transação aberta durante o FETCH externo (rede/
        # navegador): idle-in-transaction derrubaria a conexão em Postgres
        # gerenciado. Constrói o contexto de fetch ANTES do commit (captura
        # escola_id/execucao_id já carregados, sem reabrir transação depois),
        # commita o que leu/logou e roda o conector com logs AUTÔNOMOS — `cred`
        # é objeto simples (Credenciais) e `escola` recarrega sob demanda na
        # persistência, que segue transacional (commit único no fim).
        contexto_fetch = _contexto(db, execucao, autonomo=True)
        # INCREMENTAL SEGURO: passa as contagens por aluno da última sync — o
        # conector pula a coleta pesada de quem não mudou (aluno novo/atrasado
        # SEMPRE coleta tudo). 1ª sync = vazio = tudo.
        contexto_fetch.contadores_anteriores = _carregar_contadores(
            db, execucao.escola_id, execucao.plataforma)
        db.commit()
        arquivos = asyncio.run(conector.sincronizar(cred, contexto_fetch))
        execucao.parser_versao = "perfis_pdf/planilhas"

        totais = {"alunos": 0, "erros": 0, "turmas": 0, "arquivos": 0}
        for i, arquivo in enumerate(arquivos):
            # Só recalcula no ÚLTIMO arquivo (economia; igual ao lote manual).
            recalcular = (i == len(arquivos) - 1)
            res = orchestrator.aplicar_arquivo(
                db, escola, arquivo, usuario_id=execucao.usuario_id,
                recalcular=recalcular, contexto=contexto)
            totais["arquivos"] += 1
            if not res.get("sem_dados"):
                totais["alunos"] += res["qtd_alunos"]
                totais["erros"] += res["qtd_erros"]
                totais["turmas"] += res["qtd_turmas"]

        execucao.qtd_arquivos = totais["arquivos"]
        execucao.qtd_alunos = totais["alunos"]
        execucao.qtd_erros = totais["erros"]
        execucao.qtd_turmas = totais["turmas"]
        execucao.qtd_alteracoes = totais["alunos"]
        execucao.status = "concluida" if totais["arquivos"] else "sem_dados"
        # INCREMENTAL: guarda as contagens por aluno vistas nesta sync (merge) —
        # a próxima pula quem não mudou.
        if totais["arquivos"]:
            _salvar_contadores(db, execucao.escola_id, execucao.plataforma,
                               contexto_fetch.contadores_novos)
        # Sucesso: fecha alertas de credencial/indisponibilidade da plataforma.
        vault_linha = vault.obter_linha(db, execucao.escola_id, execucao.plataforma)
        if vault_linha is not None:
            vault.marcar_status(db, vault_linha, "valida")
        resolver_alertas(db, execucao.escola_id, execucao.plataforma,
                         ("senha_invalida", "senha_expirada", "falha_auth",
                          "falha_download", "timeout", "plataforma_indisponivel"))
        registrar_log(db, execucao, "importacao", "info",
                      f"Concluído: {totais['alunos']} aluno(s), "
                      f"{totais['arquivos']} arquivo(s).")

    except ErroConector as exc:
        _tratar_falha(db, execucao, contexto, exc.codigo, str(exc),
                      recuperavel=exc.recuperavel)
    except Exception as exc:  # noqa: BLE001 — qualquer falha inesperada é logada
        _tratar_falha(db, execucao, contexto, "erro_inesperado",
                      f"Falha inesperada: {type(exc).__name__}", recuperavel=True)

    execucao.finalizada_em = _agora()
    execucao.duracao_ms = int((time.monotonic() - inicio) * 1000)
    if execucao.duracao_ms > settings.SYNC_LENTO_S * 1000:
        abrir_alerta(db, execucao.escola_id, execucao.plataforma, "lento",
                     f"Sincronização levou {execucao.duracao_ms // 1000}s "
                     f"(> {settings.SYNC_LENTO_S}s).", severidade="info",
                     execucao_id=execucao.id)
    db.commit()
    return execucao


# Códigos que viram alerta acionável, com severidade.
_ALERTA_POR_CODIGO = {
    "senha_invalida": ("senha_invalida", "critico"),
    "senha_expirada": ("senha_expirada", "critico"),
    "falha_auth": ("falha_autenticacao", "warn"),
    "falha_download": ("falha_download", "warn"),
    "timeout": ("timeout", "warn"),
    "navegador_indisponivel": ("plataforma_indisponivel", "critico"),
    "parser_incompativel": ("parser_incompativel", "critico"),
}


def _tratar_falha(db: Session, execucao: SincronizacaoExecucao, contexto: Contexto,
                  codigo: str, mensagem: str, *, recuperavel: bool) -> None:
    execucao.status = "erro"
    execucao.erro_resumo = mensagem[:300]
    registrar_log(db, execucao, "scheduler", "error", mensagem)
    tipo, sev = _ALERTA_POR_CODIGO.get(codigo, ("falha_download", "warn"))
    abrir_alerta(db, execucao.escola_id, execucao.plataforma, tipo, mensagem,
                 severidade=sev, execucao_id=execucao.id)
    # marca a credencial como inválida quando for o caso
    if codigo in ("senha_invalida", "senha_expirada"):
        linha = vault.obter_linha(db, execucao.escola_id, execucao.plataforma)
        if linha is not None:
            vault.marcar_status(db, linha, "invalida", mensagem)
    # retry com backoff exponencial p/ falhas recuperáveis
    if recuperavel and execucao.tentativa < settings.SYNC_MAX_TENTATIVAS:
        atraso = settings.SYNC_BACKOFF_BASE_S * (2 ** (execucao.tentativa - 1))
        proxima = _agora() + timedelta(seconds=atraso)
        enfileirar(db, execucao.escola_id, execucao.plataforma,
                   origem=execucao.origem, usuario_id=execucao.usuario_id,
                   tentativa=execucao.tentativa + 1, disponivel_em=proxima)
        registrar_log(db, execucao, "scheduler", "warn",
                      f"Reenfileirado (tentativa {execucao.tentativa + 1}) em "
                      f"{atraso}s.")


def executar_por_id(execucao_id: int) -> None:
    """Roda uma execução com sessão PRÓPRIA (para thread de fundo)."""
    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        ex = db.get(SincronizacaoExecucao, execucao_id)
        if ex is not None:
            executar(db, ex)
    finally:
        db.close()


def disparar_em_thread(execucao_id: int) -> None:
    """Processa uma execução manual sem bloquear o request (thread daemon)."""
    threading.Thread(target=executar_por_id, args=(execucao_id,),
                     daemon=True, name=f"sync-manual-{execucao_id}").start()


# --------------------------------------------------------------------------
# Agendamento (cadência → próxima execução)
# --------------------------------------------------------------------------
def calcular_proxima(config: SincronizacaoConfig, base: datetime | None = None) -> datetime | None:
    """Próxima execução a partir da cadência. None se manual/inativo."""
    if not config.ativo or config.cadencia == "manual":
        return None
    base = base or _agora()
    hh, mm = (config.hora_local or "03:00").split(":")
    alvo = base.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    if config.cadencia == "diaria":
        if alvo <= base:
            alvo += timedelta(days=1)
        return alvo
    if config.cadencia == "semanal":
        dia = config.dia_semana if config.dia_semana is not None else 0
        delta = (dia - alvo.weekday()) % 7
        alvo += timedelta(days=delta)
        if alvo <= base:
            alvo += timedelta(days=7)
        return alvo
    return None


def enfileirar_agendados(db: Session) -> int:
    """Varre configs vencidas e enfileira as execuções (chamado pelo worker).

    CLAIM ATÔMICO da config: ``UPDATE ... WHERE proxima_execucao<=agora`` avança
    a próxima e só enfileira se ganharmos a corrida (rowcount==1). Assim, N
    schedulers (um por réplica) nunca enfileiram a mesma agenda duas vezes — o
    lock de linha do UPDATE serializa e o WHERE re-checa a janela."""
    agora = _agora()
    n = 0
    vencidas = db.execute(
        select(SincronizacaoConfig).where(
            SincronizacaoConfig.ativo.is_(True),
            SincronizacaoConfig.cadencia != "manual",
            SincronizacaoConfig.proxima_execucao.isnot(None),
            SincronizacaoConfig.proxima_execucao <= agora,
        )
    ).scalars().all()
    for config in vencidas:
        nova = calcular_proxima(config, agora)
        reivindicou = db.execute(
            update(SincronizacaoConfig)
            .where(SincronizacaoConfig.id == config.id,
                   SincronizacaoConfig.proxima_execucao <= agora)
            .values(proxima_execucao=nova)).rowcount
        if reivindicou == 1:
            enfileirar(db, config.escola_id, config.plataforma, origem="scheduler")
            db.commit()               # solta o lock da config e publica a fila
            n += 1
        else:
            db.rollback()             # outro worker reivindicou; descarta
    return n


def finalizar_orfas_no_boot(db: Session) -> int:
    """No BOOT do processo: toda execução ainda em 'executando' é ÓRFÃ — o worker
    que a rodava morreu no restart/redeploy (instância única: nada está rodando
    ao subir). Marca como 'erro' e LIBERA a trava (uq_sync_exec_ativa) na hora,
    SEM re-enfileirar (o usuário retoma quando quiser). Assim um redeploy no meio
    de uma sync não prende a escola até o timeout de 30 min. Idempotente."""
    orfas = db.execute(
        select(SincronizacaoExecucao).where(
            SincronizacaoExecucao.status == "executando")
    ).scalars().all()
    n = 0
    for ex in orfas:
        if _finalizar_travada(db, ex):
            n += 1
    if n:
        db.commit()
    return n


def recuperar_execucoes_travadas(db: Session) -> int:
    """Reaper (retomada após crash): execuções presas em 'executando' além de
    ``SYNC_TRAVADA_S`` — worker morto ou redeploy no meio — são finalizadas como
    'erro' e re-enfileiradas (respeitando o limite de tentativas). Sem isto, o
    índice de exclusão mútua prenderia a escola até uma intervenção manual.

    Roda no início de cada rodada do scheduler. É seguro com várias réplicas: o
    UPDATE atômico garante que só um worker reivindica cada órfã."""
    orfas = db.execute(
        select(SincronizacaoExecucao).where(
            SincronizacaoExecucao.status == "executando",
            SincronizacaoExecucao.iniciada_em.isnot(None),
            SincronizacaoExecucao.iniciada_em
            < (_agora() - timedelta(seconds=settings.SYNC_TRAVADA_S)),
        )
    ).scalars().all()
    n = 0
    for ex in orfas:
        if not _finalizar_travada(db, ex):
            db.rollback()             # outro worker já a reivindicou
            continue
        abrir_alerta(db, ex.escola_id, ex.plataforma, "interrompida",
                     "Sincronização interrompida (reinício do serviço) e reprogramada.",
                     severidade="warn", execucao_id=ex.id)
        if ex.tentativa < settings.SYNC_MAX_TENTATIVAS:
            enfileirar(db, ex.escola_id, ex.plataforma, origem=ex.origem,
                       usuario_id=ex.usuario_id, tentativa=ex.tentativa + 1)
        db.commit()
        n += 1
    return n
