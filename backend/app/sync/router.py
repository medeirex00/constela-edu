"""API do Módulo de Sincronização (painel administrativo).

Isolamento multi-tenant: as rotas por-escola usam ``escola_autorizada`` (a
escola do path tem de bater com a do usuário; global vê todas) e exigem
admin/coordenador. O dashboard cross-escola exige usuário GLOBAL. Nenhuma
resposta jamais inclui senha (o cofre só devolve status).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

logger = logging.getLogger("constela.sync")

from app.core.database import get_db
from app.core.deps import escola_autorizada, exigir_papeis, get_usuario_atual
from app.models import Aluno, Escola, Turma, Usuario
from app.models.sincronizacao import (
    PlataformaCredencial,
    SincronizacaoAlerta,
    SincronizacaoConfig,
    SincronizacaoExecucao,
    SincronizacaoLog,
)
from app.services import permissoes
from app.services.audit import registrar
from app.sync import aovivo, connectors, diagnostico_elefante, scheduler, service, vault
from app.sync.interfaces import Contexto, Credenciais, ErroConector, ResultadoValidacao
from app.sync.schemas import (
    AlertaOut,
    ConfigIn,
    CredenciaisIn,
    DashboardOut,
    EscolaStatus,
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


def _ultima_execucao(db: Session, escola_id: int, plataforma: str):
    return db.execute(
        select(SincronizacaoExecucao)
        .where(SincronizacaoExecucao.escola_id == escola_id,
               SincronizacaoExecucao.plataforma == plataforma)
        .order_by(SincronizacaoExecucao.id.desc()).limit(1)
    ).scalars().first()


# ---------------------------------------------------------------------------
# Status por escola
# ---------------------------------------------------------------------------
@router.get("/status", response_model=EscolaStatus)
def status_escola(escola_id: int = Depends(escola_autorizada),
                  usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
                  db: Session = Depends(get_db)):
    escola = db.get(Escola, escola_id)
    qtd_alunos = db.scalar(select(func.count(Aluno.id)).where(
        Aluno.escola_id == escola_id, Aluno.status == "ativo")) or 0
    qtd_turmas = db.scalar(select(func.count(Turma.id)).where(
        Turma.escola_id == escola_id)) or 0

    creds = {c.plataforma: c for c in db.execute(select(PlataformaCredencial)
             .where(PlataformaCredencial.escola_id == escola_id)).scalars()}
    confs = {c.plataforma: c for c in db.execute(select(SincronizacaoConfig)
             .where(SincronizacaoConfig.escola_id == escola_id)).scalars()}

    plataformas = []
    for con in connectors.listar():
        if con.plataforma == "manual":
            continue
        cred = creds.get(con.plataforma)
        conf = confs.get(con.plataforma)
        ult = _ultima_execucao(db, escola_id, con.plataforma)
        plataformas.append(PlataformaStatus(
            plataforma=con.plataforma, estrategia=con.estrategia.value,
            conectada=bool(cred and cred.status == "valida"),
            credencial_status=cred.status if cred else "nao_configurada",
            validada_em=cred.validada_em if cred else None,
            ultimo_erro=cred.ultimo_erro if cred else None,
            agendada=bool(conf and conf.ativo),
            cadencia=conf.cadencia if conf else "manual",
            hora_local=conf.hora_local if conf else "03:00",
            dia_semana=conf.dia_semana if conf else None,
            proxima_execucao=conf.proxima_execucao if conf else None,
            ultima_execucao=ExecucaoOut.model_validate(ult) if ult else None))

    abertos = db.scalar(select(func.count(SincronizacaoAlerta.id)).where(
        SincronizacaoAlerta.escola_id == escola_id,
        SincronizacaoAlerta.resolvido.is_(False))) or 0
    return EscolaStatus(escola_id=escola_id, escola_nome=escola.nome if escola else "",
                        qtd_alunos=qtd_alunos, qtd_turmas=qtd_turmas,
                        plataformas=plataformas, alertas_abertos=abertos,
                        lista_piloto_importada=qtd_turmas > 0,
                        integracao_configurada=len(creds) > 0)


# ---------------------------------------------------------------------------
# Credenciais
# ---------------------------------------------------------------------------
@router.put("/credenciais/{plataforma}", response_model=ResultadoTeste)
async def salvar_credenciais(plataforma: str, dados: CredenciaisIn,
                             escola_id: int = Depends(escola_autorizada),
                             usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
                             db: Session = Depends(get_db)):
    """Grava a credencial CIFRADA e valida IMEDIATAMENTE, com erro claro."""
    _validar_plataforma(plataforma)
    cred = Credenciais(usuario=dados.usuario, senha=dados.senha, extra=dados.extra)
    linha = vault.salvar_credencial(db, escola_id, plataforma, cred)
    if plataforma == "matific":
        aovivo.limpar_sessao(db, escola_id)     # esquece sessão da credencial antiga
        aovivo.invalidar_cache(escola_id)       # e o ranking cacheado da conta antiga
    registrar(db, "sync.credencial_salva", escola_id=escola_id, usuario_id=usuario.id,
              entidade="plataforma", detalhes={"plataforma": plataforma})  # sem senha
    db.commit()

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
    # Relê a linha DEPOIS do await (I/O longo): não sobrescreve um status que
    # uma execução concorrente possa ter mudado nesse intervalo (lost update).
    linha = vault.obter_linha(db, escola_id, plataforma) or linha
    vault.marcar_status(db, linha, "valida" if resultado.ok else "invalida",
                        None if resultado.ok else resultado.mensagem)
    if resultado.ok:
        service.resolver_alertas(db, escola_id, plataforma,
                                 ("senha_invalida", "senha_expirada", "falha_auth"))
        # Credencial válida → liga a sincronização DIÁRIA automática (se ainda não
        # houver cadência), para o banco local do ano ficar em dia sozinho.
        _garantir_agenda_diaria(db, escola_id, plataforma)
    else:
        service.abrir_alerta(db, escola_id, plataforma,
                             resultado.codigo or "senha_invalida", resultado.mensagem,
                             severidade="critico")
    db.commit()
    return ResultadoTeste(ok=resultado.ok, mensagem=resultado.mensagem,
                          codigo=resultado.codigo)


@router.post("/credenciais/{plataforma}/testar", response_model=ResultadoTeste)
async def testar_credenciais(plataforma: str,
                             escola_id: int = Depends(escola_autorizada),
                             usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
                             db: Session = Depends(get_db)):
    _validar_plataforma(plataforma)
    cred = vault.obter_credencial(db, escola_id, plataforma)
    if cred is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Nenhuma credencial configurada para esta plataforma.")
    conector = connectors.obter(plataforma)
    db.rollback()  # solta a conexão do pool antes do await de I/O longo (navegador)
    resultado = await conector.testar_credenciais(cred, _ctx_efemero(escola_id))
    linha = vault.obter_linha(db, escola_id, plataforma)  # relê fresco após o await
    if linha is not None:
        vault.marcar_status(db, linha, "valida" if resultado.ok else "invalida",
                            None if resultado.ok else resultado.mensagem)
    db.commit()
    return ResultadoTeste(ok=resultado.ok, mensagem=resultado.mensagem,
                          codigo=resultado.codigo)


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
    registrar(db, "sync.credencial_removida", escola_id=escola_id,
              usuario_id=usuario.id, detalhes={"plataforma": plataforma})
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
                      parametros: dict | None = None) -> list[SincronizacaoExecucao]:
    alvos = ([plataforma] if plataforma
             else connectors.plataformas_automatizaveis())
    execucoes = []
    for plat in alvos:
        _validar_plataforma(plat)
        if vault.obter_credencial(db, escola_id, plat) is None:
            continue  # sem credencial: silenciosamente pula (aparece no status)
        # A janela de datas (coleta por período) só se aplica ao Matific.
        params = parametros if (parametros and plat == "matific") else None
        ex = service.enfileirar(db, escola_id, plat, origem="manual",
                                usuario_id=usuario.id, parametros=params)
        execucoes.append(ex)
    db.commit()
    for ex in execucoes:
        service.disparar_em_thread(ex.id)  # roda já, sem bloquear o request
    return execucoes


_RE_DATA_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@router.post("/agora", response_model=list[ExecucaoOut])
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
        if fim < inicio:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "A data final não pode ser antes da inicial.")
        parametros = {"matific_start_date": inicio, "matific_end_date": fim}
    execucoes = _enfileirar_agora(db, escola_id, usuario, plataforma, parametros)
    if not execucoes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Nenhuma plataforma com credencial configurada.")
    return [ExecucaoOut.model_validate(e) for e in execucoes]


# HTTP por código de erro do conector (o Matific é um upstream → 502 quando ele
# nega/bloqueia; 4xx quando o problema é a configuração; 409 quando ocupado).
_STATUS_ERRO = {
    "sem_credencial": status.HTTP_400_BAD_REQUEST,
    "periodo_invalido": status.HTTP_400_BAD_REQUEST,
    "escola": status.HTTP_404_NOT_FOUND,
    "sem_conector": status.HTTP_503_SERVICE_UNAVAILABLE,
    "navegador_indisponivel": status.HTTP_503_SERVICE_UNAVAILABLE,
    "ocupado": status.HTTP_409_CONFLICT,
    "timeout": status.HTTP_504_GATEWAY_TIMEOUT,
}


@router.get("/matific/placar-ao-vivo")
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
    vê), mas o servidor filtra o resultado para SÓ os alunos das turmas dele."""
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
        itens = [i for i in resultado.get("itens", []) if i.get("aluno_id") in ids]
        resultado = {**resultado, "itens": itens}
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
    inventário (com avisos se a API mudou). Substitui crawler/F12; nada é público."""
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
@router_global.get("/dashboard", response_model=DashboardOut)
def dashboard(usuario: Usuario = Depends(get_usuario_atual),
              db: Session = Depends(get_db)):
    if not usuario.is_global:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Painel global exige usuário com acesso total.")
    escolas_total = db.scalar(select(func.count(Escola.id))) or 0
    escolas_config = db.scalar(select(func.count(func.distinct(
        PlataformaCredencial.escola_id)))) or 0
    em_andamento = db.scalar(select(func.count(SincronizacaoExecucao.id)).where(
        SincronizacaoExecucao.status == "executando")) or 0
    fila = db.scalar(select(func.count(SincronizacaoExecucao.id)).where(
        SincronizacaoExecucao.status == "fila")) or 0
    com_erro = db.scalar(select(func.count(func.distinct(
        SincronizacaoAlerta.escola_id))).where(
        SincronizacaoAlerta.resolvido.is_(False),
        SincronizacaoAlerta.severidade == "critico")) or 0
    sincronizadas = db.scalar(select(func.count(func.distinct(
        SincronizacaoExecucao.escola_id))).where(
        SincronizacaoExecucao.status == "concluida")) or 0
    ultima = db.scalar(select(func.max(SincronizacaoExecucao.finalizada_em)).where(
        SincronizacaoExecucao.status == "concluida"))
    tempo_medio = db.scalar(select(func.avg(SincronizacaoExecucao.duracao_ms)).where(
        SincronizacaoExecucao.status == "concluida", SincronizacaoExecucao.duracao_ms > 0))
    dur_ultima = db.scalar(
        select(SincronizacaoExecucao.duracao_ms)
        .where(SincronizacaoExecucao.status == "concluida")
        .order_by(SincronizacaoExecucao.finalizada_em.desc()).limit(1))
    alertas_abertos = db.scalar(select(func.count(SincronizacaoAlerta.id)).where(
        SincronizacaoAlerta.resolvido.is_(False))) or 0
    return DashboardOut(
        escolas_total=escolas_total, escolas_configuradas=escolas_config,
        escolas_sincronizadas=sincronizadas, escolas_com_erro=com_erro,
        em_andamento=em_andamento, fila=fila,
        workers_ativos=(1 if scheduler.ativo() else 0),
        scheduler_ligado=scheduler.ativo(),
        ultima_sincronizacao=ultima,
        duracao_ultima_ms=int(dur_ultima) if dur_ultima else None,
        tempo_medio_ms=int(tempo_medio) if tempo_medio else None,
        alertas_abertos=alertas_abertos)
