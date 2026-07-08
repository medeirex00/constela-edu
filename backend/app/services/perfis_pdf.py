"""Perfis de relatório PDF — leitura POSICIONAL dos formatos reais.

As estratégias genéricas de `importacao.py` trabalham com texto corrido e
resolvem relatórios colados ou PDFs simples. Os PDFs REAIS do Elefante
Letrado e do Matific, porém, têm layout complexo: nomes quebrados em até
4 linhas, durações fatiadas ("42h" / "09min" / "01s"), cabeçalhos que se
repetem a cada página e títulos de livro que contêm palavras como "Nível".

Nada disso é recuperável com heurísticas de texto. Este módulo lê as
COORDENADAS de cada palavra (pdfplumber) e reconstrói as tabelas:

    palavras com posição (x0, topo)
        │
        ├─ detecção do PERFIL pelo texto compactado (sem espaços/acentos)
        │     "relatoriodeperformancedaturma"     → Elefante · turma
        │     "relatoriodeperformancedoestudante" → Elefante · estudante
        │     "matific" / "atividadesfinalizadas" → Matific
        │
        ├─ cabeçalho: agrupa rótulos por x0 e casa por SEMELHANÇA
        │   (a posição do cabeçalho vira o mapa de colunas da página)
        ├─ registros: linha que preenche várias colunas INICIA um registro;
        │   fragmentos (sobrenomes, "34min", turma quebrada) são costurados
        │   ao registro vizinho pela coluna em que caem
        └─ conversões tolerantes: duração → minutos, número pt-BR, datas

Se nenhum perfil reconhecer o arquivo (formato futuro, plataforma nova),
o fluxo cai automaticamente nas 4 estratégias genéricas — o usuário nunca
fica sem resposta.
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from datetime import timedelta

from app.services.importacao import (
    Analise,
    LinhaImportacao,
    _casar_coluna,
    _eh_coluna_nome,
    _fechar_linha,
    _numero,
    _similaridade,
    normalizar_nome,
)

# --------------------------------------------------------------------------
# Extração de palavras com posição
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Palavra:
    texto: str
    x0: float
    x1: float
    topo: float


@dataclass
class Pagina:
    numero: int
    palavras: list[Palavra]


def extrair_paginas(conteudo: bytes) -> list[Pagina]:
    """Palavras de cada página com coordenadas (pdfplumber)."""
    import pdfplumber

    # PDFs do Elefante têm fontes sem FontBBox — o aviso não interessa aqui
    logging.getLogger("pdfminer").setLevel(logging.ERROR)

    paginas: list[Pagina] = []
    with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
        for numero, pagina in enumerate(pdf.pages, start=1):
            palavras = [
                Palavra(p["text"], float(p["x0"]), float(p["x1"]), float(p["top"]))
                for p in pagina.extract_words(x_tolerance=2.5)
            ]
            paginas.append(Pagina(numero=numero, palavras=palavras))
    return paginas


def compactar(texto: str) -> str:
    """Normaliza e remove TODO espaço — imune ao espaçamento intra-letra
    que esses PDFs produzem ("Re la tó rio" → "relatorio")."""
    return normalizar_nome(texto).replace(" ", "")


# --------------------------------------------------------------------------
# Conversões tolerantes
# --------------------------------------------------------------------------

_RE_RELOGIO = re.compile(r"^(\d+):([0-5]?\d)(?::([0-5]?\d))?$")
_RE_DATA = re.compile(r"^([0-3]?\d)/([01]?\d)/(\d{4})$")


def duracao_em_minutos(bruto: str) -> int:
    """Aceita "19:40:02", "0:06:04", "42 h 09 min 01 s", "00 s" → minutos."""
    plano = normalizar_nome(bruto)
    relogio = _RE_RELOGIO.match(plano.replace(" ", ""))
    if relogio:
        horas, minutos, segundos = (int(g or 0) for g in relogio.groups())
        return round(horas * 60 + minutos + segundos / 60)
    horas = re.search(r"(\d+)\s*h(?![a-z0-9])", plano)
    minutos_m = re.search(r"(\d+)\s*min", plano)
    segundos_m = re.search(r"(\d+)\s*s(?![a-z0-9])", plano)
    if not (horas or minutos_m or segundos_m):
        raise ValueError(f"duração ilegível: {bruto!r}")
    total = ((int(horas.group(1)) * 60 if horas else 0)
             + (int(minutos_m.group(1)) if minutos_m else 0)
             + (int(segundos_m.group(1)) / 60 if segundos_m else 0))
    return round(total)


def _data_iso(bruto: str) -> str:
    par = _RE_DATA.match(bruto.strip())
    if not par:
        raise ValueError(f"data ilegível: {bruto!r}")
    dia, mes, ano = par.groups()
    return f"{ano}-{int(mes):02d}-{int(dia):02d}"


def _data_hora_iso(par: tuple[str, str | None]) -> str:
    """Combina "DD/MM/AAAA" com um horário "HH:MM:SS" opcional → ISO datetime.
    Sem horário, devolve só a data (o import grava à meia-noite). O relatório
    individual do Elefante traz data e hora empilhadas na coluna "Data/Hora"."""
    data_str, hora_str = par
    dia_iso = _data_iso(data_str)  # "AAAA-MM-DD"
    if hora_str:
        rel = _RE_RELOGIO.match(hora_str.strip())
        if rel:
            h, m, s = (int(g or 0) for g in rel.groups())
            return f"{dia_iso}T{h:02d}:{m:02d}:{s:02d}"
    return dia_iso


# --------------------------------------------------------------------------
# Linhas visuais e colunas
# --------------------------------------------------------------------------

TOLERANCIA_LINHA = 4.0   # unidades ("min", "s") ficam ~3,3pt abaixo do número
TOLERANCIA_COLUNA = 3.0  # rótulos empilhados do cabeçalho compartilham o x0


@dataclass
class LinhaVisual:
    topo: float
    palavras: list[Palavra] = field(default_factory=list)

    @property
    def texto(self) -> str:
        return " ".join(p.texto for p in sorted(self.palavras, key=lambda p: p.x0))


def _linhas_visuais(palavras: list[Palavra]) -> list[LinhaVisual]:
    linhas: list[LinhaVisual] = []
    for palavra in sorted(palavras, key=lambda p: (p.topo, p.x0)):
        if linhas and palavra.topo - linhas[-1].topo <= TOLERANCIA_LINHA:
            linhas[-1].palavras.append(palavra)
        else:
            linhas.append(LinhaVisual(topo=palavra.topo, palavras=[palavra]))
    return linhas


@dataclass
class Coluna:
    campo: str
    x0: float
    x_min: float = float("-inf")
    x_max: float = float("inf")


def _delimitar(colunas: list[Coluna]) -> list[Coluna]:
    """Fronteira entre colunas = âncora da coluna seguinte (dados alinhados
    à esquerda: tudo que começa antes da próxima âncora pertence à atual)."""
    ordenadas = sorted(colunas, key=lambda c: c.x0)
    for anterior, atual in zip(ordenadas, ordenadas[1:]):
        anterior.x_max = atual.x0 - 2.0
        atual.x_min = atual.x0 - 2.0
    return ordenadas


def _coluna_de(colunas: list[Coluna], palavra: Palavra) -> Coluna | None:
    for coluna in colunas:
        if coluna.x_min <= palavra.x0 < coluna.x_max:
            return coluna
    return None


# --------------------------------------------------------------------------
# Cabeçalhos: detecção por vocabulário e mapa de colunas por x0
# --------------------------------------------------------------------------

def _vocabulario(colunas_def: dict[str, list[str]], com_nome: bool) -> set[str]:
    """Todos os tokens que podem aparecer num cabeçalho deste perfil."""
    tokens: set[str] = set()
    sinonimos = [s for lista in colunas_def.values() for s in lista]
    if com_nome:
        sinonimos += ["nome do estudante", "nome do aluno", "aluno", "estudante"]
    for sinonimo in sinonimos:
        tokens.update(compactar(t) for t in sinonimo.split())
    return tokens


def _forca_cabecalho(linha: LinhaVisual, vocabulario: set[str]) -> str | None:
    """'forte' = linha claramente de cabeçalho; 'fraca' = só conectivos
    ("de", "do") — vale apenas colada a uma linha forte."""
    tokens = [compactar(p.texto) for p in linha.palavras]
    tokens = [t for t in tokens if t]
    if not tokens or any(any(c.isdigit() for c in t) for t in tokens):
        return None
    no_vocab = sum(1 for t in tokens if t in vocabulario)
    if no_vocab == len(tokens) and all(len(t) < 4 for t in tokens):
        return "fraca"
    if no_vocab / len(tokens) >= 0.6 and any(
            t in vocabulario and len(t) >= 4 for t in tokens):
        return "forte"
    return None


def _mapear_bloco(linhas_bloco: list[LinhaVisual],
                  colunas_def: dict[str, list[str]],
                  com_nome: bool) -> list[Coluna]:
    """Agrupa as palavras do bloco por x0; cada grupo vira um rótulo
    ("Leituras" + "Concluídas" empilhados = "Leituras Concluídas")."""
    palavras = [p for linha in linhas_bloco for p in linha.palavras]
    grupos: list[list[Palavra]] = []
    for palavra in sorted(palavras, key=lambda p: p.x0):
        if grupos and palavra.x0 - grupos[-1][0].x0 <= TOLERANCIA_COLUNA:
            grupos[-1].append(palavra)
        else:
            grupos.append([palavra])

    colunas: list[Coluna] = []
    mapeados: set[str] = set()
    for grupo in grupos:
        rotulo = " ".join(p.texto for p in sorted(grupo, key=lambda p: (p.topo, p.x0)))
        x0 = grupo[0].x0
        if com_nome and "nome" not in mapeados and _eh_coluna_nome(rotulo):
            colunas.append(Coluna(campo="nome", x0=x0))
            mapeados.add("nome")
            continue
        campo = _casar_coluna(rotulo, colunas_def, ignorar=mapeados)
        if campo:
            colunas.append(Coluna(campo=campo, x0=x0))
            mapeados.add(campo)
    return colunas


# --------------------------------------------------------------------------
# Tabela posicional: registros iniciados e costurados por coluna
# --------------------------------------------------------------------------

@dataclass
class Registro:
    topo: float
    campos: dict[str, list[Palavra]] = field(default_factory=dict)

    def texto(self, campo: str) -> str:
        palavras = sorted(self.campos.get(campo, []), key=lambda p: (p.topo, p.x0))
        return " ".join(p.texto for p in palavras).strip()


def _tabela_posicional(
    paginas: list[Pagina],
    colunas_def: dict[str, list[str]],
    *,
    com_nome: bool,
    aceitar_cabecalho,
    inicia_registro,
    ignorar_linha=None,
    anexo_por_proximidade: bool = False,
) -> list[Registro]:
    """Motor comum dos perfis: encontra cabeçalhos, delimita colunas e
    costura registros de várias linhas. O mapa de colunas persiste entre
    páginas — relatórios que só imprimem o cabeçalho uma vez também funcionam.
    """
    vocab = _vocabulario(colunas_def, com_nome)
    colunas: list[Coluna] | None = None
    registros: list[Registro] = []
    inicio_pagina = 0                      # `topo` é relativo à página: um
    orfas: list[LinhaVisual] = []          # fragmento só casa com registros
                                           # da MESMA página

    def _so_coluna_nome(linha: LinhaVisual) -> bool:
        """Fragmento que cai INTEIRO na coluna 'nome' e não tem dígitos — é um
        pedaço de nome quebrado (sobrenome numa 3ª linha), não turma/dado."""
        if colunas is None or not linha.palavras:
            return False
        for palavra in linha.palavras:
            coluna = _coluna_de(colunas, palavra)
            if coluna is None or coluna.campo != "nome" or any(c.isdigit() for c in palavra.texto):
                return False
        return True

    def _fechar_orfas() -> None:
        """Anexa cada fragmento ao registro mais próximo verticalmente.

        O nome do aluno pode quebrar em 3 linhas visuais (o registro nasce na
        do meio): as pontas ficam a ~1 altura de linha (~16pt), acima do limiar
        de 12pt usado para a turma fatiada. Fragmentos que caem só na coluna
        'nome' ganham um limiar maior — sem alcançar a próxima linha de dados
        (~23pt adiante), então não invadem o registro vizinho."""
        da_pagina = registros[inicio_pagina:]
        for linha in orfas:
            vizinho = min(da_pagina, key=lambda r: abs(r.topo - linha.topo),
                          default=None)
            limite = 18.0 if _so_coluna_nome(linha) else 12.0
            if vizinho is not None and abs(vizinho.topo - linha.topo) <= limite:
                _depositar(vizinho, linha)
        orfas.clear()

    def _depositar(registro: Registro, linha: LinhaVisual) -> None:
        for palavra in linha.palavras:
            coluna = _coluna_de(colunas, palavra)
            if coluna is not None:
                registro.campos.setdefault(coluna.campo, []).append(palavra)

    for pagina in paginas:
        inicio_pagina = len(registros)
        linhas = _linhas_visuais(pagina.palavras)
        forcas = [_forca_cabecalho(linha, vocab) for linha in linhas]
        registro_atual: Registro | None = None

        indice = 0
        while indice < len(linhas):
            # Bloco de cabeçalho: sequência com ao menos uma linha "forte"
            if forcas[indice] is not None:
                fim = indice
                while fim < len(linhas) and forcas[fim] is not None:
                    fim += 1
                bloco = linhas[indice:fim]
                if any(forcas[i] == "forte" for i in range(indice, fim)):
                    mapeadas = _mapear_bloco(bloco, colunas_def, com_nome)
                    if aceitar_cabecalho({c.campo for c in mapeadas}):
                        if anexo_por_proximidade:
                            _fechar_orfas()
                        colunas = _delimitar(mapeadas)
                        registro_atual = None
                        indice = fim
                        continue
                # Não era cabeçalho válido: trata as linhas como dados comuns
                indice_dados = indice
                indice = fim
                alcance = range(indice_dados, fim)
            else:
                alcance = range(indice, indice + 1)
                indice += 1

            for i in alcance:
                linha = linhas[i]
                if colunas is None:
                    continue  # dados antes do primeiro cabeçalho: resumo/capa
                if ignorar_linha is not None and ignorar_linha(linha):
                    continue
                presentes: dict[str, list[Palavra]] = {}
                for palavra in linha.palavras:
                    coluna = _coluna_de(colunas, palavra)
                    if coluna is not None:
                        presentes.setdefault(coluna.campo, []).append(palavra)
                if inicia_registro(presentes):
                    registro_atual = Registro(topo=linha.topo, campos={
                        campo: list(ps) for campo, ps in presentes.items()
                    })
                    registros.append(registro_atual)
                elif anexo_por_proximidade:
                    orfas.append(linha)
                elif registro_atual is not None:
                    _depositar(registro_atual, linha)
        if anexo_por_proximidade:
            _fechar_orfas()
    return registros


def _atribuir(item: LinhaImportacao, campo: str, bruto: str, conversor) -> None:
    """Conversão tolerante: falha vira aviso, nunca derruba a linha (§51)."""
    if not bruto:
        return
    try:
        item.dados[campo] = conversor(bruto)
    except (ValueError, TypeError):
        item.avisos.append(f"“{campo}” ilegível ({bruto!r}) — campo ficará ausente.")


def _inteiro(bruto: str) -> int:
    return int(_numero(bruto))


# --------------------------------------------------------------------------
# Perfil 1 — Elefante Letrado · relatório de performance da TURMA
# --------------------------------------------------------------------------

# Os campos de escuta (não pontuados) vêm ANTES dos de leitura para que
# "Livros Escutados" nunca seja capturado pelo sinônimo genérico "livros".
COLUNAS_PERFIL_TURMA = {
    "nivel": ["nivel"],
    "livros_escutados": ["livros escutados"],
    "tempo_escuta": ["tempo de escuta"],
    "livros_unicos": ["leituras concluidas", "livros lidos", "leituras"],
    "tempo_leitura_min": ["tempo de leitura"],
    "questoes_tentativas": ["questoes respondidas"],
    "questoes_acertos": ["questoes aprovadas"],
}

_CAMPOS_TURMA = {"livros_unicos", "tempo_leitura_min",
                 "questoes_tentativas", "questoes_acertos", "nivel"}


class PerfilElefanteTurma:
    plataforma = "elefante"
    formato = "resumo"
    estrategia = "perfil_elefante_turma"

    def detecta(self, compacto: str, nome_arquivo: str = "") -> bool:
        return ("performancedaturma" in compacto
                or "performancedaturma" in compactar(nome_arquivo)
                or ("habitodeleitura" in compacto and "nomedoestudante" in compacto))

    def analisar(self, paginas: list[Pagina], nome_arquivo: str = "") -> Analise:
        registros = _tabela_posicional(
            paginas, COLUNAS_PERFIL_TURMA, com_nome=True,
            aceitar_cabecalho=lambda campos: "nome" in campos
            and len(campos & _CAMPOS_TURMA) >= 3,
            inicia_registro=lambda presentes: "nome" in presentes
            and len(presentes) >= 4,
        )
        turma = _turma_da_capa(paginas)
        analise = Analise(plataforma=self.plataforma, formato=self.formato,
                          estrategia=self.estrategia, turma_detectada=turma,
                          mensagem_deteccao="Este arquivo pertence ao Elefante "
                          "Letrado — relatório de performance da turma"
                          + (f" ({turma})" if turma else "") + ".")
        for numero, registro in enumerate(registros, start=1):
            item = LinhaImportacao(numero=numero, nome=registro.texto("nome"),
                                   dados={})
            if turma:
                item.dados["turma_relatorio"] = turma
            _atribuir(item, "nivel", registro.texto("nivel"),
                      lambda b: _codigo_nivel(b))
            _atribuir(item, "livros_unicos", registro.texto("livros_unicos"), _inteiro)
            _atribuir(item, "tempo_leitura_min",
                      registro.texto("tempo_leitura_min"), duracao_em_minutos)
            _atribuir(item, "questoes_tentativas",
                      registro.texto("questoes_tentativas"), _inteiro)
            _atribuir(item, "questoes_acertos",
                      registro.texto("questoes_acertos"), _inteiro)
            analise.linhas.append(_fechar_linha(item))
        return analise


def _codigo_nivel(bruto: str) -> str:
    codigo = bruto.strip().upper()
    if not re.fullmatch(r"[A-Z]{1,2}", codigo):
        raise ValueError(f"nível ilegível: {bruto!r}")
    return codigo


def _turma_da_capa(paginas: list[Pagina]) -> str:
    """Nome da turma na capa: linha logo após a do intervalo de datas."""
    if not paginas:
        return ""
    linhas = _linhas_visuais(paginas[0].palavras)
    for indice, linha in enumerate(linhas[:6]):
        if re.search(r"\d{2}/\d{2}/\d{4}", linha.texto) and indice + 1 < len(linhas):
            turma = linhas[indice + 1].texto.strip()
            if 0 < len(turma) <= 60:
                return turma
    return ""


# --------------------------------------------------------------------------
# Perfil 2 — Elefante Letrado · relatório individual do ESTUDANTE
# --------------------------------------------------------------------------

COLUNAS_PERFIL_ESTUDANTE = {
    "livro": ["titulo do livro", "titulo"],
    "nivel": ["nivel"],
    "genero": ["genero textual"],
    "tempo": ["tempo de leitura"],
    "data": ["data/hora", "data hora", "data"],
}

# Rótulos de seção do cabeçalho — nunca são nome do aluno nem turma.
_ROTULOS_SECAO = ("habitodeleitura", "leiturasconcluidas", "tempodeleitura",
                  "historicodelivroslidos", "compreensaoleitora",
                  "livrosescutados", "tempodeescuta")

# Prefixos de legenda/decoração que NUNCA são nome de aluno (imagens, logos...).
_PREFIXOS_LIXO = ("imagem", "figura", "foto", "logotipo", "logo", "marca",
                  "icone", "banner", "grafico", "captura", "screenshot")

# Nome do aluno no NOME DO ARQUIVO — fonte preferencial, pois o Elefante
# exporta "Relatório de performance do estudante - NOME DO ALUNO.pdf".
_RE_NOME_ARQUIVO = re.compile(
    r"(?:performance|desempenho)\s+d[oe]\s+(?:estudante|aluno)\s*[-–—:]\s*(.+)$",
    re.IGNORECASE,
)


def _parece_nome_pessoa(nome: str) -> bool:
    """≥2 palavras, essencialmente alfabético e sem cara de legenda/rótulo."""
    limpo = (nome or "").strip()
    if len(limpo) < 3 or len(limpo) > 80 or len(limpo.split()) < 2:
        return False
    plano = compactar(limpo)
    # Rejeita legenda de imagem/logo pelo PRIMEIRO TOKEN isolado ("Imagem de…",
    # "Figura 1…") — comparar a string inteira colada descartaria nomes reais
    # cujo início por acaso coincide com um prefixo ("Marcela", "Figueiredo").
    if compactar(limpo.split()[0]) in _PREFIXOS_LIXO:
        return False
    if any(r in plano for r in _ROTULOS_SECAO):
        return False
    alfabeticas = sum(1 for c in limpo if c.isalpha() or c in " '-.")
    return alfabeticas / max(1, len(limpo)) >= 0.85


def nome_do_arquivo(nome_arquivo: str) -> str | None:
    """Extrai o nome do aluno do NOME DO ARQUIVO (tudo após '... estudante -').

    Tolera acentos e variações no rótulo (só casa a partir de 'performance',
    que não tem acento). Devolve None se o arquivo não segue o padrão."""
    if not nome_arquivo:
        return None
    base = re.sub(r"\.(pdf|txt|csv|tsv)$", "", nome_arquivo.strip(), flags=re.IGNORECASE)
    casado = _RE_NOME_ARQUIVO.search(base)
    if not casado:
        return None
    nome = re.sub(r"\s+", " ", casado.group(1)).strip(" -–—_")
    # Remove o sufixo "(1)", "(2)"… que o navegador acrescenta ao baixar cópias
    # do mesmo relatório — senão o casamento exato de nome falharia.
    nome = re.sub(r"\s*\(\d+\)\s*$", "", nome).strip()
    return nome if _parece_nome_pessoa(nome) else None


class PerfilElefanteEstudante:
    plataforma = "elefante"
    formato = "leituras"
    estrategia = "perfil_elefante_estudante"

    def detecta(self, compacto: str, nome_arquivo: str = "") -> bool:
        # O nome do arquivo também identifica o relatório individual — cobre
        # PDFs cujo conteúdo veio ruim (escaneado/imagem).
        return ("performancedoestudante" in compacto
                or "historicodelivroslidos" in compacto
                or "performancedoestudante" in compactar(nome_arquivo)
                or "desempenhodoestudante" in compactar(nome_arquivo))

    def analisar(self, paginas: list[Pagina], nome_arquivo: str = "") -> Analise | None:
        cabecalho = self._cabecalho(paginas)
        # PRIORIDADE 1: nome do arquivo (fonte oficial e confiável do Elefante).
        # PRIORIDADE 2: conteúdo do PDF. PRIORIDADE 3: seleção manual.
        nome_arq = nome_do_arquivo(nome_arquivo)
        nome_conteudo = cabecalho.get("nome")
        if nome_arq:
            nome_aluno, origem = nome_arq, "arquivo"
        elif nome_conteudo:
            nome_aluno, origem = nome_conteudo, "conteudo"
        else:
            nome_aluno, origem = "", "nenhum"

        registros = _tabela_posicional(
            paginas, COLUNAS_PERFIL_ESTUDANTE, com_nome=False,
            aceitar_cabecalho=lambda campos: {"livro", "tempo", "data"} <= campos,
            inicia_registro=lambda presentes: any(
                _RE_RELOGIO.match(p.texto) for p in presentes.get("tempo", [])
            ) and any(
                _RE_DATA.match(p.texto) for p in presentes.get("data", [])),
        )

        # Sem nome confiável E sem histórico: deixa o genérico/manual decidir.
        if not nome_aluno and not registros:
            return None
        nome_linha = nome_aluno or "Aluno não identificado"

        resumo = self._resumo(paginas)
        turma = cabecalho.get("turma", "")
        por_metodo = {"arquivo": "pelo nome do arquivo",
                      "conteudo": "pelo conteúdo do PDF"}.get(origem)
        analise = Analise(
            plataforma=self.plataforma, formato=self.formato,
            estrategia=self.estrategia,
            turma_detectada=turma,
            escola_detectada=cabecalho.get("escola", ""),
            professor_detectado=cabecalho.get("professor", ""),
            origem_nome=origem,
            mensagem_deteccao="Este arquivo pertence ao Elefante Letrado — "
            + (f"relatório individual de {nome_aluno} (identificado {por_metodo})"
               if nome_aluno else "relatório individual (aluno não identificado "
               "automaticamente — selecione manualmente)")
            + (f", turma {turma}" if turma else "")
            + (f" · {resumo['leituras']} leituras concluídas na plataforma"
               if "leituras" in resumo else "") + ".")

        # O nome do arquivo tem prioridade, mas se DIVERGIR do nome no conteúdo
        # do PDF é sinal de arquivo renomeado/trocado — avisa para o usuário
        # conferir antes de importar (não muda a prioridade, só sinaliza).
        if origem == "arquivo" and nome_conteudo and _similaridade(
                normalizar_nome(nome_arq), normalizar_nome(nome_conteudo)) < 0.85:
            analise.erros_gerais.append(
                f"Atenção: o nome do arquivo (“{nome_arq}”) difere do nome no "
                f"conteúdo do PDF (“{nome_conteudo}”). Confirme se o relatório é "
                "do aluno certo antes de importar.")

        for numero, registro in enumerate(registros, start=1):
            item = LinhaImportacao(numero=numero, nome=nome_linha, dados={})
            if turma:
                item.dados["turma_relatorio"] = turma
            titulo = registro.texto("livro")
            if titulo:
                item.dados["livro"] = titulo
            _atribuir(item, "nivel", registro.texto("nivel"), _codigo_nivel)
            genero = registro.texto("genero")
            if genero:
                item.dados["genero"] = genero.strip(" ,")
            # A coluna Data/Hora traz a DATA na 1ª linha e o HORÁRIO na 2ª —
            # captura os dois para preservar o momento exato da leitura.
            tokens_data = [p.texto for p in registro.campos.get("data", [])]
            datas = [t for t in tokens_data if _RE_DATA.match(t)]
            horas = [t for t in tokens_data if _RE_RELOGIO.match(t)]
            if datas:
                _atribuir(item, "data", (datas[0], horas[0] if horas else None),
                          _data_hora_iso)
            _atribuir(item, "tempo_livro_min", registro.texto("tempo"),
                      duracao_em_minutos)
            analise.linhas.append(_fechar_linha(item))

        # Tempo total de leitura do resumo: complementa alunos que ainda não
        # têm snapshot vindo do relatório da turma (nunca o sobrescreve).
        if analise.linhas and "tempo_leitura_min" in resumo:
            analise.linhas[0].dados["tempo_leitura_min"] = resumo["tempo_leitura_min"]
        return analise

    def _cabecalho(self, paginas: list[Pagina]) -> dict:
        """Nome, turma, escola e professor do cabeçalho do relatório individual.

        Layout (posicional): abaixo do título vem o NOME; depois a linha
        "TURMA - ESCOLA"; e o bloco Professor|Escola|Turma em colunas
        (Turma alinhada à direita, x0 alto)."""
        info: dict = {}
        if not paginas:
            return info
        linhas = _linhas_visuais(paginas[0].palavras)
        apos_titulo = False
        for linha in linhas[:10]:
            texto = linha.texto.strip()
            compacto = compactar(texto)
            if "performancedoestudante" in compacto:
                apos_titulo = True
                continue
            if not apos_titulo or not texto:
                continue
            if re.search(r"\d{2}/\d{2}/\d{4}", texto):
                continue  # linha do intervalo de datas — ignorar
            # Rótulos de seção nunca são nome nem turma.
            if any(r in compacto for r in _ROTULOS_SECAO):
                continue
            # NOME do aluno vem PRIMEIRO no layout (topo mais alto) — capturado
            # antes da regra de turma para não confundir nomes com hífen
            # ("Ana - Maria") com "TURMA - ESCOLA". Legendas de imagem
            # ("Imagem de..."), logos e rótulos são recusados.
            if "nome" not in info and not re.search(r"\d", texto) \
                    and _parece_nome_pessoa(texto):
                info["nome"] = texto
                continue
            # Linha "TURMA - ESCOLA": SÓ depois do nome e SÓ se começar por
            # dígito (a série). rpartition separa a escola (último segmento),
            # preservando turmas cujo nome contenha " - ".
            if "nome" in info and "turma" not in info and " - " in texto \
                    and re.match(r"^\s*\d", texto):
                turma, _, escola = texto.rpartition(" - ")
                if turma.strip() and len(turma) <= 60:
                    info["turma"] = turma.strip()
                    if escola.strip():
                        info["escola"] = escola.strip()
                continue
        # Professor: coluna à esquerda do bloco "Professor | Escola | Turma".
        info["professor"] = self._professor(linhas)
        # Reforço da turma pela coluna "Turma" (x0 alto) se a linha falhou.
        if not info.get("turma"):
            info["turma"] = self._turma_por_coluna(linhas)
        return info

    def _professor(self, linhas: list[LinhaVisual]) -> str:
        for indice, linha in enumerate(linhas[:12]):
            if compactar(linha.texto).startswith("professor"):
                nomes = []
                for prox in linhas[indice + 1:indice + 4]:
                    trecho = " ".join(
                        p.texto for p in sorted(prox.palavras, key=lambda p: p.x0)
                        if p.x0 < 200)
                    if trecho.strip():
                        nomes.append(trecho.strip())
                return " ".join(nomes).strip(" ,")[:200]
        return ""

    def _turma_por_coluna(self, linhas: list[LinhaVisual]) -> str:
        for indice, linha in enumerate(linhas[:12]):
            rotulo = next((p for p in linha.palavras
                           if compactar(p.texto) == "turma"), None)
            if rotulo is None:
                continue
            for prox in linhas[indice + 1:indice + 3]:
                trecho = " ".join(
                    p.texto for p in sorted(prox.palavras, key=lambda p: p.x0)
                    if p.x0 >= rotulo.x0 - 8)
                if trecho.strip():
                    return trecho.strip()
        return ""

    def _resumo(self, paginas: list[Pagina]) -> dict:
        """Valores do bloco "Hábito de Leitura" (rótulo em cima, valor embaixo)."""
        resumo: dict = {}
        if not paginas:
            return resumo
        linhas = _linhas_visuais(paginas[0].palavras)
        for indice, linha in enumerate(linhas):
            for alvo, chave, conversor in (
                ("leiturasconcluidas", "leituras", _inteiro),
                ("tempodeleitura", "tempo_leitura_min", duracao_em_minutos),
            ):
                if chave in resumo:
                    continue
                x0 = _x0_do_rotulo(linha, alvo)
                if x0 is None:
                    continue
                for proxima in linhas[indice + 1:indice + 3]:
                    for palavra in proxima.palavras:
                        if abs(palavra.x0 - x0) <= 15.0:
                            try:
                                resumo[chave] = conversor(palavra.texto)
                            except (ValueError, TypeError):
                                pass
                            break
                    if chave in resumo:
                        break
        return resumo


def _x0_do_rotulo(linha: LinhaVisual, alvo_compacto: str) -> float | None:
    """x0 da sequência de palavras cujo texto compactado forma o rótulo."""
    palavras = sorted(linha.palavras, key=lambda p: p.x0)
    for inicio in range(len(palavras)):
        acumulado = ""
        for palavra in palavras[inicio:]:
            acumulado += compactar(palavra.texto)
            if acumulado == alvo_compacto:
                return palavras[inicio].x0
            if len(acumulado) >= len(alvo_compacto):
                break
    return None


# --------------------------------------------------------------------------
# Perfil 3 — Matific · classificação de estrelas dos estudantes
# --------------------------------------------------------------------------

COLUNAS_PERFIL_MATIFIC = {
    "serie": ["serie"],
    "turma_relatorio": ["turma"],
    "atividades": ["atividades finalizadas", "atividades"],
    "pontuacao_media": ["pontuacao media"],
    "estrelas": ["estrelas"],
}

_RE_RODAPE_MATIFIC = re.compile(r"https?://|www\.|matific\.com", re.IGNORECASE)

# "Intervalo de datas 2026-03-01-2026-04-01" (leaderboard mensal/semanal).
# Tolerante: "datas"/"dados", datas ISO ou brasileiras, separador -, – ou "a".
_RE_INTERVALO_MATIFIC = re.compile(
    r"intervalo\s*de\s*(?:dat[ao]s?|dados)\s*:?\s*"
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})"
    r"\s*(?:[-–—]|ate|até|a)\s*"
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})",
    re.IGNORECASE,
)

# O campo também aceita PRESETS em vez de datas explícitas. Os semanais são
# resolvidos pela data de impressão do rodapé; os demais viram TOTAL acumulado
# (com aviso — para rankings por período, o certo é "Personalizar intervalo").
_RE_INTERVALO_PRESET = re.compile(
    r"intervalo\s*de\s*(?:dat[ao]s?|dados)\s*:?\s*([^\d\s][^\n]{2,60}?)\s*$",
    re.IGNORECASE,
)
_RE_DATA_IMPRESSAO = re.compile(r"([0-3]?\d)/([01]?\d)/(\d{4}),")


def _data_impressao(paginas: list[Pagina]):
    """Data em que o PDF foi impresso (rodapé "08/07/2026, 01:13 Matific")."""
    from datetime import date as _date
    for pagina in paginas:
        for linha in _linhas_visuais(pagina.palavras):
            casado = _RE_DATA_IMPRESSAO.search(linha.texto)
            if casado:
                dia, mes, ano = (int(g) for g in casado.groups())
                try:
                    return _date(ano, mes, dia)
                except ValueError:
                    continue
    return None


def _intervalo_matific(paginas: list[Pagina]) -> tuple[str, str, str]:
    """("AAAA-MM-DD", "AAAA-MM-DD", observação) do "Intervalo de datas".

    * Datas explícitas → o intervalo impresso (degenerado é descartado: a
      confirmação responderia 400 sem saída — melhor cair no acumulado).
    * "Esta semana"/"Última semana" → resolvidos pela data de impressão do
      rodapé (semana de segunda a domingo).
    * "Ano acadêmico ..."/"Olimpíadas ..." → sem período: os valores são
      tratados como TOTAL acumulado, com observação orientando o usuário.
    """
    if not paginas:
        return "", "", ""
    for linha in _linhas_visuais(paginas[0].palavras)[:12]:
        casado = _RE_INTERVALO_MATIFIC.search(linha.texto)
        if casado:
            try:
                inicio, fim = (
                    bruto if re.fullmatch(r"\d{4}-\d{2}-\d{2}", bruto)
                    else _data_iso(bruto)
                    for bruto in casado.groups()
                )
                if inicio < fim:
                    return inicio, fim, ""
            except ValueError:
                pass
            # Datas presentes mas ilegíveis/degeneradas: NUNCA em silêncio —
            # sem período, a confirmação SUBSTITUI o acumulado.
            return "", "", ("O intervalo de datas do relatório não pôde ser "
                            "lido — os valores serão tratados como TOTAL "
                            "acumulado. Para rankings por semana/mês, exporte "
                            "com “Personalizar intervalo”.")
        preset = _RE_INTERVALO_PRESET.search(linha.texto.strip())
        if not preset:
            continue
        rotulo = preset.group(1).strip(" .:-–—")
        plano = compactar(rotulo)
        if plano in ("estasemana", "ultimasemana"):
            impressao = _data_impressao(paginas)
            if impressao is None:
                return "", "", (f"O intervalo de datas está como “{rotulo}”, mas "
                                "não encontrei a data de impressão no rodapé — os "
                                "valores serão tratados como total acumulado.")
            # A semana do Matific começa no DOMINGO (help.br.matific.com:
            # "Esta semana cobre do último domingo até hoje").
            domingo = impressao - timedelta(days=(impressao.weekday() + 1) % 7)
            if plano == "ultimasemana":
                inicio_d, fim_d = domingo - timedelta(days=7), domingo
            else:
                inicio_d, fim_d = domingo, impressao + timedelta(days=1)
            return (inicio_d.isoformat(), fim_d.isoformat(),
                    f"“{rotulo}” resolvido pela data de impressão do relatório.")
        if plano:
            return "", "", (f"O intervalo de datas está como “{rotulo}” — os "
                            "valores serão tratados como TOTAL acumulado. Para "
                            "rankings por semana/mês, exporte o relatório com "
                            "“Personalizar intervalo”.")
    return "", "", ""


def _data_br(iso: str) -> str:
    ano, mes, dia = iso.split("-")
    return f"{dia}/{mes}/{ano}"


class PerfilMatific:
    plataforma = "matific"
    formato = "resumo"
    estrategia = "perfil_matific"

    def detecta(self, compacto: str, nome_arquivo: str = "") -> bool:
        return ("matific" in compacto
                or "matific" in compactar(nome_arquivo)
                or ("atividadesfinalizadas" in compacto and "estrelas" in compacto))

    def analisar(self, paginas: list[Pagina], nome_arquivo: str = "") -> Analise:
        # O botão lateral "Opinião" é desenhado de lado ("oãinipO") e pousa
        # na MESMA linha visual de registros reais — remove-se por palavra.
        paginas = [
            Pagina(numero=pagina.numero, palavras=[
                p for p in pagina.palavras
                if compactar(p.texto)[::-1] != "opiniao"
            ])
            for pagina in paginas
        ]

        def ignorar(linha: LinhaVisual) -> bool:
            texto = linha.texto
            if _RE_RODAPE_MATIFIC.search(texto):
                return True
            # Rodapé "06/07/2026, 16:10 Matific"
            return re.search(r"\d{2}/\d{2}/\d{4},", texto) is not None

        def inicia(presentes: dict[str, list[Palavra]]) -> bool:
            # Conta colunas de métrica PREENCHIDAS — número OU traço ("-"/"—").
            # O aluno inativo pode vir "- - -": ainda é um aluno (nome + Série),
            # e a linha deve sobreviver com avisos, nunca sumir (§51).
            preenchidas = sum(
                1 for campo in ("atividades", "pontuacao_media", "estrelas")
                if any(re.fullmatch(r"[\d.,]+|[-–—]", p.texto)
                       for p in presentes.get(campo, [])))
            if "nome" in presentes:
                return preenchidas >= 2
            # Nome comprido quebra INTEIRO nas linhas vizinhas ("CHRISTOPHER"
            # acima, "D" abaixo) e a linha do registro fica só com números:
            # série + as 3 métricas bastam — o nome chega pela costura de
            # órfãs. Sem isto o aluno sumia do relatório.
            return preenchidas >= 3 and "serie" in presentes

        registros = _tabela_posicional(
            paginas, COLUNAS_PERFIL_MATIFIC, com_nome=True,
            aceitar_cabecalho=lambda campos: "nome" in campos
            and {"atividades", "estrelas"} <= campos and len(campos) >= 4,
            inicia_registro=inicia,
            ignorar_linha=ignorar,
            anexo_por_proximidade=True,  # a turma vem fatiada acima E abaixo
        )
        # O "Intervalo de datas" da capa define A QUE PERÍODO os números
        # pertencem: a confirmação soma ao acumulado e data o snapshot no fim
        # do intervalo — rankings e premiações do mês certo, mesmo importando
        # o relatório semanas depois.
        inicio, fim, observacao = _intervalo_matific(paginas)
        analise = Analise(plataforma=self.plataforma, formato=self.formato,
                          estrategia=self.estrategia,
                          periodo_inicio=inicio, periodo_fim=fim,
                          mensagem_deteccao="Este arquivo pertence ao Matific — "
                          "classificação de estrelas dos estudantes"
                          + (f", com dados do período de {_data_br(inicio)} a "
                             f"{_data_br(fim)}" if inicio else "")
                          + "." + (f" {observacao}" if observacao else ""))
        for numero, registro in enumerate(registros, start=1):
            item = LinhaImportacao(numero=numero, nome=registro.texto("nome"),
                                   dados={})
            _atribuir(item, "atividades", registro.texto("atividades"), _inteiro)
            _atribuir(item, "pontuacao_media",
                      registro.texto("pontuacao_media"), _numero)
            _atribuir(item, "estrelas", registro.texto("estrelas"), _inteiro)
            serie = registro.texto("serie")
            if serie:
                item.dados["serie"] = serie
            turma = re.sub(r"\s*\(\d+\)\s*$", "", registro.texto("turma_relatorio"))
            if turma:
                item.dados["turma_relatorio"] = turma
            analise.linhas.append(_fechar_linha(item))
        return analise


# --------------------------------------------------------------------------
# Orquestração: perfis primeiro, estratégias genéricas como rede de segurança
# --------------------------------------------------------------------------

PERFIS = (PerfilElefanteEstudante(), PerfilElefanteTurma(), PerfilMatific())


def analisar_pdf(conteudo: bytes, plataforma: str | None = None,
                 nome_arquivo: str = "") -> Analise:
    """Analisa um PDF: detecta o perfil real e reconstrói a tabela por
    posição; sem perfil compatível, cai nas estratégias genéricas de texto.

    `nome_arquivo` é a fonte PREFERENCIAL do nome do aluno no relatório
    individual do Elefante ("... estudante - NOME.pdf").
    """
    from app.services import importacao as generico

    try:
        paginas = extrair_paginas(conteudo)
    except Exception:  # noqa: BLE001 — pdfplumber é melhor esforço
        paginas = []

    compacto = ""
    if paginas:
        compacto = compactar(" ".join(
            p.texto for pagina in paginas for p in pagina.palavras))
    for perfil in PERFIS:
        if plataforma and perfil.plataforma != plataforma:
            continue
        if not perfil.detecta(compacto, nome_arquivo):
            continue
        try:
            analise = perfil.analisar(paginas, nome_arquivo)
        except Exception:  # noqa: BLE001 — layout inesperado: usa o genérico
            analise = None
        if analise is not None and analise.linhas:
            return analise

    texto = generico.extrair_texto_pdf(conteudo)
    return generico.analisar_texto(texto, plataforma)
