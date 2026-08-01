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

from sqlalchemy import func, select
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
from app.services.importacao import (
    casa_abreviado_posicional,
    tokens_nome,
    variante_ortografica,
)
from app.services.matriculas import chave_turma_norm


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
        # Compara a turma NORMALIZADA (série+letra), não o turma_id: as duplicatas
        # da importação antiga ficam em turmas-fantasma distintas ("4ºC" vs
        # "4 ANO C INTEGRAL (300303525)") que são a MESMA sala — sem isto, os
        # cadastros do mesmo aluno nunca eram sequer comparados.
        return chave_turma_norm(turma_de[x.id][1]) == chave_turma_norm(turma_de[y.id][1])

    pares: list[tuple[Aluno, Aluno, str, str, str]] = []
    for primeiro, grupo in grupos.items():
        if not primeiro or len(grupo) < 2:
            continue
        # Titular de cada NOME (conjunto de tokens) = o da LISTA PILOTO (perfil
        # principal); sem piloto, o de MENOR id (mais antigo).
        titular_por_tokens: dict[frozenset, Aluno] = {}
        for a in sorted(grupo, key=lambda x: (not x.da_lista_piloto, x.id)):
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
            # AMBIGUIDADE conta ALUNOS candidatos, não conjuntos de tokens: dois
            # homônimos/gêmeos ("MARIA EDUARDA SANTOS" ×2) têm o MESMO token-set e
            # colapsariam num só — aí o stub curto seria colado no aluno errado.
            # Só é inequívoco quando existe UM ÚNICO aluno mais completo.
            if len(expansoes) == 1:
                alvo = expansoes[0]                    # o nome mais completo (a ⊂ alvo)
                # O perfil da LISTA PILOTO sempre sobrevive (nunca é deletado, nome
                # oficial mantido) — mesmo sendo o nome mais curto.
                survivor = _melhor_perfil(a, alvo)
                loser = alvo if survivor.id == a.id else a
                motivo = "subconjunto" if tk < tokens(alvo.nome) else "abreviacao"
                pares.append((loser, survivor, "revisar", motivo, turma_de[loser.id][1]))

        # VARIAÇÃO ORTOGRÁFICA (LUÍS/LUIZ): nomes DIFERENTES mas quase iguais na
        # mesma turma normalizada, sem conflito de identidade. É o que a comparação
        # por token-set EXATO deixava passar. "revisar" (nunca pré-marca): estrito
        # o bastante para NÃO parear crianças diferentes (LUÍS×LUCAS → ratio baixo).
        # Cada aluno aponta para o MELHOR parceiro (piloto > completo > antigo), não
        # para todos: assim 3 fichas do mesmo aluno viram um LEQUE (todas → o piloto),
        # nunca uma cadeia entre duplicatas.
        ja_losers = {l.id for l, _s, *_ in pares}
        ordenado = sorted(grupo, key=lambda x: x.id)
        for a in ordenado:
            if a.id in ja_losers:
                continue                              # já sai por outro par
            parceiros = [b for b in ordenado
                         if b.id != a.id and mesma_turma(a, b)
                         and not _conflito_forte(a, b)
                         and variante_ortografica(tokens_nome(a.nome), tokens_nome(b.nome))]
            # SÓ sugere quando há UM único parceiro variante (ambíguo → não sugere).
            # E é SEMPRE revisão manual (nunca automático): similaridade de nome não
            # distingue "LUÍS/LUIZ" (mesma criança) de "MARIA/MARTA" (crianças
            # diferentes) — ambos caem no mesmo limiar. Só um humano decide.
            if len(parceiros) != 1:
                continue
            survivor = _melhor_perfil(parceiros[0], a)
            if survivor.id == a.id:
                continue                              # `a` é o melhor → não é loser
            pares.append((a, survivor, "revisar", "variante", turma_de[a.id][1]))
            ja_losers.add(a.id)
    return pares


def _melhor_perfil(a: Aluno, b: Aluno) -> Aluno:
    """Qual dos dois é o perfil PRINCIPAL (survivor): o da Lista Piloto vence
    (fonte da verdade do cadastro); senão o de nome mais completo; empate, menor
    id (mais antigo)."""
    if a.da_lista_piloto != b.da_lista_piloto:
        return a if a.da_lista_piloto else b
    ta, tb = len(tokens(a.nome)), len(tokens(b.nome))
    if ta != tb:
        return a if ta > tb else b
    return a if a.id <= b.id else b


