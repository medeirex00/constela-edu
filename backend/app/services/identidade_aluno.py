"""PORTA ÚNICA de identidade das linhas de PLATAFORMA (Elefante/Matific).

Decide, para cada linha importada/sincronizada, DE QUEM são aqueles dados — e é
o MESMO cálculo na PRÉVIA (``importacao.casar_nomes``) e na CONFIRMAÇÃO
(``routers.importacoes._resolver_aluno``): a prévia mostra exatamente o que a
confirmação fará, e a sincronização automática não tem atalho próprio.

Ordem (mais forte primeiro — ver ``decidir``):
  1. identidade externa (UUID do Matific / studentId do Elefante) já vinculada;
  2. RA;
  3. sala informada (escola + série + letra, TODAS as turmas da sala): nome
     idêntico único → chamada/RA/nascimento corroborando → candidato ÚNICO
     estruturalmente plausível (``matching.classificar_linha``);
  4. homônimo EXATO fora da sala (outra turma, outra série) → revisão, nunca
     vínculo;
  5. revisão sempre que houver candidato e nenhum for seguro;
  6. criação SÓ quando não houver candidato algum.

Nunca escolhe "o primeiro" candidato, nunca funde fichas (fusão é ação
administrativa explícita) e nunca cria ficha nova quando a identidade externa
pertence a uma ficha existente — nem se ela estiver inativa. Ficha EXCLUÍDA não
é reutilizada: não é candidata e não segura identidade externa.

Este módulo só LÊ o banco (``Contexto`` é carregado uma vez por importação e
atualizado em memória pelo chamador a cada aluno criado/identidade vinculada).
Quem grava é o router — inclusive a fila de revisão (``RevisaoIdentidade``).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Aluno, Escola, IdentidadeExterna, Matricula, Turma
from app.models.academico import RevisaoIdentidade
from app.services import matching
from app.services.importacao import chave_nome
from app.services.lista_piloto import ra_util

ASSOCIAR = "associar"   # dados vão para uma ficha existente
REVISAR = "revisar"     # há candidato(s), nenhum seguro: não associa, não cria
CRIAR = "criar"         # nenhum candidato plausível: ficha nova
IGNORAR = "ignorar"     # entrada inválida (aluno de outra escola/excluído)

STATUS_INATIVOS = ("arquivado", "fora_lista_piloto")

# Campo de ``dados`` que carrega o id do aluno em cada plataforma.
CAMPO_ID_EXTERNO = {"matific": "matific_uuid", "elefante": "elefante_student_id"}

# Rótulos humanos dos motivos de revisão (mensagem ao gestor e à API).
MOTIVOS = {
    "identidade_de_ficha_inativa": "a identidade da plataforma pertence a uma ficha inativa",
    "identidade_de_outro_aluno": "a identidade da plataforma já pertence a outro aluno",
    "outra_identidade_na_plataforma": "o aluno encontrado já tem outra conta nesta plataforma",
    "ficha_inativa": "o único candidato está com a ficha inativa",
    "correspondencia_insegura": "nome parecido, mas a correspondência não é segura",
    "candidatos_multiplos": "mais de um aluno plausível na sala",
    "homonimo_em_outra_sala": "há aluno com o mesmo nome em outra turma/série",
    "nome_casa_em_outra_sala": "o nome corresponde a aluno de outra turma/série",
    "ra_repetido": "o RA aponta para mais de um aluno",
    "turma_ambigua": "mais de uma turma cadastrada corresponde à sala do relatório",
    "turma_nao_cadastrada": "a turma do relatório não existe no cadastro da escola",
    "sem_turma": "a linha não informa turma e nenhum aluno corresponde ao nome",
}


def plataforma_da_linha(dados: dict | None, padrao: str | None = None) -> str:
    """Plataforma da linha: a informada pelo import; sem ela, deduzida do campo de
    identidade presente nos dados."""
    if padrao:
        return padrao
    dados = dados or {}
    for plataforma, campo in CAMPO_ID_EXTERNO.items():
        if str(dados.get(campo) or "").strip():
            return plataforma
    return ""


def id_externo_da_linha(plataforma: str, dados: dict | None) -> str:
    campo = CAMPO_ID_EXTERNO.get(plataforma)
    return str((dados or {}).get(campo) or "").strip() if campo else ""


def ra_forte(valor) -> str:
    """RA utilizável como identidade (``lista_piloto.ra_util``), normalizado dos DOIS
    lados de toda comparação."""
    return ra_util(valor)


def identidade_do_aluno(aluno: Aluno) -> matching.Identidade:
    """Aluno do banco → ``matching.Identidade`` (a moeda do motor único)."""
    return matching.Identidade(
        id=aluno.id, nome=aluno.nome, chamada=aluno.numero_chamada,
        nascimento=aluno.data_nascimento,
        ra=ra_forte((aluno.ficha or {}).get("ra")),
        da_lista_piloto=bool(aluno.da_lista_piloto))


def chave_sala(nome_turma: str) -> str:
    from app.services.matriculas import chave_turma_norm
    return chave_turma_norm(nome_turma or "")


def _sala_parseavel(chave: str) -> bool:
    """A chave traz série E letra ("5|A")? Só então a sala informada é contexto
    confiável para dizer "este homônimo está em OUTRA sala"."""
    num, _, letra = chave.partition("|")
    return bool(num and letra)


# ---------------------------------------------------------------------------
# Entrada e saída
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LinhaIdentidade:
    nome: str
    plataforma: str = ""
    id_externo: str = ""
    turma_nome: str = ""               # turma informada (relatório/linha)
    turma_id: int | None = None        # turma escolhida explicitamente
    ra: str = ""
    chamada: int | None = None
    nascimento: date | None = None
    aluno_id: int | None = None        # escolha EXPLÍCITA de um humano


def _chamada(dados: dict) -> int | None:
    bruto = str(dados.get("numero_chamada") or dados.get("chamada") or "").strip()
    return int(bruto) if bruto.isdigit() else None


def _nascimento(dados: dict) -> date | None:
    valor = dados.get("data_nascimento") or dados.get("nascimento")
    if isinstance(valor, date):
        return valor
    texto = str(valor or "").strip()[:10]
    try:
        return date.fromisoformat(texto) if texto else None
    except ValueError:
        return None


def linha_de_dados(nome: str, dados: dict | None, *, plataforma: str | None = None,
                   turma_nome: str = "", turma_id: int | None = None,
                   aluno_id: int | None = None) -> LinhaIdentidade:
    """Monta a ``LinhaIdentidade`` a partir da linha importada — UM só lugar, usado
    pela prévia e pela confirmação (mesmos campos, mesma normalização)."""
    dados = dados or {}
    plat = plataforma_da_linha(dados, plataforma)
    return LinhaIdentidade(
        nome=nome or "", plataforma=plat, id_externo=id_externo_da_linha(plat, dados),
        turma_nome=(turma_nome or "").strip(), turma_id=turma_id,
        ra=str(dados.get("ra") or "").strip(), chamada=_chamada(dados),
        nascimento=_nascimento(dados), aluno_id=aluno_id)


@dataclass(frozen=True)
class Decisao:
    acao: str                          # ASSOCIAR | REVISAR | CRIAR | IGNORAR
    aluno_id: int | None = None        # associado (ASSOCIAR) ou sugerido (REVISAR)
    via: str = ""                      # identidade|ra|exato|identificador|abreviacao|…
    motivo: str = ""                   # por que REVISAR/IGNORAR
    candidatos: tuple[int, ...] = ()
    turma_id: int | None = None        # onde criar (CRIAR) / turma da sala (REVISAR)
    chave_sala: str = ""
    vetados: tuple[int, ...] = ()      # nome casava, identidade provou outra criança


# ---------------------------------------------------------------------------
# Estado da escola (lido uma vez; o chamador o mantém vivo durante o import)
# ---------------------------------------------------------------------------

@dataclass
class Contexto:
    escola_id: int
    ano: int
    alunos: dict[int, Aluno] = field(default_factory=dict)
    identidade: dict[tuple[str, str], int] = field(default_factory=dict)
    ids_do_aluno: dict[tuple[int, str], set[str]] = field(default_factory=dict)
    turmas: dict[int, Turma] = field(default_factory=dict)
    turmas_da_sala: dict[str, list[int]] = field(default_factory=dict)
    alunos_da_sala: dict[str, set[int]] = field(default_factory=dict)
    turma_de: dict[int, int] = field(default_factory=dict)
    por_nome: dict[str, set[int]] = field(default_factory=dict)
    por_ra: dict[str, set[int]] = field(default_factory=dict)
    # decisões de revisão já tomadas por um humano, por chave de identidade
    resolvidas: dict[str, int] = field(default_factory=dict)
    _memo_escola: dict = field(default_factory=dict, repr=False)

    # --- manutenção em memória -------------------------------------------
    def registrar_aluno(self, aluno: Aluno) -> None:
        self._memo_escola.clear()
        self.alunos[aluno.id] = aluno
        if aluno.status == "excluido":
            return
        chave = chave_nome(aluno.nome)
        if chave:
            self.por_nome.setdefault(chave, set()).add(aluno.id)
        ra = ra_forte((aluno.ficha or {}).get("ra"))
        if ra:
            self.por_ra.setdefault(ra, set()).add(aluno.id)

    def registrar_turma(self, turma: Turma) -> None:
        self.turmas[turma.id] = turma
        ids = self.turmas_da_sala.setdefault(chave_sala(turma.nome), [])
        if turma.id not in ids:
            ids.append(turma.id)
            ids.sort()

    def registrar_matricula(self, aluno_id: int, turma_id: int) -> None:
        self._memo_escola.clear()
        turma = self.turmas.get(turma_id)
        if turma is not None:
            self.alunos_da_sala.setdefault(chave_sala(turma.nome), set()).add(aluno_id)
            self.turma_de[aluno_id] = turma_id

    def vincular(self, aluno_id: int, plataforma: str, id_externo: str) -> None:
        if not (plataforma and id_externo):
            return
        antigo = self.identidade.get((plataforma, id_externo))
        if antigo is not None and antigo != aluno_id:
            self.ids_do_aluno.get((antigo, plataforma), set()).discard(id_externo)
        self.identidade[(plataforma, id_externo)] = aluno_id
        self.ids_do_aluno.setdefault((aluno_id, plataforma), set()).add(id_externo)

    # --- leitura ------------------------------------------------------------
    def ativo(self, aluno_id: int | None) -> Aluno | None:
        a = self.alunos.get(aluno_id) if aluno_id is not None else None
        return a if a is not None and a.status != "excluido" else None

    def roster(self, chave: str) -> list[Aluno]:
        return [self.alunos[i] for i in sorted(self.alunos_da_sala.get(chave, ()))
                if i in self.alunos and self.alunos[i].status != "excluido"]

    def classificar_na_escola(self, ident: matching.Identidade,
                              excluir_sala: str | None = None) -> matching.Resultado:
        """O motor contra a escola INTEIRA (fichas não excluídas, sem nº de chamada),
        fora da sala ``excluir_sala`` — para saber se o nome casa em OUTRA turma.
        Memorizado por identidade da linha (um relatório individual repete o mesmo
        aluno em cada livro)."""
        chave = (chave_nome(ident.nome), ident.ra, ident.nascimento, excluir_sala)
        if chave not in self._memo_escola:
            fora = self.alunos_da_sala.get(excluir_sala, set()) if excluir_sala else set()
            roster = [replace(identidade_do_aluno(a), chamada=None)
                      for a in self.alunos.values()
                      if a.status != "excluido" and a.id not in fora]
            self._memo_escola[chave] = matching.classificar_linha(ident, roster)
        return self._memo_escola[chave]

    def turma_do_aluno(self, aluno_id: int) -> Turma | None:
        tid = self.turma_de.get(aluno_id)
        return self.turmas.get(tid) if tid is not None else None


def carregar_contexto(db: Session, escola_id: int, ano: int | None = None) -> Contexto:
    if ano is None:
        escola = db.get(Escola, escola_id)
        ano = escola.ano_letivo_ativo if escola else 0
    ctx = Contexto(escola_id=escola_id, ano=ano or 0)
    for aluno in db.execute(
            select(Aluno).where(Aluno.escola_id == escola_id).order_by(Aluno.id)).scalars():
        ctx.registrar_aluno(aluno)
    for turma in db.execute(
            select(Turma).where(Turma.escola_id == escola_id, Turma.ano_letivo == ctx.ano)
            .order_by(Turma.id)).scalars():
        ctx.registrar_turma(turma)
    for aluno_id, turma_id in db.execute(
            select(Matricula.aluno_id, Matricula.turma_id)
            .where(Matricula.escola_id == escola_id, Matricula.ano_letivo == ctx.ano)).all():
        ctx.registrar_matricula(aluno_id, turma_id)
    for plataforma, id_externo, aluno_id in db.execute(
            select(IdentidadeExterna.plataforma, IdentidadeExterna.id_externo,
                   IdentidadeExterna.aluno_id)
            .where(IdentidadeExterna.escola_id == escola_id)
            .order_by(IdentidadeExterna.id)).all():
        ctx.vincular(aluno_id, plataforma, str(id_externo))
    for chave_ident, aluno_id in db.execute(
            select(RevisaoIdentidade.chave_identidade, RevisaoIdentidade.aluno_escolhido_id)
            .where(RevisaoIdentidade.escola_id == escola_id,
                   RevisaoIdentidade.status == "resolvida",
                   RevisaoIdentidade.aluno_escolhido_id.is_not(None))
            .order_by(RevisaoIdentidade.resolvida_em, RevisaoIdentidade.id)).all():
        ctx.resolvidas[chave_ident] = aluno_id
    return ctx


# ---------------------------------------------------------------------------
# Chaves da fila de revisão
# ---------------------------------------------------------------------------

def chave_identidade(linha: LinhaIdentidade, chave: str) -> str:
    """Quem é esta linha, independentemente do arquivo: a identidade externa
    quando existe; senão nome + sala. É a memória das decisões humanas."""
    if linha.id_externo:
        return f"{linha.plataforma}|id:{linha.id_externo}"
    return f"{linha.plataforma}|nome:{chave_nome(linha.nome)}|sala:{chave}"


def chave_pendencia(chave_ident: str, formato: str, periodo_inicio: str = "",
                    periodo_fim: str = "") -> str:
    """Uma pendência por identidade E por tipo de dado (resumo, leituras, período
    do Matific) — reimportar o mesmo relatório atualiza a pendência existente."""
    return "|".join((chave_ident, formato or "", periodo_inicio or "", periodo_fim or ""))[:400]


# ---------------------------------------------------------------------------
# A decisão
# ---------------------------------------------------------------------------

def _confirmado_por_humano(ctx: Contexto, linha: LinhaIdentidade, chave: str,
                           aluno_id: int) -> bool:
    """Um gestor já resolveu uma revisão desta MESMA identidade para este aluno."""
    return ctx.resolvidas.get(chave_identidade(linha, chave)) == aluno_id


def _para_aluno(ctx: Contexto, linha: LinhaIdentidade, aluno: Aluno, via: str,
                chave: str, candidatos: tuple[int, ...] = ()) -> Decisao:
    """Um candidato SEGURO foi achado: associa — exceto se a ficha estiver inativa
    (revisão: não se aplica dado a ficha fora do ranking, nem se cria outra) ou se
    ela já tem OUTRA conta nesta plataforma (revisão: pode ser outra criança).
    Ficha inativa escolhida por um gestor numa revisão anterior não volta à fila."""
    cands = candidatos or (aluno.id,)
    if aluno.status in STATUS_INATIVOS and not _confirmado_por_humano(
            ctx, linha, chave, aluno.id):
        return Decisao(REVISAR, aluno.id, via, "ficha_inativa", cands, chave_sala=chave)
    if linha.id_externo:
        outras = ctx.ids_do_aluno.get((aluno.id, linha.plataforma), set()) - {linha.id_externo}
        if outras:
            return Decisao(REVISAR, aluno.id, via, "outra_identidade_na_plataforma",
                           cands, chave_sala=chave)
    return Decisao(ASSOCIAR, aluno.id, via, candidatos=(aluno.id,), chave_sala=chave)


def _turma_para_criar(ctx: Contexto, linha: LinhaIdentidade, chave: str
                      ) -> tuple[int | None, str]:
    """Turma CADASTRADA onde a ficha nova nasce — determinística, nunca "a primeira":
    a escolhida explicitamente; senão a única turma da sala; havendo várias, a do
    código externo (SED/Censo) ou a de nome idêntico. Devolve (turma_id, motivo):
    motivo "turma_ambigua" quando não dá para decidir, "" quando decidiu ou quando
    a sala ainda não tem turma (o chamador cria, se o fluxo permitir)."""
    if linha.turma_id is not None:
        return linha.turma_id, ""
    ids = ctx.turmas_da_sala.get(chave, [])
    if not ids:
        return None, ""
    if len(ids) == 1:
        return ids[0], ""
    from app.services.matriculas import codigo_externo_do_nome, nome_turma_exibicao
    codigo = codigo_externo_do_nome(linha.turma_nome)
    if codigo:
        por_codigo = [i for i in ids if (ctx.turmas[i].codigo_externo or "") == codigo]
        if len(por_codigo) == 1:
            return por_codigo[0], ""
    for alvo in (linha.turma_nome.strip(), nome_turma_exibicao(linha.turma_nome)):
        por_nome = [i for i in ids if ctx.turmas[i].nome.strip().casefold() == alvo.casefold()]
        if alvo and len(por_nome) == 1:
            return por_nome[0], ""
    return None, "turma_ambigua"


def decidir(ctx: Contexto, linha: LinhaIdentidade) -> Decisao:
    """A decisão ÚNICA (prévia = confirmação). Só lê ``ctx``."""
    chave = chave_sala(ctx.turmas[linha.turma_id].nome) if (
        linha.turma_id is not None and linha.turma_id in ctx.turmas) else chave_sala(linha.turma_nome)

    # 0) Escolha EXPLÍCITA de um humano (prévia aceita, alternativa escolhida,
    # revisão resolvida). Vale — salvo se a identidade externa da linha já for de
    # OUTRO aluno: aí os dados não podem ir para o escolhido sem uma reatribuição
    # explícita (feita na resolução da revisão), então vira revisão.
    if linha.aluno_id is not None:
        aluno = ctx.alunos.get(linha.aluno_id)
        if aluno is None:
            return Decisao(IGNORAR, motivo="aluno_de_outra_escola", chave_sala=chave)
        if aluno.status == "excluido":
            return Decisao(IGNORAR, aluno.id, motivo="aluno_excluido", chave_sala=chave)
        if linha.id_externo:
            dono = ctx.ativo(ctx.identidade.get((linha.plataforma, linha.id_externo)))
            if dono is not None and dono.id != aluno.id:
                return Decisao(REVISAR, dono.id, "explicito", "identidade_de_outro_aluno",
                               (dono.id, aluno.id), chave_sala=chave)
            if dono is not None:
                return Decisao(ASSOCIAR, aluno.id, "identidade", candidatos=(aluno.id,),
                               chave_sala=chave)
        return Decisao(ASSOCIAR, aluno.id, "explicito", candidatos=(aluno.id,),
                       chave_sala=chave)

    # 1) Identidade externa — consultada ANTES de qualquer nome, em ficha ativa ou
    # inativa. Ficha excluída não segura identidade (fica livre p/ reatribuir).
    if linha.id_externo:
        dono = ctx.ativo(ctx.identidade.get((linha.plataforma, linha.id_externo)))
        if dono is not None:
            if dono.status in STATUS_INATIVOS and not _confirmado_por_humano(
                    ctx, linha, chave, dono.id):
                return Decisao(REVISAR, dono.id, "identidade", "identidade_de_ficha_inativa",
                               (dono.id,), chave_sala=chave)
            return Decisao(ASSOCIAR, dono.id, "identidade", candidatos=(dono.id,),
                           chave_sala=chave)

    # 1b) Decisão humana anterior para esta mesma identidade (revisão resolvida).
    anterior = ctx.ativo(ctx.resolvidas.get(chave_identidade(linha, chave)))
    if anterior is not None:
        return _para_aluno(ctx, linha, anterior, "revisao", chave)

    # 2) RA (identificador forte da escola inteira).
    ra = ra_forte(linha.ra)
    if ra:
        from app.services.matriculas import nomes_compativeis
        por_ra = [ctx.alunos[i] for i in sorted(ctx.por_ra.get(ra, ()))
                  if nomes_compativeis(linha.nome, ctx.alunos[i].nome)]
        if len(por_ra) == 1:
            return _para_aluno(ctx, linha, por_ra[0], "ra", chave)
        if len(por_ra) > 1:
            ids = tuple(a.id for a in por_ra)
            return Decisao(REVISAR, ids[0], "ra", "ra_repetido", ids, chave_sala=chave)

    ident = matching.Identidade(nome=linha.nome, chamada=linha.chamada,
                                nascimento=linha.nascimento, ra=ra)
    alvo_nome = chave_nome(linha.nome)
    sala_conhecida = bool(chave) and (
        linha.turma_id is not None or chave in ctx.turmas_da_sala or _sala_parseavel(chave))

    # 3) A SALA informada (todas as turmas dela, nunca "a primeira").
    vetados: tuple[int, ...] = ()
    na_sala: set[int] = set()
    if sala_conhecida:
        roster_alunos = ctx.roster(chave)
        na_sala = {a.id for a in roster_alunos}
        roster = [identidade_do_aluno(a) for a in roster_alunos]
        # 3a) Nome IDÊNTICO único na sala (sem identificador divergente): é o dono.
        exatos = [c for c in roster if chave_nome(c.nome) == alvo_nome
                  and not matching.conflito_identidade(ident, c)]
        if len(exatos) == 1:
            return _para_aluno(ctx, linha, ctx.alunos[exatos[0].id], "exato", chave)
        # 3b) Motor único: chamada/RA/nascimento corroborando, candidato único
        # estruturalmente plausível, ou revisão.
        res = matching.classificar_linha(ident, roster, permitir_subconjunto_unico=True,
                                         vincular_variante=False)
        if res.status == matching.VINCULADO and res.aluno_id in ctx.alunos:
            return _para_aluno(ctx, linha, ctx.alunos[res.aluno_id], res.motivo, chave)
        if res.status == matching.REVISAR:
            motivo = ("candidatos_multiplos" if len(res.candidatos) > 1
                      else "correspondencia_insegura")
            return Decisao(REVISAR, res.aluno_id, res.motivo, motivo, res.candidatos,
                           chave_sala=chave)
        vetados = res.vetados

    # 4) Homônimo EXATO fora da sala (outra turma/série, qualquer status não
    # excluído). Com a sala conhecida ele NÃO casa — é revisão (pode ser a mesma
    # criança que mudou de sala, ou outra criança). Sem sala utilizável, o nome
    # idêntico ÚNICO na escola é a melhor evidência que existe.
    fora = []
    for aid in sorted(ctx.por_nome.get(alvo_nome, ())):
        a = ctx.ativo(aid)
        if a is None or aid in na_sala:
            continue
        if matching.conflito_identidade(replace(ident, chamada=None),
                                        replace(identidade_do_aluno(a), chamada=None)):
            continue
        fora.append(a)
    if fora:
        ids = tuple(a.id for a in fora)
        if not sala_conhecida and len(fora) == 1:
            return _para_aluno(ctx, linha, fora[0], "exato", chave)
        motivo = "homonimo_em_outra_sala" if sala_conhecida else "candidatos_multiplos"
        return Decisao(REVISAR, ids[0], "exato", motivo, ids, chave_sala=chave)

    # 4b) Nome que só casa FORA da sala (abreviação, parcial, grafia): nunca
    # associa e nunca cria — revisão. Com a sala conhecida é "casa em outra turma";
    # sem sala utilizável, nome não idêntico nunca decide sozinho. Só sem nenhum
    # candidato plausível em lugar nenhum a ficha nova é criada. (Chamada é
    # numeração da sala: fora dela não corrobora nem veta nada.)
    res = ctx.classificar_na_escola(replace(ident, chamada=None), excluir_sala=chave
                                    if sala_conhecida else None)
    if res.status in (matching.VINCULADO, matching.REVISAR):
        if sala_conhecida:
            motivo = "nome_casa_em_outra_sala"
        else:
            motivo = ("candidatos_multiplos" if len(res.candidatos) > 1
                      else "correspondencia_insegura")
        return Decisao(REVISAR, res.aluno_id, res.motivo, motivo, res.candidatos,
                       chave_sala=chave)
    vetados = vetados or res.vetados

    # 5) Nenhum candidato: CRIAR — na turma cadastrada da sala, decidida sem chute.
    # Sem turma alguma, quem cria precisa escolher a turma (a tela pede; a
    # sincronização não tem como — ``_resolver_aluno`` manda para revisão).
    if not chave:
        return Decisao(CRIAR, None, "novo", "sem_turma", chave_sala=chave, vetados=vetados)
    turma_id, motivo = _turma_para_criar(ctx, linha, chave)
    if motivo:
        return Decisao(REVISAR, None, "", motivo, (), chave_sala=chave)
    return Decisao(CRIAR, None, "novo", turma_id=turma_id, chave_sala=chave,
                   vetados=vetados)


# ---------------------------------------------------------------------------
# Fila de revisão (gravação fica com o chamador — aqui só a montagem)
# ---------------------------------------------------------------------------

def descrever_candidatos(ctx: Contexto, ids) -> list[dict]:
    saida = []
    for aid in ids:
        a = ctx.alunos.get(aid)
        if a is None:
            continue
        turma = ctx.turma_do_aluno(aid)
        saida.append({"aluno_id": a.id, "nome": a.nome, "status": a.status,
                      "turma": turma.nome if turma is not None else None})
    return saida


@dataclass
class Pendencia:
    chave: str
    chave_identidade: str
    plataforma: str
    formato: str
    id_externo: str
    nome: str
    turma_informada: str
    turma_id: int | None
    motivo: str
    candidatos: list[dict]
    linhas: list[dict] = field(default_factory=list)


class ColetorRevisoes:
    """Junta as linhas em revisão de UMA importação (várias linhas do mesmo aluno →
    uma pendência) e grava/atualiza a fila no fim, sem duplicar pendências."""

    def __init__(self, *, formato: str = "", contexto: dict | None = None,
                 origem: str = "importacao", importacao_id: int | None = None):
        self.formato = formato or ""
        self.contexto = contexto or {}
        self.origem = origem
        self.importacao_id = importacao_id
        self.pendencias: dict[str, Pendencia] = {}

    def adicionar(self, ctx: Contexto, linha: LinhaIdentidade, decisao: Decisao,
                  dados: dict) -> Pendencia:
        ident = chave_identidade(linha, decisao.chave_sala)
        chave = chave_pendencia(ident, self.formato,
                                str(self.contexto.get("periodo_inicio") or ""),
                                str(self.contexto.get("periodo_fim") or ""))
        pend = self.pendencias.get(chave)
        if pend is None:
            turma_id = decisao.turma_id
            if turma_id is None:
                ids = ctx.turmas_da_sala.get(decisao.chave_sala, [])
                turma_id = ids[0] if len(ids) == 1 else None
            pend = Pendencia(
                chave=chave, chave_identidade=ident[:400], plataforma=linha.plataforma,
                formato=self.formato, id_externo=linha.id_externo,
                nome=linha.nome.strip(), turma_informada=linha.turma_nome.strip(),
                turma_id=turma_id, motivo=decisao.motivo,
                candidatos=descrever_candidatos(ctx, decisao.candidatos))
            self.pendencias[chave] = pend
        pend.linhas.append(dict(dados or {}))
        return pend

    def gravar(self, db: Session, escola_id: int) -> list[RevisaoIdentidade]:
        from app.models.base import agora
        gravadas: list[RevisaoIdentidade] = []
        for pend in self.pendencias.values():
            rev = db.execute(
                select(RevisaoIdentidade).where(
                    RevisaoIdentidade.escola_id == escola_id,
                    RevisaoIdentidade.chave == pend.chave,
                    RevisaoIdentidade.status == "pendente")
                .order_by(RevisaoIdentidade.id)).scalars().first()
            if rev is None:
                rev = RevisaoIdentidade(
                    escola_id=escola_id, chave=pend.chave,
                    chave_identidade=pend.chave_identidade, plataforma=pend.plataforma,
                    formato=pend.formato, ocorrencias=0, linhas=[])
                db.add(rev)
            rev.id_externo = pend.id_externo or None
            rev.nome_recebido = pend.nome[:200]
            rev.turma_informada = (pend.turma_informada or None) and pend.turma_informada[:200]
            rev.turma_id = pend.turma_id
            rev.motivo = pend.motivo
            rev.candidatos = pend.candidatos
            rev.linhas = _juntar_linhas(rev.linhas or [], pend.linhas, pend.formato)
            rev.contexto = dict(self.contexto)
            rev.origem = self.origem
            rev.importacao_id = self.importacao_id
            rev.ocorrencias = (rev.ocorrencias or 0) + 1
            rev.atualizada_em = agora()
            gravadas.append(rev)
        db.flush()
        return gravadas


def _juntar_linhas(antigas: list[dict], novas: list[dict], formato: str) -> list[dict]:
    """Leituras se ACUMULAM (sem repetir a mesma linha); resumo/placar é retrato —
    vale o mais recente."""
    if formato != "leituras":
        return list(novas)
    vistos: set[str] = set()
    saida: list[dict] = []
    for d in list(antigas) + list(novas):
        chave = json.dumps(d, sort_keys=True, ensure_ascii=False, default=str)
        if chave in vistos:
            continue
        vistos.add(chave)
        saida.append(d)
    return saida
