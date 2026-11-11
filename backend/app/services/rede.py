"""Agregação por REDE / Secretaria de Educação (o tier acima da escola).

Roda SOBRE os dados por escola já existentes — não reimplementa scoring nem toca
em pesos/fórmulas (o motor de pontuação é a fonte única). Cada indicador
municipal é uma soma/média dos indicadores por escola. O isolamento continua por
escola; aqui só se AGREGAM as escolas que pertencem à rede, e NUNCA se expõe PII
de criança nem ranking individual entre escolas (privacidade).

Desempenho: os KPIs de TODAS as escolas da rede saem em 3 consultas agregadas
(GROUP BY escola_id), não em N×3 — uma rede municipal grande tem centenas de
escolas. O filtro de ano correlaciona a coluna por-escola ``Escola.ano_letivo_ativo``
(cada escola tem o seu), nunca uma constante.
"""
from __future__ import annotations

import secrets

from sqlalchemy import (Float, Integer, String, and_, case, cast, delete, false, func,
                        literal_column, null, or_, select, union_all)
from sqlalchemy.orm import Session

from app.models import (
    Aluno,
    Escola,
    Leitura,
    Matricula,
    MetaRede,
    Nota,
    Professor,
    Rede,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
)

# CARIMBO institucional (JSON path, visível em SQL no SQLite e no Postgres): só a
# Nota gravada por `scoring.recalcular_escola` o carrega, com a VERSÃO da régua
# usada. Linhas anteriores (migração 0028: colunas `*_institucional` com default
# 0,0 e SEM backfill) não têm carimbo — a rede NÃO as agrega como zero: ficam
# "pendentes de recálculo" até `scripts.recalcular_institucional --pendentes`.
# Carimbo com versão ANTIGA (ex.: v1 quando a vigente é a v2) continua sendo
# agregado — é número calculado, não ausência —, mas também conta como pendente.
_CARIMBO_INSTITUCIONAL = Nota.detalhes["regua_institucional"]["versao_dificuldade"].as_string()


def _matriculado_no_ano_ativo(turma_ids: list[int] | None = None):
    """EXISTS: o aluno da Nota tem matrícula no ano letivo ATIVO da escola.

    ``turma_ids`` (opcional) restringe a matrícula que conta a essas turmas —
    é por onde entra o corte de elegibilidade (só turmas premiáveis). ``None``
    = qualquer turma (comportamento de sempre)."""
    consulta = (
        select(Matricula.id)
        .where(Matricula.escola_id == Nota.escola_id,
               Matricula.aluno_id == Nota.aluno_id,
               Matricula.ano_letivo == Escola.ano_letivo_ativo)
    )
    if turma_ids is not None:
        consulta = consulta.where(Matricula.turma_id.in_(turma_ids))
    return consulta.exists()


def _carimbo_pendente():
    """Nota que ainda PRECISA de recálculo institucional. Duas situações, a mesma
    regra de ``scripts.recalcular_institucional --pendentes``:

    1. **sem carimbo** — linha anterior à régua institucional (migração 0028, sem
       backfill): a rede a deixa FORA da média (ausência de cálculo, não zero);
    2. **carimbo com versão ≠ da vigente** — foi calculada, é agregada
       normalmente, mas por uma régua antiga (ex.: v1 com a v2 vigente).

    Em SQL, ``carimbo != 'v2'`` é NULL quando não há carimbo — por isso o ``OR``
    explícito com ``IS NULL`` (o caso 1 não pode depender do caso 2)."""
    return or_(_CARIMBO_INSTITUCIONAL.is_(None),
               _CARIMBO_INSTITUCIONAL != dificuldade_livro.VERSAO_VIGENTE)


def _pendentes_recalculo(db: Session, ids: list[int]) -> dict[int, int]:
    """``{escola_id: nº de notas do ano ativo pendentes de recálculo}`` entre os
    alunos ativos matriculados (ver ``_carimbo_pendente``).

    Só CONTA: o que a rede agrega não muda por causa disto — as médias continuam
    lendo qualquer nota carimbada, e trocar a versão da régua não recalcula nada
    sozinho (só o Admin Global, explicitamente, pelo script)."""
    if not ids:
        return {}
    return {linha[0]: int(linha[1] or 0) for linha in db.execute(_q_pendentes(ids)).all()}


def escolas_com_notas_pendentes(db: Session) -> list[int]:
    """Escolas com alguma Nota do ano ativo pendente de recálculo — sem carimbo
    institucional OU carimbada com versão de régua diferente da vigente (para o
    recálculo pós-deploy ser seletivo e idempotente)."""
    ids = [e for (e,) in db.execute(select(Escola.id)).all()]
    return sorted(_pendentes_recalculo(db, ids))
from app.services import (dificuldade_livro, elegibilidade, grupo_pequeno,
                          matific_destaque, modulos, scoring)
from app.services.analise import K_MINIMO

# Regras de "escola que precisa de atenção" (transparentes e auditáveis).
ADOCAO_BAIXA = 40.0      # % de alunos ativos com nota abaixo disto = pouca adoção
# Desempenho baixo é medido no ÍNDICE DA REDE (0–1000, per capita, régua = melhor
# escola do município), NÃO na média 0–100 do motor: aquela é normalizada contra o
# P90 da PRÓPRIA escola, então mede a forma da distribuição interna e não o nível
# — a escola onde todos leem pouco e igual pontuava ACIMA da que lê muito com uma
# cauda parada, e a escola que mais lia no município caía na lista de atenção.
# 300 de 1000 = menos de um terço do desempenho per capita da melhor escola.
INDICE_BAIXO = 300.0


def escolas_da_rede(db: Session, rede_id: int) -> list[Escola]:
    return list(db.execute(
        select(Escola).where(Escola.rede_id == rede_id).order_by(Escola.nome)
    ).scalars().all())


def _motivo_atencao(total_alunos: int, com_dados: int, adocao: float,
                    pontuacao_geral: float) -> str | None:
    """Por que a escola precisa de atenção — ou None se está saudável.

    A ordem importa: falta de aluno e falta de dado vêm ANTES do desempenho,
    para que índice 0 por AUSÊNCIA nunca seja lido como desempenho ruim.
    """
    if total_alunos == 0:
        return "Sem alunos matriculados no ano letivo."
    if com_dados == 0:
        return "Nenhum aluno com dados das plataformas ainda."
    if adocao < ADOCAO_BAIXA:
        return f"Baixa adoção: só {adocao:.0f}% dos alunos têm dados."
    if 0 < pontuacao_geral < INDICE_BAIXO:
        # "Índice", não "desempenho": é a pontuação do Constela pelo USO das plataformas,
        # não avaliação de aprendizagem (o mesmo texto vai para a tela e para o boletim).
        return (f"Índice do Constela baixo frente à rede: {pontuacao_geral:.0f} de 1000 "
                f"(pelo uso das plataformas; 1000 = maior índice da rede).")
    return None


def _matific_no_ano_ativo(anos: dict[int, int]):
    """Condição SQL: o snapshot do Matific é do ano letivo ATIVO da escola dele.

    MATIFIC É CONTADOR DO ANO — a mesma definição de aferido do motor
    (``scoring.snapshots_matific_do_ano``) e a mesma janela
    (``matific_destaque.janela_ano_letivo``). Cada escola tem o seu ano ativo,
    então a janela é montada POR ANO e casada pelo ``escola_id`` (as escolas de
    uma rede costumam estar no mesmo ano: na prática, um termo só). ``anos``:
    ``{escola_id: ano_letivo_ativo}`` das escolas já lidas (sem ir ao banco)."""
    por_ano: dict[int, list[int]] = {}
    for escola_id, ano in anos.items():
        por_ano.setdefault(ano, []).append(escola_id)
    termos = []
    for ano, escolas in por_ano.items():
        inicio, fim = matific_destaque.janela_ano_letivo(ano)
        termos.append(and_(SnapshotMatific.escola_id.in_(escolas),
                           SnapshotMatific.data_referencia >= inicio,
                           SnapshotMatific.data_referencia <= fim))
    return or_(*termos) if termos else false()


def _q_totais(ids: list[int], anos: dict[int, int], modelo, campos: list[str],
              premiaveis: list[int]):
    """Soma, por escola, os campos do snapshot ATUAL de cada aluno (o último por
    data_referencia,id — mesma régua do scoring) e conta os alunos ATIVOS na
    plataforma — de TODOS e, à parte, de quem CONCORRE (matrícula numa turma de
    ``premiaveis``, o corte "as Fases não concorrem" do PER CAPITA). UMA window
    query para a rede inteira e as duas populações. Só números BRUTOS agregados.

    RESTRINGE ao MESMO conjunto das contagens de ``_kpis_da_rede`` (aluno ativo
    E matriculado no ano letivo ATIVO da escola). Sem isso, o snapshot 'preso' de
    um aluno transferido/arquivado (que persiste — o scoring já o filtra de
    propósito) inflava os totais e o ``ativos_*`` frente ao total de alunos. A
    matrícula é ÚNICA por aluno e ano (``uq_matricula_aluno_ano``): a turma é a
    mesma em todas as linhas do aluno, então o retrato atual de quem concorre é o
    mesmo retrato atual dele entre todos — as duas somas saem da mesma numeração.

    MATIFIC É CONTADOR DO ANO (``_matific_no_ano_ativo``): o retrato "atual" é o
    último DENTRO do ano letivo ativo da escola, ANTES de numerar. Sem o corte, as
    estrelas/atividades de outro ano entravam nos totais e no PER CAPITA.

    ``com_<campo>``: quantos alunos têm o campo > 0, isto é, SOMAM no total. É o k
    da vitrine pública (``_top_escolas``): ``ativos`` conta também o retrato com
    zero. Os de quem concorre levam o sufixo ``_p``."""
    filtro = [_matific_no_ano_ativo(anos)] if modelo is SnapshotMatific else []
    numerado = (
        select(
            modelo.escola_id.label("escola_id"),
            *[getattr(modelo, c).label(c) for c in campos],
            case((Matricula.turma_id.in_(premiaveis), 1), else_=0).label("concorre"),
            func.row_number().over(
                partition_by=(modelo.escola_id, modelo.aluno_id),
                order_by=(modelo.data_referencia.desc(), modelo.id.desc()),
            ).label("pos"),
        )
        .join(Aluno, Aluno.id == modelo.aluno_id)
        .join(Escola, Escola.id == modelo.escola_id)
        .join(Matricula, (Matricula.aluno_id == modelo.aluno_id)
              & (Matricula.escola_id == modelo.escola_id)
              & (Matricula.ano_letivo == Escola.ano_letivo_ativo))
        .where(modelo.escola_id.in_(ids), Aluno.status == "ativo", *filtro)
        .subquery()
    )
    n = numerado.c
    concorre = n.concorre == 1
    soma = lambda expr: func.coalesce(func.sum(expr), 0)  # noqa: E731
    colunas = [func.count(), *[soma(n[c]) for c in campos],
               *[soma(case((n[c] > 0, 1), else_=0)) for c in campos],
               soma(n.concorre), *[soma(case((concorre, n[c]), else_=0)) for c in campos],
               *[soma(case((and_(concorre, n[c] > 0), 1), else_=0)) for c in campos]]
    return n.escola_id, colunas, select(*colunas).where(n.pos == 1)


def _totais_lidos(linhas, campos: list[str]) -> tuple[dict[int, dict], dict[int, dict]]:
    """(todos, quem concorre) por escola, no formato de sempre: ``escola_id``,
    ``ativos``, os campos e ``com_<campo>``. A escola sem nenhum aluno que concorre
    com retrato não aparece no segundo (como antes, quando era outra consulta)."""
    todos, concorrem = {}, {}
    k = len(campos)
    for escola_id, *v in linhas:
        v = [int(x or 0) for x in v]
        todos[escola_id] = {"escola_id": escola_id, "ativos": v[0],
                            **dict(zip(campos, v[1:1 + k])),
                            **{f"com_{c}": x for c, x in zip(campos, v[1 + k:1 + 2 * k])}}
        if v[1 + 2 * k]:
            concorrem[escola_id] = {
                "escola_id": escola_id, "ativos": v[1 + 2 * k],
                **dict(zip(campos, v[2 + 2 * k:2 + 3 * k])),
                **{f"com_{c}": x for c, x in zip(campos, v[2 + 3 * k:2 + 4 * k])}}
    return todos, concorrem


