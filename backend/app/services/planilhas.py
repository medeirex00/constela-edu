"""Importação de relatórios em PLANILHA (Excel .xlsx) — hoje o Matific.

O Matific exporta o "Relatório de Atividade do Aluno" por turma como um
workbook: uma aba-resumo da turma (uma linha por aluno) seguida de uma aba
por aluno. Só a aba-resumo interessa — as abas por aluno trazem apenas o
cabeçalho.

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
  * "Pontuação média" vem como fração 0–1 (0.48). É multiplicada por 5 para
    ficar na MESMA escala 0–5 do relatório GERAL em PDF (avg. de estrelas) —
    senão, numa escola que importa os dois formatos, o scoring (que normaliza
    pelo máximo da escola) rebaixaria ~5× quem veio do Excel.
  * NÃO há coluna "Estrelas" — o importador preserva o valor anterior.
  * As colunas são classificadas por TOKEN ("única" → coluna de únicas; caso
    contrário "atividade" → total), robusto a rótulos curtos ("Atividades").
  * Contas DUPLICADAS do Matific (mesmo aluno, uma zerada e outra real, caixa
    diferente) são deduplicadas; homônimos REAIS (duas contas com atividades)
    são preservados e um AVISO é emitido — nunca some aluno em silêncio.
  * "Toda a turma" e variações de idioma (Whole class / Toda la clase) nunca
    viram aluno.
"""
from __future__ import annotations

import io
import re

from app.services.importacao import (
    Analise,
    LinhaImportacao,
    _atribuir_campo,
    _eh_coluna_nome,
    _fechar_linha,
    normalizar_nome,
)

# Escala da "Pontuação média": o Excel usa 0–1; o PDF geral usa 0–5 (média de
# estrelas). Alinhamos o Excel ao PDF para não enviesar o ranking quando a
# escola importa os dois formatos (o scoring normaliza pelo máximo da escola).
ESCALA_PONTUACAO_XLSX = 5.0

# Linhas cujo "nome" é, na verdade, o total da turma — nunca são aluno.
_NAO_ALUNO = {"toda a turma", "toda turma", "turma toda", "total da turma",
              "total da classe", "total", "whole class", "toda la clase",
              "clase completa"}

_CODIGO_TURMA = re.compile(r"\s*\(\d+\)\s*$")  # "(300397500)" ao fim do nome


def _texto(celula) -> str:
    return "" if celula is None else str(celula).strip()


def _classificar_coluna(rotulo: str) -> str | None:
    """Campo de MÉTRICA de uma coluna da aba-resumo, por token — robusto a
    rótulos curtos. "Atividades únicas Concluídas" tem 'única' e é a coluna de
    únicas; "Total de atividades concluídas" OU só "Atividades" é o TOTAL."""
    p = normalizar_nome(rotulo)
    if not p:
        return None
    if "pontuacao" in p or "media" in p:
        return "pontuacao_media"
    if "unica" in p:  # "Atividades únicas Concluídas" — só âncora, não é o total
        return "atividades_unicas"
    if "tempo" in p:  # "Tempo gasto" — só âncora
        return "tempo"
    if "atividade" in p:
        return "atividades"
    return None


