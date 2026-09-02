"""Premiações por PERÍODO (PRD — premiações da escola).

Calcula os vencedores de cada categoria usando EXCLUSIVAMENTE os dados do
intervalo escolhido — leituras (com data real, Fase 1) e desempenho no Matific
(snapshot do fim da janela). Premiações justas: quem só importou dados fora do
intervalo não pontua.

Camada de PREMIAÇÃO — NÃO altera o scoring oficial. A "melhor matemática" usa a
``nota_matific`` OFICIAL (0–100) calculada READ-ONLY pelo motor sobre o estado do
período (decisão do dono 2026-09-01): antes premiava só a QUANTIDADE de
atividades (volume), que não representa o melhor desempenho.

Turno (manhã/tarde/noite) é o eixo do PERÍODO ESCOLAR, ORTOGONAL ao PERÍODO
TEMPORAL (datas). Com ``por_turno`` os pódios saem quebrados por ``Turma.turno``,
mas a régua (P90 do Matific) é a da escola INTEIRA — senão cada turno teria uma
escala diferente e as notas deixariam de ser comparáveis.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Aluno, Escola, Leitura, Livro, Matricula, SnapshotMatific, Turma
from app.services import scoring
from app.services import turnos as svc_turnos
from app.services.evolucao import _janela, _series_por_aluno


def _podio(valores: dict[int, float], alunos: dict[int, dict], limite: int = 5,
           desempate: dict[int, tuple] | None = None) -> list[dict]:
    """Top N (só quem tem valor > 0), ordenado por valor. ``desempate`` opcional
    é uma cascata secundária por aluno (ex.: estrelas→atividades→média no
    Matific); sem ele, desempata pelo nome (determinístico e estável)."""
    itens = [
        {"aluno_id": aid, "nome": alunos[aid]["nome"], "turma": alunos[aid]["turma"],
         "valor": round(float(valor), 2)}
        for aid, valor in valores.items()
        if aid in alunos and valor and valor > 0
    ]
    itens.sort(key=lambda x: (
        -x["valor"],
        *(tuple(-v for v in desempate[x["aluno_id"]]) if desempate else ()),
        x["nome"].casefold(),
    ))
    for posicao, item in enumerate(itens[:limite], start=1):
        item["posicao"] = posicao
    return itens[:limite]


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


def _leitura_no_periodo(db: Session, escola_id: int, alunos: dict[int, dict],
                        inicio: datetime | None, fim: datetime | None):
    """Livros, pontos de dificuldade e tempo somados por aluno no intervalo.
    Pontos resolvidos pela TURMA do aluno (TURMA>SÉRIE>padrão) — a MESMA régua do
    ranking anual, senão o 'Melhor Leitor' coroaria a criança errada."""
    mapa_turmas = scoring.mapa_pontos_turmas(db, escola_id)
    livros: dict[int, float] = {}
    pontos: dict[int, float] = {}
    tempo: dict[int, float] = {}
    if not alunos:
        return livros, pontos, tempo
    consulta = (
        select(Leitura.aluno_id, Livro.nivel_codigo, Leitura.tempo_leitura_min)
        .join(Livro, Leitura.livro_id == Livro.id)
        .where(Leitura.aluno_id.in_(alunos.keys()))
    )
    if inicio is not None:
        consulta = consulta.where(Leitura.data >= inicio)
    if fim is not None:
        consulta = consulta.where(Leitura.data <= fim)
    for aid, codigo, minutos in db.execute(consulta).all():
        livros[aid] = livros.get(aid, 0) + 1
        mapa_aluno = mapa_turmas.get(alunos[aid]["turma_id"], mapa_turmas[None])
        pontos[aid] = pontos.get(aid, 0.0) + mapa_aluno.get((codigo or "").upper(), 0.0)
        tempo[aid] = tempo.get(aid, 0) + (minutos or 0)
    return livros, pontos, tempo


def _notas_matific_periodo(db: Session, escola_id: int, aluno_ids,
                           inicio: datetime | None, fim: datetime | None) -> dict[int, dict]:
    """``nota_matific`` OFICIAL (0–100) do ESTADO no fim da janela, calculada
    READ-ONLY pelo motor (mesma régua P90 do scoring). NÃO grava nada e NÃO altera
    pesos/normalização. Régua da escola inteira (aluno_ids = todos os ativos), para
    as notas serem comparáveis mesmo quando o pódio depois é filtrado por turno.
    Só entra quem tem snapshot na janela (senão a dimensão é ausência, não 0)."""
    series = _series_por_aluno(db, escola_id, SnapshotMatific)
    estados: dict[int, SnapshotMatific] = {}
    for aid in aluno_ids:
        atual, _ = _janela(series.get(aid, []), inicio, fim, base_no_periodo=True)
        if atual is not None:
            estados[aid] = atual
    if not estados:
        return {}
    # Régua P90 do Matific direto pelo motor oficial (read-only) — uma única
    # dimensão (matemática), então chamamos scoring.referencias_robustas sem
    # depender do helper por-dimensão da Arquitetura 2. NÃO altera scoring.
    refs, k_vol = scoring.referencias_robustas({
        "atividades": [s.atividades for s in estados.values()],
        "media": [s.pontuacao_media for s in estados.values()],
        "estrelas": [s.estrelas for s in estados.values()],
    })
    pesos = scoring.obter_pesos(db, escola_id, "pesos.matific")
    pesos_pct = scoring.obter_pesos_brutos(db, escola_id, "pesos.matific")
    notas: dict[int, dict] = {}
    for aid, s in estados.items():
        nota, _ = scoring.calcular_matific(s, refs, pesos, pesos_pct, k_vol)
        notas[aid] = {"nota": nota, "estrelas": s.estrelas,
                      "atividades": s.atividades, "media": s.pontuacao_media}
    return notas


def _categorias(alunos: dict[int, dict], livros: dict, pontos: dict, tempo: dict,
                matific: dict[int, dict]) -> list[dict]:
    """Os 4 pódios para um conjunto de alunos (a escola toda ou um turno)."""
    notas_m = {aid: d["nota"] for aid, d in matific.items()}
    desempate_m = {aid: (d["estrelas"], d["atividades"], d["media"])
                   for aid, d in matific.items()}
    return [
        {"chave": "melhor_leitor", "titulo": "Melhor Leitor", "icone": "🏆",
         "descricao": "Mais pontos de dificuldade no período", "unidade": "pontos",
         "podio": _podio(pontos, alunos)},
        {"chave": "melhor_matematica", "titulo": "Melhor Matemática", "icone": "🧮",
         "descricao": "Maior nota oficial de Matemática (0–100) no período",
         "unidade": "nota", "podio": _podio(notas_m, alunos, desempate=desempate_m)},
        {"chave": "mais_livros", "titulo": "Mais Livros Lidos", "icone": "📚",
         "descricao": "Maior quantidade de livros no período", "unidade": "livros",
         "podio": _podio(livros, alunos)},
        {"chave": "mais_tempo", "titulo": "Mais Tempo de Leitura", "icone": "⏱️",
         "descricao": "Maior tempo dedicado à leitura", "unidade": "min",
         "podio": _podio(tempo, alunos)},
    ]


def premiacoes(db: Session, escola_id: int, inicio: datetime | None,
               fim: datetime | None, turma_id: int | None = None,
               turma_ids: list[int] | None = None,
               por_turno: bool = False) -> dict:
    escola = db.get(Escola, escola_id)
    ano = escola.ano_letivo_ativo
    alunos = _alunos_ativos(db, escola_id, ano, turma_id, turma_ids)

    livros, pontos, tempo = _leitura_no_periodo(db, escola_id, alunos, inicio, fim)
    # Régua do Matific calculada sobre a escola INTEIRA (todos os alunos do escopo)
    # uma vez — comparável entre turnos.
    matific = _notas_matific_periodo(db, escola_id, alunos.keys(), inicio, fim)

    resultado: dict = {"categorias": _categorias(alunos, livros, pontos, tempo, matific)}

    # Quebra por TURNO (só na visão "todas as turmas"): agrupa os MESMOS dados já
    # calculados por Turma.turno, sem recomputar a régua. Turnos vêm do banco.
    if por_turno and turma_id is None:
        grupos: dict = {}
        for aid, info in alunos.items():
            grupos.setdefault(info["turno"], {})[aid] = info
        resultado["turnos"] = [
            {"turno": turno, "turno_rotulo": svc_turnos.rotulo_turno(turno),
             "total": len(sub),
             "categorias": _categorias(sub, livros, pontos, tempo, matific)}
            for turno, sub in sorted(grupos.items(), key=lambda kv: svc_turnos.ordem_turno(kv[0]))
        ]
    return resultado