def _q_medias(ids: list[int], anos: dict[int, int], modelo, coluna, premiaveis: list[int]):
    """Média da nota de UMA plataforma, SOMENTE sobre os alunos que têm dado dela:
    (escola, alunos com dado, média, quantos com a nota > 0).

    O motor cria uma linha em ``notas`` para TODO aluno matriculado, inclusive quem
    nunca usou a plataforma (nota 0). Se a média incluísse esses zeros, ela mediria
    *desempenho × cobertura*. O corte é pela EXISTÊNCIA de snapshot, nunca por
    ``nota > 0``: quem usa e leu 0 livros é um zero LEGÍTIMO; quem não usa é ausência.

    O conjunto é o dos MATRICULADOS no ano letivo ativo numa turma PREMIÁVEL (as
    Fases não concorrem: ``services.elegibilidade``) — EXISTS, e não JOIN, porque o
    JOIN duplicaria a linha da nota. A nota órfã de quem perdeu a matrícula não
    entra. Leitura ITEMIZADA também é dado do Elefante. MATIFIC É CONTADOR DO ANO:
    "tem dado" do Matific é ter snapshot DENTRO do ano letivo ativo da escola
    (``_matific_no_ano_ativo``). Só notas CALCULADAS pelo motor vigente (nunca o
    default 0,0). A quarta coluna é o ``grupo_pequeno`` da Secretaria."""
    tem_dado = (select(modelo.id)
                .where(modelo.escola_id == Nota.escola_id, modelo.aluno_id == Nota.aluno_id))
    if modelo is SnapshotMatific:
        tem_dado = tem_dado.where(_matific_no_ano_ativo(anos))
    tem_dado = tem_dado.exists()
    if modelo is SnapshotElefante:
        tem_dado = tem_dado | (
            select(Leitura.id)
            .where(Leitura.escola_id == Nota.escola_id, Leitura.aluno_id == Nota.aluno_id)
            .exists()
        )
    colunas = [func.count(Nota.id), func.coalesce(func.sum(case((coluna > 0, 1), else_=0)), 0),
               func.avg(coluna)]
    return colunas, (
        select(Nota.escola_id, *colunas)
        .join(Aluno, Aluno.id == Nota.aluno_id)
        .join(Escola, Escola.id == Nota.escola_id)
        .where(Nota.escola_id.in_(ids),
               Nota.ano_letivo == Escola.ano_letivo_ativo,
               Aluno.status == "ativo",
               _matriculado_no_ano_ativo(turma_ids=premiaveis),
               tem_dado,
               _CARIMBO_INSTITUCIONAL.isnot(None))
        .group_by(Nota.escola_id))


def _medias_por_plataforma(db: Session, ids: list[int], modelo, coluna,
                           turmas_premiaveis: list[int] | None = None, *,
                           com_positivas: bool = False) -> dict[int, tuple]:
    """A média de UMA plataforma por escola, sozinha (``_q_medias``; os cartões a leem
    junto com o resto, em ``_leituras_da_rede``). Devolve ``{escola_id: (alunos_com_dado,
    media)}``; ``com_positivas`` acrescenta quantos têm a nota > 0. ``None`` em
    ``turmas_premiaveis`` = calcula aqui."""
    if not ids:
        return {}
    anos = dict(db.execute(select(Escola.id, Escola.ano_letivo_ativo)
                           .where(Escola.id.in_(ids))).all())
    if turmas_premiaveis is None:
        turmas_premiaveis = elegibilidade.turmas_premiaveis_da_rede(db, ids)
    _colunas, q = _q_medias(ids, anos, modelo, coluna, turmas_premiaveis)
    linhas = db.execute(q).all()
    if com_positivas:
        return {e: (int(n or 0), float(m or 0.0), int(p or 0)) for e, n, p, m in linhas}
    return {e: (int(n or 0), float(m or 0.0)) for e, n, p, m in linhas}


def _q_com_dado(ids: list[int], modelo):
    """(escola, aluno) DISTINTOS com retrato da plataforma, entre os alunos ativos e
    matriculados no ano letivo ativo — o numerador honesto da cobertura: alunos com
    dado de ALGUMA plataforma (a contagem antiga, por linhas de ``notas``, dava ~100%)."""
    return (select(modelo.escola_id, modelo.aluno_id)
            .join(Aluno, Aluno.id == modelo.aluno_id)
            .join(Escola, Escola.id == modelo.escola_id)
            .join(Matricula, (Matricula.aluno_id == modelo.aluno_id)
                  & (Matricula.escola_id == modelo.escola_id)
                  & (Matricula.ano_letivo == Escola.ano_letivo_ativo))
            .where(modelo.escola_id.in_(ids), Aluno.status == "ativo")
            .distinct())


# O retrato de cada módulo do catálogo: quem tem dado de um módulo, para a COBERTURA.
_RETRATO_DO_MODULO = (("leitura", SnapshotElefante), ("matematica", SnapshotMatific))


def _retratos_contratados(contratados) -> list:
    """Os modelos de retrato dos módulos CONTRATADOS (``None`` = todos, como a escola
    avulsa). A cobertura (``alunos_com_dados``) só conta a plataforma que a rede
    assinou: o retrato antigo de um módulo fora do plano (rede que deixou de contratar
    a Matemática, escola que veio de outra rede) não é adoção — a mesma regra das
    médias e do índice (``_cartoes_da_rede``)."""
    return [modelo for modulo, modelo in _RETRATO_DO_MODULO
            if contratados is None or modulo in contratados]


def _alunos_com_qualquer_dado(db: Session, ids: list[int],
                              contratados: set[str] | None = None) -> dict[int, int]:
    """Alunos DISTINTOS com dado de ALGUMA plataforma CONTRATADA, por escola, sozinho
    (``_q_com_dado``; os cartões o leem junto com o resto, em ``_leituras_da_rede``).
    ``contratados`` = os módulos da rede (``None`` = todos)."""
    if not ids:
        return {}
    total: dict[int, set[int]] = {}
    for modelo in _retratos_contratados(contratados):
        for escola_id, aluno_id in db.execute(_q_com_dado(ids, modelo)).all():
            total.setdefault(escola_id, set()).add(aluno_id)
    return {escola_id: len(alunos) for escola_id, alunos in total.items()}


def _q_pendentes(ids: list[int]):
    """As notas do ano ativo pendentes de recálculo por escola (``_carimbo_pendente``)."""
    return (select(Nota.escola_id, func.count(Nota.id))
            .join(Aluno, Aluno.id == Nota.aluno_id)
            .join(Escola, Escola.id == Nota.escola_id)
            .where(Nota.escola_id.in_(ids),
                   Nota.ano_letivo == Escola.ano_letivo_ativo,
                   Aluno.status == "ativo",
                   _matriculado_no_ano_ativo(),
                   _carimbo_pendente())
            .group_by(Nota.escola_id))


def _ramo(fonte: str, colunas: list, larguras: dict) -> list:
    """As colunas de UM ramo de um ``UNION ALL``: a fonte, as dele e nulos TIPADOS no
    lugar das dos outros ramos (``larguras``: tipo SQL → quantas colunas)."""
    saida = [literal_column(f"'{fonte}'")]
    for tipo, quantas in larguras.items():
        minhas = [c for c, t in colunas if t is tipo]
        assert len(minhas) <= quantas, f"o ramo {fonte} tem mais colunas que a largura do UNION"
        saida += minhas + [cast(null(), tipo) for _ in range(quantas - len(minhas))]
    assert len(colunas) == sum(1 for _, t in colunas if t in larguras), fonte
    # Um rótulo por POSIÇÃO: o ramo lido sozinho (``_ler_ramos``) não confunde os nulos.
    return [c.label(f"c{i}") for i, c in enumerate(saida)]


_INT, _TXT, _NUM = Integer, String, Float
# Teto de parâmetros por comando: o PostgreSQL aceita até 65.535 e cada valor de um IN é um
# parâmetro. Acima disto (rede muito grande, muitas turmas acumuladas), os ramos vão um a um.
_TETO_PARAMETROS = 30_000


def _ler_ramos(db: Session, partes: list, parametros: int) -> list:
    """As linhas de todos os ramos: num ``UNION ALL`` só (uma ida ao banco) ou, se os
    parâmetros passariam do teto, ramo a ramo (o mesmo SQL de cada um)."""
    if parametros <= _TETO_PARAMETROS:
        return list(db.execute(union_all(*partes)).all())
    return [linha for parte in partes for linha in db.execute(parte).all()]


def _leituras_da_rede(db: Session, escolas: list[Escola], contratados: set[str], *,
                      com_pendentes: bool) -> dict:
    """Tudo o que os cartões das escolas leem do banco, em DUAS consultas (cada uma um
    ``UNION ALL`` de agregados que já eram consultas separadas, com o MESMO SQL de cada
    um): (A) turmas, alunos, professores, a lista de turmas (para as premiáveis), quem
    tem dado de alguma plataforma (com a turma, para separar quem concorre) e — no
    painel — as notas pendentes; (B), que depende das turmas premiáveis, quem concorre,
    as médias por plataforma e os totais. Antes eram 17 consultas; em produção cada uma
    custa ~195 ms de ida e volta ao banco."""
    ids = [e.id for e in escolas]
    anos = {e.id: e.ano_letivo_ativo for e in escolas}
    contagens = {
        "turmas": (Turma.escola_id, [(func.count(Turma.id), _INT)],
                   lambda q: q.where(Turma.escola_id.in_(ids),
                                     Turma.ano_letivo == Escola.ano_letivo_ativo,
                                     Turma.status == "ativa")
                   .join_from(Turma, Escola, Escola.id == Turma.escola_id)
                   .group_by(Turma.escola_id)),
        "alunos": (Matricula.escola_id,
                   [(func.count(func.distinct(Matricula.aluno_id)), _INT)],
                   lambda q: q.join_from(Matricula, Aluno, Aluno.id == Matricula.aluno_id)
                   .join(Escola, Escola.id == Matricula.escola_id)
                   .where(Matricula.escola_id.in_(ids),
                          Matricula.ano_letivo == Escola.ano_letivo_ativo,
                          Aluno.status == "ativo")
                   .group_by(Matricula.escola_id)),
        "professores": (Professor.escola_id, [(func.count(Professor.id), _INT)],
                        lambda q: q.where(Professor.escola_id.in_(ids))
                        .group_by(Professor.escola_id)),
    }
    larg_a = {_INT: 3, _TXT: 1}
    partes = [m(select(*_ramo(f, [(e, _INT), *c], larg_a)))
              for f, (e, c, m) in contagens.items()]
    partes.append(select(*_ramo("turma", [(Turma.escola_id, _INT), (Turma.id, _INT),
                                          (Turma.ano_escolar, _TXT)], larg_a))
                  .where(Turma.escola_id.in_(ids)))
    for modelo in _retratos_contratados(contratados):
        # A turma da matrícula do ano vai junto: é por ela que se sabe quem CONCORRE.
        q = _q_com_dado(ids, modelo)
        partes.append(q.with_only_columns(*_ramo(
            "dado", [(modelo.escola_id, _INT), (modelo.aluno_id, _INT),
                     (Matricula.turma_id, _INT)], larg_a)))
    if com_pendentes:
        q = _q_pendentes(ids)
        partes.append(q.with_only_columns(*_ramo(
            "pendentes", [(Nota.escola_id, _INT), (func.count(Nota.id), _INT)], larg_a)))
    lido: dict = {"turmas": {}, "alunos": {}, "professores": {}, "pendentes": {}}
    turmas_e_rotulos, com_dado = [], {}
    for fonte, a, b, turma_id, rotulo in _ler_ramos(db, partes, 8 * len(ids)):
        if fonte == "turma":
            turmas_e_rotulos.append((b, rotulo))
        elif fonte == "dado":
            com_dado.setdefault(a, {})[b] = turma_id
        else:
            lido[fonte][a] = int(b or 0)
    # (as Fases não concorrem: a mesma regra de ``elegibilidade.turmas_premiaveis_da_rede``)
    premiaveis = [tid for tid, rotulo in turmas_e_rotulos
                  if elegibilidade.participa_de_premiacao(rotulo)]
    lido["com_dados"] = {e: len(alunos) for e, alunos in com_dado.items()}
    # Quem CONCORRE (turma premiável) entre os que têm dado: o peso da média geral
    # da rede (``_media_geral_das_comparadas``), que só mede as turmas premiáveis.
    so_premiaveis = set(premiaveis)
    lido["com_dados_premiaveis"] = {
        e: sum(1 for turma in alunos.values() if turma in so_premiaveis)
        for e, alunos in com_dado.items()}

    # (B) — depende das turmas premiáveis.
    larg_b = {_INT: 11, _NUM: 1}
    partes = [select(*_ramo("alunos_p", [
        (Matricula.escola_id, _INT), (func.count(func.distinct(Matricula.aluno_id)), _INT)],
        larg_b))
        .join_from(Matricula, Aluno, Aluno.id == Matricula.aluno_id)
        .join(Escola, Escola.id == Matricula.escola_id)
        .where(Matricula.escola_id.in_(ids), Matricula.ano_letivo == Escola.ano_letivo_ativo,
               Matricula.turma_id.in_(premiaveis), Aluno.status == "ativo")
        .group_by(Matricula.escola_id)]
    # RÉGUA INSTITUCIONAL: a rede lê SEMPRE as colunas `nota_*_institucional` (perfil fixo do
    # Constela), nunca a nota LOCAL da escola — senão um coordenador mexeria na posição da escola
    # no ranking da rede mudando os próprios pesos. Travado por test_scoring_institucional.py.
    medias = {"med_ele": ("leitura", SnapshotElefante, Nota.nota_elefante_institucional),
              "med_mat": ("matematica", SnapshotMatific, Nota.nota_matific_institucional)}
    for fonte, (modulo, modelo, coluna) in medias.items():
        if modulo in contratados:
            (n, positivas, media), q = _q_medias(ids, anos, modelo, coluna, premiaveis)
            partes.append(q.with_only_columns(*_ramo(fonte, [
                (Nota.escola_id, _INT), (n, _INT), (positivas, _INT), (media, _NUM)], larg_b)))
    totais = {"tot_mat": (SnapshotMatific, ["atividades", "estrelas"]),
              "tot_ele": (SnapshotElefante, ["livros_unicos", "tempo_leitura_min"])}
    for fonte, (modelo, campos) in totais.items():
        escola, colunas, q = _q_totais(ids, anos, modelo, campos, premiaveis)
        partes.append(q.with_only_columns(*_ramo(
            fonte, [(escola, _INT), *[(c, _INT) for c in colunas]], larg_b))
            .group_by(escola))
    linhas_b: dict[str, list] = {f: [] for f in ("alunos_p", *medias, *totais)}
    for fonte, *resto in _ler_ramos(db, partes, 5 * len(premiaveis) + 8 * len(ids)):
        linhas_b[fonte].append(resto)
    lido["alunos_premiaveis"] = {r[0]: int(r[1] or 0) for r in linhas_b["alunos_p"]}
    for fonte in medias:
        # (alunos com dado, média, quantos com a nota > 0) — o formato de sempre.
        lido[fonte] = {r[0]: (int(r[1] or 0), float(r[-1] or 0.0), int(r[2] or 0))
                       for r in linhas_b[fonte]}
    for fonte, (_modelo, campos) in totais.items():
        k = 2 + 4 * len(campos)          # ativos, somas, com_, quem concorre: ativos, somas, com_
        lido[fonte], lido[f"{fonte}_p"] = _totais_lidos(
            [(r[0], *r[1:1 + k]) for r in linhas_b[fonte]], campos)
    return lido


