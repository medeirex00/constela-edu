"""Análise de relatórios das plataformas (PRD §15–§16, §50–§52).

O fluxo é sempre em duas etapas:
  1. `analisar` — interpreta o texto (ou PDF) e devolve uma prévia com todos
     os erros e correspondências de nomes, sem gravar nada (PRD §51).
  2. `confirmar` (no router) — grava apenas o que o usuário aprovou.

Nota importante: os formatos aceitos foram definidos SEM amostras reais dos
relatórios da Matific e do Elefante Letrado (pré-requisito da Fase 2 no
ROADMAP). Por isso o parser é deliberadamente tolerante — cabeçalho com
sinônimos, separadores variados (tab, `;`, `,` ou colunas de espaços) e
números em formato pt-BR — e NADA entra no banco sem prévia aprovada.
Quando as amostras reais chegarem, basta ajustar os sinônimos de coluna.
"""
from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Aluno

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


def _niveis(celula: str) -> dict[str, int]:
    """Interpreta 'AA:2, D:1' (ou 'AA=2; D=1') como {"AA": 2, "D": 1}."""
    pares = re.findall(r"([A-Za-z]{1,2})\s*[:=]\s*(\d+)", celula)
    if not pares and celula.strip():
        raise ValueError(f"níveis ilegíveis: {celula!r}")
    return {codigo.upper(): int(qtd) for codigo, qtd in pares}


# --------------------------------------------------------------------------
# Detecção de plataforma e formato (PRD §50)
# --------------------------------------------------------------------------

_PALAVRAS = {
    "matific": ["matific", "atividade", "estrela", "episodio", "pontuacao media"],
    "elefante": ["elefante", "letrado", "livro", "leitura", "questo", "nivel"],
}


def detectar_plataforma(texto: str) -> str | None:
    plano = normalizar_nome(texto)
    pontos = {p: sum(plano.count(k) for k in ks) for p, ks in _PALAVRAS.items()}
    if pontos["matific"] == pontos["elefante"]:
        return None
    return max(pontos, key=pontos.get)  # type: ignore[arg-type]


# Sinônimos aceitos em cabeçalhos (normalizados, comparação por prefixo)
_COL_NOME = ["nome do aluno", "nome", "aluno", "estudante"]

COLUNAS_MATIFIC = {
    "atividades": ["atividades finalizadas", "atividades concluidas", "atividades"],
    "pontuacao_media": ["pontuacao media", "media de pontuacao", "media", "pontuacao"],
    "estrelas": ["estrelas"],
}

COLUNAS_ELEFANTE_RESUMO = {
    "livros_unicos": ["livros lidos", "livros unicos", "livros concluidos", "livros"],
    "tempo_leitura_min": ["tempo de leitura", "tempo (min)", "tempo", "minutos"],
    "questoes_tentativas": ["questoes respondidas", "questoes", "tentativas"],
    "questoes_acertos": ["acertos", "respostas corretas", "questoes corretas"],
    "livros_por_nivel": ["livros por nivel", "niveis", "nivel dos livros"],
}

# Formato alternativo do Elefante: uma linha por livro concluído
COLUNAS_ELEFANTE_LEITURAS = {
    "livro": ["titulo do livro", "titulo", "livro"],
    "nivel": ["nivel do livro", "nivel", "codigo"],
}

_OBRIGATORIAS = {
    "matific": {"atividades"},
    "elefante_resumo": {"livros_unicos"},
    "elefante_leituras": {"livro"},
}


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
    linhas: list[LinhaImportacao] = field(default_factory=list)
    erros_gerais: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Leitura de tabelas em texto livre
# --------------------------------------------------------------------------

def _dividir(linha: str, separador: str) -> list[str]:
    if separador == "espacos":
        return [c.strip() for c in re.split(r"\s{2,}", linha.strip()) if c.strip()]
    return [c.strip() for c in linha.split(separador)]


def _detectar_separador(linhas: list[str]) -> str:
    corpo = "\n".join(linhas)
    if "\t" in corpo:
        return "\t"
    if ";" in corpo:
        return ";"
    if re.search(r"\S\s{2,}\S", corpo):
        return "espacos"
    return ","


def _mapear_cabecalho(celulas: list[str], colunas: dict[str, list[str]]) -> tuple[int | None, dict[str, int]]:
    """Retorna (índice da coluna de nome, {campo: índice}) para um cabeçalho."""
    idx_nome = None
    mapa: dict[str, int] = {}
    for indice, celula in enumerate(celulas):
        plano = normalizar_nome(celula)
        if idx_nome is None and any(plano.startswith(s) for s in _COL_NOME):
            idx_nome = indice
            continue
        for campo, sinonimos in colunas.items():
            if campo not in mapa and any(plano.startswith(s) for s in sinonimos):
                mapa[campo] = indice
                break
    return idx_nome, mapa


def _escolher_formato(plataforma: str, celulas: list[str]) -> tuple[str, dict[str, int], int | None]:
    """Tenta os formatos conhecidos da plataforma no cabeçalho dado."""
    candidatos = (
        [("resumo", COLUNAS_MATIFIC)]
        if plataforma == "matific"
        else [("leituras", COLUNAS_ELEFANTE_LEITURAS), ("resumo", COLUNAS_ELEFANTE_RESUMO)]
    )
    melhor = ("", {}, None, -1)
    for formato, colunas in candidatos:
        idx_nome, mapa = _mapear_cabecalho(celulas, colunas)
        chave = "elefante_" + formato if plataforma == "elefante" else "matific"
        if idx_nome is None or not (_OBRIGATORIAS[chave] & set(mapa)):
            continue
        if len(mapa) > melhor[3]:
            melhor = (formato, mapa, idx_nome, len(mapa))
    return melhor[0], melhor[1], melhor[2]


