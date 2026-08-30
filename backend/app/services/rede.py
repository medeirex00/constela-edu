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

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import (
    Aluno,
    Escola,
    Matricula,
    MetaRede,
    Nota,
    Professor,
    Rede,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
)
from app.services import modulos, scoring

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
        return (f"Desempenho baixo frente à rede: índice {pontuacao_geral:.0f} "
                f"de 1000 (1000 = melhor escola da rede).")
    return None


def _totais_plataforma_por_escola(db: Session, ids: list[int], modelo,
                                  campos: list[str]) -> dict[int, dict]:
    """Soma, por escola, os campos do snapshot ATUAL de cada aluno (o último por
    data_referencia,id — mesma régua do scoring) e conta os alunos ATIVOS na
    plataforma. UMA window query para a rede inteira (não N por escola). Só
    números BRUTOS agregados: nenhum dado individual de criança.

    RESTRINGE ao MESMO conjunto das contagens de ``_kpis_da_rede`` (aluno ativo
    E matriculado no ano letivo ATIVO da escola). Sem isso, o snapshot 'preso' de
    um aluno transferido/arquivado (que persiste — o scoring já o filtra de
    propósito) inflava os totais e o ``ativos_*`` frente ao total de alunos,
    chegando a ``ativos_elefante > total_alunos`` no painel da rede/global. O
    JOIN em Matrícula pode multiplicar a linha do snapshot (aluno em >1 turma),
    mas a janela por (escola_id, aluno_id) + ``pos == 1`` deduplica: um aluno
    conta uma vez, sempre pelo snapshot mais recente."""
    if not ids:
        return {}
    numerado = (
        select(
            modelo.escola_id.label("escola_id"),
            *[getattr(modelo, c).label(c) for c in campos],
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
        .where(modelo.escola_id.in_(ids), Aluno.status == "ativo")
        .subquery()
    )
    colunas = [numerado.c.escola_id, func.count().label("ativos")]
    colunas += [func.coalesce(func.sum(getattr(numerado.c, c)), 0).label(c) for c in campos]
    linhas = db.execute(
        select(*colunas).where(numerado.c.pos == 1).group_by(numerado.c.escola_id)
    ).all()
    return {linha.escola_id: dict(linha._mapping) for linha in linhas}


def _medias_por_plataforma(db: Session, ids: list[int], modelo, coluna
                           ) -> dict[int, tuple[int, float]]:
    """Média da nota de UMA plataforma, SOMENTE sobre os alunos que têm dado dela.

    O motor cria uma linha em ``notas`` para TODO aluno matriculado (ele precisa
    disso para o ranking interno), inclusive quem nunca usou a plataforma — e
    esse aluno fica com nota 0. Se a média da escola incluísse esses zeros, ela
    mediria *desempenho × cobertura*, e não desempenho: uma escola ótima com
    metade dos alunos fora da plataforma parecia ruim (o caso "42/54" do dono).

    O corte é pela EXISTÊNCIA de snapshot, nunca por ``nota > 0``: um aluno que
    usa a plataforma e ainda leu 0 livros é um zero LEGÍTIMO e deve pesar na
    média; quem não usa é ausência de dado e fica fora da conta.

    E o conjunto é o dos MATRICULADOS no ano letivo ativo — o mesmo de
    ``total_alunos``, de ``_alunos_com_qualquer_dado`` e de
    ``_totais_plataforma_por_escola``. ``notas`` NÃO é apagada quando o aluno
    perde a matrícula (o recálculo só grava por cima das linhas do conjunto
    pontuado), então a nota órfã de quem foi desvinculado — ao excluir uma turma
    antiga, ao ser movido de escola — continuava entrando na média e no
    denominador ``alunos_com_nota_*``. Era o MESMO furo que
    ``_totais_plataforma_por_escola`` já fecha com a matrícula, e produzia dois
    sintomas: a média puxada pelo dado de quem não está mais na escola e
    ``alunos_com_nota_elefante > total_alunos`` no cartão. EXISTS (e não JOIN)
    porque o aluno pode ter matrícula em mais de uma turma: o JOIN duplicaria a
    linha da nota e distorceria a contagem e a média.

    Devolve ``{escola_id: (alunos_com_dado, media)}``.
    """
    if not ids:
        return {}
    tem_dado = (
        select(modelo.id)
        .where(modelo.escola_id == Nota.escola_id, modelo.aluno_id == Nota.aluno_id)
        .exists()
    )
    matriculado = (
        select(Matricula.id)
        .where(Matricula.escola_id == Nota.escola_id,
               Matricula.aluno_id == Nota.aluno_id,
               Matricula.ano_letivo == Escola.ano_letivo_ativo)
        .exists()
    )
    linhas = db.execute(
        select(Nota.escola_id, func.count(Nota.id), func.avg(coluna))
        .join(Aluno, Aluno.id == Nota.aluno_id)
        .join(Escola, Escola.id == Nota.escola_id)
        .where(Nota.escola_id.in_(ids),
               Nota.ano_letivo == Escola.ano_letivo_ativo,
               Aluno.status == "ativo",
               matriculado,
               tem_dado)
        .group_by(Nota.escola_id)
    ).all()
    return {linha[0]: (int(linha[1] or 0), float(linha[2] or 0.0)) for linha in linhas}


def _alunos_com_qualquer_dado(db: Session, ids: list[int]) -> dict[int, int]:
    """Alunos DISTINTOS com dado de ALGUMA plataforma, por escola — o numerador
    honesto da cobertura. (A contagem antiga usava linhas de ``notas``, que
    existem para todo matriculado, então a "adoção" dava ~100% sempre.)"""
    if not ids:
        return {}
    total: dict[int, set[int]] = {}
    for modelo in (SnapshotElefante, SnapshotMatific):
        for escola_id, aluno_id in db.execute(
            select(modelo.escola_id, modelo.aluno_id)
            .join(Aluno, Aluno.id == modelo.aluno_id)
            .join(Escola, Escola.id == modelo.escola_id)
            .join(Matricula, (Matricula.aluno_id == modelo.aluno_id)
                  & (Matricula.escola_id == modelo.escola_id)
                  & (Matricula.ano_letivo == Escola.ano_letivo_ativo))
            .where(modelo.escola_id.in_(ids), Aluno.status == "ativo")
            .distinct()
        ).all():
            total.setdefault(escola_id, set()).add(aluno_id)
    return {escola_id: len(alunos) for escola_id, alunos in total.items()}


def _kpis_da_rede(db: Session, rede_id: int) -> list[dict]:
    """Cartão resumido de CADA escola da rede (contagens + médias + totais brutos
    das plataformas do ano letivo ativo da própria escola), agregado no banco.
    ``adocao`` = % de alunos ativos com nota (proxy de engajamento). Escolas sem
    dados entram com zeros. NUNCA expõe PII: só agregados por escola."""
    escolas = escolas_da_rede(db, rede_id)
    if not escolas:
        return []
    ids = [e.id for e in escolas]

    # (1) turmas ativas por escola — cada escola pelo seu ano_letivo_ativo.
    turmas = dict(db.execute(
        select(Turma.escola_id, func.count(Turma.id))
        .join(Escola, Escola.id == Turma.escola_id)
        .where(Turma.escola_id.in_(ids),
               Turma.ano_letivo == Escola.ano_letivo_ativo,
               Turma.status == "ativa")
        .group_by(Turma.escola_id)
    ).all())

    # (2) alunos ativos distintos por escola.
    alunos = dict(db.execute(
        select(Matricula.escola_id, func.count(func.distinct(Matricula.aluno_id)))
        .join(Aluno, Aluno.id == Matricula.aluno_id)
        .join(Escola, Escola.id == Matricula.escola_id)
        .where(Matricula.escola_id.in_(ids),
               Matricula.ano_letivo == Escola.ano_letivo_ativo,
               Aluno.status == "ativo")
        .group_by(Matricula.escola_id)
    ).all())

    # MÓDULOS CONTRATADOS pela rede (SaaS). O que não foi contratado não entra em
    # média, ranking nem adoção — e NÃO é a mesma coisa que "sem dados": módulo
    # contratado sem importação continua valendo e aparece vazio na tela.
    contratados = modulos.modulos_da_rede(db, rede_id)
    tem_mod_leitura = "leitura" in contratados
    tem_mod_matematica = "matematica" in contratados

    # (3) DESEMPENHO por plataforma — média só sobre quem TEM dado dela (ver
    # _medias_por_plataforma). Separa desempenho de cobertura: a média responde
    # "quem usa, vai bem?" e a adoção responde "quantos usam?".
    #
    # RÉGUA INSTITUCIONAL (separação institucional × escola): a rede lê SEMPRE as
    # colunas `nota_*_institucional` — calculadas com o perfil fixo do Constela
    # (A3 + pesos padrão + linear P90), imunes a qualquer configuração local. Ler
    # `Nota.nota_elefante`/`nota_matific` (a nota LOCAL da escola) aqui deixaria um
    # coordenador manipular a posição da escola no ranking da rede mudando os
    # próprios pesos/dificuldade. Travado por test_scoring_institucional.py.
    med_ele = (_medias_por_plataforma(db, ids, SnapshotElefante,
                                      Nota.nota_elefante_institucional)
               if tem_mod_leitura else {})
    med_mat = (_medias_por_plataforma(db, ids, SnapshotMatific,
                                      Nota.nota_matific_institucional)
               if tem_mod_matematica else {})
    # COBERTURA: alunos distintos com dado de alguma plataforma (numerador real).
    com_dados_por_escola = _alunos_com_qualquer_dado(db, ids)

    # (4) professores por escola (mesma contagem do painel da escola).
    professores = dict(db.execute(
        select(Professor.escola_id, func.count(Professor.id))
        .where(Professor.escola_id.in_(ids))
        .group_by(Professor.escola_id)
    ).all())

    # (5) totais BRUTOS das plataformas por escola (snapshot atual de cada aluno):
    # livros/tempo do Elefante e atividades/estrelas do Matific + alunos ativos.
    mat = _totais_plataforma_por_escola(db, ids, SnapshotMatific, ["atividades", "estrelas"])
    ele = _totais_plataforma_por_escola(db, ids, SnapshotElefante,
                                        ["livros_unicos", "tempo_leitura_min"])

    cartoes = []
    for escola in escolas:
        total_alunos = int(alunos.get(escola.id, 0))
        # DESEMPENHO: média de quem TEM dado da plataforma (ausência ≠ zero).
        n_ele, media_elefante = med_ele.get(escola.id, (0, 0.0))
        n_mat, media_matific = med_mat.get(escola.id, (0, 0.0))
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
            # Per capita por MATRÍCULA (÷ total de alunos da escola) — critério de
            # ranking JUSTO entre escolas de tamanhos diferentes: combina adoção e
            # intensidade e NÃO favorece a escola grande pelo volume bruto (item 1).
            # É a conta do dono: 19.122÷200≈95,6 supera 24.000÷600=40.
            "livros_por_matricula": round(livros / total_alunos, 1) if total_alunos else 0.0,
            "estrelas_por_matricula": round(estrelas / total_alunos, 1) if total_alunos else 0.0,
            "atividades_por_matricula": round(atividades / total_alunos, 1) if total_alunos else 0.0,
            "tempo_por_matricula_min": round(tempo_min / total_alunos, 1) if total_alunos else 0.0,
        })
    # O índice comparável é resolvido com a COORTE inteira em mãos (a régua é a
    # melhor escola da rede), e só então o alerta de atenção — que agora depende
    # dele — pode ser decidido. Por isso os dois passos vêm depois do laço.
    _pontuar_por_percapita(cartoes)
    for cartao in cartoes:
        motivo = _motivo_atencao(cartao["total_alunos"], cartao["alunos_com_dados"],
                                 cartao["adocao"], cartao["pontuacao_geral"])
        cartao["precisa_atencao"] = motivo is not None
        cartao["motivo_atencao"] = motivo
    return cartoes


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
    nenhum número do painel municipal se move."""
    if not cartoes:
        return

    def _na_coorte(c: dict, dimensao: str, ativos: str) -> bool:
        """O cartão entra na pontuação (e, portanto, na régua) desta dimensão?
        São dois cortes: módulo fora do plano nem existe; módulo contratado sem
        importação existe, mas ainda não tem o que pontuar."""
        return c[ativos] > 0 and dimensao in (c.get("modulos") or list(modulos.TODOS))

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


def dashboard_rede(db: Session, rede_id: int) -> dict:
    """Painel municipal: totais da rede + cartão de cada escola (para cards e o
    mapa), ordenado por média geral e já numerado (``posicao``). Inclui um resumo
    de EQUIDADE (dispersão entre escolas) e a lista de escolas em ATENÇÃO."""
    cartoes = _kpis_da_rede(db, rede_id)

    total_alunos = sum(c["total_alunos"] for c in cartoes)
    total_turmas = sum(c["total_turmas"] for c in cartoes)
    total_professores = sum(c["total_professores"] for c in cartoes)
    com_dados = sum(c["alunos_com_dados"] for c in cartoes)

    # Média da rede PONDERADA por alunos-com-nota (não média de médias, que daria
    # peso igual a uma escola de 10 e uma de 500 alunos).
    #
    # O PESO é o DENOMINADOR DAQUELA MÉTRICA (Arquitetura 2, spec §1.2 — ausência
    # não é zero, também na rede). Para as médias POR DIMENSÃO o denominador é o
    # número de alunos aferidos NAQUELA dimensão, não "alunos com dado de alguma
    # plataforma": com o peso genérico, a escola que não usa o Elefante entrava na
    # média de LEITURA da rede com `media_elefante = 0` e puxava o número para
    # baixo — o mesmo "ausência vira zero" que a arquitetura elimina no aluno,
    # reaparecendo um nível acima. `media_geral` e `pontuacao_geral` seguem com o
    # peso genérico porque o denominador delas É "alunos com algum dado".
    def _ponderada(chave: str, peso: str = "alunos_com_dados") -> float:
        total = sum(c[peso] for c in cartoes)
        if not total:
            return 0.0
        return round(sum(c[chave] * c[peso] for c in cartoes) / total, 1)

    media_rede = _ponderada("media_geral")
    indice_rede = _ponderada("pontuacao_geral")
    com_nota = [c for c in cartoes if c["alunos_com_dados"] > 0]
    medias = [c["media_geral"] for c in com_nota]
    indices = [c["pontuacao_geral"] for c in com_nota]
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
    # nome (determinístico), a mesma régua de `ranking_escolas`.
    cartoes.sort(key=lambda c: (-c["pontuacao_geral"], -c["adocao"],
                                c["nome"].casefold()))
    for posicao, cartao in enumerate(cartoes, start=1):
        cartao["posicao"] = posicao

    # Totais brutos das plataformas na rede + alunos ativos (soma dos cartões).
    total_livros = sum(c["livros"] for c in cartoes)
    total_atividades = sum(c["atividades"] for c in cartoes)
    ativos_elefante = sum(c["ativos_elefante"] for c in cartoes)
    # A melhor escola COM dados (o pódio do ranking geral) — atalho para o KPI.
    melhor = next((c for c in cartoes if c["alunos_com_dados"] > 0), None)

    return {
        "rede_id": rede_id,
        # Módulos contratados — a interface inteira (cards, abas, rankings,
        # explicador) se adapta a partir daqui.
        "modulos": sorted(modulos.modulos_da_rede(db, rede_id)),
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
            "media_matific": _ponderada("media_matific", "alunos_com_nota_matific"),
            "media_elefante": _ponderada("media_elefante", "alunos_com_nota_elefante"),
            # ÍNDICE (0–1000) da rede: média ponderada do índice das escolas — a
            # métrica comparável, usada nas metas e no boletim.
            "pontuacao_geral": indice_rede,
            "escolas_em_atencao": sum(1 for c in cartoes if c["precisa_atencao"]),
            # Totais das plataformas na rede inteira (seções Elefante/Matific).
            "livros": total_livros,
            "tempo_leitura_min": sum(c["tempo_leitura_min"] for c in cartoes),
            "atividades": total_atividades,
            "estrelas": sum(c["estrelas"] for c in cartoes),
            "ativos_matific": sum(c["ativos_matific"] for c in cartoes),
            "ativos_elefante": ativos_elefante,
            "livros_por_aluno": round(total_livros / ativos_elefante, 1) if ativos_elefante else 0.0,
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
    }


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
                    metrica: str = "geral") -> list[dict]:
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
    adoção de alguma plataforma qualquer."""
    chave = METRICAS_RANKING.get(metrica, "pontuacao_geral")
    desempate = DESEMPATE_DA_DIMENSAO.get(DIMENSAO_DA_METRICA.get(metrica), "adocao")
    cartoes = [c for c in _kpis_da_rede(db, rede_id) if c["alunos_com_dados"] > 0]
    cartoes.sort(key=lambda c: (-c[chave], -c[desempate], c["nome"].casefold()))
    for posicao, cartao in enumerate(cartoes[:limite], start=1):
        cartao["posicao"] = posicao
    return cartoes[:limite]


