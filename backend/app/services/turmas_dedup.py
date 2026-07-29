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


def _grupo_consolidavel(db: Session, ts: list[Turma], ano: int, chave: str,
                        campo: dict[int, str]) -> dict | None:
    """Monta o descritor de UM grupo de turmas que são a mesma sala. Devolve
    ``None`` quando não deve ser consolidado (só 1 turma, ou titulares REAIS
    diferentes). Escolhe a canônica por prioridade e lista as duplicadas.
    ``campo`` = ``{turma_id: código de turno do CAMPO}`` ('' = shell sem turno)."""
    if len(ts) < 2:
        return None
    # GUARDA de professor, mas SÓ entre salas REAIS (com turno no campo): duas
    # salas reais de titulares diferentes não se unem (item 7). Já os shells
    # administrativos do SED ("2 ANO A INTEGRAL", turno vazio) trazem professor
    # NOMINAL/errado e NÃO devem impedir a fusão na sala real — foi o que deixava
    # "5ºB" (PRISCILA) e "5 ANO B INTEGRAL" (FRANCIELLI) como duplicatas.
    profs_reais = {t.professor_id for t in ts
                   if t.professor_id is not None and campo.get(t.id)}
    if len(profs_reais) >= 2:
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

    Turno: o único sinal CONFIÁVEL é o CAMPO `turno` (vem da Lista Piloto). O
    turno embutido no NOME (SED: "INTEGRAL", "MANHA") é ruído — só é usado como
    desempate quando NENHUMA turma da sala tem turno no campo. Assim, "2ºA"
    (tarde) e "2 ANO A INTEGRAL"/"3 ANO A MANHA" (turno só no nome, campo vazio)
    são reconhecidas como a MESMA sala e fundidas — mesmo numa escola sem turno
    integral. Só há separação quando existem DOIS turnos REAIS de campo na mesma
    série·letra (manhã E tarde de verdade)."""
    turmas = db.execute(
        select(Turma).where(Turma.escola_id == escola_id, Turma.status == "ativa")
    ).scalars().all()

    # Base do grupo = (ano_letivo, série, letra) — SEM turno.
    grupos: dict[tuple[int, str, str], list[Turma]] = {}
    for t in turmas:
        chave = mat.chave_canonica(t.nome, t.ano_escolar or "", t.turno)
        # Só agrupa o que a chave RECONHECEU (contém "|"): nomes fora do padrão
        # série+letra (Maternal, Pré, EJA, AEE, Multi…) nunca são fundidos.
        if "|" not in chave:
            continue
        num, letra, _turno = chave.split("|")
        grupos.setdefault((t.ano_letivo, num, letra), []).append(t)

    resultado: list[dict] = []
    for (ano, num, letra), ts in grupos.items():
        campo = {t.id: mat.turno_codigo(t.turno) for t in ts}   # turno CONFIÁVEL
        do_campo = {c for c in campo.values() if c}
        if do_campo:
            efetivo = dict(campo)                    # shells (campo '') ficam ''
            turnos = do_campo
        else:
            # Ninguém tem turno no campo → cai para o turno do NOME (fraco).
            efetivo = {t.id: mat.turno_do_nome(t.nome) for t in ts}
            turnos = {c for c in efetivo.values() if c}

        if len(turnos) >= 2:
            # CONFLITO real de turno (manhã × tarde): salas distintas. Consolida
            # dentro de cada turno; as sem turno definido (shells) ficam de fora
            # (ambíguas — poderiam pertencer a qualquer um dos turnos).
            por_turno: dict[str, list[Turma]] = {}
            for t in ts:
                if efetivo[t.id]:
                    por_turno.setdefault(efetivo[t.id], []).append(t)
            for tc, grupo_ts in por_turno.items():
                grupo = _grupo_consolidavel(db, grupo_ts, ano, f"{num}|{letra}|{tc}", campo)
                if grupo:
                    resultado.append(grupo)
        else:
            # 0 ou 1 turno → mesma sala: funde TODAS as cópias (2, 3, 4…),
            # inclusive shells, sob o turno conhecido (ou vazio).
            tc = next(iter(turnos)) if turnos else ""
            grupo = _grupo_consolidavel(db, ts, ano, f"{num}|{letra}|{tc}", campo)
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