def _kpis_da_rede(db: Session, rede_id: int, *, com_contribuintes: bool = False,
                  contratados: set[str] | None = None) -> list[dict]:
    """Os cartões das escolas (ver ``_cartoes_da_rede``)."""
    return _cartoes_da_rede(db, rede_id, com_contribuintes=com_contribuintes,
                            contratados=contratados)[0]


def _cartoes_da_rede(db: Session, rede_id: int, *, com_contribuintes: bool = False,
                     contratados: set[str] | None = None, com_pendentes: bool = False
                     ) -> tuple[list[dict], dict[int, int]]:
    """Cartão resumido de CADA escola da rede (contagens + médias + totais brutos
    das plataformas do ano letivo ativo da própria escola), agregado no banco.
    ``adocao`` = % de alunos ativos com dado de alguma plataforma CONTRATADA (proxy
    de engajamento). Escolas sem dados entram com zeros. NUNCA expõe PII: só agregados por escola.

    ``com_contribuintes`` (só a resposta da Secretaria pede) acrescenta a cada
    cartão a chave INTERNA ``_contribuintes`` (``_contribuintes_do_cartao``),
    que ``_proteger_cartoes`` usa para decidir o grupo pequeno e tira antes de
    responder. Sem ela, o cartão de sempre. ``contratados``: os módulos da rede,
    quando quem chama já os leu. ``com_pendentes`` (o painel): devolve também as
    notas pendentes de recálculo por escola (``_pendentes_recalculo``), lidas na
    mesma consulta. Devolve (cartões, pendentes)."""
    escolas = escolas_da_rede(db, rede_id)
    if not escolas:
        return [], {}
    # MÓDULOS CONTRATADOS pela rede (SaaS). O que não foi contratado não entra em
    # média, ranking nem adoção — e NÃO é a mesma coisa que "sem dados": módulo
    # contratado sem importação continua valendo e aparece vazio na tela.
    if contratados is None:
        contratados = modulos.modulos_da_rede(db, rede_id)
    lido = _leituras_da_rede(db, escolas, contratados, com_pendentes=com_pendentes)
    turmas, alunos, professores = lido["turmas"], lido["alunos"], lido["professores"]
    alunos_premiaveis = lido["alunos_premiaveis"]
    # DESEMPENHO por plataforma — média só sobre quem TEM dado dela, pela RÉGUA
    # INSTITUCIONAL (as colunas `nota_*_institucional`, imunes à configuração local
    # da escola: travado por test_scoring_institucional.py). COBERTURA: alunos
    # distintos com dado de alguma plataforma. Totais BRUTOS do snapshot atual de
    # cada aluno (todos e só quem concorre — o numerador do per capita).
    med_ele, med_mat = lido.get("med_ele", {}), lido.get("med_mat", {})
    com_dados_por_escola = lido["com_dados"]
    com_dados_premiaveis = lido["com_dados_premiaveis"]
    mat, mat_p = lido["tot_mat"], lido["tot_mat_p"]
    ele, ele_p = lido["tot_ele"], lido["tot_ele_p"]

    cartoes = []
    for escola in escolas:
        total_alunos = int(alunos.get(escola.id, 0))
        # DESEMPENHO: média de quem TEM dado da plataforma (ausência ≠ zero).
        n_ele, media_elefante = med_ele.get(escola.id, (0, 0.0))[:2]
        n_mat, media_matific = med_mat.get(escola.id, (0, 0.0))[:2]
        media_elefante = round(media_elefante, 1)
        media_matific = round(media_matific, 1)
        # A geral é a média das DIMENSÕES DISPONÍVEIS (não a média das notas
        # gerais dos alunos): assim a escola que usa só uma plataforma não é
        # dividida por dois — a ausência sai da conta em vez de valer zero.
        disponiveis = [m for m, n in ((media_elefante, n_ele), (media_matific, n_mat)) if n]
        media_geral = round(sum(disponiveis) / len(disponiveis), 1) if disponiveis else 0.0
        dimensoes_com_dados = [nome for nome, n in (("leitura", n_ele), ("matematica", n_mat)) if n]
        # COBERTURA: quantos alunos de fato usam (o que a "adoção" sempre quis dizer).
        com_dados = int(com_dados_por_escola.get(escola.id, 0))
        adocao = round(com_dados / total_alunos * 100, 1) if total_alunos else 0.0
        m, e = mat.get(escola.id), ele.get(escola.id)
        livros = int(e["livros_unicos"]) if e else 0
        ativos_ele = int(e["ativos"]) if e else 0
        estrelas = int(m["estrelas"]) if m else 0
        atividades = int(m["atividades"]) if m else 0
        tempo_min = int(e["tempo_leitura_min"]) if e else 0
        # PER CAPITA só de quem concorre (numerador E denominador).
        n_p = int(alunos_premiaveis.get(escola.id, 0))
        mp, ep = mat_p.get(escola.id), ele_p.get(escola.id)
        livros_p = int(ep["livros_unicos"]) if ep else 0
        tempo_p = int(ep["tempo_leitura_min"]) if ep else 0
        estrelas_p = int(mp["estrelas"]) if mp else 0
        atividades_p = int(mp["atividades"]) if mp else 0
        cartoes.append({
            "escola_id": escola.id, "nome": escola.nome, "cidade": escola.cidade,
            "status": escola.status,
            "latitude": escola.latitude, "longitude": escola.longitude,
            "total_turmas": int(turmas.get(escola.id, 0)),
            "total_professores": int(professores.get(escola.id, 0)),
            "total_alunos": total_alunos,
            # DESEMPENHO (0–100) — só de quem tem dado da plataforma.
            "media_geral": media_geral,
            "media_matific": media_matific,
            "media_elefante": media_elefante,
            "dimensoes_com_dados": dimensoes_com_dados,
            "alunos_com_nota_elefante": n_ele,
            "alunos_com_nota_matific": n_mat,
            # ENGAJAMENTO / COBERTURA — quantos usam (conceito SEPARADO do acima).
            "alunos_com_dados": com_dados,
            "adocao": adocao,
            # Os mesmos, só entre quem CONCORRE (1º–5º ano): o peso da escola na
            # média geral da rede, que só mede as turmas premiáveis.
            "alunos_com_dados_premiaveis": int(com_dados_premiaveis.get(escola.id, 0)),
            # Totais brutos das plataformas (para as seções Elefante/Matific da rede).
            "livros": livros,
            "tempo_leitura_min": tempo_min,
            "atividades": atividades,
            "estrelas": estrelas,
            "ativos_matific": int(m["ativos"]) if m else 0,
            "ativos_elefante": ativos_ele,
            # Adoção POR PLATAFORMA: a leitura mais acionável para a Secretaria
            # ("53% usam o Elefante, 80% usam o Matific") — separada do desempenho.
            "adocao_elefante": round(ativos_ele / total_alunos * 100, 1) if total_alunos else 0.0,
            "adocao_matific": (round(int(m["ativos"]) / total_alunos * 100, 1)
                               if (m and total_alunos) else 0.0),
            # Módulos CONTRATADOS pela rede — a interface usa isto para não
            # renderizar (nem como zero) o que não faz parte do plano.
            "modulos": sorted(contratados),
            "livros_por_aluno": round(livros / ativos_ele, 1) if ativos_ele else 0.0,
            # Per capita por MATRÍCULA — critério de ranking JUSTO entre escolas
            # de tamanhos diferentes: combina adoção e intensidade e NÃO favorece
            # a escola grande pelo volume bruto (item 1). É a conta do dono:
            # 19.122÷200≈95,6 supera 24.000÷600=40. Numerador e denominador são
            # SÓ de quem concorre (1º–5º ano): as Fases não concorrem, nem
            # diluindo o denominador nem somando livros no numerador.
            "alunos_premiaveis": n_p,
            "livros_premiaveis": livros_p,
            # Horas lidas da MESMA população (a coluna "Horas lidas" da aba
            # Leitura fica ao lado de "Alunos (1º–5º)" e "Livros lidos").
            "tempo_premiaveis_min": tempo_p,
            "estrelas_premiaveis": estrelas_p,
            "atividades_premiaveis": atividades_p,
            "ativos_elefante_premiaveis": int(ep["ativos"]) if ep else 0,
            "ativos_matific_premiaveis": int(mp["ativos"]) if mp else 0,
            # Quem SOMA no numerador do per capita (valor > 0): o k da vitrine pública
            # (``_top_escolas``). Só contagens, nenhum dado individual.
            "com_livros_premiaveis": int(ep["com_livros_unicos"]) if ep else 0,
            "com_estrelas_premiaveis": int(mp["com_estrelas"]) if mp else 0,
            "livros_por_matricula": round(livros_p / n_p, 1) if n_p else 0.0,
            "estrelas_por_matricula": round(estrelas_p / n_p, 1) if n_p else 0.0,
            "atividades_por_matricula": round(atividades_p / n_p, 1) if n_p else 0.0,
            "tempo_por_matricula_min": round(tempo_p / n_p, 1) if n_p else 0.0,
        })
        if com_contribuintes:
            cartoes[-1]["_contribuintes"] = _contribuintes_do_cartao(
                {"leitura": med_ele.get(escola.id), "matematica": med_mat.get(escola.id)},
                {"leitura": (e, ep), "matematica": (m, mp)})
    # O índice comparável é resolvido com a COORTE inteira em mãos (a régua é a
    # melhor escola da rede), e só então o alerta de atenção — que agora depende
    # dele — pode ser decidido. Por isso os dois passos vêm depois do laço.
    _pontuar_por_percapita(cartoes)
    for cartao in cartoes:
        motivo = _motivo_atencao(cartao["total_alunos"], cartao["alunos_com_dados"],
                                 cartao["adocao"], cartao["pontuacao_geral"])
        cartao["precisa_atencao"] = motivo is not None
        cartao["motivo_atencao"] = motivo
    return cartoes, lido["pendentes"]


