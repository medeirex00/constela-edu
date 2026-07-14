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
import threading
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.database import engine
from app.core.security import cifrar_segredo, decifrar_segredo
from app.models.academico import Aluno, Matricula
from app.models.configuracao import Configuracao
from app.models.escola import Escola
from app.services import periodos
from app.sync import connectors, vault
from app.sync.interfaces import Contexto, ErroConector

_NS_SESSAO = "matific_sessao"          # namespace KV da sessão reaproveitável
_CHAVE_SESSAO = "matific"
_TTL_SESSAO_S = 6 * 3600               # sessão só é reusada se salva há < 6 h
_TIMEOUT_S = 150                       # teto DURO por consulta (login + fetch)
_LOCK_NS = 0x4D41                      # 'MA' — namespace do advisory lock do Postgres

_OCUPADO = ("Já existe uma consulta ao Matific em andamento para esta escola. "
            "Aguarde alguns segundos e tente de novo.")

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
        return (f"start_date={di:%Y-%m-%d}&end_date={df:%Y-%m-%d}",
                periodos._rotulo_intervalo(di, df), di, df)

    # Presets NATIVOS do site (casam byte-a-byte com o que o Matific manda).
    if p == "semana":
        i, f, _ = periodos.resolver("semana", hoje, ano_letivo)
        return "duration=week", "Esta semana", i.date(), f.date()
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
    return (f"start_date={di:%Y-%m-%d}&end_date={df:%Y-%m-%d}", rotulo, di, df)


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
    houver, expirou ou não decifra (SECRET_KEY trocada)."""
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


# --- Casamento best-effort com o aluno do Constela (link p/ a ficha) ---------

def _norm(nome: str) -> str:
    base = unicodedata.normalize("NFKD", nome or "")
    base = "".join(c for c in base if not unicodedata.combining(c))
    return " ".join(base.casefold().split())


def _mapa_nome_para_aluno(db: Session, escola_id: int, ano_letivo: int) -> dict[str, int]:
    """{nome_normalizado: aluno_id} dos alunos ATIVOS e matriculados no ano —
    para linkar cada linha do Placar à ficha. Nomes duplicados viram None (não
    dá para desambiguar) e a linha fica sem link, mas AINDA aparece no ranking."""
    linhas = db.execute(
        select(Aluno.id, Aluno.nome)
        .join(Matricula, Matricula.aluno_id == Aluno.id)
        .where(Matricula.escola_id == escola_id,
               Matricula.ano_letivo == ano_letivo,
               Aluno.status == "ativo")
    ).all()
    mapa: dict[str, int | None] = {}
    for aluno_id, nome in linhas:
        chave = _norm(nome)
        if not chave:
            continue
        mapa[chave] = None if chave in mapa else aluno_id  # ambíguo → sem link
    return {k: v for k, v in mapa.items() if v is not None}


def _montar_ranking(alunos: list[dict], mapa_aluno: dict[str, int]) -> list[dict]:
    """Ordena como o Placar do Matific (estrelas desc) e monta a linha do
    ranking. ``pontuacao_media = estrelas / atividades`` (definição do Matific)."""
    ordenados = sorted(
        alunos,
        key=lambda a: (-int(a.get("estrelas", 0)), -int(a.get("atividades", 0)),
                       _norm(a.get("nome", ""))))
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
            "aluno_id": mapa_aluno.get(_norm(a.get("nome", ""))),
        })
    return itens


# --- Consulta ao vivo (entrada única, síncrona) ------------------------------

def placar_matific(db: Session, escola_id: int, *, periodo: str | None,
                   inicio: str | None, fim: str | None,
                   agora: datetime | None = None) -> dict:
    """Consulta o Placar do Matific AO VIVO para o período e devolve o ranking
    pronto para a tela. Levanta ``ErroConector`` (o router traduz em HTTP)."""
    agora = agora or datetime.utcnow()          # UTC — TTL da sessão e atualizado_em
    # A data do FILTRO é a de HOJE no Brasil (o Matific interpreta o intervalo no
    # fuso da escola). O Brasil não tem horário de verão desde 2019 → UTC-3 fixo.
    # Sem isto, entre 21h e 00h (BRT) o "Hoje/mês/bimestre" pediria o dia seguinte
    # (UTC) e o Placar viria vazio.
    hoje_br = (agora - timedelta(hours=3)).date()
    escola = db.get(Escola, escola_id)
    if escola is None:
        raise ErroConector("Escola não encontrada.", codigo="escola",
                           recuperavel=False)
    ano_letivo = escola.ano_letivo_ativo

    filtro, rotulo, _di, _df = mapa_filtro(periodo, inicio, fim, ano_letivo, hoje_br)

    cred = vault.obter_credencial(db, escola_id, "matific")
    if cred is None:
        raise ErroConector(
            "As credenciais do Matific não estão configuradas. Configure em "
            "Sincronização automática → Matific.", codigo="sem_credencial",
            recuperavel=False)

    conector = connectors.obter("matific")
    if conector is None or not hasattr(conector, "coletar_placar_ao_vivo"):
        raise ErroConector("Conector do Matific indisponível.",
                           codigo="sem_conector", recuperavel=False)

    with _lock_consulta(escola_id):
        estado = _carregar_sessao(db, escola_id, agora)
        # Solta a conexão do banco ANTES do login do Playwright (~1 min): nada de
        # transação ociosa segurando o pool durante o I/O de rede longo. As
        # escritas/leituras seguintes reabrem a conexão sob demanda.
        db.rollback()

        eventos: list[str] = []

        def log(etapa: str, nivel: str, mensagem: str) -> None:  # noqa: ARG001
            eventos.append(f"{nivel}: {mensagem}")

        contexto = Contexto(escola_id=escola_id, execucao_id=None, log=log,
                            timeout_s=_TIMEOUT_S)

        async def _consultar():
            # Teto DURO da consulta inteira (login + fetch): uma coleta travada
            # não segura o lock da escola para sempre.
            return await asyncio.wait_for(
                conector.coletar_placar_ao_vivo(cred, contexto, filtro=filtro,
                                                storage_state=estado),
                timeout=_TIMEOUT_S)

        try:
            alunos, novo_estado = asyncio.run(_consultar())
        except asyncio.TimeoutError as exc:
            raise ErroConector(
                "A consulta ao Matific demorou demais e foi cancelada. "
                "Tente novamente.", codigo="timeout", recuperavel=True) from exc

        # Persiste a sessão nova (cookies renovados) para a próxima consulta
        # sair rápida. Falha ao salvar não invalida o resultado já obtido.
        try:
            _salvar_sessao(db, escola_id, novo_estado, agora)
        except Exception:  # noqa: BLE001
            db.rollback()

        mapa_aluno = _mapa_nome_para_aluno(db, escola_id, ano_letivo)
        itens = _montar_ranking(alunos, mapa_aluno)
        return {
            "periodo": rotulo,
            "filtro": filtro,
            "atualizado_em": agora.isoformat() + "Z",
            "total": len(itens),
            "com_link": sum(1 for i in itens if i["aluno_id"]),
            "itens": itens,
        }
