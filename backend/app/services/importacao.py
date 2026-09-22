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

from sqlalchemy.orm import Session

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


def _int_api(v, ausente=0):
    """Inteiro tolerante (aceita int/float/str) — para os campos numéricos da API
    interna. Ausente/ilegível → ``ausente`` (passe ``None`` quando "não veio" NÃO
    pode virar 0 e sobrescrever um snapshot válido)."""
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return ausente


def _id_livro_elefante(valor) -> int | None:
    """``bookId`` da API como inteiro positivo; bool, fração, texto não numérico
    ou ausente → None (o importador cai no casamento por título+nível)."""
    if isinstance(valor, bool):
        return None
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    if isinstance(valor, str) and valor.strip().isdigit():
        valor = int(valor.strip())
    return valor if isinstance(valor, int) and valor > 0 else None


def _student_id_elefante(valor) -> str:
    """studentId do Elefante como texto estável ("12345"); "" se ausente/ilegível.
    Aceita int ou string numérica — nunca um id genérico de outro registro."""
    texto = str(valor if valor is not None else "").strip()
    if texto.endswith(".0"):
        texto = texto[:-2]
    return texto if texto.isdigit() and texto.strip("0") else ""


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
        # NUNCA filtra por data aqui (dropar por data global perderia a leitura
        # de um aluno novo/atrasado). A dedução do que é novo é por ALUNO, no
        # conector (pula quem não mudou); a UNIQUE de Leitura garante zero
        # duplicidade quando reprocessa.
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
            tempo_seg = _int_api(r.get("totalTimeSpent", r.get("tempo_livro_seg")), None)
            dados_l = {
                "livro": titulo,
                "nivel": str(r.get("levelName") or r.get("nivel") or "").strip(),
                "genero": str(r.get("genre") or r.get("theme") or r.get("genero") or "").strip(),
                "data": data_iso,
                # tempo do livro em MINUTOS (a API dá segundos em totalTimeSpent).
                "tempo_livro_min": round(tempo_seg / 60) if tempo_seg else None,
                "turma_relatorio": turma,
            }
            # IDENTIDADE OFICIAL do livro (bookId do catálogo do Elefante): o
            # importador casa por ela antes do título. Só inteiro válido entra.
            elefante_id = _id_livro_elefante(r.get("bookId"))
            if elefante_id is not None:
                dados_l["elefante_id"] = elefante_id
            # IDENTIDADE do ALUNO no Elefante (studentId): casa antes do nome e é
            # gravada no vínculo aluno↔plataforma na confirmação.
            sid = _student_id_elefante(r.get("studentId"))
            if sid:
                dados_l["elefante_student_id"] = sid
            linhas_l.append(LinhaImportacao(numero=i, nome=nome, dados=dados_l))
        return Analise(
            plataforma=plataforma, formato="leituras", estrategia="api-elefante",
            mensagem_deteccao="Histórico de leitura por aluno (API Elefante Letrado).",
            linhas=linhas_l, turma_detectada=turma, escola_detectada=escola,
            professor_detectado=professor)

    alunos = payload.get("students")
    linhas: list[LinhaImportacao] = []
    ausentes: dict[str, int] = {}
    for i, al in enumerate(alunos or [], start=1):
        if not isinstance(al, dict):
            continue
        nome = str(al.get("studentName") or "").strip()
        if not nome:
            continue
        # GUARDA DE SANIDADE: campo ausente/renomeado/ilegível na API NÃO vira 0 —
        # a chave simplesmente não entra em `dados`, e o importador do resumo
        # HERDA o valor do snapshot anterior ("presente vence; ausente herda").
        # Sem isto, uma mudança de nome de campo zerava a escola inteira.
        tempo_seg = _int_api(al.get("totalReadTime", al.get("readTime")), None)
        campos = {
            "livros_unicos": _int_api(al.get("totalBooksRead", al.get("qtdBooksRead")), None),
            "tempo_leitura_min": (round(tempo_seg / 60) if tempo_seg is not None else None),
            "questoes_tentativas": _int_api(al.get("responses"), None),
            "questoes_acertos": _int_api(al.get("approvedResponses"), None),
        }
        dados = {k: v for k, v in campos.items() if v is not None}
        for k, v in campos.items():
            if v is None:
                ausentes[k] = ausentes.get(k, 0) + 1
        # Desambigua HOMÔNIMOS na turma certa (mesmo campo que o parser de
        # PDF usa) — evita casar/duplicar aluno errado.
        dados["turma_relatorio"] = turma
        # IDENTIDADE do ALUNO no Elefante (studentId) — ver acima.
        sid = _student_id_elefante(al.get("studentId"))
        if sid:
            dados["elefante_student_id"] = sid
        linhas.append(LinhaImportacao(numero=i, nome=nome, dados=dados))
    erros_gerais = []
    if ausentes and linhas:
        erros_gerais.append(
            "Campos ausentes na resposta da API do Elefante ("
            + ", ".join(f"{k}: {n} aluno(s)" for k, n in sorted(ausentes.items()))
            + ") — valores anteriores preservados, nada foi zerado. Verifique o conector.")
    return Analise(
        plataforma=plataforma, formato="resumo", estrategia="api-elefante",
        mensagem_deteccao="Relatório de turma (API interna do Elefante Letrado).",
        linhas=linhas, erros_gerais=erros_gerais, turma_detectada=turma,
        escola_detectada=escola, professor_detectado=professor)