def _contribuintes_do_cartao(medias: dict, totais: dict) -> dict:
    """{matéria: {"media_positiva", "contribuintes", "contribuintes_concorrem"}}
    de UM cartão, no formato de ``grupo_pequeno.decidir_escola``.

    ``medias[matéria]`` é a linha de ``_q_medias`` com
    ``com_positivas`` (n, média, n com nota > 0) e ``totais[matéria]`` é o par
    (todos, quem concorre) de ``_q_totais`` (``_totais_lidos``), que já traz
    ``com_<campo>``: quantas crianças têm o campo > 0, isto é, SOMAM no total. É
    o mesmo k sobre quem soma da vitrine pública (``_top_escolas``); ``ativos``
    conta também o retrato zerado e não serve para isso. Os campos são os que o
    cartão soma (``grupo_pequeno.CAMPOS_DO_PER_CAPITA``), iguais nos dois."""
    def _somam(linha, campos) -> dict[str, int]:
        return {campo: (int(linha[f"com_{campo}"]) if linha else 0) for campo in campos}

    saida = {}
    for dimensao, (todos, concorrem) in totais.items():
        media = medias.get(dimensao)
        campos = grupo_pequeno.CAMPOS_DO_PER_CAPITA[dimensao]
        saida[dimensao] = {"media_positiva": int(media[2]) if media else 0,
                           "contribuintes": _somam(todos, campos),
                           "contribuintes_concorrem": _somam(concorrem, campos)}
    return saida


# ---------------------------------------------------------------------------
# ÍNDICE DA REDE (0–1000) — pontuação COMPARÁVEL ENTRE escolas
# ---------------------------------------------------------------------------
# Por que NÃO reusar media_elefante/media_matific aqui: aquelas notas (0–100) são
# normalizadas contra a régua da PRÓPRIA escola (P90 dos alunos dela, ver
# scoring._referencias) — um "60" numa escola não equivale a um "60" noutra. Elas
# servem ao ranking INTERNO (competição entre colegas), não à comparação entre
# escolas. O índice da rede usa a MESMA primitiva de normalização do motor
# (``scoring.normalizar``), mudando só duas coisas: a COORTE passa a ser a REDE
# (a régua é a melhor escola, não a própria escola) e o indicador é PER CAPITA —
# que é o que torna escolas de tamanhos diferentes comparáveis. Nenhuma segunda
# lógica de pontuação: é o mesmo motor com outro escopo.
#
# Régua = MELHOR ESCOLA DA REDE (não o P90): entre poucas dezenas de escolas o
# P90 empataria o pódio inteiro no teto (10% das escolas), e o pódio é justamente
# o que a Secretaria lê. Com o máximo, o índice é estritamente monotônico —
# a ordem do ranking e a pontuação nunca se contradizem — e a leitura é direta:
# "1000 = melhor da rede; 500 = metade do desempenho da melhor".
ESCALA_INDICE = 10.0          # 0–100 do motor → 0–1000 exibido na rede


def _indice_da_rede(valor: float, melhor: float) -> float:
    """Indicador per capita → índice 0–1000 na régua da REDE (melhor escola=1000).
    Reusa ``scoring.normalizar`` (linear, teto 100) e só reescala para 0–1000."""
    return round(scoring.normalizar(valor, melhor) * ESCALA_INDICE, 1)


def _pontuar_por_percapita(cartoes: list[dict], sufixo: str = "") -> None:
    """Acrescenta a cada cartão o índice por DIMENSÃO (leitura/matemática) e o
    geral, IN PLACE. As dimensões são conceitos distintos e cada uma tem o seu
    indicador per capita como base:

      * leitura     → livros por aluno   (o critério principal do ranking de leitura)
      * matemática  → estrelas por aluno

    ``pontuacao_geral`` é a média das dimensões em que a escola TEM dados: uma
    escola que só usa o Elefante não é punida com um zero de Matific que não
    reflete desempenho, e ``dimensoes_pontuadas`` diz quais entraram na conta
    (a interface mostra isso, para a Secretaria saber o que está comparando).

    ESCOPO = a COORTE recebida, e a régua é o melhor cartão dela. A função não
    sabe (nem precisa saber) se os cartões são escolas de uma rede, escolas de
    TODAS as redes ou redes inteiras: o que ela exige é ``livros_por_matricula``
    / ``estrelas_por_matricula`` (per capita, é o que torna unidades de tamanhos
    diferentes comparáveis) e as contagens de ativos. Comparar índices de
    coortes DIFERENTES não é válido — por isso o painel global pontua as escolas
    de novo, com escopo global, em ``sufixo="_global"``, em vez de reaproveitar
    o índice de rede.

    A RÉGUA de cada dimensão sai SÓ da coorte daquela dimensão — os cartões que
    de fato entram na pontuação dela (contratada **e** com dados). Um cartão de
    fora não pode definir a régua de quem está dentro: no painel global a coorte
    mistura redes com CONTRATOS diferentes, e uma rede que não assinou a Leitura
    (mas tem dado antigo do Elefante em banco) puxava ``melhor_leitura`` para
    cima e rebaixava o índice de Leitura de todas as redes que assinaram — sem
    aparecer em ranking nenhum. É o mesmo princípio de ``scoring._referencias`` e
    de ``_carregar_contexto``: a referência sai do conjunto PONTUADO, nunca de
    quem está fora dele. Dentro de UMA rede o contrato é o mesmo para todas as
    escolas e quem não tem dado tem per capita 0, então a régua não muda —
    nenhum número do painel municipal se move.

    GRUPO PEQUENO (só na resposta da Secretaria, ``_proteger_cartoes``): a
    matéria listada na chave interna ``_fora_do_indice`` do cartão fica fora da
    coorte dela — nem é pontuada nem serve de régua. Sem isso, se a escola
    escondida fosse a melhor da rede, o índice de qualquer outra (com o per
    capita dela, que é visível) devolveria o per capita da escondida. Cartão sem
    a chave (todos os outros chamadores) = exatamente a régua de sempre."""
    if not cartoes:
        return

    def _na_coorte(c: dict, dimensao: str, ativos: str) -> bool:
        """O cartão entra na pontuação (e, portanto, na régua) desta dimensão?
        São dois cortes: módulo fora do plano nem existe; módulo contratado sem
        importação existe, mas ainda não tem o que pontuar."""
        if dimensao in c.get("_fora_do_indice", ()):
            return False
        # Ativos ENTRE OS QUE CONCORREM quando o cartão os traz (escola só com a
        # Educação Infantil usando a plataforma não pontua: per capita 0 não é
        # desempenho, é ausência de quem concorre).
        ativos_cartao = c.get(f"{ativos}_premiaveis", c[ativos])
        return ativos_cartao > 0 and dimensao in (c.get("modulos") or list(modulos.TODOS))

    melhor_leitura = max((c["livros_por_matricula"] for c in cartoes
                          if _na_coorte(c, "leitura", "ativos_elefante")), default=0.0)
    melhor_matematica = max((c["estrelas_por_matricula"] for c in cartoes
                             if _na_coorte(c, "matematica", "ativos_matific")), default=0.0)
    for c in cartoes:
        tem_leitura = _na_coorte(c, "leitura", "ativos_elefante")
        tem_matematica = _na_coorte(c, "matematica", "ativos_matific")
        leitura = (_indice_da_rede(c["livros_por_matricula"], melhor_leitura)
                   if tem_leitura else 0.0)
        matematica = (_indice_da_rede(c["estrelas_por_matricula"], melhor_matematica)
                      if tem_matematica else 0.0)
        c["pontuacao_leitura" + sufixo] = leitura
        c["pontuacao_matematica" + sufixo] = matematica
        disponiveis = [p for p, tem in ((leitura, tem_leitura),
                                        (matematica, tem_matematica)) if tem]
        c["pontuacao_geral" + sufixo] = (
            round(sum(disponiveis) / len(disponiveis), 1) if disponiveis else 0.0)
        c["dimensoes_pontuadas" + sufixo] = [
            nome for nome, tem in (("leitura", tem_leitura),
                                   ("matematica", tem_matematica)) if tem]


def tem_dado_de_quem_concorre(cartao: dict) -> bool:
    """A escola entra nas comparações ENTRE escolas (ranking, equidade, índice
    e média geral da rede, e a marca ``comparada`` que o painel e o Boletim
    leem)? Só se alguma dimensão contratada foi pontuada — isto é, se algum
    aluno que CONCORRE (1º–5º ano) tem dado dela.

    ``alunos_com_dados > 0`` não serve aqui: ele conta TODOS os matriculados
    (cobertura), inclusive a Educação Infantil. A escola em que só as Fases usam
    a plataforma (ou que só tem dado de um módulo fora do plano) tem per capita 0
    e fica fora da coorte do índice — por AUSÊNCIA de quem concorre, não por
    desempenho. Com o filtro antigo ela entrava no ranking em último, com
    "0,0 livros/aluno", levava o ``gap_indice`` a 1000 e puxava o índice da rede
    para baixo."""
    return bool(cartao.get("dimensoes_pontuadas"))


# Os PESOS da rede que não são por dimensão (``_ponderada``: o peso é o denominador
# da métrica). O índice 0–1000 é per capita POR MATRÍCULA de quem concorre (livros e
# estrelas ÷ ``alunos_premiaveis``), então o índice da rede ponderado por ele é o per
# capita da rede inteira na régua da melhor escola. A média geral 0–100 é desempenho
# de quem TEM dado, só nas turmas premiáveis. Nenhum dos dois é a cobertura
# (``alunos_com_dados``), que conta também as crianças das Fases.
PESO_DO_INDICE = "alunos_premiaveis"
PESO_DA_MEDIA_GERAL = "alunos_com_dados_premiaveis"


def _ponderada(cartoes: list[dict], chave: str, peso: str) -> float:
    """Média de ``chave`` sobre ``cartoes`` PONDERADA por ``peso`` (não média de
    médias, que daria peso igual a uma escola de 10 e uma de 500 alunos).

    O PESO é o DENOMINADOR DAQUELA MÉTRICA (Arquitetura 2, spec §1.2 — ausência
    não é zero, também na rede). Para as médias POR DIMENSÃO o denominador é o
    número de alunos aferidos NAQUELA dimensão, não "alunos com dado de alguma
    plataforma": com o peso genérico, a escola que não usa o Elefante entrava na
    média de LEITURA da rede com `media_elefante = 0` e puxava o número para
    baixo — o mesmo "ausência vira zero" que a arquitetura elimina no aluno,
    reaparecendo um nível acima. Peso total zero = nada medido → 0.0 (quem
    exibe distingue isso pelo próprio denominador).

    Não há peso padrão: cada chamada diz o denominador da sua métrica. O antigo
    padrão (``alunos_com_dados``, cobertura de TODOS os matriculados) contava as
    crianças das Fases, que não entram no índice nem nas médias de escola
    nenhuma — e era o peso do índice e da média geral da rede.

    Valor NULO é a matéria escondida da Secretaria (grupo pequeno, ver
    ``_proteger_cartoes``): sai da conta junto com o seu peso, como ausência.
    Para os outros perfis nenhum valor é nulo e a conta é a de sempre."""
    validos = [c for c in cartoes if c[chave] is not None]
    total = sum(c[peso] for c in validos)
    if not total:
        return 0.0
    return round(sum(c[chave] * c[peso] for c in validos) / total, 1)


def _media_geral_das_comparadas(cartoes: list[dict]) -> float:
    """``media_geral`` (0–100) de um conjunto de escolas — a ÚNICA fórmula dela,
    usada pelo painel da rede (``dashboard_rede``), pelo cartão de cada rede no
    Panorama Global e pelo total global (``dashboard_global``).

    Pondera por ``alunos_com_dados_premiaveis`` (``PESO_DA_MEDIA_GERAL``): quem
    CONCORRE (1º–5º ano) e tem dado de alguma plataforma, o denominador dela — as
    médias da escola só olham as turmas premiáveis. Com ``alunos_com_dados``
    (cobertura, que conta também as Fases), a escola com mais crianças da
    Educação Infantil usando a plataforma puxava a média da rede para o lado dela.

    E só sobre as escolas COMPARADAS (``tem_dado_de_quem_concorre``): a escola em
    que só a Educação Infantil usa a plataforma tem ``media_geral`` 0,0 por
    AUSÊNCIA. Quando o Panorama Global tinha a fórmula própria, sobre TODOS os
    cartões, a mesma rede aparecia com 60 para a Secretaria e 20 para o Admin
    Global."""
    return _ponderada([c for c in cartoes if tem_dado_de_quem_concorre(c)], "media_geral",
                      PESO_DA_MEDIA_GERAL)


