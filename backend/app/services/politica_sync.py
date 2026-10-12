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

CONSOLIDAÇÃO DAS FICHAS-SOMBRA (``consolidar_sombras``). A ficha que a
sincronização criou ao lado da ficha OFICIAL da mesma criança (nome truncado
pelo relatório, mesma turma, fora da Lista Piloto) divide os dados dela em
dois. A escola declara quem a consolida:

    manual       ninguém além de uma pessoa (Alunos › Fundir duplicatas) — atual
    automatico   ao fim de cada sincronização, as sombras cuja evidência basta
                 são fundidas na oficial (``services/consolidacao_sombras``);
                 qualquer dúvida segue para a fila, como hoje

DEFAULT = ``manual``: escola que não configurou não vê fusão nenhuma acontecer
sozinha. A chave é ADITIVA no mesmo registro de configuração (sem migração), e
política gravada antes dela continua valendo como estava.
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

MANUAL = "manual"
AUTOMATICO = "automatico"
MODOS_CONSOLIDACAO = (MANUAL, AUTOMATICO)

# Comportamento histórico: sem política configurada, a sincronização cria e
# nenhuma ficha é fundida sem uma pessoa.
PADRAO = {"criar_aluno": PERMITIR, "consolidar_sombras": MANUAL}


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
        modo = str(guardado.get("consolidar_sombras") or "").strip().lower()
        if modo in MODOS_CONSOLIDACAO:
            valores["consolidar_sombras"] = modo
    return valores


def pode_criar_aluno(db: Session, escola_id: int) -> bool:
    """A sincronização desta escola pode criar ficha de aluno?

    É a única pergunta que o orquestrador faz. Valor desconhecido ou corrompido
    cai no PADRÃO (``permitir``) de propósito: uma configuração ilegível não
    pode, sozinha, mudar o comportamento de uma escola que ninguém configurou.
    """
    return obter(db, escola_id)["criar_aluno"] == PERMITIR


def consolidar_sombras_automatico(db: Session, escola_id: int) -> bool:
    """A sincronização desta escola consolida sozinha as fichas-sombra?

    Só ``automatico`` responde sim. Valor desconhecido ou corrompido cai no
    PADRÃO (``manual``): fundir ficha de criança sem ninguém pedir exige uma
    declaração legível, nunca um acidente de configuração."""
    return obter(db, escola_id)["consolidar_sombras"] == AUTOMATICO


def definir(db: Session, escola_id: int, criar_aluno: str | None = None, *,
            consolidar_sombras: str | None = None) -> dict:
    """Grava a política — só as chaves informadas; a outra fica como estava.
    NÃO commita — quem chama confirma (padrão do projeto)."""
    if criar_aluno is None and consolidar_sombras is None:
        raise ValueError("Nada a alterar: informe “criar_aluno” e/ou "
                         "“consolidar_sombras”.")
    valores = obter(db, escola_id)
    if criar_aluno is not None:
        modo = str(criar_aluno or "").strip().lower()
        if modo not in MODOS:
            raise ValueError(
                "Modo inválido para “criar_aluno”: use “%s” ou “%s”."
                % (PERMITIR, BLOQUEAR))
        valores["criar_aluno"] = modo
    if consolidar_sombras is not None:
        modo = str(consolidar_sombras or "").strip().lower()
        if modo not in MODOS_CONSOLIDACAO:
            raise ValueError(
                "Modo inválido para “consolidar_sombras”: use “%s” ou “%s”."
                % (MANUAL, AUTOMATICO))
        valores["consolidar_sombras"] = modo
    linha = _linha(db, escola_id)
    if linha is None:
        db.add(Configuracao(escola_id=escola_id, namespace=NAMESPACE,
                            chave=CHAVE, valor=valores))
    else:
        linha.valor = valores
    db.flush()
    return valores
