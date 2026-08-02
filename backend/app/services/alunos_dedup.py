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
from functools import reduce
from itertools import combinations

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
from app.services.importacao import casa_abreviado, tokens_nome
from app.services.matching import plausivel
from app.services.matriculas import chave_turma_norm


def _expande(curto: str, completo: str) -> bool:
    """``completo`` é uma forma MAIS completa de ``curto`` (mesma pessoa)?
    Cobre os padrões de duplicata do Matific/Elefante:
      * subconjunto ESTRITO de tokens ('Maria Silva' ⊂ 'Maria Eduarda Silva');
      * abreviação POSICIONAL com inicial em qualquer posição ('Agatha V' →
        'Agatha Vitoria …', 'M. Eduarda' → 'Maria Eduarda …', 'Maria Edu' →
        'Maria Eduarda …'), sem casar 'Eloa S' com 'Eloa … Silva' (posicional)."""
    tc, tk = tokens(curto), tokens(completo)
    if tc and tc < tk:
        return True
    return casa_abreviado(tokens_nome(curto), tokens_nome(completo))


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


def _nome_completo(nome: str) -> bool:
    """Nome de fato COMPLETO — dois tokens ou mais e SEM inicial solta ('ANA B',
    'MARIA E'). Um stub truncado do Matific/Elefante NÃO é nome completo: dois
    'ANA B' idênticos podem ser crianças diferentes (Ana Beatriz × Ana Bianca),
    então não entram na faixa pré-marcada."""
    tk = tokens(nome)
    return len(tk) >= 2 and all(len(t) > 1 for t in tk)


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
    ``confianca`` ∈ {"alta","provavel","revisar"} (🟢 aprova em lote / 🟡 lote com
    conferência / 🔴 uma a uma); ``motivo`` ∈ {"nome_identico","subconjunto",
    "abreviacao","variante"}. survivor = perfil principal (piloto > nome completo)."""
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

    # Chave canônica da turma memoizada por aluno (1x, não por par): as duplicatas
    # da importação antiga ficam em turmas-fantasma distintas ("4ºC" vs "4 ANO C
    # INTEGRAL (300303525)") que são a MESMA sala — comparar por chave normalizada
    # (série+letra) as reúne. Calcular aqui evita recomputar o regex a cada par.
    chave_de: dict[int, str] = {a.id: chave_turma_norm(turma_de[a.id][1]) for a in membros}

    # Agrupa por (PRIMEIRA LETRA do 1º nome, TURMA canônica): a 1ª letra põe o stub
    # com inicial ("M. EDUARDA") no mesmo balde que "MARIA EDUARDA SILVA" (com token
    # inteiro nunca eram comparados); a turma mantém o balde PEQUENO (só a mesma
    # sala), evitando o custo O(n²) por letra numa escola grande. Casamentos só
    # acontecem dentro da mesma sala, então nada é perdido.
    grupos: dict[tuple[str, str], list[Aluno]] = defaultdict(list)
    for a in membros:
        grupos[(primeiro_token(a.nome)[:1], chave_de[a.id])].append(a)

    def mesma_turma(x: Aluno, y: Aluno) -> bool:
        return chave_de[x.id] == chave_de[y.id]

    pares: list[tuple[Aluno, Aluno, str, str, str]] = []
    for (letra, _turma), grupo in grupos.items():
        if not letra or len(grupo) < 2:
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
                    # 🟢 "alta" (pré-marcada, aprova em lote) quando é claramente
                    # a MESMA criança: nascimento igual corrobora, OU é a cópia de
                    # PLATAFORMA (a, não-piloto) de um aluno da LISTA PILOTO
                    # (titular) com nome COMPLETO — não um stub truncado
                    # ("ANA B"=="ANA B", que pode ser outra criança). Senão,
                    # 🔴 "revisar" (gêmeo/homônimo de verdade → o dono confere).
                    copia_de_piloto = (titular.da_lista_piloto
                                       and not a.da_lista_piloto
                                       and _nome_completo(a.nome))
                    conf = ("alta" if (_dob_concordante(a, titular) or copia_de_piloto)
                            else "revisar")
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
                # 🟡 "provável" (NÃO pré-marcada; um clique em "Selecionar todos"
                # une o grupo): o stub curto (loser, não-piloto) é a abreviação de
                # UM único aluno da LISTA PILOTO (survivor). Seguro para aprovar em
                # lote SE a lista estiver completa — por isso não pré-marca e avisa.
                # Sem âncora na lista (ninguém é piloto) → 🔴 "revisar" a uma.
                conf = ("provavel"
                        if (survivor.da_lista_piloto and not loser.da_lista_piloto)
                        else "revisar")
                pares.append((loser, survivor, conf, motivo, turma_de[loser.id][1]))

        # VARIAÇÃO DE GRAFIA / TYPO: nomes DIFERENTES mas quase iguais na mesma turma
        # normalizada, sem conflito de identidade — o motor único marca 'fraco'
        # (variante LUÍS/LUIZ E erro de digitação GABRYEL/GABRIEL, inclusive no 1º
        # nome). É o que a comparação por token-set EXATO deixava passar. SEMPRE
        # "revisar" (nunca pré-marca, nunca funde sozinho): similaridade não distingue
        # "LUÍS/LUIZ" (mesma criança) de "MARIA/MARTA" (diferentes) — só um humano
        # decide. Cada aluno aponta para o MELHOR parceiro (piloto > completo >
        # antigo): 3 fichas do mesmo aluno viram um LEQUE, nunca uma cadeia.
        ja_losers = {l.id for l, _s, *_ in pares}
        ordenado = sorted(grupo, key=lambda x: x.id)
        for a in ordenado:
            if a.id in ja_losers:
                continue                              # já sai por outro par
            parceiros = [b for b in ordenado
                         if b.id != a.id and mesma_turma(a, b)
                         and not _conflito_forte(a, b)
                         and plausivel(a.nome, b.nome) == "fraco"]
            # SÓ sugere quando há UM único parceiro de grafia (ambíguo → não sugere).
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
            "confianca": confianca,     # "alta" | "provavel" | "revisar"
            "motivo": motivo,
            "impacto": impactos.get(loser.id, _VAZIO),
        }
        for loser, survivor, confianca, motivo, turma in candidatos
    ]


def _plataformas_dos(db: Session, ids: set[int]) -> dict[int, frozenset[str]]:
    """aluno_id → conjunto de plataformas de onde ele tem dado (identidade externa,
    snapshot Matific/Elefante, leitura). Usado para saber se duas fichas de MESMO
    nome vêm de plataformas DIFERENTES (1 conta por plataforma = mesma criança)."""
    if not ids:
        return {}
    plats: dict[int, set[str]] = defaultdict(set)
    for aid, plat in db.execute(
        select(IdentidadeExterna.aluno_id, IdentidadeExterna.plataforma)
        .where(IdentidadeExterna.aluno_id.in_(ids))).all():
        plats[aid].add(plat)
    for modelo, nome in ((SnapshotMatific, "matific"), (SnapshotElefante, "elefante"),
                         (Leitura, "elefante")):
        for (aid,) in db.execute(
            select(modelo.aluno_id).where(modelo.aluno_id.in_(ids)).distinct()).all():
            plats[aid].add(nome)
    return {aid: frozenset(p) for aid, p in plats.items()}


def _colapsavel(edges: list[tuple], membros: list[Aluno],
                plataformas: dict[int, frozenset[str]], eh_cadeia: bool) -> bool:
    """Um COMPONENTE de 3+ fichas (LEQUE ou CADEIA) é seguro para colapsar num único
    perfil canônico? A régua é "1 criança com cópias de importação vs. crianças
    DIFERENTES".
    NÃO colapsa (fica para revisão manual) quando há sinal de crianças distintas:
      * VARIANTE de grafia (LUÍS/LUIZ é indistinguível de MARIA/MARTA — fuzzy);
      * 2+ membros da LISTA PILOTO — a lista é a matrícula OFICIAL, então 2 registros
        nela = 2 crianças matriculadas de verdade (gêmeos/homônimos reais);
      * CONFLITO forte (nascimento/RA/nº de chamada divergente);
      * NOME IDÊNTICO cujos dois registros NÃO vêm de plataformas diferentes: dois
        nomes iguais sem outro sinal são indistinguíveis de gêmeos. Só é seguro quando
        as cópias são de plataformas DISTINTAS (ex.: uma do Matific, outra do
        Elefante) — 1 conta por plataforma = a MESMA criança (decisão do dono)."""
    # VETOS DUROS (valem para LEQUE e CADEIA — qualquer colapso de 3+ fichas): um
    # grupo com variante de grafia, 2+ da Lista Piloto, ou QUALQUER par de membros
    # com conflito forte (nascimento/RA/nº de chamada divergente — inclusive entre
    # co-losers, que a detecção não compara) é crianças diferentes → não colapsa.
    if any(motivo == "variante" for _l, _s, motivo in edges):
        return False
    if sum(1 for a in membros if a.da_lista_piloto) >= 2:
        return False
    if any(_conflito_forte(a, b) for a, b in combinations(membros, 2)):
        return False
    # Heurística de nome idêntico SÓ em cadeia: exige plataformas distintas (1 conta
    # por plataforma = mesma criança). No leque legítimo o survivor é o piloto (sem
    # plataforma), então esta regra não se aplica — os vetos duros acima já bastam.
    if eh_cadeia:
        for loser, survivor, motivo in edges:
            if motivo == "nome_identico":
                pa = plataformas.get(loser.id, frozenset())
                pb = plataformas.get(survivor.id, frozenset())
                if not (pa and pb and pa.isdisjoint(pb)):
                    return False    # mesma plataforma / sem plataforma → possível gêmeo
    return True


def aplicar_deduplicacao(db: Session, escola_id: int, loser_ids: list[int],
                         usuario_id: int) -> dict:
    """APLICA só as fusões CONFIRMADAS (``loser_ids``). Recomputa os candidatos no
    servidor (fonte da verdade — o cliente só manda ids), agrupa em COMPONENTES
    conexos e funde cada componente num único perfil canônico. NÃO commita nem
    recalcula — o endpoint faz isso UMA vez no fim.

    LEQUE, CADEIA SEGURA e CADEIA AMBÍGUA:
      * LEQUE (A→S, B→S) → funde no S (como sempre).
      * CADEIA ESTRUTURAL (A→B→C só por abreviação/subconjunto, sem conflito) → é o
        MESMO aluno em várias formas abreviadas: colapsa TODAS no perfil mais
        completo automaticamente (resolve o "una um par por vez" sem trabalho manual).
      * CADEIA AMBÍGUA (tem nome idêntico=gêmeo, variante de grafia, ou conflito de
        identidade no meio) → NÃO colapsa; reporta para revisão manual (nunca funde
        crianças diferentes sem um humano decidir par a par)."""
    escolhidos = set(loser_ids or [])
    selecionados = [(loser, survivor, motivo)
                    for loser, survivor, _conf, motivo, _turma in _candidatos(db, escola_id)
                    if loser.id in escolhidos]

    # COMPONENTES conexos (une loser↔survivor): cada componente é 1 aluno real (se
    # colapsável) ou um nó ambíguo (se cadeia insegura).
    pai: dict[int, int] = {}

    def raiz(x: int) -> int:
        pai.setdefault(x, x)
        while pai[x] != x:
            pai[x] = pai[pai[x]]
            x = pai[x]
        return x

    def unir(a: int, b: int) -> None:
        pai[raiz(a)] = raiz(b)

    for loser, survivor, _m in selecionados:
        unir(loser.id, survivor.id)

    edges_por_comp: dict[int, list[tuple]] = defaultdict(list)
    membros_por_comp: dict[int, set[int]] = defaultdict(set)
    for loser, survivor, motivo in selecionados:
        r = raiz(loser.id)
        edges_por_comp[r].append((loser, survivor, motivo))
        membros_por_comp[r].update((loser.id, survivor.id))

    todos_ids = {i for ids in membros_por_comp.values() for i in ids}
    plataformas = _plataformas_dos(db, todos_ids)   # p/ decidir nome-idêntico em cadeia

    fundidos = 0
    falhas: list[dict] = []
    detalhes: list[dict] = []
    for r, edges in edges_por_comp.items():
        membros = [db.get(Aluno, i) for i in membros_por_comp[r]]
        if any(a is None or a.escola_id != escola_id or a.status != "ativo"
               for a in membros) or len(membros) < 2:
            for loser, _s, _m in edges:
                falhas.append({"loser_id": loser.id,
                               "motivo": "cadastro indisponível (já fundido?)"})
            continue

        losers = {loser.id for loser, _s, _m in edges}
        survivors = {survivor.id for _l, survivor, _m in edges}
        eh_cadeia = bool(losers & survivors)        # algum nó é survivor E loser
        # Todo colapso de 3+ fichas (LEQUE ou CADEIA) passa pelos vetos: um par
        # simples (2 membros) já foi validado pela detecção (que veta conflito).
        if len(membros) >= 3 and not _colapsavel(edges, membros, plataformas, eh_cadeia):
            for loser, _s, _m in edges:
                falhas.append({"loser_id": loser.id,
                               "motivo": "grupo ambíguo (nome idêntico/variante/conflito) — revise manualmente"})
            continue

        # Colapsa TODOS os membros no perfil canônico (Lista Piloto > nome mais
        # completo > menor id) — transforma a cadeia num leque e funde par a par.
        canonico = reduce(_melhor_perfil, membros)
        for m in membros:
            if m.id == canonico.id:
                continue
            try:
                with db.begin_nested():   # isola a falha do par; o lote segue
                    res = alunos_fusao.fundir_par(db, escola_id, canonico, m, usuario_id)
                fundidos += 1
                detalhes.append({"manter_id": canonico.id, "manter": res["manter_nome"],
                                 "removido": res["remover_nome"]})
            except Exception:   # noqa: BLE001
                falhas.append({"loser_id": m.id,
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
