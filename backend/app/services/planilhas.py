"""Importação de relatórios em PLANILHA (Excel .xlsx) — hoje o Matific.

O Matific exporta o "Relatório de Atividade do Aluno" por turma como um
workbook: uma aba-resumo da turma (uma linha por aluno) seguida de uma aba
por aluno. Só a aba-resumo interessa — as abas por aluno trazem apenas o
cabeçalho.

Layout real da aba-resumo (openpyxl, `data_only`):

    R00 | Relatório de Atividade do Aluno |        | Exportado em: 7 jul 2026
    R02 | Turma                           | 5 ANO B MANHA ANUAL (300397500)
    R03 | Professor(a)                    | Marta Simulatti
    R08 | Datas                          | 6 jun 2026 - 7 jul 2026
    R10 | Alunos | Total de atividades concluídas | Atividades únicas … | Tempo gasto | Pontuação média | <22 tópicos…>
    R11 | Toda a turma | 371 | 93 | 28 h 33 min | 0.31 | …          ← totais (ignorar)
    R12 | TEOBALDO … FICTICIO | 0  | 0  | -          | -    | …          ← conta vazia
    R13 | Teobaldo … Ficticio | 30 | 22 | 2 h 4 min  | 0.48 | …          ← conta real

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

Este módulo também guarda a defesa ÚNICA contra planilha inflada
(``exigir_xlsx_contido`` e ``limitar_celula``), usada pelo relatório do Matific,
pela Lista Piloto e pela sincronização antes de o openpyxl abrir o arquivo, e a
leitura das linhas com teto do que é percorrido (``linhas_contidas`` com
``OrcamentoLeitura``), contra a dimensão declarada enorme.
"""
from __future__ import annotations

import io
import re
import zipfile