_RODAPES = ("total", "media", "pagina", "gerado em", "relatorio")


def analisar_texto(texto: str, plataforma: str | None = None) -> Analise:
    """Interpreta um relatório colado/extraído. Nunca grava nada."""
    plataforma = plataforma or detectar_plataforma(texto)
    if plataforma is None:
        analise = Analise(plataforma="", formato="")
        analise.erros_gerais.append(
            "Não foi possível identificar a plataforma automaticamente. "
            "Selecione Matific ou Elefante Letrado e tente novamente."
        )
        return analise

    linhas_texto = [l for l in texto.splitlines() if l.strip()]
    separador = _detectar_separador(linhas_texto)

    formato, mapa, idx_nome, inicio = "", {}, None, 0
    for indice, linha in enumerate(linhas_texto):
        formato, mapa, idx_nome = _escolher_formato(plataforma, _dividir(linha, separador))
        if formato:
            inicio = indice + 1
            break

    analise = Analise(plataforma=plataforma, formato=formato)
    if not formato:
        analise.erros_gerais.append(
            "Cabeçalho não reconhecido. O relatório precisa ter uma coluna de "
            "nome do aluno e as colunas de dados da plataforma."
        )
        return analise

    for numero, linha in enumerate(linhas_texto[inicio:], start=inicio + 1):
        celulas = _dividir(linha, separador)
        plano = normalizar_nome(linha)
        if any(plano.startswith(r) for r in _RODAPES):
            continue
        if idx_nome >= len(celulas) or not celulas[idx_nome]:
            analise.linhas.append(
                LinhaImportacao(numero=numero, nome="", dados={},
                                erros=["Linha sem nome de aluno."])
            )
            continue

        item = LinhaImportacao(numero=numero, nome=celulas[idx_nome], dados={})
        for campo, indice_coluna in mapa.items():
            if indice_coluna >= len(celulas) or not celulas[indice_coluna].strip():
                continue
            bruto = celulas[indice_coluna]
            try:
                if campo == "livros_por_nivel":
                    item.dados[campo] = _niveis(bruto)
                elif campo in ("livro", "nivel"):
                    item.dados[campo] = bruto.strip().upper() if campo == "nivel" else bruto.strip()
                else:
                    valor = _numero(bruto)
                    if valor < 0:
                        raise ValueError("valor negativo")
                    item.dados[campo] = valor
            except ValueError:
                item.erros.append(f"Valor inválido em “{campo}”: {bruto!r}.")
        analise.linhas.append(item)

    if not analise.linhas:
        analise.erros_gerais.append("Nenhuma linha de dados encontrada após o cabeçalho.")
    return analise


# --------------------------------------------------------------------------
# Extração de texto de PDF
# --------------------------------------------------------------------------

def extrair_texto_pdf(conteudo: bytes) -> str:
    from pypdf import PdfReader

    leitor = PdfReader(io.BytesIO(conteudo))
    return "\n".join(pagina.extract_text() or "" for pagina in leitor.pages)


# --------------------------------------------------------------------------
# Correspondência inteligente de nomes (PRD §52)
# --------------------------------------------------------------------------

LIMIAR_PROVAVEL = 0.80   # abaixo disso não sugerimos automaticamente
LIMIAR_ALTERNATIVA = 0.60


def _similaridade(a: str, b: str) -> float:
    direta = SequenceMatcher(None, a, b).ratio()
    tokens = SequenceMatcher(None, " ".join(sorted(a.split())), " ".join(sorted(b.split()))).ratio()
    return max(direta, tokens)


def casar_nomes(db: Session, escola_id: int, linhas: list[LinhaImportacao]) -> None:
    """Preenche `correspondencia` de cada linha comparando com os alunos ativos.

    * exato — nomes iguais ignorando acentos/caixa: importa direto.
    * provavel — parecido o suficiente: exige confirmação do usuário (§52).
    * nao_encontrado — o usuário decide entre criar o aluno ou ignorar a linha.
    """
    alunos = db.execute(
        select(Aluno).where(Aluno.escola_id == escola_id, Aluno.status == "ativo")
    ).scalars().all()
    indice = [(aluno, normalizar_nome(aluno.nome)) for aluno in alunos]

    for linha in linhas:
        if not linha.nome:
            linha.correspondencia = {"status": "nao_encontrado", "alternativas": []}
            continue
        alvo = normalizar_nome(linha.nome)
        pontuadas = sorted(
            ((aluno, _similaridade(alvo, nome_plano)) for aluno, nome_plano in indice),
            key=lambda par: par[1],
            reverse=True,
        )
        alternativas = [
            {"aluno_id": aluno.id, "nome": aluno.nome, "similaridade": round(nota * 100, 1)}
            for aluno, nota in pontuadas[:3]
            if nota >= LIMIAR_ALTERNATIVA
        ]
        if pontuadas and normalizar_nome(pontuadas[0][0].nome) == alvo:
            aluno = pontuadas[0][0]
            linha.correspondencia = {
                "status": "exato", "aluno_id": aluno.id, "aluno_nome": aluno.nome,
                "similaridade": 100.0, "alternativas": alternativas,
            }
        elif pontuadas and pontuadas[0][1] >= LIMIAR_PROVAVEL:
            aluno, nota = pontuadas[0]
            linha.correspondencia = {
                "status": "provavel", "aluno_id": aluno.id, "aluno_nome": aluno.nome,
                "similaridade": round(nota * 100, 1), "alternativas": alternativas,
            }
        else:
            linha.correspondencia = {"status": "nao_encontrado", "alternativas": alternativas}