# ---------------------------------------------------------------------------
# Visão GLOBAL do Admin Global — consolida TODAS as redes (uma camada acima da
# Secretaria, que vê só a própria rede). Só agregados por escola/rede, sem PII.
# ---------------------------------------------------------------------------

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

        # Mesmo peso-por-denominador de `dashboard_rede._ponderada`: a média de
        # LEITURA da rede pesa pelos alunos aferidos EM LEITURA. Sem isso, uma
        # escola que não usa o Elefante entra na média de leitura com zero.
        def _pond(chave: str, peso: str = "alunos_com_dados",
                  _cartoes=cartoes) -> float:
            total = sum(c[peso] for c in _cartoes)
            if not total:
                return 0.0
            return round(sum(c[chave] * c[peso] for c in _cartoes) / total, 1)

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
            "media_geral": _pond("media_geral"),
            "media_matific": _pond("media_matific", "alunos_com_nota_matific"),
            "media_elefante": _pond("media_elefante", "alunos_com_nota_elefante"),
            # Denominadores POR DIMENSÃO da rede — o peso das médias no nível
            # global (`_pond_global`) e o "de quantos alunos" de cada média.
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
            "livros_por_matricula": round(livros / alunos, 1) if alunos else 0.0,
            "estrelas_por_matricula": round(estrelas / alunos, 1) if alunos else 0.0,
        })
        for c in cartoes:
            todas_escolas.append({**c, "rede_id": rede.id, "rede_nome": rede.nome})

    total_com_dados = sum(r["alunos_com_dados"] for r in cartoes_rede)

    def _pond_global(chave: str, peso: str = "alunos_com_dados") -> float:
        total = sum(r[peso] for r in cartoes_rede)
        if not total:
            return 0.0
        return round(sum(r[chave] * r[peso] for r in cartoes_rede) / total, 1)

    # Comparação ENTRE REDES: índice per capita na coorte "todas as redes".
    _pontuar_por_percapita(cartoes_rede)
    cartoes_rede.sort(key=lambda r: (-r["pontuacao_geral"], r["nome"].casefold()))
    for posicao, cartao in enumerate(cartoes_rede, start=1):
        cartao["posicao"] = posicao
    # Melhores escolas de TODAS as redes: o índice DE REDE de cada uma não serve
    # aqui (cada escola foi normalizada contra a melhor da SUA rede, então um
    # 1000 de um município de 3 escolas empataria com o 1000 de uma capital).
    # Pontua-se de novo, com a coorte global, em chaves próprias.
    top = [e for e in todas_escolas if e["alunos_com_dados"] > 0]
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
            "media_geral": _pond_global("media_geral"),
            "media_matific": _pond_global("media_matific", "alunos_com_nota_matific"),
            "media_elefante": _pond_global("media_elefante", "alunos_com_nota_elefante"),
            "pontuacao_geral": _pond_global("pontuacao_geral"),
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
# com que `dashboard_rede._ponderada` calcula o total da rede: se ele é zero, o
# "atual" não é um desempenho zero — é a ausência de medição.
_PESO_DA_META = {
    "media_elefante": "alunos_com_nota_elefante",
    "media_matific": "alunos_com_nota_matific",
    "media_geral": "alunos_com_dados",
}