# ---------------------------------------------------------------------------
# GRUPO PEQUENO — o que a SECRETARIA não vê no cartão de uma escola (LGPD)
# ---------------------------------------------------------------------------
# A mesma regra das turmas (``services/grupo_pequeno.py``), no nível da escola:
# com 1 aluno com dado numa matéria, o cartão da escola entregava à Secretaria
# os livros, o tempo e a nota DAQUELA criança. Só a resposta da Secretaria muda;
# o Admin Global e o Panorama Global recebem os cartões de sempre.

# Campos do cartão (``_kpis_da_rede``) com o desempenho e os totais de cada
# matéria: a média, os totais brutos, os totais e o per capita de quem concorre
# e o índice. Saem juntos (motivo ``grupo_pequeno``).
CAMPOS_DA_MATERIA_NO_CARTAO = {
    "leitura": ("media_elefante", "livros", "tempo_leitura_min", "livros_por_aluno",
                "livros_premiaveis", "tempo_premiaveis_min", "livros_por_matricula",
                "tempo_por_matricula_min", "pontuacao_leitura"),
    "matematica": ("media_matific", "atividades", "estrelas", "atividades_premiaveis",
                   "estrelas_premiaveis", "atividades_por_matricula",
                   "estrelas_por_matricula", "pontuacao_matematica"),
}
# Só os totais de TODOS os matriculados (motivo ``complementar``: as turmas que
# não concorrem têm de 1 a k − 1 crianças com dado, e "todos − quem concorre"
# entregaria a soma delas).
TOTAIS_DE_TODOS_NO_CARTAO = {
    "leitura": ("livros", "tempo_leitura_min", "livros_por_aluno"),
    "matematica": ("atividades", "estrelas"),
}
# As três populações de ``grupo_pequeno.decidir_escola``, nas contagens do cartão
# (que continuam visíveis: são quantas crianças têm dado, não o desempenho delas).
# Os CONTRIBUINTES (quem soma em cada total e quem tem nota > 0) vêm na chave
# interna ``_contribuintes`` (``_kpis_da_rede(com_contribuintes=True)``).
CONTAGENS_NO_CARTAO = {
    "leitura": {"media": "alunos_com_nota_elefante", "indicadores": "ativos_elefante",
                "concorrem": "ativos_elefante_premiaveis"},
    "matematica": {"media": "alunos_com_nota_matific", "indicadores": "ativos_matific",
                   "concorrem": "ativos_matific_premiaveis"},
}
_MEDIA_NO_CARTAO = (("media_elefante", "alunos_com_nota_elefante"),
                    ("media_matific", "alunos_com_nota_matific"))
# Quantas crianças SOMAM no per capita (a régua k da vitrine pública). Saem do
# cartão da Secretaria: com a matéria escondida, "1" ao lado do total nulo diz
# que só uma criança leu; com ela visível, a cada coleta a diferença no número
# de quem soma e no total aponta quanto leu quem acabou de começar. A tela não
# os usa; a decisão já os tem em ``_contribuintes``.
_CONTRIBUINTES_NO_CARTAO = ("com_livros_premiaveis", "com_estrelas_premiaveis")


def _proteger_cartoes(cartoes: list[dict]) -> list[dict]:
    """Aplica, IN PLACE, a regra do grupo pequeno aos cartões da rede para a
    resposta da SECRETARIA e devolve a lista das escolas com alguma matéria
    escondida (``{escola_id, nome, grupo_pequeno, oculto}``).

    Por cartão: as contagens decidem (``grupo_pequeno.decidir_escola``: as três
    populações do cartão e os contribuintes da chave interna ``_contribuintes``,
    quando o cartão a traz); a matéria escondida sai com os campos nulos e o
    cartão ganha ``grupo_pequeno`` e ``oculto`` ({matéria: {motivo, texto,
    parcial} | None}). ``_contribuintes`` e as contagens de quem soma
    (``_CONTRIBUINTES_NO_CARTAO``) saem de todo cartão. A matéria
    escondida inteira também sai da COORTE do índice (nem pontua nem é régua,
    ver ``_pontuar_por_percapita``); a ``media_geral`` e a ``pontuacao_geral``
    da escola passam a ser só das matérias visíveis (nulas se nenhuma sobra) —
    nunca calculadas com o número escondido. O motivo de atenção é refeito com o
    índice que a Secretaria vê.

    Os totais e as médias ponderadas da rede, montados depois sobre estes
    cartões, deixam a matéria escondida de fora (valor nulo = ausência em
    ``_ponderada``): somá-la no total e escondê-la só no cartão devolveria a
    criança por subtração."""
    motivos = {}
    for c in cartoes:
        contribuintes = c.pop("_contribuintes", None) or {}
        for chave in _CONTRIBUINTES_NO_CARTAO:
            c.pop(chave, None)
        motivos[c["escola_id"]] = grupo_pequeno.decidir_escola(
            {d: {**{populacao: c[campo] for populacao, campo in campos.items()},
                 **(contribuintes.get(d) or {})}
             for d, campos in CONTAGENS_NO_CARTAO.items()})
    inteiras = {eid: [d for d, m in ms.items() if m == grupo_pequeno.MOTIVO_GRUPO_PEQUENO]
                for eid, ms in motivos.items()}
    if any(inteiras.values()):
        for c in cartoes:
            if inteiras[c["escola_id"]]:
                c["_fora_do_indice"] = inteiras[c["escola_id"]]
        _pontuar_por_percapita(cartoes)
        for c in cartoes:
            c.pop("_fora_do_indice", None)
    ocultas = []
    for c in cartoes:
        ms = motivos[c["escola_id"]]
        for dimensao, motivo in ms.items():
            if motivo is None:
                continue
            campos = (CAMPOS_DA_MATERIA_NO_CARTAO[dimensao]
                      if motivo == grupo_pequeno.MOTIVO_GRUPO_PEQUENO
                      else TOTAIS_DE_TODOS_NO_CARTAO[dimensao])
            for campo in campos:
                c[campo] = None
        if inteiras[c["escola_id"]]:
            visiveis = [c[media] for media, n in _MEDIA_NO_CARTAO
                        if c[media] is not None and c[n]]
            c["media_geral"] = (round(sum(visiveis) / len(visiveis), 1)
                                if visiveis else None)
            if not c["dimensoes_pontuadas"]:
                c["pontuacao_geral"] = None
        motivo = _motivo_atencao(c["total_alunos"], c["alunos_com_dados"],
                                 c["adocao"], c["pontuacao_geral"] or 0.0)
        c["precisa_atencao"] = motivo is not None
        c["motivo_atencao"] = motivo
        c["grupo_pequeno"] = grupo_pequeno.MOTIVO_GRUPO_PEQUENO in ms.values()
        c["oculto"] = {d: grupo_pequeno.bloco_oculto_escola(ms.get(d))
                       for d in grupo_pequeno.DIMENSOES}
        if any(ms.values()):
            ocultas.append({"escola_id": c["escola_id"], "nome": c["nome"],
                            "grupo_pequeno": c["grupo_pequeno"], "oculto": c["oculto"]})
    return ocultas


def cartoes_da_rede(db: Session, rede_id: int, *, secretaria: bool = False) -> list[dict]:
    """Os cartões das escolas como o perfil pode vê-los: para a Secretaria, com
    os grupos pequenos escondidos (``_proteger_cartoes``); para os demais,
    exatamente ``_kpis_da_rede``."""
    cartoes = _kpis_da_rede(db, rede_id, com_contribuintes=secretaria)
    if secretaria:
        _proteger_cartoes(cartoes)
    return cartoes


def _soma(cartoes: list[dict], chave: str) -> int:
    """Soma de um total dos cartões; o nulo (matéria escondida da Secretaria)
    fica fora, como ausência."""
    return sum(c[chave] for c in cartoes if c[chave] is not None)


