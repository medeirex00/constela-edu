"""MÓDULOS CONTRATADOS por rede (modelo SaaS).

Cada rede municipal assina os módulos que usa. Hoje: Leitura (Elefante Letrado)
e Matemática (Matific). O que a rede NÃO contratou não existe para ela — nem na
interface, nem na API, nem nas médias/rankings.

Duas regras que sustentam tudo:

1. **Ausência de configuração = LIGADO.** A tabela ``modulos_rede`` é esparsa;
   só existe linha quando alguém mexeu. Assim a introdução do recurso não muda
   nenhuma rede já cadastrada (nada de backfill, deploy sem efeito colateral) e
   desligar é sempre explícito.
2. **Escola SEM rede = tudo ligado.** ``Escola.rede_id`` é nulo por padrão (o
   cadastro de escola nem aceita rede), então escola avulsa é o estado comum —
   ela ainda não é um cliente do modelo SaaS e segue com o sistema inteiro.

NÃO confundir com "sem dados": módulo contratado que ainda não recebeu
importação continua contratado, e a tela mostra estado vazio. São coisas
diferentes e a interface as trata de formas diferentes.

Acrescentar um módulo no futuro (Avaliações, Quest, ...) é uma entrada em
``CATALOGO`` — sem migração, sem tocar no motor.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Escola, ModuloRede

_log = logging.getLogger(__name__)

# Catálogo de módulos. `plataformas` casa com o vocabulário já usado no resto do
# sistema (snapshots, conectores de sync, catálogo de indicadores), evitando um
# segundo dicionário para dizer a mesma coisa.
CATALOGO: dict[str, dict] = {
    "leitura": {
        "nome": "Leitura",
        "produto": "Elefante Letrado",
        "icone": "📚",
        "plataformas": ["elefante"],
        "descricao": "Leitura: livros, tempo de leitura, questões e dificuldade.",
    },
    "matematica": {
        "nome": "Matemática",
        "produto": "Matific",
        "icone": "🔢",
        "plataformas": ["matific"],
        "descricao": "Matemática: atividades, estrelas e pontuação média.",
    },
}

# Plataforma (nome técnico do dado) → módulo do catálogo. Usado pelos guards das
# rotas por plataforma e pela filtragem de agregações.
PLATAFORMA_MODULO: dict[str, str] = {
    plataforma: chave
    for chave, meta in CATALOGO.items()
    for plataforma in meta["plataformas"]
}

TODOS = tuple(CATALOGO)


def modulos_da_rede(db: Session, rede_id: int | None) -> set[str]:
    """Módulos ATIVOS de uma rede. ``rede_id`` nulo (escola avulsa) → todos.

    Lê a tabela esparsa e aplica a regra de ouro: só sai da lista o módulo com
    linha explícita ``ativo=False``. Módulo fora do catálogo é ignorado (um
    registro antigo de módulo removido não vira erro)."""
    if rede_id is None:
        return set(TODOS)
    desligados = {
        m for (m,) in db.execute(
            select(ModuloRede.modulo).where(ModuloRede.rede_id == rede_id,
                                            ModuloRede.ativo.is_(False))
        ).all()
    }
    return {chave for chave in TODOS if chave not in desligados}


def modulos_da_escola(db: Session, escola: Escola | None) -> set[str]:
    """Módulos ativos para uma ESCOLA — herdados da rede dela. Escola sem rede
    (ou inexistente) fica com tudo ligado (ver regra 2 no topo)."""
    if escola is None:
        return set(TODOS)
    return modulos_da_rede(db, escola.rede_id)


def modulos_do_usuario(db: Session, usuario) -> set[str]:
    """Módulos que valem para o usuário logado — o que a interface dele deve ver.

    Admin GLOBAL não é de uma rede só: enxerga o catálogo inteiro (ele administra
    todas as redes; o recorte por rede acontece ao abrir cada rede). Secretaria
    usa a própria rede. Usuário de escola herda a rede da escola dele."""
    if getattr(usuario, "is_global", False):
        return set(TODOS)
    if getattr(usuario, "rede_id", None) is not None:
        return modulos_da_rede(db, usuario.rede_id)
    escola_id = getattr(usuario, "escola_id", None)
    if escola_id is None:
        return set(TODOS)
    return modulos_da_escola(db, db.get(Escola, escola_id))


def definir(db: Session, rede_id: int, modulo: str, ativo: bool) -> ModuloRede:
    """Liga/desliga um módulo da rede (upsert por (rede, módulo)).

    O INSERT vai dentro de um SAVEPOINT porque SELECT-depois-INSERT é uma corrida
    clássica: dois admins mexendo no MESMO módulo pela primeira vez enxergam
    "não existe" e os dois tentam inserir — o índice único ``uq_modulo_rede``
    barra o segundo. Sem o savepoint essa colisão aborta a transação inteira e o
    perdedor leva um 500 sem ter mudado nada. Com ele, desfazemos só o INSERT
    perdido, relemos a linha que o vencedor acabou de criar e aplicamos o UPDATE
    — que é exatamente o que o pedido queria. A partir da segunda vez a linha já
    existe e nem entramos aqui."""
    if modulo not in CATALOGO:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Módulo desconhecido: {modulo}.")
    linha = db.execute(
        select(ModuloRede).where(ModuloRede.rede_id == rede_id,
                                 ModuloRede.modulo == modulo)
    ).scalar_one_or_none()
    if linha is not None:
        linha.ativo = ativo
        db.flush()
        return linha
    try:
        with db.begin_nested():
            linha = ModuloRede(rede_id=rede_id, modulo=modulo, ativo=ativo)
            db.add(linha)
            db.flush()
        return linha
    except IntegrityError:
        # Alguém inseriu entre o nosso SELECT e o nosso INSERT. O savepoint já
        # foi desfeito; a transação segue viva.
        linha = db.execute(
            select(ModuloRede).where(ModuloRede.rede_id == rede_id,
                                     ModuloRede.modulo == modulo)
        ).scalar_one()
        linha.ativo = ativo
        db.flush()
        return linha


def resultado_do_contrato(db: Session, rede_id: int,
                          alteracoes: dict[str, bool]) -> set[str]:
    """Como ficaria o contrato da rede SE ``alteracoes`` fosse aplicado.

    Simulação pura (não grava nada), para a rota poder recusar um pedido antes
    de mexer no banco. Chave ausente do pedido = mantém o que já está."""
    atuais = modulos_da_rede(db, rede_id)
    return {
        chave for chave in TODOS
        if (bool(alteracoes[chave]) if chave in alteracoes else chave in atuais)
    }


def escolas_da_rede(db: Session, rede_id: int) -> list[tuple[int, str]]:
    """``[(escola_id, nome), ...]`` da rede, em ordem estável (id)."""
    return [
        (eid, nome) for eid, nome in db.execute(
            select(Escola.id, Escola.nome)
            .where(Escola.rede_id == rede_id).order_by(Escola.id)
        ).all()
    ]


def recalcular_rede(db: Session, rede_id: int) -> dict:
    """Recalcula as notas de TODAS as escolas da rede com o contrato ATUAL.

    Por que existe: ``pesos.geral`` depende dos módulos contratados, então mudar
    o contrato muda a ``nota_geral`` gravada de cada aluno. Sem este passo as
    notas em banco ficariam descrevendo um contrato que não existe mais (a rede
    só assina Leitura, mas a nota gravada ainda é ``0,5·leitura + 0,5·0``).

    **Idempotente**: ``recalcular_escola`` é determinístico e sobrescreve as
    linhas de ``notas`` que já existem — rodar duas vezes dá o mesmo resultado
    que rodar uma. Por isso reenviar o mesmo PUT é uma recuperação segura.

    **Isolamento por escola**: cada escola tem seu próprio ``commit`` (dentro de
    ``recalcular_escola``). Se uma falhar, desfazemos apenas a transação dela e
    seguimos para as outras — uma escola com dado corrompido não impede as
    demais de ficarem corretas. A lista de falhas volta no retorno para a
    interface mostrar o que precisa ser refeito.
    """
    from app.services import scoring

    escolas = escolas_da_rede(db, rede_id)
    recalculadas: list[dict] = []
    falhas: list[dict] = []
    for escola_id, nome in escolas:
        try:
            alunos = scoring.recalcular_escola(db, escola_id)
            recalculadas.append({"escola_id": escola_id, "nome": nome, "alunos": alunos})
        except Exception as erro:  # noqa: BLE001 — uma escola ruim não derruba a rede
            db.rollback()
            _log.exception("Falha ao recalcular a escola %s da rede %s", escola_id, rede_id)
            falhas.append({"escola_id": escola_id, "nome": nome, "erro": str(erro)[:300]})
    return {
        "escolas": len(escolas),
        "recalculadas": recalculadas,
        "falhas": falhas,
        "alunos": sum(r["alunos"] for r in recalculadas),
    }


def aplicar_contrato(db: Session, rede_id: int, alteracoes: dict[str, bool],
                     usuario_id: int | None = None) -> dict:
    """Grava o contrato da rede e recalcula as notas — a operação completa.

    Ordem deliberada, e o motivo dela:

    1. **O contrato é gravado de uma vez só** (um único ``commit`` para todos os
       módulos do pedido + a trilha de auditoria). Ou o contrato inteiro muda,
       ou nada muda: nunca fica meio aplicado — Leitura desligada e Matemática
       ainda no ar.
    2. **Depois recalcula.** As notas são DERIVADAS do contrato, não o
       contrário. Se o recálculo cair no meio, o contrato gravado continua
       correto e o que sobra é cache velho em algumas escolas — nunca um
       contrato inventado. A recuperação é reenviar o mesmo PUT (idempotente,
       ver ``recalcular_rede``), e o retorno diz exatamente quais escolas
       faltam.

    O recálculo roda SEMPRE, inclusive quando o pedido não muda nada — é o que
    torna o reenvio uma recuperação de verdade, e é a operação mais barata que o
    Admin Global dispara (ele mexe em contrato raramente).
    """
    from app.services.audit import registrar

    antes = sorted(modulos_da_rede(db, rede_id))
    for modulo, ativo in alteracoes.items():
        definir(db, rede_id, modulo, bool(ativo))
    depois = sorted(modulos_da_rede(db, rede_id))
    registrar(db, "rede.modulos_alterados", usuario_id=usuario_id, entidade="rede",
              entidade_id=rede_id,
              detalhes={"pedido": dict(alteracoes), "de": antes, "para": depois})
    db.commit()  # ponto de não-retorno do CONTRATO — daqui para baixo é cache

    recalculo = recalcular_rede(db, rede_id)
    _log.info("Contrato da rede %s: %s -> %s; %s escola(s), %s aluno(s), %s falha(s)",
              rede_id, antes, depois, recalculo["escolas"], recalculo["alunos"],
              len(recalculo["falhas"]))
    return {"modulos": catalogo_da_rede(db, rede_id), "de": antes, "para": depois,
            "recalculo": recalculo}


def catalogo_da_rede(db: Session, rede_id: int) -> list[dict]:
    """Catálogo COMPLETO com o estado de contratação — o que o Admin Global edita
    (todos os módulos aparecem; `ativo` diz se estão contratados)."""
    ativos = modulos_da_rede(db, rede_id)
    return [{"chave": chave, **meta, "ativo": chave in ativos}
            for chave, meta in CATALOGO.items()]


def exigir(modulos: set[str], modulo: str) -> None:
    """Barra o acesso a um módulo não contratado (403). O 404 seria pior: some
    a informação de que o recurso existe, mas o produto não foi assinado."""
    if modulo not in modulos:
        meta = CATALOGO.get(modulo, {})
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"O módulo {meta.get('nome', modulo)} não faz parte do plano desta rede.")
