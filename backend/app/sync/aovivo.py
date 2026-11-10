"""Consulta em TEMPO REAL ao Placar do Matific (premiação por período).

O usuário escolhe um período e o Constela vira um CLIENTE do Matific: consulta a
API interna do Placar com o filtro do período e devolve exatamente os mesmos
alunos/estrelas/atividades que o site mostra — sem PDF, sem importação, sem
depender de snapshots. Substitui a reconstrução por diferença de snapshots (que
só funcionava para o acumulado do ano).

Mecanismo do período (confirmado — MATIFIC_API.md §4/§8, sem suposição):
  * ``duration=week``      → Esta semana   (preset NATIVO do site)
  * ``duration=this-year`` → Ano letivo    (preset NATIVO do site)
  * ``start_date=AAAA-MM-DD&end_date=AAAA-MM-DD`` → qualquer intervalo; devolve o
    que o aluno fez DENTRO do intervalo (não o acumulado). É a base do período
    personalizado e também de Hoje/Este mês/Este bimestre (o Matific não tem
    preset nativo para esses — usamos o mesmo mecanismo do personalizado).

Velocidade: o login do robô é caro, então a sessão (cookies) é guardada CIFRADA
e reaproveitada. 1ª consulta após ociosidade faz login (~1 min); as seguintes
reusam a sessão (poucos segundos). Cada escola é serializada por um lock — dois
cliques simultâneos não disparam dois logins.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.database import engine
from app.core.security import cifrar_segredo, decifrar_segredo
from app.models.academico import Aluno, IdentidadeExterna, Matricula
from app.models.configuracao import Configuracao
from app.models.escola import Escola
from app.services import periodos
from app.sync import connectors, escola_externa, fuso, vault
from app.sync.connectors.navegador import (
    FALHA_CONHECIDA,
    FALHA_NOSSA,
    FALHA_TEMPO,
    classificar_falha_da_coleta,
    erro_conector_de_dentro,
)
from app.sync.interfaces import Contexto, ErroConector

logger = logging.getLogger("constela.sync")

_NS_SESSAO = "matific_sessao"          # namespace KV da sessão reaproveitável
_CHAVE_SESSAO = "matific"
_TTL_SESSAO_S = 6 * 3600               # sessão só é reusada se salva há < 6 h
_TIMEOUT_S = 150                       # teto DURO por consulta (login + fetch)
_LOCK_NS = 0x4D41                      # 'MA' — namespace do advisory lock do Postgres

_OCUPADO = ("Já existe uma consulta ao Matific em andamento para esta escola. "
            "Aguarde alguns segundos e tente de novo.")
_DEMOROU = ("A consulta ao Matific demorou demais e foi cancelada. "
            "Tente novamente.")
_FORA_DO_AR = ("Não foi possível consultar o Matific agora: a conexão com o site do "
               "Matific falhou ou ele não respondeu. Tente de novo em alguns minutos.")


def _erro_da_consulta(exc: BaseException) -> Exception | None:
    """O que levantar no lugar de uma falha no meio da consulta ao vivo, pelo critério
    único de ``navegador.classificar_falha_da_coleta`` (o mesmo do diagnóstico do
    Elefante, ``diagnostico_elefante._erro_da_coleta``):

    * REDE (DNS, conexão recusada, TLS, página que não abriu — o ``OSError`` da rede,
      a exceção do Playwright/httpx que não é nenhuma das abaixo) vira um
      ``ErroConector`` que diz que foi o Matific (502), e o tempo esgotado, 504 — não
      um 500 "Erro interno" que põe a culpa no Constela. O detalhe técnico fica no log
      WARNING (o formatador redige o que foi digitado); a resposta não leva nada
      interno;
    * o NOSSO navegador que caiu no meio da consulta (``TargetClosedError``, "Page
      crashed", o driver do Playwright morto) vira 503 ``navegador_indisponivel``,
      sem culpar o Matific: o ``ErroConector`` vem de ``erro_conector_de_dentro``,
      que grava o log ERROR (a falha é do servidor). O que NÃO ABRIU já chega como
      esse ``ErroConector`` (``abrir_playwright``, também com log ERROR);
    * um ``ErroConector`` de dentro de um grupo de exceções passa com a mensagem dele;
    * DEFEITO NOSSO (KeyError, TypeError, AttributeError…) vai para o log ERROR (o
      Sentry o vê) e devolve None: quem chama relança a exceção crua (500). O
      ``asyncio.CancelledError`` que sai de dentro do conector (o ``asyncio.run`` o
      devolve quando ninguém de fora cancelou) também é nosso, mas não pode subir cru
      (é BaseException: escaparia do tratamento de erro da rota) — volta um
      ``RuntimeError`` com ele como causa."""
    tipo = classificar_falha_da_coleta(exc)
    if tipo == FALHA_NOSSA:
        logger.exception("Consulta ao vivo do Matific falhou por um defeito do "
                         "Constela (%s).", type(exc).__name__)
        if isinstance(exc, asyncio.CancelledError):
            return RuntimeError("A consulta ao vivo do Matific foi cancelada por dentro "
                                "do conector, sem tempo esgotado.")
        return None
    if tipo == FALHA_CONHECIDA:
        return erro_conector_de_dentro(exc)
    demorou = tipo == FALHA_TEMPO
    logger.warning("Consulta ao vivo do Matific falhou (%s): %s",
                   "tempo esgotado" if demorou else "rede",
                   type(exc).__name__, exc_info=True)
    if demorou:
        return ErroConector(_DEMOROU, codigo="timeout", recuperavel=True)
    return ErroConector(_FORA_DO_AR, codigo="indisponivel_externo", recuperavel=True)


# Serializa a consulta ao vivo por escola. DENTRO do worker: threading.Lock por
# processo (cobre o duplo-clique). ENTRE workers (uvicorn sobe --workers 2): esse
# lock não basta, então em Postgres também pegamos um advisory lock (ver
# _lock_consulta). Cada worker tem sua própria cópia deste dicionário.
_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_da_escola(escola_id: int) -> threading.Lock:
    with _locks_guard:
        lk = _locks.get(escola_id)
        if lk is None:
            lk = _locks[escola_id] = threading.Lock()
        return lk


@contextmanager
def _lock_consulta(escola_id: int):
    """Garante UMA consulta ao vivo por escola de cada vez. In-process (duplo-
    clique no mesmo worker) + advisory lock do Postgres (entre workers). Em
    SQLite (testes) só o in-process — não há multi-worker. Libera tudo no fim,
    inclusive em erro."""
    lk = _lock_da_escola(escola_id)
    if not lk.acquire(timeout=2):
        raise ErroConector(_OCUPADO, codigo="ocupado", recuperavel=True)
    conn = None
    try:
        if engine.dialect.name == "postgresql":
            # Conexão DEDICADA (não a do request, que é liberada antes do login):
            # o advisory lock vive nela e é solto no finally.
            conn = engine.connect()
            travou = conn.execute(
                text("SELECT pg_try_advisory_lock(:ns, :k)"),
                {"ns": _LOCK_NS, "k": int(escola_id)}).scalar()
            if not travou:
                raise ErroConector(_OCUPADO, codigo="ocupado", recuperavel=True)
        yield
    finally:
        if conn is not None:
            try:
                conn.execute(text("SELECT pg_advisory_unlock(:ns, :k)"),
                             {"ns": _LOCK_NS, "k": int(escola_id)})
                conn.commit()
            except Exception:  # noqa: BLE001 — unlock best-effort (a conexão fechará)
                pass
            conn.close()
        lk.release()


# --- Período → filtro da API do Matific --------------------------------------

def mapa_filtro(periodo: str | None, inicio: str | None, fim: str | None,
                ano_letivo: int, hoje: date) -> tuple[str, str, date | None, date | None]:
    """(filtro_querystring, rótulo, dt_i, dt_f). Usa o preset NATIVO do Matific
    quando existe (semana/ano) e datas explícitas para o resto — o mesmo
    mecanismo do período personalizado, confirmado na API."""
    p = (periodo or "").strip().lower()

    # Personalizado (ou datas soltas sem preset): intervalo exato pedido.
    if p == "personalizado" or (not p and (inicio or fim)):
        try:
            di = periodos._parse_data(inicio)
            df = periodos._parse_data(fim)
        except ValueError as exc:
            raise ErroConector("Datas inválidas — use o formato AAAA-MM-DD.",
                               codigo="periodo_invalido", recuperavel=False) from exc
        if not di or not df:
            raise ErroConector("Informe as duas datas (início e fim) do período.",
                               codigo="periodo_invalido", recuperavel=False)
        if df < di:
            raise ErroConector("A data final não pode ser anterior à inicial.",
                               codigo="periodo_invalido", recuperavel=False)
        return (f"start_date={di:%Y-%m-%d}&end_date={_end_date(df):%Y-%m-%d}",
                periodos._rotulo_intervalo(di, df), di, df)

    # Presets NATIVOS do site (casam byte-a-byte com o que o Matific manda).
    if p == "semana":
        i, f, _ = periodos.resolver("semana", hoje, ano_letivo)
        return "duration=week", "Esta semana", i.date(), f.date()
    if p in ("semana_anterior", "semana_passada"):
        return "duration=last-week", "Semana passada", None, None
    if p in ("ano_letivo", "ano", "tudo"):
        return "duration=this-year", f"Ano letivo {ano_letivo}", None, None

    # Hoje / Este mês / Este bimestre: datas calculadas (o Matific não tem preset
    # próprio) — mesmo mecanismo confirmado do personalizado.
    i, f, rotulo = periodos.resolver(p or "mes", hoje, ano_letivo)
    if i is None or f is None:
        raise ErroConector(f"Período '{periodo}' não é suportado.",
                           codigo="periodo_invalido", recuperavel=False)
    # Nunca pede data FUTURA ao Matific: "este mês/bimestre" vai do início até
    # HOJE (o fim do mês/bimestre ainda não chegou). Evita rejeição e casa com o
    # significado "premiar pelo que já foi feito no período".
    di, df = i.date(), min(f.date(), hoje)
    return (f"start_date={di:%Y-%m-%d}&end_date={_end_date(df):%Y-%m-%d}", rotulo, di, df)


def _end_date(fim: date) -> date:
    """``end_date`` do Placar para um período que termina em ``fim`` (inclusive),
    pela MESMA semântica da sincronização (MATIFIC_END_DATE): com 'exclusiva', o
    dia seguinte; com 'inclusiva' ou 'desconhecida', o próprio dia (o de sempre)."""
    from app.sync.connectors.matific import end_date_do_filtro
    return end_date_do_filtro(fim)


# --- Sessão reaproveitável (cifrada em repouso) ------------------------------

def _linha_sessao(db: Session, escola_id: int) -> Configuracao | None:
    return db.execute(
        select(Configuracao).where(
            Configuracao.escola_id == escola_id,
            Configuracao.namespace == _NS_SESSAO,
            Configuracao.chave == _CHAVE_SESSAO)
    ).scalar_one_or_none()


def _carregar_sessao(db: Session, escola_id: int, agora: datetime) -> dict | None:
    """storage_state cifrado da última consulta, se salvo há < TTL. None se não
    houver, expirou ou não decifra (DATA_ENCRYPTION_KEY ou SECRET_KEY trocada sem
    recifrar)."""
    row = _linha_sessao(db, escola_id)
    if row is None or not isinstance(row.valor, dict):
        return None
    salvo = row.valor.get("salvo_em")
    try:
        quando = datetime.fromisoformat(salvo) if salvo else None
    except (TypeError, ValueError):
        quando = None
    if quando is None or (agora - quando).total_seconds() > _TTL_SESSAO_S:
        return None
    texto = decifrar_segredo(str(row.valor.get("cifrado") or ""))
    if not texto:
        return None
    try:
        estado = json.loads(texto)
        return estado if isinstance(estado, dict) else None
    except (ValueError, TypeError):
        return None


def _salvar_sessao(db: Session, escola_id: int, estado: dict | None,
                   agora: datetime) -> None:
    if not estado:
        return
    valor = {"cifrado": cifrar_segredo(json.dumps(estado, ensure_ascii=False)),
             "salvo_em": agora.isoformat()}
    row = _linha_sessao(db, escola_id)
    if row is None:
        db.add(Configuracao(escola_id=escola_id, namespace=_NS_SESSAO,
                            chave=_CHAVE_SESSAO, valor=valor))
    else:
        row.valor = valor
    db.commit()


def limpar_sessao(db: Session, escola_id: int) -> None:
    """Esquece a sessão salva (ex.: ao trocar as credenciais do Matific)."""
    row = _linha_sessao(db, escola_id)
    if row is not None:
        db.delete(row)
        db.commit()


# --- Cache curto de RESULTADO (dedupe de consultas idênticas) ----------------
# Vários usuários pedindo o MESMO período em segundos → uma única ida ao Matific.
# Por processo (cada worker tem o seu): reduz carga sem precisar de Redis. TTL
# curto porque o dado é "ao vivo". A tecla é (escola_id, filtro).
_CACHE_TTL_S = 60
_cache: dict[tuple[int, str], tuple[datetime, dict]] = {}
_cache_guard = threading.Lock()


def _cache_get(escola_id: int, filtro: str, agora: datetime) -> dict | None:
    with _cache_guard:
        item = _cache.get((escola_id, filtro))
    if item is None:
        return None
    quando, valor = item
    if (agora - quando).total_seconds() > _CACHE_TTL_S:
        return None
    return valor


def _cache_put(escola_id: int, filtro: str, agora: datetime, valor: dict) -> None:
    with _cache_guard:
        _cache[(escola_id, filtro)] = (agora, valor)
        # Poda preguiçosa: descarta entradas vencidas para não crescer sem fim.
        if len(_cache) > 512:
            vencidos = [k for k, (q, _) in _cache.items()
                        if (agora - q).total_seconds() > _CACHE_TTL_S]
            for k in vencidos:
                _cache.pop(k, None)


def invalidar_cache(escola_id: int) -> None:
    """Descarta o cache de resultado desta escola — chamado ao trocar/remover a
    credencial, para NUNCA servir o ranking da conta antiga (PII de outra conta)."""
    with _cache_guard:
        for k in [k for k in _cache if k[0] == escola_id]:
            _cache.pop(k, None)


def _coletar_http_first(conector, cred, contexto, estado: dict | None,
                        filtro: str) -> tuple[list[dict], dict | None]:
    """Coleta o Placar priorizando a API por HTTP; o navegador entra SÓ para
    autenticar (renovar cookies) e o fetch-no-navegador é o ÚLTIMO recurso.
    Devolve (alunos, novo_storage_state_ou_None). Teto DURO por etapa lenta.

    Com VÍNCULO da escola externa (``contexto.escola_externa``), a escola da conta
    é conferida em todos os caminhos: escola diferente levanta
    ``escola_externa_trocada`` e nenhum nome de outra escola chega à tela."""
    esperada = str((getattr(contexto, "escola_externa", None) or {}).get("id") or "")
    recusadas = frozenset(getattr(contexto, "externas_de_outras_escolas", None) or ())
    extra_http = {"escola_esperada": esperada} if esperada else {}
    if recusadas:
        extra_http["escolas_recusadas"] = recusadas
    # 1) HTTP direto com a sessão salva (sem navegador algum).
    if estado:
        try:
            return conector.coletar_via_http(estado, filtro, **extra_http), None
        except ErroConector as exc:
            if exc.codigo not in ("sessao_invalida", "http_indisponivel"):
                raise  # erro real da API (não é sessão velha/rede) → sobe

    # 2) Navegador SÓ para AUTENTICAR (login/renova cookies) e refaz por HTTP.
    novo = asyncio.run(asyncio.wait_for(
        conector.autenticar(cred, contexto, storage_state=estado),
        timeout=_TIMEOUT_S))
    if novo and novo.get("cookies"):   # só tenta HTTP se de fato temos os cookies
        try:
            return conector.coletar_via_http(novo, filtro, **extra_http), novo
        except ErroConector as exc:
            if exc.codigo not in ("sessao_invalida", "http_indisponivel"):
                raise

    # 3) Último recurso: fetch DENTRO do navegador (same-origin), caso o HTTP
    # server-side seja recusado apesar do cookie fresco.
    contexto.log("download", "warn",
                 "[Matific] HTTP recusado após login — usando fetch no navegador.")
    alunos, novo2 = asyncio.run(asyncio.wait_for(
        conector.coletar_placar_ao_vivo(cred, contexto, filtro=filtro,
                                        storage_state=novo),
        timeout=_TIMEOUT_S))
    return alunos, (novo2 or novo)


# --- Casamento best-effort com o aluno do Constela (link p/ a ficha) ---------

def _norm(nome: str) -> str:
    # A definição ÚNICA de "mesmo nome" (sem acento/caixa/pontuação) — liga a linha
    # do Placar à ficha.
    from app.services.importacao import chave_nome
    return chave_nome(nome)


def _ordem_nome(nome: str) -> str:
    """Desempate ALFABÉTICO da ordenação do placar (inalterado: não é identidade)."""
    base = unicodedata.normalize("NFKD", nome or "")
    base = "".join(c for c in base if not unicodedata.combining(c))
    return " ".join(base.casefold().split())


@dataclass(frozen=True)
class _FichasDaEscola:
    """Como ligar uma linha do Placar à ficha do Constela (o link para o perfil).

    A ordem é a da sincronização ("a conta da plataforma casa antes do nome"):

    1. pela CONTA (``uuid``): a ``IdentidadeExterna`` EFETIVA desta escola, de um
       aluno ativo e matriculado no ano — também quando o Placar só manda o nome
       abreviado ("ANA B") ou quando há homônimo na escola;
    2. conta CONHECIDA aqui que não leva a uma ficha ativa do ano (aposentada,
       de ficha inativa, sem matrícula no ano) → SEM link. O nome não entra: a
       conta duplicada que a escola aposentou, ou a de um transferido, ganharia
       o link do homônimo. Também é "conhecida" a conta que é a identidade
       EFETIVA de um aluno de OUTRA escola do Constela (a regra única do D10,
       ``identidade_aluno.efetivas_em_outra_escola``): a sincronização manda essa
       linha para a revisão ``identidade_de_outra_escola`` (``decidir``, passo
       0d) e nunca a liga pelo nome — aqui ela fica sem link, em vez de ganhar o
       do homônimo desta escola (o professor dele a veria como do aluno dele, e
       é a tela do "premiar por período"). A conta que TAMBÉM vale aqui segue
       pela regra 1;
    3. só a conta DESCONHECIDA (ou a linha sem ``uuid``) cai no NOME, como
       reserva — nome repetido continua sem link, e a ficha que já tem OUTRA
       conta efetiva nesta plataforma não é ligada pelo nome (a sincronização
       mandaria essa linha para a revisão 'outra_identidade_na_plataforma').

    Sem link a linha AINDA aparece no ranking; só não abre a ficha."""
    por_uuid: dict[str, int] = field(default_factory=dict)
    contas_conhecidas: frozenset[str] = frozenset()
    com_conta_efetiva: frozenset[int] = frozenset()
    por_nome: dict[str, int] = field(default_factory=dict)

    def aluno_da_linha(self, linha: dict) -> int | None:
        uuid = str(linha.get("uuid") or "").strip()
        if uuid:
            if uuid in self.por_uuid:
                return self.por_uuid[uuid]
            if uuid in self.contas_conhecidas:
                return None
        aluno_id = self.por_nome.get(_norm(linha.get("nome", "")))
        if aluno_id is None or aluno_id in self.com_conta_efetiva:
            return None
        return aluno_id


def _fichas_da_escola(db: Session, escola_id: int, ano_letivo: int,
                      uuids=()) -> _FichasDaEscola:
    """As fichas que uma linha do Placar pode abrir: alunos ATIVOS e matriculados
    no ano letivo desta escola, indexados pela conta do Matific vinculada a eles
    (identidade efetiva) e, como reserva, pelo nome normalizado (ver
    ``_FichasDaEscola``). Nome repetido não entra (não dá para desambiguar).

    ``uuids`` são as contas das linhas do Placar: as que já são a identidade
    efetiva de um aluno de OUTRA escola entram em ``contas_conhecidas`` (sem
    link pelo nome, como na sincronização). Uma consulta por placar (em lotes de
    500, ``efetivas_em_outra_escola``)."""
    linhas = db.execute(
        select(Aluno.id, Aluno.nome)
        .join(Matricula, Matricula.aluno_id == Aluno.id)
        .where(Matricula.escola_id == escola_id,
               Matricula.ano_letivo == ano_letivo,
               Aluno.status == "ativo")
    ).all()
    no_ano = {aluno_id for aluno_id, _ in linhas}
    mapa: dict[str, int | None] = {}
    for aluno_id, nome in linhas:
        chave = _norm(nome)
        if not chave:
            continue
        mapa[chave] = None if chave in mapa else aluno_id  # ambíguo → sem link

    por_uuid: dict[str, int] = {}
    conhecidas: set[str] = set()
    com_conta: set[int] = set()
    # Ficha EXCLUÍDA não segura a conta (a mesma regra da sincronização): a conta
    # dela fica livre e a linha cai no nome.
    for id_externo, aluno_id, situacao in db.execute(
        select(IdentidadeExterna.id_externo, IdentidadeExterna.aluno_id,
               IdentidadeExterna.status)
        .join(Aluno, Aluno.id == IdentidadeExterna.aluno_id)
        .where(IdentidadeExterna.escola_id == escola_id,
               IdentidadeExterna.plataforma == "matific",
               Aluno.escola_id == escola_id,
               Aluno.status != "excluido")
    ).all():
        conta = str(id_externo or "").strip()
        if not conta:
            continue
        conhecidas.add(conta)
        if situacao == "aposentada":
            continue
        com_conta.add(aluno_id)
        if aluno_id in no_ano:
            por_uuid[conta] = aluno_id
    contas_do_placar = [c for c in (str(u or "").strip() for u in uuids or ()) if c]
    if contas_do_placar:
        from app.services import identidade_aluno as ida
        conhecidas |= set(ida.efetivas_em_outra_escola(db, escola_id, "matific",
                                                       contas_do_placar))
    return _FichasDaEscola(
        por_uuid=por_uuid, contas_conhecidas=frozenset(conhecidas),
        com_conta_efetiva=frozenset(com_conta),
        por_nome={k: v for k, v in mapa.items() if v is not None})


def _montar_ranking(alunos: list[dict], fichas: _FichasDaEscola) -> list[dict]:
    """Ordena como o Placar do Matific (estrelas desc) e monta a linha do
    ranking. ``pontuacao_media = estrelas / atividades`` (definição do Matific).
    O ``aluno_id`` (link para a ficha) vem de ``fichas`` — conta antes do nome."""
    ordenados = sorted(
        alunos,
        key=lambda a: (-int(a.get("estrelas", 0)), -int(a.get("atividades", 0)),
                       _ordem_nome(a.get("nome", ""))))
    itens: list[dict] = []
    for i, a in enumerate(ordenados, 1):
        estrelas = int(a.get("estrelas", 0))
        atividades = int(a.get("atividades", 0))
        media = round(estrelas / atividades, 2) if atividades else 0.0
        itens.append({
            "posicao": i,
            "nome": a.get("nome", ""),
            "turma": a.get("turma") or None,
            "serie": a.get("serie") or None,
            "estrelas": estrelas,
            "atividades": atividades,
            "pontuacao_media": media,
            "aluno_id": fichas.aluno_da_linha(a),
        })
    return itens


def _recusar_linhas_sem_numeros(alunos: list[dict]) -> None:
    """Linha do Placar sem ``score`` ou ``activities_completed`` (a CHAVE não veio:
    campo renomeado na API) não é "0 estrelas": uma criança de 300 estrelas sairia
    do pódio em silêncio. Vale nos dois caminhos (HTTP e navegador) e antes do
    cache. A sincronização trata o mesmo sinal na importação (``ausentes``)."""
    sem_numeros = [a for a in alunos if a.get("ausentes")]
    if not sem_numeros:
        return
    campos = sorted({c for a in sem_numeros for c in a["ausentes"]})
    raise ErroConector(
        f"O Placar do Matific veio sem {' e '.join(campos)} em {len(sem_numeros)} de "
        f"{len(alunos)} aluno(s) — a API pode ter mudado. A premiação não foi montada "
        "para não mostrar 0 no lugar do número real. Verifique o conector.",
        codigo="parser_incompativel", recuperavel=False)


# --- Consulta ao vivo (entrada única, síncrona) ------------------------------

def placar_matific(db: Session, escola_id: int, *, periodo: str | None,
                   inicio: str | None, fim: str | None, forcar: bool = False,
                   agora: datetime | None = None) -> dict:
    """Consulta o Placar do Matific AO VIVO para o período e devolve o ranking
    pronto para a tela. Prioriza a API por HTTP (navegador só para autenticar) e
    tem cache curto de resultado. ``forcar`` ignora o cache (botão Atualizar).
    Levanta ``ErroConector`` (o router traduz em HTTP)."""
    agora = agora or datetime.utcnow()          # UTC — TTL da sessão e atualizado_em
    # A data do FILTRO é a de HOJE no Brasil (o Matific interpreta o intervalo no
    # fuso da escola) — pela regra única de fuso do módulo (``sync.fuso``). Sem
    # isto, entre 21h e 00h (BRT) o "Hoje/mês/bimestre" pediria o dia seguinte
    # (UTC) e o Placar viria vazio.
    hoje_br = fuso.hoje_local(agora)
    escola = db.get(Escola, escola_id)
    if escola is None:
        raise ErroConector("Escola não encontrada.", codigo="escola",
                           recuperavel=False)
    ano_letivo = escola.ano_letivo_ativo

    filtro, rotulo, _di, _df = mapa_filtro(periodo, inicio, fim, ano_letivo, hoje_br)

    # Cache curto de resultado (dedupe): antes de qualquer trabalho pesado.
    if not forcar:
        hit = _cache_get(escola_id, filtro, agora)
        if hit is not None:
            return {**hit, "cache": True}

    cred = vault.obter_credencial(db, escola_id, "matific")
    if cred is None:
        if vault.obter_linha(db, escola_id, "matific") is not None:
            # A credencial existe, mas a cifra não abre (status 'ilegivel'): "não
            # configurada" seria mentira. Pede o recadastro, como o /sync/agora e o
            # diagnóstico do Elefante, sem detalhe da falha da cifra e sem gravar.
            raise ErroConector(vault.mensagem_credencial_ilegivel(["matific"]),
                               codigo=vault.CODIGO_CREDENCIAL_ILEGIVEL, recuperavel=False)
        raise ErroConector(
            "As credenciais do Matific não estão configuradas. Configure em "
            "Sincronização automática → Matific.", codigo="sem_credencial",
            recuperavel=False)

    conector = connectors.obter("matific")
    if conector is None or not hasattr(conector, "coletar_via_http"):
        raise ErroConector("Conector do Matific indisponível.",
                           codigo="sem_conector", recuperavel=False)

    with _lock_consulta(escola_id):
        # Re-checa o cache: outra requisição pode tê-lo preenchido enquanto
        # esperávamos o lock (evita duas coletas para o mesmo período).
        if not forcar:
            hit = _cache_get(escola_id, filtro, agora)
            if hit is not None:
                return {**hit, "cache": True}

        estado = _carregar_sessao(db, escola_id, agora)
        # VÍNCULO da escola externa: com ele, a consulta recusa a conta de outra
        # escola (sem ele, não aprende nada aqui — a consulta ao vivo só lê).
        vinculo = escola_externa.obter(db, escola_id, "matific")
        de_outras = escola_externa.ids_de_outras_escolas(db, "matific", escola_id)
        # Solta a conexão do banco ANTES do I/O de rede longo: nada de transação
        # ociosa segurando o pool durante o HTTP/login. As leituras/escritas
        # seguintes reabrem a conexão sob demanda.
        db.rollback()

        eventos: list[str] = []

        def log(etapa: str, nivel: str, mensagem: str) -> None:  # noqa: ARG001
            eventos.append(f"{nivel}: {mensagem}")

        contexto = Contexto(escola_id=escola_id, execucao_id=None, log=log,
                            timeout_s=_TIMEOUT_S, escola_externa=vinculo,
                            externas_de_outras_escolas=de_outras)

        try:
            # HTTP-first: API por httpx; navegador só para autenticar (fallback).
            alunos, novo_estado = _coletar_http_first(
                conector, cred, contexto, estado, filtro)
        except ErroConector:
            raise                   # já diz o que houve (CAPTCHA, senha, escola…)
        except asyncio.TimeoutError as exc:
            raise ErroConector(_DEMOROU, codigo="timeout", recuperavel=True) from exc
        except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001 — só a COLETA
            erro = _erro_da_consulta(exc)
            if erro is None:
                raise               # defeito nosso: sobe cru (500), já no log ERROR
            raise erro from exc

        # Persiste a sessão nova (cookies renovados), se o navegador autenticou.
        if novo_estado:
            try:
                _salvar_sessao(db, escola_id, novo_estado, agora)
            except Exception:  # noqa: BLE001
                db.rollback()

        _recusar_linhas_sem_numeros(alunos)
        fichas = _fichas_da_escola(db, escola_id, ano_letivo,
                                   uuids=[a.get("uuid") for a in alunos])
        itens = _montar_ranking(alunos, fichas)
        resultado = {
            "periodo": rotulo,
            "filtro": filtro,
            "atualizado_em": agora.isoformat() + "Z",
            "total": len(itens),
            "com_link": sum(1 for i in itens if i["aluno_id"]),
            "itens": itens,
            "cache": False,
        }
        _cache_put(escola_id, filtro, agora, resultado)
        return resultado