def _eh_linha_total(nome: str) -> bool:
    """A linha de totais da turma ("Toda a turma" e variações de idioma)."""
    p = normalizar_nome(nome)
    if p in _NAO_ALUNO:
        return True
    if "toda" in p and ("turma" in p or "classe" in p or "clase" in p):
        return True
    if "whole" in p and "class" in p:
        return True
    if "total" in p and ("turma" in p or "classe" in p or "class" in p or "geral" in p):
        return True
    return False


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
    ao menos uma métrica reconhecível (a 1ª ocorrência de cada campo vence)."""
    for indice, celulas in enumerate(linhas):
        if not celulas or not _texto(celulas[0]):
            continue
        if not _eh_coluna_nome(_texto(celulas[0])):
            continue
        mapa: dict[str, int] = {}
        for coluna, celula in enumerate(celulas[1:], start=1):
            campo = _classificar_coluna(_texto(celula))
            if campo and campo not in mapa:
                mapa[campo] = coluna
        if "atividades" in mapa or "pontuacao_media" in mapa:
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
    """Sem abrir tudo: é um .xlsx (ZIP 'PK')? A confirmação real vem de
    `analisar_planilha`, que só reconhece se achar a tabela de alunos."""
    return conteudo[:2] == b"PK"


def _ler_aluno(numero: int, celulas: list, mapa: dict[str, int], turma: str) -> LinhaImportacao:
    """Uma linha de dados → LinhaImportacao (só nome, atividades, pontuação)."""
    item = LinhaImportacao(numero=numero, nome=_texto(celulas[0]), dados={})
    if turma:
        item.dados["turma_relatorio"] = turma
    for campo in ("atividades", "pontuacao_media"):  # só estes viram dados
        coluna = mapa.get(campo)
        if coluna is None or coluna >= len(celulas):
            continue
        bruto = _texto(celulas[coluna])
        if bruto and bruto not in {"-", "—", "–"}:
            _atribuir_campo(item, campo, bruto)
    # Alinha a pontuação (0–1) à escala 0–5 do relatório em PDF.
    if "pontuacao_media" in item.dados:
        item.dados["pontuacao_media"] = round(
            item.dados["pontuacao_media"] * ESCALA_PONTUACAO_XLSX, 2)
    return _fechar_linha(item)


def _atividades(item: LinhaImportacao) -> float:
    return float(item.dados.get("atividades", 0) or 0)


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

    # 1) Lê cada linha de dados (pula a linha de totais da turma).
    brutos: list[LinhaImportacao] = []
    for numero, celulas in enumerate(linhas[indice_cab + 1:], start=indice_cab + 2):
        nome = _texto(celulas[0]) if celulas else ""
        if not nome or _eh_linha_total(nome):
            continue
        brutos.append(_ler_aluno(numero, celulas, mapa, turma))

    # 2) Agrupa por nome; colapsa contas DUPLICADAS (uma zerada) mas PRESERVA
    #    homônimos reais (duas contas com atividades) — nunca some aluno calado.
    grupos: dict[str, list[LinhaImportacao]] = {}
    ordem: list[str] = []
    for item in brutos:
        chave = normalizar_nome(item.nome)
        if chave not in grupos:
            grupos[chave] = []
            ordem.append(chave)
        grupos[chave].append(item)

    linhas_final: list[LinhaImportacao] = []
    homonimos: list[str] = []
    for chave in ordem:
        itens = grupos[chave]
        if len(itens) == 1:
            linhas_final.append(itens[0])
            continue
        com_dados = [it for it in itens if _atividades(it) > 0]
        if len(com_dados) <= 1:
            # Duplicata do Matific (conta vazia + real, ou todas vazias):
            # mantém a de mais atividades.
            linhas_final.append(max(itens, key=_atividades))
        else:
            # Homônimos reais: preserva TODAS as contas com dados e avisa.
            linhas_final.extend(com_dados)
            homonimos.append(f"{com_dados[0].nome} ({len(com_dados)} contas)")

    for pos, item in enumerate(linhas_final, start=1):
        item.numero = pos

    analise = Analise(
        plataforma="matific", formato="resumo", estrategia="planilha_matific",
        turma_detectada=turma, professor_detectado=professor,
        mensagem_deteccao="Este arquivo pertence ao Matific — relatório de "
        "atividade da turma" + (f" ({turma})" if turma else "") + ".")
    analise.linhas = linhas_final
    if homonimos:
        analise.erros_gerais.append(
            "Atenção: nomes repetidos na turma (confira e ajuste manualmente): "
            + "; ".join(homonimos) + ".")
    if not linhas_final:
        analise.erros_gerais.append(
            "A planilha do Matific foi lida, mas nenhuma linha de aluno foi "
            "encontrada na aba-resumo da turma.")
    return analise