_VAZIO = {"leituras": 0, "snapshots_matific": 0, "snapshots_elefante": 0,
          "eventos": 0, "notas": 0, "plataformas": []}


def _impactos_em_lote(db: Session, aluno_ids: list[int]) -> dict[int, dict]:
    """Resumo do que será MOVIDO de CADA duplicado, calculado em POUCAS queries
    (um GROUP BY por modelo) — não uma dúzia por candidato. Sem isto, numa escola
    grande (Debora Pilon) a prévia fazia centenas de consultas e a tela de Fundir
    Duplicatas travava/estourava."""
    if not aluno_ids:
        return {}
    ids = set(aluno_ids)

    def contar(modelo) -> dict[int, int]:
        return {aid: n for aid, n in db.execute(
            select(modelo.aluno_id, func.count())
            .where(modelo.aluno_id.in_(ids)).group_by(modelo.aluno_id)).all()}

    leituras = contar(Leitura)
    smat = contar(SnapshotMatific)
    sele = contar(SnapshotElefante)
    eventos = contar(EventoAluno)
    notas = contar(Nota)
    plats: dict[int, set[str]] = defaultdict(set)
    for aid, plat in db.execute(
        select(IdentidadeExterna.aluno_id, IdentidadeExterna.plataforma)
        .where(IdentidadeExterna.aluno_id.in_(ids))).all():
        plats[aid].add(plat)

    return {aid: {
        "leituras": leituras.get(aid, 0),
        "snapshots_matific": smat.get(aid, 0),
        "snapshots_elefante": sele.get(aid, 0),
        "eventos": eventos.get(aid, 0),
        "notas": notas.get(aid, 0),
        "plataformas": sorted(plats.get(aid, set())),
    } for aid in ids}


def plano_deduplicacao(db: Session, escola_id: int) -> list[dict]:
    """PRÉVIA (read-only): uma linha por candidato — qual cadastro sai, em qual
    fica, a turma, a confiança/motivo e o resumo de impacto. Nada é alterado."""
    candidatos = _candidatos(db, escola_id)
    impactos = _impactos_em_lote(db, [loser.id for loser, *_ in candidatos])
    return [
        {
            "loser_id": loser.id,
            "manter_id": survivor.id,
            "apagar": loser.nome,
            "manter": survivor.nome,
            "turma": turma,
            "confianca": confianca,     # "alta" | "revisar"
            "motivo": motivo,
            "impacto": impactos.get(loser.id, _VAZIO),
        }
        for loser, survivor, confianca, motivo, turma in candidatos
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

    # LEQUE vs CADEIA. Um aluno TRIPLICADO cujas fichas apontam TODAS para o mesmo
    # perfil principal (A→S, B→S — o caso Debora Pilon, com o survivor da Lista
    # Piloto escolhido por _melhor_perfil) é um LEQUE e funde numa tacada só. Já a
    # CADEIA genuína (A→B, B→C: um cadastro é survivor de um par E loser de outro)
    # tem um nó AMBÍGUO no meio (pode ser gêmeo/homônimo) — recusa e reporta, para
    # nunca colapsar crianças diferentes sem revisão. É a régua "precisão acima de
    # tudo": o leque (seguro) passa; a cadeia (ambígua) espera revisão.
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


# NOTA (revisão adversarial, 2 rodadas): a AUTO-FUSÃO do passivo foi REMOVIDA por
# não ser segura. Todo sinal automático pode fundir CRIANÇAS DIFERENTES:
#   * nome idêntico → gêmeos/homônimos; * variante (LUÍS/LUIZ) → indistinguível de
#   MARIA/MARTA; * abreviação ("ABRAÃO L") → o dono real da inicial pode não estar
#   no roster, então "1 candidato" é artefato de roster incompleto, não prova.
# Como a fusão DELETA registros (irreversível), o passivo é resolvido SÓ pela
# ferramenta MANUAL (detecção inteligente + "Selecionar todos" + avisos ⚠), onde
# um humano confirma. A regra do dono ("nunca fundir crianças diferentes") vence a
# conveniência da automação.
