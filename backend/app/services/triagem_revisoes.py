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
ID_DUPLICADO_NO_RELATORIO = "id_externo_duplicado_no_relatorio"
IDENTIDADE_DE_OUTRA_ESCOLA = "identidade_de_outra_escola"

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
    # Três situações (``_triar_um`` e a disputa entre pendências seguras): a ficha
    # já tem outra conta, ou outra conta numa pendência aberta leva a ela — nesta,
    # a ficha pode não ter conta nenhuma. O ``conflitos`` diz qual é.
    MULTI_IDENTIDADE: "outra conta desta plataforma também leva a esta ficha (já "
                      "vinculada a ela ou numa pendência aberta) — pode ser conta "
                      "duplicada ou outra criança",
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
    ID_DUPLICADO_NO_RELATORIO: "o mesmo identificador da plataforma veio em mais de "
                               "uma linha do relatório com nomes diferentes — a "
                               "conta não prova de quem são estes números",
    IDENTIDADE_DE_OUTRA_ESCOLA: "a conta da plataforma já é de um aluno de OUTRA "
                                "escola do Constela — só um gestor desta escola "
                                "confirma que ela é de uma criança daqui",
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


# --- o texto que a coordenação lê -------------------------------------------
# Evidências e conflitos vão para a gaveta de Revisões: a ficha é citada como a
# coordenação a vê na tela (nome e turma), nunca pelo id interno, e a conta da
# plataforma pelo nome da plataforma, nunca pelo identificador (UUID). Os ids
# continuam nos campos estruturados (``aluno_id``, ``irmas``).
_PLATAFORMA = {"matific": "Matific", "elefante": "Elefante Letrado"}
_SITUACAO = {"arquivado": "arquivada", "fora_lista_piloto": "fora da Lista Piloto",
             "transferido": "transferido"}


def _plataforma(plataforma: str | None) -> str:
    return _PLATAFORMA.get(plataforma or "", plataforma or "da plataforma")


def _ficha(ctx: ident.Contexto, aluno_id: int | None,
           rev: RevisaoIdentidade | None = None) -> str:
    """A ficha pelo nome e pela turma do ano ("JOANA LIMA (3º Ano)"). Fora do
    contexto da escola, o nome congelado na pendência; sem nenhum, uma descrição."""
    aluno = ctx.alunos.get(aluno_id) if aluno_id is not None else None
    nome = aluno.nome if aluno is not None else next(
        (c.get("nome") for c in ((rev.candidatos if rev is not None else None) or [])
         if isinstance(c, dict) and c.get("aluno_id") == aluno_id), None)
    if not nome:
        return "uma ficha que não é desta escola"
    turma = ctx.turma_do_aluno(aluno_id) if aluno is not None else None
    return f"{nome} ({turma.nome})" if turma is not None else nome


