"""Engajamento nas plataformas por ESCOLA × SÉRIE num período — sem nenhum dado pessoal
(``GET /redes/{id}/analise/plataformas`` e o bloco de plataformas de
``GET /escolas/{id}/analise``).

COMO (sem regra nova de leitura): por escola, as MESMAS regras do Relatório por Período
(``relatorios_periodo``), que são as das premiações — lidas EM LOTE para todas as escolas
e períodos (ver "Leituras do banco"; ``test_analise_plataformas`` confere os números contra
as funções de uma escola):

* ``resolver_janela`` (o período, pelo serviço oficial ``periodos.resolver``);
* a coorte de ``_coorte`` (alunos ATIVOS matriculados no ano letivo ativo da escola), sem
  o nome; a SÉRIE é ``elegibilidade.ano_premiavel`` (1º ao 5º ano; Fases/EMEI/EJA ficam
  fora do recorte);
* os dois eixos de ``_elefante`` (livros novos e tempo por ``Leitura.data``; atividade por
  ``EventoAluno``); as questões pela diferença entre retratos
  (``relatorios_periodo._diferenca_de_retratos``, com as exclusões de
  ``_elefante_questoes``) e o Matific pelo ganho entre retratos
  (``matific_destaque.ganho_no_periodo``, a regra das premiações) — aplicadas a cada
  aluno com SÓ os retratos que essas regras podem ler, em vez do histórico diário inteiro:
  nas questões, as coletas em volta das bordas do período em BRASÍLIA (a até
  ``TOLERANCIA_BORDA`` delas), a última antes e a primeira e a última dentro, uma linha
  por execução (``_coletas_das_questoes``); no Matific, o último antes do início e o
  primeiro e o último dentro, no instante UTC da regra das premiações
  (``_retratos_essenciais``);
* o nível médio usa o nível CONGELADO da leitura (``coalesce(Leitura.nivel_codigo,
  Livro.nivel_codigo)``, o mesmo das premiações) na posição de ``scoring.POS_DO_NIVEL``.

O que sai é só CONTAGEM e TAXA por (escola, série), nunca ``aluno_id``, nome ou turma —
nem os totais brutos (tentativas, acertos, atividades, estrelas, livros) que refariam uma
taxa escondida. As fórmulas, a coorte, a janela e o ``k`` estão na metodologia
(``docs/analise/METODOLOGIA.md``).

AUSÊNCIA ≠ ZERO: escola sem coleta que cubra o período fica com as métricas NULAS e o
motivo; escola cuja coleta PAROU antes do fim do período (``coleta_parcial``) mostra o que
foi medido, com a data até onde vale, e fica fora das somas da rede e da relação. Aluno
que a plataforma não conhece no período (sem conta no Elefante; sem coleta do Matific
dentro do período) fica FORA do denominador — não conta como zero. Métrica que depende de
um subconjunto (alunos medidos, com questão, com nível, com atividade) só aparece com pelo
menos ``k`` alunos nele.

SUPRESSÃO (decidida só por CONTAGENS da coorte, que não dependem do período): célula
(escola × série) com menos de ``k`` alunos não mostra nem o número de alunos nem as
métricas; e, para a conta "total − visíveis" não revelar a célula pequena, a supressão é
COMPLEMENTAR com FAIXA DE PROTEÇÃO: enquanto as suprimidas somarem menos de ``2k`` alunos,
a menor visível também é suprimida (o mesmo entre as escolas da rede). O motivo é um só
(``suprimido``), para a resposta não dizer qual célula é a pequena. Os blocos do Elefante
e do Matific de uma escola (e da rede) somam SÓ as células (e escolas) visíveis: a
diferença entre o bloco e as partes mostradas é sempre zero.

SUPRESSÃO COMPLEMENTAR POR MÉTRICA (``_PROTEGIDAS``): numa célula visível, a métrica que
depende de um subconjunto com menos de ``k`` crianças some (poucos alunos medidos, com
nível, com questão ou com atividade). Como o total soma a célula, "total − células que
mostram a métrica" a refaria; então a métrica some também do TOTAL que a revelaria — da
escola, quando as crianças escondidas nas séries dela somam de 1 a ``k − 1``; da rede,
quando as escondidas nas escolas que também a esconderam somam de 1 a ``k − 1``; e do
total da rede numa série, sempre que alguma célula dela a esconde (senão a conta cruzada
com o total da escola isolaria a célula). Métrica derivada de duas somas some com qualquer
uma delas: o desempenho do Matific (estrelas ÷ atividades) some de todo total que esconde
as atividades — ao lado das estrelas por aluno, ele as refaria. As marcas por grupo (as
que a rede soma) continuam as das SOMAS: o total que esconde só o desempenho ainda fixa as
estrelas dele. E o grupo VAZIO numa série sem número (poucos medidos, nenhuma criança com
atividade) não é zero sabido: as estrelas por aluno somem do total enquanto os medidos
dessas séries somarem de 1 a ``k − 1`` e nenhuma outra criança esconder as estrelas.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import (String, and_, case, cast, extract, func, literal_column,
                        null, or_, select, union_all)
from sqlalchemy.orm import Session

from app.core.tempo import FUSO_BR, para_br
from app.models import (Aluno, Escola, EventoAluno, Leitura, Livro, Matricula, Rede,
                        SnapshotElefante, SnapshotMatific, Turma)
from app.services import matific_destaque
from app.services import modulos as svc_modulos
from app.services import relatorios_periodo as rp
from app.services.analise import K_MINIMO, AnaliseInvalida, validar_anos
from app.services.analise.indicadores import (ano_letivo_de_referencia, escolas_da_rede,
                                              ordem_nome)
from app.services.elegibilidade import ANOS_PREMIAVEIS, ano_premiavel
from app.services.indicadores.ica import arredondar
from app.services.scoring import NIVEIS_ORDENADOS, POS_DO_NIVEL

PLATAFORMA_MODULO = {"elefante": "leitura", "matific": "matematica"}

COBERTURA_OK = "ok"
COLETA_PARCIAL = "coleta_parcial"
SEM_COLETA = "sem_coleta"
SEM_COLETA_NO_PERIODO = "sem_coleta_no_periodo"
MODULO_DESLIGADO = "modulo_nao_contratado"
SEM_ALUNOS = "sem_alunos_no_recorte"
# Motivos de bloco sem número (além dos de cobertura acima).
POUCOS_MEDIDOS = "poucos_alunos_medidos"
SEM_CONTA = "sem_conta_na_plataforma"
SERIES_SUPRIMIDAS = "series_suprimidas"
SEM_ESCOLA_VISIVEL = "sem_dado_nas_escolas_visiveis"
# Com uma série escolhida: a escola tem alunos, mas nenhum ativo NESSA série (não é "sem
# aluno do 1º ao 5º ano" — a escola sem aluno nenhum continua com SEM_ALUNOS).
SEM_ALUNOS_NA_SERIE = "sem_alunos_na_serie"
# A recoleta completa do Elefante é semanal: coleta mais velha que isso (antes do fim do
# período, ou de hoje) deixa dias sem medir.
TOLERANCIA_COLETA_DIAS = 7
# Escola com a coleta parcial ENTRA na soma da rede se a coleta cobre ao menos esta fração
# do período (contado até hoje): o pedaço sem medir é pequeno e a data vem junto. Abaixo
# disso, a soma da rede ficaria enviesada para baixo — fica de fora. Na RELAÇÃO estatística
# qualquer coleta parcial continua fora (relacao.py).
FRACAO_MINIMA_SOMA_REDE = 0.9
TEXTOS_COBERTURA = {
    SEM_COLETA: "a escola não tem nenhuma coleta desta plataforma",
    SEM_COLETA_NO_PERIODO: ("nenhuma coleta desta plataforma cobre o período pedido (sem dado "
                            "não é zero)"),
    COLETA_PARCIAL: ("a coleta parou antes do fim do período: os números valem só até "
                     "{coberto_ate} (o resto do período não foi medido — sem dado não é zero)"),
    MODULO_DESLIGADO: "a rede não contratou este módulo",
    SEM_ALUNOS: "nenhum aluno ativo do 1º ao 5º ano matriculado no ano letivo",
    POUCOS_MEDIDOS: ("menos de {k} alunos com dado desta plataforma no período: os números não "
                     "aparecem, para proteger as crianças"),
    SEM_CONTA: ("nenhum aluno deste recorte tem conta nesta plataforma (sem dado não é "
                "zero)"),
    SEM_ALUNOS_NA_SERIE: "a escola não tem aluno ativo nesta série no ano letivo",
    SERIES_SUPRIMIDAS: ("todas as séries desta escola têm poucos alunos: os números das "
                        "plataformas não aparecem, para proteger as crianças"),
    SEM_ESCOLA_VISIVEL: ("nenhuma das escolas mostradas tem coleta em dia desta plataforma no "
                         "período (as escolas com poucos alunos ou com a coleta atrasada não "
                         "entram na soma da rede)"),
}

TEXTO_CONTADOR_REGREDIU = ("o contador de questões de algum aluno diminuiu entre as coletas "
                           "(contas misturadas ou recontadas): esse aluno fica fora do acerto "
                           "nas questões, como no Relatório por Período")

# Métricas que dependem de um SUBCONJUNTO da célula — (chaves, campo do subconjunto na
# soma). Com menos de ``k`` crianças no subconjunto (ou menos de ``k`` medidas) a métrica
# some; o campo diz quantas crianças ficariam expostas pela diferença "total − partes".
# Uma métrica DERIVADA de duas somas fica nos dois grupos e some quando qualquer um some:
# o desempenho do Matific é estrelas ÷ atividades — num total que esconde as atividades e
# mostra as estrelas por aluno (estrelas = média × alunos medidos), ele refaria as
# atividades escondidas (atividades = estrelas ÷ desempenho).
_PROTEGIDAS = {
    "elefante": ((("alunos_com_leitura", "participacao_pct", "livros_por_aluno",
                   "minutos_por_aluno"), "medidos"),
                 (("nivel_medio", "nivel_medio_posicao"), "alunos_com_nivel"),
                 (("taxa_acerto_pct",), "alunos_com_questao")),
    "matific": ((("participacao_pct", "atividades_por_aluno", "desempenho_medio"), "medidos"),
                (("estrelas_por_aluno", "desempenho_medio"), "com_atividade")),
}
# Subconjuntos cuja média divide a soma pelos alunos MEDIDOS (as estrelas por aluno do
# Matific: estrelas = média × alunos medidos, exata) — numa parte sem número nenhum (poucos
# medidos), o grupo VAZIO ali (nenhuma criança com atividade) soma zero sem que o zero seja
# sabido, e a diferença "total − partes" o devolveria (``_esconde_no_total``). No Elefante,
# o nível e o acerto dividem por somas que não saem em resposta nenhuma.
_ZERO_NAO_SABIDO = {"elefante": (), "matific": ("com_atividade",)}
TEXTO_METRICAS_PROTEGIDAS = ("algumas médias deste total não aparecem: ele soma um grupo de "
                             "menos de {k} alunos cujos números estão escondidos numa parte "
                             "dele, e a diferença os revelaria")

SUPRIMIDO = "suprimido"
TEXTO_SUPRESSAO = ("poucos alunos neste recorte (ou escondido junto com um recorte pequeno, "
                   "para que nenhum seja descoberto pela diferença do total): os números não "
                   "aparecem, para proteger as crianças")
ESCOPO_BLOCOS = "escolas_visiveis"
TEXTO_BLOCOS_REDE = ("Os números do Elefante e do Matific da rede somam só as escolas e as "
                     "séries mostradas, com a coleta em dia no período (ou cobrindo ao menos "
                     "90% dele): as que têm poucos alunos ficam de fora, para proteger as "
                     "crianças.")
TEXTO_BLOCOS_ESCOLA = ("Os números do Elefante e do Matific desta escola somam só as séries "
                       "mostradas: as séries com poucos alunos ficam de fora, para proteger as "
                       "crianças.")

LIMITACOES = [
    ("Elefante — questões: o Elefante só informa o contador VITALÍCIO de cada aluno (desde a "
     "criação da conta). As questões do período vêm da diferença entre duas coletas, e o "
     "intervalo real é o das coletas, não o pedido."),
    ("Elefante — livros e tempo: valem pela data da leitura gravada na PRIMEIRA importação do "
     "livro (releitura não muda a data); o tempo é um piso (a fonte nem sempre o informa)."),
    ("Matific: o contador é o acumulado do ANO ACADÊMICO do Matific (o calendário deles "
     "começa em 29/12), gravado uma vez por dia, na coleta; a atividade do período é a "
     "diferença entre coletas."),
    ("Alunos medidos: só entram na conta os alunos que a plataforma conhece no período — no "
     "Elefante, os que têm conta (alguma coleta); no Matific, os que têm coleta dentro do "
     "período. Quem ainda não tem conta fica fora do denominador: ausência não é zero."),
    ("Coleta atrasada: escola cuja última coleta é de mais de 7 dias antes do fim do período "
     "(ou de hoje) aparece como coleta parcial, com a data até onde os números valem. Ela "
     "entra na soma da rede só se a coleta cobre ao menos 90% do período (até hoje), com a "
     "data informada; abaixo disso fica fora. Na relação estatística, toda coleta parcial "
     "fica fora."),
    ("Datas: as coletas são gravadas em UTC e o período é contado no horário de Brasília "
     "(UTC−3). Leituras das 21h à meia-noite podem cair no dia seguinte, e a coleta da "
     "madrugada mede o dia anterior."),
    ("Coorte: alunos ATIVOS matriculados no ano letivo ativo, do 1º ao 5º ano. Aluno "
     "transferido ou inativo sai de todas as contas, com o histórico dele."),
    ("As plataformas só têm dados do ano letivo em curso; as avaliações oficiais por escola "
     "são de anos anteriores. Por isso a relação entre as duas só é calculada no mesmo ano "
     "letivo — e, mesmo assim, não mede causa e efeito."),
]


def _arred(valor: float | None, casas: int) -> float | None:
    return None if valor is None else arredondar(valor, casas)


def _iso_br(momento: datetime | None) -> str | None:
    """Instante gravado em UTC → horário de Brasília, com o fuso explícito."""
    return para_br(momento).isoformat() if momento is not None else None


def _data_br(momento: datetime) -> date:
    return para_br(momento).date()


# --- Somas -----------------------------------------------------------------------------

@dataclass
class _Elefante:
    """O que é SOMÁVEL do Elefante num grupo de alunos (célula, escola ou rede)."""
    coorte: int = 0                 # alunos do recorte (escola com coleta que cobre o período)
    medidos: int = 0                # com conta no Elefante (alguma coleta) ou leitura no período
    com_leitura: int = 0
    livros_novos: int = 0
    tempo_min: int = 0
    soma_nivel: float = 0.0
    livros_com_nivel: int = 0
    alunos_com_nivel: int = 0
    tentativas: int = 0
    acertos: int = 0
    alunos_com_questao: int = 0
    # Alunos com o contador de questões que DIMINUIU entre as coletas (série que mistura
    # contas — fusão, colisão de identidade — ou recontada): fora das questões, como na
    # regra oficial. Só sai como aviso (sim/não), nunca a contagem.
    contador_regrediu: int = 0
    bases: list = field(default_factory=list)
    atuais: list = field(default_factory=list)


@dataclass
class _Matific:
    """O que é SOMÁVEL do Matific num grupo de alunos."""
    coorte: int = 0
    medidos: int = 0                # com coleta dentro do período (o ganho existe)
    com_atividade: int = 0
    atividades: float = 0.0
    estrelas: float = 0.0
    bases: list = field(default_factory=list)
    atuais: list = field(default_factory=list)


def _somar(destino, origem) -> None:
    for f in fields(destino):
        atual = getattr(destino, f.name)
        if isinstance(atual, list):
            atual.extend(getattr(origem, f.name))
        else:
            setattr(destino, f.name, atual + getattr(origem, f.name))


@dataclass
class _Celula:
    alunos: int                                 # da CONTAGEM (a que decide a supressão)
    elefante: _Elefante | None = None
    matific: _Matific | None = None


@dataclass
class _Contagem:
    """Alunos da coorte por série (1º–5º) e fora do recorte, de UMA escola."""
    escola: Escola
    series: dict[int, int] = field(default_factory=dict)
    fora: int = 0

    @property
    def total(self) -> int:
        return sum(self.series.values())


@dataclass
class _Medida:
    """Uma escola VISÍVEL medida no período: só as séries visíveis entram em ``series``."""
    escola: Escola
    janela: rp.Janela
    contagem: _Contagem
    series: dict[int, _Celula]
    cobertura: dict[str, str]
    ultima_coleta: dict[str, datetime | None]
    coberto_ate: dict[str, datetime | None]
    # Fração do período (até hoje) que a coleta cobre — só para a coleta parcial.
    fracao_coberta: dict[str, float | None] = field(default_factory=dict)

    def blocos(self) -> tuple[_Elefante | None, _Matific | None]:
        """A soma das células VISÍVEIS (nunca as suprimidas)."""
        ele = mat = None
        for c in self.series.values():
            if c.elefante is not None:
                ele = ele or _Elefante()
                _somar(ele, c.elefante)
            if c.matific is not None:
                mat = mat or _Matific()
                _somar(mat, c.matific)
        return ele, mat


# --- Leituras do banco -----------------------------------------------------------------
#
# A API e o banco ficam em regiões diferentes (~195 ms por ida e volta, medido nos logs de
# produção): o tempo de uma rota é o NÚMERO de consultas, quase nada o tamanho delas. Por
# isso cada leitura abaixo é UMA consulta para TODAS as escolas medidas (``escola_id IN``)
# e, quando a rota mede vários períodos de uma vez (a evolução por bimestre), para todos
# eles — um ``UNION ALL`` por período, com a posição dele na coluna ``g``. O custo de uma
# rota não cresce com o número de escolas nem de bimestres. A regra de cada escola é a de
# uma escola sozinha: as funções de janela particionam por (escola, aluno) e o recorte da
# coorte é conferido escola a escola (a leitura de um aluno numa escola só conta para ela).

def _coortes(db: Session, escolas: list[Escola]
             ) -> tuple[dict[int, _Contagem], dict[int, dict[int, dict]]]:
    """A contagem por série que decide a supressão e a coorte de cada escola — UMA consulta
    para todas. É a população de ``relatorios_periodo._coorte`` (aluno ATIVO matriculado no
    ano letivo ATIVO da escola; uma matrícula por aluno no ano, ``uq_matricula_aluno_ano``)
    e não depende do período: a supressão é decidida só com ela. Da coorte fica só o que as
    somas usam (turma e ano escolar); o nome do aluno nem é lido."""
    contagens = {e.id: _Contagem(escola=e) for e in escolas}
    coortes: dict[int, dict[int, dict]] = {e.id: {} for e in escolas}
    if not escolas:
        return contagens, coortes
    linhas = db.execute(
        select(Aluno.escola_id, Aluno.id, Turma.id, Turma.ano_escolar)
        .join(Matricula, Matricula.aluno_id == Aluno.id)
        .join(Turma, Matricula.turma_id == Turma.id)
        .join(Escola, Escola.id == Aluno.escola_id)
        .where(Aluno.escola_id.in_(list(contagens)), Aluno.status == "ativo",
               Matricula.ano_letivo == Escola.ano_letivo_ativo)).all()
    for escola_id, aluno_id, turma_id, ano_escolar in linhas:
        c = contagens[escola_id]
        serie = ano_premiavel(ano_escolar)
        if serie is None:
            c.fora += 1
        else:
            c.series[serie] = c.series.get(serie, 0) + 1
        coortes[escola_id][aluno_id] = {"turma_id": turma_id, "ano_escolar": ano_escolar}
    for c in contagens.values():
        c.series = dict(sorted(c.series.items()))
    return contagens, coortes


def _coletas_e_primeiros(db: Session, ids: list[int], com_primeiro_evento: bool
                         ) -> tuple[dict[str, dict[int, tuple]], dict[int, datetime]]:
    """A primeira e a última coleta de cada plataforma por escola e, para a cobertura da
    rede, o evento do Elefante mais antigo de cada escola (o piso do histórico consultável,
    ``relatorios_periodo._primeiro_evento``) — UMA consulta (os ``GROUP BY`` em ``UNION
    ALL``)."""
    coletas: dict[str, dict[int, tuple]] = {"elefante": {}, "matific": {}}
    primeiros: dict[int, datetime] = {}
    if not ids:
        return coletas, primeiros
    partes = [select(literal_column(f"'{p}'").label("fonte"), m.escola_id.label("escola_id"),
                     func.min(m.data_referencia).label("ini"),
                     func.max(m.data_referencia).label("fim"))
              .where(m.escola_id.in_(ids)).group_by(m.escola_id)
              for p, m in (("elefante", SnapshotElefante), ("matific", SnapshotMatific))]
    if com_primeiro_evento:
        primeiro = func.min(EventoAluno.ocorrido_em)
        partes.append(select(literal_column("'evento'").label("fonte"),
                             EventoAluno.escola_id.label("escola_id"), primeiro.label("ini"),
                             primeiro.label("fim"))
                      .where(EventoAluno.escola_id.in_(ids), EventoAluno.plataforma == "elefante")
                      .group_by(EventoAluno.escola_id))
    for fonte, escola_id, ini, fim in db.execute(union_all(*partes)).all():
        if fonte == "evento":
            if ini is not None:
                primeiros[escola_id] = ini
        else:
            coletas[fonte][escola_id] = (ini, fim)
    return coletas, primeiros


def _elefante_em_lote(db: Session, grupos: dict[int, tuple[rp.Janela, list[int]]],
                      coortes: dict[int, dict[int, dict]]
                      ) -> tuple[dict[tuple[int, int], dict[int, dict]],
                                 dict[tuple[int, int], dict[int, tuple[float, int]]]]:
    """Por (grupo, escola) e aluno da coorte: os livros NOVOS e o tempo (``Leitura.data``, o
    par das premiações) e os eventos de leitura (``EventoAluno.ocorrido_em``) — os dois
    eixos de ``relatorios_periodo._elefante`` — e (soma das posições, livros) do nível
    CONGELADO da leitura (``coalesce(Leitura.nivel_codigo, Livro.nivel_codigo)``, posição em
    ``scoring.POS_DO_NIVEL``; nível fora do vocabulário não entra na média). UMA consulta:
    as leituras agrupadas por nível (livro novo e tempo somam todos os níveis; o nível só
    conta a leitura com livro, como o ``JOIN`` de antes) e os eventos, de todos os grupos. A
    releitura (o terceiro eixo de ``_elefante``) não entra em conta nenhuma desta análise.

    O recorte da coorte é o da coorte JÁ LIDA (``coortes``, a mesma do denominador), aluno a
    aluno e escola a escola: uma subconsulta da coorte seria lida em outro instante, e um
    aluno inativado no meio da requisição ficaria no denominador sem as leituras dele."""
    ele: dict[tuple[int, int], dict[int, dict]] = {}
    niveis: dict[tuple[int, int], dict[int, tuple[float, int]]] = {}
    if not grupos:
        return ele, niveis
    nivel =func.coalesce(Leitura.nivel_codigo, Livro.nivel_codigo)
    com_livro = case((Livro.id.is_(None), 0), else_=1)
    partes = []
    for g, (janela, ids) in grupos.items():
        leituras = (
            select(literal_column("'L'").label("fonte"), literal_column(str(g)).label("g"),
                   Leitura.escola_id.label("escola_id"), Leitura.aluno_id.label("aluno_id"),
                   nivel.label("nivel"), com_livro.label("com_livro"), func.count().label("n"),
                   func.coalesce(func.sum(Leitura.tempo_leitura_min), 0).label("minutos"))
            .select_from(Leitura).outerjoin(Livro, Leitura.livro_id == Livro.id)
            .where(Leitura.escola_id.in_(ids))
            .group_by(Leitura.escola_id, Leitura.aluno_id, nivel, com_livro))
        eventos = (
            select(literal_column("'E'"), literal_column(str(g)), EventoAluno.escola_id,
                   EventoAluno.aluno_id, cast(null(), String), literal_column("0"),
                   func.count(), literal_column("0"))
            .where(EventoAluno.escola_id.in_(ids), EventoAluno.plataforma == "elefante",
                   EventoAluno.tipo_evento == "leitura")
            .group_by(EventoAluno.escola_id, EventoAluno.aluno_id))
        if janela.inicio is not None:
            leituras = leituras.where(Leitura.data >= janela.inicio)
            eventos = eventos.where(EventoAluno.ocorrido_em >= janela.inicio)
        if janela.fim is not None:
            leituras = leituras.where(Leitura.data <= janela.fim)
            eventos = eventos.where(EventoAluno.ocorrido_em <= janela.fim)
        partes += [leituras, eventos]
    for fonte, g, escola_id, aid, codigo, tem_livro, n, minutos in db.execute(
            union_all(*partes)).all():
        if aid not in coortes[escola_id]:
            continue                # fora da coorte desta escola (outra escola, inativo...)
        chave, n = (int(g), escola_id), int(n or 0)
        alvo = ele.setdefault(chave, {}).setdefault(
            aid, {"livros_novos": 0, "tempo_min": 0, "eventos_leitura": 0})
        if fonte == "E":
            alvo["eventos_leitura"] += n
            continue
        alvo["livros_novos"] += n
        alvo["tempo_min"] += int(minutos or 0)
        pos = POS_DO_NIVEL.get(str(codigo or "").strip().upper()) if int(tem_livro) else None
        if pos is not None:
            soma, livros = niveis.setdefault(chave, {}).get(aid, (0.0, 0))
            niveis[chave][aid] = (soma + pos * n, livros + n)
    return ele, niveis


def _por_aluno(linhas) -> dict[tuple[int, int], dict[int, list]]:
    series: dict[tuple[int, int], dict[int, list]] = {}
    for linha in linhas:
        series.setdefault((int(linha.g), linha.escola_id), {}).setdefault(
            linha.aluno_id, []).append(linha)
    return series


def _retratos_em_lote(db: Session, modelo, campos: tuple[str, ...],
                      grupos: dict[int, tuple[datetime | None, datetime | None,
                                              datetime | None, list[int]]]
                      ) -> dict[tuple[int, int], dict[int, list]]:
    """Por (grupo, escola) e aluno, SÓ os retratos que a regra do MATIFIC lê — o ÚLTIMO antes
    de ``inicio`` e o PRIMEIRO e o ÚLTIMO dentro de [inicio, fim] —, em ordem de (data, id).
    ``matific_destaque.ganho_no_periodo`` compara o instante gravado (UTC) com a janela sem
    conversão (a regra das premiações) e não usa nenhum outro retrato da série, então o
    resultado é o mesmo da série inteira, sem carregar o histórico diário. UMA consulta para
    todos os grupos (``row_number`` por escola, aluno e faixa). As questões do Elefante têm
    outra regra (Brasília, tolerância de borda, uma linha por execução):
    ``_questoes_em_lote``.

    Cada grupo é (inicio, fim, piso, escolas); ``piso``: retratos antes dele não existem
    para a regra (o Matific descarta o que é de fora do ano letivo)."""
    if not grupos:
        return {}
    d = modelo.data_referencia
    partes = []
    for g, (inicio, fim, piso, ids) in grupos.items():
        whens = []
        if inicio is not None:
            whens.append((d < inicio, 0))
        if fim is not None:
            whens.append((d > fim, 2))
        faixa = case(*whens, else_=1) if whens else literal_column("1")
        particao = ((modelo.escola_id, modelo.aluno_id, faixa) if whens
                    else (modelo.escola_id, modelo.aluno_id))
        filtro = [modelo.escola_id.in_(ids)]
        if piso is not None:
            filtro.append(d >= piso)
        if fim is not None:
            filtro.append(d <= fim)
        sub = select(
            modelo.id.label("id"), modelo.escola_id.label("escola_id"),
            modelo.aluno_id.label("aluno_id"), d.label("data_referencia"),
            *[getattr(modelo, c).label(c) for c in campos], faixa.label("faixa"),
            func.row_number().over(partition_by=particao, order_by=(d.asc(), modelo.id.asc())
                                   ).label("rn_asc"),
            func.row_number().over(partition_by=particao, order_by=(d.desc(), modelo.id.desc())
                                   ).label("rn_desc"),
        ).where(*filtro).subquery()
        c = sub.c
        partes.append(
            select(literal_column(str(g)).label("g"), c.escola_id, c.id, c.aluno_id,
                   c.data_referencia, *[c[x] for x in campos])
            .where(or_(and_(c.faixa == 0, c.rn_desc == 1),
                       and_(c.faixa == 1, or_(c.rn_asc == 1, c.rn_desc == 1)),
                       and_(c.faixa == 2, c.rn_asc == 1))))
    u = union_all(*partes).subquery()
    return _por_aluno(db.execute(select(u).order_by(u.c.g, u.c.escola_id, u.c.aluno_id,
                                                    u.c.data_referencia, u.c.id)).all())


def _retratos_essenciais(db: Session, modelo, escola_id: int, campos: tuple[str, ...],
                         inicio: datetime | None, fim: datetime | None, *,
                         piso: datetime | None = None) -> dict[int, list]:
    """``_retratos_em_lote`` de UMA escola (a regra está lá)."""
    return _retratos_em_lote(db, modelo, campos, {0: (inicio, fim, piso, [escola_id])}).get(
        (0, escola_id), {})


# As colunas da coleta do Elefante que ``_diferenca_de_retratos`` lê: as questões e, para
# a primeira coleta provar "conta nova" (``_zerado``), os livros e o tempo.
_QUESTOES = ("questoes_tentativas", "questoes_acertos")
_COLUNAS_QUESTOES = (*_QUESTOES, *rp._CONTA_NOVA_EXIGE_ZERO)


def _utc(momento_br: datetime) -> datetime:
    """Borda do período (naive, em dias de Brasília) → o instante UTC naive em que as
    coletas são gravadas — o inverso de ``relatorios_periodo._br``."""
    return momento_br.replace(tzinfo=FUSO_BR).astimezone(timezone.utc).replace(tzinfo=None)


def _segundos(db: Session, coluna):
    """O instante em segundos, para medir a distância entre duas linhas na consulta."""
    if db.get_bind().dialect.name == "postgresql":
        return extract("epoch", coluna)
    return func.julianday(coluna) * 86400.0


def _questoes_em_lote(db: Session, grupos: dict[int, tuple[rp.Janela, list[int]]]
                      ) -> dict[tuple[int, int], dict[int, list]]:
    """Por (grupo, escola) e aluno, as coletas do Elefante que ``_diferenca_de_retratos``
    PODE usar, em ordem de (data, id) — com o critério dela: instantes comparados em
    BRASÍLIA, bordas medidas pela coleta a até ``TOLERANCIA_BORDA`` delas e as linhas da
    MESMA execução (a até ``_MESMA_COLETA`` da anterior) contadas como uma, a primeira (o
    resumo).

    Só entra a PRIMEIRA linha de cada execução e, delas: a última antes de "início −
    tolerância"; todas a até a tolerância do início; a primeira e a última do miolo do
    período; todas a até a tolerância do fim (a 0h do dia seguinte); e a primeira depois
    disso (só para saber que a conta existe). Nenhuma outra coleta muda o resultado da
    regra, então ele é o da série inteira — sem carregar o histórico diário. UMA consulta
    para todos os grupos: a execução de cada linha (``lag`` por escola e aluno) sai de uma
    CTE só, e cada grupo escolhe as dele (``row_number`` por escola, aluno e faixa).
    Limitação: uma sequência de linhas a menos de 15 min uma da outra que dure mais de 15
    min (só em dado antigo; hoje a sync reescreve o retrato do dia no lugar) conta aqui como
    uma execução só."""
    if not grupos:
        return {}
    m = SnapshotElefante
    d = m.data_referencia
    todas = select(
        m.id.label("id"), m.escola_id.label("escola_id"), m.aluno_id.label("aluno_id"),
        d.label("data_referencia"), *[getattr(m, c).label(c) for c in _COLUNAS_QUESTOES],
        func.lag(d).over(partition_by=(m.escola_id, m.aluno_id), order_by=(d.asc(), m.id.asc())
                         ).label("anterior"),
    ).where(m.escola_id.in_(sorted({i for _, ids in grupos.values() for i in ids}))).subquery()
    t = todas.c
    primeiras = select(t.id, t.escola_id, t.aluno_id, t.data_referencia,
                       *[t[c] for c in _COLUNAS_QUESTOES]).where(or_(
                           t.anterior.is_(None),
                           _segundos(db, t.data_referencia) - _segundos(db, t.anterior)
                           > rp._MESMA_COLETA.total_seconds())).cte("primeiras")
    p = primeiras.c
    tol = rp.TOLERANCIA_BORDA
    partes = []
    for g, (janela, ids) in grupos.items():
        whens = []
        if janela.inicio is not None:
            ini = _utc(janela.inicio)
            whens += [(p.data_referencia < ini - tol, 0), (p.data_referencia <= ini + tol, 1)]
        if janela.fim is not None:
            fim_excl = _utc(janela.fim + timedelta(microseconds=1))
            whens += [(p.data_referencia < fim_excl - tol, 2),
                      (p.data_referencia <= fim_excl + tol, 3)]
        faixa = (case(*whens, else_=4 if janela.fim is not None else 2) if whens
                 else literal_column("2"))
        particao = (p.escola_id, p.aluno_id, faixa) if whens else (p.escola_id, p.aluno_id)
        sub = select(
            p.id, p.escola_id, p.aluno_id, p.data_referencia, *[p[c] for c in _COLUNAS_QUESTOES],
            faixa.label("faixa"),
            func.row_number().over(partition_by=particao,
                                   order_by=(p.data_referencia.asc(), p.id.asc())).label("rn_asc"),
            func.row_number().over(partition_by=particao,
                                   order_by=(p.data_referencia.desc(), p.id.desc())
                                   ).label("rn_desc"),
        ).where(p.escola_id.in_(ids)).subquery()
        c = sub.c
        partes.append(
            select(literal_column(str(g)).label("g"), c.escola_id, c.id, c.aluno_id,
                   c.data_referencia, *[c[x] for x in _COLUNAS_QUESTOES])
            .where(or_(and_(c.faixa == 0, c.rn_desc == 1),
                       c.faixa.in_((1, 3)),
                       and_(c.faixa == 2, or_(c.rn_asc == 1, c.rn_desc == 1)),
                       and_(c.faixa == 4, c.rn_asc == 1))))
    u = union_all(*partes).subquery()
    return _por_aluno(db.execute(select(u).order_by(u.c.g, u.c.escola_id, u.c.aluno_id,
                                                    u.c.data_referencia, u.c.id)).all())


def _coletas_das_questoes(db: Session, escola_id: int, janela: rp.Janela) -> dict[int, list]:
    """``_questoes_em_lote`` de UMA escola (o critério está lá)."""
    return _questoes_em_lote(db, {0: (janela, [escola_id])}).get((0, escola_id), {})


def _janela(preset: str, ano: int, inicio: date | None, fim: date | None,
            hoje: date) -> rp.Janela:
    try:
        return rp.resolver_janela(preset, ano, inicio=inicio, fim=fim, hoje=hoje)
    except rp.RelatorioInvalido as exc:
        raise AnaliseInvalida(str(exc)) from exc


# --- Medição das escolas visíveis ----------------------------------------------------------
#
# Em três passos, para as leituras do banco serem UMA por fonte: (1) sem banco, o que medir
# em cada (período, escola) — a cobertura, as séries visíveis e as janelas; (2) as leituras
# de todos de uma vez (``_ler_em_lote``); (3) sem banco, as somas de cada escola, aluno a
# aluno, com as regras oficiais (``_medir_escola``).

@dataclass
class _Preparo:
    """Uma escola visível num período, antes das leituras."""
    g: int                                      # a posição do período pedido
    contagem: _Contagem
    janela: rp.Janela
    series: dict[int, _Celula]                  # só as séries visíveis
    cobertura: dict[str, str]
    ultima: dict[str, datetime | None]
    medir: list[str]                            # plataformas com a coleta cobrindo o período
    efetiva_matific: tuple[datetime, datetime] | None = None
    piso_matific: datetime | None = None


def _preparar(g: int, contagem: _Contagem, visiveis: set[int], janela: rp.Janela,
              mods: set[str], coletas: dict[str, tuple | None]) -> _Preparo:
    """O que medir de UMA escola visível no período, só nas séries ``visiveis``. Escola sem
    coleta (ou sem módulo, ou sem alunos) não pede leitura nenhuma."""
    escola = contagem.escola
    series = {s: _Celula(alunos=n) for s, n in contagem.series.items() if s in visiveis}
    ultima = {p: (coletas.get(p) or (None, None))[1] for p in PLATAFORMA_MODULO}
    cobertura = {}
    for p, modulo in PLATAFORMA_MODULO.items():
        if modulo not in mods:
            cobertura[p] = MODULO_DESLIGADO
        elif not contagem.total:
            cobertura[p] = SEM_ALUNOS
        elif ultima[p] is None:
            cobertura[p] = SEM_COLETA
        else:
            cobertura[p] = COBERTURA_OK
    # Elefante: a coleta precisa ter acontecido no período ou depois dele começar —
    # senão os livros do período ainda não chegaram e o zero seria falta de dado.
    if (cobertura["elefante"] == COBERTURA_OK and janela.inicio is not None
            and rp._sem_tz(ultima["elefante"]) < janela.inicio):
        cobertura["elefante"] = SEM_COLETA_NO_PERIODO
    medir = [p for p in PLATAFORMA_MODULO if cobertura[p] == COBERTURA_OK] if series else []
    prep = _Preparo(g=g, contagem=contagem, janela=janela, series=series, cobertura=cobertura,
                    ultima=ultima, medir=medir)
    if "matific" in medir:
        ano = escola.ano_letivo_ativo
        prep.efetiva_matific = matific_destaque.janela_efetiva(janela.inicio, janela.fim, ano)
        prep.piso_matific = matific_destaque.janela_ano_letivo(ano)[0]
    return prep


@dataclass
class _Lidos:
    """As leituras de todas as escolas e períodos, por (grupo, escola)."""
    elefante: dict = field(default_factory=dict)
    niveis: dict = field(default_factory=dict)
    questoes: dict = field(default_factory=dict)
    matific: dict = field(default_factory=dict)
    grupo_elefante: dict = field(default_factory=dict)  # (inicio, fim) → grupo
    grupo_matific: dict = field(default_factory=dict)   # (inicio, fim, piso) → grupo


def _ler_em_lote(db: Session, preparos: list[_Preparo], coortes: dict[int, dict[int, dict]]
                 ) -> _Lidos:
    """As leituras de todas as escolas e períodos: no Elefante, UMA consulta para os livros,
    o tempo, os eventos e o nível, e UMA para as coletas das questões; no Matific, UMA para os
    retratos. Períodos com as mesmas datas leem uma vez só."""
    lidos = _Lidos()
    grupos_ele: dict[int, tuple[rp.Janela, list[int]]] = {}
    grupos_mat: dict[int, tuple[datetime, datetime, datetime | None, list[int]]] = {}
    for prep in preparos:
        eid = prep.contagem.escola.id
        if "elefante" in prep.medir:
            chave = (prep.janela.inicio, prep.janela.fim)
            g = lidos.grupo_elefante.setdefault(chave, len(lidos.grupo_elefante))
            ids = grupos_ele.setdefault(g, (prep.janela, []))[1]
            if eid not in ids:
                ids.append(eid)
        if "matific" in prep.medir and prep.efetiva_matific is not None:
            chave = (*prep.efetiva_matific, prep.piso_matific)
            g = lidos.grupo_matific.setdefault(chave, len(lidos.grupo_matific))
            ids = grupos_mat.setdefault(g, (*chave, []))[3]
            if eid not in ids:
                ids.append(eid)
    lidos.elefante, lidos.niveis = _elefante_em_lote(db, grupos_ele, coortes)
    lidos.questoes = _questoes_em_lote(db, grupos_ele)
    lidos.matific = _retratos_em_lote(db, SnapshotMatific, ("atividades", "estrelas"), grupos_mat)
    return lidos


def _somar_elefante(janela: rp.Janela, por_serie: dict[int, dict], series: dict[int, _Celula],
                    ele: dict[int, dict], niveis: dict[int, tuple[float, int]],
                    retratos: dict[int, list], hoje: date) -> None:
    for s, d in por_serie.items():
        soma = series[s].elefante = _Elefante(coorte=len(d))
        for aid in d:
            e = ele.get(aid)
            if aid not in retratos and not e:
                continue              # sem conta no Elefante: fora da conta (não é zero)
            soma.medidos += 1
            if e:
                soma.livros_novos += e["livros_novos"]
                soma.tempo_min += e["tempo_min"]
                if e["livros_novos"] or e["eventos_leitura"]:
                    soma.com_leitura += 1
            nv = niveis.get(aid)
            if nv:
                soma.soma_nivel += nv[0]
                soma.livros_com_nivel += nv[1]
                soma.alunos_com_nivel += 1
            # Questões: a regra oficial (``relatorios_periodo._elefante_questoes``), aluno a
            # aluno — com as MESMAS exclusões: sem intervalo medido (uma coleta só, sem
            # base) não soma 0/0, e o contador que DIMINUIU (contas misturadas) sai da conta
            # (zerar um campo e somar o outro inventaria número: a taxa passava de 100%).
            ganho = rp._diferenca_de_retratos(retratos.get(aid, []), janela, _QUESTOES,
                                              hoje=hoje)
            if ganho is None or not ganho["_medido"]:
                continue
            if ganho["_regrediu"]:
                soma.contador_regrediu += 1
                continue
            soma.tentativas += ganho["questoes_tentativas"]
            soma.acertos += ganho["questoes_acertos"]
            if ganho["questoes_tentativas"] or ganho["questoes_acertos"]:
                soma.alunos_com_questao += 1
            if ganho["_data_base"] is not None:
                soma.bases.append(ganho["_data_base"])
            soma.atuais.append(ganho["_data_atual"])


def _somar_matific(janela: rp.Janela, ano: int, por_serie: dict[int, dict],
                   series: dict[int, _Celula], retratos: dict[int, list]) -> bool:
    """Devolve se algum aluno tem coleta dentro do período (senão, sem dado)."""
    algum = False
    for s, d in por_serie.items():
        soma = series[s].matific = _Matific(coorte=len(d))
        for aid in d:
            # A regra oficial (``relatorios_periodo._matific``), aluno a aluno.
            ganho = matific_destaque.ganho_no_periodo(retratos.get(aid, []), janela.inicio,
                                                      janela.fim, ano)
            if ganho is None:
                continue              # sem coleta no período: fora da conta (não é zero)
            algum = True
            soma.medidos += 1
            atividades, estrelas = int(ganho.atividades or 0), int(ganho.estrelas or 0)
            soma.atividades += atividades
            soma.estrelas += estrelas
            if atividades or estrelas:
                soma.com_atividade += 1
            if ganho.data_base is not None:
                soma.bases.append(rp._sem_tz(ganho.data_base))
            soma.atuais.append(rp._sem_tz(ganho.data_atual))
    return algum


def _limite_em_dia(janela: rp.Janela, hoje: date) -> date:
    """A data a partir da qual a coleta está "em dia" para o período."""
    fim = janela.fim.date() if janela.fim is not None else hoje
    return min(fim, hoje) - timedelta(days=TOLERANCIA_COLETA_DIAS)


def _medir_escola(prep: _Preparo, coorte: dict[int, dict], lidos: _Lidos, hoje: date
                  ) -> _Medida:
    """As somas de UMA escola visível no período, com as leituras já feitas."""
    escola, janela, series = prep.contagem.escola, prep.janela, prep.series
    cobertura = dict(prep.cobertura)
    coberto_ate: dict[str, datetime | None] = {p: None for p in PLATAFORMA_MODULO}
    if prep.medir and series:
        por_serie: dict[int, dict] = {}
        for aid, info in coorte.items():
            s = ano_premiavel(info["ano_escolar"])
            if s in series:
                por_serie.setdefault(s, {})[aid] = info
        if "elefante" in prep.medir:
            chave = (lidos.grupo_elefante[(janela.inicio, janela.fim)], escola.id)
            _somar_elefante(janela, por_serie, series, lidos.elefante.get(chave, {}),
                            lidos.niveis.get(chave, {}), lidos.questoes.get(chave, {}), hoje)
            coberto_ate["elefante"] = prep.ultima["elefante"]
        if "matific" in prep.medir:
            retratos = None
            if prep.efetiva_matific is not None:
                g = lidos.grupo_matific[(*prep.efetiva_matific, prep.piso_matific)]
                retratos = lidos.matific.get((g, escola.id), {})
            if retratos is not None and _somar_matific(janela, escola.ano_letivo_ativo,
                                                       por_serie, series, retratos):
                coberto_ate["matific"] = max(a for c in series.values() if c.matific
                                             for a in c.matific.atuais)
            else:
                cobertura["matific"] = SEM_COLETA_NO_PERIODO
                for c in series.values():
                    c.matific = None
    # Coleta PARADA antes do fim do período: o que foi medido vale só até ela.
    limite = _limite_em_dia(janela, hoje)
    fracao: dict[str, float | None] = {p: None for p in PLATAFORMA_MODULO}
    for p in PLATAFORMA_MODULO:
        if coberto_ate[p] is not None and _data_br(coberto_ate[p]) < limite:
            cobertura[p] = COLETA_PARCIAL
            fracao[p] = _fracao_coberta(janela, coberto_ate[p], hoje)
    return _Medida(escola=escola, janela=janela, contagem=prep.contagem, series=series,
                   cobertura=cobertura, ultima_coleta=prep.ultima, coberto_ate=coberto_ate,
                   fracao_coberta=fracao)


def _fracao_coberta(janela: rp.Janela, coberto_ate: datetime, hoje: date) -> float | None:
    """Que fração do período, contado até hoje, a coleta cobre (0–1). Sem início no
    período (preset 'tudo'), não há como medir: None (não entra na soma)."""
    if janela.inicio is None:
        return None
    inicio = janela.inicio.date()
    fim = min(janela.fim.date() if janela.fim is not None else hoje, hoje)
    total = (fim - inicio).days
    if total <= 0:
        return None
    return max(0.0, min(1.0, (_data_br(coberto_ate) - inicio).days / total))


def _entra_na_soma_da_rede(m: _Medida, p: str) -> bool:
    if m.cobertura[p] == COBERTURA_OK:
        return True
    fracao = m.fracao_coberta.get(p)
    return (m.cobertura[p] == COLETA_PARCIAL and fracao is not None
            and fracao >= FRACAO_MINIMA_SOMA_REDE)


# --- Métricas (a partir das somas) -------------------------------------------------------

_CHAVES_ELEFANTE = ("alunos_medidos", "alunos_sem_conta", "alunos_com_leitura",
                    "participacao_pct", "livros_por_aluno", "minutos_por_aluno", "nivel_medio",
                    "nivel_medio_posicao", "taxa_acerto_pct", "janela_questoes",
                    "contador_regrediu", "texto_contador_regrediu")
_CHAVES_MATIFIC = ("alunos_medidos", "alunos_com_retrato", "alunos_sem_retrato",
                   "participacao_pct", "atividades_por_aluno", "estrelas_por_aluno",
                   "desempenho_medio", "janela_efetiva")


def _texto(motivo: str | None, k: int, coberto_ate: datetime | None = None) -> str | None:
    if not motivo or motivo not in TEXTOS_COBERTURA:
        return None
    quando = para_br(coberto_ate).strftime("%d/%m/%Y") if coberto_ate is not None else "—"
    return TEXTOS_COBERTURA[motivo].format(k=k, coberto_ate=quando)


def _cobertura_bloco(parcial: bool, coberto_ate: datetime | None, k: int) -> dict:
    return {"coleta_parcial": parcial, "coberto_ate": _iso_br(coberto_ate),
            "texto_cobertura": _texto(COLETA_PARCIAL, k, coberto_ate) if parcial else None}


def _sem_protecao() -> dict:
    return {"metricas_protegidas": [], "texto_metricas_protegidas": None}


def _sem_dado(chaves: tuple[str, ...], motivo: str, k: int, **conhecidos) -> dict:
    return {**{c: None for c in chaves}, **conhecidos, **_cobertura_bloco(False, None, k),
            **_sem_protecao(), "motivo_sem_dado": motivo, "texto_sem_dado": _texto(motivo, k)}


_INICIO_DO_ZERO = {
    "elefante": ("sem coleta antes do período: as questões contam desde a primeira coleta "
                 "dentro dele"),
    "matific": ("sem coleta antes do período: o contador do ano letivo parte do zero (início "
                "do ano)"),
}


def _intervalo(bases: list[datetime], atuais: list[datetime], plataforma: str) -> dict | None:
    """O intervalo REAL das coletas que entraram na conta (horário de Brasília)."""
    if not atuais:
        return None
    primeira = min(bases) if bases else None
    return {"inicio": _iso_br(primeira), "fim": _iso_br(max(atuais)),
            "observacao": None if primeira else _INICIO_DO_ZERO[plataforma]}


def metricas_elefante(s: _Elefante | None, k: int, motivo: str | None = None, *,
                      parcial: bool = False, coberto_ate: datetime | None = None) -> dict:
    if motivo is not None:
        return _sem_dado(_CHAVES_ELEFANTE, motivo, k)
    if s is None or s.coorte == 0:
        return _sem_dado(_CHAVES_ELEFANTE, SEM_COLETA_NO_PERIODO, k)
    n = s.medidos
    contas = {"alunos_medidos": n, "alunos_sem_conta": s.coorte - n}
    if n < k:
        return _sem_dado(_CHAVES_ELEFANTE, POUCOS_MEDIDOS if n else SEM_CONTA, k, **contas)
    pos = (s.soma_nivel / s.livros_com_nivel
           if s.livros_com_nivel and s.alunos_com_nivel >= k else None)
    nivel = None
    if pos is not None:
        nivel = NIVEIS_ORDENADOS[min(max(int(arredondar(pos, 0)), 0), len(NIVEIS_ORDENADOS) - 1)]
    return {
        **contas,
        "alunos_com_leitura": s.com_leitura,
        "participacao_pct": _arred(100 * s.com_leitura / n, 1),
        "livros_por_aluno": _arred(s.livros_novos / n, 2),
        "minutos_por_aluno": _arred(s.tempo_min / n, 1),
        "nivel_medio": nivel,
        "nivel_medio_posicao": _arred(pos, 2),
        "taxa_acerto_pct": (_arred(100 * s.acertos / s.tentativas, 1)
                            if s.tentativas and s.alunos_com_questao >= k else None),
        "janela_questoes": _intervalo(s.bases, s.atuais, "elefante"),
        # Aviso (sim/não, sem a contagem) de que algum aluno ficou fora das questões porque
        # o contador dele diminuiu — o Relatório por Período declara o mesmo caso.
        "contador_regrediu": s.contador_regrediu > 0,
        "texto_contador_regrediu": TEXTO_CONTADOR_REGREDIU if s.contador_regrediu else None,
        **_cobertura_bloco(parcial, coberto_ate, k), **_sem_protecao(),
        "motivo_sem_dado": None, "texto_sem_dado": None,
    }


def metricas_matific(s: _Matific | None, k: int, motivo: str | None = None, *,
                     parcial: bool = False, coberto_ate: datetime | None = None) -> dict:
    if motivo is not None:
        return _sem_dado(_CHAVES_MATIFIC, motivo, k)
    if s is None or s.coorte == 0 or s.medidos == 0:
        return _sem_dado(_CHAVES_MATIFIC, SEM_COLETA_NO_PERIODO, k,
                         **({"alunos_medidos": 0, "alunos_com_retrato": 0,
                             "alunos_sem_retrato": s.coorte} if s and s.coorte else {}))
    n = s.medidos
    contas = {"alunos_medidos": n, "alunos_com_retrato": n, "alunos_sem_retrato": s.coorte - n}
    if n < k:
        return _sem_dado(_CHAVES_MATIFIC, POUCOS_MEDIDOS, k, **contas)
    ativos = s.com_atividade >= k
    return {
        **contas,
        "participacao_pct": _arred(100 * s.com_atividade / n, 1),
        "atividades_por_aluno": _arred(s.atividades / n, 2),
        # Estrelas ÷ atividades das duas médias refaria o desempenho: com menos de k alunos
        # com atividade, as estrelas por aluno somem junto com ele.
        "estrelas_por_aluno": _arred(s.estrelas / n, 2) if ativos else None,
        "desempenho_medio": (_arred(s.estrelas / s.atividades, 2)
                             if s.atividades and ativos else None),
        "janela_efetiva": _intervalo(s.bases, s.atuais, "matific"),
        **_cobertura_bloco(parcial, coberto_ate, k), **_sem_protecao(),
        "motivo_sem_dado": None, "texto_sem_dado": None,
    }


def _blocos_da_medida(m: _Medida, ele: _Elefante | None, mat: _Matific | None,
                      mods: set[str], k: int, *, sem_series: bool = False) -> dict:
    """Os blocos de uma escola (ou de uma célula dela), com a cobertura da escola."""
    saida = {}
    for p, soma, funcao in (("elefante", ele, metricas_elefante),
                            ("matific", mat, metricas_matific)):
        if PLATAFORMA_MODULO[p] not in mods:
            saida[p] = None
            continue
        cob = m.cobertura[p]
        if cob not in (COBERTURA_OK, COLETA_PARCIAL):
            saida[p] = funcao(None, k, cob)
        elif sem_series:
            saida[p] = funcao(None, k, SERIES_SUPRIMIDAS)
        else:
            saida[p] = funcao(soma, k, parcial=cob == COLETA_PARCIAL,
                              coberto_ate=m.coberto_ate[p])
    return saida


# --- Supressão complementar por métrica -------------------------------------------------

def _escondidas(soma, plataforma: str, k: int) -> list[int]:
    """Por grupo de ``_PROTEGIDAS``: quantas crianças do subconjunto têm o número ESCONDIDO
    nesta parte (0 = a métrica aparece, ou o subconjunto é vazio e a parte soma zero) — as
    mesmas condições de ``metricas_elefante``/``metricas_matific``. O zero de uma parte sem
    número (poucos medidos), que não é sabido, é tratado em ``_esconde_no_total``."""
    return [0 if soma.medidos >= k and getattr(soma, campo) >= k else getattr(soma, campo)
            for _chaves, campo in _PROTEGIDAS[plataforma]]


def _uniao_escondida(partes: list, plataforma: str, k: int) -> list[int]:
    """Por grupo, a soma das crianças escondidas nas ``partes`` (as que o total soma)."""
    uniao = [0] * len(_PROTEGIDAS[plataforma])
    for parte in partes:
        for i, g in enumerate(_escondidas(parte, plataforma, k)):
            uniao[i] += g
    return uniao


def _medidos_sem_numero(partes: list, k: int) -> int:
    """Os alunos medidos das partes que não mostram número nenhum (menos de ``k`` medidos):
    nem a participação delas aparece."""
    return sum(p.medidos for p in partes if 0 < p.medidos < k)


def _esconde_no_total(escondidas: list[int], sem_numero: list[int], plataforma: str, k: int,
                      *, qualquer: bool = False) -> list[bool]:
    """Por grupo de ``_PROTEGIDAS``: se um total esconde a métrica em complemento, pelas
    crianças escondidas nas partes que ele soma (``escondidas``) — de 1 a k − 1 (ou qualquer
    uma, com ``qualquer``: o total da rede numa série).

    Num grupo de ``_ZERO_NAO_SABIDO`` sem nenhuma criança escondida, valem os alunos medidos
    das partes sem número (``sem_numero``): o grupo vazio ali soma zero, mas esse zero não é
    sabido (a participação delas não aparece) e "total − partes" o devolveria — a soma de
    menos de k crianças. Com k ou mais delas, o zero é o de k ou mais crianças (o padrão
    dos medidos, o mesmo das atividades)."""
    saida = []
    for g, n, (_chaves, campo) in zip(escondidas, sem_numero, _PROTEGIDAS[plataforma]):
        if g == 0 and campo in _ZERO_NAO_SABIDO[plataforma]:
            g = n
        saida.append(g > 0 if qualquer else 0 < g < k)
    return saida


def _partes(m: _Medida, plataforma: str) -> list:
    """As células VISÍVEIS (com dado da plataforma) que o bloco da escola soma."""
    return [getattr(c, plataforma) for c in m.series.values()
            if getattr(c, plataforma) is not None]


def _complemento_da_escola(partes: list, plataforma: str, k: int
                           ) -> tuple[list[bool], list[int], int]:
    """O complemento do bloco da escola pelas séries dela: (grupos escondidos, crianças
    escondidas por grupo, alunos medidos das séries sem número)."""
    uniao = _uniao_escondida(partes, plataforma, k)
    sem_numero = _medidos_sem_numero(partes, k)
    return (_esconde_no_total(uniao, [sem_numero] * len(uniao), plataforma, k), uniao,
            sem_numero)


def _escola_esconde(m: _Medida, plataforma: str, k: int
                    ) -> tuple[list[bool], list[int], int]:
    """Por grupo: se o bloco da ESCOLA esconde a SOMA do grupo (pelo próprio subconjunto ou
    em complemento) e quantas crianças escondidas as séries dela somam; e os alunos medidos
    das séries sem número dela. A métrica derivada (o desempenho do Matific, nos dois
    grupos) não muda a marca: ela some junto com a soma que a refaria (``_proteger``), e a
    outra soma continua fixada pelo total."""
    partes = _partes(m, plataforma)
    complemento, uniao, sem_numero = _complemento_da_escola(partes, plataforma, k)
    soma = None
    for parte in partes:
        soma = soma or (_Elefante() if plataforma == "elefante" else _Matific())
        _somar(soma, parte)
    proprias = _escondidas(soma, plataforma, k) if soma is not None else [0] * len(uniao)
    return ([bool(proprias[i]) or complemento[i] for i in range(len(uniao))], uniao,
            sem_numero)


def _proteger(bloco: dict | None, plataforma: str, esconder: list[bool], k: int) -> None:
    """Esconde do TOTAL os grupos marcados (complemento) e diz quais, com o texto. A métrica
    que está em dois grupos (derivada das duas somas) some se qualquer um deles some."""
    if not bloco or bloco.get("motivo_sem_dado"):
        return
    for (chaves, _campo), sim in zip(_PROTEGIDAS[plataforma], esconder):
        if not sim:
            continue
        for chave in chaves:
            if bloco.get(chave) is not None:
                bloco[chave] = None
                bloco["metricas_protegidas"].append(chave)
    if bloco["metricas_protegidas"]:
        bloco["texto_metricas_protegidas"] = TEXTO_METRICAS_PROTEGIDAS.format(k=k)


# --- Supressão ------------------------------------------------------------------------

def suprimir(itens: list[dict], k: int) -> None:
    """Marca ``suprimido`` em itens com ``_n`` (alunos) e ``_ordem``. Primeiro, os com 1 a
    k−1 alunos; depois, a FAIXA DE PROTEÇÃO: enquanto o que ficou suprimido somar de 1 a
    2k−1 alunos, os menores visíveis também são suprimidos (supressão complementar). Assim
    a diferença "total − visíveis" é sempre de pelo menos 2k alunos e não fixa o tamanho de
    nenhuma célula pequena."""
    for it in itens:
        if not it.get("suprimido"):
            it["suprimido"] = 0 < it["_n"] < k
    uniao = sum(it["_n"] for it in itens if it["suprimido"])
    if 0 < uniao < 2 * k:
        for it in sorted((i for i in itens if not i["suprimido"] and i["_n"] > 0),
                         key=lambda i: (i["_n"], i["_ordem"])):
            it["suprimido"] = True
            uniao += it["_n"]
            if uniao >= 2 * k:
                break
    for it in itens:
        it["motivo_supressao"] = SUPRIMIDO if it["suprimido"] else None


def _texto_supressao(motivo: str | None) -> str | None:
    return TEXTO_SUPRESSAO if motivo else None


def decidir_supressao(contagens: list[_Contagem], k: int
                      ) -> tuple[list[_Contagem], dict[int, dict]]:
    """A supressão, decidida só pelas CONTAGENS (escolas × todas as séries), que não
    dependem do período, e usada igual em toda resposta — rede, série filtrada, escola e
    relação. Decidir de novo em cada recorte abriria a conta "total − visíveis" entre duas
    respostas.

    Devolve as contagens em ordem de NOME e, por escola, a decisão da escola e de cada
    série (``{"escola": info, "series": {serie: info}}``)."""
    ordenadas = sorted(contagens, key=lambda c: ordem_nome(c.escola.nome, c.escola.id))
    infos = [{"_n": c.total, "_ordem": i} for i, c in enumerate(ordenadas)]
    suprimir(infos, k)
    decisoes = {}
    for c, info in zip(ordenadas, infos):
        celulas = [{"_n": n, "_ordem": serie, "serie": serie}
                   for serie, n in c.series.items() if n > 0]
        if info["suprimido"]:
            # Escola suprimida: todas as séries dela (senão a soma refaria o total).
            for cel in celulas:
                cel["suprimido"], cel["motivo_supressao"] = True, SUPRIMIDO
        else:
            suprimir(celulas, k)
        decisoes[c.escola.id] = {"escola": info, "series": {cel["serie"]: cel for cel in celulas}}
    return ordenadas, decisoes


def _visiveis(decisao: dict) -> set[int]:
    if decisao["escola"]["suprimido"]:
        return set()
    return {s for s, cel in decisao["series"].items() if not cel["suprimido"]}


# --- JSON ---------------------------------------------------------------------------------

def _celula_json(serie: int, m: _Medida | None, info: dict, mods: set[str], k: int) -> dict:
    if info["suprimido"] or m is None:
        return {"serie": serie, "alunos": None, "suprimido": True,
                "motivo_supressao": SUPRIMIDO, "texto_supressao": TEXTO_SUPRESSAO,
                "elefante": None, "matific": None}
    c = m.series[serie]
    return {"serie": serie, "alunos": c.alunos, "suprimido": False, "motivo_supressao": None,
            "texto_supressao": None, **_blocos_da_medida(m, c.elefante, c.matific, mods, k)}


def _escola_suprimida(c: _Contagem) -> dict:
    e = c.escola
    return {"escola_id": e.id, "nome": e.nome, "ano_letivo": e.ano_letivo_ativo,
            "cobertura": None, "ultima_coleta": None, "coberto_ate": None,
            "dias_desde_ultima_coleta": None,
            "alunos": None, "suprimido": True, "motivo_supressao": SUPRIMIDO,
            "texto_supressao": TEXTO_SUPRESSAO, "blocos_parciais": False, "texto_blocos": None,
            "elefante": None, "matific": None, "series": []}


def _escola_json(m: _Medida | None, c: _Contagem, decisao: dict, mods: set[str], k: int,
                 hoje: date, serie: int | None = None) -> dict:
    """A escola na resposta. Com ``serie``, o bloco da escola é o da série (com a decisão
    de supressão da tabela inteira). Escola suprimida: nada dela — nem a cobertura."""
    if decisao["escola"]["suprimido"] or m is None:
        return _escola_suprimida(c)
    e = c.escola
    base = {"escola_id": e.id, "nome": e.nome, "ano_letivo": e.ano_letivo_ativo,
            "cobertura": dict(m.cobertura),
            "ultima_coleta": {p: _iso_br(m.ultima_coleta[p]) for p in PLATAFORMA_MODULO},
            "coberto_ate": {p: _iso_br(m.coberto_ate[p]) for p in PLATAFORMA_MODULO},
            "dias_desde_ultima_coleta": {
                p: ((hoje - _data_br(m.ultima_coleta[p])).days
                    if m.ultima_coleta[p] is not None else None) for p in PLATAFORMA_MODULO}}
    if serie is not None:
        info = decisao["series"].get(serie)
        if info is not None and info["suprimido"]:
            return {**base, "alunos": None, "suprimido": True, "motivo_supressao": SUPRIMIDO,
                    "texto_supressao": TEXTO_SUPRESSAO, "blocos_parciais": False,
                    "texto_blocos": None, "elefante": None, "matific": None, "series": []}
        if info is None:
            # Nenhum aluno ativo NESTA série: a escola com alunos em outras séries não é
            # "sem aluno do 1º ao 5º ano" — o motivo diz a série.
            return {**base, "alunos": 0, "suprimido": False, "motivo_supressao": None,
                    "texto_supressao": None, "blocos_parciais": False, "texto_blocos": None,
                    **_sem_alunos(mods, k, SEM_ALUNOS_NA_SERIE if c.total else SEM_ALUNOS),
                    "series": []}
        celula = m.series[serie]
        return {**base, "alunos": celula.alunos, "suprimido": False, "motivo_supressao": None,
                "texto_supressao": None, "blocos_parciais": False, "texto_blocos": None,
                **_blocos_da_medida(m, celula.elefante, celula.matific, mods, k),
                "series": [_celula_json(serie, m, info, mods, k)]}
    series = [_celula_json(s, m, info, mods, k) for s, info in decisao["series"].items()]
    parciais = any(s["suprimido"] for s in series)
    if not c.total:
        blocos = _sem_alunos(mods, k)
    else:
        ele, mat = m.blocos()
        blocos = _blocos_da_medida(m, ele, mat, mods, k, sem_series=not m.series)
        # Métrica escondida numa série: some também do total da escola quando as crianças
        # escondidas somam de 1 a k − 1 (senão "escola − séries mostradas" a refaria) — ou,
        # nas estrelas do Matific, quando o zero de uma série sem número se refaria.
        for p in PLATAFORMA_MODULO:
            esconder, _uniao, _sem_numero = _complemento_da_escola(_partes(m, p), p, k)
            _proteger(blocos.get(p), p, esconder, k)
    return {**base, "alunos": c.total, "suprimido": False, "motivo_supressao": None,
            "texto_supressao": None, "blocos_parciais": parciais,
            "texto_blocos": TEXTO_BLOCOS_ESCOLA if parciais else None,
            **blocos, "series": series}


def _sem_alunos(mods: set[str], k: int, motivo: str = SEM_ALUNOS) -> dict:
    return {"elefante": (_sem_dado(_CHAVES_ELEFANTE, motivo, k)
                         if PLATAFORMA_MODULO["elefante"] in mods else None),
            "matific": (_sem_dado(_CHAVES_MATIFIC, motivo, k)
                        if PLATAFORMA_MODULO["matific"] in mods else None)}


def _janela_json(janela: rp.Janela, ano: int | None, anos: list[int]) -> dict:
    return {"preset": janela.preset, "rotulo": janela.rotulo,
            "inicio": janela.inicio.date().isoformat() if janela.inicio else None,
            "fim": janela.fim.date().isoformat() if janela.fim else None,
            "ano_letivo": ano, "anos_letivos": anos}


def _validar_serie(serie: int | None) -> None:
    if serie is not None and serie not in ANOS_PREMIAVEIS:
        raise AnaliseInvalida("A série vai do 1º ao 5º ano (serie=1 a 5): as plataformas são "
                              "analisadas só no Fundamental I.")


# --- A tabela (rede ou escola) ---------------------------------------------------------------

@dataclass(frozen=True)
class Periodo:
    """Um período pedido (o preset do serviço de períodos e, no personalizado, as datas)."""
    preset: str = "ano_letivo"
    inicio: date | None = None
    fim: date | None = None


@dataclass
class _Tabela:
    contagens: list[_Contagem]                  # em ordem de nome
    decisoes: dict[int, dict]
    medidas: dict[int, _Medida]                 # só as escolas VISÍVEIS
    mods: set[str]
    janela: rp.Janela                           # a do ano letivo de referência
    ano: int | None
    anos: list[int]
    primeiros: dict[int, datetime]


def _tabelas(db: Session, escolas_da_decisao: list[Escola], medir: list[Escola], mods: set[str],
             *, periodos: list[Periodo], hoje: date, k: int, com_primeiro_evento: bool = False
             ) -> list[_Tabela]:
    """Uma tabela por período: a supressão decidida sobre ``escolas_da_decisao`` (só
    contagens, igual em todos os períodos) e a medição só das escolas de ``medir`` que
    ficaram visíveis. Datas fora da faixa aceita são recusadas (422) antes de qualquer
    consulta. As leituras do banco são as mesmas para qualquer número de escolas e de
    períodos (ver "Leituras do banco")."""
    for p in periodos:
        validar_anos(inicio=p.inicio, fim=p.fim)
    contagens, coortes = _coortes(db, escolas_da_decisao)
    ordenadas, decisoes = decidir_supressao(list(contagens.values()), k)
    alvo = [e for e in medir if not decisoes[e.id]["escola"]["suprimido"]]
    ids = [e.id for e in alvo]
    col, primeiros = _coletas_e_primeiros(db, ids, com_primeiro_evento)
    janelas: dict[tuple[int, int], rp.Janela] = {}
    preparos = []
    for g, p in enumerate(periodos):
        for e in alvo:
            if (g, e.ano_letivo_ativo) not in janelas:
                janelas[(g, e.ano_letivo_ativo)] = _janela(p.preset, e.ano_letivo_ativo,
                                                           p.inicio, p.fim, hoje)
            preparos.append(_preparar(g, contagens[e.id], _visiveis(decisoes[e.id]),
                                      janelas[(g, e.ano_letivo_ativo)], mods,
                                      {pl: col[pl].get(e.id) for pl in PLATAFORMA_MODULO}))
    ano = ano_letivo_de_referencia(escolas_da_decisao)
    janelas_ref = [_janela(p.preset, ano if ano is not None else hoje.year, p.inicio, p.fim,
                           hoje) for p in periodos]
    lidos = _ler_em_lote(db, preparos, coortes)
    medidas: list[dict[int, _Medida]] = [{} for _ in periodos]
    for prep in preparos:
        eid = prep.contagem.escola.id
        medidas[prep.g][eid] = _medir_escola(prep, coortes[eid], lidos, hoje)
    anos = sorted({e.ano_letivo_ativo for e in escolas_da_decisao})
    return [_Tabela(contagens=ordenadas, decisoes=decisoes, medidas=medidas[g], mods=mods,
                    janela=janelas_ref[g], ano=ano, anos=anos, primeiros=primeiros)
            for g in range(len(periodos))]


def _cobertura(t: _Tabela, hoje: date) -> dict:
    """A cobertura da rede, só com as escolas VISÍVEIS (a de uma escola suprimida não
    aparece em lugar nenhum)."""
    medidas = list(t.medidas.values())
    contratadas = [p for p in PLATAFORMA_MODULO if PLATAFORMA_MODULO[p] in t.mods]
    ultimas = {}
    for p in PLATAFORMA_MODULO:
        datas = [m.ultima_coleta[p] for m in medidas if m.ultima_coleta[p] is not None]
        ultimas[p] = max(datas) if datas and p in contratadas else None
    recentes = [d for d in ultimas.values() if d is not None]
    primeiros = list(t.primeiros.values())
    return {
        "escopo": ESCOPO_BLOCOS,
        "ultima_coleta": {p: _iso_br(d) for p, d in ultimas.items()},
        "escolas_sem_coleta": [m.escola.id for m in medidas if contratadas and all(
            m.cobertura[p] == SEM_COLETA for p in contratadas)],
        "escolas_sem_coleta_no_periodo": {
            p: [m.escola.id for m in medidas
                if m.cobertura[p] in (SEM_COLETA, SEM_COLETA_NO_PERIODO)]
            for p in contratadas},
        "escolas_coleta_parcial": {
            p: [m.escola.id for m in medidas if m.cobertura[p] == COLETA_PARCIAL]
            for p in contratadas},
        "primeiro_evento_elefante": min(primeiros).isoformat() if primeiros else None,
        "dias_desde_ultima_coleta": ((hoje - _data_br(max(recentes))).days
                                     if recentes else None),
    }


def _limitacoes(anos: list[int]) -> list[str]:
    saida = list(LIMITACOES)
    if len(anos) > 1:
        saida.append("As escolas da rede estão em anos letivos diferentes ("
                     + ", ".join(map(str, anos)) + "): o período de cada uma é o do ano dela.")
    return saida


def _bloco_da_rede(t: _Tabela, k: int, serie: int | None) -> tuple[dict, dict]:
    """Os blocos da rede: SÓ as escolas visíveis, com a coleta em dia (ou parcial cobrindo
    ao menos ``FRACAO_MINIMA_SOMA_REDE`` do período, com a data junto), e nelas só as
    células visíveis — o bloco é sempre igual à soma do que a resposta mostra. Devolve
    (blocos, escolas que entraram por plataforma)."""
    somas: dict[str, object] = {"elefante": None, "matific": None}
    entraram = {p: 0 for p in PLATAFORMA_MODULO}
    parciais: dict[str, list[datetime]] = {p: [] for p in PLATAFORMA_MODULO}
    # Crianças escondidas que a diferença "rede − partes mostradas" isolaria, por grupo — e,
    # das mesmas partes, os alunos medidos das séries sem número (``_esconde_no_total``).
    escondidas = {p: [0] * len(_PROTEGIDAS[p]) for p in PLATAFORMA_MODULO}
    sem_numero = {p: [0] * len(_PROTEGIDAS[p]) for p in PLATAFORMA_MODULO}
    for m in t.medidas.values():
        if serie is None:
            ele, mat = m.blocos()
        else:
            cel = m.series.get(serie)
            ele, mat = (cel.elefante, cel.matific) if cel else (None, None)
        for p, soma, vazio in (("elefante", ele, _Elefante), ("matific", mat, _Matific)):
            if soma is None or not _entra_na_soma_da_rede(m, p):
                continue
            somas[p] = somas[p] or vazio()
            _somar(somas[p], soma)
            entraram[p] += 1
            if m.cobertura[p] == COLETA_PARCIAL:
                parciais[p].append(m.coberto_ate[p])
            if serie is None:
                # Escola que MOSTRA a métrica já fixa a soma das escondidas dela (≥ k); a
                # rede menos as partes mostradas dá a soma das escondidas nas escolas que
                # TAMBÉM a esconderam.
                esconde, uniao, sem_numero_escola = _escola_esconde(m, p, k)
                for i, sim in enumerate(esconde):
                    if sim:
                        escondidas[p][i] += uniao[i]
                        sem_numero[p][i] += sem_numero_escola
            else:
                sem_numero_celula = _medidos_sem_numero([soma], k)
                for i, g in enumerate(_escondidas(soma, p, k)):
                    escondidas[p][i] += g
                    sem_numero[p][i] += sem_numero_celula
    blocos = {}
    for p, funcao in (("elefante", metricas_elefante), ("matific", metricas_matific)):
        if PLATAFORMA_MODULO[p] not in t.mods:
            blocos[p] = None
        elif somas[p] is None:
            blocos[p] = funcao(None, k, SEM_ESCOLA_VISIVEL)
        else:
            blocos[p] = funcao(somas[p], k)
            # Na rede inteira, o complemento vale quando as escondidas somam de 1 a k − 1.
            # Numa série, qualquer célula escondida esconde o total da série: cruzado com o
            # total de uma escola (outra resposta), ele isolaria a célula dela.
            _proteger(blocos[p], p, _esconde_no_total(escondidas[p], sem_numero[p], p, k,
                                                      qualquer=serie is not None), k)
            if parciais[p]:
                # A soma vale até a coleta mais antiga das escolas parciais que entraram.
                mais_antiga = min(parciais[p])
                blocos[p]["escolas_coleta_parcial_na_soma"] = len(parciais[p])
                blocos[p]["coberto_ate_parcial"] = _iso_br(mais_antiga)
                blocos[p]["texto_parcial_na_soma"] = (
                    f"{len(parciais[p])} escola(s) entram com a coleta até "
                    f"{para_br(mais_antiga).strftime('%d/%m/%Y')} (cobrem ao menos 90% do "
                    "período; o restante não foi medido — sem dado não é zero).")
    return blocos, entraram


# --- Entradas ---------------------------------------------------------------------------

def plataformas_da_rede(db: Session, rede: Rede, *, preset: str = "ano_letivo",
                        inicio: date | None = None, fim: date | None = None,
                        serie: int | None = None, escola_id: int | None = None,
                        hoje: date, k: int = K_MINIMO) -> dict:
    return plataformas_da_rede_por_periodo(db, rede, [Periodo(preset, inicio, fim)],
                                           serie=serie, escola_id=escola_id, hoje=hoje, k=k)[0]


def plataformas_da_rede_por_periodo(db: Session, rede: Rede, periodos: list[Periodo], *,
                                    serie: int | None = None, escola_id: int | None = None,
                                    hoje: date, k: int = K_MINIMO, so_escola: bool = False,
                                    escolas: list[Escola] | None = None,
                                    mods: set[str] | None = None) -> list[dict]:
    """A resposta de ``plataformas_da_rede`` para cada período, com as leituras do banco
    feitas UMA vez para todos (a evolução por bimestre).

    ``so_escola`` (a ficha da escola): mede SÓ a escola ``escola_id`` — a supressão continua
    a da rede inteira (pelas contagens de todas as escolas, sem medi-las), então os números
    dela são os mesmos da rota da rede. A rede não é medida: ``rede`` e ``cobertura`` saem
    nulos. ``escolas`` e ``mods``: os da rede, quando quem chama já os leu."""
    _validar_serie(serie)
    if escolas is None:
        escolas = escolas_da_rede(db, rede)
    if escola_id is not None and escola_id not in {e.id for e in escolas}:
        raise AnaliseInvalida("Escola não encontrada nesta rede.", 404)
    if so_escola and escola_id is None:
        raise AnaliseInvalida("Para medir só a escola, informe a escola (escola_id).", 422)
    if mods is None:
        mods = svc_modulos.modulos_da_rede(db, rede.id)
    medir = [e for e in escolas if e.id == escola_id] if so_escola else escolas
    tabelas = _tabelas(db, escolas, medir, mods, periodos=periodos, hoje=hoje, k=k,
                       com_primeiro_evento=not so_escola)
    return [_resposta_da_rede(t, p, mods, k, hoje, serie, escola_id, so_escola)
            for t, p in zip(tabelas, periodos)]


def _resposta_da_rede(t: _Tabela, periodo: Periodo, mods: set[str], k: int, hoje: date,
                      serie: int | None, escola_id: int | None, so_escola: bool) -> dict:
    lista = [_escola_json(t.medidas.get(c.escola.id), c, t.decisoes[c.escola.id], mods, k, hoje,
                          serie) for c in t.contagens
             if escola_id is None or c.escola.id == escola_id]
    if so_escola:
        rede = None
    else:
        if serie is None:
            alunos = sum(c.total for c in t.contagens)
            suprimida = 0 < alunos < k
        else:
            alunos = sum(c.series.get(serie, 0) for c in t.contagens)
            # Série filtrada: o total da rede nessa série menos as escolas visíveis daria a
            # soma das células suprimidas — então ele some quando há alguma célula suprimida.
            suprimida = 0 < alunos < k or any(
                d["series"].get(serie, {}).get("suprimido") for d in t.decisoes.values())
        blocos, entraram = _bloco_da_rede(t, k, serie)
        motivo = SUPRIMIDO if suprimida else None
        rede = {"alunos": None if suprimida else alunos,
                "alunos_fora_do_recorte": (None if suprimida else
                                           sum(c.fora for c in t.contagens)),
                "suprimido": suprimida, "motivo_supressao": motivo,
                "texto_supressao": _texto_supressao(motivo),
                "escolas_com_dado": {p: (0 if suprimida else entraram[p])
                                     for p in PLATAFORMA_MODULO},
                "escopo_blocos": ESCOPO_BLOCOS, "texto_blocos": TEXTO_BLOCOS_REDE,
                **({"elefante": None, "matific": None} if suprimida else blocos)}
    return {
        "janela": _janela_json(t.janela, t.ano, t.anos),
        "modulos": {p: PLATAFORMA_MODULO[p] in mods for p in PLATAFORMA_MODULO},
        "k_minimo": k,
        "filtros": {"periodo": periodo.preset,
                    "inicio": periodo.inicio.isoformat() if periodo.inicio else None,
                    "fim": periodo.fim.isoformat() if periodo.fim else None, "serie": serie,
                    "escola_id": escola_id},
        "rede": rede,
        "escolas": lista,
        "cobertura": None if so_escola else _cobertura(t, hoje),
        "limitacoes": _limitacoes(t.anos),
    }


def celulas_da_rede(db: Session, rede: Rede, *, preset: str, inicio: date | None,
                    fim: date | None, hoje: date, k: int = K_MINIMO) -> dict:
    """Para a relação: por escola, o bloco da escola (1º–5º, só as séries visíveis) e o de
    cada série — com as MESMAS decisões de supressão da rota de plataformas."""
    escolas = escolas_da_rede(db, rede)
    mods = svc_modulos.modulos_da_rede(db, rede.id)
    (t,) = _tabelas(db, escolas, escolas, mods, periodos=[Periodo(preset, inicio, fim)],
                    hoje=hoje, k=k)
    lista = [_escola_json(t.medidas.get(c.escola.id), c, t.decisoes[c.escola.id], mods, k, hoje)
             for c in t.contagens]
    return {
        "janela": t.janela, "ano_letivo": t.ano, "anos_letivos": t.anos,
        "modulos": {p: PLATAFORMA_MODULO[p] in mods for p in PLATAFORMA_MODULO},
        "por_escola": {e["escola_id"]: {"escola": e,
                                        "series": {c["serie"]: c for c in e["series"]}}
                       for e in lista},
    }


def plataformas_da_escola(db: Session, escola: Escola, *, preset: str = "ano_letivo",
                          inicio: date | None = None, fim: date | None = None, hoje: date,
                          k: int = K_MINIMO, escopo_rede: bool = True) -> dict:
    """O bloco de plataformas de UMA escola — medindo SÓ ela.

    ``escopo_rede`` (a Secretaria e o admin global, que também leem a rota da rede): a
    supressão é a da REDE inteira (decidida pelas contagens de todas as escolas, sem medi-
    las), e a escola vê exatamente o que a rota da rede mostra para ela — senão a
    Secretaria recomporia uma escola pequena com o total da rede. Sem ``escopo_rede`` (o
    coordenador ou o admin da própria escola, que não leem a rede) e escola sem rede: a
    supressão é decidida só dentro da escola, e nada da resposta depende das outras."""
    rede = db.get(Rede, escola.rede_id) if escola.rede_id is not None else None
    if rede is not None and escopo_rede:
        escolas = escolas_da_rede(db, rede)
        mods = svc_modulos.modulos_da_rede(db, rede.id)
    else:
        escolas = [escola]
        mods = svc_modulos.modulos_da_escola(db, escola)
    (t,) = _tabelas(db, escolas, [escola], mods, periodos=[Periodo(preset, inicio, fim)],
                    hoje=hoje, k=k)
    contagem = next(c for c in t.contagens if c.escola.id == escola.id)
    minha = _escola_json(t.medidas.get(escola.id), contagem, t.decisoes[escola.id], mods, k,
                         hoje)
    janela = (t.medidas[escola.id].janela if escola.id in t.medidas
              else _janela(preset, escola.ano_letivo_ativo, inicio, fim, hoje))
    return {"janela": _janela_json(janela, escola.ano_letivo_ativo, [escola.ano_letivo_ativo]),
            "modulos": {p: PLATAFORMA_MODULO[p] in mods for p in PLATAFORMA_MODULO},
            "k_minimo": k,
            "alunos": minha["alunos"], "suprimido": minha["suprimido"],
            "motivo_supressao": minha["motivo_supressao"],
            "texto_supressao": minha["texto_supressao"],
            "cobertura": minha["cobertura"], "ultima_coleta": minha["ultima_coleta"],
            "coberto_ate": minha["coberto_ate"],
            "dias_desde_ultima_coleta": minha["dias_desde_ultima_coleta"],
            "blocos_parciais": minha["blocos_parciais"], "texto_blocos": minha["texto_blocos"],
            "elefante": minha["elefante"], "matific": minha["matific"],
            "series": minha["series"], "limitacoes": list(LIMITACOES)}
