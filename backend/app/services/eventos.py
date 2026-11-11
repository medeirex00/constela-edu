"""Ingestão idempotente de EVENTOS granulares por aluno (EventoAluno).

A camada de "espelho evento a evento" e a base da linha do tempo cronológica.
Genérica de propósito: as duas plataformas emitem dicts de evento e esta função
grava sem duplicar (Elefante hoje; Matific quando o login destravar). A
idempotência vem da chave_natural DETERMINÍSTICA — reimportar o mesmo relatório
é no-op, nunca duplica e nunca perde histórico.

A FICHA ESTÁ DENTRO DA CHAVE, de propósito: é a prova de origem que a
restauração histórica (``leituras_restauracao``) confere depois de uma fusão. Por
isso a chave sozinha não reconhece o mesmo evento em fichas diferentes — a fusão
move os eventos SEM regenerar a chave. Quem compara eventos de fichas diferentes
(a ingestão depois de uma fusão, a própria fusão, a limpeza do passivo) usa o
CONTEÚDO (``conteudo_evento``): a chave sem a ficha.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime
from itertools import groupby

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.models import Aluno, EventoAluno, LogAuditoria
from app.services.audit import registrar


def chave_evento(plataforma: str, tipo: str, aluno_id: int, titulo: str,
                 quando: datetime, extra: str = "") -> str:
    """Chave de dedup DETERMINÍSTICA de um evento. Como Matific/Elefante não
    expõem um id estável de evento, sintetizamos a partir do que o identifica:
    plataforma, tipo, aluno, título normalizado e o MINUTO do ocorrido — mais um
    ``extra`` opcional (ex.: nº da tentativa) para casos com repetição no mesmo
    minuto. sha256 em hex (64 chars, cabe na coluna)."""
    base = "|".join([
        plataforma, tipo, str(aluno_id),
        (titulo or "").strip().casefold(),
        quando.strftime("%Y-%m-%dT%H:%M"),
        extra,
    ])
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def conteudo_evento(plataforma: str, tipo: str, titulo: str | None,
                    quando: datetime | None) -> tuple[str, str, str, str] | None:
    """O que identifica o evento SEM a ficha: a ``chave_evento`` menos o aluno
    (plataforma, tipo, título normalizado, minuto). Duas cópias com o mesmo
    conteúdo são a MESMA linha do relatório gravada em fichas diferentes.

    ``None`` sem título ou sem data: aí o conteúdo não identifica nada (duas
    atividades sem nome no mesmo minuto podem ser coisas diferentes) e só vale a
    chave. O ``extra`` da chave não é gravado em coluna; por isso o conteúdo só é
    usado quando a chave prova que o evento foi gerado SEM ``extra``
    (``nasceu_na_ficha``) — a repetição no mesmo minuto continua distinta."""
    normalizado = (titulo or "").strip().casefold()
    if not normalizado or quando is None:
        return None
    return (plataforma, tipo, normalizado, quando.strftime("%Y-%m-%dT%H:%M"))


def nasceu_na_ficha(chave_natural: str, aluno_id: int, plataforma: str, tipo: str,
                    titulo: str | None, quando: datetime) -> bool:
    """A chave é a que ``chave_evento`` gera para ESTA ficha, sem ``extra``: o
    evento nasceu aqui (não veio de uma ficha absorvida) e o conteúdo o
    identifica por inteiro."""
    return chave_natural == chave_evento(plataforma, tipo, aluno_id, titulo or "", quando)


def origem_comprovada(evento, origens) -> int | None:
    """A ficha, entre ``origens``, cuja chave ``evento`` prova ter nascido nela
    sem ``extra`` (``nasceu_na_ficha``); ``None`` quando nenhuma se prova.
    ``evento`` é um ``EventoAluno`` ou uma linha com as mesmas colunas."""
    return next((origem for origem in origens if nasceu_na_ficha(
        evento.chave_natural, origem, evento.plataforma, evento.tipo_evento,
        evento.conteudo_titulo, evento.ocorrido_em)), None)


def primeiras_ocorrencias(eventos) -> set[int]:
    """Ids das cópias que a deduplicação por conteúdo NÃO pode apagar: para cada
    ficha de origem, a PRIMEIRA ocorrência de um livro quando essa mesma origem
    tem outra ocorrência do livro depois.

    ``eventos``: tuplas ``(id, origem, livro_id, plataforma, ocorrido_em)``, com a
    ``origem`` que a chave prova (``origem_comprovada``) ou ``None``. Passe TODOS
    os eventos que vão ficar juntos na ficha, não só os repetidos.

    POR QUÊ. A restauração histórica (``leituras_restauracao``, regra 9) só aceita
    como evidência a primeira ocorrência do livro na ficha de origem, e reconhece
    as ocorrências daquela ficha pela chave. Apagar a primeira deixaria a seguinte
    com cara de primeira, e a restauração aceitaria reescrever a leitura com a
    data errada. A ocorrência única pode sair (não sobra posterior para enganar a
    regra), e as seguintes também (a primeira continua lá). Vale também para a
    ficha que fica: ela vira origem quando for absorvida depois."""
    por_origem: dict[tuple, list[tuple[datetime, int]]] = defaultdict(list)
    for evento_id, origem, livro_id, plataforma, quando in eventos:
        if origem is not None and livro_id is not None and quando is not None:
            por_origem[(origem, livro_id, plataforma)].append((quando, evento_id))
    return {min(ocorrencias)[1] for ocorrencias in por_origem.values()
            if len(ocorrencias) > 1}


def _conteudo_comprovado(ev: dict, aluno_id: int, plataforma: str):
    """Conteúdo de um evento A GRAVAR, só quando a chave dele prova que foi
    gerado sem ``extra`` para esta ficha; senão ``None`` (vale só a chave)."""
    tipo, quando = ev.get("tipo_evento"), ev.get("ocorrido_em")
    if not tipo or not isinstance(quando, datetime):
        return None
    titulo = ev.get("conteudo_titulo")
    if not nasceu_na_ficha(ev["chave_natural"], aluno_id, plataforma, tipo, titulo, quando):
        return None
    return conteudo_evento(plataforma, tipo, titulo, quando)


def ingerir_eventos(db: Session, aluno_id: int, plataforma: str,
                    eventos: list[dict]) -> int:
    """Grava só os eventos NOVOS (idempotente). ``eventos`` são dicts com as
    colunas de EventoAluno, incluindo ``chave_natural``. Descarta os que já
    existem para este aluno+plataforma — pela chave OU pelo conteúdo, porque o
    evento que a fusão trouxe de uma ficha absorvida tem a chave DELA e é a mesma
    linha do relatório — e os repetidos no próprio lote; grava o resto num único
    INSERT executemany. Devolve quantos foram inseridos. Portável SQLite+Postgres
    (não usa on-conflict de dialeto)."""
    if not eventos:
        return 0
    linhas = db.execute(
        select(EventoAluno.chave_natural, EventoAluno.tipo_evento,
               EventoAluno.conteudo_titulo, EventoAluno.ocorrido_em).where(
            EventoAluno.aluno_id == aluno_id,
            EventoAluno.plataforma == plataforma)
    ).all()
    existentes: set[str] = {chave for chave, *_ in linhas}
    conteudos = {conteudo_evento(plataforma, tipo, titulo, quando)
                 for _chave, tipo, titulo, quando in linhas}
    conteudos.discard(None)
    novos: list[dict] = []
    vistos: set[str] = set()
    for ev in eventos:
        chave = ev.get("chave_natural")
        if not chave or chave in existentes or chave in vistos:
            continue
        conteudo = _conteudo_comprovado(ev, aluno_id, plataforma)
        if conteudo is not None and conteudo in conteudos:
            continue   # a mesma linha já está aqui, vinda de uma ficha absorvida
        vistos.add(chave)
        if conteudo is not None:
            conteudos.add(conteudo)
        novos.append(ev)
    if novos:
        db.execute(insert(EventoAluno), novos)
    return len(novos)


def fichas_absorvidas(db: Session, aluno_ids) -> dict[int, set[int]]:
    """Para cada ficha de ``aluno_ids``, as que ela absorveu em fusões — direta ou
    em cadeia —, pelo log ``aluno.fundido`` (``entidade_id`` = a que ficou,
    ``removido.id`` = a absorvida). Junto com a própria ficha, são as origens
    possíveis das chaves dos eventos que estão nela hoje. Lê só as entradas da
    cadeia dessas fichas, não o log inteiro (a fusão chama isto a cada par).

    Id absorvido que hoje é de uma ficha VIVA não entra nem é percorrido: a
    absorvida foi apagada, então o id em uso é reaproveitamento (outra criança) —
    a mesma regra de ``exclusao_aluno.fichas_absorvidas``."""
    resultado: dict[int, set[int]] = {}
    for raiz in dict.fromkeys(aluno_ids):
        vistas: set[int] = set()
        fronteira = {raiz}
        while fronteira:
            novas: set[int] = set()
            for (detalhes,) in db.execute(select(LogAuditoria.detalhes).where(
                    LogAuditoria.acao == "aluno.fundido",
                    LogAuditoria.entidade_id.in_(sorted(fronteira)))):
                removido = (((detalhes if isinstance(detalhes, dict) else {})
                             .get("removido") or {}).get("id"))
                if isinstance(removido, int) and removido != raiz and removido not in vistas:
                    novas.add(removido)
            if novas:
                novas -= set(db.execute(select(Aluno.id).where(
                    Aluno.id.in_(sorted(novas)))).scalars())
            vistas |= novas
            fronteira = novas
        resultado[raiz] = vistas
    return resultado


def _fichas_absorvidas(db: Session, escola_id: int | None) -> dict[int, set[int]]:
    """Para cada ficha, as que ela absorveu em fusões (direta ou em cadeia), pelo
    log ``aluno.fundido`` (``mantido.id`` ← ``removido.id``). São as origens
    possíveis das chaves dos eventos que estão nela hoje."""
    consulta = select(LogAuditoria.detalhes).where(LogAuditoria.acao == "aluno.fundido")
    if escola_id is not None:
        consulta = consulta.where(LogAuditoria.escola_id == escola_id)
    filhos: dict[int, set[int]] = defaultdict(set)
    for (detalhes,) in db.execute(consulta):
        mantido = ((detalhes or {}).get("mantido") or {}).get("id")
        removido = ((detalhes or {}).get("removido") or {}).get("id")
        if isinstance(mantido, int) and isinstance(removido, int):
            filhos[mantido].add(removido)
    fechadas: dict[int, set[int]] = {}
    for raiz, diretos in filhos.items():
        vistas: set[int] = set()
        pilha = list(diretos)
        while pilha:
            atual = pilha.pop()
            if atual in vistas or atual == raiz:
                continue
            vistas.add(atual)
            pilha.extend(filhos.get(atual, ()))
        fechadas[raiz] = vistas
    return fechadas


def deduplicar_eventos_por_conteudo(db: Session, *, escola_id: int | None = None,
                                    aplicar: bool = False) -> dict:
    """Limpa o PASSIVO de eventos duplicados que as fusões anteriores ao conserto
    deixaram (a mesma linha do relatório duas vezes na mesma ficha, cada cópia
    com a chave de uma ficha diferente). NÃO commita: quem chama decide.

    Só entra na comparação o evento cuja chave é provada contra uma origem
    conhecida — a própria ficha ou uma que ela absorveu (log ``aluno.fundido``) —
    e sem ``extra``; o que não se prova fica intocado. Em cada grupo de cópias
    fica UMA: a que veio de uma ficha absorvida (é a evidência de origem da
    restauração histórica), a de menor id entre elas; a cópia nativa é a
    redundante. Mas nunca sai a primeira ocorrência de um livro para a ficha de
    origem dela quando essa ficha tem ocorrência posterior do mesmo livro
    (``primeiras_ocorrencias``): essa fica, e saem as outras; se o grupo tem mais
    de uma assim, ficam todas elas. Cada remoção vai para o log
    ``aluno.eventos_duplicados_removidos`` da ficha (só ids, instante, livro e
    chave). Com ``aplicar=False`` só conta.

    Lê em fluxo, uma ficha por vez, para caber na memória numa rede inteira; as
    remoções acontecem depois da leitura."""
    absorvidas = _fichas_absorvidas(db, escola_id)
    consulta = (select(EventoAluno.id, EventoAluno.escola_id, EventoAluno.aluno_id,
                       EventoAluno.plataforma, EventoAluno.tipo_evento,
                       EventoAluno.conteudo_titulo, EventoAluno.ocorrido_em,
                       EventoAluno.chave_natural, EventoAluno.livro_id)
                .order_by(EventoAluno.aluno_id, EventoAluno.id)
                .execution_options(yield_per=2000))
    if escola_id is not None:
        consulta = consulta.where(EventoAluno.escola_id == escola_id)

    remocoes: dict[tuple[int, int], list[dict]] = {}
    for aluno_id, linhas in groupby(db.execute(consulta), key=lambda linha: linha.aluno_id):
        origens = [aluno_id, *sorted(absorvidas.get(aluno_id, ()))]
        da_ficha = [(origem_comprovada(linha, origens), linha) for linha in linhas]
        protegidas = primeiras_ocorrencias(
            (linha.id, origem, linha.livro_id, linha.plataforma, linha.ocorrido_em)
            for origem, linha in da_ficha)
        grupos: dict[tuple, list[tuple[int, object]]] = defaultdict(list)
        escola_da_ficha = None
        for origem, linha in da_ficha:
            escola_da_ficha = linha.escola_id
            conteudo = conteudo_evento(linha.plataforma, linha.tipo_evento,
                                       linha.conteudo_titulo, linha.ocorrido_em)
            if conteudo is not None and origem is not None:
                grupos[conteudo].append((origem, linha))
        saem: list[dict] = []
        for copias in grupos.values():
            if len(copias) < 2:
                continue
            # Fica a cópia de uma ficha absorvida (prova de origem); depois, a mais
            # antiga — salvo as primeiras ocorrências, que ficam todas.
            copias.sort(key=lambda par: (par[0] == aluno_id, par[1].id))
            ficam = [linha for _origem, linha in copias if linha.id in protegidas]
            fica = (ficam or [copias[0][1]])[0]
            for _origem, linha in copias:
                if linha.id == fica.id or linha.id in protegidas:
                    continue
                saem.append({"evento_id": linha.id, "igual_ao_evento_id": fica.id,
                             "livro_id": linha.livro_id,
                             "ocorrido_em": linha.ocorrido_em.isoformat(),
                             "chave_natural": linha.chave_natural})
        if saem:
            remocoes[(escola_da_ficha, aluno_id)] = saem

    total = sum(len(saem) for saem in remocoes.values())
    if aplicar:
        for (escola_da_ficha, aluno_id), saem in remocoes.items():
            db.execute(delete(EventoAluno).where(
                EventoAluno.id.in_([s["evento_id"] for s in saem])))
            registrar(db, "aluno.eventos_duplicados_removidos",
                      escola_id=escola_da_ficha, entidade="aluno", entidade_id=aluno_id,
                      detalhes={"motivo": "mesma linha do relatório gravada duas vezes "
                                          "na ficha por uma fusão anterior",
                                "eventos": saem})
    return {"alunos": len(remocoes), "eventos_duplicados": total}
