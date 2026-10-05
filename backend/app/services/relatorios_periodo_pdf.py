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
# "0" (zero é uma afirmação: a criança foi medida e não produziu).
SEM_SUPORTE = "não suportado"
SEM_DADO = "sem dado"

log = logging.getLogger(__name__)

_ROTULO_PLATAFORMA = {"elefante": "Elefante Letrado", "matific": "Matific"}
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
                       "Leitura.data - o mesmo número da premiação"))
        linhas.append(("Tempo de leitura", _tempo(ele.get("tempo_min")),
                       "tempo informado por livro novo"))
        linhas.append(("Estudantes com livro novo", _num(ele.get("alunos_com_livro_novo")), ""))
        linhas.append(("Livros com atividade", _num(ele.get("livros_com_atividade")),
                       "EventoAluno.ocorrido_em - inclui releitura"))
        linhas.append(("Livros relidos", _num(ele.get("livros_relidos")),
                       "livro lido na janela cuja 1ª importação é anterior a ela"))
        linhas.append(("Registros de leitura", _num(ele.get("eventos_leitura")),
                       "piso de atividade, não contagem de sessões"))
        # Se NINGUÉM do recorte teve coleta na janela, o "0" das questões não é
        # medição — é ausência. O próprio módulo escreveu a regra lá em cima:
        # zero é uma afirmação. Aqui ela vale também para o acumulado.
        tent, cert = ele.get("questoes_tentativas"), ele.get("questoes_acertos")
        ninguem = (ele.get("alunos_sem_retrato") or 0) >= (
            (dados.get("alunos") or {}).get("considerados") or 0) > 0
        linhas.append(("Questões tentadas", SEM_DADO if ninguem else _num(tent),
                       "nenhuma coleta na janela" if ninguem
                       else "diferença entre coletas"))
        linhas.append(("Questões corretas", SEM_DADO if ninguem else _num(cert), ""))
        linhas.append(("Sem coleta na janela", _num(ele.get("alunos_sem_retrato")),
                       "ausência de coleta, não zero"))
        linhas.append(("Tempo por registro de leitura", SEM_SUPORTE,
                       "o campo é acumulado por livro - ver as notas finais"))

    mat = dados.get("matific")
    if mat is not None:
        linhas.append(("Atividades (Matific)", _num(mat.get("atividades")),
                       "ganho entre coletas"))
        linhas.append(("Estrelas (Matific)", _num(mat.get("estrelas")), ""))
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
        tiles.append((_num(mat.get("atividades")), "atividades de matemática"))
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


def _ressalvas(dados: dict) -> list[tuple[str, str]]:
    """(indicador, ressalva) de tudo que o motor qualificou."""
    saida = []
    for chave, s in ((dados.get("elefante") or {}).get("suporte") or {}).items():
        if isinstance(s, dict) and s.get("ressalva"):
            saida.append((f"Elefante · {chave.replace('_', ' ')}", s["ressalva"]))
    sup_mat = (dados.get("matific") or {}).get("suporte") or {}
    if sup_mat.get("ressalva"):
        saida.append(("Matific · atividades e estrelas", sup_mat["ressalva"]))
    return saida


def _janela_efetiva_html(dados: dict) -> str:
    """Avisa quando um número veio de diferença entre COLETAS e, por isso, cobre
    um intervalo diferente do pedido. Esconder isso seria mentir sobre o recorte."""
    observacoes = {
        "Questões do Elefante": ((dados.get("elefante") or {})
                                 .get("janela_efetiva_questoes") or {}).get("observacao"),
        "Matific": ((dados.get("matific") or {})
                    .get("janela_efetiva") or {}).get("observacao"),
    }
    return "".join(
        f'<div class="rp-nota"><b>{_esc_html(rotulo)}:</b> a conta vai de '
        f'{_esc_html(de)} a {_esc_html(ate)} — '
        f'{_esc_html(observacoes.get(rotulo) or "")}</div>'
        for rotulo, de, ate in _avisos_janela(dados))


_SELO = {"SUPORTADO": "ok", "SUPORTADO COM RESSALVA": "res", "NÃO SUPORTADO": "nao"}


def _suporte_html(dados: dict) -> str:
    """"Como ler estes números": a classificação de cada métrica, com a ressalva.

    Sai no papel porque o PDF circula sozinho — longe da tela que explicava.
    """
    linhas = []

    def item(nome: str, s: dict) -> None:
        classe = _SELO.get(s.get("classificacao"), "nao")
        campo = f'<br><span class="rp-fonte">{_esc_html(s["campo"])}</span>' if s.get("campo") else ""
        ressalva = (f'<br><span class="rp-porque"><b>Ressalva:</b> '
                    f'{_esc_html(s["ressalva"])}</span>' if s.get("ressalva") else "")
        linhas.append(
            f'<tr><td class="esq nome">{_esc_html(nome)}{campo}</td>'
            f'<td><span class="rp-selo {classe}">'
            f'{_esc_html(s.get("classificacao") or "")}</span></td>'
            f'<td class="esq rp-porque">{_esc_html(s.get("por_que") or "")}{ressalva}</td></tr>')

    ele = dados.get("elefante") or {}
    for chave, s in (ele.get("suporte") or {}).items():
        if isinstance(s, dict) and s.get("classificacao"):
            item(f"Elefante · {chave.replace('_', ' ')}", s)
    mat = dados.get("matific") or {}
    sup_mat = mat.get("suporte") or {}
    if sup_mat.get("classificacao"):
        item("Matific · atividades e estrelas", sup_mat)
    if isinstance(sup_mat.get("questoes"), dict):
        item("Matific · questões", sup_mat["questoes"])
    if not linhas:
        return ""
    return ('<h2 class="secao">COMO LER ESTES NÚMEROS</h2>'
            '<table class="tab"><thead><tr><th class="esq">Indicador</th>'
            '<th>Classificação</th><th class="esq">Por quê</th></tr></thead>'
            f'<tbody>{"".join(linhas)}</tbody></table>')


def _nao_suportado_html(dados: dict) -> str:
    itens = dados.get("nao_suportado") or []
    if not itens:
        return ""
    blocos = "".join(
        f'<div class="rp-nota"><b>'
        f'{_esc_html(_ROTULO_PLATAFORMA.get(i.get("plataforma"), i.get("plataforma") or ""))}'
        f' · {_esc_html(str(i.get("metrica") or "").replace("_", " "))}:</b> '
        f'{_esc_html(i.get("por_que") or "")}</div>' for i in itens)
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
        linhas.append(["Recorte do usuário", f"{len(restrito)} turma(s)",
                       "vinculadas ao cadastro de quem gerou - nao e a escola inteira"])
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
    for nome, s_ in _ressalvas(dados):
        linhas.append(["Ressalva · " + nome, "", _primeira_frase(s_, 72)])

    for item in dados.get("nao_suportado") or []:
        rotulo = (f"{_ROTULO_PLATAFORMA.get(item.get('plataforma'), '')} · "
                  f"{str(item.get('metrica') or '').replace('_', ' ')}")
        linhas.append([rotulo.strip(" ·"), SEM_SUPORTE,
                       _primeira_frase(item.get("por_que"))])

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
