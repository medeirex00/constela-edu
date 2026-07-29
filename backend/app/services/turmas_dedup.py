"""Consolidação de TURMAS duplicadas.

A mesma sala pode ter sido criada com nomes diferentes vindos de fontes
distintas — ex.: "1 ANO A TARDE ANUAL (300302821)" (arquivo oficial/SED) e
"1ºA" (Lista Piloto). Como a identidade da turma no banco é o NOME exato
(uq_turma_escola_ano_nome), viram DUAS turmas.

Aqui detectamos os grupos pela chave canônica (série · letra · turno — ver
`matriculas.chave_canonica`, conservadora: só agrupa o que reconhece) e
consolidamos MOVENDO as matrículas da duplicada para a canônica (o nome curto
padronizado), herdando o titular quando a canônica não tem, e removendo a turma
duplicada já vazia. Mover matrícula é seguro: a unicidade é (aluno, ano_letivo),
então cada aluno tem UMA matrícula no ano — repontar `turma_id` nunca colide.

NÃO fundimos alunos automaticamente (unir pessoas por nome é arriscado): apenas
REPORTAMOS quantos nomes aparecem repetidos na turma final, para o gestor revisar
com "Fundir alunos".
"""
from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Aluno, Matricula, Turma
from app.services import matriculas as mat

# Palavras administrativas que, no NOME da turma, indicam a forma "longa" (menos
# canônica). Usadas só para pontuar qual nome do grupo é o preferido.
_ADMIN = frozenset({
    "ano", "anos", "serie", "anual", "semestral", "turma", "sala",
    "manha", "tarde", "noite", "integral", "matutino", "vespertino", "noturno",
})


def _pontuar_nome(nome: str) -> tuple[int, int]:
    """Quanto MENOR, mais canônico/curto/padronizado — o preferido do grupo.
    "1ºA" vence "1 ANO A TARDE ANUAL (300302821)"."""
    penal = 0
    if "(" in nome and any(c.isdigit() for c in nome.split("(", 1)[1]):
        penal += 100                                  # tem código entre parênteses
    tokens = mat.normalizar(nome).split()
    penal += 8 * sum(1 for t in tokens if t in _ADMIN)  # palavras administrativas
    return (penal, len(nome))


def _alunos_ativos(db: Session, turma: Turma) -> int:
    return db.execute(
        select(func.count()).select_from(Matricula)
        .join(Aluno, Aluno.id == Matricula.aluno_id)
        .where(Matricula.turma_id == turma.id,
               Matricula.ano_letivo == turma.ano_letivo,
               Aluno.status == "ativo")
    ).scalar() or 0


def _grupo_consolidavel(db: Session, ts: list[Turma], ano: int, chave: str) -> dict | None:
    """Monta o descritor de UM grupo de turmas que são a mesma sala. Devolve
    ``None`` quando não deve ser consolidado (só 1 turma, ou titulares
    diferentes). Escolhe a canônica por prioridade e lista as duplicadas."""
    if len(ts) < 2:
        return None
    # GUARDA (professores diferentes = grupos distintos): se duas turmas do
    # grupo têm titulares DIFERENTES, não são a mesma sala → não unir.
    professores = {t.professor_id for t in ts if t.professor_id is not None}
    if len(professores) >= 2:
        return None
    # PRIORIDADE da turma principal (canônica), nesta ordem:
    #   1) a que TEM professor vinculado;
    #   2) a com MAIS alunos;
    #   3) o nome mais curto/padronizado (_pontuar_nome);
    #   4) desempate estável por id.
    alunos = {t.id: _alunos_ativos(db, t) for t in ts}
    ordenadas = sorted(ts, key=lambda t: (0 if t.professor_id is not None else 1,
                                          -alunos[t.id], *_pontuar_nome(t.nome), t.id))
    canonica, *duplicadas = ordenadas
    return {
        "chave": chave,
        "ano_letivo": ano,
        "canonica": {"id": canonica.id, "nome": canonica.nome,
                     "turno": canonica.turno, "alunos": alunos[canonica.id]},
        "duplicadas": [{"id": d.id, "nome": d.nome, "turno": d.turno,
                        "alunos": alunos[d.id]} for d in duplicadas],
    }