def _meta_medida(metrica: str, cartoes: list[dict]) -> bool:
    """A métrica tem população aferida na rede hoje? Contagens, adoção e índice
    per capita não passam por aqui: neles o zero é um fato sobre as matrículas."""
    peso = _PESO_DA_META.get(metrica)
    return True if peso is None else sum(c.get(peso, 0) for c in cartoes) > 0


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
    com_dados = [c for c in dados["escolas"] if c["alunos_com_dados"] > 0]
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
            "medida": _meta_medida(m.metrica, dados["escolas"]),
            "escolas_atingiram": None, "escolas_total": None,
        }
        # A contagem "X de Y escolas atingiram" só existe para métrica
        # COMPARÁVEL: com a média 0–100 (régua interna de cada escola) ela era um
        # número inválido publicado ao lado de um número válido.
        if cfg["por_escola"] and cfg["comparavel"] and com_dados:
            item["escolas_atingiram"] = sum(1 for c in com_dados if c.get(m.metrica, 0) >= m.alvo)
            item["escolas_total"] = len(com_dados)
        saida.append(item)
    return saida


# ---------------------------------------------------------------------------
# Painel PÚBLICO da Secretaria (vitrine SEM login): as MELHORES ESCOLAS da rede
# em leitura e matemática — decisão de produto do dono. NUNCA nome de criança
# nem ranking individual; só escolas + a métrica. Habilitado por um token na
# rede (nulo = desligado); trocar/limpar o token invalida o link imediatamente.
# ---------------------------------------------------------------------------

