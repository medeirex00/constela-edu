"""Importação inteligente de relatórios (PRD §15–§16, §50–§52).

Objetivo: o usuário baixa o PDF da plataforma e arrasta para o Constela Edu
— sem editar, converter ou renomear nada. Para isso, o parser não depende
de um formato fixo: ele é um PIPELINE de estratégias que competem entre si
e vence a que reconhecer mais alunos.

    texto (PDF em modo layout, ou colado)
        │
        ├─ detecção da plataforma (pontuação por palavras-chave)
        │
        ├─ Estratégia TABELA          cabeçalho + separadores (tab ; , espaços)
        ├─ Estratégia VERTICAL        cabeçalho em linhas separadas (PDF comum)
        ├─ Estratégia RÓTULOS         blocos "Campo: valor" por aluno
        └─ Estratégia POSICIONAL      "Nome Sobrenome 42 85,5 120" sem cabeçalho
        │
        └─ melhor resultado → prévia (nada é gravado sem confirmação)

Princípios de robustez (pedido do produto):
  * colunas casadas por SEMELHANÇA (acentos/caixa/espaços ignorados,
    sinônimos e distância de edição), nunca por nome exato;
  * campo que falhar vira AVISO na linha — a importação continua com o
    que foi reconhecido; erro de verdade só quando a linha não tem nome
    ou nenhum dado aproveitável;
  * quando nada é reconhecido, o diagnóstico diz exatamente o que foi
    detectado e o que faltou (inclusive PDF digitalizado/imagem).
"""
from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Aluno, Matricula, Turma

# --------------------------------------------------------------------------
# Normalização de texto e números
# --------------------------------------------------------------------------