def dashboard_rede(db: Session, rede_id: int, *, secretaria: bool = False) -> dict:
    """Painel municipal: totais da rede + cartão de cada escola (para cards e o
    mapa), ordenado pelo índice e numerado (``posicao``) SÓ entre as escolas
    comparadas. Inclui um resumo de EQUIDADE (dispersão entre escolas) e a lista
    de escolas em ATENÇÃO.

    Cada cartão traz ``comparada`` (= ``tem_dado_de_quem_concorre``): é a marca
    que TODO consumidor que compara escolas usa (o Boletim, o Top 5 e o
    Comparativo do painel), a mesma régua do Ranking da Rede, da equidade e do
    índice. A escola não comparada continua na lista — a cobertura (alunos, com
    dados, adoção) é dela também —, mas vai para o fim e sem ``posicao``.

    ``secretaria``: os cartões passam por ``_proteger_cartoes`` (grupo pequeno)
    e os totais da rede deixam de fora as matérias escondidas. A resposta ganha
    ``ocultas`` (as escolas com alguma matéria escondida) e
    ``totais.grupo_pequeno`` ({matéria: nº de escolas fora, texto}); o total de
    uma matéria em que TODA escola com dado está escondida sai nulo. A escola
    sem nenhuma matéria pontuada visível fica ``comparada = False``, sem
    posição. Sem ``secretaria``, a resposta de sempre, chave por chave."""
    contratados = modulos.modulos_da_rede(db, rede_id)
    cartoes, pendentes = _cartoes_da_rede(db, rede_id, com_contribuintes=secretaria,
                                          contratados=contratados, com_pendentes=True)
    ocultas = _proteger_cartoes(cartoes) if secretaria else None

    total_alunos = sum(c["total_alunos"] for c in cartoes)
    total_turmas = sum(c["total_turmas"] for c in cartoes)
    total_professores = sum(c["total_professores"] for c in cartoes)
    com_dados = sum(c["alunos_com_dados"] for c in cartoes)

    # A MARCA de comparação vai no cartão: antes cada consumidor decidia sozinho
    # quem comparar (`alunos_com_dados > 0`, que conta as Fases) e o mesmo PDF
    # dizia "pior escola 1000 · diferença 0" acima de uma linha "2º · índice 0".
    for cartao in cartoes:
        cartao["comparada"] = tem_dado_de_quem_concorre(cartao)

    # A média geral e o índice só ponderam as escolas COMPARADAS: o 0 de quem
    # não tem ninguém do 1º–5º ano com dado é ausência, e com o peso dos alunos
    # da Fase ele baixava o índice da rede usado nas metas. E cada um pesa pelo
    # SEU denominador (ver `_ponderada`), nunca pela cobertura, que conta as
    # crianças das Fases: a média geral, por quem concorre com dado; o índice,
    # por quem concorre (`PESO_DO_INDICE`).
    comparadas = [c for c in cartoes if c["comparada"]]
    media_rede = _media_geral_das_comparadas(cartoes)
    indice_rede = _ponderada(comparadas, "pontuacao_geral", PESO_DO_INDICE)
    # (A `media_geral` nula é a da escola com a matéria escondida da Secretaria
    # e nenhuma outra média visível: fica fora da dispersão, como ausência.)
    medias = [c["media_geral"] for c in comparadas if c["media_geral"] is not None]
    indices = [c["pontuacao_geral"] for c in comparadas]
    equidade = {
        # EQUIDADE é comparação ENTRE escolas, então a distância tem de ser
        # medida na régua COMPARÁVEL (índice per capita 0–1000). É o que a tela e
        # o boletim mostram. Medida em `media_geral` (normalizada dentro de cada
        # escola), ela apontava para o lado errado: a rede parecia mais desigual
        # quanto mais escolas tivessem dispersão interna, e não quanto maior
        # fosse a diferença real de leitura entre elas.
        "gap_indice": round(max(indices) - min(indices), 1) if len(indices) >= 2 else 0.0,
        "escola_maior_indice": round(max(indices), 1) if indices else 0.0,
        "escola_menor_indice": round(min(indices), 1) if indices else 0.0,
        "escolas_abaixo_do_indice_medio": sum(1 for i in indices if i < indice_rede),
        # Mantidas para não quebrar consumidores antigos e porque a dispersão das
        # médias internas ainda informa algo (o quanto as escolas variam por
        # dentro) — mas NÃO são comparáveis entre escolas. Não governam nada.
        "gap_media": round(max(medias) - min(medias), 1) if len(medias) >= 2 else 0.0,
        "escola_maior_media": round(max(medias), 1) if medias else 0.0,
        "escola_menor_media": round(min(medias), 1) if medias else 0.0,
        "escolas_abaixo_da_media": sum(1 for m in medias if m < media_rede),
    }

    # ORDEM e POSIÇÃO do painel: o índice per capita, que é o único número
    # comparável entre escolas de tamanhos diferentes. Desempata por adoção e
    # nome (determinístico), a mesma régua de `ranking_escolas` — e a posição só
    # conta as COMPARADAS, como lá. Numerando todas, a escola só com a Fase
    # (índice 0 e adoção alta) passava à frente de uma comparada com índice 0 no
    # empate, e a posição do Boletim deixava de ser a do Ranking da Rede.
    # (Índice nulo só na escola não comparada da Secretaria; ordena como 0.)
    cartoes.sort(key=lambda c: (not c["comparada"], -(c["pontuacao_geral"] or 0.0),
                                -c["adocao"], c["nome"].casefold()))
    posicao = 0
    for cartao in cartoes:
        if cartao["comparada"]:
            posicao += 1
            cartao["posicao"] = posicao
        else:
            # Fora da comparação: sem posição (não é "último lugar").
            cartao["posicao"] = None

    # Totais brutos das plataformas na rede + alunos ativos (soma dos cartões).
    # O total nulo de um cartão (matéria escondida da Secretaria) fica fora, e o
    # "livros por aluno" divide só pelos ativos das escolas que somaram livros.
    total_livros = _soma(cartoes, "livros")
    total_atividades = _soma(cartoes, "atividades")
    ativos_elefante = sum(c["ativos_elefante"] for c in cartoes)
    ativos_com_livros = sum(c["ativos_elefante"] for c in cartoes if c["livros"] is not None)
    # A melhor escola COMPARADA (o pódio do ranking geral) — atalho para o KPI.
    melhor = next((c for c in cartoes if c["comparada"]), None)

    resposta = {
        "rede_id": rede_id,
        # Módulos contratados — a interface inteira (cards, abas, rankings,
        # explicador) se adapta a partir daqui.
        "modulos": sorted(contratados),
        "totais": {
            "escolas": len(cartoes),
            "escolas_ativas": sum(1 for c in cartoes if c["status"] == "ativa"),
            "alunos": total_alunos,
            "turmas": total_turmas,
            "professores": total_professores,
            "alunos_com_dados": com_dados,
            "adocao": round(com_dados / total_alunos * 100, 1) if total_alunos else 0.0,
            # DESEMPENHO (0–100): média das notas de quem TEM dado da plataforma.
            # Continua sendo o retrato honesto de desempenho da rede — só não
            # serve para COMPARAR escolas entre si (é o que o índice faz).
            "media_geral": media_rede,
            # Peso = alunos aferidos NAQUELA dimensão (ver `_ponderada`).
            "media_matific": _ponderada(cartoes, "media_matific", "alunos_com_nota_matific"),
            "media_elefante": _ponderada(cartoes, "media_elefante", "alunos_com_nota_elefante"),
            # ÍNDICE (0–1000) da rede: média ponderada do índice das escolas — a
            # métrica comparável, usada nas metas e no boletim.
            "pontuacao_geral": indice_rede,
            "escolas_em_atencao": sum(1 for c in cartoes if c["precisa_atencao"]),
            # Totais das plataformas na rede inteira (seções Elefante/Matific).
            "livros": total_livros,
            "tempo_leitura_min": _soma(cartoes, "tempo_leitura_min"),
            "atividades": total_atividades,
            "estrelas": _soma(cartoes, "estrelas"),
            "ativos_matific": sum(c["ativos_matific"] for c in cartoes),
            "ativos_elefante": ativos_elefante,
            "livros_por_aluno": (round(total_livros / ativos_com_livros, 1)
                                 if ativos_com_livros else 0.0),
            # "Melhor escola" é uma COMPARAÇÃO: quem lidera é quem tem o maior
            # índice per capita (a lista já vem ordenada por ele). A média
            # interna vai junto, como leitura complementar.
            "melhor_escola": {"nome": melhor["nome"],
                              "pontuacao_geral": melhor["pontuacao_geral"],
                              "media_geral": melhor["media_geral"]}
            if melhor else None,
        },
        "equidade": equidade,
        "escolas": cartoes,
        # Atalho: só as escolas que precisam de atenção (a lista de ação da rede).
        "atencao": [c for c in cartoes if c["precisa_atencao"]],
        # OPERACIONAL (não é métrica — fica fora dos cartões/totais): notas do
        # ano ativo que ainda não passaram pela régua institucional VIGENTE — sem
        # carimbo (essas ficam FORA das médias, não entram como zero) ou
        # carimbadas com uma versão anterior da régua (essas são agregadas, mas
        # pelo número antigo). total > 0 = rodar
        # `python -m scripts.recalcular_institucional --pendentes`.
        "recalculo_pendente": _recalculo_pendente(pendentes),
    }
    if secretaria:
        _marcar_totais_da_secretaria(resposta["totais"], cartoes)
        # As escolas com alguma matéria escondida (o cartão de cada uma também
        # traz `grupo_pequeno` e `oculto`): é por aqui que o Ranking da Rede, que
        # tira a escola da ordem da matéria escondida, explica quem ficou de fora.
        resposta["ocultas"] = ocultas
    return resposta


# Totais da REDE de cada matéria: (chave em `totais`, campo do cartão que soma
# nela, contagem do cartão que diz se a escola tem dado dessa matéria).
_TOTAIS_DA_MATERIA = {
    "leitura": (("media_elefante", "media_elefante", "alunos_com_nota_elefante"),
                ("livros", "livros", "ativos_elefante"),
                ("tempo_leitura_min", "tempo_leitura_min", "ativos_elefante"),
                ("livros_por_aluno", "livros", "ativos_elefante")),
    "matematica": (("media_matific", "media_matific", "alunos_com_nota_matific"),
                   ("atividades", "atividades", "ativos_matific"),
                   ("estrelas", "estrelas", "ativos_matific")),
}


def _marcar_totais_da_secretaria(totais: dict, cartoes: list[dict]) -> None:
    """Totais da rede na resposta da Secretaria: já somam só o que ela vê
    (``_soma``/``_ponderada`` deixam o nulo de fora). Aqui (1) o total de uma
    matéria em que NENHUMA escola visível tem dado, mas alguma escondida tem,
    sai nulo em vez de um 0 que pareceria medido — e a média geral e o índice
    também, se nenhuma escola sobra comparada; e (2) ``grupo_pequeno`` diz
    quantas escolas ficaram fora de cada matéria."""
    fora = {d: sum(1 for c in cartoes if c["oculto"][d]) for d in grupo_pequeno.DIMENSOES}
    for dimensao, campos in _TOTAIS_DA_MATERIA.items():
        if not fora[dimensao]:
            continue
        for chave, campo, contagem in campos:
            if not any(c[campo] is not None and c[contagem] for c in cartoes):
                totais[chave] = None
    if any(fora.values()) and not any(c["comparada"] for c in cartoes):
        totais["media_geral"] = None
        totais["pontuacao_geral"] = None
    totais["grupo_pequeno"] = {**fora, "texto": grupo_pequeno.TEXTO_FORA_DOS_TOTAIS_DA_REDE}


def _recalculo_pendente(pendentes: dict[int, int]) -> dict:
    return {"total": int(sum(pendentes.values())),
            "por_escola": {str(eid): int(n) for eid, n in sorted(pendentes.items())}}


# Métricas de ordenação do ranking de escolas (SEDUC escolhe o critério). Só
# agregados por escola — nunca ranking individual entre escolas (privacidade).
METRICAS_RANKING = {
    # Critérios por DIMENSÃO = índice per capita, COMPARÁVEL entre escolas. São
    # os que a Secretaria usa para ranquear (antes apontavam para as médias
    # 0–100, normalizadas dentro de cada escola: ordenar por elas premiava
    # homogeneidade interna e rebaixava a escola que mais lê do município).
    "geral": "pontuacao_geral",
    "leitura": "pontuacao_leitura",
    "matematica": "pontuacao_matematica",
    # Critérios por PLATAFORMA = as médias 0–100 do motor. Ficam disponíveis como
    # opção explícita ("como vai quem usa o Elefante nesta escola?"), mas são
    # régua INTERNA de cada escola — não comparam escolas.
    "elefante": "media_elefante",
    "matific": "media_matific",
    "engajamento": "adocao",
    "livros": "livros",
    "estrelas": "estrelas",
    # Critérios PER CAPITA (÷ matrícula) — comparação JUSTA entre escolas de
    # tamanhos diferentes (item 1): não favorecem a escola grande pelo volume bruto.
    # "livros_aluno" é o critério PRINCIPAL do ranking de LEITURA da rede.
    "livros_aluno": "livros_por_matricula",
    "estrelas_aluno": "estrelas_por_matricula",
    "atividades_aluno": "atividades_por_matricula",
    # ÍNDICES da rede (0–1000, régua = melhor escola sobre o indicador per capita).
    # Nomes explícitos das mesmas métricas de "geral"/"leitura"/"matematica",
    # mantidos porque as abas do Ranking da Rede já apontam para eles.
    "indice_geral": "pontuacao_geral",
    "indice_leitura": "pontuacao_leitura",
    "indice_matematica": "pontuacao_matematica",
}

# DIMENSÃO de cada métrica de ranking — e, por consequência, qual COBERTURA
# desempata quando duas escolas empatam nela.
#
# O desempate de um ranking DE DIMENSÃO tem de ser LOCAL a ela. É a mesma regra
# que `scoring.CRITERIOS_DESEMPATE_DIMENSAO` já fixou no nível do ALUNO ("num
# ranking de Leitura, deixar a nota de Matemática desempatar faria a medalha de
# leitura ser decidida pela matemática"), aplicada um nível acima. O desempate
# genérico é `adocao` = % de alunos com dado de ALGUMA plataforma: num empate de
# índice de LEITURA entre duas escolas, quem passava na frente era a que usa
# mais o **Matific** — a matemática decidindo a colocação de leitura na tela que
# a Secretaria usa para premiar. Métrica de dimensão desempata pela adoção
# DAQUELA plataforma; métrica de união (`geral`, `engajamento`) segue com a
# adoção geral, que é o denominador dela.
DIMENSAO_DA_METRICA: dict[str, str] = {
    "leitura": "leitura", "indice_leitura": "leitura", "elefante": "leitura",
    "livros": "leitura", "livros_aluno": "leitura",
    "matematica": "matematica", "indice_matematica": "matematica",
    "matific": "matematica", "estrelas": "matematica",
    "estrelas_aluno": "matematica", "atividades_aluno": "matematica",
}
DESEMPATE_DA_DIMENSAO: dict[str, str] = {"leitura": "adocao_elefante",
                                         "matematica": "adocao_matific"}


def ranking_escolas(db: Session, rede_id: int, limite: int = 50,
                    metrica: str = "geral", *, secretaria: bool = False) -> list[dict]:
    """Ranking MUNICIPAL por escola (não expõe ranking individual de crianças
    entre escolas — decisão de privacidade). A SEDUC escolhe o CRITÉRIO em
    ``metrica`` (ver ``METRICAS_RANKING``); desempata por adoção e nome. Só
    escolas com dados entram.

    As abas do Ranking da Rede usam: ``indice_geral`` (Geral), ``livros_aluno``
    (Leitura — livros ÷ alunos, o critério principal), ``estrelas_aluno``
    (Matemática) e ``engajamento`` (participação). Todas per capita ou índice, de
    modo que a escola GRANDE não sobe só por ter mais alunos.

    O DESEMPATE é local à dimensão da métrica (ver ``DIMENSAO_DA_METRICA``): num
    ranking de Leitura, a cobertura que desempata é a do Elefante, nunca a
    adoção de alguma plataforma qualquer.

    "Com dados" = com dado de quem CONCORRE (``tem_dado_de_quem_concorre``): a
    escola em que só a Educação Infantil usa a plataforma não entra com zero.

    ``secretaria``: os cartões passam por ``_proteger_cartoes`` (grupo pequeno)
    e a escola cujo número desta métrica está escondido SAI da lista — não ganha
    posição nem é vizinha de ninguém na ordem (a vizinhança cercaria o número). A
    lista continua lista (um envelope novo quebraria quem a consome): quem ficou
    de fora está em ``ocultas`` do ``/dashboard``. Na ``geral``, a escola com uma
    matéria escondida concorre pelo índice das matérias visíveis
    (``dimensoes_pontuadas`` diz quais). Em TODA métrica, inclusive a
    ``engajamento`` (cobertura, que não tem número escondido), sai também a
    escola sem nenhuma matéria pontuada visível (``comparada = False`` no
    painel): é a mesma marca de quem a Secretaria compara."""
    chave = METRICAS_RANKING.get(metrica, "pontuacao_geral")
    desempate = DESEMPATE_DA_DIMENSAO.get(DIMENSAO_DA_METRICA.get(metrica), "adocao")
    cartoes = [c for c in cartoes_da_rede(db, rede_id, secretaria=secretaria)
               if tem_dado_de_quem_concorre(c) and c[chave] is not None]
    cartoes.sort(key=lambda c: (-c[chave], -c[desempate], c["nome"].casefold()))
    for posicao, cartao in enumerate(cartoes[:limite], start=1):
        cartao["posicao"] = posicao
    return cartoes[:limite]