def analisar_matific_api(payload) -> Analise:
    """Placar da Escola pela API interna do Matific (school_student), já com o
    nome COMPLETO casado (via student-leaderboard) pelo conector. Uma turma por
    payload (o conector agrupa por ``klassName``), no MESMO formato do upload do
    Excel do Matific — reusa ``_importar_matific`` (atividades/estrelas/média).

    Mapeamento (campo da API → dado do snapshot):
      score               → estrelas (headline do ranking de matemática)
      activities_completed→ atividades
      score / atividades  → pontuacao_media (0–5; = "Pontuação média" da tela)
    """
    payload = payload if isinstance(payload, dict) else {}
    # O conector manda UMA turma por payload (``turma`` no topo); o upload do
    # bookmarklet manda a ESCOLA inteira (turma por aluno). Aceita os dois.
    turma_topo = str(payload.get("turma") or "").strip()
    linhas: list[LinhaImportacao] = []
    ausentes: dict[str, int] = {}
    for i, a in enumerate(payload.get("alunos") or [], start=1):
        if not isinstance(a, dict):
            continue
        nome = str(a.get("nome") or "").strip()
        if not nome:
            continue
        turma = turma_topo or str(a.get("turma") or "").strip()
        # GUARDA DE SANIDADE (mesma do Elefante): campo ausente/ilegível NÃO vira 0
        # — a chave não entra em `dados` e `_importar_matific` HERDA o snapshot
        # anterior ("presente vence; ausente herda"). Senão, um campo renomeado
        # no Placar zerava as estrelas/atividades da escola inteira.
        estrelas = _int_api(a.get("estrelas"), None)
        atividades = _int_api(a.get("atividades"), None)
        dados = {
            # Desambigua homônimos na turma certa (mesmo campo do Excel/PDF).
            "turma_relatorio": turma,
            # UUID do aluno no Matific: identidade estável p/ recasar e para
            # detectar mudança de turma com segurança (não muda de sala p/ sala).
            "matific_uuid": str(a.get("uuid") or "").strip(),
        }
        if atividades is not None:
            dados["atividades"] = atividades
        else:
            ausentes["atividades"] = ausentes.get("atividades", 0) + 1
        if estrelas is not None:
            dados["estrelas"] = estrelas
        else:
            ausentes["estrelas"] = ausentes.get("estrelas", 0) + 1
        if atividades is not None and estrelas is not None:
            # "Pontuação média" da tela = estrelas por atividade (0–5). Ex.: 3914/1082=3.62.
            dados["pontuacao_media"] = round(estrelas / atividades, 2) if atividades else 0.0
        linhas.append(LinhaImportacao(numero=i, nome=nome, dados=dados))
    erros_gerais = []
    if ausentes and linhas:
        erros_gerais.append(
            "Campos ausentes na resposta do Placar do Matific ("
            + ", ".join(f"{k}: {n} aluno(s)" for k, n in sorted(ausentes.items()))
            + ") — valores anteriores preservados, nada foi zerado. Verifique o conector.")
    # Período personalizado (start_date/end_date do Placar) → import POR PERÍODO
    # (premiação por semana/mês). Sem período, cai no import cumulativo.
    pi = str(payload.get("periodo_inicio") or "").strip()
    pf = str(payload.get("periodo_fim") or "").strip()
    msg = "Placar da Escola (API interna do Matific)."
    if pi and pf:
        msg = f"Placar do Matific no período {pi} a {pf} (API interna)."
    return Analise(
        plataforma="matific", formato="resumo", estrategia="api-matific",
        mensagem_deteccao=msg, linhas=linhas, erros_gerais=erros_gerais,
        turma_detectada=turma_topo, escola_detectada="", professor_detectado="",
        periodo_inicio=pi, periodo_fim=pf)


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

LIMIAR_ALTERNATIVA = 0.60   # parecido o bastante para ser OFERECIDO ao gestor