def _fichas(ctx: ident.Contexto, ids, rev: RevisaoIdentidade | None = None) -> str:
    return "; ".join(_ficha(ctx, aid, rev) for aid in ids)


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

    # Id externo DUPLICADO no relatório: a conta já vinculada NÃO desempata — ela
    # pode ser justamente a da outra criança. Nunca "segura".
    if rev.motivo == "id_externo_duplicado":
        caso.conflitos.append("O identificador da plataforma veio repetido no "
                              "relatório, com outro nome")
        return veredito(DECISAO_HUMANA, ID_DUPLICADO_NO_RELATORIO)

    # Conta já EFETIVA em OUTRA escola do Constela: nenhum vínculo DESTA escola
    # desempata (pode ser justamente a credencial da outra escola). Nunca "segura".
    if rev.motivo == "identidade_de_outra_escola":
        caso.conflitos.append("A conta da plataforma já está vinculada a um aluno de "
                              "outra escola do Constela")
        return veredito(DECISAO_HUMANA, IDENTIDADE_DE_OUTRA_ESCOLA)

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
            f"A conta {_plataforma(rev.plataforma)} desta linha foi aposentada na ficha "
            f"de {_ficha(ctx, aposentado, rev)}: os dados dela não valem mais, e "
            "reativá-la exige decisão explícita")
        return veredito(DECISAO_HUMANA, IDENTIDADE_APOSENTADA, aposentado)

    # ------------------------------------------------------------------ alvo
    # A identidade externa é a evidência mais forte do sistema — é o passo 1 do
    # próprio motor de decisão. A lista de candidatos foi CONGELADA na
    # importação, quando muitas vezes só havia um nome truncado; se o vínculo já
    # existe hoje, ele vale mais do que aquela lista velha.
    if dono is not None:
        if congelados and dono not in congelados:
            caso.conflitos.append(
                f"A conta {_plataforma(rev.plataforma)} desta linha pertence à ficha de "
                f"{_ficha(ctx, dono, rev)}, que não está entre as fichas candidatas")
            return veredito(DECISAO_HUMANA, CONFLITO_IDENTIDADE, dono)
        alvo = dono
        motivo_ok = IDENTIDADE_DESEMPATA if len(congelados) > 1 else IDENTIDADE_JA_VINCULADA
        caso.evidencias.append(f"A conta {_plataforma(rev.plataforma)} desta linha já "
                               f"está vinculada à ficha de {_ficha(ctx, alvo, rev)}")
        if len(congelados) > 1:
            outros = [c for c in congelados if c != alvo]
            caso.evidencias.append(
                "Nenhuma das outras fichas candidatas tem esta conta: "
                f"{_fichas(ctx, outros, rev)}")
    elif len(congelados) == 1:
        alvo, motivo_ok = congelados[0], CANDIDATO_UNICO_COMPATIVEL
        caso.evidencias.append(f"Candidato único registrado: {_ficha(ctx, alvo, rev)}")
    elif not congelados:
        return veredito(DECISAO_HUMANA, SEM_CANDIDATO)
    else:
        # Vários candidatos e NENHUMA identidade que desempate. Não se escolhe
        # por nome parecido, por ordem da lista nem por volume de dados.
        caso.conflitos.append(
            f"{len(congelados)} fichas candidatas, e "
            + ("a conta da plataforma não pertence a nenhuma delas" if id_externo
               else "a linha não traz a conta da plataforma"))
        for ordem, aid in enumerate(congelados, start=1):
            turma = ctx.turma_do_aluno(aid)
            if turma is not None:
                codigo = f" (código {turma.codigo_externo})" if turma.codigo_externo else ""
                caso.evidencias.append(
                    f"{ordem}ª ficha candidata: {_ficha(ctx, aid, rev)}{codigo}")
        return veredito(DECISAO_HUMANA, AMBIGUA)

    # --------------------------------------------------------- portões do alvo
    aluno = ctx.alunos.get(alvo)
    if aluno is None:
        caso.conflitos.append("A ficha candidata não pertence a esta escola")
        return veredito(DECISAO_HUMANA, SEM_CANDIDATO, alvo)
    if aluno.status == "excluido":
        caso.conflitos.append("A ficha foi excluída")
        return veredito(DECISAO_HUMANA, FICHA_EXCLUIDA, alvo)

    # Transferência / fora da lista piloto NÃO significa "outra criança": a
    # identidade continua valendo. Mas aplicar dado a uma ficha fora do ranking é
    # decisão de gestão — a não ser que um humano já tenha escolhido esta ficha.
    if aluno.status in ident.STATUS_INATIVOS:
        if humano == alvo:
            caso.evidencias.append(
                "A ficha está fora do ranking (situação: "
                f"{_SITUACAO.get(aluno.status, aluno.status)}), mas um gestor já "
                "escolheu esta mesma ficha antes")
        else:
            caso.conflitos.append("A ficha está fora do ranking (situação: "
                                  f"{_SITUACAO.get(aluno.status, aluno.status)})")
            return veredito(DECISAO_HUMANA, FICHA_INATIVA, alvo)

    if not id_externo:
        caso.conflitos.append("A linha não traz identificador da plataforma")
        return veredito(DECISAO_HUMANA, SEM_IDENTIFICADOR, alvo)

    # Duas contas da MESMA plataforma na MESMA ficha: pode ser conta duplicada
    # (e aí uma delas deve sumir) ou duas crianças que viraram uma ficha só.
    # Nenhuma regra objetiva resolve — e escolher pela conta com mais atividades
    # seria inventar. Vai para decisão humana SEMPRE.
    outras = sorted(ctx.ids_do_aluno.get((alvo, rev.plataforma), set()) - {id_externo})
    if outras:
        caso.conflitos.append(f"A ficha de {_ficha(ctx, alvo, rev)} já tem outra(s) "
                              f"conta(s) {_plataforma(rev.plataforma)}")
        return veredito(DECISAO_HUMANA, MULTI_IDENTIDADE, alvo)
    # A mesma disputa com a outra conta AINDA SEM VÍNCULO, numa pendência aberta da
    # escola (lida no contexto, não só nesta página da fila): a conta desta pendência
    # pode ter levado a ficha só porque apareceu sozinha no arquivo seguinte da
    # coleta. Encerrar por aqui confirmaria um vínculo que ninguém decidiu.
    rivais = sorted(ctx.contas_rivais(rev.plataforma, alvo, id_externo))
    if rivais:
        caso.conflitos.append(f"Outra pendência aberta liga a ficha de "
                              f"{_ficha(ctx, alvo, rev)} a uma conta "
                              f"{_plataforma(rev.plataforma)} diferente, ainda sem vínculo")
        return veredito(DECISAO_HUMANA, MULTI_IDENTIDADE, alvo)

    turma = ctx.turma_do_aluno(alvo)
    if turma is None:
        caso.conflitos.append("A ficha não tem matrícula no ano letivo ativo")
        return veredito(DECISAO_HUMANA, SEM_MATRICULA, alvo)

    # --------------------------------------------------------- sala e série
    codigo = _codigo_da_sala(rev.turma_informada)
    if codigo and turma.codigo_externo:
        if codigo == turma.codigo_externo:
            caso.evidencias.append(f"O código da turma do relatório ({codigo}) é o "
                                   f"da turma da ficha ({turma.nome})")
        else:
            caso.conflitos.append(
                f"O código da turma do relatório ({codigo}) não é o da turma da "
                f"ficha ({turma.nome}, código {turma.codigo_externo})")
            return veredito(DECISAO_HUMANA, SERIE_INCOMPATIVEL, alvo)

    serie_rel = serie_da_sala(rev.turma_informada or "")
    serie_ficha = serie_da_sala(turma.nome, getattr(turma, "ano_escolar", "") or "")
    if serie_rel is not None and serie_ficha is not None:
        if serie_rel != serie_ficha:
            caso.conflitos.append(f"A série do relatório ({serie_rel}º ano) não é a "
                                  f"da ficha ({serie_ficha}º ano)")
            return veredito(DECISAO_HUMANA, SERIE_INCOMPATIVEL, alvo)
        caso.evidencias.append(f"Série compatível ({serie_rel}º ano)")
    elif dono is None:
        # Sem identidade vinculada, a série é a única checagem de sala que resta.
        caso.conflitos.append(
            "Não dá para ler a série (turma do relatório: "
            f"{rev.turma_informada or 'não informada'}; turma da ficha: {turma.nome})")
        return veredito(DECISAO_HUMANA, SERIE_INDETERMINADA, alvo)

    if humano == alvo:
        caso.evidencias.append("Um gestor já escolheu esta ficha para esta conta")
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
            # Quais irmãs: em ``irmas`` (estruturado); no texto, só quantas.
            culpadas = [b.revisao_id for b in bloqueadas]
            resultado[v.revisao_id] = Triagem(
                revisao_id=v.revisao_id, classificacao=DECISAO_HUMANA,
                motivo=IRMA_BLOQUEADA, aluno_id=v.aluno_id,
                evidencias=v.evidencias,
                conflitos=v.conflitos + (
                    "Outra pendência da mesma conta exige decisão de um gestor"
                    if len(culpadas) == 1 else
                    f"{len(culpadas)} outras pendências da mesma conta exigem decisão "
                    "de um gestor",),
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
                    f"Outra pendência aberta liga a ficha de {_ficha(ctx, t.aluno_id, r)} "
                    f"a uma conta {_plataforma(r.plataforma)} diferente",),
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
                        "As pendências da mesma conta apontam para fichas diferentes: "
                        f"{_fichas(ctx, sorted(x for x in alvos if x), r)}",),
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
