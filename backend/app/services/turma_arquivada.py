"""Decisão D17 (T24) pelo lado de quem ENTRA: turma arquivada não recebe aluno ativo.

Arquivar uma turma só a tira dos filtros: NÃO encerra as matrículas. Aluno
ativo matriculado no ano letivo ativo numa turma arquivada continuaria nos
rankings, premiações, certificado e relatórios ligado a uma turma invisível —
um estado sem semântica. Por isso:

  * arquivar é recusado enquanto houver aluno ativo na turma
    (``routers.academico._exigir_turma_sem_alunos_ativos``);
  * e nenhuma porta põe aluno ativo DENTRO de turma arquivada. A regra é a
    mesma da importação (``identidade_aluno.turma_ativa`` — a REDE DE SEGURANÇA
    de ``routers.importacoes._persistir_linhas``, motivo ``turma_arquivada``) e
    vale, com o 409 deste módulo, em:

      - "Transferir de turma" (POST /alunos/acoes, ``transferir``) — destino;
      - cadastro manual (POST /alunos);
      - "Reativar" (POST /alunos/acoes, ``reativar``) de ficha cuja matrícula do
        ano ativo está em turma arquivada (``exigir_reativacao_em_turma_ativa``);
      - "Corrigir turmas duplicadas" (POST /turmas/duplicadas/corrigir) — a
        canônica que recebe as matrículas das duplicadas;
      - fila de Revisões de identidade (POST /importacoes/revisoes/{id}/resolver)
        com ``criar_em_turma_id`` — a ficha nova nasce "ativa".

Mora em ``app/services`` (e não num router) para as portas de
``routers.academico`` e ``routers.importacoes`` usarem o MESMO texto sem um
router importar o outro.

As portas tomam a trava da escola (``bloquear_escola_para_importacao``) ANTES de
ler o status da turma — a mesma do arquivamento —, para a turma não ser
arquivada entre a leitura e a gravação (no-op no SQLite).

O ANO LETIVO da turma (trava do destino, ``exigir_destino_do_ano_ativo``): a
matrícula que uma porta grava (ou move) é a do ano letivo ATIVO, e numa turma
ATIVA de outro ano (ex.: 2025 com a escola em 2026) ela continuava contando na
escola e sumia das turmas do ano — a diferença entregava a criança à Secretaria
por subtração. Era a lacuna geral declarada aqui; agora TODAS as portas a
fecham com 409, antes de gravar:

  - cadastro manual (POST /alunos) e o DESTINO de "Transferir de turma"
    (``routers.academico``, com esta função);
  - fila de Revisões de identidade (POST /importacoes/revisoes/{id}/resolver)
    com ``criar_em_turma_id`` (``routers.importacoes``, com esta função);
  - "Corrigir turmas duplicadas": duplicada de ano diferente do da canônica
    (``routers.academico._exigir_duplicadas_do_ano_da_canonica``);
  - mudar o ano letivo de turma com matrícula de outro ano
    (``routers.academico._exigir_turma_sem_matricula_de_outro_ano``);
  - "Reativar" ficha cuja matrícula do ano ativo (legada) está em turma de
    outro ano (``exigir_reativacao_em_turma_ativa``): a ficha voltaria a contar
    pela matrícula, fora das turmas do ano.

O pipeline de importação recusa a mesma combinação (motivo
``turma_fora_do_ano_letivo``). Dado legado já nesse estado não é tocado: a ficha
ATIVA que já está assim continua contando até alguém transferi-la."""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import bloquear_escola_para_importacao
from app.models import Aluno, Matricula, Turma
from app.services import identidade_aluno

# O motivo, igual em todas as portas.
NAO_RECEBE = ("Turma arquivada não recebe aluno ativo: arquivar não encerra as "
              "matrículas, e o aluno continuaria nos rankings, premiações e "
              "relatórios ligado a uma turma fora dos filtros.")
# A saída, quando a turma deve mesmo voltar a receber alunos.
REATIVAR_TURMA = ("reative a turma em Turmas › “Mostrar turmas arquivadas e de "
                  "outros anos letivos” › Reativar")


def mensagem_turma_arquivada(turma: Turma) -> str:
    return (f"A turma “{turma.nome}” está arquivada. {NAO_RECEBE} Escolha uma turma "
            f"ativa — ou, se esta turma deve voltar a receber alunos, {REATIVAR_TURMA}.")


def exigir_turma_ativa(turma: Turma) -> None:
    """409 se ``turma`` não recebe aluno ativo (arquivada). Chamar ANTES de gravar
    qualquer coisa (ficha, matrícula, auditoria) e depois da trava da escola."""
    if identidade_aluno.turma_ativa(turma):
        return
    raise HTTPException(status.HTTP_409_CONFLICT, mensagem_turma_arquivada(turma))