def _similaridade(a: str, b: str) -> float:
    direta = SequenceMatcher(None, a, b).ratio()
    tokens = SequenceMatcher(None, " ".join(sorted(a.split())), " ".join(sorted(b.split()))).ratio()
    return max(direta, tokens)


def _tokens_turma(texto: str) -> set[str]:
    """Tokens comparáveis de nome de turma: "5º Ano B" ≈ "5 ANO B MANHA".

    O ordinal (º/ª/°) é trocado por ESPAÇO (não removido): sem isso "4ºC" colava
    em "4c" (um token só) e NUNCA sobrepunha "4 ANO C INTEGRAL" ({4,ano,c,...}) —
    o overlap dava 0 e a importação criava uma turma-fantasma paralela (e rebaixava
    o casamento do aluno certo). Alinhado com matriculas.chave_canonica, que já
    troca º por espaço."""
    plano = normalizar_nome(re.sub(r"[ºª°]", " ", texto or ""))
    return {t for t in plano.split() if t}


# Expostos para o casamento da Lista Piloto (import de matrículas).
def tokens_turma(texto: str) -> set[str]:
    return _tokens_turma(texto)


def tokens_nome(nome: str) -> list[str]:
    """Tokens normalizados, SEM pontuação por token: "M. EDUARDA" → ["m","eduarda"]
    (o ponto da inicial abreviada não pode virar parte do token, senão "m." nunca
    casaria o prefixo de "maria")."""
    saida: list[str] = []
    for t in normalizar_nome(nome or "").split():
        limpo = "".join(c for c in t if c.isalnum())
        if limpo:
            saida.append(limpo)
    return saida


def chave_nome(nome: str) -> str:
    """A definição ÚNICA de "mesmo nome" de aluno: sem acento, sem caixa, espaços
    colapsados e SEM pontuação — "HELOISA* DE SOUZA", "Heloísa de  Souza" e
    "HELOISA DE SOUZA." dão a mesma chave. Toda comparação de igualdade de nome de
    aluno (prévia, confirmação, sincronização, Lista Piloto, cursor da sync) usa
    esta função; ``normalizar_nome`` sozinho mantém a pontuação e NÃO serve para
    decidir identidade."""
    return " ".join(tokens_nome(nome))


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


def casa_abreviado(curto: list[str], longo: list[str]) -> bool:
    """`curto` é uma abreviação POSICIONAL de `longo` (mesma pessoa)? Generaliza
    ``casa_abreviado_posicional`` para os casos que faltavam na spec do dono:
      • inicial no PRIMEIRO nome ("M. EDUARDA" → "MARIA EDUARDA SILVA");
      • truncamento de token cheio ("MARIA EDU" → "MARIA EDUARDA …");
      • inicial em qualquer posição ("ABRAAO L" → "ABRAÃO LUÍS DIAS").
    Continua POSICIONAL (curto[i] alinha com longo[i]) — nunca subsequência solta —
    e exige uma ÂNCORA: pelo menos um token cheio IDÊNTICO por posição. Sem âncora
    ("M S" → "MARIA SILVA", só iniciais) NÃO casa: seria loose demais e casaria
    crianças diferentes. `longo` precisa ser mais informativo (nome idêntico segue
    pelo caminho exato)."""
    if len(curto) < 2 or len(curto) > len(longo):
        return False
    cheios_iguais = 0                             # âncora: token cheio idêntico
    abreviados = 0                                # inicial ou truncamento (abreviação real)
    for i in range(len(curto)):
        c, l = curto[i], longo[i]
        if c == l:
            cheios_iguais += 1
        elif l.startswith(c):                     # inicial (1 char) OU truncamento (>=2)
            abreviados += 1
        else:
            return False
    # Precisa de ÂNCORA (>=1 token cheio idêntico) E de ao menos UMA abreviação real.
    # Um PREFIXO puro de tokens cheios ("JOAO SANTOS" ⊂ "JOAO SANTOS OLIVEIRA") NÃO é
    # abreviação — é nome parcial; sem `abreviados>=1` ele cai no ramo de subconjunto
    # (→ "media"/revisão), nunca em auto-vínculo (o dono real do sobrenome que falta
    # pode estar fora do roster).
    return cheios_iguais >= 1 and abreviados >= 1


def variante_ortografica(a_tokens: list[str], b_tokens: list[str]) -> bool:
    """Os dois nomes são a MESMA pessoa escrita com pequena variação ortográfica?
    Mesmo nº de tokens, mesmo 1º nome, e os tokens que diferem são MUITO próximos
    (ex.: LUÍS↔LUIZ, ratio 0.75) — NÃO aceita troca real de nome (LUÍS↔LUCAS,
    ratio 0.44). Estrito de propósito: separa variante de homônimo diferente."""
    if len(a_tokens) != len(b_tokens) or not a_tokens:
        return False
    if a_tokens[0] != b_tokens[0]:
        return False
    diferentes = 0
    for ta, tb in zip(a_tokens, b_tokens):
        if ta == tb:
            continue
        if _similaridade(ta, tb) < 0.7:          # token trocado de verdade
            return False
        diferentes += 1
    return 1 <= diferentes <= 2


