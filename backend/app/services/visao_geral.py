"""VISÃO GERAL da escola e ATIVIDADE SEMANAL — consultas SÓ DE LEITURA para a tela
inicial da identidade visual v2 (``docs/design/IDENTIDADE-VISUAL-V2.md`` §5).

Não existe aqui uma régua nova. Cada número sai das MESMAS funções do Relatório por
Período (``services/relatorios_periodo``), que por sua vez são as da premiação:

* coorte  = ``relatorios_periodo._coorte`` — alunos ATIVOS matriculados no ano letivo,
  recortados pelas turmas permitidas do usuário (o professor vê só as dele);
* livros e tempo de leitura = ``relatorios_periodo._elefante`` (``Leitura.data``, o par
  de "Mais Livros"/"Mais Tempo"; releitura não soma livro; o tempo é um PISO);
* atividades do Matific = ``matific_destaque.ganho_no_periodo`` (diferença entre
  retratos, a regra oficial das premiações), com a declaração de cobertura de
  ``relatorios_periodo._intervalo_matific``/``_cobertura``.

O QUE É "ALUNO ATIVO" (a mesma regra nas duas rotas):
* Leitura: leu ou releu ao menos um livro na janela — ``Leitura.data`` OU evento de
  leitura do espelho (``EventoAluno.ocorrido_em``) dentro dela, os dois eixos de
  ``relatorios_periodo._elefante``.
* Matemática: GANHO > 0 de atividades na janela. Ter retrato não é ter atividade: toda
  coleta grava retrato de todo aluno, e contar "tem retrato" (o viés de
  ``relatorios_periodo.gerar`` em ``alunos.com_atividade``) faria a escola parecer
  inteira ativa. Ganho de estrelas sem atividade não existe (``limitar_estrelas``).
* Ativos = a união dos dois conjuntos (só das plataformas contratadas e com dado).

AUSÊNCIA NÃO É ZERO. Sem coleta, o número é ``None`` (lacuna), nunca 0:
* Elefante: a janela só tem número se a fonte já foi VISTA depois do início dela
  (:func:`_elefante_visto`). ``Leitura.data`` é a data da leitura na plataforma, e uma
  coleta posterior traz as datas passadas — então semana antiga coletada depois tem
  número; semana posterior à última coleta não tem, nem semana fechada vista só em
  parte (a coleta parou no meio dela). No período da Visão Geral, o número visto em
  parte SAI (é o que já se sabe), mas declarado: ``leitura.cobertura = "parcial"`` e
  ``leitura.coletado_ate`` dizem até que dia ele conta — a mesma régua do ``em_dia``
  que já desligava a comparação.
* Matific: a janela só tem número se ao menos um aluno tem um INTERVALO medido nela (duas
  coletas, ou o zero do contador no início do ano) — a mesma régua do
  ``sem_intervalo`` do relatório. Uma coleta só não mede nada. Na semana, só conta o
  aluno com a base na borda dela (sem isso, a atividade da semana sem coleta migraria
  para a seguinte).

COMPARAÇÃO (decisão D6 do documento de design): a MESMA quantidade de dias decorridos a
partir do início do período anterior — comparar um bimestre em curso com o anterior
inteiro enganaria. Só existe dentro do mesmo ano letivo (o contador do Matific é do ano)
e só sai quando as duas janelas estão medidas por inteiro; senão ``None``. Na Leitura, a
quantidade é a dos dias de fato COBERTOS pela coleta (a das 0h10 mede o dia anterior).

Nada é gravado (nem auditoria: é tela de acompanhamento sem dado individual) e nenhuma
lista de alunos sai daqui.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from itertools import chain

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Escola, EventoAluno, Leitura, SnapshotElefante, SnapshotMatific
from app.services import bimestres, matific_destaque, periodos
from app.services import relatorios_periodo as rp
from app.services.evolucao import sem_ajustes_superados_matific

# Os presets de ``periodos`` que têm as DUAS pontas: "tudo" não tem período, e
# "personalizado" exige datas que esta rota não recebe.
PRESETS = tuple(p for p in periodos.PRESETS if p not in ("tudo", "personalizado"))
SEMANAS_MIN, SEMANAS_MAX = 1, 26

# Período anterior EQUIVALENTE de cada preset (os demais não têm comparação).
_ANTERIOR = {
    "bimestre": "bimestre_anterior",
    "bimestre_2": "bimestre_1",
    "bimestre_3": "bimestre_2",
    "bimestre_4": "bimestre_3",
    "mes": "mes_anterior",
    "semana": "semana_anterior",
}
# Folga da leitura dos retratos do Matific em volta do ano letivo: o recorte exato é o
# de ``ganho_no_periodo`` (que descarta o que é de fora do ano); a folga só garante que
# o SQL nunca corte um retrato que a regra oficial veria.
_FOLGA_ANO = timedelta(days=1)


class PedidoInvalido(Exception):
    """Pedido que não se sustenta (período ou número de semanas)."""


# --------------------------------------------------------------------------- datas
def _ini(dia: date) -> datetime:
    return datetime.combine(dia, time.min)


def _fim(dia: date) -> datetime:
    return datetime.combine(dia, time(23, 59, 59, 999999))


def _iso_utc(momento: datetime | None) -> str | None:
    """Instante de coleta (gravado em UTC; naive = UTC) em ISO com o fuso explícito."""
    if momento is None:
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(timezone.utc).isoformat()


def _ano(escola: Escola, hoje: date) -> int:
    return escola.ano_letivo_ativo or hoje.year


# ------------------------------------------------------------------------ Elefante
@dataclass(frozen=True)
class _Visto:
    """Até onde o Elefante desta coorte já foi visto."""
    ate: datetime | None            # Brasília, sem fuso
    ultima_coleta: datetime | None  # UTC, sem fuso (o retrato mais recente)


def _elefante_visto(db: Session, escola_id: int, coorte: dict[int, dict]) -> _Visto:
    """O último instante que o Elefante desta coorte já cobriu.

    É o maior entre: a coleta mais recente (retrato, gravado em UTC, levado a Brasília
    e recuado de ``TOLERANCIA_BORDA`` — a coleta das 0h10 mede o dia ANTERIOR, a mesma
    régua do relatório), a leitura mais recente e o evento de leitura mais recente (uma
    leitura datada em T prova que a fonte já foi vista depois de T). ``None`` = esta
    coorte nunca teve dado do Elefante."""
    if not coorte:
        return _Visto(None, None)
    ids = list(coorte)
    coleta = db.execute(
        select(func.max(SnapshotElefante.data_referencia))
        .where(SnapshotElefante.escola_id == escola_id,
               SnapshotElefante.aluno_id.in_(ids))).scalar()
    leitura = db.execute(
        select(func.max(Leitura.data))
        .where(Leitura.escola_id == escola_id, Leitura.aluno_id.in_(ids))).scalar()
    evento = db.execute(
        select(func.max(EventoAluno.ocorrido_em))
        .where(EventoAluno.escola_id == escola_id,
               EventoAluno.plataforma == "elefante",
               EventoAluno.tipo_evento == "leitura",
               EventoAluno.aluno_id.in_(ids))).scalar()
    candidatos = [rp._sem_tz(m) for m in (leitura, evento) if m is not None]
    if coleta is not None:
        coleta = rp._sem_tz(coleta)
        candidatos.append(rp._br(coleta) - rp.TOLERANCIA_BORDA)
    return _Visto(max(candidatos) if candidatos else None, coleta)


def _leitura(db: Session, escola_id: int, coorte: dict[int, dict], janela: rp.Janela,
             visto: _Visto) -> dict | None:
    """Livros novos, tempo e quem leu na janela — ``None`` se o Elefante desta coorte
    ainda não foi visto depois do início dela (sem dado, nunca zero)."""
    if visto.ate is None or visto.ate < janela.inicio:
        return None
    bloco, por_aluno = rp._elefante(db, escola_id, coorte, janela)
    return {"livros": bloco.livros_novos, "tempo_min": bloco.tempo_min,
            "ativos": set(por_aluno)}


def _leitores_por_semana(db: Session, escola_id: int, coorte: dict[int, dict],
                         inicios: list[date]) -> list[set[int]]:
    """Quem leu em cada semana (segunda a domingo), nas DUAS consultas da faixa toda.

    Os mesmos campos e filtros de ``relatorios_periodo._elefante`` — ``Leitura.data`` e
    o evento de leitura do Elefante (``EventoAluno.ocorrido_em``) —, agrupados por semana
    aqui em vez de uma ida ao banco por semana."""
    por_semana: list[set[int]] = [set() for _ in inicios]
    if not coorte:
        return por_semana
    ids = list(coorte)
    de, ate = _ini(inicios[0]), _fim(inicios[-1] + timedelta(days=6))
    leituras = db.execute(
        select(Leitura.aluno_id, Leitura.data)
        .where(Leitura.escola_id == escola_id, Leitura.aluno_id.in_(ids),
               Leitura.data >= de, Leitura.data <= ate)).all()
    eventos = db.execute(
        select(EventoAluno.aluno_id, EventoAluno.ocorrido_em)
        .where(EventoAluno.escola_id == escola_id,
               EventoAluno.plataforma == "elefante",
               EventoAluno.tipo_evento == "leitura",
               EventoAluno.aluno_id.in_(ids),
               EventoAluno.ocorrido_em >= de, EventoAluno.ocorrido_em <= ate)).all()
    for aluno_id, quando in chain(leituras, eventos):
        if quando is None:
            continue
        indice = (rp._sem_tz(quando).date() - inicios[0]).days // 7
        if 0 <= indice < len(inicios):
            por_semana[indice].add(aluno_id)
    return por_semana


# ------------------------------------------------------------------------- Matific
@dataclass
class _SeriesMatific:
    """Retratos do Matific por aluno, em ordem, com as chaves de data para recortar."""
    series: dict[int, list]
    chaves: dict[int, list[datetime]]
    ultima_coleta: datetime | None


def _series_matific(db: Session, escola_id: int, coorte: dict[int, dict],
                    ano: int) -> _SeriesMatific:
    """UMA consulta, só as colunas que a regra oficial lê, só em volta do ano letivo
    (o contador do Matific é do ano: ``ganho_no_periodo`` descarta o resto).

    Sem o ajuste manual que uma coleta posterior do mesmo ano desmentiu
    (``matific_destaque.sem_ajustes_superados``): a mesma série das premiações e do
    Relatório por Período. A folga em volta do ano não muda isso — o ajuste só é
    desmentido por coleta do MESMO ano, que está inteiro na consulta."""
    if not coorte:
        return _SeriesMatific({}, {}, None)
    ini_ano, fim_ano = matific_destaque.janela_ano_letivo(ano)
    linhas = db.execute(
        select(SnapshotMatific.aluno_id, SnapshotMatific.id,
               SnapshotMatific.data_referencia, SnapshotMatific.atividades,
               SnapshotMatific.estrelas, SnapshotMatific.importacao_id)
        .where(SnapshotMatific.escola_id == escola_id,
               SnapshotMatific.aluno_id.in_(list(coorte)),
               SnapshotMatific.data_referencia >= ini_ano - _FOLGA_ANO,
               SnapshotMatific.data_referencia <= fim_ano + _FOLGA_ANO)
        .order_by(SnapshotMatific.aluno_id, SnapshotMatific.data_referencia,
                  SnapshotMatific.id)).all()
    series: dict[int, list] = {}
    for linha in linhas:
        series.setdefault(linha.aluno_id, []).append(linha)
    series = sem_ajustes_superados_matific(db, escola_id, series)
    chaves ={aid: [matific_destaque._data(s) for s in serie]
              for aid, serie in series.items()}
    ultima = db.execute(
        select(func.max(SnapshotMatific.data_referencia))
        .where(SnapshotMatific.escola_id == escola_id,
               SnapshotMatific.aluno_id.in_(list(coorte)))).scalar()
    return _SeriesMatific(series, chaves, rp._sem_tz(ultima) if ultima else None)


def _ganho(serie: list, chaves: list[datetime], inicio: datetime, fim: datetime,
           ano: int):
    """``matific_destaque.ganho_no_periodo`` sobre o RECORTE mínimo da série: o último
    retrato antes do início + os de dentro da janela. O resultado é o MESMO da série
    inteira — a regra só lê a base (o último retrato do ano antes do início efetivo) e
    os retratos de dentro; o resto ela descarta — e a conta deixa de reler o ano todo
    a cada semana. Nenhum retrato dentro da janela = ``None`` (ausência), como lá."""
    lo = bisect_left(chaves, inicio)
    hi = bisect_right(chaves, fim)
    if lo == hi:
        return None
    return matific_destaque.ganho_no_periodo(serie[max(0, lo - 1):hi], inicio, fim, ano)


@dataclass
class _Matematica:
    atividades: int | None
    ativos: set[int] | None
    cobertura: str          # "completa" | "parcial" | "sem_dado"


def _matematica(dados: _SeriesMatific, coorte: dict[int, dict], janela: rp.Janela,
                ano: int, hoje: date) -> _Matematica:
    """Atividades e ativos (ganho > 0) do Matific na janela, com a cobertura.

    O número é o da regra oficial (o mesmo total de ``relatorios_periodo._matific``).
    A cobertura traduz a do relatório para três estados:
      * ``sem_dado``  — ninguém tem intervalo medido (sem coleta na janela, ou uma
        coleta só): número ``None``;
      * ``parcial``   — a cobertura do relatório é ``parcial`` (conta que começou
        depois do início, aluno com uma coleta só), OU há aluno que era coletado no
        ano e não tem coleta na janela (a coleta parou para ele), OU a coleta mais
        recente usada é anterior à véspera do fim efetivo (coleta parada), OU a base
        de algum aluno é bem anterior ao início (o ganho inclui atividade de fora);
      * ``completa``  — fora isso. Uma tolerância de um dia: a coleta das 0h10 mede o
        dia anterior."""
    ini_ano = matific_destaque.janela_ano_letivo(ano)[0]
    atividades = 0
    ativos: set[int] = set()
    intervalos: list[dict] = []
    bases: list[datetime] = []      # UTC, de quem tem intervalo (sem a base nula)
    uma_coleta = interrompidos = 0
    atuais: list[datetime] = []
    for aid in coorte:
        serie, chaves = dados.series.get(aid, []), dados.chaves.get(aid, [])
        ganho = _ganho(serie, chaves, janela.inicio, janela.fim, ano)
        if ganho is None:
            if bisect_left(chaves, janela.inicio) > bisect_left(chaves, ini_ano):
                interrompidos += 1    # coletado no ano ANTES da janela, nada nela
            continue
        if ganho.data_atual is not None:
            atuais.append(ganho.data_atual)
            intervalo = rp._intervalo_matific(janela, ini_ano, ganho)
            if intervalo is None:
                uma_coleta += 1       # uma coleta só: a regra oficial dá 0
            else:
                intervalos.append(intervalo)
                if intervalo["base"] is not None:
                    bases.append(intervalo["base"])
        feitas = int(ganho.atividades or 0)
        atividades += feitas
        if feitas > 0:
            ativos.add(aid)
    cobertura = rp._cobertura(janela, hoje, intervalos, uma_coleta,
                              regra="oficial_matific")
    if not intervalos or cobertura is None or cobertura["status"] == "sem_intervalo":
        return _Matematica(None, None, "sem_dado")
    ultima = max(rp._br(rp._sem_tz(a)) for a in atuais).date()
    parado = ultima < rp._fim_efetivo(janela, hoje) - timedelta(days=1)
    # ``regra_oficial`` não verifica a borda do início: base de semanas antes faz o
    # ganho somar atividade de fora (e liberaria a comparação). Aceita-se a coleta da
    # véspera (mede o dia anterior) mais a ``TOLERANCIA_BORDA``; a conta não muda.
    limite_base = janela.inicio - (rp.TOLERANCIA_BORDA + timedelta(days=1))
    base_antiga = any(rp._br(b) < limite_base for b in bases)
    if cobertura["status"] == "parcial" or interrompidos or parado or base_antiga:
        return _Matematica(atividades, ativos, "parcial")
    return _Matematica(atividades, ativos, "completa")


def _ativos_matific_semana(dados: _SeriesMatific, coorte: dict[int, dict],
                           janela: rp.Janela, ano: int) -> int | None:
    """Alunos com ganho > 0 na semana; ``None`` se nenhum aluno tem intervalo medido
    nela (semana sem coleta, ou com uma coleta só) — lacuna, nunca 0.

    Só está medido quem tem a base NA BORDA da semana (a coleta da véspera da segunda,
    mais a ``TOLERANCIA_BORDA``), ou a base nula da abertura do ano letivo. Base mais
    antiga quer dizer semana sem coleta antes: o ganho levaria a atividade da lacuna
    para esta semana. Esse aluno fica fora da conta (nem medido, nem ativo)."""
    ini_ano = matific_destaque.janela_ano_letivo(ano)[0]
    limite_base = janela.inicio - (rp.TOLERANCIA_BORDA + timedelta(days=1))
    medida = False
    ativos = 0
    for aid in coorte:
        ganho = _ganho(dados.series.get(aid, []), dados.chaves.get(aid, []),
                       janela.inicio, janela.fim, ano)
        if ganho is None:
            continue
        if (ganho.data_base is not None
                and rp._br(rp._sem_tz(ganho.data_base)) < limite_base):
            continue        # base antiga: o ganho não é desta semana
        if (ganho.data_atual is not None
                and rp._intervalo_matific(janela, ini_ano, ganho) is not None):
            medida = True
        if int(ganho.atividades or 0) > 0:
            ativos += 1
    return ativos if medida else None


# ---------------------------------------------------------------------- comparação
def _rotulo_comparacao(anterior: str, inicio: date) -> str:
    if anterior.startswith("bimestre"):
        numero = (bimestres.bimestre_da_data(inicio)
                  if bimestres.ano_com_calendario(inicio.year) else None)
        return (f"mesmo ponto do {bimestres.rotulo(numero)}" if numero
                else "mesmo ponto do bimestre anterior")
    if anterior == "mes_anterior":
        return "mesmo ponto do mês anterior"
    return "mesmo ponto da semana anterior"


def _comparacao(preset: str, janela: rp.Janela, ano: int, hoje: date,
                dias_decorridos: int) -> rp.Janela | None:
    """Os ``dias_decorridos`` primeiros dias do período anterior equivalente.

    ``None`` quando o preset não tem anterior equivalente, quando o período ainda nem
    começou, ou quando o anterior cai fora do ano letivo (o 1º bimestre não se compara
    com o 4º do ano passado: o contador do Matific zera na virada)."""
    anterior = _ANTERIOR.get(preset)
    if anterior is None or dias_decorridos <= 0:
        return None
    inicio, fim, _ = periodos.resolver(anterior, hoje, ano)
    if inicio is None or fim is None:
        return None
    ini_ano, fim_ano = matific_destaque.janela_ano_letivo(ano)
    if inicio < ini_ano or fim > fim_ano or inicio >= janela.inicio:
        return None
    ultimo = min(inicio.date() + timedelta(days=dias_decorridos - 1), fim.date())
    return rp.Janela(preset=anterior, inicio=inicio, fim=_fim(ultimo),
                     rotulo=_rotulo_comparacao(anterior, inicio.date()))


# --------------------------------------------------------------------------- rotas
def visao_geral(db: Session, escola: Escola, *, preset: str, modulos: set[str],
                turma_ids: list[int] | None, hoje: date) -> dict:
    """Indicadores do período e da MESMA janela de dias do período anterior."""
    if preset not in PRESETS:
        raise PedidoInvalido(
            f"Período {preset!r} não existe nesta tela. Os aceitos são: "
            + ", ".join(PRESETS) + ".")
    ano = _ano(escola, hoje)
    try:
        janela = rp.resolver_janela(preset, ano, hoje=hoje)
    except rp.RelatorioInvalido as exc:
        raise PedidoInvalido(str(exc)) from exc
    inicio, fim = janela.inicio.date(), janela.fim.date()
    dias_total = (fim - inicio).days + 1
    dias_decorridos = max(0, min((min(hoje, fim) - inicio).days + 1, dias_total))
    comparacao = _comparacao(preset, janela, ano, hoje, dias_decorridos)
    coorte = rp._coorte(db, escola.id, ano, turma_ids=turma_ids)
    leitura_ok, mat_ok = "leitura" in modulos, "matematica" in modulos

    atuais: dict[str, set[int]] = {}
    anteriores: dict[str, set[int]] = {}
    coletas: list[datetime] = []

    leitura = {"contratado": leitura_ok, "livros": None, "livros_anterior": None,
               "tempo_min": None, "tempo_min_anterior": None,
               "cobertura": "sem_dado", "coletado_ate": None}
    ativos_leitura = None
    if leitura_ok:
        visto = _elefante_visto(db, escola.id, coorte)
        if visto.ultima_coleta is not None:
            coletas.append(visto.ultima_coleta)
        if visto.ate is not None:
            # Até onde a leitura destes alunos já foi vista (nunca depois de hoje).
            leitura["coletado_ate"] = min(visto.ate.date(), hoje).isoformat()
        agora = _leitura(db, escola.id, coorte, janela, visto)
        if agora is not None:
            leitura["livros"], leitura["tempo_min"] = agora["livros"], agora["tempo_min"]
            ativos_leitura = len(agora["ativos"])
            atuais["leitura"] = agora["ativos"]
            # A comparação só é justa com a fonte em dia: com a coleta parada, o
            # período atual perde os últimos dias e o anterior sai inteiro.
            em_dia = visto.ate.date() >= rp._fim_efetivo(janela, hoje) - timedelta(days=1)
            # COBERTURA da Leitura: a MESMA régua do ``em_dia``. Coleta parada no meio
            # do período = "parcial" — os números contam só até ``coletado_ate`` e não
            # são o total do período (o Matific já declarava isso; a Leitura não).
            leitura["cobertura"] = "completa" if em_dia else "parcial"
            # Em dia ainda aceita a véspera (a coleta das 0h10 mede o dia anterior):
            # o período atual pode ter N-1 dias vistos. O anterior mede os MESMOS dias
            # cobertos, não os N decorridos — senão 1 livro/dia sai 1 × 2 (▼50%).
            # Esta faixa pode ter um dia a menos que ``comparacao`` (a da resposta,
            # que é a geral e vale para o Matific); o contrato não tem campo para ela.
            dias_leitura = min(dias_decorridos,
                               (min(hoje, visto.ate.date()) - inicio).days + 1)
            comp_leitura = _comparacao(preset, janela, ano, hoje, dias_leitura)
            antes = (_leitura(db, escola.id, coorte, comp_leitura, visto)
                     if comp_leitura is not None and em_dia else None)
            if antes is not None:
                leitura["livros_anterior"] = antes["livros"]
                leitura["tempo_min_anterior"] = antes["tempo_min"]
                anteriores["leitura"] = antes["ativos"]

    matematica = {"contratado": mat_ok, "atividades": None, "atividades_anterior": None,
                  "cobertura": "sem_dado"}
    ativos_matematica = None
    if mat_ok:
        dados = _series_matific(db, escola.id, coorte, ano)
        if dados.ultima_coleta is not None:
            coletas.append(dados.ultima_coleta)
        agora_m = _matematica(dados, coorte, janela, ano, hoje)
        matematica["cobertura"] = agora_m.cobertura
        if agora_m.ativos is not None:
            matematica["atividades"] = agora_m.atividades
            ativos_matematica = len(agora_m.ativos)
            atuais["matematica"] = agora_m.ativos
            if comparacao is not None and agora_m.cobertura == "completa":
                antes_m = _matematica(dados, coorte, comparacao, ano, hoje)
                if antes_m.cobertura == "completa":
                    matematica["atividades_anterior"] = antes_m.atividades
                    anteriores["matematica"] = antes_m.ativos

    ativos = len(set().union(*atuais.values())) if atuais else None
    # A comparação de ativos só vale com as MESMAS plataformas medidas nas duas janelas.
    # O conjunto da Leitura vem da faixa dos dias cobertos (``comp_leitura``).
    ativos_anterior = (len(set().union(*anteriores.values()))
                       if atuais and set(anteriores) == set(atuais) else None)
    return {
        "periodo": {"chave": preset, "rotulo": janela.rotulo,
                    "inicio": inicio.isoformat(), "fim": fim.isoformat(),
                    "dias_decorridos": dias_decorridos, "dias_total": dias_total},
        "comparacao": ({"rotulo": comparacao.rotulo,
                        "inicio": comparacao.inicio.date().isoformat(),
                        "fim": comparacao.fim.date().isoformat()}
                       if comparacao is not None else None),
        "alunos": {"total": len(coorte), "ativos": ativos,
                   "ativos_anterior": ativos_anterior,
                   "ativos_leitura": ativos_leitura,
                   "ativos_matematica": ativos_matematica},
        "leitura": leitura,
        "matematica": matematica,
        # A tela só é tão atual quanto a fonte MAIS ATRASADA entre as contratadas.
        "atualizado_em": _iso_utc(min(coletas)) if coletas else None,
    }


def _pct(alunos: int | None, denominador: int) -> float | None:
    if alunos is None or not denominador:
        return None
    return round(alunos / denominador * 100, 1)


def atividade_semanal(db: Session, escola: Escola, *, semanas: int, modulos: set[str],
                      turma_ids: list[int] | None, hoje: date) -> dict:
    """Percentual da coorte com atividade em cada semana (segunda a domingo), por
    plataforma, em ordem cronológica; a última é a semana corrente (parcial)."""
    if not (SEMANAS_MIN <= semanas <= SEMANAS_MAX):
        raise PedidoInvalido(
            f"Peça de {SEMANAS_MIN} a {SEMANAS_MAX} semanas (pedido: {semanas}).")
    ano = _ano(escola, hoje)
    coorte = rp._coorte(db, escola.id, ano, turma_ids=turma_ids)
    denominador = len(coorte)
    leitura_ok, mat_ok = "leitura" in modulos, "matematica" in modulos
    segunda = hoje - timedelta(days=hoje.weekday())
    inicios = [segunda - timedelta(weeks=k) for k in range(semanas - 1, -1, -1)]

    visto = _elefante_visto(db, escola.id, coorte) if leitura_ok else _Visto(None, None)
    leitores = (_leitores_por_semana(db, escola.id, coorte, inicios)
                if visto.ate is not None else [set() for _ in inicios])
    dados = _series_matific(db, escola.id, coorte, ano) if mat_ok else None

    saida = []
    for indice, dia in enumerate(inicios):
        janela = rp.Janela(preset="semana", inicio=_ini(dia),
                           fim=_fim(dia + timedelta(days=6)), rotulo="semana")
        # Semana fechada só tem número se o Elefante foi visto até o domingo dela (a
        # coleta das 0h10 de segunda mede o domingo): parada no meio, é lacuna — o
        # número de parte da semana não é o da semana. A corrente segue "em curso"
        # (pode crescer até domingo) com o que já foi visto, como a Visão Geral.
        corrente = indice == len(inicios) - 1
        ultimo_dia = min(dia + timedelta(days=6), hoje - timedelta(days=1))
        vista = (visto.ate is not None and visto.ate >= janela.inicio
                 and (corrente or visto.ate.date() >= ultimo_dia))
        leitura_alunos = len(leitores[indice]) if vista else None
        matematica_alunos = (_ativos_matific_semana(dados, coorte, janela, ano)
                             if dados is not None else None)
        saida.append({
            "inicio": dia.isoformat(),
            "fim": (dia + timedelta(days=6)).isoformat(),
            "leitura_alunos": leitura_alunos,
            "leitura_pct": _pct(leitura_alunos, denominador),
            "matematica_alunos": matematica_alunos,
            "matematica_pct": _pct(matematica_alunos, denominador),
        })

    recorte = " das suas turmas" if turma_ids is not None else ""
    observacao = (
        "Aluno ativo na semana: na Leitura, leu ou releu ao menos um livro no Elefante "
        "Letrado; na Matemática, concluiu ao menos uma atividade nova no Matific "
        "(diferença entre coletas). O percentual é sobre "
        f"{denominador} aluno{'s' if denominador != 1 else ''} ativo"
        f"{'s' if denominador != 1 else ''} matriculado{'s' if denominador != 1 else ''} "
        f"no ano letivo {ano}{recorte}. Semana sem coleta fica vazia (lacuna), nunca "
        "zero; na Leitura, também a semana já encerrada que foi coletada só em parte; "
        "a última semana ainda está em andamento.")
    return {"denominador": denominador, "leitura_contratado": leitura_ok,
            "matematica_contratado": mat_ok, "observacao": observacao,
            "semanas": saida}