from app.services.importacao import (
    Analise,
    LinhaImportacao,
    _atribuir_campo,
    _eh_coluna_nome,
    _fechar_linha,
    chave_nome,
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


# --------------------------------------------------------------------------
# Planilha inflada (bomba de descompressão) — defesa ÚNICA, antes do openpyxl
# --------------------------------------------------------------------------
# O upload só confere o tamanho COMPRIMIDO (10 MB). Um .xlsx é um zip: poucos KB
# de texto repetido inflam para centenas de MB. Medido no e97: 84 MB
# descomprimidos (83 KB enviados) levaram o worker de 157 MB para 1,5 GB na Lista
# Piloto, e 1 MB numa célula prendia ~6 s de CPU no relatório do Matific. Tudo é
# conferido ANTES de o openpyxl abrir o arquivo (padrão de ``indicadores.ica.
# ler_do_zip``): o que o próprio zip DECLARA e, por robustez, o que ele de fato
# descomprime, lido aos poucos e com teto.

#: Soma máxima das partes descomprimidas. Relatório do Matific e Lista Piloto reais
#: ficam muito abaixo disso.
XLSX_MAX_DESCOMPRIMIDO = 30 * 1024 * 1024
#: Razão descomprimido/comprimido acima da qual o pacote é recusado. O XML de uma
#: planilha real comprime de 5 a 20 vezes; texto repetido de propósito, 1.000 vezes.
XLSX_MAX_RAZAO = 100
#: Abaixo deste total a razão não é conferida: arquivo pequeno não esgota nada.
_XLSX_RAZAO_A_PARTIR_DE = 1024 * 1024
#: Uma planilha real tem dezenas de partes (abas, estilos, relações).
XLSX_MAX_PARTES = 5_000
#: O .xlsx só usa estas compactações. bzip2/LZMA o ``zipfile`` descomprime SEM
#: teto por leitura (o tamanho declarado não o limita): recusadas antes de ler.
_COMPACTACOES_XLSX = (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
_BLOCO_LEITURA = 1024 * 1024

#: Teto do texto de UMA célula lida de planilha (Matific e Lista Piloto). Nome,
#: turma, rótulo e data cabem com folga; acima disso é lixo ou ataque — e todo o
#: processamento seguinte (casamento difuso, regex, normalização) custa em função
#: do tamanho do texto.
MAX_TEXTO_CELULA = 1_000

#: Colunas lidas de cada linha. A aba-resumo do Matific tem ~30 e a Lista Piloto
#: ~20; o openpyxl, sem teto, completa cada linha até a dimensão DECLARADA (até a
#: coluna XFD, 16.384) ou até a última célula da linha.
MAX_COLUNAS_LIDAS = 256


class PlanilhaRecusada(ValueError):
    """A planilha foi recusada ANTES de ser aberta (pacote inflado) ou durante a
    leitura (orçamento do que se percorre). ``status_http`` é o código que a rota
    devolve: 413 para tamanho/inflação, 400 para formato que o Excel não gera.
    Subclasse de ``ValueError``: quem já trata ``ValueError`` como "planilha
    ilegível" continua tratando."""

    def __init__(self, mensagem: str, status_http: int = 413):
        super().__init__(mensagem)
        self.status_http = status_http


def exigir_xlsx_contido(conteudo: bytes, max_total: int = XLSX_MAX_DESCOMPRIMIDO,
                        max_razao: float = XLSX_MAX_RAZAO) -> None:
    """Recusa (``PlanilhaRecusada``) o .xlsx que infla além do teto, ANTES do openpyxl.

    Confere, nesta ordem e sem descomprimir nada antes de tudo estar em ordem: o
    número de partes, a compactação de cada uma, a soma dos tamanhos que o zip
    declara e a razão de compressão do pacote. Depois descomprime cada parte aos
    poucos (``read`` limitado), contando os bytes REAIS contra o mesmo teto — o
    tamanho declarado é do próprio arquivo e não basta como garantia.

    O que não é zip, ou é um zip corrompido/cifrado, passa sem erro: quem abre a
    planilha (openpyxl/xlrd) recusa com a mensagem de sempre, e nada aqui chega a
    alocar além do teto."""
    try:
        pacote = zipfile.ZipFile(io.BytesIO(conteudo))
    except Exception:  # noqa: BLE001 — não é zip legível: o leitor da planilha recusa
        return
    with pacote:
        partes = pacote.infolist()
        if len(partes) > XLSX_MAX_PARTES:
            raise PlanilhaRecusada(
                "A planilha tem partes internas demais e foi recusada. Confira se é o "
                "arquivo certo e envie de novo.")
        if any(info.compress_type not in _COMPACTACOES_XLSX for info in partes):
            raise PlanilhaRecusada(
                "A planilha usa uma compactação que o Excel não gera e foi recusada. "
                "Abra o arquivo no Excel, salve de novo e envie outra vez.", 400)
        declarado = sum(info.file_size for info in partes)
        comprimido = sum(info.compress_size for info in partes)
        mensagem_teto = (
            f"A planilha passa de {max_total // (1024 * 1024)} MB depois de "
            "descompactada e foi recusada. Confira se é o arquivo certo (o relatório "
            "da turma ou a Lista Piloto) e envie de novo.")
        if declarado > max_total:
            raise PlanilhaRecusada(mensagem_teto)
        if declarado > _XLSX_RAZAO_A_PARTIR_DE and declarado > max_razao * max(comprimido, 1):
            raise PlanilhaRecusada(
                "A planilha tem compactação fora do normal (o conteúdo infla mais de "
                f"{int(max_razao)} vezes) e foi recusada. Abra o arquivo no Excel, "
                "salve de novo e envie outra vez.")
        restante = max_total
        for info in partes:
            if info.is_dir():
                continue
            try:
                with pacote.open(info) as entrada:
                    while bloco := entrada.read(min(_BLOCO_LEITURA, restante + 1)):
                        restante -= len(bloco)
                        if restante < 0:
                            raise PlanilhaRecusada(mensagem_teto)
            except PlanilhaRecusada:
                raise
            except Exception:  # noqa: BLE001 — parte corrompida/cifrada: o leitor recusa
                return


def limitar_celula(valor):
    """O valor da célula com o TEXTO cortado em ``MAX_TEXTO_CELULA`` caracteres;
    números, datas e vazios passam intactos."""
    if isinstance(valor, str) and len(valor) > MAX_TEXTO_CELULA:
        return valor[:MAX_TEXTO_CELULA]
    return valor


# --------------------------------------------------------------------------
# Leitura das linhas com teto do que é PERCORRIDO (dimensão declarada)
# --------------------------------------------------------------------------
# O teto do descomprimido não basta: um .xlsx de 2 KB pode DECLARAR a dimensão
# A1:XFD5000 e ter uma só célula em A5000. O openpyxl (read_only) então entrega
# 5.000 linhas de 16.384 colunas — as linhas que faltam no XML ele completa, e cada
# linha ele completa até a dimensão ou até a última célula. Medido no e97: 7 s e
# +655 MB no relatório do Matific; 33 s na Lista Piloto. Aqui a leitura tem teto de
# linhas e de colunas, a linha vazia não é materializada, as vazias à direita saem,
# e o que se percorre (inclusive vazio) é contado contra um orçamento do arquivo.

class OrcamentoLeitura:
    """O que a leitura de UM arquivo pode percorrer, somadas todas as abas.

    Conta o PERCORRIDO, não só o preenchido: toda linha entregue pelo leitor
    (inclusive a vazia que ele completa entre duas linhas do XML) e, em cada linha
    com conteúdo, as células até a última preenchida (inclusive as vazias no meio).
    Linha vazia e colunas vazias à direita custam quase nada e não entram nas
    células — a formatação aplicada a uma aba inteira não esgota o orçamento."""

    def __init__(self, max_linhas: int, max_celulas: int):
        self.max_linhas = max_linhas
        self.max_celulas = max_celulas
        self.linhas = 0
        self.celulas = 0

    def recusar(self):
        raise PlanilhaRecusada(
            "A planilha tem linhas ou células demais para ser lida e foi recusada. "
            "Confira se é o arquivo certo; se for, apague as linhas e colunas vazias "
            "depois da tabela em cada aba, salve e envie de novo.")


def linhas_contidas(ws, orcamento: OrcamentoLeitura, max_linhas: int, *,
                    manter_vazias: bool = True, converter=None) -> list[list]:
    """As linhas de uma aba ``read_only`` com teto do que é percorrido.

    * no máximo ``max_linhas`` linhas e ``MAX_COLUNAS_LIDAS`` colunas, passados
      explicitamente ao openpyxl: a dimensão declarada não alarga nada;
    * linha toda vazia vira ``[]`` (ou some, com ``manter_vazias=False``, quando a
      posição da linha não importa a quem lê);
    * as células vazias à direita da última preenchida saem da linha;
    * o texto de cada célula é cortado em ``MAX_TEXTO_CELULA``; ``converter``, se
      houver, é aplicado a cada célula depois do corte.

    Estourar o orçamento levanta ``PlanilhaRecusada`` (413)."""
    linhas: list[list] = []
    for linha in ws.iter_rows(values_only=True, max_row=max_linhas,
                              max_col=MAX_COLUNAS_LIDAS):
        orcamento.linhas += 1
        if orcamento.linhas > orcamento.max_linhas:
            orcamento.recusar()
        fim = len(linha)
        if linha.count(None) == fim:          # vazia (a contagem roda em C)
            if manter_vazias:
                linhas.append([])
            continue
        while linha[fim - 1] is None:
            fim -= 1
        orcamento.celulas += fim
        if orcamento.celulas > orcamento.max_celulas:
            orcamento.recusar()
        celulas = [v if type(v) is not str or len(v) <= MAX_TEXTO_CELULA
                   else v[:MAX_TEXTO_CELULA] for v in linha[:fim]]
        if converter is not None:
            celulas = [converter(v) for v in celulas]
        linhas.append(celulas)
    return linhas


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


#: Linhas lidas por aba do relatório do Matific (a aba-resumo tem dezenas).
_MAX_LINHAS_ABA_MATIFIC = 5000
#: Orçamento do arquivo do Matific: a aba-resumo e uma aba por aluno, com dezenas
#: de linhas cada — muito abaixo destes tetos.
_MAX_LINHAS_MATIFIC = 50_000
_MAX_CELULAS_MATIFIC = 1_000_000


def _linhas_da_aba(ws, orcamento: OrcamentoLeitura,
                   limite: int = _MAX_LINHAS_ABA_MATIFIC) -> list[list]:
    # Texto cortado já na leitura: a 1ª célula de cada linha passa pelo casamento
    # difuso do cabeçalho e o valor de "Turma" por uma regex — ambos custam em
    # função do tamanho (1 MB numa célula prendia ~6 s de CPU, e97). Linha vazia
    # fica como [] para a posição das linhas não mudar.
    return linhas_contidas(ws, orcamento, limite)


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
            if celula is None:
                continue
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
    as abas por aluno só têm metadados, então nunca casam. O orçamento do que se
    percorre vale para o arquivo inteiro, não por aba.
    """
    orcamento = OrcamentoLeitura(_MAX_LINHAS_MATIFIC, _MAX_CELULAS_MATIFIC)
    for ws in wb.worksheets:
        linhas = _linhas_da_aba(ws, orcamento)
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
    reconhecível — o router traduz em HTTP 400. A planilha inflada ou grande demais
    levanta ``PlanilhaRecusada`` (subclasse, com o status da recusa).
    """
    import openpyxl

    # A guarda do descomprimido fica AQUI, antes do openpyxl, e não em cada
    # chamador (upload manual, sincronização): quem chamar o parser não tem como
    # esquecê-la — como na Lista Piloto (``lista_piloto._abrir_xlsx``).
    exigir_xlsx_contido(conteudo)
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
        chave = chave_nome(item.nome)   # a definição ÚNICA de "mesmo nome"
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
