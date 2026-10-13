"""PORTA ÚNICA de identidade das linhas de PLATAFORMA (Elefante/Matific).

Decide, para cada linha importada/sincronizada, DE QUEM são aqueles dados — e é
o MESMO cálculo na PRÉVIA (``importacao.casar_nomes``) e na CONFIRMAÇÃO
(``routers.importacoes._resolver_aluno``): a prévia mostra exatamente o que a
confirmação fará, e a sincronização automática não tem atalho próprio.

Ordem (mais forte primeiro — ver ``decidir``):
  1. identidade externa (UUID do Matific / studentId do Elefante) já vinculada;
  2. RA;
  3. sala informada (escola + série + letra, TODAS as turmas da sala; quando a
     escola cadastrou a turma SEM a letra, a sala do relatório é reconhecida pela
     SÉRIE se houver uma única turma ativa dela — ``Contexto.sala_efetiva``): nome
     idêntico único → chamada/RA/nascimento corroborando → candidato ÚNICO
     estruturalmente plausível (``matching.classificar_linha``, com a variação de
     grafia SEGURA do nome do meio — o mesmo critério da Lista Piloto) → ficha
     oficial da Lista Piloto × duplicata dela na sala, de nome igual ou
     abreviado (``_oficial_entre_duplicatas``);
  4. homônimo EXATO fora da sala (outra turma, outra série) → revisão, nunca
     vínculo;
  5. revisão sempre que houver candidato e nenhum for seguro;
  6. criação SÓ quando não houver candidato algum.

O nome RECEBIDO entra no casamento sem os tokens que contêm dígito (o sufixo de
turma que o professor digita junto do nome, "… 2B") — ``_nome_para_casar``.

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
import re
from dataclasses import dataclass, field, replace
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Aluno, Escola, IdentidadeExterna, Matricula, Turma
from app.models.academico import RevisaoIdentidade
from app.services import matching
from app.services.importacao import chave_nome, tokens_nome
from app.services.lista_piloto import ra_util

ASSOCIAR = "associar"   # dados vão para uma ficha existente
REVISAR = "revisar"     # há candidato(s), nenhum seguro: não associa, não cria
CRIAR = "criar"         # nenhum candidato plausível: ficha nova
IGNORAR = "ignorar"     # entrada inválida (aluno de outra escola/excluído)

STATUS_INATIVOS = ("arquivado", "fora_lista_piloto", "transferido")

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
    "criacao_bloqueada_por_politica":
        "nenhum aluno corresponde e a política desta escola não deixa a "
        "sincronização criar ficha (a matrícula vem da Lista Piloto)",
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
    # Desempate "oficial × duplicata" (passo 3c): as fichas da sala que ERAM
    # candidatas e foram deixadas de lado — o rastro de quem perdeu, para auditoria
    # (``candidatos`` de um ASSOCIAR só traz o escolhido).
    preteridos: tuple[int, ...] = ()


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
    # Turmas ATIVAS por SÉRIE (4 → [164]). Só para reconhecer a sala do relatório
    # numa escola que cadastrou a turma sem a letra — ver ``sala_efetiva``.
    turmas_por_serie: dict[int, list[int]] = field(default_factory=dict)
    alunos_da_sala: dict[str, set[int]] = field(default_factory=dict)
    turma_de: dict[int, int] = field(default_factory=dict)
    por_nome: dict[str, set[int]] = field(default_factory=dict)
    por_ra: dict[str, set[int]] = field(default_factory=dict)
    # decisões de revisão já tomadas por um humano, por chave de identidade. As
    # revisões ENCERRADAS PELO SISTEMA (``resolucao.automatica``) não entram ao
    # carregar: valem só dentro da importação que as encerrou — ver
    # ``carregar_contexto``.
    resolvidas: dict[str, int] = field(default_factory=dict)
    # Revisões PENDENTES da escola por chave de identidade → ids (as "irmãs" de
    # formato — resumo, leituras, períodos do Matific — ficam na mesma lista).
    # Lidas UMA vez: na primeira linha ASSOCIADA de uma identidade, o router
    # avalia as pendências dela, encerra as que essa linha respondeu (as do MESMO
    # tipo de dado) e retira todas daqui — já avaliadas nesta importação —, sem
    # uma consulta por linha numa sincronização de milhares
    # (``importacoes._encerrar_revisoes_respondidas``).
    pendentes: dict[str, list[int]] = field(default_factory=dict)
    # Identidades APOSENTADAS: (plataforma, id_externo) → aluno_id. Continuam
    # provando de quem era o id externo, mas estão FORA de ``identidade`` e de
    # ``ids_do_aluno`` — não casam, não contam e não voltam sozinhas.
    aposentadas: dict[tuple[str, str], int] = field(default_factory=dict)
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
        from app.services.matriculas import serie_da_sala
        self.turmas[turma.id] = turma
        ids = self.turmas_da_sala.setdefault(chave_sala(turma.nome), [])
        if turma.id not in ids:
            ids.append(turma.id)
            ids.sort()
        # Índice por série — só turmas ATIVAS (uma turma arquivada não recebe
        # aluno) e só quando o rótulo marca a série.
        if getattr(turma, "status", "ativa") != "ativa":
            return
        serie = serie_da_sala(turma.nome, getattr(turma, "ano_escolar", "") or "")
        if serie is None:
            return
        da_serie = self.turmas_por_serie.setdefault(serie, [])
        if turma.id not in da_serie:
            da_serie.append(turma.id)
            da_serie.sort()

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

    def sala_efetiva(self, chave: str, turma_nome: str = "") -> str:
        """A sala do CADASTRO que corresponde à sala do RELATÓRIO.

        Devolve ``chave`` INTACTA quando ela já é uma sala cadastrada — o caminho
        de sempre, para toda escola que cadastra a turma com a letra. Só quando a
        sala do relatório NÃO existe no cadastro e a escola tem EXATAMENTE UMA
        turma ATIVA daquela SÉRIE é que a chave vira a dessa turma: é a mesma sala
        escrita de outro jeito ("4 ANO A INTEGRAL (300309347)" no relatório ×
        "4º Ano" no cadastro, série única na escola).

        Nunca decide sozinha nada mais: série ilegível ("EJA 2", "Maternal"),
        série com DUAS ou mais turmas, sala já cadastrada, ou LETRAS que se
        contradizem (o cadastro diz "4ºA" e o relatório diz "4 ANO B" — os dois
        lados afirmam a letra e elas divergem, então são salas diferentes)
        devolvem a chave como veio, e a linha segue exatamente o fluxo de hoje,
        revisão inclusive. E reconhecer a sala não vincula ninguém: quem decide
        continua sendo o nome contra o roster DAQUELA sala (nome idêntico,
        identificador, candidato único), com a mesma proteção contra homônimo."""
        from app.services.matriculas import serie_da_sala
        if not chave or chave in self.turmas_da_sala or not turma_nome:
            return chave
        serie = serie_da_sala(turma_nome)
        if serie is None:
            return chave
        ids = self.turmas_por_serie.get(serie, [])
        if len(ids) != 1:                      # nenhuma ou várias: não escolhe
            return chave
        chave_cadastrada = chave_sala(self.turmas[ids[0]].nome)
        letra_relatorio, letra_cadastro = (chave.partition("|")[2],
                                           chave_cadastrada.partition("|")[2])
        if letra_relatorio and letra_cadastro and letra_relatorio != letra_cadastro:
            return chave                       # letras declaradas e divergentes
        return chave_cadastrada

    def decisao_humana(self, linha: LinhaIdentidade, *chaves: str) -> int | None:
        """Aluno que um gestor já escolheu para ESTA identidade, procurando em cada
        chave de sala informada. São duas quando ``sala_efetiva`` reconheceu a sala
        pela série: a decisão tomada ANTES dessa correção (gravada sob a sala do
        relatório) continua valendo — nenhuma escolha humana se perde."""
        vistas: set[str] = set()
        for chave in chaves:
            if not chave or chave in vistas:
                continue
            vistas.add(chave)
            aluno_id = self.resolvidas.get(chave_identidade(linha, chave))
            if aluno_id is not None:
                return aluno_id
        return None


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
    for plataforma, id_externo, aluno_id, status in db.execute(
            select(IdentidadeExterna.plataforma, IdentidadeExterna.id_externo,
                   IdentidadeExterna.aluno_id, IdentidadeExterna.status)
            .where(IdentidadeExterna.escola_id == escola_id)
            .order_by(IdentidadeExterna.id)).all():
        # A APOSENTADA fica FORA dos índices de casamento: quem consulta
        # ``identidade``/``ids_do_aluno`` está perguntando "quem é esta conta
        # HOJE", e a resposta para uma conta aposentada é "ninguém". O vínculo
        # continua registrado em ``aposentadas`` para o motor reconhecê-la e
        # recusá-la explicitamente, em vez de tratá-la como conta nova.
        if status == "aposentada":
            ctx.aposentadas[(plataforma, str(id_externo))] = aluno_id
            continue
        ctx.vincular(aluno_id, plataforma, str(id_externo))
    for chave_ident, aluno_id, resolucao in db.execute(
            select(RevisaoIdentidade.chave_identidade, RevisaoIdentidade.aluno_escolhido_id,
                   RevisaoIdentidade.resolucao)
            .where(RevisaoIdentidade.escola_id == escola_id,
                   RevisaoIdentidade.status == "resolvida",
                   RevisaoIdentidade.aluno_escolhido_id.is_not(None))
            .order_by(RevisaoIdentidade.resolvida_em, RevisaoIdentidade.id)).all():
        # Revisão ENCERRADA PELO SISTEMA não vira memória: a escolha dela só
        # repete a regra que a fez, e a regra roda de novo a cada linha. Se ela
        # entrasse aqui, valeria como confirmação humana — a guarda de ficha
        # inativa (``_confirmado_por_humano``) deixaria de abrir revisão e um
        # homônimo novo na sala não reabriria a dúvida. A linha com conta da
        # plataforma continua estável pelo vínculo gravado na ficha.
        if isinstance(resolucao, dict) and resolucao.get("automatica") is True:
            continue
        ctx.resolvidas[chave_ident] = aluno_id
    for chave_ident, revisao_id in db.execute(
            select(RevisaoIdentidade.chave_identidade, RevisaoIdentidade.id)
            .where(RevisaoIdentidade.escola_id == escola_id,
                   RevisaoIdentidade.status == "pendente")
            .order_by(RevisaoIdentidade.id)).all():
        ctx.pendentes.setdefault(chave_ident, []).append(revisao_id)
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
                           aluno_id: int, chave_alt: str = "") -> bool:
    """Um gestor já resolveu uma revisão desta MESMA identidade para este aluno.
    ``chave_alt`` é a sala do relatório quando ela difere da efetiva (ver
    ``Contexto.sala_efetiva``): a decisão anterior vale nas duas."""
    return ctx.decisao_humana(linha, chave, chave_alt) == aluno_id


def _para_aluno(ctx: Contexto, linha: LinhaIdentidade, aluno: Aluno, via: str,
                chave: str, candidatos: tuple[int, ...] = (),
                chave_alt: str = "") -> Decisao:
    """Um candidato SEGURO foi achado: associa — exceto se a ficha estiver inativa
    (revisão: não se aplica dado a ficha fora do ranking, nem se cria outra) ou se
    ela já tem OUTRA conta nesta plataforma (revisão: pode ser outra criança).
    Ficha inativa escolhida por um gestor numa revisão anterior não volta à fila."""
    cands = candidatos or (aluno.id,)
    if aluno.status in STATUS_INATIVOS and not _confirmado_por_humano(
            ctx, linha, chave, aluno.id, chave_alt):
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


# Sufixo de TURMA que o professor digita junto do nome: série (1–2 dígitos), o
# ordinal opcional e a letra da sala — "2B", "4A", "2ºB" ("2°B" já chega como "2b":
# ``tokens_nome`` tira o símbolo de grau). Número PURO ("… SOUZA 2") não é sufixo
# de turma: pode ser o número que a escola usa para separar dois homônimos.
_SUFIXO_TURMA = re.compile(r"\d{1,2}[ºª]?[a-z]")
# O mesmo sufixo GRUDADO no último nome ("PINTO2B"): sai só o sufixo.
_SUFIXO_TURMA_COLADO = re.compile(r"([a-z]{2,})(\d{1,2}[ºª]?[a-z])")


def _sufixo_da_sala(token: str, chave: str) -> bool:
    """O sufixo de turma ("2b", "2ºb") é o da SALA da linha ("2|B")? Só então ele é
    a turma digitada junto do nome. Sufixo de OUTRA sala ("3a" na 2ºB) contradiz
    o relatório, e "2o" ("2o B") não é sala nenhuma — nos dois casos o token fica
    e a linha segue o caminho de sempre."""
    num, _, letra = (chave or "").partition("|")
    digitos = re.match(r"\d{1,2}", token)
    return (bool(num.isdigit() and letra and digitos)
            and int(digitos.group()) == int(num) and token[-1] == letra.lower())


def _nome_para_casar(nome: str, chave: str = "", chave_alt: str = "") -> str:
    """O nome RECEBIDO como ele entra no CASAMENTO: sem o sufixo de TURMA. O
    professor do Elefante às vezes digita a turma junto do nome ("… RIBEIRO 2B",
    "… BRIET 4A"); esse sufixo não é nome de criança e, mantido, transformava o nome
    idêntico da ficha em "nome parcial" — revisão a cada sincronização.

    Só sai o que tem forma de sufixo de turma (``_SUFIXO_TURMA``) E é a sala da
    própria linha (``_sufixo_da_sala`` contra ``chave`` — ou contra ``chave_alt``,
    a sala do relatório que ``sala_efetiva`` reconheceu na turma sem letra), como token separado ou
    grudado no fim de um nome ("PINTO2B" → "PINTO"); sem sala legível, nada sai. Qualquer outro
    token com dígito fica: um número puro ("… SOUZA 2") pode distinguir homônimos
    e, se sumisse, o dado da 2ª criança iria para a ficha da 1ª.

    Vale SÓ para decidir de quem é a linha: o nome exibido, o gravado na revisão e
    o da chave da identidade (``chave_identidade``, memória das decisões humanas)
    continuam os recebidos. Sem sufixo de turma — ou quando só sobraria o sufixo —
    devolve o nome intacto, e nada muda."""
    tokens = tokens_nome(nome)
    limpos: list[str] = []
    for t in tokens:
        if _SUFIXO_TURMA.fullmatch(t) and (_sufixo_da_sala(t, chave)
                                           or _sufixo_da_sala(t, chave_alt)):
            continue
        colado = _SUFIXO_TURMA_COLADO.fullmatch(t)
        da_sala = colado is not None and (_sufixo_da_sala(colado.group(2), chave)
                                          or _sufixo_da_sala(colado.group(2), chave_alt))
        limpos.append(colado.group(1) if da_sala else t)
    if not limpos or limpos == tokens:
        return nome
    return " ".join(limpos)


# Grafias equivalentes de nome próprio no português do Brasil (LUÍS/LUIZ,
# RODRIGUES/RODRIGUEZ, EMANUELE/EMANUELLE, THAIS/TAIS, HELOISA/ELOISA): a MESMA
# pronúncia escrita de outro jeito.
_EQUIVALENCIAS = (("ph", "f"), ("th", "t"), ("y", "i"), ("w", "v"), ("k", "c"), ("z", "s"))


def _forma_ortografica(token: str) -> str:
    for de, para in _EQUIVALENCIAS:
        token = token.replace(de, para)
    if token.startswith("h"):
        token = token[1:]                                     # H inicial mudo
    return re.sub(r"([b-df-hj-np-tv-z])\1", r"\1", token)   # consoante dobrada


def _distancia_edicao(a: str, b: str) -> int:
    """Distância de edição com transposição (Damerau, alinhamento ótimo)."""
    d = [[i + j if i * j == 0 else 0 for j in range(len(b) + 1)] for i in range(len(a) + 1)]
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1,
                          d[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


# Vínculos do motor que vêm de VARIAÇÃO DE GRAFIA (não de nome idêntico, abreviação,
# subconjunto ou identificador) — os que a plataforma passou a aceitar (A).
_VIA_GRAFIA = ("variante", "typo")

# Erro de digitação (uma letra trocada, sobrando, faltando ou invertida) só é
# reconhecido em palavra com pelo menos isto de letras: em nome curto, uma letra
# separa nomes diferentes (LARA/LAURA, ELOA/ELOAH).
_MINIMO_LETRAS_ERRO_DIGITACAO = 5


def _grafia_segura(recebido: str, ficha: str) -> bool:
    """A diferença entre o nome RECEBIDO da plataforma e o da FICHA é de grafia —
    a mesma criança — e não outro nome? Vale para o vínculo automático por grafia
    de candidato único (passo 3b) e para o desempate oficial × duplicata (3c).

    O motor aceita até dois tokens do meio com similaridade >= 0,7
    (``variante_ortografica``); isso também casa NOMES DIFERENTES (ALICE/ALINE,
    CRISTINA/CRISTIANA, GUSTAVO/AUGUSTO). Aqui, só com TODAS as condições:
      1. mesmo nº de palavras (3+), UMA só diferente, no MEIO (1º nome e último
         sobrenome idênticos);
      2. as duas formas são a MESMA grafia (``_forma_ortografica``: Z/S, Y/I, W/V,
         K/C, PH/F, TH/T, H inicial mudo, consoante dobrada) — em qualquer palavra
         do meio; OU
      3. é um erro de UMA letra (``_distancia_edicao`` == 1), em palavra de 5+
         letras, num SOBRENOME do meio: nome de 4+ palavras e a diferença da 3ª
         palavra em diante (nunca na última). Irmãos e gêmeos compartilham os
         sobrenomes e se distinguem pelo PRENOME — MARIA ALICE × MARIA ALINE
         ALVES PEREIRA —, então uma letra diferente no prenome é revisão. Não
         há lista de prenomes a consultar: o cadastro de produção (1.420 fichas,
         2026-10-11) não tem ALINE, CRISTIANA, DANIELE nem BRUNA, e um corpus
         assim ligaria justamente as gêmeas.
    Medido em 2026-10-11 (só leitura): das linhas pendentes da rede que o motor
    ligaria por grafia, as de sobrenome do meio e as de grafia equivalente ligam;
    as de erro de uma letra num prenome (2º nome) passam a pedir revisão."""
    ta, tb = tokens_nome(recebido), tokens_nome(ficha)
    if len(ta) != len(tb) or len(ta) < 3:
        return False
    difs = [i for i, (x, y) in enumerate(zip(ta, tb)) if x != y]
    if len(difs) != 1 or difs[0] in (0, len(ta) - 1):
        return False
    i = difs[0]
    x, y = ta[i], tb[i]
    if _forma_ortografica(x) == _forma_ortografica(y):
        return True
    sobrenome_do_meio = len(ta) >= 4 and i >= 2
    return (sobrenome_do_meio and _distancia_edicao(x, y) == 1
            and min(len(x), len(y)) >= _MINIMO_LETRAS_ERRO_DIGITACAO)


def _homonimos_fora_da_sala(ctx: Contexto, ident: matching.Identidade, alvo_nome: str,
                            na_sala: set[int]) -> list[Aluno]:
    """Fichas (não excluídas) de nome IDÊNTICO ao recebido FORA da sala, sem
    identificador que prove ser outra criança. A chamada não conta: é numeração da
    sala, e fora dela não veta nem corrobora nada."""
    fora: list[Aluno] = []
    for aid in sorted(ctx.por_nome.get(alvo_nome, ())):
        a = ctx.ativo(aid)
        if a is None or aid in na_sala:
            continue
        if matching.conflito_identidade(replace(ident, chamada=None),
                                        replace(identidade_do_aluno(a), chamada=None)):
            continue
        fora.append(a)
    return fora


def _casa_fora_da_sala(ctx: Contexto, ident: matching.Identidade,
                       chave: str) -> tuple[int, ...]:
    """Fichas FORA da sala com que a linha casa pelo MESMO motor do passo 4b
    (``classificar_na_escola``): nome idêntico, abreviado, sem um sobrenome, com
    "DE" a mais ou de grafia parecida — sem identificador que prove ser outra
    criança. Só olhar o nome IDÊNTICO deixava de fora a dona real cadastrada como
    "… ALVES DE PEREIRA", "… PEREIRA" ou como o stub "MARIA A", e a linha ia
    para a ficha só parecida da sala."""
    res = ctx.classificar_na_escola(replace(ident, chamada=None), excluir_sala=chave)
    if res.status in (matching.VINCULADO, matching.REVISAR):
        return tuple(res.candidatos)
    return ()


def _revisar_casa_fora(ctx: Contexto, fora: tuple[int, ...], da_sala: tuple[int, ...],
                       via: str, chave: str, alvo_nome: str) -> Decisao:
    """Revisão com as fichas das DUAS salas: a de fora casa com a linha e a sala
    do relatório pode estar errada — quem decide é gente."""
    identica = any(chave_nome(ctx.alunos[i].nome) == alvo_nome
                   for i in fora if i in ctx.alunos)
    ids = tuple(dict.fromkeys((*fora, *da_sala)))
    return Decisao(REVISAR, fora[0], via,
                   "homonimo_em_outra_sala" if identica else "nome_casa_em_outra_sala",
                   ids, chave_sala=chave)


def _oficial_entre_duplicatas(ctx: Contexto, linha: LinhaIdentidade,
                              ident: matching.Identidade,
                              candidatos: tuple[int, ...]) -> tuple[Aluno, str] | None:
    """Desempate DETERMINÍSTICO "ficha oficial × duplicata dela", na sala.

    O padrão real (escola 1, 2ºB; aqui com nome fictício): a ficha OFICIAL da
    Lista Piloto "LARISSA VITORIA MENEZES COSTA" e, na mesma sala, a ficha
    "LARISSA V" que a sincronização do Matific criou quando só recebia o nome
    abreviado. O Elefante manda o nome completo com um typo no meio ("MENEZEZ"),
    os dois viram candidatos e a linha ia para a revisão a cada sincronização — o
    dado da criança ficava parado. A ficha abreviada não é uma segunda criança
    plausível para ESSA linha: é a sombra da oficial.

    Devolve (O, como a linha casa com O) SOMENTE quando TODAS as condições valem:
      1. exatamente UM candidato é da Lista Piloto — e ele está ativo (é O);
      2. a linha casaria com O SOZINHA pelo critério de candidato único da
         plataforma (o mesmo ``matching.classificar_linha`` do passo 3b: nome
         exato/abreviação, grafia diferente em UM nome do meio ou subconjunto
         estrutural);
      3. cada OUTRO candidato S está fora da Lista Piloto, tem nome igual ao de O
         ou forma curta/abreviação dele (``matching.plausivel`` == 'forte' — nome
         parcial ou com grafia diferente NÃO serve), não tem identificador que
         prove ser outra criança (RA/nascimento/chamada divergentes dos de O) e
         NÃO tem conta nesta mesma plataforma — se tem, pode ser a conta de outra
         criança, e quem decide é gente.
    Qualquer outra situação (duas fichas da Lista Piloto, ficha fora da lista sem
    dono compatível na Lista Piloto, identificador divergente, conta própria)
    devolve None e a linha segue para a revisão de sempre. O chamador ainda
    confere o nome idêntico em OUTRA sala (``_homonimos_fora_da_sala``). Nada é
    fundido aqui: a duplicata continua existindo, com a conta dela, até a fusão
    administrativa — ou até a consolidação automática da escola que a ligou
    (``consolidacao_sombras``, com regras próprias e mais estritas)."""
    if len(candidatos) < 2 or not linha.plataforma:
        return None
    alunos = [ctx.alunos.get(i) for i in candidatos]
    if any(a is None for a in alunos):
        return None
    da_lista = [a for a in alunos if a.da_lista_piloto]
    if len(da_lista) != 1 or da_lista[0].status != "ativo":
        return None
    oficial = da_lista[0]
    id_oficial = identidade_do_aluno(oficial)
    sozinha = matching.classificar_linha(ident, [id_oficial], permitir_subconjunto_unico=True,
                                         vincular_variante=True)
    if sozinha.status != matching.VINCULADO or sozinha.aluno_id != oficial.id:
        return None
    # Conta APOSENTADA nesta plataforma também conta como "tem conta": a escola já
    # olhou para aquela ficha e decidiu algo sobre ela — não é sombra anônima.
    com_conta_aposentada = {aid for (plat, _), aid in ctx.aposentadas.items()
                            if plat == linha.plataforma}
    todas_aposentadas = set(ctx.aposentadas.values())
    for sombra in alunos:
        if sombra.id == oficial.id:
            continue
        if matching.plausivel(sombra.nome, oficial.nome) != "forte":
            return None
        if matching.conflito_identidade(identidade_do_aluno(sombra), id_oficial):
            return None
        if (ctx.ids_do_aluno.get((sombra.id, linha.plataforma))
                or sombra.id in com_conta_aposentada):
            return None
        # Nome IDÊNTICO ao da oficial (não abreviado) pode ser OUTRA criança real
        # com o mesmo nome: só é sombra sem conta em NENHUMA plataforma.
        if set(tokens_nome(sombra.nome)) == set(tokens_nome(oficial.nome)) and (
                any(ctx.ids_do_aluno.get((sombra.id, plat)) for plat in CAMPO_ID_EXTERNO)
                or sombra.id in todas_aposentadas):
            return None
    return oficial, sozinha.motivo


def decidir(ctx: Contexto, linha: LinhaIdentidade) -> Decisao:
    """A decisão ÚNICA (prévia = confirmação). Só lê ``ctx``."""
    # A SALA da linha. Turma escolhida explicitamente manda; senão vale a do
    # relatório, RECONHECIDA no cadastro quando a escola tem uma turma só naquela
    # série (``sala_efetiva`` — "4 ANO A INTEGRAL (300…)" × "4º Ano"). A chave crua
    # do relatório segue viva só para não perder decisão humana anterior.
    chave_relatorio = chave_sala(linha.turma_nome)
    chave = chave_sala(ctx.turmas[linha.turma_id].nome) if (
        linha.turma_id is not None and linha.turma_id in ctx.turmas
    ) else ctx.sala_efetiva(chave_relatorio, linha.turma_nome)
    chave_alt = chave_relatorio if chave_relatorio != chave else ""

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

    # 0b) Identidade APOSENTADA: a escola já decidiu que esta conta duplicada
    # não representa mais a criança no Constela. A linha não vira dado nem volta
    # para a fila — senão cada sincronização reabriria a mesma duplicidade que já
    # foi decidida. Ela é IGNORADA, com aviso, e o histórico continua no banco.
    # Só uma nova decisão humana (reativar a identidade) desfaz isso.
    if linha.id_externo:
        aposentada = ctx.aposentadas.get((linha.plataforma, linha.id_externo))
        if aposentada is not None:
            return Decisao(IGNORAR, aposentada, "identidade", "identidade_aposentada",
                           (aposentada,), chave_sala=chave)

    # 1) Identidade externa — consultada ANTES de qualquer nome, em ficha ativa ou
    # inativa. Ficha excluída não segura identidade (fica livre p/ reatribuir).
    if linha.id_externo:
        dono = ctx.ativo(ctx.identidade.get((linha.plataforma, linha.id_externo)))
        if dono is not None:
            if dono.status in STATUS_INATIVOS and not _confirmado_por_humano(
                    ctx, linha, chave, dono.id, chave_alt):
                return Decisao(REVISAR, dono.id, "identidade", "identidade_de_ficha_inativa",
                               (dono.id,), chave_sala=chave)
            # DUAS CONTAS NA MESMA FICHA: a mesma trava que todo caminho por NOME
            # já aplica (``_para_aluno``) vale também quando se chega pela
            # identidade. Sem ela, as duas contas viram ASSOCIAR para a MESMA
            # ficha e o retrato de uma sobrescreve o da outra em silêncio — o
            # importador guarda só a ÚLTIMA linha do aluno, e a reimportação do
            # mesmo dia ainda muta o snapshot no lugar. Não há como somar nem
            # escolher: qual conta é a criança é decisão de gente.
            outras = ctx.ids_do_aluno.get((dono.id, linha.plataforma), set()) - {linha.id_externo}
            if outras:
                return Decisao(REVISAR, dono.id, "identidade",
                               "outra_identidade_na_plataforma", (dono.id,),
                               chave_sala=chave)
            return Decisao(ASSOCIAR, dono.id, "identidade", candidatos=(dono.id,),
                           chave_sala=chave)

    # 1b) Decisão humana anterior para esta mesma identidade (revisão resolvida) —
    # procurada também sob a sala do RELATÓRIO, para que reconhecer a sala pela
    # série não apague uma escolha que um gestor já fez.
    anterior = ctx.ativo(ctx.decisao_humana(linha, chave, chave_alt))
    if anterior is not None:
        return _para_aluno(ctx, linha, anterior, "revisao", chave, chave_alt=chave_alt)

    # Daqui em diante o NOME decide: entra o recebido sem o sufixo de turma com
    # dígito ("… 2B"). A linha (nome exibido/gravado, chave da identidade) não muda.
    nome_casar = _nome_para_casar(linha.nome, chave, chave_alt)

    # 2) RA (identificador forte da escola inteira).
    ra = ra_forte(linha.ra)
    if ra:
        from app.services.matriculas import nomes_compativeis
        por_ra = [ctx.alunos[i] for i in sorted(ctx.por_ra.get(ra, ()))
                  if nomes_compativeis(nome_casar, ctx.alunos[i].nome)]
        if len(por_ra) == 1:
            return _para_aluno(ctx, linha, por_ra[0], "ra", chave, chave_alt=chave_alt)
        if len(por_ra) > 1:
            ids = tuple(a.id for a in por_ra)
            return Decisao(REVISAR, ids[0], "ra", "ra_repetido", ids, chave_sala=chave)

    ident = matching.Identidade(nome=nome_casar, chamada=linha.chamada,
                                nascimento=linha.nascimento, ra=ra)
    alvo_nome = chave_nome(nome_casar)
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
            return _para_aluno(ctx, linha, ctx.alunos[exatos[0].id], "exato", chave,
                               chave_alt=chave_alt)
        # 3b) Motor único: chamada/RA/nascimento corroborando, candidato único
        # estruturalmente plausível, ou revisão. A variação de grafia SEGURA de
        # candidato único ("RICADO"/"RICARDO": 1º nome e último sobrenome idênticos)
        # associa — decisão do dono, o MESMO critério que a Lista Piloto já usa
        # (``matching.vincula_por_nome_unico``), com duas travas a mais aqui:
        #   * a grafia difere em UM nome do meio só (o motor aceita dois) — com dois,
        #     revisão como antes;
        #   * nome IDÊNTICO em OUTRA sala vence o nome só parecido desta: revisão
        #     "homonimo_em_outra_sala" com as fichas das duas salas.
        # Variação no sobrenome ou no 1º nome (SOUZA/SOUSA, BRUNO/BRUNA) continua
        # em revisão.
        res = matching.classificar_linha(ident, roster, permitir_subconjunto_unico=True,
                                         vincular_variante=True)
        if (res.status == matching.VINCULADO and res.motivo in _VIA_GRAFIA
                and res.aluno_id in ctx.alunos):
            # Grafia: primeiro, a dona pode estar em OUTRA sala (com qualquer forma
            # do nome) — revisão com as duas salas; depois, a diferença tem de ser
            # de grafia mesmo, não outro nome (``_grafia_segura``) — senão, a
            # revisão do candidato único de antes da mudança.
            fora = _casa_fora_da_sala(ctx, ident, chave)
            if fora:
                return _revisar_casa_fora(ctx, fora, res.candidatos, res.motivo, chave,
                                          alvo_nome)
            if not _grafia_segura(nome_casar, ctx.alunos[res.aluno_id].nome):
                res = replace(res, status=matching.REVISAR)
        if res.status == matching.VINCULADO and res.aluno_id in ctx.alunos:
            return _para_aluno(ctx, linha, ctx.alunos[res.aluno_id], res.motivo, chave,
                               chave_alt=chave_alt)
        if res.status == matching.REVISAR:
            # 3c) Ficha oficial da Lista Piloto × duplicata abreviada dela na sala:
            # desempate determinístico, com as guardas de sempre (``_para_aluno``:
            # ficha inativa, outra conta nesta plataforma → revisão). Se a linha não
            # casa com a oficial por nome IDÊNTICO, um homônimo exato em outra sala
            # manda para a revisão — o desempate é novo e não arrisca.
            desempate = _oficial_entre_duplicatas(ctx, linha, ident, res.candidatos)
            if desempate is not None and desempate[1] != "exato":
                fora = _casa_fora_da_sala(ctx, ident, chave)
                if fora:
                    return _revisar_casa_fora(ctx, fora, res.candidatos, res.motivo, chave,
                                              alvo_nome)
                if (desempate[1] in _VIA_GRAFIA
                        and not _grafia_segura(nome_casar, desempate[0].nome)):
                    desempate = None
            if desempate is not None:
                oficial, como = desempate
                dec = _para_aluno(ctx, linha, oficial, "lista_piloto_unica", chave,
                                  candidatos=res.candidatos, chave_alt=chave_alt)
                if dec.acao == ASSOCIAR:
                    dec = replace(dec, preteridos=tuple(
                        i for i in res.candidatos if i != oficial.id))
                return dec
            motivo = ("candidatos_multiplos" if len(res.candidatos) > 1
                      else "correspondencia_insegura")
            return Decisao(REVISAR, res.aluno_id, res.motivo, motivo, res.candidatos,
                           chave_sala=chave)
        vetados = res.vetados

    # 4) Homônimo EXATO fora da sala (outra turma/série, qualquer status não
    # excluído). Com a sala conhecida ele NÃO casa — é revisão (pode ser a mesma
    # criança que mudou de sala, ou outra criança). Sem sala utilizável, o nome
    # idêntico ÚNICO na escola é a melhor evidência que existe.
    fora = _homonimos_fora_da_sala(ctx, ident, alvo_nome, na_sala)
    if fora:
        ids = tuple(a.id for a in fora)
        if not sala_conhecida and len(fora) == 1:
            return _para_aluno(ctx, linha, fora[0], "exato", chave, chave_alt=chave_alt)
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