def _top_escolas(cartoes: list[dict], chave: str, limite: int = 5) -> list[dict]:
    """Top-N escolas por uma métrica (>0), sem PII — só nome + valor."""
    validos = [c for c in cartoes if c["alunos_com_dados"] > 0 and c.get(chave, 0) > 0]
    validos.sort(key=lambda c: (-c[chave], c["nome"].casefold()))
    return [{"nome": c["nome"], "valor": round(float(c[chave]), 1)}
            for c in validos[:limite]]


def painel_publico_rede(db: Session, rede_id: int) -> dict:
    """Dados da vitrine pública: top 5 escolas em LEITURA e em MATEMÁTICA. Só
    agregado por escola — sem PII de criança.

    O critério é PER CAPITA (livros ÷ alunos, estrelas ÷ alunos), o mesmo do
    Ranking da Rede. Ordenar pelas médias 0–100 do motor coroaria em praça
    pública a escola de distribuição mais homogênea — que pode ser justamente a
    que menos lê —, porque aquela régua é o P90 de cada escola contra ela mesma.
    A unidade vai junto para o telão dizer o que o número significa."""
    rede = db.get(Rede, rede_id)
    cartoes = _kpis_da_rede(db, rede_id)
    return {
        "rede_nome": rede.nome if rede else "",
        "top_leitura": _top_escolas(cartoes, "livros_por_matricula"),
        "top_matematica": _top_escolas(cartoes, "estrelas_por_matricula"),
        "unidade_leitura": "livros por aluno",
        "unidade_matematica": "estrelas por aluno",
    }


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
