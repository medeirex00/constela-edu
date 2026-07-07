"""Importação de relatórios em PLANILHA (Excel .xlsx) — hoje o Matific.

O Matific exporta o "Relatório de Atividade do Aluno" como um workbook:
uma aba-resumo da turma (uma linha por aluno) seguida de uma aba por aluno.
Só a aba-resumo interessa — as abas por aluno trazem apenas o cabeçalho.

Layout real da aba-resumo (openpyxl, `data_only`):

    R00 | Relatório de Atividade do Aluno |        | Exportado em: 7 jul 2026
    R02 | Turma                           | 5 ANO B MANHA ANUAL (300397500)
    R03 | Professor(a)                    | Andressa Evangelista
    R08 | Datas                          | 6 jun 2026 - 7 jul 2026
    R10 | Alunos | Total de atividades concluídas | Atividades únicas … | Tempo gasto | Pontuação média | <22 tópicos…>
    R11 | Toda a turma | 371 | 93 | 28 h 33 min | 0.31 | …          ← totais (ignorar)
    R12 | CARLOS … SANTOS | 0  | 0  | -          | -    | …          ← conta vazia
    R13 | Carlos … Santos | 30 | 22 | 2 h 4 min  | 0.48 | …          ← conta real

Particularidades tratadas aqui:
  * "Pontuação média" vem como fração 0–1 (0.48) — o scoring normaliza pelo
    máximo da escola, então a escala é preservada como está (auto-normaliza).
  * NÃO há coluna "Estrelas" — o importador preserva o valor anterior.
  * Alunos DUPLICADOS (contas repetidas do Matific: uma zerada, outra real,
    com caixa diferente) são deduplicados mantendo a linha com MAIS atividades.
  * "Toda a turma" e as linhas de metadados nunca viram aluno.
"""
from __future__ import annotations

import io
import re

from app.services.importacao import (
    Analise,
    LinhaImportacao,
    _atribuir_campo,
    _casar_coluna,
    _eh_coluna_nome,
    _fechar_linha,
    normalizar_nome,
)

# Colunas de MÉTRICA da aba-resumo do Matific. A ordem importa: "atividades
# únicas" e "tempo" vêm ANTES de "atividades"/"pontuação" para absorverem os
# rótulos parecidos e não deixarem "Atividades únicas Concluídas" ser capturada
# como o total de atividades.
COLUNAS_MATIFIC_PLANILHA = {
    "atividades_unicas": ["atividades unicas concluidas", "atividades unicas"],
    "tempo": ["tempo gasto", "tempo"],
    "atividades": ["total de atividades concluidas", "total de atividades",
                   "atividades concluidas", "atividades finalizadas", "atividades"],
    "pontuacao_media": ["pontuacao media", "media de pontuacao", "media"],
}

# Só estes viram dados do aluno; os demais (colunas de tópico) são ignorados.
_CAMPOS_UTEIS = {"atividades", "pontuacao_media"}

# Linhas cujo "nome" é, na verdade, o total da turma — nunca são aluno.
_NAO_ALUNO = {"toda a turma", "toda turma", "total da turma", "total"}

_CODIGO_TURMA = re.compile(r"\s*\(\d+\)\s*$")  # "(300397500)" ao fim do nome


def _texto(celula) -> str:
    return "" if celula is None else str(celula).strip()


def _linhas_da_aba(ws, limite: int = 5000) -> list[list]:
    linhas: list[list] = []
    for indice, linha in enumerate(ws.iter_rows(values_only=True)):
        linhas.append(list(linha))
        if indice + 1 >= limite:
            break
    return linhas


def _achar_cabecalho(linhas: list[list]) -> tuple[int | None, dict[str, int]]:
    """Índice da linha de cabeçalho e o mapa campo→coluna. O cabeçalho é a
    primeira linha cuja 1ª célula é uma coluna de nome ("Alunos") e que traz
    ao menos uma métrica reconhecível."""
    for indice, celulas in enumerate(linhas):
        if not celulas or not _texto(celulas[0]):
            continue
        if not _eh_coluna_nome(_texto(celulas[0])):
            continue
        mapa: dict[str, int] = {}
        for coluna, celula in enumerate(celulas[1:], start=1):
            rotulo = _texto(celula)
            if not rotulo:
                continue
            campo = _casar_coluna(rotulo, COLUNAS_MATIFIC_PLANILHA, ignorar=set(mapa))
            if campo:
                mapa[campo] = coluna
        if _CAMPOS_UTEIS & set(mapa):
            return indice, mapa
    return None, {}