def detectar(db: Session, escola_id: int) -> list[dict]:
    """Grupos de turmas ATIVAS que são a mesma sala (mesma série · letra no mesmo
    ano letivo). Cada grupo traz a canônica sugerida + TODAS as duplicadas — 2,
    3 ou 4 registros da mesma sala são consolidados de uma vez.

    O agrupamento ignora o TURNO de propósito: cópias da mesma sala que vieram
    SEM turno (ex.: Matific/Elefante gravam "1º Ano A") caem no mesmo grupo das
    que têm turno ("1ºA" tarde, "1 ANO A TARDE ANUAL"). Só quando há CONFLITO
    real de turno no grupo — manhã E tarde juntos — é que separamos por turno
    (são salas distintas; item 7), deixando as cópias sem turno de fora (não dá
    para saber a qual delas pertencem)."""
    turmas = db.execute(
        select(Turma).where(Turma.escola_id == escola_id, Turma.status == "ativa")
    ).scalars().all()

    # Base do grupo = (ano_letivo, série, letra) SEM o turno. Guarda junto o
    # código de turno de cada turma (''=desconhecido) para decidir conflitos.
    grupos: dict[tuple[int, str, str], list[tuple[Turma, str]]] = {}
    for t in turmas:
        chave = mat.chave_canonica(t.nome, t.ano_escolar or "", t.turno)
        # Só agrupa o que a chave RECONHECEU (contém "|"): nomes fora do padrão
        # série+letra (Maternal, Pré, EJA, AEE, Multi…) nunca são fundidos.
        if "|" not in chave:
            continue
        num, letra, tcode = chave.split("|")
        grupos.setdefault((t.ano_letivo, num, letra), []).append((t, tcode))

    resultado: list[dict] = []
    for (ano, num, letra), ts_turno in grupos.items():
        turnos = {tc for _, tc in ts_turno if tc}
        if len(turnos) >= 2:
            # CONFLITO real de turno (manhã × tarde): salas distintas. Consolida
            # só DENTRO de cada turno conhecido; as cópias sem turno ficam de
            # fora (ambíguas — poderiam ser de qualquer um dos turnos).
            por_turno: dict[str, list[Turma]] = {}
            for t, tc in ts_turno:
                if tc:
                    por_turno.setdefault(tc, []).append(t)
            for tc, ts in por_turno.items():
                grupo = _grupo_consolidavel(db, ts, ano, f"{num}|{letra}|{tc}")
                if grupo:
                    resultado.append(grupo)
        else:
            # 0 ou 1 turno conhecido → mesma sala: funde TODAS as cópias (2, 3,
            # 4…), inclusive as sem turno, sob o turno conhecido (ou vazio).
            tc = turnos.pop() if turnos else ""
            grupo = _grupo_consolidavel(db, [t for t, _ in ts_turno], ano, f"{num}|{letra}|{tc}")
            if grupo:
                resultado.append(grupo)

    # As com mais duplicatas primeiro (mais "sujas").
    resultado.sort(key=lambda g: len(g["duplicadas"]), reverse=True)
    return resultado


def consolidar(db: Session, escola_id: int, canonica_id: int,
               duplicada_ids: list[int]) -> dict:
    """Move as matrículas das turmas `duplicada_ids` para a `canonica_id`,
    herda o titular quando a canônica não tem, remove as turmas duplicadas (já
    vazias) e devolve um resumo. Sem commit — o chamador decide."""
    canonica = db.get(Turma, canonica_id)
    if canonica is None or canonica.escola_id != escola_id:
        raise ValueError("Turma canônica inválida para esta escola.")

    ids = [i for i in dict.fromkeys(duplicada_ids) if i != canonica_id]
    alvos: list[Turma] = []
    for did in ids:
        dup = db.get(Turma, did)
        if dup is None or dup.escola_id != escola_id:
            raise ValueError("Uma das turmas duplicadas não pertence a esta escola.")
        alvos.append(dup)

    movidos = 0
    for dup in alvos:
        if canonica.professor_id is None and dup.professor_id is not None:
            canonica.professor_id = dup.professor_id      # herda o titular
        if not canonica.turno and dup.turno:
            canonica.turno = dup.turno                     # herda o turno conhecido
        dup.professor_id = None                            # solta antes de excluir
        for m in db.execute(
            select(Matricula).where(Matricula.turma_id == dup.id)
        ).scalars().all():
            m.turma_id = canonica.id                       # seguro (1 matrícula/aluno/ano)
            movidos += 1

    db.flush()
    for dup in alvos:
        db.delete(dup)                                     # agora vazia

    # Possíveis alunos duplicados (mesma pessoa 2×) na turma final — para revisar
    # em "Fundir alunos". NÃO fundimos automaticamente (unir por nome é arriscado).
    nomes = db.execute(
        select(Aluno.nome)
        .join(Matricula, Matricula.aluno_id == Aluno.id)
        .where(Matricula.turma_id == canonica.id,
               Matricula.ano_letivo == canonica.ano_letivo,
               Aluno.status == "ativo")
    ).scalars().all()
    contagem = Counter(mat.normalizar(n) for n in nomes)
    possiveis_duplicados = sum(1 for c in contagem.values() if c > 1)

    return {
        "canonica_id": canonica.id,
        "canonica_nome": canonica.nome,
        "turmas_removidas": len(alvos),
        "alunos_movidos": movidos,
        "possiveis_alunos_duplicados": possiveis_duplicados,
    }