# ---------------------------------------------------------------------------
# Visão GLOBAL do Admin Global — consolida TODAS as redes (uma camada acima da
# Secretaria, que vê só a própria rede). Só agregados por escola/rede, sem PII.
# ---------------------------------------------------------------------------

def _por(total: int, alunos: int) -> float:
    return round(total / alunos, 1) if alunos else 0.0


def dashboard_global(db: Session) -> dict:
    """Panorama consolidado de TODAS as redes (Admin Global): totais globais,
    cartão por REDE (para comparar/ranquear redes) e as melhores escolas de toda
    a base com o nome da rede. Reusa ``_kpis_da_rede`` por rede — só agregado."""
    redes = db.execute(select(Rede).order_by(Rede.nome)).scalars().all()
    cartoes_rede: list[dict] = []
    todas_escolas: list[dict] = []
    for rede in redes:
        cartoes = _kpis_da_rede(db, rede.id)
        alunos = sum(c["total_alunos"] for c in cartoes)
        com_dados = sum(c["alunos_com_dados"] for c in cartoes)

        # As médias da rede saem das MESMAS funções de `dashboard_rede` (nenhuma
        # fórmula própria aqui): a de LEITURA pesa pelos alunos aferidos EM
        # LEITURA (sem isso, a escola que não usa o Elefante entra com zero) e a
        # geral só pondera as escolas comparadas — com a fórmula duplicada, a
        # mesma rede saía com uma média no painel dela e outra no Panorama.
        livros = sum(c["livros"] for c in cartoes)
        estrelas = sum(c["estrelas"] for c in cartoes)
        aferidos_ele = sum(c["alunos_com_nota_elefante"] for c in cartoes)
        aferidos_mat = sum(c["alunos_com_nota_matific"] for c in cartoes)
        cartoes_rede.append({
            "rede_id": rede.id, "nome": rede.nome, "uf": rede.uf, "status": rede.status,
            "escolas": len(cartoes),
            "alunos": alunos, "turmas": sum(c["total_turmas"] for c in cartoes),
            "professores": sum(c["total_professores"] for c in cartoes),
            "alunos_com_dados": com_dados,
            "adocao": round(com_dados / alunos * 100, 1) if alunos else 0.0,
            "media_geral": _media_geral_das_comparadas(cartoes),
            "media_matific": _ponderada(cartoes, "media_matific", "alunos_com_nota_matific"),
            "media_elefante": _ponderada(cartoes, "media_elefante", "alunos_com_nota_elefante"),
            # Denominadores POR DIMENSÃO da rede — o peso das médias por
            # dimensão no nível global e o "de quantos alunos" de cada média.
            "alunos_com_nota_elefante": aferidos_ele,
            "alunos_com_nota_matific": aferidos_mat,
            "livros": livros,
            "atividades": sum(c["atividades"] for c in cartoes),
            "estrelas": estrelas,
            "escolas_em_atencao": sum(1 for c in cartoes if c["precisa_atencao"]),
            # Per capita da REDE + ativos/módulos: é o que `_pontuar_por_percapita`
            # consome. Assim a comparação ENTRE REDES usa o mesmo motor e o mesmo
            # conceito das escolas (nenhuma segunda lógica), em vez da média
            # 0–100, que é régua interna de cada escola e não compara nada.
            "ativos_elefante": sum(c["ativos_elefante"] for c in cartoes),
            "ativos_matific": sum(c["ativos_matific"] for c in cartoes),
            "modulos": sorted(modulos.modulos_da_rede(db, rede.id)),
            # Per capita da rede só de quem concorre (a mesma régua das escolas).
            "alunos_premiaveis": sum(c["alunos_premiaveis"] for c in cartoes),
            "ativos_elefante_premiaveis": sum(c["ativos_elefante_premiaveis"] for c in cartoes),
            "ativos_matific_premiaveis": sum(c["ativos_matific_premiaveis"] for c in cartoes),
            "livros_por_matricula": _por(sum(c["livros_premiaveis"] for c in cartoes),
                                         sum(c["alunos_premiaveis"] for c in cartoes)),
            "estrelas_por_matricula": _por(sum(c["estrelas_premiaveis"] for c in cartoes),
                                           sum(c["alunos_premiaveis"] for c in cartoes)),
        })
        for c in cartoes:
            todas_escolas.append({**c, "rede_id": rede.id, "rede_nome": rede.nome})

    total_com_dados = sum(r["alunos_com_dados"] for r in cartoes_rede)

    # Comparação ENTRE REDES: índice per capita na coorte "todas as redes".
    _pontuar_por_percapita(cartoes_rede)
    cartoes_rede.sort(key=lambda r: (-r["pontuacao_geral"], r["nome"].casefold()))
    for posicao, cartao in enumerate(cartoes_rede, start=1):
        cartao["posicao"] = posicao
    # Melhores escolas de TODAS as redes: o índice DE REDE de cada uma não serve
    # aqui (cada escola foi normalizada contra a melhor da SUA rede, então um
    # 1000 de um município de 3 escolas empataria com o 1000 de uma capital).
    # Pontua-se de novo, com a coorte global, em chaves próprias.
    # Mesma régua de entrada do ranking da rede: o cartão já traz a coorte
    # (`dimensoes_pontuadas`), que só depende dele mesmo, não do escopo.
    top = [e for e in todas_escolas if tem_dado_de_quem_concorre(e)]
    _pontuar_por_percapita(top, sufixo="_global")
    top.sort(key=lambda e: (-e["pontuacao_geral_global"], e["nome"].casefold()))

    return {
        "totais": {
            "redes": len(cartoes_rede),
            "escolas": sum(r["escolas"] for r in cartoes_rede),
            "alunos": sum(r["alunos"] for r in cartoes_rede),
            "turmas": sum(r["turmas"] for r in cartoes_rede),
            "professores": sum(r["professores"] for r in cartoes_rede),
            "livros": sum(r["livros"] for r in cartoes_rede),
            "atividades": sum(r["atividades"] for r in cartoes_rede),
            "estrelas": sum(r["estrelas"] for r in cartoes_rede),
            "alunos_com_dados": total_com_dados,
            # A média geral GLOBAL sai das ESCOLAS (a mesma função da rede), não
            # do cartão de cada rede: o peso do cartão (`alunos_com_dados`) conta
            # também as escolas não comparadas, e repesar a média da rede por ele
            # devolveria às Fases, entre redes, o peso que a média tirou delas.
            "media_geral": _media_geral_das_comparadas(todas_escolas),
            "media_matific": _ponderada(cartoes_rede, "media_matific", "alunos_com_nota_matific"),
            "media_elefante": _ponderada(cartoes_rede, "media_elefante",
                                         "alunos_com_nota_elefante"),
            # O índice entre redes pesa cada rede por quem concorre nela (o
            # denominador do per capita da rede) e só olha as redes PONTUADAS: a
            # rede em que só as Fases têm dado tem índice 0 por ausência, como a
            # escola não comparada no painel da rede.
            "pontuacao_geral": _ponderada(
                [r for r in cartoes_rede if tem_dado_de_quem_concorre(r)],
                "pontuacao_geral", PESO_DO_INDICE),
            "escolas_em_atencao": sum(r["escolas_em_atencao"] for r in cartoes_rede),
        },
        "redes": cartoes_rede,
        "top_escolas": top[:10],
    }


# ---------------------------------------------------------------------------
# METAS da rede (§9) — a Secretaria CADASTRA o alvo de um indicador; o progresso
# é sempre calculado sobre os totais REAIS (nunca número fictício).
# ---------------------------------------------------------------------------

# Indicadores que aceitam meta. ``por_escola`` = o indicador existe no cartão de
# cada escola (totais municipais não: uma escola não bate um total da rede).
# ``comparavel`` = o valor de uma escola pode ser confrontado com o de outra pelo
# MESMO alvo. As médias 0–100 são normalizadas dentro de cada escola, então
# "3 de 5 escolas atingiram média 70" mede homogeneidade interna, não conquista —
# por isso elas continuam valendo como meta DA REDE (o progresso agregado é
# legítimo) mas não produzem mais contagem por escola.
METRICAS_META: dict[str, dict] = {
    "pontuacao_geral": {"rotulo": "Índice da rede (0–1000)", "sufixo": "",
                        "por_escola": True, "comparavel": True},
    "adocao": {"rotulo": "Engajamento (adoção)", "sufixo": "%",
               "por_escola": True, "comparavel": True},
    "media_geral": {"rotulo": "Média geral da rede", "sufixo": "",
                    "por_escola": True, "comparavel": False},
    "media_elefante": {"rotulo": "Leitura (Elefante Letrado)", "sufixo": "",
                       "por_escola": True, "comparavel": False},
    "media_matific": {"rotulo": "Matemática (Matific)", "sufixo": "",
                      "por_escola": True, "comparavel": False},
    "livros": {"rotulo": "Livros lidos na rede", "sufixo": "",
               "por_escola": False, "comparavel": False},
    "atividades": {"rotulo": "Atividades Matific na rede", "sufixo": "",
                   "por_escola": False, "comparavel": False},
}


def listar_metas(db: Session, rede_id: int) -> list[dict]:
    metas = db.execute(
        select(MetaRede).where(MetaRede.rede_id == rede_id).order_by(MetaRede.metrica)
    ).scalars().all()
    return [{"id": m.id, "metrica": m.metrica, "alvo": m.alvo, "descricao": m.descricao}
            for m in metas]


def definir_meta(db: Session, rede_id: int, metrica: str, alvo: float,
                 descricao: str | None = None) -> MetaRede:
    """Upsert: UMA meta por (rede, métrica) — redefinir sobrescreve o alvo."""
    if metrica not in METRICAS_META:
        raise ValueError("Métrica de meta inválida.")
    meta = db.execute(select(MetaRede).where(
        MetaRede.rede_id == rede_id, MetaRede.metrica == metrica)).scalars().first()
    if meta is None:
        meta = MetaRede(rede_id=rede_id, metrica=metrica, alvo=alvo, descricao=descricao)
        db.add(meta)
    else:
        meta.alvo = alvo
        meta.descricao = descricao
    return meta


def remover_meta(db: Session, rede_id: int, metrica: str) -> None:
    db.execute(delete(MetaRede).where(
        MetaRede.rede_id == rede_id, MetaRede.metrica == metrica))


# Peso (= denominador) de cada meta que é MÉDIA DE DESEMPENHO. É o mesmo peso
# com que `_ponderada` calcula o total da rede: se ele é zero, o "atual" não é
# um desempenho zero — é a ausência de medição.
_PESO_DA_META = {
    "media_elefante": "alunos_com_nota_elefante",
    "media_matific": "alunos_com_nota_matific",
    "media_geral": PESO_DA_MEDIA_GERAL,
}


def _meta_medida(metrica: str, cartoes: list[dict]) -> bool:
    """A métrica tem população aferida na rede hoje? Contagens, adoção e índice
    per capita não passam por aqui: neles o zero é um fato sobre as matrículas.

    A BASE é a mesma da conta: a média geral só pondera as escolas comparadas
    (``_media_geral_das_comparadas``). Somando o peso de TODAS, a rede em que só
    as Fases têm dado tinha média 0,0 por falta de peso e, mesmo assim, a meta
    saía "medida" — o "0,0 / 70" que este campo existe para não publicar."""
    peso = _PESO_DA_META.get(metrica)
    if peso is None:
        return True
    base = ([c for c in cartoes if tem_dado_de_quem_concorre(c)]
            if metrica == "media_geral" else cartoes)
    # A média nula (matéria escondida da Secretaria) não entra na conta da rede
    # (`_ponderada`), então o peso dela também não mede nada aqui.
    return sum(c.get(peso, 0) for c in base if c.get(metrica, 0) is not None) > 0


