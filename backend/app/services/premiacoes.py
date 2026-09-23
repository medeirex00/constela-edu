"""Premiações por PERÍODO (PRD — premiações da escola).

Calcula os vencedores de cada categoria usando EXCLUSIVAMENTE os dados do
intervalo escolhido — leituras (com data real, Fase 1) e o GANHO do Matific
dentro do período. Premiações justas: quem só tem dados fora do intervalo não
pontua, e o período mostrado é o período calculado.

Camada de PREMIAÇÃO — NÃO altera o scoring oficial (pesos, A3, P90, notas).

"MELHOR MATEMÁTICA" — DECISÃO DO DONO (2026-09-15), que substitui a de
2026-09-01 (nota oficial do estado do período):

  * vale só o que foi feito DENTRO do período, medido por snapshots do ANO
    LETIVO (um acumulado de dez/2025 nunca vira "setembro/2026");
  * o critério é a MÉDIA AJUSTADA DE ESTRELAS POR ATIVIDADE: estrelas do
    período ÷ (atividades do período + 20% da mediana de atividades da coorte),
    escala 0 a 5 — a regra inteira mora em ``services.matific_destaque``;
  * a régua (a mediana) é a da ESCOLA INTEIRA: a coorte completa de alunos ativos
    matriculados no ano letivo. Turma, professor e turno só decidem QUEM APARECE
    no pódio; a nota de cada criança é a mesma em qualquer recorte.

Turno (manhã/tarde/noite) é o eixo do PERÍODO ESCOLAR, ORTOGONAL ao PERÍODO
TEMPORAL (datas). Com ``por_turno`` os pódios saem quebrados por ``Turma.turno``,
reusando os valores já calculados sobre a escola inteira.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (Aluno, Escola, Leitura, Livro, Matricula, SnapshotElefante,
                        SnapshotMatific, Turma)
from app.services import dificuldade_livro, matific_destaque, scoring
from app.services import turnos as svc_turnos
from app.services.evolucao import _series_por_aluno


def _ordenar(valores: dict[int, float], alunos: dict[int, dict],
             desempate: dict[int, tuple] | None = None) -> list[tuple[int, float]]:
    """A ORDEM da premiação — FONTE ÚNICA. Só quem tem valor > 0, pelo valor
    BRUTO.

    O arredondamento (2 casas) é só de exibição: ordenar pelo arredondado
    empataria 3,964 com 3,961 e entregaria a medalha ao desempate. ``desempate``
    opcional é uma cascata secundária por aluno (ex.: estrelas → atividades no
    Matific); depois vem o nome (casefold) e o ``aluno_id``, para a ordem ser
    determinística e estável.

    O Top 5 e o ranking completo saem DESTA lista: o ranking é o mesmo pódio com
    mais linhas, nunca uma segunda ordenação. Mudar o critério é mudar aqui — e
    só aqui."""
    candidatos = [
        (aid, float(valor)) for aid, valor in valores.items()
        if aid in alunos and valor is not None and valor > 0
    ]
    candidatos.sort(key=lambda par: (
        -par[1],
        *(tuple(-v for v in desempate.get(par[0], ())) if desempate else ()),
        alunos[par[0]]["nome"].casefold(),
        par[0],
    ))
    return candidatos


def _itens(ordenados: list[tuple[int, float]], alunos: dict[int, dict], limite: int,
           extras: dict[int, dict] | None = None) -> list[dict]:
    """Os ``limite`` primeiros da ordem, com a POSIÇÃO REAL da premiação (1, 2,
    3…) — pedir 50 em vez de 5 estende a MESMA lista, sem renumerar nada.
    ``extras`` acrescenta campos de auditoria ao item."""
    itens: list[dict] = []
    for posicao, (aid, valor) in enumerate(ordenados[:limite], start=1):
        item = {"aluno_id": aid, "nome": alunos[aid]["nome"],
                "turma": alunos[aid]["turma"], "valor": round(valor, 2),
                "posicao": posicao}
        if extras and aid in extras:
            item.update(extras[aid])
        itens.append(item)
    return itens


def _podio(valores: dict[int, float], alunos: dict[int, dict], limite: int = 5,
           desempate: dict[int, tuple] | None = None,
           extras: dict[int, dict] | None = None) -> list[dict]:
    """Top N da premiação: ``_ordenar`` + ``_itens`` (mesma ordem, mesma posição)."""
    return _itens(_ordenar(valores, alunos, desempate), alunos, limite, extras)


def _alunos_ativos(db: Session, escola_id: int, ano: int,
                   turma_id: int | None,
                   turma_ids: list[int] | None = None) -> dict[int, dict]:
    consulta = (
        select(Aluno.id, Aluno.nome, Turma.nome, Turma.id, Turma.ano_escolar, Turma.turno)
        .join(Matricula, Matricula.aluno_id == Aluno.id)
        .join(Turma, Matricula.turma_id == Turma.id)
        .where(Aluno.escola_id == escola_id, Aluno.status == "ativo",
               Matricula.ano_letivo == ano)
    )
    if turma_id:
        consulta = consulta.where(Turma.id == turma_id)
    if turma_ids is not None:  # professor: só as turmas designadas a ele
        consulta = consulta.where(Turma.id.in_(turma_ids))
    return {aid: {"nome": nome, "turma": turma, "turma_id": tid,
                  "ano_escolar": serie, "turno": turno}
            for aid, nome, turma, tid, serie, turno in db.execute(consulta).all()}


def _recorte(coorte: dict[int, dict], turma_id: int | None,
             turma_ids: list[int] | None) -> dict[int, dict]:
    """Quem APARECE nos pódios: o mesmo corte que ``_alunos_ativos`` faria no
    banco (turma escolhida e, para o professor, só as turmas dele), aplicado
    sobre a coorte já carregada — a régua continua sendo a da escola inteira."""
    permitidas = set(turma_ids) if turma_ids is not None else None
    return {aid: info for aid, info in coorte.items()
            if (not turma_id or info["turma_id"] == turma_id)
            and (permitidas is None or info["turma_id"] in permitidas)}


def _leitura_no_periodo(db: Session, escola_id: int, alunos: dict[int, dict],
                        inicio: datetime | None, fim: datetime | None):
    """Livros, pontos de dificuldade e tempo somados por aluno no intervalo.
    Cada leitura vale o que a FONTE ÚNICA de dificuldade diz (v1 global: nível ×
    ajuste do livro × série; ou a régua legada da escola personalizada) — a MESMA
    regra do ranking anual, senão o 'Melhor Leitor' coroaria a criança errada.
    Valores BRUTOS por aluno (sem régua da coorte): o recorte não os altera."""
    regra = dificuldade_livro.regra_da_escola(db, escola_id)
    livros: dict[int, float] = {}
    pontos: dict[int, float] = {}
    tempo: dict[int, float] = {}
    if not alunos:
        return livros, pontos, tempo
    # NÍVEL CONGELADO da leitura; nulo (leitura anterior a esta versão) cai no
    # nível ATUAL do livro. Mesma ``coalesce`` do motor e do /ranking/leitura:
    # renivelar um livro não muda o pódio de um período já encerrado.
    nivel_efetivo = func.coalesce(Leitura.nivel_codigo, Livro.nivel_codigo)
    consulta = (
        select(Leitura.aluno_id, nivel_efetivo, Leitura.tempo_leitura_min,
               Livro.titulo, Livro.elefante_id)
        .join(Livro, Leitura.livro_id == Livro.id)
        .where(Leitura.aluno_id.in_(alunos.keys()))
    )
    if inicio is not None:
        consulta = consulta.where(Leitura.data >= inicio)
    if fim is not None:
        consulta = consulta.where(Leitura.data <= fim)
    itens: dict[int, list] = {}
    for aid, codigo, minutos, titulo, elefante_id in db.execute(consulta).all():
        livros[aid] = livros.get(aid, 0) + 1
        # Identidade oficial do livro (id do catálogo do Elefante) antes do título.
        pontos[aid] = pontos.get(aid, 0.0) + regra.valor_livro(
            codigo, titulo, alunos[aid]["ano_escolar"], alunos[aid]["turma_id"],
            elefante_id=elefante_id)
        tempo[aid] = tempo.get(aid, 0) + (minutos or 0)
        itens.setdefault(aid, []).append((titulo, codigo, 0, elefante_id))
    if inicio is None and fim is None:
        # "Todo o histórico": inclui o AGREGADO do Elefante (snapshot atual) com a
        # MESMA reconciliação da nota anual e do /ranking/leitura — quem só tem o
        # relatório da turma não fica com 0; quem tem os dois não conta em dobro.
        q_snap = (
            select(SnapshotElefante.aluno_id, SnapshotElefante.livros_unicos,
                   SnapshotElefante.tempo_leitura_min, SnapshotElefante.livros_por_nivel)
            .where(SnapshotElefante.id.in_(scoring.ids_snapshots_atuais(SnapshotElefante, escola_id)),
                   SnapshotElefante.aluno_id.in_(alunos.keys())))
        for aid, n_livros, minutos, por_nivel in db.execute(q_snap).all():
            livros[aid] = max(livros.get(aid, 0), int(n_livros or 0))
            tempo[aid] = max(tempo.get(aid, 0), int(minutos or 0))
            pontos[aid] = regra.pontos_aluno(por_nivel or {}, alunos[aid]["ano_escolar"],
                                             turma_id=alunos[aid]["turma_id"],
                                             leituras=itens.get(aid))
    return livros, pontos, tempo


def _iso(momento: datetime | None) -> str | None:
    return momento.isoformat() if momento is not None else None


def _matematica_no_periodo(db: Session, escola_id: int, coorte: dict[int, dict],
                           inicio: datetime | None, fim: datetime | None,
                           ano_letivo: int) -> tuple[dict[int, dict], dict]:
    """Índice da "Melhor Matemática" de cada aluno + a régua usada.

    ``coorte`` é a ESCOLA INTEIRA (todos os ativos matriculados no ano letivo): é
    dela que sai a mediana ``k``, e por isso o índice de uma criança não muda
    quando o pódio é filtrado por turma, professor ou turno. Só entra quem tem
    snapshot do Matific no período (ausência não é zero) e pelo menos uma
    atividade no período (sem atividade não há média a medir). NÃO grava nada e
    NÃO toca o scoring. Toda a aritmética está em ``matific_destaque``."""
    series = _series_por_aluno(db, escola_id, SnapshotMatific)
    ganhos: dict[int, matific_destaque.GanhoMatific] = {}
    for aid in coorte:
        ganho = matific_destaque.ganho_no_periodo(
            series.get(aid, []), inicio, fim, ano_letivo)
        if ganho is not None:
            ganhos[aid] = ganho
    regua, indices = matific_destaque.indices_da_coorte(ganhos)

    todo_historico = inicio is None and fim is None
    janela = (None if todo_historico
              else matific_destaque.janela_efetiva(inicio, fim, ano_letivo))
    # Personalizado com as datas trocadas (início depois do fim): não há janela,
    # mas o motivo não é o ano letivo — o rótulo não pode mentir sobre isso.
    invertido = (inicio is not None and fim is not None
                 and inicio.replace(tzinfo=None) > fim.replace(tzinfo=None))
    if todo_historico:
        modo = "situacao_atual"
    elif janela is not None:
        modo = "periodo"
    else:
        modo = "periodo_invalido" if invertido else "fora_do_ano_letivo"
    k = regua.k_mediana_atividades
    descricao_regua = {
        "coorte": "escola",
        "k_mediana_atividades": round(k, 4) if k is not None else None,
        "zeros_extras": (round(regua.zeros_extras, 4)
                         if regua.zeros_extras is not None else None),
        "alunos_com_atividade": regua.alunos_com_atividade,
        "ano_letivo": ano_letivo,
        # Datas EFETIVAMENTE usadas: o período ∩ ano letivo. "Todo o histórico"
        # não recorta período (vale o último snapshot do ano letivo); um período
        # que não toca o ano letivo, ou com as datas trocadas, não tem janela —
        # em todos esses casos, sem datas.
        "modo": modo,
        "inicio_efetivo": _iso(janela[0]) if janela else None,
        "fim_efetivo": _iso(janela[1]) if janela else None,
    }
    matematica = {
        aid: {"indice": valor,
              "estrelas": ganhos[aid].estrelas,
              "atividades": ganhos[aid].atividades,
              "data_base": _iso(ganhos[aid].data_base),
              "data_atual": _iso(ganhos[aid].data_atual)}
        for aid, valor in indices.items()
    }
    return matematica, descricao_regua


def _categoria(chave: str, titulo: str, icone: str, descricao: str, unidade: str,
               valores: dict, alunos: dict[int, dict], limite: int,
               desempate: dict[int, tuple] | None = None,
               extras: dict[int, dict] | None = None) -> dict:
    """Uma categoria: a ordem calculada UMA vez, o pódio (``limite`` linhas) e o
    ``total`` de premiáveis — é o total que diz à tela se há ranking além do que
    ela já tem."""
    ordenados = _ordenar(valores, alunos, desempate)
    return {"chave": chave, "titulo": titulo, "icone": icone, "descricao": descricao,
            "unidade": unidade, "total": len(ordenados),
            "podio": _itens(ordenados, alunos, limite, extras)}


def _categorias(alunos: dict[int, dict], livros: dict, pontos: dict, tempo: dict,
                matematica: dict[int, dict], limite: int = 5) -> list[dict]:
    """Os 4 pódios para um conjunto de alunos (o recorte, ou um turno dele).

    ``limite`` é só QUANTAS linhas voltam: 5 no cartão, mais no ranking completo.
    A ordem, o desempate e o valor de cada linha não mudam com ele."""
    indices = {aid: d["indice"] for aid, d in matematica.items()}
    # Desempate da Matemática: estrelas do período → atividades do período → nome.
    desempate_m = {aid: (d["estrelas"], d["atividades"]) for aid, d in matematica.items()}
    auditoria_m = {aid: {"estrelas": d["estrelas"], "atividades": d["atividades"],
                         "data_base": d["data_base"], "data_atual": d["data_atual"]}
                   for aid, d in matematica.items()}
    return [
        _categoria("melhor_leitor", "Melhor Leitor", "🏆",
                   "Mais pontos de dificuldade no período", "pontos",
                   pontos, alunos, limite),
        _categoria("melhor_matematica", "Melhor Matemática", "🧮",
                   "Maior média ajustada de estrelas por atividade no período",
                   "estrelas/atividade", indices, alunos, limite,
                   desempate=desempate_m, extras=auditoria_m),
        _categoria("mais_livros", "Mais Livros Lidos", "📚",
                   "Maior quantidade de livros no período", "livros",
                   livros, alunos, limite),
        _categoria("mais_tempo", "Mais Tempo de Leitura", "⏱️",
                   "Maior tempo dedicado à leitura", "min",
                   tempo, alunos, limite),
    ]


def premiacoes(db: Session, escola_id: int, inicio: datetime | None,
               fim: datetime | None, turma_id: int | None = None,
               turma_ids: list[int] | None = None,
               por_turno: bool = False, limite: int = 5) -> dict:
    """Pódios do período. ``limite`` é QUANTAS linhas cada pódio traz — 5 no
    cartão da tela, mais quando ela pede o ranking completo daquela premiação.
    Nada além do tamanho da lista muda: mesma coorte, mesma régua, mesma ordem,
    mesmo desempate, mesmas posições."""
    escola = db.get(Escola, escola_id)
    ano = escola.ano_letivo_ativo
    # COORTE COMPLETA da escola (sem turma nem professor): é a base da régua.
    coorte = _alunos_ativos(db, escola_id, ano, None)
    # RECORTE: quem aparece nos pódios.
    alunos = _recorte(coorte, turma_id, turma_ids)

    livros, pontos, tempo = _leitura_no_periodo(db, escola_id, alunos, inicio, fim)
    matematica, regua = _matematica_no_periodo(db, escola_id, coorte, inicio, fim, ano)

    resultado: dict = {
        "categorias": _categorias(alunos, livros, pontos, tempo, matematica, limite),
        "regua_matematica": regua,
    }

    # Quebra por TURNO (só na visão "todas as turmas"): agrupa os MESMOS dados já
    # calculados por Turma.turno, sem recomputar a régua. Turnos vêm do banco.
    if por_turno and turma_id is None:
        grupos: dict = {}
        for aid, info in alunos.items():
            grupos.setdefault(info["turno"], {})[aid] = info
        resultado["turnos"] = [
            {"turno": turno, "turno_rotulo": svc_turnos.rotulo_turno(turno),
             "total": len(sub),
             "categorias": _categorias(sub, livros, pontos, tempo, matematica, limite)}
            for turno, sub in sorted(grupos.items(), key=lambda kv: svc_turnos.ordem_turno(kv[0]))
        ]
    return resultado
