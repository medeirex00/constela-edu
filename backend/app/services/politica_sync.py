"""Política de sincronização da escola: quem é a FONTE DE VERDADE da matrícula.

O PROBLEMA QUE ISTO RESOLVE. A sincronização entrega as linhas da plataforma ao
mesmo pipeline do upload manual, e esse pipeline, quando não encontra candidato
seguro, CRIA a ficha da criança. Para uma escola cujas matrículas vêm da Lista
Piloto oficial, isso está errado na raiz: a plataforma não é fonte de matrícula.
Um nome truncado pelo relatório ("ANNA E"), uma criança de outra unidade que
aparece na turma, ou um RA divergente que VETA o candidato certo viram ficha
nova — ativa, sem RA, sem nascimento, já contando no ranking e mexendo na régua
da escola inteira. E não existe desfazer.

A POLÍTICA. Cada escola declara se a sincronização pode ou não criar ficha:

    permitir   a sincronização cria a ficha quando não há candidato (atual)
    bloquear   a sincronização NUNCA cria: a linha vai para a fila de revisão

``bloquear`` não descarta nada. A linha vira pendência de identidade com tudo o
que um gestor precisa para decidir — nome recebido, plataforma, id externo,
turma do relatório, candidatos e motivo —, e o dado só entra quando alguém
apontar a ficha certa (ou criar a ficha deliberadamente, pela própria tela de
revisão). O caminho da Lista Piloto continua criando normalmente: ele É a fonte.

DEFAULT = ``permitir``. Escola sem política configurada se comporta exatamente
como antes desta mudança — a trava é opt-in, por escola, e nunca retroativa.

Isto vale só para o pipeline de SINCRONIZAÇÃO. O upload manual do gestor não
passa por aqui (``ImportacaoConfirm.permitir_criar_aluno`` continua ``True`` por
padrão) e o cadastro pela tela de Alunos nem toca neste caminho.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Configuracao

NAMESPACE = "sincronizacao"
CHAVE = "politica"

PERMITIR = "permitir"
BLOQUEAR = "bloquear"
MODOS = (PERMITIR, BLOQUEAR)

# Comportamento histórico: sem política configurada, a sincronização cria.
PADRAO = {"criar_aluno": PERMITIR}


def _linha(db: Session, escola_id: int) -> Configuracao | None:
    return db.execute(
        select(Configuracao).where(Configuracao.escola_id == escola_id,
                                   Configuracao.namespace == NAMESPACE,
                                   Configuracao.chave == CHAVE)).scalars().first()


def obter(db: Session, escola_id: int) -> dict:
    """A política vigente da escola, já com os defaults preenchidos."""
    linha = _linha(db, escola_id)
    valores = dict(PADRAO)
    guardado = (linha.valor if linha is not None else None) or {}
    if isinstance(guardado, dict):
        modo = str(guardado.get("criar_aluno") or "").strip().lower()
        if modo in MODOS:
            valores["criar_aluno"] = modo
    return valores


def pode_criar_aluno(db: Session, escola_id: int) -> bool:
    """A sincronização desta escola pode criar ficha de aluno?

    É a única pergunta que o orquestrador faz. Valor desconhecido ou corrompido
    cai no PADRÃO (``permitir``) de propósito: uma configuração ilegível não
    pode, sozinha, mudar o comportamento de uma escola que ninguém configurou.
    """
    return obter(db, escola_id)["criar_aluno"] == PERMITIR


def definir(db: Session, escola_id: int, criar_aluno: str) -> dict:
    """Grava a política. NÃO commita — quem chama confirma (padrão do projeto)."""
    modo = str(criar_aluno or "").strip().lower()
    if modo not in MODOS:
        raise ValueError(
            "Modo inválido para “criar_aluno”: use “%s” ou “%s”."
            % (PERMITIR, BLOQUEAR))
    valores = {**obter(db, escola_id), "criar_aluno": modo}
    linha = _linha(db, escola_id)
    if linha is None:
        db.add(Configuracao(escola_id=escola_id, namespace=NAMESPACE,
                            chave=CHAVE, valor=valores))
    else:
        linha.valor = valores
    db.flush()
    return valores
