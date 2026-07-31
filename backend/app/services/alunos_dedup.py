"""Detecção em LOTE de alunos duplicados (o motor do "Fundir duplicatas").

Espelha o dedup de professores (``professores._candidatos``), mas com a TURMA
como discriminador central — a regra do dono é precisão acima de tudo: é muito
pior fundir duas crianças diferentes do que deixar duas fichas duplicadas.

Por isso o detector é conservador (prefere o falso-negativo):
  * só compara alunos ATIVOS que têm turma no ano letivo ativo;
  * só sugere pares da MESMA turma (nunca entre turmas ou escolas);
  * nome idêntico + mesma turma → 🟢 "alta";
  * nome curto que é começo/abreviação de UM único nome mais completo, mesma
    turma → 🟡 "revisar" (o caso Matific-curto × Lista-Piloto-completo, ex.:
    "AKEMI CAROLINA VIEIRA" ⊂ "AKEMI CAROLINA VIEIRA GOMES KARIYA");
  * ambíguo (o curto caberia em DOIS nomes completos da turma) → não sugere.

Nada funde automaticamente: isto só PRODUZ candidatos; o Admin Global/coordenador
confirma cada par (checkbox) e a fusão em si é ``alunos_fusao.fundir_par``.
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Aluno,
    Escola,
    EventoAluno,
    IdentidadeExterna,
    Leitura,
    Matricula,
    Nota,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
)
from app.services import alunos_fusao
from app.services._nomes import primeiro_token, tokens
from app.services.importacao import casa_abreviado_posicional, tokens_nome


def _expande(curto: str, completo: str) -> bool:
    """``completo`` é uma forma MAIS completa de ``curto`` (mesma pessoa)?
    Cobre dois padrões de duplicata do Matific/Elefante:
      * subconjunto ESTRITO de tokens ('Maria Silva' ⊂ 'Maria Eduarda Silva');
      * abreviação POSICIONAL ('Agatha V' → 'Agatha Vitoria …'), sem casar
        'Eloa S' com 'Eloa … Silva' (o matcher já rejeita subsequência)."""
    tc, tk = tokens(curto), tokens(completo)
    if tc and tc < tk:
        return True
    return casa_abreviado_posicional(tokens_nome(curto), tokens_nome(completo))


def _conflito_forte(a: Aluno, b: Aluno) -> bool:
    """Sinais que PROVAM serem crianças DIFERENTES — vetam a sugestão de fusão
    (nunca sugerir, nem para revisar). Data de nascimento, nº de chamada ou RA
    preenchidos NOS DOIS cadastros e divergentes = duas crianças distintas."""
    if (a.data_nascimento and b.data_nascimento
            and a.data_nascimento != b.data_nascimento):
        return True
    if (a.numero_chamada is not None and b.numero_chamada is not None
            and a.numero_chamada != b.numero_chamada):
        return True
    ra_a = str((a.ficha or {}).get("ra", "")).strip()
    ra_b = str((b.ficha or {}).get("ra", "")).strip()
    return bool(ra_a and ra_b and ra_a != ra_b)


def _dob_concordante(a: Aluno, b: Aluno) -> bool:
    """Data de nascimento preenchida NOS DOIS e IGUAL — corrobora que é a mesma
    criança (sobe a confiança do nome idêntico de 'revisar' para 'alta')."""
    return bool(a.data_nascimento and b.data_nascimento
               and a.data_nascimento == b.data_nascimento)


def _turmas_ativas(db: Session, escola_id: int, ano: int) -> dict[int, tuple[int, str]]:
    """aluno_id → (turma_id, turma_nome) no ano letivo ativo (1 por aluno)."""
    linhas = db.execute(
        select(Matricula.aluno_id, Turma.id, Turma.nome)
        .join(Turma, Turma.id == Matricula.turma_id)
        .where(Matricula.escola_id == escola_id, Matricula.ano_letivo == ano)
    ).all()
    return {aluno_id: (turma_id, turma_nome)
            for aluno_id, turma_id, turma_nome in linhas}


def _candidatos(db: Session, escola_id: int
                ) -> list[tuple[Aluno, Aluno, str, str, str]]:
    """Pares (loser, survivor, confianca, motivo, turma_nome) da MESMA turma.
    ``confianca`` ∈ {"alta","revisar"}; ``motivo`` ∈ {"nome_identico",
    "subconjunto","abreviacao"}. survivor = o nome mais completo (empate: menor id)."""
    escola = db.get(Escola, escola_id)
    if escola is None:
        return []
    ano = escola.ano_letivo_ativo
    turma_de = _turmas_ativas(db, escola_id, ano)

    alunos = db.execute(
        select(Aluno).where(Aluno.escola_id == escola_id, Aluno.status == "ativo")
    ).scalars().all()
    # A turma é o discriminador: quem não tem turma no ano ativo fica de fora
    # (evita sugerir fusão sem o sinal mais forte).
    membros = [a for a in alunos if a.id in turma_de]

    grupos: dict[str, list[Aluno]] = defaultdict(list)
    for a in membros:
        grupos[primeiro_token(a.nome)].append(a)

    def mesma_turma(x: Aluno, y: Aluno) -> bool:
        return turma_de[x.id][0] == turma_de[y.id][0]

    pares: list[tuple[Aluno, Aluno, str, str, str]] = []
    for primeiro, grupo in grupos.items():
        if not primeiro or len(grupo) < 2:
            continue
        # Titular de cada NOME (conjunto de tokens) = o de MENOR id.
        titular_por_tokens: dict[frozenset, Aluno] = {}
        for a in sorted(grupo, key=lambda x: x.id):
            titular_por_tokens.setdefault(tokens(a.nome), a)

        for a in grupo:
            tk = tokens(a.nome)
            titular = titular_por_tokens[tk]
            if a.id != titular.id:
                # Nome idêntico (id maior). Só sugere na MESMA turma e se NENHUM
                # sinal forte provar serem crianças diferentes. Confiança "alta"
                # exige nascimento igual nos dois (corrobora); senão "revisar"
                # (não pré-marcada) — pode ser homônimo/gêmeo de verdade.
                if mesma_turma(a, titular) and not _conflito_forte(a, titular):
                    conf = "alta" if _dob_concordante(a, titular) else "revisar"
                    pares.append((a, titular, conf, "nome_identico",
                                  turma_de[a.id][1]))
                continue
            # `a` é o titular do seu nome → procura o nome mais completo (único)
            # na mesma turma, descartando quem tem conflito forte de identidade.
            expansoes = [q for q in grupo
                         if q.id != a.id and mesma_turma(a, q)
                         and _expande(a.nome, q.nome)
                         and not _conflito_forte(a, q)]
            tokens_exp = {tokens(q.nome) for q in expansoes}
            if len(tokens_exp) == 1:      # exatamente UM nome mais completo
                survivor = min(expansoes, key=lambda q: q.id)
                motivo = "subconjunto" if tk < tokens(survivor.nome) else "abreviacao"
                pares.append((a, survivor, "revisar", motivo, turma_de[a.id][1]))
    return pares


def _impacto(db: Session, aluno: Aluno) -> dict:
    """Resumo do que será MOVIDO do duplicado para o principal — para o gestor
    ver o peso de cada fusão antes de confirmar."""
    def conta(modelo) -> int:
        return len(db.execute(
            select(modelo.id).where(modelo.aluno_id == aluno.id)).scalars().all())

    plataformas = db.execute(
        select(IdentidadeExterna.plataforma)
        .where(IdentidadeExterna.aluno_id == aluno.id)
    ).scalars().all()
    return {
        "leituras": conta(Leitura),
        "snapshots_matific": conta(SnapshotMatific),
        "snapshots_elefante": conta(SnapshotElefante),
        "eventos": conta(EventoAluno),
        "notas": conta(Nota),
        "plataformas": sorted(set(plataformas)),
    }


def plano_deduplicacao(db: Session, escola_id: int) -> list[dict]:
    """PRÉVIA (read-only): uma linha por candidato — qual cadastro sai, em qual
    fica, a turma, a confiança/motivo e o resumo de impacto. Nada é alterado."""
    return [
        {
            "loser_id": loser.id,
            "manter_id": survivor.id,
            "apagar": loser.nome,
            "manter": survivor.nome,
            "turma": turma,
            "confianca": confianca,     # "alta" | "revisar"
            "motivo": motivo,
            "impacto": _impacto(db, loser),
        }
        for loser, survivor, confianca, motivo, turma in _candidatos(db, escola_id)
    ]


def aplicar_deduplicacao(db: Session, escola_id: int, loser_ids: list[int],
                         usuario_id: int) -> dict:
    """APLICA só as fusões CONFIRMADAS (``loser_ids``). Recomputa os candidatos
    no servidor (fonte da verdade — o cliente só manda ids), funde par-a-par via
    ``alunos_fusao.fundir_par`` e reporta as falhas individuais SEM abortar o
    lote. NÃO commita nem recalcula — o endpoint faz isso UMA vez no fim."""
    escolhidos = set(loser_ids or [])
    selecionados = [(loser.id, survivor.id)
                    for loser, survivor, *_ in _candidatos(db, escola_id)
                    if loser.id in escolhidos]

    # CADEIA: um cadastro que aparece dos DOIS lados entre os pares escolhidos
    # (survivor de um par e loser de outro) fundiria em cascata e poderia colapsar
    # 3 cadastros num só. Recusa e reporta — o gestor resolve um par por vez.
    losers_sel = {l for l, _s in selecionados}
    survivors_sel = {s for _l, s in selecionados}

    fundidos = 0
    falhas: list[dict] = []
    detalhes: list[dict] = []
    for loser_id, survivor_id in selecionados:
        if survivor_id in losers_sel or loser_id in survivors_sel:
            falhas.append({"loser_id": loser_id,
                           "motivo": "faz parte de uma cadeia de fusões — una um par por vez"})
            continue
        remover = db.get(Aluno, loser_id)
        manter = db.get(Aluno, survivor_id)
        if (remover is None or manter is None or remover.id == manter.id
                or remover.escola_id != escola_id or manter.escola_id != escola_id
                or remover.status != "ativo" or manter.status != "ativo"):
            falhas.append({"loser_id": loser_id,
                           "motivo": "cadastro indisponível (já fundido?)"})
            continue
        # SAVEPOINT por par: uma fusão que estoure (dado inconsistente) desfaz SÓ
        # a si mesma e o lote segue — cumpre o contrato "falhas sem abortar o lote"
        # (o commit final fica com o endpoint).
        try:
            with db.begin_nested():
                r = alunos_fusao.fundir_par(db, escola_id, manter, remover, usuario_id)
            fundidos += 1
            detalhes.append({"manter_id": survivor_id, "manter": r["manter_nome"],
                             "removido": r["remover_nome"]})
        except Exception:   # noqa: BLE001 — isola a falha do par, não derruba o lote
            falhas.append({"loser_id": loser_id,
                           "motivo": "erro ao fundir (dados inconsistentes)"})

    return {"fundidos": fundidos, "falhas": falhas, "detalhes": detalhes}
