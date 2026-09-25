"""Triagem EXPLICÁVEL da fila de revisão de identidade (§ porta única).

A fila de ``RevisaoIdentidade`` guarda as linhas que o motor de identidade não
soube decidir sozinho. Depois que um gestor (ou uma sincronização posterior) já
resolveu o vínculo, muita pendência fica ÓRFÃ: a identidade externa já aponta
para o aluno certo e só falta encerrar o registro. Outras, ao contrário, nunca
poderão ser decididas por máquina — duas contas na mesma ficha, vários candidatos
sem desempate objetivo, identidade que pertence a outra criança.

Este módulo responde UMA pergunta por pendência, com a resposta auditável:

    "dá para encerrar isto com segurança, e por quê?"

DETERMINÍSTICO E EXPLICÁVEL DE PROPÓSITO. Não existe score de confiança: ou há
uma evidência objetiva que sustenta a conclusão (identidade externa já vinculada,
código da turma do relatório, série, decisão humana anterior), ou o caso vai para
decisão humana com o motivo escrito. Um número de confiança só esconderia um
palpite — e um palpite errado aqui mistura os dados de duas crianças.

Serve a QUALQUER escola e QUALQUER plataforma: tudo que ele sabe vem do
``identidade_aluno.Contexto``, o mesmo estado que a importação usa. Não grava
nada; quem encerra a pendência continua sendo o ``/resolver`` oficial, com a
transação única e a guarda ``_retrato_superado``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.academico import RevisaoIdentidade
from app.services import identidade_aluno as ident
from app.services.matriculas import serie_da_sala

# --- classificações ---------------------------------------------------------
SEGURA = "segura"                  # dá para encerrar pelo /resolver oficial
DECISAO_HUMANA = "decisao_humana"  # só um humano pode decidir
ENCERRADA = "encerrada"            # já resolvida/descartada: nada a fazer

# --- motivos de SEGURA ------------------------------------------------------
IDENTIDADE_JA_VINCULADA = "identidade_ja_vinculada"
IDENTIDADE_DESEMPATA = "identidade_externa_desempata_candidatos"
CANDIDATO_UNICO_COMPATIVEL = "candidato_unico_compativel"

# --- motivos de DECISAO_HUMANA ---------------------------------------------
SEM_CANDIDATO = "sem_candidato"
CONFLITO_IDENTIDADE = "conflito_identidade"
MULTI_IDENTIDADE = "multi_identidade_mesmo_aluno"
AMBIGUA = "ambigua_decisao_humana"
SERIE_INCOMPATIVEL = "serie_incompativel"
SERIE_INDETERMINADA = "serie_indeterminada"
FICHA_INATIVA = "ficha_inativa"
FICHA_EXCLUIDA = "ficha_excluida"
SEM_MATRICULA = "sem_matricula_no_ano"
SEM_IDENTIFICADOR = "sem_identificador_externo"
IRMA_BLOQUEADA = "irma_bloqueada"
IDENTIDADE_APOSENTADA = "identidade_aposentada"

# Texto humano de cada motivo — a mesma frase vai para a API e para o relatório.
TEXTO = {
    IDENTIDADE_JA_VINCULADA: "a conta da plataforma já pertence a este aluno: "
                             "a pendência só não foi encerrada",
    IDENTIDADE_DESEMPATA: "entre os candidatos, a conta da plataforma já pertence "
                          "a exatamente um deles",
    CANDIDATO_UNICO_COMPATIVEL: "candidato único, turma e série compatíveis, "
                                "sem conta concorrente",
    SEM_CANDIDATO: "nenhum aluno corresponde — criar ficha é decisão de gestão",
    CONFLITO_IDENTIDADE: "a conta da plataforma pertence a outra ficha",
    MULTI_IDENTIDADE: "a ficha já tem outra conta nesta plataforma — pode ser "
                      "conta duplicada ou outra criança",
    AMBIGUA: "mais de um candidato e nenhuma evidência objetiva desempata",
    SERIE_INCOMPATIVEL: "a série do relatório não é a da ficha",
    SERIE_INDETERMINADA: "não dá para ler a série dos dois lados e não há "
                         "identidade que confirme",
    FICHA_INATIVA: "a ficha está fora do ranking (arquivada ou fora da lista piloto)",
    FICHA_EXCLUIDA: "a ficha foi excluída e não recebe dados",
    SEM_MATRICULA: "o candidato não tem matrícula no ano letivo ativo",
    SEM_IDENTIFICADOR: "a linha não traz identificador da plataforma — o vínculo "
                       "não é verificável",
    IRMA_BLOQUEADA: "outra pendência da MESMA identidade exige decisão humana, e "
                    "encerrar uma encerra todas",
    IDENTIDADE_APOSENTADA: "esta conta da plataforma foi aposentada nesta ficha: "
                           "o histórico está preservado, mas ela não alimenta mais "
                           "o retrato do aluno",
}


@dataclass(frozen=True)
class Triagem:
    """O veredito de uma pendência, legível por máquina e por gente."""

    revisao_id: int
    classificacao: str
    motivo: str
    aluno_id: int | None = None
    evidencias: tuple[str, ...] = ()
    conflitos: tuple[str, ...] = ()
    # None quando não se aplica (``leituras`` acumula, nunca é retrato).
    retrato_superado: bool | None = None
    irmas: tuple[int, ...] = ()

    @property
    def segura(self) -> bool:
        return self.classificacao == SEGURA

    def como_dict(self) -> dict:
        return {
            "classificacao": self.classificacao,
            "motivo": self.motivo,
            "motivo_texto": TEXTO.get(self.motivo, ""),
            "aluno_id": self.aluno_id,
            "evidencias": list(self.evidencias),
            "conflitos": list(self.conflitos),
            "retrato_superado": self.retrato_superado,
            "irmas": list(self.irmas),
        }


@dataclass
class _Caso:
    """O que se sabe de UMA pendência depois de cruzar com o estado da escola."""

    rev: RevisaoIdentidade
    evidencias: list[str] = field(default_factory=list)
    conflitos: list[str] = field(default_factory=list)


def _codigo_da_sala(texto: str | None) -> str | None:
    """Código externo da turma dentro do rótulo do relatório:
    "3 ANO A TARDE ANUAL (300309115)" → "300309115". É a evidência mais dura que
    o relatório carrega sobre a SALA, e o cadastro guarda o mesmo código em
    ``Turma.codigo_externo``."""
    texto = (texto or "").strip()
    if not texto.endswith(")") or "(" not in texto:
        return None
    codigo = texto[texto.rfind("(") + 1:-1].strip()
    return codigo or None


def _candidatos_congelados(rev: RevisaoIdentidade) -> list[int]:
    return [c["aluno_id"] for c in (rev.candidatos or [])
            if isinstance(c, dict) and c.get("aluno_id")]


def _triar_um(ctx: ident.Contexto, rev: RevisaoIdentidade,
              superado: bool | None, irmas: tuple[int, ...]) -> Triagem:
    """A decisão de UMA pendência. Cada retorno carrega o porquê."""
    caso = _Caso(rev)

    def veredito(classificacao: str, motivo: str, aluno_id: int | None = None) -> Triagem:
        return Triagem(revisao_id=rev.id, classificacao=classificacao, motivo=motivo,
                       aluno_id=aluno_id, evidencias=tuple(caso.evidencias),
                       conflitos=tuple(caso.conflitos), retrato_superado=superado,
                       irmas=irmas)

    if rev.status != "pendente":
        return veredito(ENCERRADA, rev.status, rev.aluno_escolhido_id)

    congelados = _candidatos_congelados(rev)
    id_externo = (rev.id_externo or "").strip()
    dono = ctx.identidade.get((rev.plataforma, id_externo)) if id_externo else None
    humano = ctx.resolvidas.get(rev.chave_identidade)

    # Conta APOSENTADA: a escola já decidiu que ela não representa a criança.
    # A pendência não é mais uma pergunta em aberto — é resíduo de uma decisão
    # tomada, e encerrar por aqui reassociaria os dados.
    if id_externo and (rev.plataforma, id_externo) in ctx.aposentadas:
        aposentado = ctx.aposentadas[(rev.plataforma, id_externo)]
        caso.conflitos.append(
            f"a conta {id_externo} foi aposentada na ficha {aposentado} — "
            "os dados dela não valem mais, e reativá-la exige decisão explícita")
        return veredito(DECISAO_HUMANA, IDENTIDADE_APOSENTADA, aposentado)

    # ------------------------------------------------------------------ alvo
    # A identidade externa é a evidência mais forte do sistema — é o passo 1 do
    # próprio motor de decisão. A lista de candidatos foi CONGELADA na
    # importação, quando muitas vezes só havia um nome truncado; se o vínculo já
    # existe hoje, ele vale mais do que aquela lista velha.
    if dono is not None:
        if congelados and dono not in congelados:
            caso.conflitos.append(
                f"a conta {id_externo} pertence à ficha {dono}, que não está "
                f"entre os candidatos registrados {congelados}")
            return veredito(DECISAO_HUMANA, CONFLITO_IDENTIDADE, dono)
        alvo = dono
        motivo_ok = IDENTIDADE_DESEMPATA if len(congelados) > 1 else IDENTIDADE_JA_VINCULADA
        caso.evidencias.append(f"a conta {rev.plataforma} {id_externo} já está "
                               f"vinculada à ficha {alvo}")
        if len(congelados) > 1:
            outros = [c for c in congelados if c != alvo]
            caso.evidencias.append(
                f"nenhum dos outros candidatos {outros} é dono desta conta")
    elif len(congelados) == 1:
        alvo, motivo_ok = congelados[0], CANDIDATO_UNICO_COMPATIVEL
        caso.evidencias.append(f"candidato único registrado: ficha {alvo}")
    elif not congelados:
        return veredito(DECISAO_HUMANA, SEM_CANDIDATO)
    else:
        # Vários candidatos e NENHUMA identidade que desempate. Não se escolhe
        # por nome parecido, por ordem da lista nem por volume de dados.
        caso.conflitos.append(f"{len(congelados)} candidatos {congelados} e a conta "
                              f"{id_externo or '(ausente)'} não pertence a nenhum deles")
        for aid in congelados:
            turma = ctx.turma_do_aluno(aid)
            if turma is not None:
                caso.evidencias.append(
                    f"ficha {aid} está em {turma.nome!r} "
                    f"(código {turma.codigo_externo or '—'})")
        return veredito(DECISAO_HUMANA, AMBIGUA)

    # --------------------------------------------------------- portões do alvo
    aluno = ctx.alunos.get(alvo)
    if aluno is None:
        caso.conflitos.append(f"a ficha {alvo} não pertence a esta escola")
        return veredito(DECISAO_HUMANA, SEM_CANDIDATO, alvo)
    if aluno.status == "excluido":
        caso.conflitos.append("a ficha foi excluída")
        return veredito(DECISAO_HUMANA, FICHA_EXCLUIDA, alvo)

    # Transferência / fora da lista piloto NÃO significa "outra criança": a
    # identidade continua valendo. Mas aplicar dado a uma ficha fora do ranking é
    # decisão de gestão — a não ser que um humano já tenha escolhido esta ficha.
    if aluno.status in ident.STATUS_INATIVOS:
        if humano == alvo:
            caso.evidencias.append(f"ficha {aluno.status}, mas um gestor já "
                                   f"escolheu esta mesma ficha antes")
        else:
            caso.conflitos.append(f"a ficha está com status {aluno.status!r}")
            return veredito(DECISAO_HUMANA, FICHA_INATIVA, alvo)

    if not id_externo:
        caso.conflitos.append("a linha não traz identificador da plataforma")
        return veredito(DECISAO_HUMANA, SEM_IDENTIFICADOR, alvo)

    # Duas contas da MESMA plataforma na MESMA ficha: pode ser conta duplicada
    # (e aí uma delas deve sumir) ou duas crianças que viraram uma ficha só.
    # Nenhuma regra objetiva resolve — e escolher pela conta com mais atividades
    # seria inventar. Vai para decisão humana SEMPRE.
    outras = sorted(ctx.ids_do_aluno.get((alvo, rev.plataforma), set()) - {id_externo})
    if outras:
        caso.conflitos.append(f"a ficha {alvo} já tem outra(s) conta(s) "
                              f"{rev.plataforma}: {outras}")
        return veredito(DECISAO_HUMANA, MULTI_IDENTIDADE, alvo)

    turma = ctx.turma_do_aluno(alvo)
    if turma is None:
        caso.conflitos.append("sem matrícula no ano letivo ativo")
        return veredito(DECISAO_HUMANA, SEM_MATRICULA, alvo)

    # --------------------------------------------------------- sala e série
    codigo = _codigo_da_sala(rev.turma_informada)
    if codigo and turma.codigo_externo:
        if codigo == turma.codigo_externo:
            caso.evidencias.append(f"o código da turma do relatório ({codigo}) é o "
                                   f"da turma da ficha ({turma.nome!r})")
        else:
            caso.conflitos.append(
                f"o código da turma do relatório ({codigo}) não é o da turma da "
                f"ficha ({turma.codigo_externo})")
            return veredito(DECISAO_HUMANA, SERIE_INCOMPATIVEL, alvo)

    serie_rel = serie_da_sala(rev.turma_informada or "")
    serie_ficha = serie_da_sala(turma.nome, getattr(turma, "ano_escolar", "") or "")
    if serie_rel is not None and serie_ficha is not None:
        if serie_rel != serie_ficha:
            caso.conflitos.append(f"série do relatório {serie_rel}ª ≠ série da ficha "
                                  f"{serie_ficha}ª")
            return veredito(DECISAO_HUMANA, SERIE_INCOMPATIVEL, alvo)
        caso.evidencias.append(f"série compatível ({serie_rel}ª ano)")
    elif dono is None:
        # Sem identidade vinculada, a série é a única checagem de sala que resta.
        caso.conflitos.append(
            f"série ilegível (relatório={rev.turma_informada!r}, ficha={turma.nome!r})")
        return veredito(DECISAO_HUMANA, SERIE_INDETERMINADA, alvo)

    if humano == alvo:
        caso.evidencias.append("um gestor já escolheu esta ficha para esta identidade")
    return veredito(SEGURA, motivo_ok, alvo)


def triar_revisoes(ctx: ident.Contexto, revisoes: list[RevisaoIdentidade],
                   superados: dict[int, bool] | None = None) -> dict[int, Triagem]:
    """Tria um conjunto de pendências da MESMA escola.

    ``superados`` é opcional e só informativo: ``{revisao_id: retrato_superado}``.
    Quem decide de verdade se o retrato se aplica continua sendo
    ``importacoes._retrato_superado``, no momento da resolução.

    CONTÁGIO ENTRE IRMÃS: o ``/resolver`` encerra todas as pendências da mesma
    ``chave_identidade`` numa transação só. Então uma irmã bloqueada bloqueia o
    grupo inteiro — senão encerrar a "segura" encerraria junto a que exige gente.
    """
    superados = superados or {}
    por_chave: dict[str, list[RevisaoIdentidade]] = {}
    for r in revisoes:
        if r.status == "pendente":
            por_chave.setdefault(r.chave_identidade, []).append(r)

    resultado: dict[int, Triagem] = {}
    for r in revisoes:
        grupo = por_chave.get(r.chave_identidade, [])
        irmas = tuple(sorted(x.id for x in grupo if x.id != r.id))
        resultado[r.id] = _triar_um(ctx, r, superados.get(r.id), irmas)

    for grupo in por_chave.values():
        ids = [r.id for r in grupo]
        vereditos = [resultado[i] for i in ids]
        bloqueadas = [v for v in vereditos if v.classificacao == DECISAO_HUMANA]
        if not bloqueadas:
            continue
        for v in vereditos:
            if v.classificacao != SEGURA:
                continue
            culpadas = [b.revisao_id for b in bloqueadas]
            resultado[v.revisao_id] = Triagem(
                revisao_id=v.revisao_id, classificacao=DECISAO_HUMANA,
                motivo=IRMA_BLOQUEADA, aluno_id=v.aluno_id,
                evidencias=v.evidencias,
                conflitos=v.conflitos + (
                    f"a(s) pendência(s) {culpadas} da mesma identidade exige(m) "
                    f"decisão humana",),
                retrato_superado=v.retrato_superado, irmas=v.irmas)

    # A MESMA situação de "duas contas" vista do outro lado: duas pendências
    # ABERTAS com contas DIFERENTES disputando a mesma ficha. Nenhuma das duas
    # está vinculada ainda, então nenhum portão individual as pega — mas encerrar
    # a primeira criaria exatamente o caso ``multi_identidade_mesmo_aluno``.
    por_id = {r.id: r for r in revisoes}
    disputa: dict[tuple[int, str], set[str]] = {}
    for t in resultado.values():
        r = por_id.get(t.revisao_id)
        if t.classificacao == SEGURA and r is not None and r.id_externo:
            disputa.setdefault((t.aluno_id, r.plataforma), set()).add(r.id_externo)
    for t in list(resultado.values()):
        r = por_id.get(t.revisao_id)
        if t.classificacao != SEGURA or r is None:
            continue
        contas = disputa.get((t.aluno_id, r.plataforma), set())
        if len(contas) > 1:
            resultado[t.revisao_id] = Triagem(
                revisao_id=t.revisao_id, classificacao=DECISAO_HUMANA,
                motivo=MULTI_IDENTIDADE, aluno_id=t.aluno_id,
                evidencias=t.evidencias,
                conflitos=t.conflitos + (
                    f"outra pendência aberta liga a ficha {t.aluno_id} a uma conta "
                    f"{r.plataforma} diferente: {sorted(contas)}",),
                retrato_superado=t.retrato_superado, irmas=t.irmas)

    # Alvos diferentes na MESMA identidade: encerrar uma escolheria pela outra.
    for grupo in por_chave.values():
        alvos = {resultado[r.id].aluno_id for r in grupo
                 if resultado[r.id].classificacao == SEGURA}
        if len(alvos) > 1:
            for r in grupo:
                v = resultado[r.id]
                resultado[r.id] = Triagem(
                    revisao_id=v.revisao_id, classificacao=DECISAO_HUMANA,
                    motivo=AMBIGUA, aluno_id=None, evidencias=v.evidencias,
                    conflitos=v.conflitos + (
                        f"irmãs da mesma identidade apontam para fichas "
                        f"diferentes: {sorted(x for x in alvos if x)}",),
                    retrato_superado=v.retrato_superado, irmas=v.irmas)
    return resultado


def triar_escola(db: Session, escola_id: int, *, situacao: str = "pendente",
                 ano: int | None = None) -> dict[int, Triagem]:
    """Tria a fila de uma escola carregando o contexto UMA vez."""
    consulta = select(RevisaoIdentidade).where(RevisaoIdentidade.escola_id == escola_id)
    if situacao != "todas":
        consulta = consulta.where(RevisaoIdentidade.status == situacao)
    revisoes = db.execute(consulta.order_by(RevisaoIdentidade.id)).scalars().all()
    if not revisoes:
        return {}
    ctx = ident.carregar_contexto(db, escola_id, ano)
    return triar_revisoes(ctx, list(revisoes), superados=_superados(db, revisoes))


def _superados(db: Session, revisoes: list[RevisaoIdentidade]) -> dict[int, bool]:
    """Retrato congelado × snapshot mais recente, só para o relatório.

    Importado aqui dentro de propósito: ``importacoes`` importa serviços, e
    importá-lo no topo deste módulo fecharia um ciclo."""
    from app.routers.importacoes import _retrato_superado

    fora: dict[int, bool] = {}
    for r in revisoes:
        alvo = r.aluno_escolhido_id or next(
            (c.get("aluno_id") for c in (r.candidatos or []) if c.get("aluno_id")), None)
        if alvo is None or r.formato == "leituras":
            continue
        try:
            fora[r.id] = _retrato_superado(db, r.escola_id, alvo, r) is not None
        except Exception:                                  # nunca derruba a fila
            continue
    return fora


def resumo(triagens: dict[int, Triagem]) -> dict[str, int]:
    """Contagem por motivo — a linha de uma escola no relatório da rede."""
    contagem: dict[str, int] = {}
    for t in triagens.values():
        chave = t.classificacao if t.classificacao == ENCERRADA else \
            f"{t.classificacao}:{t.motivo}"
        contagem[chave] = contagem.get(chave, 0) + 1
    return dict(sorted(contagem.items()))