def casar_nomes(db: Session, escola_id: int, linhas: list[LinhaImportacao], *,
                plataforma: str | None = None, turma_padrao: str = "") -> None:
    """PRÉVIA = CONFIRMAÇÃO. Preenche ``correspondencia`` de cada linha com a decisão
    da PORTA ÚNICA de identidade (``identidade_aluno.decidir``) — exatamente o
    cálculo que o /confirmar e a sincronização automática farão com a linha:

      * "exato"      — identidade externa já vinculada, RA, ou nome idêntico na sala;
      * "vinculado"  — candidato ÚNICO seguro na sala (abreviação, nome parcial
        estrutural, grafia segura, identificador corroborando);
      * "revisar"    — há candidato, nenhum seguro: a confirmação NÃO associa e NÃO
        cria — a linha vai para a fila de revisão de identidade;
      * "bloqueado"  — o nome casava, mas a identidade prova ser outra criança (cria);
      * "nao_encontrado" — nenhum candidato: a confirmação cria a ficha.

    ``via`` diz COMO casou (identidade|exato|ra|abreviacao|parcial|…) e
    ``alternativas`` lista os candidatos que o gestor pode escolher explicitamente.
    ``turma_padrao``: turma do cabeçalho do relatório (quando a linha não traz a sua).
    """
    from app.services import identidade_aluno as ida

    ctx = ida.carregar_contexto(db, escola_id)
    ativos = [a for a in ctx.alunos.values() if a.status == "ativo"]
    for linha in linhas:
        dados = linha.dados or {}
        ident = ida.linha_de_dados(
            linha.nome, dados, plataforma=plataforma,
            turma_nome=str(dados.get("turma_relatorio") or turma_padrao or ""))
        linha.correspondencia = _correspondencia(
            ctx, ida.decidir(ctx, ident), linha.nome, ativos)


def _alternativas(ctx, ids, nome: str) -> list[dict]:
    from app.services import identidade_aluno as ida
    alvo = chave_nome(nome)
    return [{"aluno_id": c["aluno_id"], "nome": c["nome"], "turma": c["turma"] or "",
             "status": c["status"],
             "similaridade": round(_similaridade(alvo, chave_nome(c["nome"])) * 100, 1)}
            for c in ida.descrever_candidatos(ctx, ids)]


def _correspondencia(ctx, decisao, nome: str, ativos) -> dict:
    from app.services import identidade_aluno as ida

    alternativas = _alternativas(ctx, decisao.candidatos, nome)
    if decisao.acao == ida.ASSOCIAR:
        aluno = ctx.alunos[decisao.aluno_id]
        forte = decisao.via in ("identidade", "exato", "ra", "revisao", "explicito")
        return {"status": "exato" if forte else "vinculado", "via": decisao.via,
                "motivo": decisao.via, "aluno_id": aluno.id, "aluno_nome": aluno.nome,
                "similaridade": 100.0, "alternativas": alternativas}
    if decisao.acao == ida.REVISAR:
        sugerido = ctx.alunos.get(decisao.aluno_id) if decisao.aluno_id else None
        return {"status": "revisar", "via": decisao.via, "motivo": decisao.motivo,
                "aluno_id": sugerido.id if sugerido else None,
                "aluno_nome": sugerido.nome if sugerido else None,
                "similaridade": 90.0 if sugerido else None,
                "alternativas": alternativas}
    # CRIAR: nenhum candidato plausível. Nomes só PARECIDOS continuam oferecidos
    # (o gestor pode escolher um explicitamente), mas nada é pré-selecionado.
    alvo = chave_nome(nome)
    parecidos = sorted(
        ((a, _similaridade(alvo, chave_nome(a.nome))) for a in ativos),
        key=lambda par: (-par[1], par[0].id))
    difusas = [{"aluno_id": a.id, "nome": a.nome,
                "turma": (ctx.turma_do_aluno(a.id).nome if ctx.turma_do_aluno(a.id) else ""),
                "status": a.status, "similaridade": round(nota * 100, 1)}
               for a, nota in parecidos[:5] if nota >= LIMIAR_ALTERNATIVA]
    return {"status": "bloqueado" if decisao.vetados else "nao_encontrado",
            "motivo": "conflito" if decisao.vetados else "novo",
            "alternativas": difusas}