def _metadado(linhas: list[list], *rotulos: str) -> str:
    """Valor (2ª célula) da primeira linha cujo 1º rótulo casa — usado para
    Turma/Professor, que vêm como pares 'Rótulo | Valor'."""
    alvos = {normalizar_nome(r) for r in rotulos}
    for celulas in linhas:
        if len(celulas) < 2:
            continue
        rotulo = normalizar_nome(_texto(celulas[0]))
        if rotulo and any(rotulo.startswith(a) for a in alvos):
            valor = _texto(celulas[1])
            if valor:
                return valor
    return ""


def _aba_resumo(wb) -> tuple[object | None, int, dict[str, int], list[list]]:
    """Escolhe a aba que contém a tabela de alunos (a aba-resumo da turma).

    Percorre todas as abas e devolve a primeira com um cabeçalho válido —
    as abas por aluno só têm metadados, então nunca casam.
    """
    for ws in wb.worksheets:
        linhas = _linhas_da_aba(ws)
        indice, mapa = _achar_cabecalho(linhas)
        if indice is not None:
            return ws, indice, mapa, linhas
    return None, -1, {}, []


def detecta_matific_planilha(conteudo: bytes, nome_arquivo: str = "") -> bool:
    """Sem abrir tudo: é um .xlsx (ZIP 'PK') e o nome/estrutura lembram Matific?
    A confirmação real vem de `analisar_planilha`, que só reconhece se achar a
    tabela de alunos."""
    return conteudo[:2] == b"PK"


def analisar_planilha(conteudo: bytes, plataforma: str | None = None,
                      nome_arquivo: str = "") -> Analise:
    """Lê um relatório Matific em .xlsx e devolve a mesma `Analise` dos PDFs.

    Levanta ValueError com mensagem amigável quando o arquivo não é um Excel
    reconhecível — o router traduz em HTTP 400.
    """
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(conteudo), data_only=True, read_only=True)
    except Exception as exc:  # noqa: BLE001 — arquivo corrompido/não-xlsx
        raise ValueError("Não foi possível abrir a planilha. "
                         "Confirme que é um arquivo Excel (.xlsx) válido.") from exc

    try:
        ws, indice_cab, mapa, linhas = _aba_resumo(wb)
    finally:
        wb.close()

    if ws is None:
        raise ValueError(
            "Planilha não reconhecida. O Constela Edu importa o Excel "
            "\"Relatório de Atividade do Aluno\" exportado pelo Matific.")

    if plataforma and plataforma != "matific":
        raise ValueError("Esta planilha é do Matific, mas a plataforma "
                         f"selecionada foi {plataforma}.")

    turma = _CODIGO_TURMA.sub("", _metadado(linhas, "turma")).strip()
    professor = _metadado(linhas, "professor", "professor(a)")

    # Uma LinhaImportacao por aluno; deduplica pela linha com mais atividades.
    por_aluno: dict[str, tuple[float, LinhaImportacao]] = {}
    ordem: list[str] = []
    for numero, celulas in enumerate(linhas[indice_cab + 1:], start=indice_cab + 2):
        nome = _texto(celulas[0]) if celulas else ""
        if not nome or normalizar_nome(nome) in _NAO_ALUNO:
            continue
        item = LinhaImportacao(numero=numero, nome=nome, dados={})
        if turma:
            item.dados["turma_relatorio"] = turma
        for campo, coluna in mapa.items():
            if campo not in _CAMPOS_UTEIS:
                continue  # atividades_unicas / tempo são só âncoras de coluna
            bruto = _texto(celulas[coluna]) if coluna < len(celulas) else ""
            if bruto and bruto not in {"-", "—", "–"}:
                _atribuir_campo(item, campo, bruto)
        _fechar_linha(item)
        chave = normalizar_nome(nome)
        atividades = float(item.dados.get("atividades", 0) or 0)
        # Mantém a conta com mais atividades (a real vence a duplicata zerada).
        if chave not in por_aluno or atividades > por_aluno[chave][0]:
            if chave not in por_aluno:
                ordem.append(chave)
            por_aluno[chave] = (atividades, item)

    # Renumera na ordem de aparição para a prévia ficar estável.
    linhas_final: list[LinhaImportacao] = []
    for pos, chave in enumerate(ordem, start=1):
        item = por_aluno[chave][1]
        item.numero = pos
        linhas_final.append(item)

    analise = Analise(
        plataforma="matific", formato="resumo", estrategia="planilha_matific",
        turma_detectada=turma, professor_detectado=professor,
        mensagem_deteccao="Este arquivo pertence ao Matific — relatório de "
        "atividade da turma" + (f" ({turma})" if turma else "") + ".")
    analise.linhas = linhas_final
    if not linhas_final:
        analise.erros_gerais.append(
            "A planilha do Matific foi lida, mas nenhuma linha de aluno foi "
            "encontrada na aba-resumo da turma.")
    return analise