def normalizar_nome(texto: str) -> str:
    """Remove acentos, caixa e espaços repetidos — base de toda comparação."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", sem_acento).strip().casefold()


def _numero(celula: str) -> float:
    """Converte '1.234,56', '85,5', '85.5' ou '92%' para float."""
    limpo = celula.strip().replace("%", "").replace(" ", "")
    if not limpo:
        raise ValueError("vazio")
    if "," in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", limpo):
        limpo = limpo.replace(".", "")  # 1.234 = milhar pt-BR
    return float(limpo)


def _eh_numero(celula: str) -> bool:
    try:
        _numero(celula)
        return True
    except ValueError:
        return False


def _niveis(celula: str) -> dict[str, int]:
    """Interpreta 'AA:2, D:1' (ou 'AA=2; D=1') como {"AA": 2, "D": 1}."""
    pares = re.findall(r"([A-Za-z]{1,2})\s*[:=]\s*(\d+)", celula)
    if not pares and celula.strip():
        raise ValueError(f"níveis ilegíveis: {celula!r}")
    return {codigo.upper(): int(qtd) for codigo, qtd in pares}


# --------------------------------------------------------------------------
# Detecção de plataforma (PRD §50) — o usuário não precisa informar
# --------------------------------------------------------------------------

_PALAVRAS = {
    "matific": ["matific", "atividade", "estrela", "episodio", "pontuacao media",
                "matematica", "activities", "stars"],
    "elefante": ["elefante", "letrado", "livro", "leitura", "questo", "nivel",
                 "titulo", "compreensao", "books", "reading"],
}

NOMES_PLATAFORMA = {"matific": "Matific", "elefante": "Elefante Letrado"}


def detectar_plataforma_detalhado(texto: str) -> tuple[str | None, str]:
    """(plataforma, mensagem amigável) — ex.: “Este arquivo pertence ao Matific.”"""
    plano = normalizar_nome(texto)
    pontos = {p: sum(plano.count(k) for k in ks) for p, ks in _PALAVRAS.items()}
    if pontos["matific"] == pontos["elefante"]:
        return None, ("Não foi possível identificar a plataforma pelo conteúdo — "
                      "selecione Matific ou Elefante Letrado.")
    plataforma = max(pontos, key=pontos.get)  # type: ignore[arg-type]
    return plataforma, f"Este arquivo pertence ao {NOMES_PLATAFORMA[plataforma]}."


def detectar_plataforma(texto: str) -> str | None:
    return detectar_plataforma_detalhado(texto)[0]


# --------------------------------------------------------------------------
# Colunas conhecidas e casamento difuso (PRD: não depender de nomes exatos)
# --------------------------------------------------------------------------

_COL_NOME = ["nome do aluno", "nome", "aluno", "aluno(a)", "aluna", "estudante",
             "nome completo", "student", "student name", "participante", "crianca"]

COLUNAS_MATIFIC = {
    "atividades": ["atividades finalizadas", "atividades concluidas",
                   "atividades completas", "atividades", "episodios concluidos",
                   "episodios", "completed activities", "activities"],
    "pontuacao_media": ["pontuacao media", "media de pontuacao", "media", "pontuacao",
                        "nota media", "desempenho", "average score", "score"],
    "estrelas": ["estrelas", "total de estrelas", "stars"],
}

# Colunas de FAIXA de dificuldade (formato "livros por nível"): cada coluna é
# a quantidade de livros concluídos numa faixa. Os valores caem em
# livros_por_nivel[<slug da faixa>] e alimentam os pontos de dificuldade.
COLUNAS_FAIXAS = {
    "faixa:pre_leitor": ["pre leitor", "pre-leitor", "preleitor",
                         "livros pre leitor", "pre leitores"],
    "faixa:nivel_1": ["nivel 1", "nivel1", "livros nivel 1", "n1"],
    "faixa:nivel_2": ["nivel 2", "nivel2", "livros nivel 2", "n2"],
    "faixa:nivel_3": ["nivel 3", "nivel3", "livros nivel 3", "n3"],
    "faixa:nivel_4": ["nivel 4", "nivel4", "livros nivel 4", "n4"],
    "faixa:nivel_5": ["nivel 5", "nivel5", "livros nivel 5", "n5"],
}

COLUNAS_ELEFANTE_RESUMO = {
    "livros_unicos": ["livros lidos", "livros unicos", "livros concluidos",
                      "livros finalizados", "titulos lidos", "titulos concluidos",
                      "livros", "books"],
    "tempo_leitura_min": ["tempo de leitura", "tempo total", "tempo (min)",
                          "minutos de leitura", "tempo lido", "tempo", "minutos",
                          "reading time"],
    "questoes_tentativas": ["questoes respondidas", "questoes feitas", "questoes",
                            "tentativas", "exercicios", "perguntas respondidas",
                            "quizzes"],
    "questoes_acertos": ["acertos", "respostas corretas", "questoes corretas",
                         "respostas certas", "correct answers"],
    "livros_por_nivel": ["livros por nivel", "nivel dos livros"],
    **COLUNAS_FAIXAS,
}

# Formato alternativo do Elefante: uma linha por livro concluído
COLUNAS_ELEFANTE_LEITURAS = {
    "livro": ["titulo do livro", "titulo", "livro", "obra"],
    "nivel": ["nivel do livro", "nivel", "codigo"],
}

_OBRIGATORIAS = {
    "matific": {"atividades"},
    "elefante_resumo": {"livros_unicos"},
    "elefante_leituras": {"livro"},
}

# Ordem padrão das colunas nos relatórios (usada pelas estratégias sem cabeçalho)
ORDEM_PADRAO = {
    "matific": ["atividades", "pontuacao_media", "estrelas"],
    "elefante": ["livros_unicos", "tempo_leitura_min",
                 "questoes_tentativas", "questoes_acertos"],
}


def _semelhante_forte(texto: str, sinonimo: str) -> bool:
    """Correspondência SEM distância de edição: prefixo ou contenção de tokens.
    Usada na 1ª passada para não confundir rótulos parecidos como “Nível 1” e
    “Nível 2” (que ficam a um caractere de distância)."""
    if not texto:
        return False
    if texto.startswith(sinonimo) or sinonimo.startswith(texto):
        return True
    tokens_texto = set(texto.split())
    tokens_sin = set(sinonimo.split())
    return bool(tokens_sin and tokens_sin <= tokens_texto
                and len(tokens_texto) <= len(tokens_sin) + 2)


def _semelhante(texto: str, sinonimo: str) -> bool:
    """Casamento difuso: correspondência forte OU distância de edição.

    A contenção de tokens só vale para textos CURTOS — senão um título como
    “Relatório de desempenho da turma” casaria com o sinônimo “desempenho”.
    """
    if _semelhante_forte(texto, sinonimo):
        return True
    return bool(texto) and SequenceMatcher(None, texto, sinonimo).ratio() >= 0.82


def _casar_coluna(celula: str, colunas: dict[str, list[str]],
                  ignorar: set[str] | None = None) -> str | None:
    """Campo cujo sinônimo mais se parece com a célula.

    Duas passadas: primeiro correspondência FORTE (exata/prefixo/tokens) em
    todos os campos — assim “Nível 2” casa com a faixa certa antes que a
    distância de edição a confunda com “Nível 1”; só depois a passada difusa
    tolera erros de digitação. `ignorar` pula campos já mapeados.
    """
    plano = normalizar_nome(celula)
    for criterio in (_semelhante_forte, _semelhante):
        for campo, sinonimos in colunas.items():
            if ignorar and campo in ignorar:
                continue
            if any(criterio(plano, s) for s in sinonimos):
                return campo
    return None


def _eh_coluna_nome(celula: str) -> bool:
    plano = normalizar_nome(celula)
    return any(_semelhante(plano, s) for s in _COL_NOME)


# --------------------------------------------------------------------------
# Estruturas de resultado
# --------------------------------------------------------------------------

@dataclass
class LinhaImportacao:
    numero: int
    nome: str
    dados: dict
    erros: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    correspondencia: dict | None = None


@dataclass
class Analise:
    plataforma: str
    formato: str  # resumo | leituras
    estrategia: str = ""
    mensagem_deteccao: str = ""
    linhas: list[LinhaImportacao] = field(default_factory=list)
    erros_gerais: list[str] = field(default_factory=list)
    # Turma lida do PDF (relatórios do Elefante trazem no cabeçalho): permite
    # criar/casar o aluno na turma certa sem o usuário informar.
    turma_detectada: str = ""
    escola_detectada: str = ""
    professor_detectado: str = ""
    # Como o nome do aluno foi identificado no relatório individual:
    # "arquivo" (nome do arquivo — preferencial) | "conteudo" | "nenhum".
    origem_nome: str = ""
    # "Intervalo de datas" impresso no relatório (leaderboard do Matific):
    # datas ISO "AAAA-MM-DD". Quando presentes, os valores do relatório são
    # o que os alunos fizeram DENTRO desse intervalo — a confirmação soma ao
    # acumulado e data o snapshot no fim do intervalo.
    periodo_inicio: str = ""
    periodo_fim: str = ""


_RODAPES = ("total", "media", "pagina", "page", "gerado em", "relatorio",
            "turma", "escola", "professor", "periodo", "data:")
_STOPWORDS_NOME = _RODAPES + ("nome", "aluno", "estudante")


def _linha_rodape(linha: str) -> bool:
    plano = normalizar_nome(linha)
    return any(plano.startswith(r) for r in _RODAPES)


def _parece_nome(texto: str) -> bool:
    """Heurística de nome de pessoa: ≥2 palavras, essencialmente alfabético."""
    limpo = texto.strip()
    if len(limpo) < 5 or any(c.isdigit() for c in limpo):
        return False
    palavras = limpo.split()
    if len(palavras) < 2:
        return False
    plano = normalizar_nome(limpo)
    if any(plano.startswith(s) for s in _STOPWORDS_NOME):
        return False
    alfabeticas = sum(1 for c in limpo if c.isalpha() or c in " '-.")
    return alfabeticas / len(limpo) >= 0.9


def _atribuir_campo(item: LinhaImportacao, campo: str, bruto: str) -> None:
    """Converte e guarda um campo; falha vira AVISO (a linha continua útil)."""
    try:
        if campo.startswith("faixa:"):
            # Coluna de faixa: acumula em livros_por_nivel sob o slug da faixa.
            slug = campo.split(":", 1)[1]
            valor = int(_numero(bruto))
            if valor < 0:
                raise ValueError("valor negativo")
            item.dados.setdefault("livros_por_nivel", {})[slug] = valor
        elif campo == "livros_por_nivel":
            item.dados[campo] = _niveis(bruto)
        elif campo == "livro":
            item.dados[campo] = bruto.strip()
        elif campo == "nivel":
            item.dados[campo] = bruto.strip().upper()
        else:
            valor = _numero(bruto)
            if valor < 0:
                raise ValueError("valor negativo")
            item.dados[campo] = valor
    except ValueError:
        item.avisos.append(f"“{campo}” ilegível ({bruto.strip()!r}) — campo ficará ausente.")


def _fechar_linha(item: LinhaImportacao) -> LinhaImportacao:
    """Regra de erro (PRD: não interromper): erro só sem nome ou sem dado algum."""
    if not item.nome:
        item.erros.append("Linha sem nome de aluno.")
    elif not item.dados:
        item.erros.append("Nenhum dado aproveitável nesta linha.")
    return item


# --------------------------------------------------------------------------
# Estratégia 1 — TABELA: cabeçalho + separador (tab ; , ou colunas de espaço)
# --------------------------------------------------------------------------

def _dividir(linha: str, separador: str) -> list[str]:
    if separador == "espacos":
        return [c.strip() for c in re.split(r"\s{2,}", linha.strip()) if c.strip()]
    return [c.strip() for c in linha.split(separador)]


def _separadores_candidatos(linhas: list[str]) -> list[str]:
    corpo = "\n".join(linhas)
    candidatos = []
    if "\t" in corpo:
        candidatos.append("\t")
    if ";" in corpo:
        candidatos.append(";")
    if re.search(r"\S\s{2,}\S", corpo):
        candidatos.append("espacos")
    candidatos.append(",")
    return candidatos


def _mapear_cabecalho(celulas: list[str], colunas: dict[str, list[str]]):
    idx_nome = None
    mapa: dict[str, int] = {}
    for indice, celula in enumerate(celulas):
        if idx_nome is None and _eh_coluna_nome(celula):
            idx_nome = indice
            continue
        campo = _casar_coluna(celula, colunas, ignorar=set(mapa))
        if campo:
            mapa[campo] = indice
    return idx_nome, mapa


def _formatos_da_plataforma(plataforma: str):
    # Resumo vem primeiro: em caso de empate (cabeçalhos ambíguos como
    # “Livros lidos”, que também parece “livro”), o agregado vence — o
    # formato leituras só ganha quando reconhece MAIS linhas que o resumo.
    if plataforma == "matific":
        return [("resumo", COLUNAS_MATIFIC, "matific")]
    return [("resumo", COLUNAS_ELEFANTE_RESUMO, "elefante_resumo"),
            ("leituras", COLUNAS_ELEFANTE_LEITURAS, "elefante_leituras")]


def _estrategia_tabela(linhas_texto: list[str], plataforma: str) -> Analise | None:
    melhor: Analise | None = None
    for separador in _separadores_candidatos(linhas_texto):
        for formato, colunas, chave in _formatos_da_plataforma(plataforma):
            resultado = _tabela_com(linhas_texto, plataforma, separador, formato,
                                    colunas, chave)
            if resultado and (melhor is None or
                              _pontuacao(resultado) > _pontuacao(melhor)):
                melhor = resultado
    return melhor


def _obrigatoria_atendida(chave: str, campos: set[str]) -> bool:
    """Colunas de faixa (faixa:*) também satisfazem o resumo do Elefante."""
    if _OBRIGATORIAS[chave] & campos:
        return True
    if chave == "elefante_resumo":
        return any(c.startswith("faixa:") for c in campos)
    return False


def _tabela_com(linhas_texto, plataforma, separador, formato, colunas, chave):
    inicio, idx_nome, mapa = None, None, {}
    for indice, linha in enumerate(linhas_texto):
        idx, m = _mapear_cabecalho(_dividir(linha, separador), colunas)
        if idx is not None and _obrigatoria_atendida(chave, set(m)):
            inicio, idx_nome, mapa = indice + 1, idx, m
            break
    if inicio is None:
        return None

    analise = Analise(plataforma=plataforma, formato=formato, estrategia="tabela")
    for numero, linha in enumerate(linhas_texto[inicio:], start=inicio + 1):
        if _linha_rodape(linha):
            continue
        celulas = _dividir(linha, separador)
        if idx_nome >= len(celulas) or not celulas[idx_nome]:
            continue
        item = LinhaImportacao(numero=numero, nome=celulas[idx_nome].strip(), dados={})
        for campo, indice_coluna in mapa.items():
            if indice_coluna < len(celulas) and celulas[indice_coluna].strip():
                _atribuir_campo(item, campo, celulas[indice_coluna])
        analise.linhas.append(_fechar_linha(item))
    return analise if analise.linhas else None


# --------------------------------------------------------------------------
# Estratégia 2 — VERTICAL: cabeçalho em linhas separadas (extração comum de PDF)
# --------------------------------------------------------------------------

def _estrategia_vertical(linhas_texto: list[str], plataforma: str) -> Analise | None:
    colunas = COLUNAS_MATIFIC if plataforma == "matific" else COLUNAS_ELEFANTE_RESUMO

    # Procura um bloco de linhas consecutivas que são nomes de colunas
    ordem: list[str] = []
    fim_cabecalho = None
    for indice, linha in enumerate(linhas_texto):
        campo = _casar_coluna(linha, colunas, ignorar=set(ordem))
        eh_nome = _eh_coluna_nome(linha)
        if campo or eh_nome:
            if not ordem and not eh_nome and campo is None:
                continue
            if campo and campo not in ordem:
                ordem.append(campo)
            fim_cabecalho = indice
        elif ordem and len(ordem) >= 2:
            break
        elif ordem:
            ordem, fim_cabecalho = [], None  # bloco interrompido cedo demais
    if len(ordem) < 2 or fim_cabecalho is None:
        return None

    analise = Analise(plataforma=plataforma, formato="resumo",
                      estrategia="cabecalho_vertical")
    item: LinhaImportacao | None = None
    preenchidos = 0
    for numero, linha in enumerate(linhas_texto[fim_cabecalho + 1:],
                                   start=fim_cabecalho + 2):
        linha = linha.strip()
        if not linha or _linha_rodape(linha):
            continue
        if _parece_nome(linha):
            if item is not None:
                analise.linhas.append(_fechar_linha(item))
            item = LinhaImportacao(numero=numero, nome=linha, dados={})
            preenchidos = 0
            continue
        if item is not None and preenchidos < len(ordem):
            if _eh_numero(linha) or ":" in linha:
                _atribuir_campo(item, ordem[preenchidos], linha)
                preenchidos += 1
    if item is not None:
        analise.linhas.append(_fechar_linha(item))
    return analise if analise.linhas else None


# --------------------------------------------------------------------------
# Estratégia 3 — RÓTULOS: blocos "Campo: valor" por aluno
# --------------------------------------------------------------------------

def _estrategia_rotulos(linhas_texto: list[str], plataforma: str) -> Analise | None:
    colunas = COLUNAS_MATIFIC if plataforma == "matific" else COLUNAS_ELEFANTE_RESUMO
    analise = Analise(plataforma=plataforma, formato="resumo", estrategia="rotulos")
    item: LinhaImportacao | None = None

    for numero, linha in enumerate(linhas_texto, start=1):
        par = re.match(r"^\s*([^:–-]{2,40})[:–-]\s*(.+)$", linha)
        if not par:
            continue
        chave, valor = par.group(1), par.group(2).strip()
        if _eh_coluna_nome(chave) and _parece_nome(valor):
            if item is not None:
                analise.linhas.append(_fechar_linha(item))
            item = LinhaImportacao(numero=numero, nome=valor, dados={})
            continue
        campo = _casar_coluna(chave, colunas)
        if campo and item is not None:
            _atribuir_campo(item, campo, valor)
    if item is not None:
        analise.linhas.append(_fechar_linha(item))
    return analise if len(analise.linhas) >= 1 and any(
        l.dados for l in analise.linhas) else None


# --------------------------------------------------------------------------
# Estratégia 4 — POSICIONAL: "Nome Sobrenome 42 85,5 120" sem cabeçalho
# --------------------------------------------------------------------------

_LINHA_POSICIONAL = re.compile(
    r"^\s*([^\d]{5,}?)\s+((?:[\d.,%]+\s*){1,8})$"
)


def _estrategia_posicional(linhas_texto: list[str], plataforma: str) -> Analise | None:
    ordem = ORDEM_PADRAO["matific" if plataforma == "matific" else "elefante"]
    analise = Analise(plataforma=plataforma, formato="resumo", estrategia="posicional")

    for numero, linha in enumerate(linhas_texto, start=1):
        if _linha_rodape(linha):
            continue
        par = _LINHA_POSICIONAL.match(linha)
        if not par or not _parece_nome(par.group(1)):
            continue
        numeros = par.group(2).split()
        item = LinhaImportacao(numero=numero, nome=par.group(1).strip(), dados={})
        for campo, bruto in zip(ordem, numeros):
            _atribuir_campo(item, campo, bruto)
        if len(numeros) < len(ordem):
            faltantes = ", ".join(ordem[len(numeros):])
            item.avisos.append(f"Colunas ausentes na linha: {faltantes}.")
        if len(numeros) > len(ordem):
            item.avisos.append(
                f"{len(numeros) - len(ordem)} coluna(s) extra(s) ignorada(s).")
        item.avisos.append("Colunas identificadas pela ordem padrão do relatório "
                           f"({', '.join(ordem[:len(numeros)])}) — confira na prévia.")
        analise.linhas.append(_fechar_linha(item))
    return analise if analise.linhas else None


# --------------------------------------------------------------------------
# Pipeline: roda todas as estratégias e escolhe a melhor
# --------------------------------------------------------------------------

def _pontuacao(analise: Analise) -> int:
    """Qualidade = linhas com nome e pelo menos um dado reconhecido."""
    return sum(1 for l in analise.linhas if not l.erros and l.dados)


def detectar_tipo(conteudo: bytes, nome_arquivo: str = "",
                  content_type: str = "") -> str:
    """Formato do arquivo: 'pdf' | 'xlsx' | 'texto'. FONTE ÚNICA de verdade,
    usada pelo upload manual (analisar) E pela sincronização (orchestrator) —
    para as duas detecções nunca divergirem. Reconhece PDF por magic bytes,
    planilha por .xlsx/.xlsm/.xls, content-type de spreadsheet, ZIP ('PK') e o
    OLE2 do .xls antigo."""
    nome = (nome_arquivo or "").lower()
    ct = content_type or ""
    if nome.endswith(".pdf") or ct == "application/pdf" or conteudo[:5] == b"%PDF-":
        return "pdf"
    if (nome.endswith((".xlsx", ".xlsm", ".xls")) or "spreadsheet" in ct
            or ct == "application/vnd.ms-excel" or conteudo[:2] == b"PK"
            or conteudo[:4] == b"\xd0\xcf\x11\xe0"):
        return "xlsx"
    return "texto"


def _int_api(v) -> int:
    """Inteiro tolerante (aceita int/float/str/None) — para os campos numéricos da
    API interna do Elefante."""
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return 0


def _data_iso_elefante(bruto) -> str:
    """Normaliza a data/hora do Elefante (``lastReadWhen``) para ISO — o importador
    de leituras faz ``datetime.fromisoformat``. Aceita ISO (com/sem T, com/sem
    fuso/Z) e o formato brasileiro (dd/mm/aaaa [hh:mm[:ss]]). Vazio se não parsear
    (a leitura ainda conta, só não entra nos rankings por período)."""
    s = str(bruto or "").strip()
    if not s:
        return ""
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).isoformat()
    except ValueError:
        pass
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).isoformat()
        except ValueError:
            continue
    return ""


def analisar_elefante_api(payload: dict, plataforma: str = "elefante") -> Analise:
    """Converte a resposta da API interna do Elefante ``/report/overall-course-
    report`` (uma TURMA) numa ``Analise`` no formato "resumo" — UMA linha por
    aluno. Reusa TODO o pipeline de importação (casar_nomes → confirmar → scoring),
    exatamente como um upload manual do relatório de turma. Não grava nem loga.

    Mapeamento (campo da API → dado do snapshot):
      studentName        → nome (casado por nome, como o upload manual)
      totalBooksRead     → livros_unicos (headline do ranking de leitura)
      totalReadTime (s)  → tempo_leitura_min (a API dá SEGUNDOS)
      responses          → questoes_tentativas
      approvedResponses  → questoes_acertos
    O nível por faixa (distribuição) não vem no agregado da turma — fica p/ depois.
    """
    payload = payload if isinstance(payload, dict) else {}
    desc = payload.get("courseSchoolDescriptors")
    desc = desc if isinstance(desc, dict) else {}
    turma = str(desc.get("courseName") or "").strip()
    if not turma and payload.get("courseId"):
        # Sem nome de turma no relatório: NÃO deixa a turma vazia (senão os alunos
        # novos seriam descartados por falta de turma para criar). Usa o id.
        turma = f"Turma {payload['courseId']}"
    escola = str(desc.get("schoolName") or "").strip()
    professor = str(desc.get("teachers") or "").strip()

    # GRANULAR ("leituras"): UMA linha por LIVRO lido, com DATA — vindo do
    # overall-student-books-read por aluno. Gera Leitura datada (ranking por
    # período: semana/mês/bimestre) + eventos da linha do tempo. Cada item traz o
    # nome do aluno + o livro (título/nível/gênero/tempo/data).
    if isinstance(payload.get("leituras"), list):
        linhas_l: list[LinhaImportacao] = []
        for i, r in enumerate(payload["leituras"], start=1):
            if not isinstance(r, dict):
                continue
            nome = str(r.get("nome") or r.get("studentName") or "").strip()
            titulo = str(r.get("bookTitle") or r.get("livro") or "").strip()
            if not nome or not titulo:
                continue
            data_iso = _data_iso_elefante(r.get("lastReadWhen") or r.get("data"))
            if not data_iso:
                # SEM data confiável → NÃO vira leitura datada (senão o importador a
                # dataria em "hoje" e ela cairia no período ERRADO do prêmio). O
                # total do aluno já está no snapshot agregado (ranking "Todo o
                # histórico"); aqui só entram leituras com data real.
                continue
            tempo_seg = _int_api(r.get("totalTimeSpent", r.get("tempo_livro_seg")))
            linhas_l.append(LinhaImportacao(
                numero=i, nome=nome,
                dados={
                    "livro": titulo,
                    "nivel": str(r.get("levelName") or r.get("nivel") or "").strip(),
                    "genero": str(r.get("genre") or r.get("theme") or r.get("genero") or "").strip(),
                    "data": data_iso,
                    # tempo do livro em MINUTOS (a API dá segundos em totalTimeSpent).
                    "tempo_livro_min": round(tempo_seg / 60) if tempo_seg else None,
                    "turma_relatorio": turma,
                }))
        return Analise(
            plataforma=plataforma, formato="leituras", estrategia="api-elefante",
            mensagem_deteccao="Histórico de leitura por aluno (API Elefante Letrado).",
            linhas=linhas_l, turma_detectada=turma, escola_detectada=escola,
            professor_detectado=professor)

    alunos = payload.get("students")
    linhas: list[LinhaImportacao] = []
    for i, al in enumerate(alunos or [], start=1):
        if not isinstance(al, dict):
            continue
        nome = str(al.get("studentName") or "").strip()
        if not nome:
            continue
        tempo_seg = _int_api(al.get("totalReadTime", al.get("readTime")))
        linhas.append(LinhaImportacao(
            numero=i, nome=nome,
            dados={
                "livros_unicos": _int_api(al.get("totalBooksRead", al.get("qtdBooksRead"))),
                "tempo_leitura_min": round(tempo_seg / 60) if tempo_seg else 0,
                "questoes_tentativas": _int_api(al.get("responses")),
                "questoes_acertos": _int_api(al.get("approvedResponses")),
                # Desambigua HOMÔNIMOS na turma certa (mesmo campo que o parser de
                # PDF usa) — evita casar/duplicar aluno errado.
                "turma_relatorio": turma,
            }))
    return Analise(
        plataforma=plataforma, formato="resumo", estrategia="api-elefante",
        mensagem_deteccao="Relatório de turma (API interna do Elefante Letrado).",
        linhas=linhas, turma_detectada=turma, escola_detectada=escola,
        professor_detectado=professor)


def analisar_texto(texto: str, plataforma: str | None = None) -> Analise:
    """Interpreta um relatório colado/extraído. Nunca grava nada."""
    detectada, mensagem = detectar_plataforma_detalhado(texto)
    plataforma = plataforma or detectada
    if plataforma is None:
        analise = Analise(plataforma="", formato="", mensagem_deteccao=mensagem)
        analise.erros_gerais.append(mensagem)
        return analise
    if plataforma == detectada:
        mensagem_final = mensagem
    else:
        mensagem_final = f"Plataforma informada manualmente: {NOMES_PLATAFORMA[plataforma]}."

    linhas_texto = [l for l in texto.splitlines() if l.strip()]

    candidatas = [
        _estrategia_tabela(linhas_texto, plataforma),
        _estrategia_vertical(linhas_texto, plataforma),
        _estrategia_rotulos(linhas_texto, plataforma),
        _estrategia_posicional(linhas_texto, plataforma),
    ]
    # Mesmo uma análise onde todas as linhas têm problema é melhor que nada:
    # a prévia mostra qual aluno/coluna falhou (PRD: não interromper tudo).
    validas = [c for c in candidatas if c is not None and c.linhas]

    if not validas:
        analise = Analise(plataforma=plataforma, formato="",
                          mensagem_deteccao=mensagem_final)
        analise.erros_gerais.append(_diagnostico(linhas_texto, plataforma))
        return analise

    melhor = max(validas, key=lambda c: (_pontuacao(c), len(c.linhas)))
    melhor.mensagem_deteccao = mensagem_final
    return melhor


def _diagnostico(linhas_texto: list[str], plataforma: str) -> str:
    """Quando nada foi reconhecido, dizer exatamente o que foi tentado."""
    nomes = sum(1 for l in linhas_texto if _parece_nome(l.strip()))
    numericas = sum(1 for l in linhas_texto
                    if any(_eh_numero(t) for t in l.split()))
    if not linhas_texto:
        return ("O arquivo não contém texto legível. Se for um PDF digitalizado "
                "(imagem escaneada), exporte o relatório em versão digital na "
                "plataforma — a leitura de imagens não é suportada.")
    return (f"Nenhuma das 4 estratégias reconheceu os dados "
            f"({NOMES_PLATAFORMA.get(plataforma, plataforma)}; "
            f"{len(linhas_texto)} linhas, {nomes} parecendo nomes, "
            f"{numericas} com números). Envie este arquivo para a equipe do "
            "Constela Edu para adicionarmos o formato — ou cole o texto do "
            "relatório para tentar de novo.")


# --------------------------------------------------------------------------
# Extração de texto de PDF
# --------------------------------------------------------------------------

def extrair_texto_pdf(conteudo: bytes) -> str:
    """Extrai o texto preservando colunas quando possível.

    O modo `layout` do pypdf mantém o espaçamento entre colunas — a
    estratégia TABELA volta a funcionar em PDFs que o modo simples
    embaralharia. Se o layout falhar, cai no modo padrão.
    """
    from pypdf import PdfReader

    leitor = PdfReader(io.BytesIO(conteudo))
    paginas: list[str] = []
    for pagina in leitor.pages:
        texto = ""
        try:
            texto = pagina.extract_text(extraction_mode="layout") or ""
        except Exception:  # noqa: BLE001 — layout é melhor esforço
            texto = ""
        if not texto.strip():
            texto = pagina.extract_text() or ""
        paginas.append(texto)
    return "\n".join(paginas)


# --------------------------------------------------------------------------
# Correspondência inteligente de nomes (PRD §52)
# --------------------------------------------------------------------------

LIMIAR_PROVAVEL = 0.80   # abaixo disso não sugerimos automaticamente
LIMIAR_ALTERNATIVA = 0.60


def _similaridade(a: str, b: str) -> float:
    direta = SequenceMatcher(None, a, b).ratio()
    tokens = SequenceMatcher(None, " ".join(sorted(a.split())), " ".join(sorted(b.split()))).ratio()
    return max(direta, tokens)


# O Matific abrevia: "ANTONELLA D" = primeiro nome + inicial de um sobrenome
_RE_ABREVIADO = re.compile(r"^(\w{2,})\s+(\w)\.?$")


def _tokens_turma(texto: str) -> set[str]:
    """Tokens comparáveis de nome de turma: "5º Ano B" ≈ "5 ANO B MANHA"."""
    plano = normalizar_nome(re.sub(r"[ºª°]", "", texto or ""))
    return {t for t in plano.split() if t}


# Expostos para o casamento da Lista Piloto (import de matrículas).
def tokens_turma(texto: str) -> set[str]:
    return _tokens_turma(texto)


def tokens_nome(nome: str) -> list[str]:
    return [t for t in normalizar_nome(nome or "").split() if t]


def casa_abreviado_posicional(antigo: list[str], completo: list[str]) -> bool:
    """`antigo` (nome abreviado de upload, ex.: ["agatha","v"]) é uma abreviação
    POSICIONAL de `completo` (nome do Excel, ex.: ["agatha","vitoria","moura",
    "da","silva"])?

    A abreviação do Matific/Elefante é posicional no 2º+ token — "AGATHA V" =
    Agatha + inicial do 2º nome (Vitoria), NÃO "Agatha ... da Silva". Por isso:
      • primeiro nome idêntico;
      • cada token intermediário cheio deve casar EXATO por posição;
      • uma inicial (1 letra) só é aceita como ÚLTIMO token de `antigo`, casando
        o começo do token de mesma posição em `completo`;
      • `completo` precisa ser mais informativo (mais tokens, ou o último token
        de `antigo` é inicial) — nomes idênticos vão pelo caminho nome-exato.
    Nunca usa subsequência (evita casar "ELOA S" com "ELOA ... SILVA")."""
    if len(antigo) < 2 or len(antigo) > len(completo):
        return False
    if antigo[0] != completo[0]:
        return False
    for i in range(1, len(antigo)):
        tok = antigo[i]
        if len(tok) == 1:                     # inicial: só no fim, casa prefixo
            if i != len(antigo) - 1 or not completo[i].startswith(tok):
                return False
        elif tok != completo[i]:              # token cheio: idêntico por posição
            return False
    return len(completo) > len(antigo) or len(antigo[-1]) == 1


def _desempatar_por_turma(candidatos: list, turma_relatorio: str | None,
                          turma_de: dict[int, str]):
    """Entre homônimos, escolhe o aluno cuja turma bate com a do relatório.
    Devolve None se não há pista de turma ou se persiste empate (o usuário
    decide, para nunca pontuar o aluno errado)."""
    if not turma_relatorio:
        return None
    alvo = _tokens_turma(turma_relatorio)
    pontuados = sorted(
        ((len(alvo & _tokens_turma(turma_de.get(a.id, ""))), a) for a in candidatos),
        key=lambda item: item[0], reverse=True)
    pontos, melhor = pontuados[0]
    empate = len(pontuados) > 1 and pontuados[1][0] == pontos
    return melhor if pontos >= 2 and not empate else None


def _casar_abreviado(alvo: str, indice, turma_relatorio: str | None,
                     turma_de: dict[int, str]) -> dict | None:
    """Correspondência para nomes abreviados; nunca devolve "exato" —
    uma inicial não é prova suficiente para importar sem confirmação."""
    par = _RE_ABREVIADO.match(alvo)
    if not par:
        return None
    primeiro, inicial = par.groups()
    candidatos = [
        aluno for aluno, nome_plano in indice
        if (tokens := nome_plano.split()) and tokens[0] == primeiro
        and any(t.startswith(inicial) for t in tokens[1:])
    ]
    if not candidatos:
        return None
    alternativas = [
        {"aluno_id": aluno.id, "nome": aluno.nome, "similaridade": 90.0}
        for aluno in candidatos[:3]
    ]
    if len(candidatos) == 1:
        aluno = candidatos[0]
        return {"status": "provavel", "aluno_id": aluno.id, "aluno_nome": aluno.nome,
                "similaridade": 92.0, "alternativas": alternativas}
    # Mais de um "HELOISA D": a turma citada no relatório desempata
    if turma_relatorio:
        alvo_turma = _tokens_turma(turma_relatorio)
        pontuados = sorted(
            ((len(alvo_turma & _tokens_turma(turma_de.get(aluno.id, ""))), aluno)
             for aluno in candidatos),
            key=lambda item: item[0], reverse=True)
        pontos, melhor = pontuados[0]
        empate = len(pontuados) > 1 and pontuados[1][0] == pontos
        if pontos >= 2 and not empate:
            return {"status": "provavel", "aluno_id": melhor.id,
                    "aluno_nome": melhor.nome, "similaridade": 88.0,
                    "alternativas": alternativas}
    return {"status": "nao_encontrado", "alternativas": alternativas}


def casar_nomes(db: Session, escola_id: int, linhas: list[LinhaImportacao]) -> None:
    """Preenche `correspondencia` de cada linha comparando com os alunos ativos.

    * exato — nomes iguais ignorando acentos/caixa: importa direto.
    * provavel — parecido o suficiente: exige confirmação do usuário (§52).
    * nao_encontrado — o usuário decide entre criar o aluno ou ignorar a linha.
    """
    alunos = db.execute(
        select(Aluno).where(Aluno.escola_id == escola_id, Aluno.status == "ativo")
        .order_by(Aluno.id)  # ordem determinística ao desempatar homônimos
    ).scalars().all()
    indice = [(aluno, normalizar_nome(aluno.nome)) for aluno in alunos]

    # Turma atual de cada aluno (matrícula mais recente) — desempata abreviados
    turma_de: dict[int, str] = {}
    for aluno_id, nome_turma, ano_escolar in db.execute(
        select(Matricula.aluno_id, Turma.nome, Turma.ano_escolar)
        .join(Turma, Matricula.turma_id == Turma.id)
        .where(Matricula.escola_id == escola_id)
        .order_by(Matricula.ano_letivo)
    ).all():
        turma_de[aluno_id] = f"{nome_turma} {ano_escolar}"

    for linha in linhas:
        if not linha.nome:
            linha.correspondencia = {"status": "nao_encontrado", "alternativas": []}
            continue
        alvo = normalizar_nome(linha.nome)
        abreviada = _casar_abreviado(
            alvo, indice, linha.dados.get("turma_relatorio"), turma_de)
        if abreviada is not None:
            linha.correspondencia = abreviada
            continue
        pontuadas = sorted(
            ((aluno, _similaridade(alvo, nome_plano)) for aluno, nome_plano in indice),
            key=lambda par: par[1],
            reverse=True,
        )
        alternativas = [
            {"aluno_id": aluno.id, "nome": aluno.nome,
             "turma": turma_de.get(aluno.id, ""),
             "similaridade": round(nota * 100, 1)}
            for aluno, nota in pontuadas[:5]
            if nota >= LIMIAR_ALTERNATIVA
        ]
        # Homônimos: mais de um aluno com o MESMO nome completo. Não marcar
        # "exato" às cegas — desempata pela turma do relatório; sem desempate,
        # exige confirmação manual (§52) para nunca pontuar o aluno errado.
        exatos = [aluno for aluno, nome_plano in indice if nome_plano == alvo]
        if len(exatos) == 1:
            aluno = exatos[0]
            linha.correspondencia = {
                "status": "exato", "aluno_id": aluno.id, "aluno_nome": aluno.nome,
                "similaridade": 100.0, "alternativas": alternativas,
            }
        elif len(exatos) > 1:
            escolhido = _desempatar_por_turma(
                exatos, linha.dados.get("turma_relatorio"), turma_de)
            if escolhido is not None:
                linha.correspondencia = {
                    "status": "provavel", "aluno_id": escolhido.id,
                    "aluno_nome": escolhido.nome, "similaridade": 100.0,
                    "alternativas": alternativas,
                }
            else:
                # empate sem pista de turma: o usuário decide entre os homônimos
                linha.correspondencia = {
                    "status": "nao_encontrado", "alternativas": alternativas}
        elif pontuadas and pontuadas[0][1] >= LIMIAR_PROVAVEL:
            aluno, nota = pontuadas[0]
            linha.correspondencia = {
                "status": "provavel", "aluno_id": aluno.id, "aluno_nome": aluno.nome,
                "similaridade": round(nota * 100, 1), "alternativas": alternativas,
            }
        else:
            linha.correspondencia = {"status": "nao_encontrado", "alternativas": alternativas}
