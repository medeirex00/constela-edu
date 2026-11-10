"""O PDF do Relatório por Período.

REGRA DE ARQUITETURA, e ela é a razão deste arquivo existir separado: este
módulo **não consulta o banco e não calcula nada**. A única entrada é o dicionário
que ``relatorios_periodo.gerar`` já produziu. Não há ``Session`` aqui, não há
``select``, não há acesso a modelo — então é impossível, por construção, o PDF
divergir da tela: os dois leem o MESMO objeto. Se um número aparece no papel, ele
veio do motor; se o motor não o produz, o papel não o inventa.

REUSO, não segundo sistema de PDF. A moldura é a mesma dos outros relatórios de
vitrine da casa (``_relatorio_shell`` + ``_relatorio_html_pdf``, renderizados por
Chromium com o CSS e o rodapé numerado oficiais) e a reserva é o mesmo
``gerar_pdf`` em fpdf que a exportação já usa quando não há Chromium — o padrão
copiado de ``gerar_lista_alunos_pdf``.

  Nota de acoplamento: importamos de ``app.services.relatorios``, que está entre
  as alterações paralelas não commitadas. Importar não é modificar, e as funções
  usadas aqui foram conferidas uma a uma: são IDÊNTICAS na versão commitada e na
  versão da árvore de trabalho. A única que difere entre as duas é ``_latin1``
  (a versão nova mapeia o travessão "—" para hífen), e por isso este módulo
  NUNCA imprime travessão: onde não há dado, escreve por extenso. Assim a saída
  é a mesma com ou sem o trabalho paralelo presente.

A RESERVA CARREGA OS MESMOS NÚMEROS. Sem Chromium o PDF sai simples, mas não sai
pobre: ``linhas_resumo`` é a fonte única das duplas (rótulo, valor) e alimenta os
DOIS caminhos. Um relatório de reserva que perdesse os números seria pior do que
um erro — pareceria certo.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime

from app.core.tempo import agora_br, para_br
from app.services.relatorios import (_esc_html, _relatorio_html_pdf,
                                     _relatorio_shell, gerar_pdf)

# Onde não há dado, escrevemos por extenso. Nunca "—" (o travessão não existe em
# latin-1, e as duas versões de `_latin1` o tratam de formas diferentes) e nunca
# "0" (zero é uma afirmação: a criança foi medida e não produziu). "Não calculado"
# é a etiqueta da tela para o que o motor classifica como NÃO SUPORTADO.
SEM_SUPORTE = "não calculado"
SEM_DADO = "sem dado"

log = logging.getLogger(__name__)

_ROTULO_ESCOPO = {"escola": "Escola inteira", "turma": "Turma", "aluno": "Estudante"}

# Estilos EXTRAS, escopados com prefixo próprio para não colidir com o
# `_REPORT_CSS` da casa, que continua valendo para faixa, títulos, tiles e
# tabelas. Vai no corpo porque é assim que o shell monta o documento.
_CSS_EXTRA = """<style>
  .rp-nota { border:1px solid #E4D3A6; border-left:4px solid #C9A24B; border-radius:6px;
             padding:9px 13px; margin:10px 0; font-size:10px; color:#6b7488; line-height:1.5; }
  .rp-nota b { color:#1B2A4A; }
  .rp-selo { display:inline-block; font-family:'Trebuchet MS','Segoe UI',sans-serif;
             font-size:7.5px; font-weight:700; letter-spacing:.4px; text-transform:uppercase;
             padding:2px 6px; border-radius:3px; border:1px solid #C9CFDC; color:#5a6478; }
  .rp-selo.ok { border-color:#9FD5AF; color:#2FA24B; }
  .rp-selo.res { border-color:#E4C98A; color:#8A6D2B; }
  .rp-selo.nao { border-color:#C9CFDC; color:#8a93a5; }
  td.rp-val { font-family:'Trebuchet MS','Segoe UI',sans-serif; font-weight:700; color:#1B2A4A; }
  td.rp-vazio { color:#8a93a5; font-style:italic; }
  .rp-fonte { font-size:9px; color:#8a93a5; }
  .rp-porque { font-size:9.5px; color:#6b7488; line-height:1.45; }
</style>"""


# ---------------------------------------------------------------- utilidades
def _num(valor) -> str:
    """Número no padrão brasileiro. ``None`` não vira zero — vira texto."""
    if valor is None:
        return SEM_DADO
    return f"{int(valor):,}".replace(",", ".")


def _tempo(minutos) -> str:
    if minutos is None:
        return SEM_DADO
    minutos = int(minutos)
    if minutos < 60:
        return f"{minutos} min"
    horas, resto = divmod(minutos, 60)
    return f"{horas}h {resto}min" if resto else f"{horas}h"


def _data(iso: str | None) -> str:
    if not iso:
        return SEM_DADO
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y")
    except ValueError:
        return str(iso)


def _data_hora(iso: str | None) -> str:
    """Instante de COLETA, convertido para Brasília — como a tela faz.

    Estes instantes (``data_referencia`` dos retratos) são gravados em UTC e
    serializados sem fuso. A tela anexa "Z" e renderiza em America/Sao_Paulo
    (``packages/core/src/formato.ts``); imprimir o UTC cru aqui deslocaria o
    papel em 3 horas em relação à tela — e, numa coleta das 22h, deslocaria o
    DIA, fazendo o aviso de janela efetiva dizer outubro onde a tela diz
    setembro. As datas do PERÍODO não passam por aqui de propósito: elas vêm de
    ``periodos.resolver`` já no fuso da escola.
    """
    if not iso:
        return SEM_DADO
    try:
        return para_br(datetime.fromisoformat(iso)).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return str(iso)


def _intervalo(periodo: dict) -> str:
    """O intervalo por extenso. Período ABERTO não é período faltando.

    O preset "tudo" devolve início e fim nulos de propósito — é "todo o
    histórico". Imprimir "sem dado a sem dado" faria o relatório parecer
    quebrado justamente quando ele está completo.
    """
    ini, fim = periodo.get("inicio"), periodo.get("fim")
    if ini and fim:
        return f"{_data(ini)} a {_data(fim)}"
    if fim:
        return f"até {_data(fim)}"
    if ini:
        return f"a partir de {_data(ini)}"
    return "todo o histórico registrado"


def _slug(texto: str, limite: int = 40) -> str:
    """Pedaço de nome de arquivo seguro: sem acento, sem separador de caminho.

    O nome do arquivo é montado a partir de dado do banco (nome de turma, de
    aluno). Em vez de confiar nesse texto, reduzimos ao alfabeto [a-z0-9-] — o
    que torna travessia de diretório impossível, e não meramente improvável.
    """
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    texto = texto.encode("ascii", "ignore").decode("ascii").lower()
    texto = re.sub(r"[^a-z0-9]+", "-", texto).strip("-")
    return texto[:limite].strip("-")


def nome_arquivo(dados: dict) -> str:
    """``constela-relatorio-<escopo>[-<quem>]-<inicio>_<fim>.pdf``.

    As duas datas entram porque "2026-09" não distingue um mês de um período
    personalizado que começa no meio dele — e o arquivo costuma ser arquivado
    solto, longe da tela que explicava o recorte.
    """
    escopo = dados.get("escopo", {}) or {}
    tipo = _slug(escopo.get("tipo") or "escola") or "escola"
    partes = ["constela", "relatorio", tipo]
    quem = _slug(_quem(dados))
    if quem:
        partes.append(quem)
    periodo = dados.get("periodo", {}) or {}
    ini, fim = periodo.get("inicio"), periodo.get("fim")
    if ini and fim:
        partes.append(f"{str(ini)[:10]}_{str(fim)[:10]}")
    else:
        partes.append(agora_br().strftime("%Y-%m-%d"))
    return "-".join(p for p in partes if p) + ".pdf"


def _quem(dados: dict) -> str:
    """Nome da turma ou do estudante do recorte.

    Lido do resultado quando ele existe; do PEDIDO (o id) quando não existe. Um
    relatório individual de criança já transferida tem coorte vazia — o motor
    filtra por ``status == "ativo"`` —, e sem este recuo o documento sairia sem
    sujeito nenhum: nem nome, nem id, nem no arquivo.
    """
    escopo_d = dados.get("escopo") or {}
    escopo = escopo_d.get("tipo")
    linhas = dados.get("por_aluno") or []
    if escopo == "aluno":
        if linhas:
            return str(linhas[0].get("nome") or "")
        return str(escopo_d["aluno_id"]) if escopo_d.get("aluno_id") else ""
    if escopo == "turma":
        turmas = dados.get("por_turma") or []
        if turmas:
            return str(turmas[0].get("turma") or "")
        if linhas:
            return str(linhas[0].get("turma") or "")
        return str(escopo_d["turma_id"]) if escopo_d.get("turma_id") else ""
    return ""


def _coorte_vazia(dados: dict) -> str:
    """O aviso de que NÃO houve quem medir — que é diferente de não ter havido
    atividade. Sem ele, o relatório de uma criança transferida se lê como
    "ela não fez nada", quando o certo é "ela não está ativa neste ano"."""
    if (dados.get("alunos") or {}).get("considerados"):
        return ""
    # A frase ESSENCIAL vem primeiro: na tabela de reserva só a primeira cabe.
    return ("Nenhum estudante ATIVO neste recorte — os zeros não são "
            "inatividade. Não houve quem medir: confira a matrícula e a "
            "situação (transferido, inativo) antes de concluir qualquer coisa.")


# ------------------------------------------------------- a fonte única dos nºs
def linhas_resumo(dados: dict) -> list[tuple[str, str, str]]:
    """(rótulo, valor, de onde vem) — a fonte ÚNICA dos números impressos.

    Alimenta o PDF de vitrine E o PDF de reserva, e é o que o teste de paridade
    compara contra o dicionário do motor. Toda métrica que o motor marca como
    não calculável sai como texto, nunca como número.
    """
    linhas: list[tuple[str, str, str]] = []
    alunos = dados.get("alunos") or {}
    linhas.append(("Estudantes no recorte", _num(alunos.get("considerados")),
                   "ativos matriculados no ano letivo"))
    linhas.append(("Com atividade no período", _num(alunos.get("com_atividade")), ""))
    linhas.append(("Sem atividade no período", _num(alunos.get("sem_atividade")), ""))

    ele = dados.get("elefante")
    if ele is not None:
        linhas.append(("Livros novos", _num(ele.get("livros_novos")),
                       "o mesmo número da premiação"))
        linhas.append(("Tempo de leitura", _tempo(ele.get("tempo_min")),
                       "tempo informado por livro novo"))
        linhas.append(("Estudantes com livro novo", _num(ele.get("alunos_com_livro_novo")), ""))
        linhas.append(("Livros com atividade", _num(ele.get("livros_com_atividade")),
                       "inclui releitura"))
        linhas.append(("Livros relidos", _num(ele.get("livros_relidos")),
                       "livro lido na janela cuja 1ª importação é anterior a ela"))
        linhas.append(("Registros de leitura", _num(ele.get("eventos_leitura")),
                       "piso de atividade, não contagem de sessões"))
        # Se NINGUÉM do recorte teve coleta na janela, o "0" das questões não é
        # medição — é ausência. O próprio módulo escreveu a regra lá em cima:
        # zero é uma afirmação. Aqui ela vale também para o acumulado.
        tent, cert = ele.get("questoes_tentativas"), ele.get("questoes_acertos")
        considerados = (dados.get("alunos") or {}).get("considerados") or 0
        vazio = considerados == 0
        ninguem = not vazio and (ele.get("alunos_sem_retrato") or 0) >= considerados
        sem_numero = vazio or ninguem or tent is None
        cob = ele.get("cobertura_questoes") or {}
        fonte = ("nenhum estudante no recorte" if vazio
                 else "nenhuma coleta na janela" if ninguem
                 else "as questões não vieram da plataforma" if (
                     tent is None and cob.get("alunos_questoes_nao_vieram"))
                 else "uma coleta só por estudante: sem diferença a medir" if tent is None
                 else "COBERTURA PARCIAL - ver nota" if cob.get("status") == "parcial"
                 else "INCLUI antes do início - ver nota" if cob.get("status") == "ampliada"
                 else "diferença entre coletas")
        linhas.append(("Questões tentadas", SEM_DADO if sem_numero else _num(tent), fonte))
        linhas.append(("Questões corretas", SEM_DADO if sem_numero else _num(cert), ""))
        linhas.append(("Sem coleta na janela", _num(ele.get("alunos_sem_retrato")),
                       "ausência de coleta, não zero"))
        linhas.append(("Tempo por registro de leitura", SEM_SUPORTE,
                       "a plataforma soma o tempo por livro - ver as notas finais"))

    mat = dados.get("matific")
    if mat is not None:
        estado_m = (mat.get("cobertura") or {}).get("status")
        # Uma coleta só por estudante: a regra oficial dá 0, mas esse 0 não mede
        # o período — o documento não o imprime como número.
        sem_medida = estado_m == "sem_intervalo"
        ressalva_m = ("COBERTURA PARCIAL - ver nota" if estado_m == "parcial"
                      else "uma coleta só: o 0 oficial não mede" if sem_medida
                      else "regra oficial - ver nota" if estado_m == "regra_oficial"
                      else "ganho entre coletas")
        linhas.append(("Atividades (Matific)",
                       SEM_DADO if sem_medida else _num(mat.get("atividades")), ressalva_m))
        linhas.append(("Estrelas (Matific)",
                       SEM_DADO if sem_medida else _num(mat.get("estrelas")),
                       ressalva_m if estado_m in ("parcial", "sem_intervalo") else ""))
        linhas.append(("Estudantes com ganho", _num(mat.get("alunos_com_atividade")), ""))
        linhas.append(("Sem coleta na janela (Matific)", _num(mat.get("alunos_sem_retrato")),
                       "ausência de coleta, não zero"))
        linhas.append(("Questões (Matific)", SEM_SUPORTE,
                       "não existe este contador na plataforma"))
    return linhas


# ------------------------------------------------------------------ o corpo
def _subtitulo(dados: dict) -> str:
    periodo = dados.get("periodo") or {}
    escopo = (dados.get("escopo") or {}).get("tipo") or "escola"
    partes = [periodo.get("rotulo") or "", dados.get("plataformas_rotulo") or ""]
    quem = _quem(dados)
    partes.append(f"{_ROTULO_ESCOPO.get(escopo, escopo)}{': ' + quem if quem else ''}")
    partes.append(f"Gerado em {agora_br().strftime('%d/%m/%Y às %H:%M')}")
    return _esc_html(" · ".join(p for p in partes if p))


def _tiles(dados: dict) -> list[tuple[str, str]]:
    """Quatro números de capa. Ordem fixa por plataforma, para dois relatórios
    do mesmo recorte serem comparáveis de relance."""
    alunos = dados.get("alunos") or {}
    ele, mat = dados.get("elefante"), dados.get("matific")
    tiles = [(_num(alunos.get("considerados")), "estudantes no recorte"),
             (_num(alunos.get("com_atividade")), "com atividade")]
    if ele is not None:
        tiles.append((_num(ele.get("livros_novos")), "livros novos"))
        tiles.append((_tempo(ele.get("tempo_min")), "tempo de leitura")
                     if mat is None else
                     (_num(ele.get("livros_com_atividade")), "livros com atividade"))
    if mat is not None:
        sem_medida = (mat.get("cobertura") or {}).get("status") == "sem_intervalo"
        tiles.append((SEM_DADO if sem_medida else _num(mat.get("atividades")),
                      "atividades de matemática"))
    return tiles[:5]


def _periodo_html(dados: dict) -> str:
    periodo = dados.get("periodo") or {}
    escola = dados.get("escola") or {}
    escopo = dados.get("escopo") or {}
    itens = [
        ("Período", _intervalo(periodo)),
        ("Tipo de período", str(periodo.get("rotulo") or "")),
        ("Plataformas", dados.get("plataformas_rotulo") or ""),
        ("Escopo", _ROTULO_ESCOPO.get(escopo.get("tipo"), str(escopo.get("tipo") or ""))),
        ("Ano letivo", str(escola.get("ano_letivo") or "")),
    ]
    quem = _quem(dados)
    if quem:
        itens.insert(4, ("Recorte", quem))
    # O PDF circula SOZINHO. Sem esta linha, o relatório de uma professora com
    # duas turmas sai rotulado "Escola inteira" e, encaminhado à secretaria,
    # lê-se como o mês da escola. Os números estariam certos e a etiqueta,
    # errada — que é a forma mais fácil de um relatório mentir.
    restrito = escopo.get("restrito_a_turmas")
    if restrito:
        itens.insert(len(itens) - 1,
                     ("Recorte do usuário",
                      f"{len(restrito)} turma(s) vinculada(s) ao cadastro de quem "
                      f"gerou — NÃO é a escola inteira"))
    corpo = "".join(
        f'<tr><td class="esq">{_esc_html(r)}</td>'
        f'<td class="esq rp-val">{_esc_html(v)}</td></tr>' for r, v in itens)
    return ('<h2 class="secao">IDENTIFICAÇÃO</h2>'
            '<table class="tab"><thead><tr><th class="esq">Campo</th>'
            '<th class="esq">Valor</th></tr></thead>'
            f'<tbody>{corpo}</tbody></table>')


def _resumo_html(dados: dict) -> str:
    corpo = []
    for rotulo, valor, fonte in linhas_resumo(dados):
        vazio = valor in (SEM_SUPORTE, SEM_DADO)
        corpo.append(
            f'<tr><td class="esq">{_esc_html(rotulo)}</td>'
            f'<td class="{"rp-vazio" if vazio else "rp-val"}">{_esc_html(valor)}</td>'
            f'<td class="esq rp-fonte">{_esc_html(fonte)}</td></tr>')
    return ('<h2 class="secao">RESUMO DO PERÍODO</h2>'
            '<table class="tab"><thead><tr><th class="esq">Indicador</th>'
            '<th>Valor</th><th class="esq">De onde vem</th></tr></thead>'
            f'<tbody>{"".join(corpo)}</tbody></table>')


def _avisos_janela(dados: dict) -> list[tuple[str, str, str]]:
    """(rótulo, primeira coleta, última coleta) de cada número que vem de
    diferença entre COLETAS. Fonte única: alimenta a vitrine e a reserva.

    As duas pontas saem SEPARADAS porque, na tabela do fpdf, uma célula longa é
    cortada — e uma data cortada ("29/09/2026 23:3...") se lê como outra data,
    exatamente como um número cortado.
    """
    saida = []
    for bloco, rotulo, chave in (
            (dados.get("elefante"), "Questões do Elefante", "janela_efetiva_questoes"),
            (dados.get("matific"), "Matific", "janela_efetiva")):
        janela = (bloco or {}).get(chave)
        if janela:
            base = janela.get("data_base_mais_antiga")
            # Base ausente significa "a conta partiu do zero" (não havia coleta
            # anterior à janela), não "falta dado".
            saida.append((rotulo,
                          _data_hora(base) if base else "a primeira coleta",
                          _data_hora(janela.get("data_atual_mais_recente"))))
    return saida


def _duracao(horas) -> str:
    if horas is None:
        return ""
    horas = int(horas)
    return f"{horas} h" if horas < 48 else f"{horas // 24} dias"


def _avisos_cobertura(dados: dict) -> list[dict]:
    """PERÍODO PEDIDO × COBERTURA DAS COLETAS de cada número de retrato — a
    mesma regra da tela (``AvisoCobertura`` em RelatorioPeriodo.tsx). O período
    pedido é a referência; quando as coletas não o cobrem exatamente, o
    documento diz o que falta (ou sobra) e por quê.

    ``motivos``: frases inteiras (vitrine). ``curtos``: pares (valor, detalhe)
    para a reserva, com a cláusula decisiva NA FRENTE — a célula do fpdf corta o
    fim, e um motivo cortado antes de "não está na conta" não diz nada."""
    saida = []
    for bloco, rotulo, chave in (
            (dados.get("elefante"), "Questões do Elefante", "cobertura_questoes"),
            (dados.get("matific"), "Matific", "cobertura")):
        c = (bloco or {}).get(chave)
        if not c:
            continue
        oficial = c.get("regra") == "oficial_matific"
        ini, fim = c.get("periodo_inicio"), c.get("periodo_fim")
        efetivo = c.get("periodo_fim_efetivo")
        pedido_curto = f"{_data(ini)} a {_data(fim)}" if ini else (
            f"todo o histórico (até {_data(efetivo)})" if efetivo else "todo o histórico")
        andamento = (f"em andamento, até {_data(efetivo)}"
                     if ini and efetivo and fim and efetivo < fim else "")
        pedido = pedido_curto + (f" ({andamento})" if andamento else "")
        # Sem coleta-base, a conta parte do início do contador da plataforma. A frase
        # muda de forma, não só de palavra: "de" + "o início do contador" dava "de o
        # início" (a tela monta igual, em ``AvisoCobertura``).
        tem_base = bool(c.get("coleta_inicio"))
        de = _data_hora(c["coleta_inicio"]) if tem_base else "o início do contador"
        ate = _data_hora(c.get("coleta_fim")) if c.get("coleta_fim") else SEM_DADO
        medidos = c.get("alunos_medidos")
        if medidos is None:      # API anterior ao campo
            medidos = ((c.get("alunos_cobertura_completa") or 0)
                       + (c.get("alunos_cobertura_parcial") or 0) + (c.get("alunos_ampliados") or 0))
        motivos, curtos = [], []

        def para(n):
            return f" para {_num(n)} estudante(s)" if n and n < medidos else ""

        def qtd(n):
            return f" ({_num(n)} est.)" if n and n < medidos else ""

        if not c.get("inicio_coberto") and c.get("alunos_sem_inicio"):
            tardio = c.get("coleta_inicio_mais_tardio")
            if c.get("inicio_do_contador_anual") and not tardio:
                motivos.append("o contador do Matific é do ano letivo: o que veio antes "
                               "de 01/01 não entra na conta")
                curtos.append(("NÃO está na conta", "antes de 01/01 (contador anual)"))
            else:
                motivos.append(
                    f"sem coleta no início do período{para(c.get('alunos_sem_inicio'))}: "
                    f"o que foi feito de {_data(ini)} até a primeira coleta"
                    + (f" (até {_data_hora(tardio)})" if tardio else "")
                    + " não está na conta: o contador que o Constela coleta é acumulado "
                      "desde o início da conta e não diz quando cada questão foi "
                      "respondida, então esse trecho não sai das coletas"
                    + (f" (a primeira coleta já trazia {_num(c['acumulado_na_primeira_coleta'])} "
                       "questões acumuladas, de datas que o contador não informa)"
                       if c.get("acumulado_na_primeira_coleta") else "")
                    + ("" if oficial else
                       ". O Elefante guarda o histórico datado por aluno (Questões "
                       "Respondidas), que o Constela ainda não coleta"))
                curtos.append(("NÃO está na conta" + qtd(c.get("alunos_sem_inicio")),
                               f"{_data(ini)} até {_data_hora(tardio) if tardio else 'a 1a coleta'}"))
        # Houve coleta no início, mas sem as questões (S9): não é "sem coleta no início".
        sq_sem_base = c.get("alunos_inicio_sem_questoes_sem_base") or 0
        if sq_sem_base:
            primeira = c.get("primeira_coleta_inicio_sem_questoes")
            ate_primeira = _data_hora(primeira) if primeira else "a 1a coleta"
            motivos.append(
                f"a coleta do início veio sem as questões{para(sq_sem_base)}: a conta começa "
                "na primeira coleta com as questões"
                + (f" (até {_data_hora(primeira)})" if primeira else "")
                + f", e o que foi feito de {_data(ini)} até ela não está na conta")
            curtos.append(("início sem questões" + qtd(sq_sem_base),
                           f"NÃO conta {_data(ini)} até {ate_primeira}"))
        if not c.get("fim_coberto") and c.get("alunos_sem_fim"):
            cedo = _data_hora(c.get("coleta_fim_mais_cedo") or c.get("coleta_fim"))
            motivos.append(
                f"a última coleta{para(c.get('alunos_sem_fim'))} é de {cedo}: o que veio "
                f"depois, até {_data(efetivo or fim)}, não está na conta")
            curtos.append(("NÃO está na conta" + qtd(c.get("alunos_sem_fim")), f"depois de {cedo}"))
        ampliados = c.get("alunos_ampliados")
        if c.get("inclui_antes_do_inicio") and (ampliados is None or ampliados > 0):
            antecedencia = _duracao(c.get("antecedencia_max_horas"))
            # A base destes alunos, sem a dos que tiveram a coleta do início sem questões.
            base_amp = c.get("coleta_base_ampliados") or c.get("coleta_inicio")
            de_amp = _data_hora(base_amp) if base_amp else "o início do contador"
            base = (f"a coleta-base é de {de_amp}" if base_amp
                    else "a conta parte do início do contador")
            motivos.append(
                f"não há coleta perto do início{para(ampliados)}: {base}"
                + (f", {antecedencia} antes de {_data(ini)}" if antecedencia else "")
                + " - o número INCLUI a atividade desse intervalo")
            curtos.append(("INCLUI antes do início" + qtd(ampliados), f"desde {de_amp}"))
        sq_com_base = c.get("alunos_inicio_sem_questoes") or 0
        if sq_com_base:
            base_sq = c.get("coleta_base_inicio_sem_questoes")
            antecedencia = _duracao(c.get("antecedencia_inicio_sem_questoes_horas"))
            motivos.append(
                f"a coleta do início veio sem as questões{para(sq_com_base)}: a conta parte "
                + (f"da coleta de {_data_hora(base_sq)}" if base_sq else "da coleta anterior")
                + (f", {antecedencia} antes de {_data(ini)}," if antecedencia else "")
                + " e INCLUI a atividade desse intervalo")
            curtos.append(("INCLUI antes do início" + qtd(sq_com_base),
                           (f"desde {_data_hora(base_sq)}: " if base_sq else "")
                           + "início sem questões"))
        n_sem = c.get("alunos_sem_intervalo") or 0
        if n_sem:
            if oficial:
                motivos.append(
                    f"{_num(n_sem)} estudante(s) com uma única coleta no período entram "
                    "com 0 pela regra oficial (a mesma das premiações): esse 0 não "
                    "mede o período")
                curtos.append((f"{_num(n_sem)} com 0 oficial", "uma coleta só: NÃO mede"))
            elif (c.get("alunos_sem_intervalo_so_inicio") or 0) >= n_sem:
                motivos.append(
                    f"{_num(n_sem)} estudante(s) só têm a coleta que mede o início do "
                    "período - a próxima medirá o que veio depois; até lá ficam fora "
                    "da conta (não contam como zero)")
                curtos.append((f"{_num(n_sem)} sem intervalo", "só a coleta do início"))
            else:
                motivos.append(
                    f"{_num(n_sem)} estudante(s) com uma única coleta no período ficam "
                    "fora da conta (não contam como zero)")
                curtos.append((f"{_num(n_sem)} sem intervalo", "fora da conta, NÃO é zero"))
        if c.get("alunos_contador_regrediu"):
            n = c["alunos_contador_regrediu"]
            motivos.append(
                f"{_num(n)} estudante(s) com o contador da plataforma DIMINUINDO no "
                "período (contas trocadas ou fundidas na mesma ficha) ficam fora da conta")
            curtos.append((f"{_num(n)} contador caiu", "fora da conta"))
        if c.get("alunos_sem_coleta_no_periodo"):
            n = c["alunos_sem_coleta_no_periodo"]
            motivos.append(
                f"{_num(n)} estudante(s) coletados antes e depois do período, mas sem "
                "nenhuma coleta dentro dele, ficam fora da conta")
            curtos.append((f"{_num(n)} sem coleta no período", "fora da conta"))
        if c.get("alunos_coleta_interrompida"):
            n = c["alunos_coleta_interrompida"]
            motivos.append(
                f"{_num(n)} estudante(s) coletados antes do período e sem nenhuma "
                "coleta que entre na conta (a coleta parou ou falhou para eles) "
                "ficam fora da conta")
            curtos.append((f"{_num(n)} coleta interrompida", "fora da conta"))
        turmas_sem = c.get("turmas_sem_coleta") or []
        if turmas_sem:
            nomes = ", ".join(str(t.get("turma") or t.get("turma_id")) for t in turmas_sem)
            motivos.append(f"turma(s) sem nenhuma coleta no período, fora da conta: {nomes}")
            curtos.append((f"{_num(len(turmas_sem))} turma(s) sem coleta", nomes))
        nao_vieram = c.get("alunos_questoes_nao_vieram") or 0
        if nao_vieram:
            motivos.append(
                f"{_num(nao_vieram)} estudante(s) com coleta no período em que a "
                "plataforma não mandou as questões (a equipe do Constela precisa ajustar a "
                "coleta dessa plataforma): essa coleta não mede as questões, e a conta "
                "deles vai só até a coleta anterior, ou fica fora dela")
            curtos.append((f"{_num(nao_vieram)} sem questões na coleta",
                           "a plataforma não mandou: NÃO medido"))
        saida.append({"rotulo": rotulo, "status": c.get("status"), "oficial": oficial,
                      "pedido": pedido, "pedido_curto": pedido_curto, "andamento": andamento,
                      "nao_vieram": nao_vieram,
                      "so_inicio": (c.get("alunos_sem_intervalo_so_inicio") or 0) >= n_sem > 0,
                      "de": de, "ate": ate, "tem_base": tem_base,
                      "em_andamento": bool(c.get("em_andamento")),
                      "motivos": motivos, "curtos": curtos})
    return saida


def _cobertura_html(aviso: dict) -> str:
    rotulo, pedido = _esc_html(aviso["rotulo"]), _esc_html(aviso["pedido"])
    de, ate = _esc_html(aviso["de"]), _esc_html(aviso["ate"])
    # Sem coleta-base: "desde o início do contador até …" (nunca "de o início").
    disponivel = f"{de} a {ate}" if aviso["tem_base"] else f"desde o início do contador até {ate}"
    medido_pelas_coletas = f"de {disponivel}" if aviso["tem_base"] else disponivel
    coleta_base = f"a coleta-base, {de}," if aviso["tem_base"] else "o início do contador"
    motivos = "".join(f" {_esc_html(m[0].upper() + m[1:])}." for m in aviso["motivos"])
    status = aviso["status"]
    if status == "sem_intervalo":
        if aviso["oficial"]:
            return (f'<div class="rp-nota"><b>{rotulo}: sem intervalo medido para '
                    f'{pedido}.</b> O 0 da regra oficial (a mesma das premiações) vem de '
                    'uma única coleta por estudante no período e nenhuma antes — ele '
                    'NÃO quer dizer que não houve atividade.</div>')
        if aviso.get("nao_vieram"):
            return (f'<div class="rp-nota"><b>{rotulo}: sem número para {pedido}.</b> A '
                    'plataforma não mandou as questões nas coletas do período (a equipe do '
                    'Constela precisa ajustar a coleta dessa plataforma): sem elas, não há '
                    'diferença a medir (não é zero).</div>')
        if aviso["so_inicio"]:
            return (f'<div class="rp-nota"><b>{rotulo}: sem número para {pedido} ainda.</b> '
                    'A única coleta do período é a que mede o início; a próxima medirá o '
                    'que veio depois (não é zero).</div>')
        return (f'<div class="rp-nota"><b>{rotulo}: sem número para {pedido}.</b> Há uma '
                'única coleta por estudante no período e nenhuma antes — não existe '
                'diferença a medir (não é zero).</div>')
    if status == "completa":
        fim = (f" Em andamento: os dados vão até a coleta de {ate}."
               if aviso["em_andamento"] else "")
        return (f'<div class="rp-nota"><b>{rotulo}:</b> período solicitado {pedido}, '
                f'medido pelas coletas {medido_pelas_coletas}.{fim}</div>')
    if status == "regra_oficial":
        return (f'<div class="rp-nota"><b>{rotulo}:</b> período solicitado {pedido}. O '
                'número segue a regra oficial do Matific (a mesma das premiações): '
                f'diferença entre {coleta_base} e a última coleta considerada, {ate} — '
                f'as bordas do período não são verificadas aqui.{motivos}</div>')
    if status == "ampliada":
        return (f'<div class="rp-nota"><b>{rotulo}: o valor INCLUI atividade de antes do '
                f'período.</b> Período solicitado: {pedido}. Intervalo medido pelas '
                f'coletas do Constela: {disponivel}.{motivos}</div>')
    return (f'<div class="rp-nota"><b>{rotulo}: COBERTURA PARCIAL — o valor NÃO '
            f'representa o período completo.</b> Período solicitado: {pedido}. '
            f'Intervalo medido pelas coletas do Constela: {disponivel}.{motivos}</div>')


# ---------------------------------------------- "Como ler estes números"
# Na língua de quem lê o relatório — o MESMO texto da tela (``EXPLICACAO_ELEFANTE``,
# ``EXPLICACAO_MATIFIC`` e ``EXPLICACAO_NAO_RESPONDE`` em
# apps/web/src/pages/RelatorioPeriodo.tsx; ``test_relatorios_periodo_pdf`` confere que
# cada frase daqui está lá). O motor manda em ``suporte`` e ``nao_suportado`` o porquê
# técnico (nome de campo e de tabela, a classificação SUPORTADO/NÃO SUPORTADO): ele
# não vai para o papel, que circula entre professores e em reuniões. Chave que estas
# listas não conhecem cai no texto do motor, como na tela. ``curto`` só serve à
# reserva (fpdf), cuja célula corta o texto longo: a frase inteira, cortada no meio,
# diria outra coisa. Por isso ele cabe INTEIRO na 3ª coluna da reserva: até
# ``LARGURA_DO_CURTO_MM`` na fonte dela (``test_relatorios_periodo_pdf`` mede cada um).
LARGURA_DO_CURTO_MM = 66.0
_ROTULO_CLASSIFICACAO = {"SUPORTADO": "Confiável",
                         "SUPORTADO COM RESSALVA": "Confiável, com um cuidado",
                         "NÃO SUPORTADO": "Não calculado"}

_TEMPO_DE_CADA_LEITURA = (
    "Não dá para saber quanto durou cada leitura: a plataforma informa o tempo somado "
    "de cada livro, não o de cada vez que o aluno o abriu, e esses totais às vezes até "
    "diminuem — o que um total somado não faria. O tempo do período vem do tempo dos "
    "livros novos, o mesmo da premiação “Mais tempo”.")

_EXPLICACAO_ELEFANTE: dict[str, dict] = {
    "livros_novos": {
        "nome": "“Livros novos”",
        "explicacao": "Conta cada livro que apareceu pela primeira vez no relatório da "
                      "plataforma dentro do período. É a mesma conta da premiação “Mais "
                      "livros”: o relatório e o pódio mostram o mesmo número.",
        "cuidado": "Vale a data em que o livro apareceu pela primeira vez no relatório da "
                   "plataforma, e ela não muda depois. Por isso um livro lido de novo não "
                   "entra aqui — ele aparece em “Livros com atividade”, como relido.",
        "curto": "livro relido conta só em Livros com atividade",
    },
    "tempo_min": {
        "nome": "“Tempo de leitura”",
        "explicacao": "Soma o tempo dos livros novos do período. É a mesma conta da "
                      "premiação “Mais tempo”.",
        "cuidado": "A plataforma nem sempre informa o tempo de um livro; quando não "
                   "informa, ele entra como zero. Por isso o total é o mínimo lido no "
                   "período — o tempo real pode ser maior.",
        "curto": "total mínimo: tempo não informado conta zero",
    },
    "livros_com_atividade": {
        "nome": "“Livros com atividade”",
        "explicacao": "Conta os livros diferentes que o aluno abriu no período, inclusive "
                      "os que ele releu, pela data e hora que a plataforma registra em "
                      "cada leitura.",
    },
    "tempo_min_por_evento": {
        "nome": "Tempo de cada leitura",
        "explicacao": _TEMPO_DE_CADA_LEITURA,
    },
    "questoes": {
        "nome": "“Questões”",
        "explicacao": "A plataforma só informa o total de questões que o aluno já "
                      "respondeu desde que começou, sem a data de cada uma. O número do "
                      "período é a diferença entre a coleta do fim e a do início.",
        "cuidado": "Só entra quem tem coleta no período; quem não tem fica fora da conta "
                   "(não conta como zero). Sem coleta no começo do período, a conta começa "
                   "na primeira coleta; sem coleta no fim, termina na última — nos dois "
                   "casos o número não cobre o período inteiro, e o aviso de “Questões”, "
                   "acima, diz quanto falta.",
        "curto": "sem coleta no início ou no fim, não cobre tudo",
    },
}

_EXPLICACAO_MATIFIC = {
    "nome": "“Atividades” e “Estrelas”",
    "explicacao": "O Matific informa o total do ano (atividades e estrelas somadas), não a "
                  "data de cada atividade. O número do período é o total no fim menos o de "
                  "antes do início — a mesma regra das premiações.",
    "cuidado": "Sem coleta dentro do período, o aluno fica fora da conta (falta de dado não "
               "é zero) e é contado em “Sem coleta na janela”.",
    "curto": "sem coleta no período, fica fora (não é zero)",
}

_EXPLICACAO_NAO_RESPONDE: dict[str, dict] = {
    "elefante.tempo_min_por_evento": {
        "nome": "Tempo de cada leitura (Elefante Letrado)",
        "explicacao": _TEMPO_DE_CADA_LEITURA,
        "curto": "o tempo vem somado por livro, não por leitura",
    },
    "matific.questoes": {
        "nome": "Questões (Matific)",
        "explicacao": "O Matific guarda atividades, estrelas e pontuação média, mas não "
                      "conta questões. Mostrar esse número para um período seria inventá-lo.",
        "curto": "o Matific não conta questões",
    },
    "elefante.pontos_de_dificuldade": {
        "nome": "Pontos de dificuldade (Elefante Letrado)",
        "explicacao": "Quem se destaca pela dificuldade dos livros é decidido em "
                      "Premiações, com a régua oficial. Calcular de novo aqui criaria uma "
                      "segunda régua, que poderia discordar do pódio: para mérito, use "
                      "Premiações.",
        "curto": "para mérito, use Premiações (a régua oficial)",
    },
}


def _explicacao(lista: dict, chave: str, s: dict) -> dict:
    """A explicação de um número; sem entrada na lista, o texto que o motor mandou (a
    mesma regra de ``explicacaoDe`` na tela)."""
    return lista.get(chave) or {"nome": re.sub(r"[._]", " ", chave),
                                "explicacao": s.get("por_que") or "",
                                "cuidado": s.get("ressalva")}


def _como_ler(dados: dict) -> list[tuple[str, dict, str]]:
    """(plataforma, explicação, classificação) de cada número de "Como ler estes
    números" — a fonte única da vitrine e da reserva, com a regra da tela: o que o
    motor lista em ``nao_suportado`` fica SÓ em "O que este relatório não responde",
    sem repetir aqui com o selo "Não calculado"; do Matific, só "Atividades" e
    "Estrelas" (as questões dele estão naquela lista)."""
    fora = {(i.get("plataforma"), i.get("metrica")) for i in dados.get("nao_suportado") or []}
    itens = []
    for chave, s in ((dados.get("elefante") or {}).get("suporte") or {}).items():
        if (isinstance(s, dict) and s.get("classificacao")
                and ("elefante", chave) not in fora):
            itens.append(("Elefante Letrado", _explicacao(_EXPLICACAO_ELEFANTE, chave, s),
                          s["classificacao"]))
    sup_mat = (dados.get("matific") or {}).get("suporte") or {}
    if sup_mat.get("classificacao"):
        itens.append(("Matific", _EXPLICACAO_MATIFIC, sup_mat["classificacao"]))
    return itens


def _o_que_nao_responde(dados: dict) -> list[dict]:
    """A explicação de cada item de ``nao_suportado``, na língua da tela."""
    return [_explicacao(_EXPLICACAO_NAO_RESPONDE,
                        f"{i.get('plataforma')}.{i.get('metrica')}", i)
            for i in dados.get("nao_suportado") or []]


def _ressalvas(dados: dict) -> list[tuple[str, str]]:
    """(indicador, cuidado ao ler) dos números de "Como ler estes números" que têm um
    cuidado — o "Cuidado ao ler" da tela, curto para caber na célula da reserva."""
    return [(e["nome"], e.get("curto") or _primeira_frase(e["cuidado"]))
            for _plataforma, e, _classificacao in _como_ler(dados) if e.get("cuidado")]


def _janela_efetiva_html(dados: dict) -> str:
    """Avisa quando um número veio de diferença entre COLETAS e, por isso, cobre
    um intervalo diferente do pedido. Esconder isso seria mentir sobre o recorte.

    Com a ``cobertura`` (API atual), o aviso é PERÍODO PEDIDO × COBERTURA; o
    aviso antigo ("a conta vai de ... a ...") só sobra para dado sem ela."""
    avisos = _avisos_cobertura(dados)
    cobertos = {a["rotulo"] for a in avisos}
    observacoes = {
        "Questões do Elefante": ((dados.get("elefante") or {})
                                 .get("janela_efetiva_questoes") or {}).get("observacao"),
        "Matific": ((dados.get("matific") or {})
                    .get("janela_efetiva") or {}).get("observacao"),
    }
    return "".join(_cobertura_html(a) for a in avisos) + "".join(
        f'<div class="rp-nota"><b>{_esc_html(rotulo)}:</b> a conta vai de '
        f'{_esc_html(de)} a {_esc_html(ate)} — '
        f'{_esc_html(observacoes.get(rotulo) or "")}</div>'
        for rotulo, de, ate in _avisos_janela(dados) if rotulo not in cobertos)


_SELO = {"SUPORTADO": "ok", "SUPORTADO COM RESSALVA": "res", "NÃO SUPORTADO": "nao"}


def _suporte_html(dados: dict) -> str:
    """"Como ler estes números": o que cada número conta e o cuidado ao lê-lo, com a
    etiqueta da tela ("Confiável", "Confiável, com um cuidado").

    Sai no papel porque o PDF circula sozinho — longe da tela que explicava.
    """
    linhas = []
    for plataforma, e, classificacao in _como_ler(dados):
        classe = _SELO.get(classificacao, "nao")
        cuidado = (f'<br><span class="rp-porque"><b>Cuidado ao ler:</b> '
                   f'{_esc_html(e["cuidado"])}</span>' if e.get("cuidado") else "")
        linhas.append(
            f'<tr><td class="esq nome">{_esc_html(e["nome"])}'
            f'<br><span class="rp-fonte">{_esc_html(plataforma)}</span></td>'
            f'<td><span class="rp-selo {classe}">'
            f'{_esc_html(_ROTULO_CLASSIFICACAO.get(classificacao, classificacao))}</span></td>'
            f'<td class="esq rp-porque">{_esc_html(e["explicacao"])}{cuidado}</td></tr>')
    if not linhas:
        return ""
    return ('<h2 class="secao">COMO LER ESTES NÚMEROS</h2>'
            '<table class="tab"><thead><tr><th class="esq">Indicador</th>'
            '<th>Classificação</th><th class="esq">O que o número conta</th></tr></thead>'
            f'<tbody>{"".join(linhas)}</tbody></table>')


def _nao_suportado_html(dados: dict) -> str:
    itens = _o_que_nao_responde(dados)
    if not itens:
        return ""
    blocos = "".join(
        f'<div class="rp-nota"><b>{_esc_html(e["nome"])}:</b> '
        f'{_esc_html(e["explicacao"])}</div>' for e in itens)
    return ('<h2 class="secao">O QUE ESTE RELATÓRIO NÃO RESPONDE</h2>'
            '<p class="rp-porque">Métrica sem dado histórico suficiente sai declarada, '
            'não estimada: um número aproximado num relatório de gestão vira decisão.</p>'
            + blocos)


def _turmas_html(dados: dict) -> str:
    turmas = dados.get("por_turma")
    if not turmas:
        return ""
    tem_ele = dados.get("elefante") is not None
    tem_mat = dados.get("matific") is not None
    cabeca = ['<th class="esq">Turma</th>', "<th>Estudantes</th>", "<th>Com atividade</th>"]
    if tem_ele:
        cabeca += ["<th>Livros novos</th>", "<th>Tempo</th>",
                   "<th>Com atividade (livros)</th>", "<th>Relidos</th>"]
    if tem_mat:
        cabeca += ["<th>Atividades</th>", "<th>Estrelas</th>"]
    linhas = []
    for t in turmas:
        e, m = t.get("elefante") or {}, t.get("matific") or {}
        nome = t.get("turma") or ""
        turno = f' <span class="rp-fonte">{_esc_html(t["turno"])}</span>' if t.get("turno") else ""
        celulas = [f'<td class="esq nome">{_esc_html(nome)}{turno}</td>',
                   f'<td>{_num(t.get("alunos"))}</td>',
                   f'<td>{_num(t.get("com_atividade"))}</td>']
        if tem_ele:
            celulas += [f'<td class="rp-val">{_num(e.get("livros_novos"))}</td>',
                        f'<td>{_tempo(e.get("tempo_min"))}</td>',
                        f'<td>{_num(e.get("livros_com_atividade"))}</td>',
                        f'<td>{_num(e.get("livros_relidos"))}</td>']
        if tem_mat:
            celulas += [f'<td class="rp-val">{_num(m.get("atividades"))}</td>',
                        f'<td>{_num(m.get("estrelas"))}</td>']
        linhas.append("<tr>" + "".join(celulas) + "</tr>")
    return ('<h2 class="secao">POR TURMA</h2>'
            f'<table class="tab"><thead><tr>{"".join(cabeca)}</tr></thead>'
            f'<tbody>{"".join(linhas)}</tbody></table>')


def _alunos_html(dados: dict) -> str:
    alunos = dados.get("por_aluno")
    if not alunos:
        return ""
    tem_ele = dados.get("elefante") is not None
    tem_mat = dados.get("matific") is not None
    escopo = (dados.get("escopo") or {}).get("tipo")
    cabeca = ['<th>Nº</th>', '<th class="esq">Estudante</th>', "<th>Turma</th>"]
    if tem_ele:
        cabeca += ["<th>Livros novos</th>", "<th>Tempo</th>",
                   "<th>Com atividade</th>", "<th>Relidos</th>"]
    if tem_mat:
        cabeca += ["<th>Atividades</th>", "<th>Estrelas</th>"]
    linhas = []
    for i, a in enumerate(alunos, 1):
        e, m = a.get("elefante") or {}, a.get("matific") or {}
        celulas = [f'<td class="num">{i:02d}</td>',
                   f'<td class="esq nome">{_esc_html(a.get("nome") or "")}</td>',
                   f'<td>{_esc_html(a.get("turma") or "")}</td>']
        if tem_ele:
            celulas += [f'<td class="rp-val">{_num(e.get("livros_novos", 0))}</td>',
                        f'<td>{_tempo(e.get("tempo_min", 0))}</td>',
                        f'<td>{_num(e.get("livros_com_atividade", 0))}</td>',
                        f'<td>{_num(e.get("livros_relidos", 0))}</td>']
        if tem_mat:
            celulas += [f'<td class="rp-val">{_num(m.get("atividades", 0))}</td>',
                        f'<td>{_num(m.get("estrelas", 0))}</td>']
        linhas.append("<tr>" + "".join(celulas) + "</tr>")
    titulo = "ESTUDANTE" if escopo == "aluno" else "POR ESTUDANTE"
    return (f'<h2 class="secao">{titulo}</h2>'
            f'<table class="tab"><thead><tr>{"".join(cabeca)}</tr></thead>'
            f'<tbody>{"".join(linhas)}</tbody></table>')


def montar_html(dados: dict, logos: tuple[str, str] | None = None) -> str:
    """O documento inteiro em HTML, pronto para o Chromium."""
    escola = dados.get("escola") or {}
    intro = (
        "Consulta do que aconteceu na janela de datas indicada. O intervalo é "
        "inclusivo nas duas pontas e vem do mesmo serviço de períodos que define "
        "as premiações — &quot;setembro&quot; aqui é o mesmo &quot;setembro&quot; "
        "do pódio. Este documento não atribui mérito, não altera posição no "
        "ranking e não substitui o certificado.")
    vazia = _coorte_vazia(dados)
    corpo = (_CSS_EXTRA
             + (f'<div class="rp-nota"><b>Atenção:</b> {_esc_html(vazia)}</div>'
                if vazia else "")
             + _periodo_html(dados)
             + _resumo_html(dados)
             + _janela_efetiva_html(dados)
             + _turmas_html(dados)
             + _alunos_html(dados)
             + _suporte_html(dados)
             + _nao_suportado_html(dados))
    return _relatorio_shell("Relatório por Período", str(escola.get("nome") or ""),
                            _subtitulo(dados), _tiles(dados), intro, corpo, logos)


# A tabela da reserva passa por `_couber`, que corta a célula na largura REAL e
# termina em "...". Um rótulo cortado é feio; um NÚMERO cortado é outra coisa:
# "98.765" vira "98.7..." e se lê como noventa e oito mil e setecentos. Por isso
# cada plataforma ocupa a sua própria coluna, em vez de uma frase só — e o teste
# `test_reserva_nao_corta_numero` guarda isso.
def _detalhe_elefante(bloco: dict) -> str:
    """Zero aqui é zero de verdade: o estudante está no recorte, foi medido e
    não produziu — diferente de `sem dado`."""
    return (f"{_num(bloco.get('livros_novos', 0))} livros · "
            f"{_tempo(bloco.get('tempo_min', 0))} · "
            f"{_num(bloco.get('livros_relidos', 0))} relidos")


def _detalhe_matific(bloco: dict) -> str:
    return (f"{_num(bloco.get('atividades', 0))} atividades · "
            f"{_num(bloco.get('estrelas', 0))} estrelas")


# Tipografia que NÃO existe em latin-1 e, portanto, não sobrevive ao PDF de
# reserva (fpdf usa fontes latin-1). Mapeamos para o equivalente ASCII antes de
# entregar a célula — senão vira "?" e o leitor lê defeito do relatório.
_FORA_DO_LATIN1 = {
    "—": "-", "–": "-", "―": "-",            # travessões
    "“": '"', "”": '"', "„": '"',            # aspas curvas
    "‘": "'", "’": "'",                       # apóstrofos curvos
    "…": "...", "•": "-", "→": "->", "≈": "~",
}


def _sem_tipografia(texto) -> str:
    """Texto pronto para a fonte latin-1 do PDF de reserva.

    Isto não é zelo estético: o motor escreve travessão nos motivos de
    "não suportado" (`MOTIVO_MATIFIC_QUESTOES`), e as DUAS versões de `_latin1`
    em `services/relatorios.py` tratam o travessão de formas diferentes — a
    commitada o transforma em "?". Normalizando aqui, a saída é a mesma com ou
    sem o trabalho paralelo presente, que é o que a nota de acoplamento no topo
    deste módulo promete.
    """
    texto = str(texto if texto is not None else "")
    for de, para in _FORA_DO_LATIN1.items():
        texto = texto.replace(de, para)
    return texto


def _curto(texto: str, limite: int = 34) -> str:
    """Encurta um RÓTULO (nome de turma/estudante) na tabela da reserva.

    A largura de cada coluna em `gerar_pdf` é proporcional à célula mais larga
    dela: um nome comprido rouba espaço das colunas de NÚMERO ao lado, e é lá
    que o corte dói — "98.765" virando "98.7..." se lê como outro número. Nome
    cortado o leitor reconhece; número cortado, não.
    """
    texto = str(texto or "").strip()
    return texto if len(texto) <= limite else texto[:limite - 1].rstrip() + "."


def _primeira_frase(texto: str, limite: int = 72) -> str:
    """O motivo cabe na tela e no PDF de vitrine por inteiro; na reserva cabe a
    primeira frase. Melhor uma frase completa do que um parágrafo cortado."""
    texto = str(texto or "").strip()
    corte = texto.find(". ")
    if 0 < corte <= limite:
        return texto[:corte + 1]
    return texto if len(texto) <= limite else texto[:limite].rsplit(" ", 1)[0] + "."


def _reserva(dados: dict, cor: str) -> bytes:
    """PDF simples (fpdf), quando não há Chromium.

    Carrega os MESMOS números do relatório de vitrine — resumo, turmas e
    estudantes. Uma reserva que perdesse as tabelas pareceria completa sem
    estar; e é justamente ela que roda na integração contínua, onde o job de
    testes do backend instala o `requirements.txt` mas NÃO baixa o Chromium.
    """
    escola = dados.get("escola") or {}
    periodo = dados.get("periodo") or {}
    tem_ele = dados.get("elefante") is not None
    tem_mat = dados.get("matific") is not None
    cabecalho = ["Indicador", "Valor", "Detalhe"]
    linhas: list[list] = [
        ["Período", _intervalo(periodo), str(periodo.get("rotulo") or "")],
        ["Plataformas", dados.get("plataformas_rotulo") or "", ""],
        ["Escopo", _ROTULO_ESCOPO.get((dados.get("escopo") or {}).get("tipo"), ""),
         _quem(dados)],
    ]
    # Em três células CURTAS: a tabela do fpdf corta a célula longa, e era
    # justamente a palavra "inatividade" que se perdia — a única que importa.
    if _coorte_vazia(dados):
        linhas.append(["ATENÇÃO: nenhum estudante ATIVO",
                       "os zeros NÃO são inatividade",
                       "confira matrícula e situação"])
    restrito = (dados.get("escopo") or {}).get("restrito_a_turmas")
    if restrito:
        # Curto para caber inteiro na 3ª coluna (como os ``curto`` de "Como ler").
        linhas.append(["Recorte do usuário", f"{len(restrito)} turma(s)",
                       "turmas de quem gerou - não é a escola inteira"])
    linhas.append(["RESUMO DO PERÍODO", "", ""])
    linhas += [list(linha) for linha in linhas_resumo(dados)]

    # UMA LINHA POR PLATAFORMA. O detalhe vai para a terceira coluna, que é a
    # larga; espremido na segunda, ele era cortado e a célula terminava logo
    # depois de um número ("4.567..."), que se lê como número truncado.
    def _entidade(rotulo: str, ele: dict, mat: dict) -> None:
        primeiro = True
        for ligado, nome, detalhe in ((tem_ele, "Elefante", _detalhe_elefante(ele)),
                                      (tem_mat, "Matific", _detalhe_matific(mat))):
            if not ligado:
                continue
            linhas.append([rotulo if primeiro else "", nome, detalhe])
            primeiro = False

    turmas = dados.get("por_turma") or []
    if turmas:
        linhas.append(["POR TURMA", "", ""])
        for t in turmas:
            _entidade(f"{_curto(t.get('turma'), 22)} "
                      f"({_num(t.get('com_atividade'))}/{_num(t.get('alunos'))})",
                      t.get("elefante") or {}, t.get("matific") or {})

    alunos = dados.get("por_aluno") or []
    if alunos:
        linhas.append(["POR ESTUDANTE", "", ""])
        for a in alunos:
            _entidade(f"{_curto(a.get('nome'), 24)} ({_curto(a.get('turma'), 12)})",
                      a.get("elefante") or {}, a.get("matific") or {})

    # AS RESSALVAS VÃO JUNTO. Carregar o número e deixar para trás o que ele
    # significa — o intervalo real que ele cobre, o piso do tempo, a ausência
    # que não é zero — entrega um documento que parece completo e não está.
    for rotulo, de, ate in _avisos_janela(dados):
        linhas.append([_curto("Janela efetiva · " + rotulo, 30), "de " + de, "a " + ate])
    for aviso in _avisos_cobertura(dados):
        estado = {"completa": "cobertura completa", "parcial": "COBERTURA PARCIAL",
                  "ampliada": "INCLUI ANTES DO INÍCIO", "regra_oficial": "regra oficial",
                  "sem_intervalo": "SEM INTERVALO MEDIDO"}.get(aviso["status"], "")
        linhas.append([_curto("Cobertura · " + aviso["rotulo"], 30), estado,
                       _curto("pedido " + aviso["pedido_curto"], 44)])
        if aviso["andamento"]:
            linhas.append(["", "em andamento", aviso["andamento"].replace("em andamento, ", "")])
        if aviso["status"] == "parcial":
            linhas.append(["", "valor NÃO é o período completo", ""])
        elif aviso["status"] == "ampliada":
            linhas.append(["", "valor NÃO é só o período", ""])
        for valor, detalhe in aviso["curtos"]:
            linhas.append(["", valor, _curto(detalhe, 44)])
    # Um título, como "POR TURMA", e o nome do número sozinho na 1ª coluna: com o "Cuidado
    # ao ler · " em cada linha, ela ficava larga e tirava da 3ª a largura do cuidado curto.
    ressalvas = _ressalvas(dados)
    if ressalvas:
        linhas.append(["CUIDADO AO LER", "", ""])
    for nome, cuidado in ressalvas:
        linhas.append([nome, "", _primeira_frase(cuidado, 72)])

    for e in _o_que_nao_responde(dados):
        linhas.append([e["nome"], SEM_SUPORTE,
                       e.get("curto") or _primeira_frase(e["explicacao"])])

    # TODA célula passa pela normalização: as que eu escrevi e, principalmente,
    # as que vieram do motor.
    linhas = [[_sem_tipografia(c) for c in linha] for linha in linhas]
    return gerar_pdf("Relatório por Período",
                     _sem_tipografia(escola.get("nome")), cor,
                     [_sem_tipografia(c) for c in cabecalho], linhas)


def gerar(dados: dict, *, cor: str, logos: tuple[str, str] | None = None) -> bytes:
    """O PDF. ``dados`` é — e só pode ser — a saída de ``relatorios_periodo.gerar``.

    A queda para a reserva é DELIBERADA (sem Chromium o relatório tem de sair
    mesmo assim), mas não é silenciosa: ela vai para o log. Sem isso, um defeito
    meu em ``montar_html`` se disfarçaria de "esta máquina não tem navegador" e
    ninguém procuraria a causa.
    """
    try:
        return _relatorio_html_pdf(montar_html(dados, logos))
    except Exception:  # noqa: BLE001 — sem Chromium ou falha de render: PDF simples
        log.warning("relatorio_periodo_pdf: caiu na reserva (fpdf)", exc_info=True)
        return _reserva(dados, cor)