def exigir_destino_do_ano_ativo(destino: Turma, ano: int) -> None:
    """A turma que RECEBE a matrícula do ano letivo ativo ("Transferir de turma",
    cadastro manual, ficha nova do /resolver) tem de ser desse ano: 409 senão,
    antes de gravar qualquer coisa. Mesmo critério de
    ``routers.academico._exigir_origem_do_ano_ativo``.

    Matrícula de 2026 numa turma de 2025 continuava contando na escola (o cartão
    da rede e o lado escola do comparador contam pela matrícula do ano ativo) e
    sumia das turmas do ano (o resumo da escola lista só as turmas do ano ativo):
    a diferença entregava a criança à Secretaria por subtração. A tela já só
    oferece turmas do ano ativo, e as importações recusam essa turma (motivo
    ``turma_fora_do_ano_letivo``); isto fecha a API direta. Dado legado nesse
    estado não é tocado. Mora aqui, e não em ``routers.academico``, para o
    /resolver de ``routers.importacoes`` usar a MESMA trava sem um router importar
    o outro."""
    if destino.ano_letivo == ano:
        return
    raise HTTPException(
        status.HTTP_409_CONFLICT,
        f"A turma “{destino.nome}” é do ano letivo {destino.ano_letivo}, e a matrícula "
        f"que ela receberia é a do ano letivo ativo ({ano}): numa turma de "
        f"{destino.ano_letivo}, o aluno ficaria fora das turmas e dos rankings de "
        f"{ano}. Nada foi gravado. Escolha uma turma do ano letivo {ano}.")


def exigir_reativacao_em_turma_ativa(db: Session, escola_id: int, alunos: list[Aluno],
                                     ano: int) -> None:
    """D17 no "Reativar": ficha que volta a "ativo" com a matrícula do ano letivo
    ATIVO numa turma arquivada recriaria o estado que o D17 proíbe (arquivar os
    alunos, arquivar a turma vazia e reativá-los). 409 para o pedido inteiro,
    ANTES de mudar qualquer status, orientando a transferir antes. Ficha que já
    está ativa não muda nada e não é contada. Conta a matrícula do ano ativo — a
    mesma que "Transferir de turma" move, que é a saída indicada.

    Também 409 (e antes do D17) quando essa matrícula está numa turma de OUTRO ano
    letivo, ativa ou arquivada — dado legado que as portas que gravam já recusam:
    reativada, a ficha voltaria a contar na escola pela matrícula e ficaria fora das
    turmas do ano (a Secretaria a veria por subtração). Reativar a turma antiga não
    resolveria; a saída é levar a matrícula a uma turma do ano.

    Toma a trava do arquivamento (no-op no SQLite) antes de ler o status das
    turmas: a turma não é arquivada entre esta leitura e a reativação."""
    ids = [a.id for a in alunos if a.status != "ativo"]
    if not ids:
        return
    bloquear_escola_para_importacao(db, escola_id)

    def contar(*filtros):
        return db.execute(
            select(Turma.nome, Turma.ano_letivo, func.count(func.distinct(Matricula.aluno_id)))
            .join(Matricula, Matricula.turma_id == Turma.id)
            .where(Matricula.aluno_id.in_(ids), Matricula.ano_letivo == ano, *filtros)
            .group_by(Turma.id, Turma.nome, Turma.ano_letivo)
            .order_by(Turma.nome)
        ).all()

    outro_ano = contar(Turma.ano_letivo.is_not(None), Turma.ano_letivo != ano)
    if outro_ano:
        total = sum(n for _nome, _ano, n in outro_ano)
        turmas = ", ".join(f"“{nome}” ({ano_turma})" for nome, ano_turma, _n in outro_ano)
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{total} aluno(s) selecionado(s) não pode(m) ser reativado(s): a matrícula do "
            f"ano letivo {ano} está em turma de outro ano letivo ({turmas}). Nada foi "
            f"alterado. Antes de reativar, leve a matrícula para uma turma de {ano} "
            "(“Transferir de turma”, ou no perfil do aluno: “Editar dados” › Turma).")
    arquivadas = contar(Turma.status != "ativa")
    if not arquivadas:
        return
    total = sum(n for _nome, _ano, n in arquivadas)
    turmas = ", ".join(f"“{nome}”" for nome, _ano, _n in arquivadas)
    raise HTTPException(
        status.HTTP_409_CONFLICT,
        f"{total} aluno(s) selecionado(s) não pode(m) ser reativado(s): a matrícula do "
        f"ano letivo {ano} está em turma arquivada ({turmas}). {NAO_RECEBE} Antes "
        "de reativar, use “Transferir de turma” para levá-los a uma turma ativa — ou, "
        f"se a turma deve voltar a receber alunos, {REATIVAR_TURMA}.")