def metas_com_progresso(db: Session, rede_id: int, dados: dict | None = None) -> list[dict]:
    """Metas cadastradas + progresso REAL: valor ATUAL da rede / alvo (limitado a
    100%) + quantas escolas COM dados já atingiram (só para métricas comparáveis
    por escola). Sem meta cadastrada → lista vazia (a UI mostra o convite)."""
    metas = db.execute(
        select(MetaRede).where(MetaRede.rede_id == rede_id).order_by(MetaRede.metrica)
    ).scalars().all()
    if not metas:
        return []
    if dados is None:
        dados = dashboard_rede(db, rede_id)
    totais = dados["totais"]
    # "X de Y escolas atingiram" conta as MESMAS escolas que o ranking, a equidade
    # e o índice comparam (a marca ``comparada``): a escola em que só a Educação
    # Infantil usa a plataforma não entra no Y (``alunos_com_dados`` a contava).
    com_dados = [c for c in dados["escolas"]
                 if c.get("comparada", tem_dado_de_quem_concorre(c))]
    saida = []
    for m in metas:
        cfg = METRICAS_META.get(m.metrica)
        if cfg is None:
            continue
        atual = float(totais.get(m.metrica, 0) or 0)
        progresso = round(min(100.0, atual / m.alvo * 100), 1) if m.alvo else 0.0
        item = {
            "id": m.id, "metrica": m.metrica, "rotulo": cfg["rotulo"],
            "sufixo": cfg["sufixo"], "alvo": round(m.alvo, 1), "atual": round(atual, 1),
            "progresso": progresso, "atingida": atual >= m.alvo, "descricao": m.descricao,
            "comparavel": cfg["comparavel"],
            # O indicador FOI MEDIDO? As médias 0–100 são DESEMPENHO: sem
            # ninguém aferido, `_ponderada` devolve 0.0 por falta de peso (não
            # porque a rede tirou zero), e a linha da meta exibia "0,0 / 70,0"
            # ao lado de um cartão que, no mesmo painel, já mostra "—" para o
            # mesmo número. Ausência não é zero também aqui — e o campo é
            # ADITIVO: quem não o lê continua vendo exatamente o que via.
            # As demais métricas (índice, adoção, contagens) têm zero legítimo:
            # "nenhuma escola usa" é um fato medido sobre as matrículas.
            # (O total nulo é o da matéria toda escondida da Secretaria.)
            "medida": (totais.get(m.metrica, 0) is not None
                       and _meta_medida(m.metrica, dados["escolas"])),
            "escolas_atingiram": None, "escolas_total": None,
        }
        # A contagem "X de Y escolas atingiram" só existe para métrica
        # COMPARÁVEL: com a média 0–100 (régua interna de cada escola) ela era um
        # número inválido publicado ao lado de um número válido.
        if cfg["por_escola"] and cfg["comparavel"] and com_dados:
            # O valor nulo (Secretaria, grupo pequeno) não conta nem no Y.
            medidas = [c for c in com_dados if c.get(m.metrica, 0) is not None]
            item["escolas_atingiram"] = sum(1 for c in medidas if c.get(m.metrica, 0) >= m.alvo)
            item["escolas_total"] = len(medidas)
        saida.append(item)
    return saida


# ---------------------------------------------------------------------------
# Painel PÚBLICO da Secretaria (vitrine SEM login): as MELHORES ESCOLAS da rede
# em leitura e matemática — decisão de produto do dono. NUNCA nome de criança
# nem ranking individual; só escolas + a métrica. Habilitado por um token na
# rede (nulo = desligado); trocar/limpar o token invalida o link imediatamente.
# ---------------------------------------------------------------------------

def _top_escolas(cartoes: list[dict], chave: str, contribuintes: str,
                 limite: int = 5, *, com_id: bool = False) -> list[dict]:
    """Top-N escolas por uma métrica (>0), sem PII — só nome + valor.

    ``com_id`` (só a tela interna da rede pede, ``destaques_rede``) acrescenta o
    ``escola_id`` de cada escola, para a tela levar à ficha dela. Sem ele, a
    saída de sempre (a da vitrine sem login): a lista e a ordem são as mesmas.

    Per capita de menos de ``K_MINIMO`` crianças que concorrem é, no limite, o número
    de UMA criança (1 aluno: o valor é o total dela): não vai para a vitrine sem login.
    É a régua de célula pequena da Análise Educacional (docs/analise/METODOLOGIA.md
    3.5). Só esconde a escola da vitrine; o cálculo não muda.

    O k vale também, POR MATÉRIA, para ``contribuintes`` — o campo do cartão com
    quantas crianças que concorrem têm a métrica > 0 (somam no numerador). Com 5 que
    concorrem e só 1 com dado, o per capita × 5 é o total dessa criança, num endereço
    sem login. Aqui a vitrine é mais estrita que a Análise autenticada, que para
    leitura exige só k medidos (METODOLOGIA §5, "Média por aluno com poucos ativos")."""
    validos = [c for c in cartoes if c["alunos_com_dados"] > 0 and c.get(chave, 0) > 0
               and c.get("alunos_premiaveis", 0) >= K_MINIMO
               and c.get(contribuintes, 0) >= K_MINIMO]
    validos.sort(key=lambda c: (-c[chave], c["nome"].casefold()))
    return [{**({"escola_id": c["escola_id"]} if com_id else {}),
             "nome": c["nome"], "valor": round(float(c[chave]), 1)}
            for c in validos[:limite]]


def painel_publico_rede(db: Session, rede_id: int) -> dict:
    """Dados da vitrine pública: top 5 escolas em LEITURA e em MATEMÁTICA. Só
    agregado por escola — sem PII de criança.

    O critério é PER CAPITA (livros ÷ alunos, estrelas ÷ alunos), o mesmo do
    Ranking da Rede. Ordenar pelas médias 0–100 do motor coroaria em praça
    pública a escola de distribuição mais homogênea — que pode ser justamente a
    que menos lê —, porque aquela régua é o P90 de cada escola contra ela mesma.
    A unidade vai junto para o telão dizer o que o número significa.

    CONTRATO (trava de módulo): a matéria de módulo que a rede NÃO contratou
    não é publicada — a lista sai vazia, como o telão da escola já faz com as
    estatísticas da plataforma fora do plano. Só esconde: nenhum cálculo muda.
    ``modulos`` (aditivo, só chaves do catálogo, nenhum dado pessoal) diz à
    tela o que a rede contratou: o cartão da matéria fora do plano NÃO aparece
    (``services/modulos.py``: o que não foi contratado não existe nem na
    interface), e "Sem dados ainda." fica para a matéria contratada sem dado.
    Cliente antigo, que não lê o campo, continua mostrando os dois cartões.

    Só escola ATIVA (docs/operacao/STATUS-ESCOLA-REDE.md): a escola inativa
    (fim de contrato, escola fechada) não entra na vitrine sem login, assim
    como o telão dela já dá 404 (`publico._escola_pelo_token`). O painel
    interno da rede continua mostrando a escola inativa, com o status."""
    rede = db.get(Rede, rede_id)
    contratados = modulos.modulos_da_rede(db, rede_id)
    cartoes = [c for c in _kpis_da_rede(db, rede_id, contratados=contratados)
               if c["status"] == "ativa"]
    return {
        "rede_nome": rede.nome if rede else "",
        "top_leitura": (_top_escolas(cartoes, "livros_por_matricula",
                                     "com_livros_premiaveis")
                        if "leitura" in contratados else []),
        "top_matematica": (_top_escolas(cartoes, "estrelas_por_matricula",
                                        "com_estrelas_premiaveis")
                           if "matematica" in contratados else []),
        "unidade_leitura": "livros por aluno",
        "unidade_matematica": "estrelas por aluno",
        "modulos": sorted(contratados),
    }


# DESTAQUES da rede na tela INTERNA (Panorama da Rede): as MESMAS escolas da
# vitrine pública, pelo MESMO critério e pela MESMA função (``_top_escolas``),
# com o ``escola_id`` de cada uma para a tela levar à ficha da escola.
LIMITE_DESTAQUES = 5
# Matéria → (métrica per capita, quem soma nela): as duas listas da vitrine.
_DESTAQUES_DA_MATERIA = {
    "leitura": ("livros_por_matricula", "com_livros_premiaveis"),
    "matematica": ("estrelas_por_matricula", "com_estrelas_premiaveis"),
}


def destaques_rede(db: Session, rede_id: int, *, secretaria: bool = False) -> dict:
    """As escolas em destaque da rede, por matéria contratada: as da vitrine
    pública (``painel_publico_rede``), na mesma ordem, com o ``escola_id``.

    Critério (o da vitrine, sem mudar nada): só escola ATIVA, só matéria
    contratada, pelo menos ``K_MINIMO`` crianças que concorrem (1º ao 5º ano) e
    ``K_MINIMO`` que somam no per capita, valor > 0; ordem pelo valor (livros
    por aluno; estrelas por aluno) e pelo nome; as ``LIMITE_DESTAQUES``
    primeiras. A lista sai dos cartões SEM proteção, como a da vitrine — com os
    cartões da Secretaria ela mudaria (a contagem de quem soma não está neles).

    ``secretaria``: a escola cuja matéria está escondida no cartão dela (grupo
    pequeno, ``_proteger_cartoes``: o per capita sai nulo) SAI da lista daquela
    matéria — o destaque não devolve o número que o ``/dashboard`` dela
    esconde —, e ``fora_por_protecao`` diz quantas saíram. A lista não é
    completada com a 6ª escola: continua sendo a da vitrine, sem quem saiu. O
    Admin Global recebe a lista inteira (``fora_por_protecao`` = 0).

    Matéria não contratada → ``None``. Só agregado por escola: nenhum dado de
    criança."""
    contratados = modulos.modulos_da_rede(db, rede_id)
    cartoes = _kpis_da_rede(db, rede_id, com_contribuintes=secretaria, contratados=contratados)
    ativas = [c for c in cartoes if c["status"] == "ativa"]
    listas = {materia: _top_escolas(ativas, chave, contribuintes, LIMITE_DESTAQUES,
                                    com_id=True)
              for materia, (chave, contribuintes) in _DESTAQUES_DA_MATERIA.items()
              if materia in contratados}
    # A proteção vem DEPOIS das listas (muda os cartões no lugar) e sobre TODOS
    # os cartões, como no ``/dashboard`` da Secretaria: a decisão é a mesma.
    escondidas: dict[str, set[int]] = {materia: set() for materia in listas}
    if secretaria:
        _proteger_cartoes(cartoes)
        escondidas = {materia: {c["escola_id"] for c in cartoes
                                if c[_DESTAQUES_DA_MATERIA[materia][0]] is None}
                      for materia in listas}
    resposta = {"modulos": sorted(contratados), "limite": LIMITE_DESTAQUES,
                "k_minimo": K_MINIMO}
    for materia in _DESTAQUES_DA_MATERIA:
        if materia not in listas:
            resposta[materia] = None
            continue
        escolas = [e for e in listas[materia] if e["escola_id"] not in escondidas[materia]]
        resposta[materia] = {"escolas": escolas,
                             "fora_por_protecao": len(listas[materia]) - len(escolas)}
    return resposta


def rede_pelo_token_publico(db: Session, token: str) -> Rede | None:
    """Resolve o token público para a rede (comparação em tempo constante contra
    força bruta de token). Só redes ATIVAS com painel habilitado."""
    # Todo token real é token_urlsafe (ASCII). Rejeita não-ASCII ANTES de comparar:
    # secrets.compare_digest levanta TypeError com não-ASCII — e o endpoint é sem
    # login, então isso viraria um 500 disparável por qualquer anônimo (deve ser 404).
    if not token or not token.isascii():
        return None
    candidatas = db.execute(
        select(Rede).where(Rede.token_publico.isnot(None), Rede.status == "ativa")
    ).scalars().all()
    for rede in candidatas:
        if secrets.compare_digest(str(rede.token_publico), token):
            return rede
    return None


def definir_painel_publico(db: Session, rede_id: int, ativo: bool) -> str | None:
    """Liga (gera token novo) ou desliga (limpa o token) a vitrine pública da
    rede. Devolve o token atual (ou None se desligado)."""
    rede = db.get(Rede, rede_id)
    if rede is None:
        return None
    rede.token_publico = secrets.token_urlsafe(9) if ativo else None
    return rede.token_publico
