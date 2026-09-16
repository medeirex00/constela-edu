"""Motor de cálculo de notas e rankings.

Princípios (PRD Parte 3):
  * Nenhum peso vive no código — tudo é lido da tabela `configuracoes`.
  * Todo indicador é normalizado para a escala 0–100 antes de ser ponderado.
  * Cada nota carrega um `detalhes` com o passo a passo completo do cálculo,
    permitindo auditoria total ("Como esta nota foi calculada", PRD §45).
  * O recálculo é integral e automático (PRD §43): qualquer importação ou
    mudança de configuração dispara `recalcular_escola`.

DESEMPENHO POR DIMENSÃO (`docs/spec-arquitetura-2.md`)
------------------------------------------------------
O desempenho do aluno é medido e ordenado POR DIMENSÃO — Leitura (Elefante) e
Matemática (Matific) — e não existe mais ordem única entre dimensões diferentes.
Três invariantes deste arquivo sustentam isso, e nenhum deles pode ser
enfraquecido sem quebrar a arquitetura inteira:

  1. ISOLAMENTO. `nota_elefante` é função exclusiva de `SnapshotElefante` (+ os
     pontos de dificuldade, que saem dele) e `nota_matific`, de
     `SnapshotMatific` — inclusive nas RÉGUAS de normalização, cujo tamanho de
     amostra é contado por dimensão (`_referencias`, `DIMENSAO_DO_INDICADOR`).
     Abrir a 2ª plataforma não move a nota da 1ª nem por um centésimo.
  2. AUSÊNCIA NÃO É ZERO. Sem snapshot da plataforma, a dimensão é `aferido:
     false` e fica FORA da ordenação dela — não entra com 0,0.
  3. SNAPSHOT ZERADO ≠ AUSÊNCIA. Quem abriu a plataforma e ainda não produziu
     entra, em último, com 0,00. O discriminante é a EXISTÊNCIA do snapshot,
     NUNCA `nota > 0`.

`nota_geral` e `posicao` (a ordem única) continuam sendo gravadas como LEGADO /
COMPATIBILIDADE, para não quebrar em silêncio as vitrines e os clientes ainda
não migrados. Elas **NÃO são fonte oficial de ranking, de premiação nem de
nenhuma decisão de negócio** — para isso existe a dimensão. Nada novo deve
passar a lê-las: a regra é travada por `tests/test_legado_nota_geral.py`
(inventário + varredura + sabotagem) e o caminho de saída está em
`docs/plano-retirada-nota-geral.md`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.database import bloquear_escola_para_recalculo
from app.models import (
    Aluno,
    Configuracao,
    DificuldadeTurma,
    Escola,
    Leitura,
    Matricula,
    NivelDificuldade,
    Nota,
    ReferenciaNormalizacao,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
)

# Pontos extras "por livro lido NA ESCOLA": a janela de horário é definida pelo
# TURNO da turma (horário de Brasília, como já vem no relatório individual do
# Elefante). Manhã 07:00–13:00 e Tarde 13:00–18:00, só de segunda a sexta. O
# limite das 13h vai para a TARDE. Integral/Noite não têm janela (sem bônus).
_JANELAS_TURNO: dict[str, tuple[time, time]] = {
    "manha": (time(7, 0), time(13, 0)),
    "tarde": (time(13, 0), time(18, 0)),
}


def _bonus_leitura_na_escola(
    db: Session, escola_id: int, turno_por_aluno: dict[int, str | None],
    pontos_por_livro: float,
) -> dict[int, float]:
    """Pontos extras de cada aluno = `pontos_por_livro` × (livros lidos DENTRO da
    janela do turno da turma dele, seg–sex). Usa a data+hora real de cada leitura
    (Leitura.data, do relatório individual do Elefante). Livro sem hora conhecida
    ou fora da janela não gera extra."""
    alvos = {aid: _JANELAS_TURNO[t] for aid, t in turno_por_aluno.items()
             if t in _JANELAS_TURNO}
    if not alvos or pontos_por_livro <= 0:
        return {}
    bonus: dict[int, float] = {}
    for aluno_id, data in db.execute(
        select(Leitura.aluno_id, Leitura.data)
        .where(Leitura.escola_id == escola_id, Leitura.aluno_id.in_(alvos.keys()))
    ):
        if data is None:
            continue
        quando = data.replace(tzinfo=None) if data.tzinfo is not None else data
        if quando.weekday() >= 5:                       # só segunda a sexta
            continue
        ini, fim = alvos[aluno_id]
        if ini <= quando.time() < fim:                  # dentro da janela do turno
            bonus[aluno_id] = bonus.get(aluno_id, 0.0) + pontos_por_livro
    return {aid: round(b, 2) for aid, b in bonus.items()}


def pontos_dif_com_bonus(db: Session, escola_id: int, matriculas,
                         pontos_dif: dict[int, float],
                         ) -> tuple[dict[int, float], dict[int, float]]:
    """``(pontos_dif + bônus, bônus por aluno)`` no perfil PERSONALIZADO.

    FONTE ÚNICA do bônus "livro lido NA ESCOLA": o motor (``recalcular_escola``) e
    o simulador (``contexto_normalizacao``) somam o MESMO valor ANTES de calcular
    as referências. Sem isso o simulador normalizava a dificuldade por uma régua
    que não conhecia o bônus e devolvia outra nota de Leitura para o mesmo aluno —
    a segunda fórmula que o simulador existe para não ter. Bônus desligado (ou
    pontos ≤ 0) devolve os pontos como estavam. Não muta o dicionário recebido."""
    extra = obter_config(db, escola_id, "pesos.elefante_extra", "valores",
                         {"ativo": False, "pontos_por_livro": 0.0})
    if not extra.get("ativo") or float(extra.get("pontos_por_livro", 0) or 0) <= 0:
        return dict(pontos_dif), {}
    turno_por_aluno = {m.aluno_id: t.turno for m, t in matriculas}
    bonus_por_aluno = _bonus_leitura_na_escola(
        db, escola_id, turno_por_aluno, float(extra["pontos_por_livro"]))
    somados = dict(pontos_dif)
    for aid, b in bonus_por_aluno.items():
        somados[aid] = somados.get(aid, 0.0) + b
    return somados, bonus_por_aluno


# Valores usados apenas na primeira execução, antes do seed gravar os
# padrões no banco. Depois disso, a fonte é sempre a tabela `configuracoes`.
PESOS_PADRAO = {
    "pesos.matific": {"atividades": 40.0, "media": 35.0, "estrelas": 25.0},
    "pesos.elefante": {"livros": 35.0, "dificuldade": 30.0, "questoes": 30.0, "tempo": 5.0},
    "pesos.questoes": {"tentativas": 30.0, "acertos": 70.0},
    "pesos.geral": {"matific": 50.0, "elefante": 50.0},
}

# ---------------------------------------------------------------------------
# PERFIL INSTITUCIONAL — a régua OFICIAL da rede (fixa, não editável)
# ---------------------------------------------------------------------------
# A separação institucional × escola nasce daqui. Este perfil é uma CONSTANTE de
# código: dificuldade A3 (`exp(0,103·pos)`), pesos padrão e normalização linear
# P90. É com ele que as notas `*_institucional` são calculadas e o ranking da
# rede é montado — nenhum coordenador o alcança. O perfil da ESCOLA (pesos e
# dificuldade em `configuracoes`/`niveis_dificuldade`) só vale no contexto
# INTERNO dela, e só quando ela escolhe "personalizado".
#
# NÃO é "editar NIVEIS_PADRAO global": NIVEIS_PADRAO segue sendo o SEED editável
# da escola; A3_INSTITUCIONAL é uma régua paralela e imutável, usada por um
# caminho de cálculo explícito (perfil institucional), nunca lida da config.

# Ordem canônica dos níveis do Elefante (AA=0 … Z=29). Posição = dificuldade.
NIVEIS_ORDENADOS = ("AA", "BB", "CC", "DD", "A", "B", "C", "D", "E", "F", "G",
                    "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S",
                    "T", "U", "V", "W", "X", "Y", "Z")
POS_DO_NIVEL = {codigo: i for i, codigo in enumerate(NIVEIS_ORDENADOS)}

# Coeficiente da A3 (decidido a partir dos dados reais do catálogo do Elefante:
# span AA→Z ≈ 19,8x, alinhado à régua histórica de 16x, monótono, sem a inversão
# DD>A do wordCount cru). NÃO alterar sem nova análise + aprovação.
A3_COEFICIENTE = 0.103


def peso_a3(codigo: str) -> float:
    """Peso institucional de dificuldade de um nível AA–Z: ``exp(0,103·pos)``.
    Nível fora da escala AA–Z (dado sujo) → 0, como no mapa por faixa da escola."""
    pos = POS_DO_NIVEL.get(str(codigo).strip().upper())
    return round(math.exp(A3_COEFICIENTE * pos), 6) if pos is not None else 0.0


# Mapa de dificuldade no formato que `_pontos_dificuldade` consome, com a A3 em
# ``__padrao__`` e SEM overrides por série/turma (a régua da rede é uma só).
A3_MAPA_DIFICULDADE: dict = {
    "__padrao__": {codigo: peso_a3(codigo) for codigo in NIVEIS_ORDENADOS},
    "__turma__": {},
}

CRITERIOS_DESEMPATE_PADRAO = [
    "nota_elefante",
    "nota_matific",
    "livros_unicos",
    "atividades",
    "pct_acertos",
    "nome",
]

# Desempate de um ranking DE DIMENSÃO: só indicadores DAQUELA dimensão (spec
# §2.2). O padrão antigo começa em `nota_elefante` e segue para `nota_matific` —
# num ranking de Leitura isso faria a medalha de leitura ser decidida pela
# matemática, reintroduzindo DENTRO da dimensão o defeito que a arquitetura
# elimina ENTRE dimensões. Configurável por escola em
# ``desempate.criterios_leitura`` / ``desempate.criterios_matematica``.
CRITERIOS_DESEMPATE_DIMENSAO: dict[str, list[str]] = {
    "leitura": ["nota_elefante", "pontos_dificuldade", "livros_unicos",
                "pct_acertos", "nome"],
    "matematica": ["nota_matific", "estrelas", "atividades", "pontuacao_media",
                   "nome"],
}


def _finito(valor) -> float | None:
    """``float`` finito ou None (None, bool, texto não numérico, NaN, ±infinito).
    Guarda numérica da normalização: nada que não seja número finito entra na conta."""
    if valor is None or isinstance(valor, bool):
        return None
    try:
        numero = float(valor)
    except (TypeError, ValueError, OverflowError):
        return None
    return numero if math.isfinite(numero) else None


def _entrada_nao_negativa(valor):
    """Entrada de indicador/referência como número FINITO ≥ 0, preservando o tipo
    quando já é válido (``12`` continua ``12`` nos detalhes da Nota). Negativo,
    NaN, infinito, None ou não numérico → 0."""
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        # `_finito` (e não `math.isfinite` direto) porque um INTEIRO fora do
        # alcance do float — `10**400`, que o JSON aceita — faz `math.isfinite`
        # levantar OverflowError no meio do cálculo da nota. Aqui ele é entrada
        # suja como qualquer outra: 0. Valor válido continua saindo INTACTO.
        numero = _finito(valor)
        if numero is not None and numero >= 0:
            return valor
        return 0.0 if isinstance(valor, float) else 0
    numero = _finito(valor)
    return numero if numero is not None and numero >= 0 else 0


def _nota_0_100(nota) -> float:
    """Nota final sempre finita em [0, 100] (arredondada a 2 casas)."""
    numero = _finito(nota)
    if numero is None:
        return 0.0
    return round(min(100.0, max(0.0, numero)), 2)


def normalizar(valor: float, referencia: float) -> float:
    """Converte um valor bruto para a escala 0–100 usando a referência.

    Referência ausente, zero, negativa ou não finita resulta em 0 (nada a
    comparar ainda); valor ≤ 0 ou não finito também dá 0. O teto é 100 mesmo que
    um aluno ultrapasse a referência manual. Resultado sempre em [0, 100].
    """
    ref = _finito(referencia)
    if ref is None or ref <= 0:
        return 0.0
    v = _finito(valor)
    if v is None or v <= 0:
        return 0.0
    return _nota_0_100(min(100.0, (v / ref) * 100.0))


# ---------------------------------------------------------------------------
# Normalização robusta (auto): saturação de VOLUME + referência por percentil
# ---------------------------------------------------------------------------
# Indicadores de VOLUME (contagens acumuladas) recebem RETORNOS DECRESCENTES:
# dobrar a quantidade não dobra a nota. Indicadores de QUALIDADE (média de
# desempenho, dificuldade, acertos) permanecem LINEARES. A referência do modo
# auto passa a ser o P90 (robusto) em vez do MÁXIMO, para que um único outlier
# não defina a régua e "esmague" os demais. Corrige a distorção de o ranking
# medir volume acumulado sem punir excesso — sem regra específica por aluno.
INDICADORES_VOLUME = {"atividades", "estrelas", "livros", "tempo", "tentativas"}
# Estatística robusta (P90/mediana) só é confiável com amostra suficiente;
# abaixo disso a escola cai na escala simples por máximo (comportamento antigo).
MIN_ALUNOS_ROBUSTO = 8

# DIMENSÃO de cada indicador. Existe para uma garantia estrutural (Arquitetura 2,
# item 6): a nota de LEITURA só pode nascer de dado do Elefante e a de MATEMÁTICA
# só de dado do Matific — **inclusive na régua de normalização**. Toda decisão de
# `_referencias` que dependa do TAMANHO DA AMOSTRA é tomada por dimensão, usando
# este mapa; sem ele, a amostra de uma plataforma decidia a régua da outra.
DIMENSAO_DO_INDICADOR: dict[str, str] = {
    "atividades": "matific",
    "media": "matific",
    "estrelas": "matific",
    "livros": "elefante",
    "pontos_dificuldade": "elefante",
    "tentativas": "elefante",
    "acertos": "elefante",
    "tempo": "elefante",
}

# Dimensão (vocabulário do produto e do catálogo de módulos) → plataforma (nome
# técnico do dado, o mesmo dos snapshots). Fonte única: quem quiser saber "de
# onde sai a nota de Leitura" olha aqui, não um `if` espalhado.
DIMENSOES: dict[str, str] = {"leitura": "elefante", "matematica": "matific"}


def normalizar_saturado(valor: float, referencia: float, k: float) -> float:
    """Normalização CÔNCAVA (retornos decrescentes) reescalada p/ referência→100.

    Curva de saturação hiperbólica ``x/(x+k)``: cresce rápido no começo e satura
    depois. ``k`` é a meia-saturação (mediana da escola) — no valor ``k`` a curva
    entrega metade do teto. ``k`` ausente/não finito/``<=0`` recai no linear;
    referência ou valor inválido (≤0, não finito) dá 0.
    Preserva ordem (monótona) e teto 100; comprime distâncias entre volumes altos.
    """
    # GUARDAS: referência ausente/≤0/não finita ou valor ≤0/não finito → 0; k
    # ausente, não finito ou ≤0 → linear. Resultado sempre em [0, 100].
    ref = _finito(referencia)
    if ref is None or ref <= 0:
        return 0.0
    v = _finito(valor)
    if v is None or v <= 0:
        return 0.0
    k_f = _finito(k)
    if k_f is None or k_f <= 0:
        return normalizar(v, ref)
    if v >= ref:
        return 100.0          # curva monótona: na referência ou acima, teto
    try:
        f_ref = ref / (ref + k_f)
        resultado = (v / (v + k_f)) / f_ref * 100.0
    except ZeroDivisionError:
        resultado = math.nan
    if not math.isfinite(resultado):
        # Magnitudes astronômicas (a soma estoura ou a fração some): a mesma
        # curva com os três termos reescalados pelo maior; se ainda degenerar, o
        # limite de k muito maior que a referência é o linear.
        escala = max(ref, k_f)
        v_e, ref_e, k_e = v / escala, ref / escala, k_f / escala
        f_ref_e = ref_e / (ref_e + k_e)
        if f_ref_e <= 0 or not math.isfinite(f_ref_e):
            return normalizar(v, ref)
        resultado = (v_e / (v_e + k_e)) / f_ref_e * 100.0
    return _nota_0_100(min(100.0, resultado))


def _percentil(valores: list[float], p: float) -> float:
    """Percentil ``p`` (0–1) por interpolação linear. Lista vazia → 0."""
    # GUARDA: valores não finitos (NaN, ±infinito, None, texto) são ignorados.
    v = sorted(x for x in (_finito(bruto) for bruto in valores) if x is not None)
    if not v:
        return 0.0
    if len(v) == 1:
        return v[0]
    pos = (len(v) - 1) * p
    baixo = int(pos)
    frac = pos - baixo
    if baixo + 1 < len(v):
        return v[baixo] + (v[baixo + 1] - v[baixo]) * frac
    return v[-1]


def _ativos_finitos(valores) -> list[float]:
    """Valores ATIVOS da régua robusta: só números finitos > 0."""
    return [x for x in (_finito(bruto) for bruto in valores) if x is not None and x > 0]


def _maximo_finito(valores):
    """Régua simples (amostra pequena): o MAIOR valor finito ≥ 0 — o próprio
    elemento, como ``max`` fazia (``30`` continua ``30``); nenhum → 0."""
    melhor, melhor_num = None, 0.0
    for bruto in valores:
        numero = _finito(bruto)
        if numero is None or numero < 0:
            continue
        if melhor is None or numero > melhor_num:
            melhor, melhor_num = bruto, numero
    if melhor is None:
        return 0
    return melhor if isinstance(melhor, (int, float)) else melhor_num


def referencias_robustas(
    listas: dict[str, list[float]],
) -> tuple[dict[str, float], dict[str, float]]:
    """Régua justa (P90 + k=mediana) a partir de listas de valores por indicador.

    Mesma regra do modo auto do Ranking Geral, em forma PURA e reutilizável —
    o Ranking de EVOLUÇÃO usa esta função sobre os GANHOS do período, para o
    topo ficar disputado lá também (um único gigante não vira a régua de todos).
    Amostra pequena (< ``MIN_ALUNOS_ROBUSTO``) recai no máximo, sem saturação.
    Retorna ``(referencias, k_por_indicador)``.

    CONTRATO DE USO (a garantia de isolamento depende de quem chama): ``n_alunos``
    é o MAIOR tamanho entre TODAS as listas recebidas. Chamar esta função com
    indicadores das DUAS dimensões de uma vez faz a coorte de uma ligar o modo
    robusto da outra — o mesmo canal entre dimensões que ``_referencias`` fecha
    com ``DIMENSAO_DO_INDICADOR``. Por isso **chame uma vez por dimensão**, só
    com os indicadores dela e só com os valores dos alunos AFERIDOS nela, como
    faz ``evolucao._referencias_por_dimensao`` (o único chamador de produção).
    """
    n_alunos = max((len(v) for v in listas.values()), default=0)
    usar_robusto = n_alunos >= MIN_ALUNOS_ROBUSTO
    refs: dict[str, float] = {}
    k_vol: dict[str, float] = {}
    for indicador, valores in listas.items():
        chave = "max_" + indicador
        # GUARDA: ativos = só finitos > 0; no fallback do máximo, só finitos ≥ 0.
        # A amostra que liga o modo robusto (``n_alunos``) não muda.
        ativos = _ativos_finitos(valores)
        if usar_robusto and len(ativos) >= 2:
            refs[chave] = _percentil(ativos, 0.90)
            if indicador in INDICADORES_VOLUME:
                k_vol[indicador] = _percentil(ativos, 0.50)
        else:
            refs[chave] = _maximo_finito(valores)
    return refs, k_vol


# ---------------------------------------------------------------------------
# Leitura de configurações
# ---------------------------------------------------------------------------

def obter_config(db: Session, escola_id: int, namespace: str, chave: str, padrao):
    row = db.execute(
        select(Configuracao).where(
            Configuracao.escola_id == escola_id,
            Configuracao.namespace == namespace,
            Configuracao.chave == chave,
        )
    ).scalar_one_or_none()
    return row.valor if row is not None else padrao


def _pesos_dos_modulos_contratados(db: Session, escola_id: int,
                                   valores: dict) -> dict:
    """Mantém em ``pesos.geral`` só as plataformas dos módulos CONTRATADOS.

    Sem isto, uma rede que assinou apenas a Leitura teria ``nota_geral =
    0,5·elefante + 0,5·0`` — metade da nota, por um produto que ela nem contratou
    (o mesmo "teto de 50" que corrigimos nas médias da escola, agora no ALUNO).
    Como ``obter_pesos`` divide pela soma logo abaixo, remover a chave já
    REDISTRIBUI o peso: só Leitura ⇒ {elefante: 1,0}. Com os dois módulos nada
    muda (50/50), então o comportamento atual é preservado bit a bit.

    Só age em ``pesos.geral`` (a combinação ENTRE plataformas). Os pesos DENTRO
    de cada plataforma (livros/dificuldade/questões, atividades/média/estrelas)
    não têm relação com contratação e ficam intocados."""
    from app.services import modulos as svc_modulos

    escola = db.get(Escola, escola_id)
    contratados = svc_modulos.modulos_da_escola(db, escola)
    permitidas = {p for chave in contratados
                  for p in svc_modulos.CATALOGO[chave]["plataformas"]}
    filtrados = {k: v for k, v in valores.items() if k in permitidas}
    # Nenhuma plataforma contratada (config exótica): mantém o original em vez de
    # zerar a nota de todo mundo — degradação segura.
    return filtrados or valores


def obter_pesos(db: Session, escola_id: int, namespace: str) -> dict[str, float]:
    """Retorna os pesos como frações (0–1), já normalizados defensivamente.

    A interface impede salvar pesos cuja soma difere de 100 (PRD §33),
    mas o motor ainda divide pela soma para nunca produzir notas > 100.

    Em ``pesos.geral``, as plataformas de módulos NÃO contratados saem da conta e
    o peso é redistribuído entre as contratadas (ver
    ``_pesos_dos_modulos_contratados``) — a fórmula, as referências (P90/mediana)
    e a saturação seguem exatamente as mesmas.
    """
    valores = obter_config(db, escola_id, namespace, "valores", PESOS_PADRAO[namespace])
    if namespace == "pesos.geral":
        valores = _pesos_dos_modulos_contratados(db, escola_id, valores)
    total = sum(float(v) for v in valores.values())
    if total <= 0:
        return {k: 0.0 for k in valores}
    return {k: float(v) / total for k, v in valores.items()}


def pesos_geral_do_aluno(pesos_geral: dict[str, float],
                         dimensoes_com_dados: set[str]) -> dict[str, float]:
    """Renormaliza ``pesos.geral`` sobre as plataformas em que o ALUNO tem dado.

    NOVO PAPEL (Arquitetura 2): a RENORMALIZAÇÃO desta função serve apenas à
    ``nota_geral``, que virou LEGADO e não ordena mais nada. O que ficou
    ESSENCIAL — e carrega mais peso do que antes — é o conjunto de entrada
    ``dimensoes_com_dados``: é ele que decide quem entra no ranking de cada
    dimensão, o ``aferido`` de cada dimensão e a adoção do aluno (|D| / |P|).
    Sem ele, "sem snapshot" e "snapshot zerado" voltam a ser a mesma coisa e a
    arquitetura inteira cai junto. Não reverter.

    É a MESMA regra que a escola já aplicava — "só quem tem dado da plataforma
    entra na média" (``rede._medias_por_plataforma``) —, agora no nível do aluno.
    Sem isto a ausência de dado entra na média ponderada como ZERO e cria um
    TETO DE 50 para quem usa uma plataforma só: a criança que leu 30 livros
    (nota_elefante 100) ficava com 50 e perdia posição, prêmio e certificado para
    quem leu 10 e também usou o Matific. O Ranking Geral passava a ordenar por
    ADESÃO, não por desempenho.

    Relação com ``_pesos_dos_modulos_contratados``: são DOIS cortes diferentes,
    em cascata, e nenhum duplica o outro —
      1. CONTRATO (rede/escola): o que a rede assinou. Já vem aplicado em
         ``pesos_geral``, que é a ENTRADA desta função.
      2. DADO (aluno): dentro do que foi contratado, o que ESTA criança usa.
    Uma dimensão contratada e sem dado do aluno sai da conta, e o peso é
    redistribuído PROPORCIONALMENTE entre as que sobraram (a divisão pela soma é
    a mesma primitiva de ``obter_pesos``). Com as duas plataformas disponíveis
    nada muda (50/50), então a nota de quem usa as duas é preservada bit a bit.

    Degradação segura: aluno sem NENHUMA dimensão disponível — ou cuja única
    dimensão com dado não é contratada — mantém os pesos de entrada. A nota é 0
    dos dois lados de qualquer jeito, e a explicação continua somando 100%. É o
    mesmo idioma do ``filtrados or valores`` do corte por módulo.
    """
    filtrados = {k: v for k, v in pesos_geral.items() if k in dimensoes_com_dados}
    total = sum(filtrados.values())
    if not filtrados or total <= 0:
        return dict(pesos_geral)
    return {k: v / total for k, v in filtrados.items()}


def obter_pesos_brutos(db: Session, escola_id: int, namespace: str) -> dict[str, float]:
    return dict(obter_config(db, escola_id, namespace, "valores", PESOS_PADRAO[namespace]))


# ---------------------------------------------------------------------------
# Estado atual dos alunos (snapshots mais recentes)
# ---------------------------------------------------------------------------

def _snapshots_atuais(db: Session, escola_id: int, modelo):
    """Último snapshot de cada aluno para a plataforma indicada.

    "Último" pela DATA DE REFERÊNCIA (id desempata), não pelo id: importar um
    relatório de um período antigo (backfill mensal do Matific) registra o
    histórico sem rebaixar o estado atual dos rankings. A seleção acontece no
    banco (window function) — snapshots são imutáveis e só crescem; varrer
    todos como objetos ORM a cada recálculo não escala."""
    ids = ids_snapshots_atuais(modelo, escola_id)
    rows = db.execute(select(modelo).where(modelo.id.in_(ids))).scalars().all()
    return {row.aluno_id: row for row in rows}


def ids_snapshots_atuais(modelo, escola_id: int):
    """Subquery com o id do snapshot mais recente (data_referencia, id) de
    cada aluno da escola."""
    numerado = (
        select(
            modelo.id.label("snap_id"),
            func.row_number().over(
                partition_by=modelo.aluno_id,
                order_by=(modelo.data_referencia.desc(), modelo.id.desc()),
            ).label("posicao"),
        )
        .where(modelo.escola_id == escola_id)
        .subquery()
    )
    return select(numerado.c.snap_id).where(numerado.c.posicao == 1).scalar_subquery()


def _chaves_do_nivel(nivel: NivelDificuldade) -> list[str]:
    """Todas as chaves que representam a faixa em livros_por_nivel: os códigos
    de letra dos livros E o código estável da faixa (ex.: "pre_leitor"), que é
    usado quando os livros são informados/importados diretamente por faixa."""
    from app.models.configuracao import slug_nivel

    chaves = list(nivel.codigos or [])
    chaves.append(nivel.codigo or slug_nivel(nivel.nome))
    return chaves


def _overrides_turma(db: Session, escola_id: int) -> dict[int, dict[str, float]]:
    """Config LIVRE de pontos por TURMA: ``{turma_id: {CODIGO_UPPER: pontos}}``
    (esparso — só turmas customizadas). Sobrepõe o padrão da escola por código."""
    from app.models.configuracao import PontuacaoNivelTurma

    saida: dict[int, dict[str, float]] = {}
    for row in db.execute(
        select(PontuacaoNivelTurma).where(PontuacaoNivelTurma.escola_id == escola_id)
    ).scalars():
        m: dict[str, float] = {}
        for k, v in (row.pontos_por_codigo or {}).items():
            try:
                m[str(k).strip().upper()] = float(v)
            except (TypeError, ValueError):
                continue
        if m:
            saida[row.turma_id] = m
    return saida


def _mapa_dificuldade(db: Session, escola_id: int) -> dict:
    """Mapa de resolução de pontos. Chaves:
      ``"__padrao__"``     -> {codigo: pontos_padrao da faixa} (case preservado)
      ``(ano_escolar, codigo)`` -> override por SÉRIE (DificuldadeTurma, legado)
      ``"__turma__"``      -> {turma_id: {CODIGO_UPPER: pontos}} livre por TURMA
    Resolução (em ``_pontos_dificuldade``): TURMA > SÉRIE > padrão."""
    niveis = db.execute(
        select(NivelDificuldade).where(NivelDificuldade.escola_id == escola_id)
    ).scalars().all()
    mapa: dict = {}
    padrao_por_codigo: dict[str, float] = {}
    for nivel in niveis:
        for codigo in _chaves_do_nivel(nivel):
            padrao_por_codigo[codigo] = float(nivel.pontos_padrao)

    niveis_por_id = {n.id: n for n in niveis}
    for override in db.execute(
        select(DificuldadeTurma).where(DificuldadeTurma.escola_id == escola_id)
    ).scalars():
        nivel = niveis_por_id.get(override.nivel_id)
        if nivel is None:
            continue
        for codigo in _chaves_do_nivel(nivel):
            mapa[(override.ano_escolar, codigo)] = float(override.pontos)

    mapa["__padrao__"] = padrao_por_codigo
    mapa["__turma__"] = _overrides_turma(db, escola_id)
    return mapa


def _pontos_dificuldade(
    livros_por_nivel: dict, ano_escolar: str, mapa: dict,
    turma_id: int | None = None,
) -> float:
    padrao: dict[str, float] = mapa.get("__padrao__", {})
    por_turma: dict[str, float] = (
        mapa.get("__turma__", {}).get(turma_id, {}) if turma_id else {})
    total = 0.0
    for codigo, quantidade in (livros_por_nivel or {}).items():
        cod_up = str(codigo).strip().upper()
        if cod_up in por_turma:                       # 1) livre por TURMA
            pontos = por_turma[cod_up]
        elif (ano_escolar, codigo) in mapa:           # 2) por SÉRIE (legado)
            pontos = mapa[(ano_escolar, codigo)]
        else:                                          # 3) padrão da faixa
            pontos = padrao.get(codigo, 0.0)
        total += float(pontos) * int(quantidade)
    return round(total, 2)


def _overrides_serie(db: Session, escola_id: int) -> dict[tuple[str, str], float]:
    """Override de pontos por SÉRIE (legado): ``{(ano_escolar, CODIGO_UPPER):
    pontos}`` a partir de DificuldadeTurma. Sobrepõe o padrão da escola; é
    sobreposto pela config LIVRE por turma. Resolução: TURMA > SÉRIE > padrão."""
    niveis = {n.id: n for n in db.execute(
        select(NivelDificuldade).where(NivelDificuldade.escola_id == escola_id)
    ).scalars()}
    saida: dict[tuple[str, str], float] = {}
    for ov in db.execute(
        select(DificuldadeTurma).where(DificuldadeTurma.escola_id == escola_id)
    ).scalars():
        nivel = niveis.get(ov.nivel_id)
        if nivel is None:
            continue
        for codigo in (nivel.codigos or []):
            if codigo:
                saida[(ov.ano_escolar, str(codigo).strip().upper())] = float(ov.pontos)
    return saida


def pontos_por_codigo(db: Session, escola_id: int, turma_id: int | None = None,
                      ano_escolar: str | None = None) -> dict[str, float]:
    """Pontos de dificuldade por CÓDIGO de letra do livro (ex.: {"AA": 1.0,
    "D": 4.0}). Base do ranking de leitura por período. Com ``ano_escolar`` e/ou
    ``turma_id``, resolve **TURMA > SÉRIE > padrão** — a MESMA régua do ranking
    anual, para as telas de PERÍODO (premiações, aba Leitura, evolução, histórico)
    não divergirem do Geral."""
    mapa: dict[str, float] = {}
    for nivel in db.execute(
        select(NivelDificuldade).where(NivelDificuldade.escola_id == escola_id)
    ).scalars():
        for codigo in (nivel.codigos or []):
            if codigo:
                mapa[str(codigo).upper()] = float(nivel.pontos_padrao)
    if ano_escolar:                       # 2) override por SÉRIE
        for (serie, cod_up), pontos in _overrides_serie(db, escola_id).items():
            if serie == ano_escolar and cod_up in mapa:
                mapa[cod_up] = pontos
    if turma_id:                          # 1) config LIVRE por TURMA (mais forte)
        mapa.update(_overrides_turma(db, escola_id).get(turma_id, {}))
    return mapa


def mapa_pontos_turmas(db: Session, escola_id: int) -> dict:
    """``{turma_id | None: {CODIGO_UPPER: pontos}}`` resolvido **TURMA > SÉRIE >
    padrão**. ``None`` = padrão da escola; cada turma já traz a SÉRIE e a config
    LIVRE aplicadas. Para o ranking/premiação por período resolver a pontuação
    pela turma do aluno numa passada só (sem N+1)."""
    base = pontos_por_codigo(db, escola_id)
    overrides_serie = _overrides_serie(db, escola_id)
    overrides_turma = _overrides_turma(db, escola_id)
    turmas = db.execute(
        select(Turma.id, Turma.ano_escolar).where(Turma.escola_id == escola_id)
    ).all()
    saida: dict = {None: base}
    for turma_id, serie in turmas:
        combinado = dict(base)
        for (s, cod_up), pontos in overrides_serie.items():   # SÉRIE
            if s == serie and cod_up in combinado:
                combinado[cod_up] = pontos
        combinado.update(overrides_turma.get(turma_id, {}))   # TURMA-livre (mais forte)
        saida[turma_id] = combinado
    return saida


def distribuicao_niveis(
    db: Session, escola_id: int, livros_por_nivel: dict, ano_escolar: str = "",
    turma_id: int | None = None, aluno_id: int | None = None,
    livros_unicos: int | None = None,
) -> dict:
    """Distribuição dos livros de um aluno pelas FAIXAS de dificuldade.

    Para relatórios/gráficos: por faixa devolve quantidade, pontos por livro,
    pontos ganhos e percentual; além do total de livros, dos pontos de
    dificuldade e da faixa predominante. Funciona com livros por faixa ou por
    código de letra.

    Os pontos saem da FONTE ÚNICA (``dificuldade_livro.regra_da_escola``): na
    regra v1 global cada livro itemizado do aluno (``aluno_id``) vale o seu
    próprio valor e ``pontos_por_livro`` é a média da faixa; na régua legada
    (perfil personalizado) vale a config LIVRE da turma, senão o override da
    série, senão o padrão — exatamente como antes.
    """
    from app.models.configuracao import slug_nivel
    from app.services import dificuldade_livro as _dl

    niveis = db.execute(
        select(NivelDificuldade)
        .where(NivelDificuldade.escola_id == escola_id)
        .order_by(NivelDificuldade.ordem)
    ).scalars().all()
    dados = livros_por_nivel or {}
    regra = _dl.regra_da_escola(db, escola_id)
    v1 = regra.versao == _dl.VERSAO_VIGENTE
    if v1:
        leituras = (_dl.leituras_por_aluno(db, escola_id, {aluno_id}).get(aluno_id)
                    if aluno_id else None)
        por_chave = regra.pontos_por_chave(dados, ano_escolar, turma_id, leituras)
    else:
        mapa = regra._mapa
        padrao: dict[str, float] = mapa.get("__padrao__", {})  # type: ignore[assignment]
        por_turma: dict[str, float] = (
            mapa.get("__turma__", {}).get(turma_id, {}) if turma_id else {})
        por_chave = {}

    faixas = []
    total_livros = 0
    pontos_total = 0.0
    for nivel in niveis:
        slug = nivel.codigo or slug_nivel(nivel.nome)
        chaves = _chaves_do_nivel(nivel)
        quantidade = sum(int(dados.get(c, 0) or 0) for c in chaves)
        if v1:
            pontos = round(sum(float(por_chave.get(c, 0.0)) for c in chaves), 2)
            pontos_unidade = (round(pontos / quantidade, 4) if quantidade
                              else regra.valor_tipico(chaves[0], ano_escolar))
        else:
            # Config LIVRE da turma (representada pela 1ª letra da faixa com
            # override) tem prioridade sobre a série e o padrão.
            override_turma = next(
                (por_turma[str(c).upper()] for c in chaves if str(c).upper() in por_turma),
                None)
            pontos_unidade = float(
                override_turma if override_turma is not None
                else mapa.get((ano_escolar, slug), padrao.get(slug, nivel.pontos_padrao)))
            pontos = round(quantidade * pontos_unidade, 2)
        faixas.append({
            "codigo": slug,
            "nome": nivel.nome,
            "quantidade": quantidade,
            "pontos_por_livro": pontos_unidade,
            "pontos": pontos,
            "percentual": 0.0,
        })
        total_livros += quantidade
        pontos_total += pontos
    if v1:
        # Chaves fora das faixas cadastradas (ex.: tier Z+) ainda pontuam no total.
        pontos_total = round(sum(por_chave.values()), 2)

    for faixa in faixas:
        faixa["percentual"] = (round(faixa["quantidade"] / total_livros * 100, 1)
                               if total_livros else 0.0)

    com_livros = [f for f in faixas if f["quantidade"] > 0]
    predominante = max(com_livros, key=lambda f: f["quantidade"])["nome"] \
        if com_livros else None

    return {
        "faixas": faixas,
        "total_livros": total_livros,
        "pontos_dificuldade": round(pontos_total, 2),
        "faixa_predominante": predominante,
        # Livros contados no snapshot (`livros_unicos`) mas SEM distribuição por
        # nível nem leituras itemizadas: a dificuldade é DESCONHECIDA, não zero.
        "incompleto": bool((livros_unicos or 0) > 0 and pontos_total == 0
                           and not (v1 and leituras)),
    }


# ---------------------------------------------------------------------------
# Referências de normalização (PRD §31, §62)
# ---------------------------------------------------------------------------

CHAVES_REFERENCIA = [
    "max_atividades",
    "max_media",
    "max_estrelas",
    "max_livros",
    "max_pontos_dificuldade",
    "max_tentativas",
    "max_acertos",
    "max_tempo",
]


def _referencias_auto(
    matific: dict[int, SnapshotMatific],
    elefante: dict[int, SnapshotElefante],
    pontos_dificuldade: dict[int, float],
) -> tuple[dict[str, float], dict[str, float]]:
    """Referências AUTO (P90 + k=mediana) e nada mais — PURO, sem tocar em
    ``configuracoes``/``ReferenciaNormalizacao``. É o coração da régua robusta,
    compartilhado por dois chamadores: ``_referencias`` (que pode sobrescrever
    com o modo MANUAL da escola) e o perfil INSTITUCIONAL (que usa este resultado
    direto, sem modo manual — a rede tem uma régua só). Retorna ``(refs, k_vol)``.

    ISOLAMENTO ENTRE DIMENSÕES: cada lista sai dos snapshots de UMA plataforma e a
    amostra que decide robusto×máximo é contada POR DIMENSÃO (``n_por_dimensao``),
    então abrir a 2ª plataforma nunca move a nota da 1ª."""
    listas = {
        "atividades": [s.atividades for s in matific.values()],
        "media": [s.pontuacao_media for s in matific.values()],
        "estrelas": [s.estrelas for s in matific.values()],
        "livros": [s.livros_unicos for s in elefante.values()],
        # `pontos_dificuldade` tem uma entrada por aluno PONTUADO (inclusive quem
        # não tem snapshot do Elefante, com 0). Os zeros são descartados de
        # `ativos` logo abaixo, então a régua continua saindo só de quem lê — e a
        # amostra que liga o modo robusto é `len(elefante)`, não o tamanho desta
        # lista, justamente para a matrícula de um aluno sem leitura não decidi-la.
        "pontos_dificuldade": list(pontos_dificuldade.values()),
        "tentativas": [s.questoes_tentativas for s in elefante.values()],
        "acertos": [s.questoes_acertos for s in elefante.values()],
        "tempo": [s.tempo_leitura_min for s in elefante.values()],
    }
    n_por_dimensao = {"matific": len(matific), "elefante": len(elefante)}
    refs: dict[str, float] = {}
    k_vol: dict[str, float] = {}
    for indicador, valores in listas.items():
        chave = "max_" + indicador
        # GUARDA: ativos = só finitos > 0; máximo só entre finitos ≥ 0 (padrão 0).
        ativos = _ativos_finitos(valores)
        usar_robusto = (n_por_dimensao[DIMENSAO_DO_INDICADOR[indicador]]
                        >= MIN_ALUNOS_ROBUSTO)
        if usar_robusto and len(ativos) >= 2:
            refs[chave] = _percentil(ativos, 0.90)        # régua robusta (top 10%)
            if indicador in INDICADORES_VOLUME:
                k_vol[indicador] = _percentil(ativos, 0.50)  # meia-saturação = mediana
        else:
            refs[chave] = _maximo_finito(valores)          # poucos dados → escala simples
    return refs, k_vol


def _referencias(
    db: Session,
    escola_id: int,
    matific: dict[int, SnapshotMatific],
    elefante: dict[int, SnapshotElefante],
    pontos_dificuldade: dict[int, float],
) -> tuple[dict[str, float], str, dict[str, float]]:
    """Resolve as referências e o k de saturação de cada indicador.

    Modo AUTO (robusto): referência = **P90** dos alunos ATIVOS (>0) — não o
    máximo — para um único outlier não definir a régua; e ``k`` (meia-saturação)
    = mediana dos ativos, só para os indicadores de VOLUME. Escola pequena
    (< ``MIN_ALUNOS_ROBUSTO``) ou indicador com poucos ativos recai no máximo
    (escala simples, sem saturação). Modo MANUAL: valores do admin, LINEARES
    (sem saturação — previsível), com chaves ausentes caindo no auto.
    Retorna ``(referencias, modo, k_por_indicador)``; ``k`` vazio = sem saturação.

    ISOLAMENTO ENTRE DIMENSÕES (garantia estrutural da Arquitetura 2): cada
    lista abaixo é montada a partir dos snapshots de UMA plataforma só, e o
    tamanho da amostra que decide o modo (robusto × máximo) é contado **por
    dimensão**. Assim ``nota_elefante`` é função exclusiva de dado do Elefante e
    ``nota_matific``, de dado do Matific — abrir a segunda plataforma não move a
    nota da primeira nem por um centésimo.
    """
    auto, k_vol = _referencias_auto(matific, elefante, pontos_dificuldade)

    ref_row = db.execute(
        select(ReferenciaNormalizacao).where(
            ReferenciaNormalizacao.escola_id == escola_id
        )
    ).scalar_one_or_none()

    if ref_row is None or ref_row.modo == "auto":
        return auto, "auto", k_vol

    # MANUAL: o admin define a régua → linear e previsível (sem saturação).
    manuais = ref_row.valores_manuais or {}
    resolvidas = {
        chave: float(manuais.get(chave) or auto[chave]) for chave in CHAVES_REFERENCIA
    }
    return resolvidas, "manual", {}


# ---------------------------------------------------------------------------
# Cálculo por módulo
# ---------------------------------------------------------------------------

def _norm(indicador: str, valor: float, referencia: float,
          k_vol: dict[str, float] | None) -> float:
    """Normaliza um indicador: saturado se ``k_vol`` tiver o k dele (volume no
    modo auto), senão linear (qualidade, modo manual, evolução)."""
    k = (k_vol or {}).get(indicador)
    return normalizar_saturado(valor, referencia, k) if k else normalizar(valor, referencia)


def _linha(nome: str, indicador: str, valor: float, referencia: float,
           peso_pct: float, k_vol: dict[str, float] | None) -> dict:
    norm = _norm(indicador, valor, referencia, k_vol)
    # GUARDA: peso não finito não vira NaN nos detalhes (JSON inválido).
    peso_seguro = peso_pct if _finito(peso_pct) is not None else 0
    return {
        "indicador": nome,
        "valor": valor,
        "referencia": referencia,
        "normalizado": norm,
        "peso": peso_seguro,
        "contribuicao": round(norm * peso_seguro / 100.0, 2),
    }


def calcular_matific(
    snapshot: SnapshotMatific | None,
    refs: dict[str, float],
    pesos: dict[str, float],
    pesos_pct: dict[str, float],
    k_vol: dict[str, float] | None = None,
) -> tuple[float, list[dict]]:
    # GUARDAS: entradas e referências como números finitos ≥ 0; referência
    # inexistente vale 0 (nota 0 no indicador, nunca KeyError); nota em [0, 100].
    atividades = _entrada_nao_negativa(snapshot.atividades) if snapshot else 0
    media = _entrada_nao_negativa(snapshot.pontuacao_media) if snapshot else 0.0
    estrelas = _entrada_nao_negativa(snapshot.estrelas) if snapshot else 0
    refs = refs or {}
    ref_atividades = _entrada_nao_negativa(refs.get("max_atividades", 0.0))
    ref_media = _entrada_nao_negativa(refs.get("max_media", 0.0))
    ref_estrelas = _entrada_nao_negativa(refs.get("max_estrelas", 0.0))

    linhas = [
        _linha("Atividades finalizadas", "atividades", atividades, ref_atividades, pesos_pct.get("atividades", 0), k_vol),
        _linha("Pontuação média", "media", media, ref_media, pesos_pct.get("media", 0), k_vol),
        _linha("Estrelas", "estrelas", estrelas, ref_estrelas, pesos_pct.get("estrelas", 0), k_vol),
    ]
    nota = (
        _norm("atividades", atividades, ref_atividades, k_vol) * pesos.get("atividades", 0)
        + _norm("media", media, ref_media, k_vol) * pesos.get("media", 0)
        + _norm("estrelas", estrelas, ref_estrelas, k_vol) * pesos.get("estrelas", 0)
    )
    return _nota_0_100(nota), linhas


def calcular_elefante(
    snapshot: SnapshotElefante | None,
    pontos_dificuldade: float,
    refs: dict[str, float],
    pesos: dict[str, float],
    pesos_pct: dict[str, float],
    pesos_questoes: dict[str, float],
    pesos_questoes_pct: dict[str, float],
    k_vol: dict[str, float] | None = None,
) -> tuple[float, list[dict], dict]:
    # GUARDAS: entradas e referências como números finitos ≥ 0; referência
    # inexistente vale 0 (nunca KeyError); sub-nota e nota finais em [0, 100].
    livros = _entrada_nao_negativa(snapshot.livros_unicos) if snapshot else 0
    tempo = _entrada_nao_negativa(snapshot.tempo_leitura_min) if snapshot else 0
    tentativas = _entrada_nao_negativa(snapshot.questoes_tentativas) if snapshot else 0
    acertos = _entrada_nao_negativa(snapshot.questoes_acertos) if snapshot else 0
    pontos_dificuldade = _entrada_nao_negativa(pontos_dificuldade)
    refs = refs or {}
    ref_livros = _entrada_nao_negativa(refs.get("max_livros", 0.0))
    ref_dificuldade = _entrada_nao_negativa(refs.get("max_pontos_dificuldade", 0.0))
    ref_tentativas = _entrada_nao_negativa(refs.get("max_tentativas", 0.0))
    ref_acertos = _entrada_nao_negativa(refs.get("max_acertos", 0.0))
    ref_tempo = _entrada_nao_negativa(refs.get("max_tempo", 0.0))

    # Sub-nota de questões: tentativas (volume → satura) + acertos (qualidade →
    # linear), PRD §36. Assim tentar muito não infla; acertar é que conta.
    n_tentativas = _norm("tentativas", tentativas, ref_tentativas, k_vol)
    n_acertos = normalizar(acertos, ref_acertos)
    nota_questoes = _nota_0_100(
        n_tentativas * pesos_questoes.get("tentativas", 0)
        + n_acertos * pesos_questoes.get("acertos", 0)
    )
    detalhe_questoes = {
        "tentativas": {"valor": tentativas, "referencia": ref_tentativas, "normalizado": n_tentativas, "peso": pesos_questoes_pct.get("tentativas", 0)},
        "acertos": {"valor": acertos, "referencia": ref_acertos, "normalizado": n_acertos, "peso": pesos_questoes_pct.get("acertos", 0)},
        "sub_nota": nota_questoes,
    }

    linhas = [
        _linha("Livros únicos concluídos", "livros", livros, ref_livros, pesos_pct.get("livros", 0), k_vol),
        _linha("Pontos de dificuldade", "pontos_dificuldade", pontos_dificuldade, ref_dificuldade, pesos_pct.get("dificuldade", 0), k_vol),
        _linha("Questões (tentativas + acertos)", "questoes", nota_questoes, 100.0, pesos_pct.get("questoes", 0), None),
        _linha("Tempo de leitura (min)", "tempo", tempo, ref_tempo, pesos_pct.get("tempo", 0), k_vol),
    ]
    nota = (
        _norm("livros", livros, ref_livros, k_vol) * pesos.get("livros", 0)
        + normalizar(pontos_dificuldade, ref_dificuldade) * pesos.get("dificuldade", 0)
        + nota_questoes * pesos.get("questoes", 0)
        + _norm("tempo", tempo, ref_tempo, k_vol) * pesos.get("tempo", 0)
    )
    return _nota_0_100(nota), linhas, detalhe_questoes


# ---------------------------------------------------------------------------
# Desempate (PRD §42) — critérios configuráveis
# ---------------------------------------------------------------------------

@dataclass
class ResultadoAluno:
    aluno: Aluno
    ano_escolar: str
    turma_nome: str
    nota_matific: float = 0.0
    nota_elefante: float = 0.0
    nota_geral: float = 0.0
    livros_unicos: int = 0
    atividades: int = 0
    pct_acertos: float = 0.0
    # Indicadores dos desempates LOCAIS de cada dimensão (§2.2): sem eles o
    # desempate da Leitura teria de cair na nota de Matemática, que é o defeito
    # que a arquitetura elimina — dentro da dimensão, inclusive.
    pontos_dificuldade: float = 0.0
    estrelas: int = 0
    pontuacao_media: float = 0.0
    # Estado por DIMENSÃO ("leitura"/"matematica"): aferido, posição na dimensão
    # e os dados brutos que sustentam a nota.
    aferido: dict = field(default_factory=dict)
    posicao_dimensao: dict = field(default_factory=dict)
    dados_dimensao: dict = field(default_factory=dict)
    snapshot_em: dict = field(default_factory=dict)
    detalhes: dict = field(default_factory=dict)


def _chave_ordenacao(resultado: ResultadoAluno, criterios: list[str]):
    """LEGADO — a ordem única (``Nota.posicao``), ancorada em ``nota_geral``.

    Continua existindo só enquanto as vitrines (certificado, cartaz, telão, Top
    10) não forem convertidas para ordem por dimensão. Nada novo deve usá-la;
    a ordenação oficial é ``_chave_ordenacao_dimensao``.
    """
    chave: list = [-resultado.nota_geral]
    for criterio in criterios:
        if criterio == "nome":
            chave.append(resultado.aluno.nome.casefold())
        else:
            chave.append(-float(getattr(resultado, criterio, 0) or 0))
    # Desempate final DETERMINÍSTICO: dois alunos DISTINTOS homônimos e com todas
    # as métricas iguais não podem trocar de posição entre recálculos sucessivos
    # (aluno.id é único e estável).
    chave.append(resultado.aluno.id)
    return tuple(chave)


def _chave_ordenacao_dimensao(resultado: ResultadoAluno, criterios: list[str]):
    """Chave de ordenação DENTRO de uma dimensão — 100% local a ela.

    Diferente de ``_chave_ordenacao``, não há âncora em ``nota_geral``: o
    primeiro critério já É a nota da dimensão. Termina no mesmo desempate
    determinístico (nome + ``aluno.id``), para que dois homônimos empatados em
    tudo não troquem de posição entre recálculos.
    """
    chave: list = []
    for criterio in criterios:
        if criterio == "nome":
            chave.append(resultado.aluno.nome.casefold())
        else:
            chave.append(-float(getattr(resultado, criterio, 0) or 0))
    chave.append(resultado.aluno.id)
    return tuple(chave)


# ---------------------------------------------------------------------------
# Recalculo integral (PRD §43)
# ---------------------------------------------------------------------------

def _carregar_contexto(db: Session, escola_id: int):
    """Carrega tudo que o cálculo precisa: matrículas do ano ativo,
    snapshots mais recentes por aluno e pontos de dificuldade por série."""
    escola = db.get(Escola, escola_id)
    if escola is None:
        return None
    ano = escola.ano_letivo_ativo

    matriculas = db.execute(
        select(Matricula, Turma)
        .join(Turma, Matricula.turma_id == Turma.id)
        .join(Aluno, Matricula.aluno_id == Aluno.id)
        .where(
            Matricula.escola_id == escola_id,
            Matricula.ano_letivo == ano,
            Aluno.status == "ativo",
        )
        .options(selectinload(Matricula.aluno))  # evita N+1 em matricula.aluno
    ).all()

    # Restringe os snapshots ao conjunto PONTUADO (ativos matriculados no ano) —
    # o mesmo dos `pontos_dif` abaixo. Sem isto, o snapshot de um aluno arquivado/
    # excluído/não-matriculado entrava na régua de normalização (P90/mediana) sem
    # ser pontuado: arquivar um aluno (operação rotineira, que dispara recálculo)
    # mudava as notas e as posições de todos os ativos.
    ids_pontuados = {m.aluno_id for m, _t in matriculas}
    matific = {aid: s for aid, s in _snapshots_atuais(db, escola_id, SnapshotMatific).items()
               if aid in ids_pontuados}
    elefante = {aid: s for aid, s in _snapshots_atuais(db, escola_id, SnapshotElefante).items()
                if aid in ids_pontuados}

    # DIFICULDADE pela FONTE ÚNICA (services/dificuldade_livro): v1 global por
    # livro (A3 × ajuste intrínseco × série) — ou a régua legada por faixa quando
    # a escola está no perfil personalizado. As leituras ITEMIZADAS (título) da
    # escola vêm numa query só, para cada livro valer o seu próprio valor; o
    # restante da contagem do snapshot vale o típico do nível.
    from app.services import dificuldade_livro as _dl
    regra = _dl.regra_da_escola(db, escola_id)
    # Leituras ITEMIZADAS (uma query) → INSUMO RECONCILIADO por aluno
    # (dificuldade_livro.InsumoElefante): livros/tempo = o MAIOR entre snapshot e
    # itemização (nunca a soma — a mesma leitura não conta duas vezes); quem só
    # tem leituras também vira insumo (ausência de snapshot não é nota zero);
    # quem não tem nada fica fora (ausência de dado). Nunca é o objeto ORM.
    leituras = _dl.leituras_por_aluno(db, escola_id, ids_pontuados)
    elefante = _dl.insumos_elefante(elefante, leituras, ids_pontuados)
    pontos_dif: dict[int, float] = {}
    for matricula, turma in matriculas:
        insumo = elefante.get(matricula.aluno_id)
        pontos_dif[matricula.aluno_id] = regra.pontos_aluno(
            insumo.livros_por_nivel if insumo else {}, turma.ano_escolar,
            turma_id=turma.id, leituras=leituras.get(matricula.aluno_id),
        )
    return escola, ano, matriculas, matific, elefante, pontos_dif


def carimbo_institucional(personalizado: bool = False) -> dict:
    """Carimbo gravado em ``Nota.detalhes`` por ``recalcular_escola``: prova que as
    colunas ``*_institucional`` da linha foram calculadas pelo motor com a régua
    vigente (a rede só agrega notas carimbadas — ver ``rede._CARIMBO_INSTITUCIONAL``).
    Determinístico (sem timestamp). Exposto para fixtures de teste que fabricam
    Notas fora do motor."""
    from app.services import dificuldade_livro as _dl
    return {"regua_institucional": {
        "versao_dificuldade": _dl.VERSAO_VIGENTE,
        "perfil_local": "personalizado" if personalizado else "institucional"}}


def _data_iso(snapshot) -> str | None:
    """``data_referencia`` do snapshot atual em ISO (só a data), ou ``None``."""
    data = getattr(snapshot, "data_referencia", None)
    return data.date().isoformat() if data is not None else None


def referencias_em_uso(db: Session, escola_id: int) -> tuple[dict, str]:
    """Referências efetivas (tela REFERÊNCIAS DE NORMALIZAÇÃO, PRD §62)."""
    refs, modo, _ = contexto_normalizacao(db, escola_id)
    return refs, modo


def contexto_normalizacao(
    db: Session, escola_id: int
) -> tuple[dict, str, dict[str, float]]:
    """``(referencias, modo, k_saturacao)`` — para o ranking e o simulador
    (sistema.py) usarem exatamente a mesma normalização."""
    contexto = _carregar_contexto(db, escola_id)
    if contexto is None:
        return {}, "auto", {}
    _, _, matriculas, matific, elefante, pontos_dif = contexto
    if not _scoring_personalizado(db, escola_id):
        # Perfil institucional: a MESMA régua de `recalcular_escola` (auto P90,
        # sem modo manual local) — senão o simulador mostrava uma nota que o
        # motor nunca calcularia para esta escola. O bônus de leitura na escola
        # não existe neste perfil (só no personalizado, abaixo).
        refs, k_vol = _referencias_auto(matific, elefante, pontos_dif)
        return refs, "auto", k_vol
    # Personalizado: o MESMO bônus que `recalcular_escola` soma em `pontos_dif`
    # ANTES das referências. Sem esta linha a referência de dificuldade do
    # simulador (e a nota de Leitura que ele mostra) ficava menor que a oficial.
    pontos_dif, _ = pontos_dif_com_bonus(db, escola_id, matriculas, pontos_dif)
    return _referencias(db, escola_id, matific, elefante, pontos_dif)


COMPOSICAO_ATUAL = "por_dimensao_v1"


def dimensoes_contratadas(db: Session, escola) -> list[str]:
    """Dimensões que a rede da escola CONTRATOU, na ordem do catálogo.

    Primeiro degrau da cascata CONTRATO → DADO (a mesma de
    ``_pesos_dos_modulos_contratados``): o que a rede não assinou não tem nota,
    não tem ranking e não entra no denominador da adoção. Contrato exótico sem
    nenhum módulo cai em "todas" — a mesma degradação segura do ``filtrados or
    valores``, para nunca zerar a escola inteira por uma configuração estranha.
    """
    from app.services import modulos as svc_modulos

    contratados = svc_modulos.modulos_da_escola(db, escola)
    return [dim for dim in DIMENSOES if dim in contratados] or list(DIMENSOES)


def _ordenar_por_dimensao(db: Session, escola_id: int, escola,
                          resultados: list[ResultadoAluno]) -> dict[str, int]:
    """Carimba, em cada resultado, a POSIÇÃO dentro de cada dimensão contratada
    e escreve o bloco ``detalhes.dimensoes`` (+ ``adocao`` e ``composicao``).

    Regras que este bloco materializa (spec §1.2, §2):
      * só entra na ordenação de ``d`` quem é AFERIDO em ``d`` — existe snapshot
        atual daquela plataforma. Ausência vira ESTADO (`aferido: false`, nota
        `null`, posição `null`), nunca o valor zero;
      * snapshot zerado ENTRA, em último, com 0,00 — é "usa e ainda não
        produziu", um zero legítimo;
      * o desempate é LOCAL à dimensão (§2.2): a medalha de Leitura não pode ser
        decidida pela nota de Matemática;
      * ``n_aferidos`` viaja junto com a posição porque é o denominador dela —
        sem ele, "3º" numa dimensão e "3º" na outra parecem comparáveis.

    Devolve ``{dimensao: n_aferidos}``.
    """
    contratadas = dimensoes_contratadas(db, escola)
    n_aferidos: dict[str, int] = {}

    for dimensao in DIMENSOES:
        if dimensao not in contratadas:
            # Módulo não contratado: a dimensão não existe para esta escola.
            # Ninguém é "não aferido" num produto que a rede não comprou.
            for resultado in resultados:
                resultado.aferido[dimensao] = False
                resultado.posicao_dimensao[dimensao] = None
            n_aferidos[dimensao] = 0
            continue
        criterios = obter_config(db, escola_id, "desempate",
                                 f"criterios_{dimensao}",
                                 CRITERIOS_DESEMPATE_DIMENSAO[dimensao])
        aferidos = [r for r in resultados if r.aferido.get(dimensao)]
        aferidos.sort(key=lambda r: _chave_ordenacao_dimensao(r, criterios))
        for posicao, resultado in enumerate(aferidos, start=1):
            resultado.posicao_dimensao[dimensao] = posicao
        n_aferidos[dimensao] = len(aferidos)

    for resultado in resultados:
        com_dados = [d for d in contratadas if resultado.aferido.get(d)]
        resultado.detalhes["dimensoes"] = {
            dimensao: {
                "plataforma": DIMENSOES[dimensao],
                "contratada": dimensao in contratadas,
                "aferido": bool(resultado.aferido.get(dimensao)),
                # Nota `null` (e não 0,0) quando não aferido: é o que a tela
                # renderiza como `—`. O 0,0 fica reservado ao zero legítimo.
                "nota": (resultado.nota_elefante if dimensao == "leitura"
                         else resultado.nota_matific
                         ) if resultado.aferido.get(dimensao) else None,
                "posicao": resultado.posicao_dimensao.get(dimensao),
                "n_aferidos": n_aferidos[dimensao],
                "snapshot_em": resultado.snapshot_em.get(dimensao),
                "dados": (resultado.dados_dimensao.get(dimensao, {})
                          if resultado.aferido.get(dimensao) else {}),
            }
            for dimensao in DIMENSOES
        }
        # ADOÇÃO DO ALUNO = |D| / |P| (§3.2): cobertura, jamais intensidade —
        # e jamais somada, multiplicada ou promediada com desempenho.
        resultado.detalhes["adocao"] = {
            "contratadas": list(contratadas),
            "com_dados": com_dados,
            "pct": round(len(com_dados) / len(contratadas) * 100, 2)
            if contratadas else 0.0,
        }
        # Carimbo de REGRA: escola sem ele é escola que ainda não foi
        # recalculada nesta arquitetura (recálculo em lote tolera falha por
        # escola). Mesmo idioma do `referencia_tipo`.
        resultado.detalhes["composicao"] = COMPOSICAO_ATUAL
    return n_aferidos


# ---------------------------------------------------------------------------
# Perfil de scoring: INSTITUCIONAL (régua da rede) × ESCOLA (contexto interno)
# ---------------------------------------------------------------------------

PERFIL_SCORING_NS = "scoring.perfil"


def _scoring_personalizado(db: Session, escola_id: int) -> bool:
    """A escola optou por PERSONALIZAR o próprio scoring interno?

    Default = NÃO → "padrão Constela", em que o note interno da escola É a régua
    institucional. Este flag governa APENAS o contexto interno (ranking/competição
    da própria escola); a régua da rede é sempre institucional, independentemente
    dele. Guardado como um valor simples em ``configuracoes`` (namespace
    ``scoring.perfil``, chave ``modo``: ``institucional`` | ``personalizado``)."""
    valor = obter_config(db, escola_id, PERFIL_SCORING_NS, "modo", "institucional")
    return str(valor).strip().lower() == "personalizado"


def _pesos_institucionais(namespace: str) -> tuple[dict[str, float], dict[str, float]]:
    """``(frações normalizadas, percentuais brutos)`` de um namespace de pesos no
    perfil INSTITUCIONAL — fixos (``PESOS_PADRAO``), sem ler config de escola."""
    pct = PESOS_PADRAO[namespace]
    total = sum(float(v) for v in pct.values()) or 1.0
    return {k: float(v) / total for k, v in pct.items()}, dict(pct)


def _pesos_geral_institucional(db: Session, escola_id: int) -> dict[str, float]:
    """``pesos.geral`` institucional (50/50) com o CONTRATO DE MÓDULOS aplicado.
    O contrato é decisão da REDE/Admin (não do coordenador), então entra na régua
    institucional; a escolha local de pesos, não. Frações normalizadas."""
    valores = _pesos_dos_modulos_contratados(db, escola_id, PESOS_PADRAO["pesos.geral"])
    total = sum(float(v) for v in valores.values()) or 1.0
    return {k: float(v) / total for k, v in valores.items()}


def pesos_efetivos(db: Session, escola_id: int,
                   namespace: str) -> tuple[dict[str, float], dict[str, float]]:
    """``(frações normalizadas, percentuais brutos)`` dos pesos que o MOTOR usa de
    fato para esta escola — a FONTE ÚNICA para quem precisa reproduzir a nota
    (simulador, evolução, premiações).

    Perfil institucional (padrão): os pesos FIXOS da rede (``PESOS_PADRAO``, com o
    contrato de módulos em ``pesos.geral``), ignorando qualquer configuração local
    — exatamente como ``recalcular_escola``. Perfil ``personalizado`` (liberado só
    pelo Admin Global): a configuração da escola. Sem isto, uma tela lia a config
    local enquanto a nota oficial usava a régua institucional, e o mesmo aluno
    aparecia com números diferentes em lugares diferentes."""
    if _scoring_personalizado(db, escola_id):
        return obter_pesos(db, escola_id, namespace), obter_pesos_brutos(db, escola_id, namespace)
    if namespace == "pesos.geral":
        fracoes = _pesos_geral_institucional(db, escola_id)
        return fracoes, {k: round(v * 100.0, 4) for k, v in fracoes.items()}
    return _pesos_institucionais(namespace)


def _insumos_institucionais(matriculas, matific, elefante, pontos_dif=None,
                            leituras_por_aluno=None):
    """Insumos do cálculo POR PLATAFORMA no perfil institucional:
    ``(pontos_dif, refs, k_vol, p_matific, pct_matific, p_elefante, pct_elefante,
    p_questoes, pct_questoes)``.

    Tudo derivado só dos dados da PLATAFORMA (snapshots + leituras itemizadas) e
    de constantes de código: dificuldade pela regra GLOBAL v1 (A3 × ajuste
    intrínseco do livro × série — ``dificuldade_livro``; sem bônus de leitura na
    escola, sem overrides por faixa/turma — a rede tem uma régua só) e referências
    AUTO (P90/mediana, sem modo manual). É a garantia estrutural da separação:
    nenhuma configuração local entra aqui, então o resultado é idêntico entre
    escolas com os mesmos dados. ``pontos_dif`` pré-calculado pela mesma regra
    (escola padrão) é reusado; senão é calculado aqui com ``leituras_por_aluno``."""
    if pontos_dif is None:
        from app.services import dificuldade_livro as _dl
        regra = _dl.regra_institucional()
        leituras_por_aluno = leituras_por_aluno or {}
        pontos_dif = {}
        for matricula, turma in matriculas:
            snap_e = elefante.get(matricula.aluno_id)
            pontos_dif[matricula.aluno_id] = regra.pontos_aluno(
                snap_e.livros_por_nivel if snap_e else {}, turma.ano_escolar,
                leituras=leituras_por_aluno.get(matricula.aluno_id))
    refs, k_vol = _referencias_auto(matific, elefante, pontos_dif)
    p_matific, pct_matific = _pesos_institucionais("pesos.matific")
    p_elefante, pct_elefante = _pesos_institucionais("pesos.elefante")
    p_questoes, pct_questoes = _pesos_institucionais("pesos.questoes")
    return (pontos_dif, refs, k_vol, p_matific, pct_matific, p_elefante,
            pct_elefante, p_questoes, pct_questoes)


def _notas_institucionais(matriculas, matific, elefante,
                          leituras_por_aluno=None) -> dict[int, tuple[float, float]]:
    """Nota institucional por aluno = ``(nota_matific, nota_elefante)`` com o
    perfil fixo. É o que a REDE consome (colunas ``*_institucional``). Usado para
    a escola PERSONALIZADA, cuja nota local diverge da institucional; na escola
    padrão a própria nota local já é institucional e este cálculo é dispensado."""
    (pontos_dif, refs, k_vol, p_matific, pct_matific, p_elefante, pct_elefante,
     p_questoes, pct_questoes) = _insumos_institucionais(
        matriculas, matific, elefante, leituras_por_aluno=leituras_por_aluno)
    notas: dict[int, tuple[float, float]] = {}
    for matricula, _turma in matriculas:
        aid = matricula.aluno_id
        nota_m, _ = calcular_matific(matific.get(aid), refs, p_matific, pct_matific, k_vol)
        nota_e, _, _ = calcular_elefante(
            elefante.get(aid), pontos_dif[aid], refs, p_elefante, pct_elefante,
            p_questoes, pct_questoes, k_vol)
        notas[aid] = (nota_m, nota_e)
    return notas


def recalcular_escola(db: Session, escola_id: int) -> int:
    """Recalcula todas as notas e o ranking da escola. Retorna nº de alunos."""
    # PRIMEIRA linha, antes de QUALQUER leitura que entre no cálculo: daqui até
    # o `db.commit()` do fim, esta escola é só desta transação. Sem isso, dois
    # recálculos sobrepostos leem o mesmo estado e gravam um por cima do outro
    # — 500 por uq_nota_aluno_ano quando inserem, e nota errada em silêncio
    # quando atualizam. Transacional: cai sozinha no commit (no-op no SQLite).
    bloquear_escola_para_recalculo(db, escola_id)
    contexto = _carregar_contexto(db, escola_id)
    if contexto is None:
        return 0
    escola, ano, matriculas, matific, elefante, pontos_dif = contexto

    # ===================================================================
    # PERFIL DE SCORING deste recálculo (contexto INTERNO da escola).
    # Padrão Constela  → o note interno É a régua institucional (A3 + pesos
    #                    padrão + auto/linear P90). Ignora a config local.
    # Personalizado    → usa a config da escola (pesos/dificuldade/normalização
    #                    + bônus de leitura na escola). Vale SÓ aqui — a rede
    #                    lê sempre as colunas `*_institucional`, nunca estas.
    # ===================================================================
    personalizado = _scoring_personalizado(db, escola_id)
    if personalizado:
        # Pontos extras por livro lido NA ESCOLA (opcional): soma nos pontos de
        # dificuldade os livros lidos dentro da janela do turno da turma. Feito
        # ANTES das referências para a normalização já considerar o bônus — pela
        # MESMA função que o simulador chama (`pontos_dif_com_bonus`), senão a
        # régua do simulador nasce sem o bônus e o mesmo aluno tem duas notas.
        pontos_dif, bonus_por_aluno = pontos_dif_com_bonus(
            db, escola_id, matriculas, pontos_dif)

        refs, modo, k_vol = _referencias(db, escola_id, matific, elefante, pontos_dif)

        p_matific = obter_pesos(db, escola_id, "pesos.matific")
        p_elefante = obter_pesos(db, escola_id, "pesos.elefante")
        p_questoes = obter_pesos(db, escola_id, "pesos.questoes")
        p_geral = obter_pesos(db, escola_id, "pesos.geral")
        pct_matific = obter_pesos_brutos(db, escola_id, "pesos.matific")
        pct_elefante = obter_pesos_brutos(db, escola_id, "pesos.elefante")
        pct_questoes = obter_pesos_brutos(db, escola_id, "pesos.questoes")
    else:
        # PADRÃO: mesmos insumos do perfil institucional, para nota/posição/
        # detalhes locais baterem EXATAMENTE com as colunas `*_institucional`.
        # `pontos_dif` já veio do contexto pela MESMA regra global v1 (reuso: sem
        # segunda varredura de leituras).
        bonus_por_aluno = {}
        (pontos_dif, refs, k_vol, p_matific, pct_matific, p_elefante,
         pct_elefante, p_questoes, pct_questoes) = _insumos_institucionais(
            matriculas, matific, elefante, pontos_dif=pontos_dif)
        modo = "auto"
        p_geral = _pesos_geral_institucional(db, escola_id)
    # Versão da regra de DIFICULDADE que produziu `pontos_dif` — carimbada em cada
    # Nota (auditoria: qual fórmula gerou este número). A régua legada por faixa
    # só existe no perfil personalizado (override autorizado).
    from app.services import dificuldade_livro as _dl
    versao_dificuldade = _dl.VERSAO_LEGADA if personalizado else _dl.VERSAO_VIGENTE
    # A EXPLICAÇÃO da Nota Geral é DERIVADA dos pesos efetivamente usados, não
    # lida de novo da configuração. Assim ela não tem como divergir da conta: as
    # parcelas exibidas somam 100% e reproduzem a nota. Sem isto, uma rede que só
    # assinou a Leitura gravaria "Matific 100 × 50% + Elefante 70 × 50% = 70" —
    # equação que não fecha, justamente na tela de auditoria da nota (PRD §45).
    # Os pesos são resolvidos POR ALUNO (abaixo), porque a renormalização por
    # dimensão disponível depende de quais plataformas aquela criança usa.

    resultados: list[ResultadoAluno] = []
    for matricula, turma in matriculas:
        aluno = matricula.aluno
        snap_m = matific.get(aluno.id)
        snap_e = elefante.get(aluno.id)

        nota_m, linhas_m = calcular_matific(snap_m, refs, p_matific, pct_matific, k_vol)
        nota_e, linhas_e, det_q = calcular_elefante(
            snap_e, pontos_dif[aluno.id], refs, p_elefante, pct_elefante,
            p_questoes, pct_questoes, k_vol,
        )
        # DIMENSÕES DISPONÍVEIS do aluno: o corte é pela EXISTÊNCIA do snapshot
        # (mesma régua de `rede._medias_por_plataforma`), NUNCA por `nota > 0` —
        # quem abriu a plataforma e ainda leu 0 livros é um zero LEGÍTIMO e tem
        # de pesar. O `or nota > 0` cobre só a nota que nasceu de OUTRA fonte que
        # não o snapshot (o bônus de leitura na escola entra em `pontos_dif`):
        # serve para nunca DESCARTAR uma nota positiva, jamais para excluir um
        # zero de quem usa a plataforma.
        dimensoes = {nome for nome, tem in (
            ("matific", snap_m is not None or nota_m > 0),
            ("elefante", snap_e is not None or nota_e > 0)) if tem}
        p_geral_aluno = pesos_geral_do_aluno(p_geral, dimensoes)
        pct_geral = {chave: round(fracao * 100, 2)
                     for chave, fracao in p_geral_aluno.items() if fracao > 0}
        # MESMA guarda das notas por dimensão (`_nota_0_100`): nota finita em
        # [0, 100]. Valor válido não muda (pesos somam 1 e as notas já estão em
        # [0, 100]); o que ela impede é um peso negativo gravado por engano na
        # configuração virar nota NEGATIVA na coluna legada (e na ordem legada).
        nota_geral = _nota_0_100(
            nota_m * p_geral_aluno.get("matific", 0)
            + nota_e * p_geral_aluno.get("elefante", 0)
        )

        tentativas = snap_e.questoes_tentativas if snap_e else 0
        acertos = snap_e.questoes_acertos if snap_e else 0
        resultados.append(
            ResultadoAluno(
                aluno=aluno,
                ano_escolar=turma.ano_escolar,
                turma_nome=turma.nome,
                nota_matific=nota_m,
                nota_elefante=nota_e,
                nota_geral=nota_geral,
                livros_unicos=snap_e.livros_unicos if snap_e else 0,
                atividades=snap_m.atividades if snap_m else 0,
                pct_acertos=round(acertos / tentativas * 100, 2) if tentativas else 0.0,
                pontos_dificuldade=pontos_dif[aluno.id],
                estrelas=snap_m.estrelas if snap_m else 0,
                pontuacao_media=snap_m.pontuacao_media if snap_m else 0.0,
                # AFERIDO por dimensão = a MESMA noção de "dimensão com dado" do
                # C-01, traduzida para o vocabulário do produto. Uma definição só
                # no motor: se mudar aqui, muda no ranking, na adoção e na lista
                # de "ainda não aferidos" ao mesmo tempo.
                aferido={dim: plat in dimensoes for dim, plat in DIMENSOES.items()},
                dados_dimensao={
                    "leitura": {
                        "livros_unicos": snap_e.livros_unicos if snap_e else 0,
                        "tempo_leitura_min": snap_e.tempo_leitura_min if snap_e else 0,
                        "questoes_tentativas": tentativas,
                        "questoes_acertos": acertos,
                        "pontos_dificuldade": pontos_dif[aluno.id],
                        "versao_dificuldade": versao_dificuldade,
                    },
                    "matematica": {
                        "atividades": snap_m.atividades if snap_m else 0,
                        "estrelas": snap_m.estrelas if snap_m else 0,
                        "pontuacao_media": snap_m.pontuacao_media if snap_m else 0.0,
                    },
                },
                # A data do snapshot ATUAL é o que separa "nota baixa" de "nota
                # velha" — existe no banco desde sempre e nunca chegou a nenhuma
                # tela de aluno.
                snapshot_em={
                    "leitura": _data_iso(snap_e), "matematica": _data_iso(snap_m),
                },
                detalhes={
                    "modo_normalizacao": modo,
                    "referencias": refs,
                    # Registro auditável da correção (PRD §45): referência P90 e a
                    # meia-saturação (k) por indicador de volume, quando aplicadas.
                    "referencia_tipo": ("p90_robusto" if (modo == "auto" and k_vol)
                                        else ("maximo" if modo == "auto" else "manual")),
                    "saturacao": dict(k_vol),
                    "matific": {"indicadores": linhas_m, "nota": nota_m},
                    "elefante": {"indicadores": linhas_e, "questoes": det_q, "nota": nota_e,
                                 "bonus_leitura_escola": round(bonus_por_aluno.get(aluno.id, 0.0), 2),
                                 # Regra de dificuldade que gerou `pontos_dificuldade`.
                                 # `incompleto`: há livros contados mas SEM distribuição
                                 # por nível nem leituras itemizadas — a dificuldade não é
                                 # "zero", é DESCONHECIDA (relatório da turma sem colunas
                                 # de nível); a tela deve dizer isso, não mostrar 0.
                                 "dificuldade": {
                                     "versao": versao_dificuldade,
                                     # Extrato do catálogo (sha256/12 + nº de livros) que
                                     # deu o wordCount — a coluna institucional o usa
                                     # também no perfil personalizado. Determinístico.
                                     "catalogo": _dl.versao_catalogo(),
                                     "incompleto": bool(
                                         snap_e is not None
                                         and int(getattr(snap_e, "livros_unicos", 0) or 0) > 0
                                         and not any((getattr(snap_e, "livros_por_nivel", None) or {}).values())
                                         and not getattr(snap_e, "itemizadas", 0)),
                                     "fonte": getattr(snap_e, "fonte", None) if snap_e else None,
                                 }},
                    # `dimensoes_com_dados` deixa a renormalização auditável: a
                    # tela de explicação mostra a conta com os pesos de fato
                    # usados, e aqui fica registrado POR QUE eles são esses.
                    # LEGADO (ver `_ordenar_por_dimensao`): esta é a única conta
                    # do motor que cruza dimensões e não ordena mais nada.
                    "geral": {"pesos": pct_geral, "nota": nota_geral,
                              "dimensoes_com_dados": sorted(dimensoes),
                              "legado": True},
                },
            )
        )

    # NOTA INSTITUCIONAL (régua fixa da rede), por aluno. Na escola PADRÃO a
    # nota local já É a institucional — reusa direto, sem recalcular. Na escola
    # PERSONALIZADA a local diverge, então computa a institucional à parte. Esta
    # é a ÚNICA nota que a rede pode ler; a `resultado.nota_*` (local) fica no
    # contexto interno da escola.
    if personalizado:
        # A régua da REDE é a v1 global: precisa das leituras itemizadas (uma query).
        ids_pontuados = {m.aluno_id for m, _t in matriculas}
        notas_inst = _notas_institucionais(
            matriculas, matific, elefante,
            leituras_por_aluno=_dl.leituras_por_aluno(db, escola_id, ids_pontuados))
    else:
        notas_inst = {r.aluno.id: (r.nota_matific, r.nota_elefante)
                      for r in resultados}

    # ORDEM OFICIAL: uma por DIMENSÃO, só entre os aferidos dela (spec §2).
    _ordenar_por_dimensao(db, escola_id, escola, resultados)

    # ORDEM LEGADO (`Nota.posicao`, ancorada em `nota_geral`): continua sendo
    # gravada enquanto certificado, cartaz, telão e Top 10 não migrarem para a
    # ordem por dimensão — são vitrines que exigem ordem única e dependem de
    # decisão de produto. Nada NOVO deve passar a lê-la.
    criterios = obter_config(
        db, escola_id, "desempate", "criterios", CRITERIOS_DESEMPATE_PADRAO
    )
    resultados.sort(key=lambda r: _chave_ordenacao(r, criterios))

    # Carrega TODAS as notas do ano numa query só (era 1 SELECT por aluno).
    notas_existentes = {
        n.aluno_id: n for n in db.execute(
            select(Nota).where(Nota.escola_id == escola_id, Nota.ano_letivo == ano)
        ).scalars()
    }
    for posicao, resultado in enumerate(resultados, start=1):
        nota_row = notas_existentes.get(resultado.aluno.id)
        if nota_row is None:
            nota_row = Nota(escola_id=escola_id, aluno_id=resultado.aluno.id, ano_letivo=ano)
            db.add(nota_row)
        nota_row.nota_matific = resultado.nota_matific
        nota_row.nota_elefante = resultado.nota_elefante
        # Colunas INSTITUCIONAIS — a régua da rede, imune à config local.
        nm_inst, ne_inst = notas_inst.get(resultado.aluno.id, (0.0, 0.0))
        nota_row.nota_matific_institucional = nm_inst
        nota_row.nota_elefante_institucional = ne_inst
        nota_row.nota_geral = resultado.nota_geral
        nota_row.posicao = posicao
        nota_row.aferido_leitura = bool(resultado.aferido.get("leitura"))
        nota_row.aferido_matematica = bool(resultado.aferido.get("matematica"))
        nota_row.posicao_leitura = resultado.posicao_dimensao.get("leitura")
        nota_row.posicao_matematica = resultado.posicao_dimensao.get("matematica")
        # CARIMBO INSTITUCIONAL (visível em SQL via JSON path): prova que as
        # colunas `*_institucional` desta linha foram calculadas por este motor.
        # A rede só agrega notas carimbadas — uma linha antiga (migração 0028 com
        # default 0,0 e sem backfill) NÃO vira "zero" na média: fica PENDENTE de
        # recálculo até `scripts.recalcular_institucional --pendentes`.
        # (sem timestamp aqui: o conteúdo da Nota tem de ser DETERMINÍSTICO —
        # recalcular duas vezes não pode gerar UPDATE; o instante fica em
        # `Nota.calculada_em`.)
        nota_row.detalhes = {**resultado.detalhes, **carimbo_institucional(personalizado)}

    db.commit()
    return len(resultados)
