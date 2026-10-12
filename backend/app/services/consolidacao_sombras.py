"""Consolidação AUTOMÁTICA e SEGURA das fichas-sombra da sincronização.

O PROBLEMA. Em julho/agosto a sincronização do Matific recebia o nome TRUNCADO
pelo relatório ("ANA S", "LUCAS O") e, sem candidato seguro na sala, criava a
ficha. Nasceu assim a FICHA-SOMBRA: ativa, fora da Lista Piloto, sem nº de
chamada nem nascimento, matriculada na MESMA turma da ficha OFICIAL da mesma
criança — e dona da conta do Matific, que a oficial não tem. Desde então a
criança é duas: a Matemática cai na sombra, a Leitura na oficial, e o ranking e
a contagem da turma a contam duas vezes. O motor de identidade já desempata a
linha do Elefante para a oficial (``identidade_aluno._oficial_entre_duplicatas``),
mas não funde nada: a sombra continua lá, com a conta dela, até alguém fundir à
mão em Alunos › Fundir duplicatas — trabalho manual rotineiro onde a evidência
já basta.

A REGRA. Fundir sozinho só quando a evidência basta, e NUNCA juntar crianças
diferentes (gêmeos, irmãos, homônimos). Sem limiar numérico de similaridade: o
vínculo usa só as relações que o motor único (``matching``) já define; uma
relação mais frouxa (``_pode_ser_a_dona``) existe só para SEGURAR, nunca para
ligar. Uma sombra S é CONSOLIDADA na oficial O quando TODAS valem:

  (a) S está ativa e fora da Lista Piloto, e nenhum identificador (nº de
      chamada, nascimento, RA) diverge do de O (``matching.conflito_identidade``);
  (b) O é a ÚNICA ficha da Lista Piloto, ativa, na MESMA turma do ano ativo com
      ``matching.plausivel(S, O) == "forte"``. Duas oficiais compatíveis
      (gêmeos) → revisão;
  (b2) o nome de S é a FORMA DO RELATÓRIO do nome de O: o MESMO prenome, os
      nomes seguintes iguais por posição e só a última palavra reduzida à
      INICIAL ("ZULEICA R", "ZULEICA RAMONA T") — ou o mesmo nome, na mesma
      ordem. "Forte" sozinho não basta: ele também aceita prefixo de nome
      inteiro, e GABRIEL × GABRIELA, LUIS × LUISA ou RICARD × RICARDO são, na
      mesma sala, irmãos de sexo diferente. Fora da forma do relatório →
      revisão: prenome diferente, os mesmos nomes em outra ordem (MARIA CLARA ×
      CLARA MARIA), nome cortado no meio, ou a OFICIAL é que está abreviada (a
      ficha fora da lista tem o nome mais completo — não é sombra de relatório).
      Uma letra diferente no prenome (RICADO × RICARDO) nem chega a "forte":
      decisão 3 do dono, 12/10 — segue na revisão manual;
  (c) nenhuma OUTRA ficha pode ser a dona de S:
      * na escola inteira, nenhuma ficha "forte" com S — de qualquer turma e
        status, com ou sem conta. Só não bloqueia a ficha FORA da Lista Piloto,
        de OUTRA turma, com conta própria (efetiva) em todas as plataformas de
        S: é a sombra de outra criança, com a conta dela. Conta própria numa
        ficha da Lista Piloto, ou numa ficha da MESMA turma, não isenta: a
        criança pode ter ganhado uma SEGUNDA conta (mudou de turma, saiu da
        escola, a gêmea fora da lista);
      * na MESMA turma, nenhuma ficha de nome PARECIDO o bastante para ser a
        dona (``_pode_ser_a_dona``: o mesmo prenome — ou com uma letra/grafia
        de diferença — e cada nome seguinte de S começando um nome posterior
        dela, sem contar DE/DA/DOS). "TEOBALDO O" pode ser "TEOBALDO DE
        OLIVEIRA SOUSA" mesmo casando "forte" só com "TEOBALDO OTAVIO LIMA", e
        "KETLYN S" pode ser "KETLIN SOFIA";
      * as outras sombras da MESMA oficial (fora da lista, ativas, na turma,
        "forte" com O) não bloqueiam desde que também sejam consolidáveis — mas
        se um identificador ESTÁVEL (nascimento/RA) prova que duas delas são
        crianças diferentes, as duas vão para revisão;
  (d) S não tem conta nem DADO numa plataforma em que O já tem conta ou dado,
      nem duas contas numa mesma plataforma, nem divide plataforma com outra
      sombra da mesma O, nem tem conta CONTESTADA na fila → CONFLITO: qual
      retrato é o da criança é decisão de gente. Dado gravado por NOME, antes
      de existir a conta (snapshot, leitura, evento), conta como presença na
      plataforma. Contestada é a conta de S que aparece numa pendência "o
      aluno já tem outra conta" / "a identidade é de outro aluno", ou numa
      pendência de OUTRA conta da mesma plataforma que lista S como candidata;
  (e) nome IDÊNTICO ao de O só consolida se S não tiver conta nem dado em
      NENHUMA plataforma: com eles, pode ser outra criança real de mesmo nome
      (a mesma regra de ``_oficial_entre_duplicatas``);
  (f) nenhuma revisão resolvida por HUMANO escolheu S como destino — uma pessoa
      já tratou S como ficha própria;
  (g) S tem uma única matrícula no ano ativo, na turma de O.

E uma trava de "nunca perder dado": se as DUAS fichas têm perfil ou credencial
do Quest, a fusão descartaria um deles (com o progresso) — revisão. A leitura do
mesmo livro nas duas fichas (que a fusão descartaria com data e tempo) já cai
em (d): as duas têm dado do Elefante.

O DESTINO de cada ficha ativa fora da Lista Piloto matriculada no ano ativo:
CONSOLIDAR (com as evidências), REVISAR (motivo), CONFLITO (motivo) ou SEM_PAR
(nenhuma ficha da Lista Piloto em que ela possa ser — é outra criança).

``planejar`` só LÊ. ``aplicar`` reconfere cada par contra o banco ATUAL antes de
fundir (compare-and-set), funde com ``alunos_fusao.fundir_par`` (a MESMA fusão
da tela), audita ``aluno.consolidado_automatico`` e recalcula a escola — tudo
numa transação só, com UM commit: ou as fusões, a auditoria e as notas ficam
juntas, ou nada fica. Rodar de novo não acha nada: a sombra fundida deixou de
existir.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Aluno,
    Escola,
    EventoAluno,
    IdentidadeExterna,
    Leitura,
    Matricula,
    RevisaoIdentidade,
    SnapshotElefante,
    SnapshotMatific,
)
from app.services import alunos_fusao, matching
from app.services._nomes import PARTICULAS
from app.services.audit import registrar
from app.services.identidade_aluno import (
    _distancia_edicao,
    _forma_ortografica,
    identidade_do_aluno,
)
from app.services.importacao import (
    casa_abreviado,
    casa_abreviado_posicional,
    chave_nome,
    tokens_nome,
)

CONSOLIDAR = "consolidar"
REVISAR = "revisar"
CONFLITO = "conflito"
SEM_PAR = "sem_par"
CLASSES = (CONSOLIDAR, REVISAR, CONFLITO, SEM_PAR)

# Rótulos humanos dos motivos (script, log e auditoria).
MOTIVOS = {
    "matriculas_multiplas": "a ficha tem mais de uma matrícula no ano ativo",
    "varias_oficiais": "mais de uma ficha da Lista Piloto compatível na turma "
                       "(gêmeos/irmãos)",
    "oficial_em_outra_turma": "a ficha da Lista Piloto compatível está em outra turma",
    "nome_parecido_na_turma": "na turma há ficha de nome parecido que também pode ser "
                              "a dona (grafia diferente, partícula, nome parcial)",
    "identificador_divergente": "nº de chamada, nascimento ou RA divergem dos da "
                                "ficha oficial",
    "decisao_humana_na_sombra": "uma pessoa já escolheu esta ficha numa revisão de "
                                "identidade",
    "conta_aposentada_na_sombra": "uma pessoa já aposentou uma conta desta ficha",
    "nome_identico_com_conta": "nome idêntico ao da oficial e com conta ou dado de "
                               "plataforma: pode ser outra criança de mesmo nome",
    "nome_em_outra_ordem": "os mesmos nomes da oficial em outra ordem (MARIA CLARA × "
                           "CLARA MARIA): pode ser outra criança",
    "prenome_diferente": "o prenome não é o mesmo da oficial (GABRIEL × GABRIELA): "
                         "irmãos e gêmeos se distinguem pelo prenome",
    "oficial_abreviada": "a ficha da Lista Piloto é que tem o nome abreviado; esta "
                         "tem o nome mais completo — não é a forma do relatório",
    "truncamento_fora_do_padrao": "um nome foi cortado no meio (RICARD × RICARDO), não "
                                  "reduzido à inicial como o relatório faz",
    "compativel_em_outra_ficha": "outra ficha da escola também corresponde ao nome e "
                                 "pode ser a dona da conta",
    "sombras_distintas": "outra ficha-sombra da mesma oficial tem nascimento/RA "
                         "diferente: são crianças diferentes",
    "sombra_irma_em_revisao": "outra ficha-sombra da mesma oficial não pode ser "
                              "consolidada",
    "quest_nos_dois": "as duas fichas têm perfil/credencial do Quest — a fusão "
                      "descartaria um deles",
    "duas_contas_mesma_plataforma": "a criança ficaria com duas contas (ou dois "
                                    "retratos) na mesma plataforma",
    "conta_contestada": "há revisão pendente contestando a conta desta ficha",
}

# Pendências que CONTESTAM a conta de uma ficha (``identidade_aluno.MOTIVOS``): a
# fila guarda uma dúvida de "duas contas / conta de outro" que só gente resolve.
_MOTIVOS_DE_CONTA_CONTESTADA = ("outra_identidade_na_plataforma",
                                "identidade_de_outro_aluno")

# Regra registrada na auditoria de cada fusão automática.
REGRA = "ficha_sombra_da_lista_piloto"

# As linhas de dado de uma ficha, por tabela — o que a fusão move ou descarta.
# A auditoria guarda os IDS (não só as contagens): desfazer uma consolidação
# errada pelo log precisa saber QUAIS linhas vieram da sombra.
_TABELAS_DA_FICHA = (
    ("snapshots_matific", SnapshotMatific),
    ("snapshots_elefante", SnapshotElefante),
    ("leituras", Leitura),
    ("eventos", EventoAluno),
    ("identidades_externas", IdentidadeExterna),
)


@dataclass
class Item:
    """O destino de UMA ficha fora da Lista Piloto. Só ids — nome é PII e fica no
    banco (o script os mostra só com ``--nomes``)."""
    sombra_id: int
    classe: str
    motivo: str = ""
    oficial_id: int | None = None
    turma_id: int | None = None
    # Ids que explicam o destino: as oficiais (gêmeos), as fichas que bloquearam
    # (irmão de outra turma) ou, num CONSOLIDAR, as outras sombras da mesma oficial.
    relacionados: tuple[int, ...] = ()
    evidencias: dict = field(default_factory=dict)
    # Retrato do par no momento do plano: ``aplicar`` só funde se o banco atual
    # der o MESMO retrato (compare-and-set).
    assinatura: tuple = ()

    def como_dict(self) -> dict:
        return {"sombra_id": self.sombra_id, "classe": self.classe,
                "motivo": self.motivo or None, "oficial_id": self.oficial_id,
                "turma_id": self.turma_id, "relacionados": list(self.relacionados),
                "evidencias": dict(self.evidencias)}


@dataclass
class Plano:
    escola_id: int
    ano: int
    itens: list[Item] = field(default_factory=list)

    def da_classe(self, classe: str) -> list[Item]:
        return [i for i in self.itens if i.classe == classe]

    @property
    def consolidar(self) -> list[Item]:
        return self.da_classe(CONSOLIDAR)

    def contagens(self) -> dict[str, int]:
        return {c: len(self.da_classe(c)) for c in CLASSES}

    def item_da_sombra(self, sombra_id: int) -> Item | None:
        return next((i for i in self.itens if i.sombra_id == sombra_id), None)


# ---------------------------------------------------------------------------
# Nomes: a forma do relatório e a relação frouxa que só segura
# ---------------------------------------------------------------------------

def _forma_do_nome(ts: list[str], to: list[str]) -> str:
    """Como o nome da ficha fora da lista (``ts``) se relaciona com o da oficial
    (``to``), sabendo que ``plausivel`` já deu "forte". Devolve ``"identico"``,
    ``"truncado"`` (a forma que o relatório produz) ou o MOTIVO da revisão.

    A forma do relatório é posicional e estreita (``casa_abreviado_posicional``):
    prenome idêntico, os nomes do meio idênticos por posição e só a ÚLTIMA
    palavra reduzida a uma inicial. É o que o Matific escreve ("WENDY S",
    "HEITOR O"); prefixo de nome inteiro (GABRIEL → GABRIELA) e corte no meio
    (RICARD → RICARDO) não são."""
    if ts == to:
        return "identico"
    if set(ts) == set(to):
        return "nome_em_outra_ordem"
    if ts[0] != to[0]:
        return "prenome_diferente"
    if len(ts[-1]) == 1 and casa_abreviado_posicional(ts, to):
        return "truncado"
    if casa_abreviado(to, ts):
        return "oficial_abreviada"
    return "truncamento_fora_do_padrao"


def _prenome_proximo(a: str, b: str) -> bool:
    """O mesmo prenome — ou com uma letra, a grafia (Y/I, K/C, TH/T…) ou o fim
    de diferença. Só para SEGURAR: é aqui que a decisão 3 do dono (uma letra no
    prenome = revisão manual) protege a dona real que o "forte" não enxerga."""
    return (a == b or _forma_ortografica(a) == _forma_ortografica(b)
            or _distancia_edicao(a, b) <= 1
            or (min(len(a), len(b)) >= 3 and (a.startswith(b) or b.startswith(a))))


def _nome_cabe(tok: str, alvo: str) -> bool:
    if alvo.startswith(tok):                       # inicial ou começo do nome
        return True
    return len(tok) > 1 and (_forma_ortografica(tok) == _forma_ortografica(alvo)
                             or _distancia_edicao(tok, alvo) <= 1)


def _pode_ser_a_dona(ts: list[str], tf: list[str]) -> bool:
    """A ficha de tokens ``tf`` PODE ser a dona do nome truncado ``ts``?

    Relação FROUXA, usada só para BLOQUEAR (nunca para vincular): prenome
    próximo (``_prenome_proximo``) e cada nome seguinte de ``ts`` cabendo, em
    ordem, num nome POSTERIOR de ``tf`` — sem contar as partículas. O relatório
    corta o nome que a escola digitou na plataforma, e a partícula ou um
    sobrenome pulado tiram a dona real do alcance do "forte": "TEOBALDO O" não
    é "forte" com "TEOBALDO DE OLIVEIRA SOUSA", mas é dela."""
    if not ts or not tf or not _prenome_proximo(ts[0], tf[0]):
        return False
    resto = [t for t in tf[1:] if t not in PARTICULAS]
    i = 0
    for tok in (t for t in ts[1:] if t not in PARTICULAS):
        while i < len(resto) and not _nome_cabe(tok, resto[i]):
            i += 1
        if i == len(resto):
            return False
        i += 1
    return True


# ---------------------------------------------------------------------------
# Estado da escola (lido uma vez por plano)
# ---------------------------------------------------------------------------

@dataclass
class _Estado:
    escola_id: int
    ano: int
    alunos: dict[int, Aluno] = field(default_factory=dict)        # não excluídos
    tokens: dict[int, list[str]] = field(default_factory=dict)
    turmas_de: dict[int, list[int]] = field(default_factory=dict)  # no ano ativo
    da_turma: dict[int, list[int]] = field(default_factory=dict)   # turma → fichas
    # aluno → plataforma → [(id_externo, status)] — efetivas E aposentadas
    contas: dict[int, dict[str, list[tuple[str, str]]]] = field(default_factory=dict)
    # aluno → plataformas em que há DADO dele (snapshot, leitura, evento), com ou
    # sem conta registrada: o histórico gravado por nome antes do id externo.
    dados: dict[int, set[str]] = field(default_factory=dict)
    escolhidas_por_humano: set[int] = field(default_factory=set)
    contestadas: set[int] = field(default_factory=set)
    por_inicial: dict[str, set[int]] = field(default_factory=dict)
    por_tokens: dict[frozenset, set[int]] = field(default_factory=dict)
    # Fichas da Lista Piloto ATIVAS por turma do ano ativo (as oficiais possíveis).
    oficiais_da_turma: dict[int, list[int]] = field(default_factory=dict)

    def plataformas(self, aluno_id: int) -> set[str]:
        """Plataformas em que a ficha tem CONTA (efetiva ou aposentada)."""
        return set(self.contas.get(aluno_id, {}))

    def presenca(self, aluno_id: int) -> set[str]:
        """Plataformas em que a ficha tem conta OU dado."""
        return self.plataformas(aluno_id) | self.dados.get(aluno_id, set())

    def tem_efetiva(self, aluno_id: int, plataforma: str) -> bool:
        return any(st != "aposentada"
                   for _i, st in self.contas.get(aluno_id, {}).get(plataforma, ()))

    def fortes_com(self, aluno_id: int) -> list[int]:
        """Fichas (não excluídas) cujo nome é "forte" com o desta — decidido pelo
        MESMO ``matching.plausivel``. O índice só PODA quem não teria como ser
        forte, sem mudar o veredito: "forte" é o mesmo conjunto de tokens
        (``por_tokens``) ou uma abreviação POSICIONAL, em que o 1º token de um é o
        começo do 1º token do outro — a mesma letra inicial (``por_inicial``)."""
        toks = self.tokens.get(aluno_id) or []
        if not toks:
            return []
        cands = (self.por_inicial.get(toks[0][0], set())
                 | self.por_tokens.get(frozenset(toks), set()))
        nome = self.alunos[aluno_id].nome
        return sorted(i for i in cands
                      if i != aluno_id
                      and matching.plausivel(nome, self.alunos[i].nome) == "forte")


def _carregar(db: Session, escola_id: int) -> _Estado:
    # ``populate_existing``: as fichas vêm do BANCO, não do identity map. Sem
    # isso, quem chamou e ainda segura as fichas desta sessão (uma tela que
    # mostrou o par antes de aplicar) faria o compare-and-set de ``aplicar``
    # comparar o retrato VELHO com ele mesmo — e a mudança gravada por outra
    # transação (nº de chamada, entrada na Lista Piloto) passaria despercebida.
    escola = db.get(Escola, escola_id, populate_existing=True)
    est = _Estado(escola_id=escola_id, ano=(escola.ano_letivo_ativo if escola else 0) or 0)
    for aluno in db.execute(select(Aluno).where(Aluno.escola_id == escola_id,
                                                Aluno.status != "excluido")
                            .order_by(Aluno.id)
                            .execution_options(populate_existing=True)).scalars():
        est.alunos[aluno.id] = aluno
        toks = tokens_nome(aluno.nome)
        est.tokens[aluno.id] = toks
        if toks:
            est.por_inicial.setdefault(toks[0][0], set()).add(aluno.id)
            est.por_tokens.setdefault(frozenset(toks), set()).add(aluno.id)
    for aluno_id, turma_id in db.execute(
            select(Matricula.aluno_id, Matricula.turma_id)
            .where(Matricula.escola_id == escola_id, Matricula.ano_letivo == est.ano)
            .order_by(Matricula.id)).all():
        est.turmas_de.setdefault(aluno_id, []).append(turma_id)
    for aluno_id, turmas in est.turmas_de.items():
        a = est.alunos.get(aluno_id)
        if a is None:
            continue
        for turma_id in dict.fromkeys(turmas):
            est.da_turma.setdefault(turma_id, []).append(aluno_id)
        if a.da_lista_piloto and a.status == "ativo" and len(turmas) == 1:
            est.oficiais_da_turma.setdefault(turmas[0], []).append(aluno_id)
    for aluno_id, plataforma, id_externo, status in db.execute(
            select(IdentidadeExterna.aluno_id, IdentidadeExterna.plataforma,
                   IdentidadeExterna.id_externo, IdentidadeExterna.status)
            .where(IdentidadeExterna.escola_id == escola_id)
            .order_by(IdentidadeExterna.id)).all():
        est.contas.setdefault(aluno_id, {}).setdefault(plataforma, []).append(
            (str(id_externo), status or "efetiva"))
    # DADO de plataforma sem olhar a conta: o histórico do Elefante das escolas
    # foi gravado por NOME antes do studentId — a ficha "sem conta" pode ter o
    # retrato da criança. Leitura é do Elefante; o evento diz a plataforma.
    for modelo, plataforma in ((SnapshotMatific, "matific"),
                               (SnapshotElefante, "elefante"),
                               (Leitura, "elefante")):
        for (aluno_id,) in db.execute(select(modelo.aluno_id)
                                      .where(modelo.escola_id == escola_id)
                                      .distinct()).all():
            est.dados.setdefault(aluno_id, set()).add(plataforma)
    for aluno_id, plataforma in db.execute(
            select(EventoAluno.aluno_id, EventoAluno.plataforma)
            .where(EventoAluno.escola_id == escola_id).distinct()).all():
        if plataforma:
            est.dados.setdefault(aluno_id, set()).add(plataforma)
    # Escolha HUMANA = revisão resolvida que não foi encerrada pelo sistema
    # (``resolucao.automatica``) — o mesmo critério de memória humana de
    # ``identidade_aluno.carregar_contexto``. Aqui vale QUALQUER escolha já feita,
    # não só a mais recente da chave: basta uma pessoa ter tratado a ficha como
    # dona de um dado para ela deixar de ser sombra anônima.
    for aluno_id, resolucao in db.execute(
            select(RevisaoIdentidade.aluno_escolhido_id, RevisaoIdentidade.resolucao)
            .where(RevisaoIdentidade.escola_id == escola_id,
                   RevisaoIdentidade.status == "resolvida",
                   RevisaoIdentidade.aluno_escolhido_id.is_not(None))).all():
        if isinstance(resolucao, dict) and resolucao.get("automatica") is True:
            continue
        est.escolhidas_por_humano.add(aluno_id)
    # Conta CONTESTADA na fila. Além dos motivos que já dizem "duas contas / conta
    # de outro", vale QUALQUER pendência de uma OUTRA conta (outro id externo) da
    # mesma plataforma que lista a ficha como candidata: a 2ª conta chega com
    # outro recorte do nome ("ODILA SOFIA L" × "ODILA S") e o motor grava
    # "candidatos_multiplos" — mas a dúvida é a mesma (é a criança com conta
    # nova, ou outra criança?), e fundir antes levaria a conta da sombra para a
    # oficial sem ninguém decidir.
    for plataforma, id_externo, motivo, candidatos in db.execute(
            select(RevisaoIdentidade.plataforma, RevisaoIdentidade.id_externo,
                   RevisaoIdentidade.motivo, RevisaoIdentidade.candidatos)
            .where(RevisaoIdentidade.escola_id == escola_id,
                   RevisaoIdentidade.status == "pendente")).all():
        ids = {c["aluno_id"] for c in candidatos or []
               if isinstance(c, dict) and isinstance(c.get("aluno_id"), int)}
        if motivo in _MOTIVOS_DE_CONTA_CONTESTADA:
            est.contestadas |= ids
            continue
        if not plataforma or not id_externo:
            continue
        for aluno_id in ids:
            minhas = {i for i, _st in est.contas.get(aluno_id, {}).get(plataforma, ())}
            if minhas and str(id_externo) not in minhas:
                est.contestadas.add(aluno_id)
    return est


def _quest_nos_dois(db: Session, a: int, b: int) -> bool:
    """As duas fichas têm perfil OU as duas têm credencial do Quest? A fusão
    manteria um e descartaria o outro (com progresso/tentativas, ou a senha com
    que a criança entra) — perda que só uma pessoa pode aceitar."""
    from app.quest.models import QuestCredencialAluno, QuestPerfil  # noqa: E402
    for modelo in (QuestPerfil, QuestCredencialAluno):
        donos = set(db.execute(select(modelo.aluno_id)
                               .where(modelo.aluno_id.in_((a, b)))).scalars())
        if {a, b} <= donos:
            return True
    return False


def _assinatura(est: _Estado, s: Aluno, o: Aluno, turma_id: int) -> tuple:
    """O que precisa continuar IGUAL para o par ainda ser o par do plano. A
    presença de DADO nas plataformas não entra: a fusão da primeira sombra leva
    dado para a oficial e não pode pular a segunda — o choque de plataforma é
    reavaliado pela própria classificação (``_classificar`` (d))."""
    def ident(a: Aluno) -> tuple:
        i = identidade_do_aluno(a)
        return (chave_nome(a.nome), a.status, bool(a.da_lista_piloto), i.chamada,
                i.nascimento, i.ra)
    contas = tuple(sorted((p, i, st) for p, lst in est.contas.get(s.id, {}).items()
                          for i, st in lst))
    return (s.id, o.id, turma_id, ident(s), ident(o), contas)


def _irmas(est: _Estado, sid: int, o: Aluno, turma: int) -> tuple[int, ...]:
    """As OUTRAS sombras possíveis da mesma oficial: fichas fora da Lista Piloto,
    ativas, só nesta turma, com nome "forte" com a oficial — em qualquer classe
    do plano. Uma conta numa delas pesa sobre a consolidação desta mesmo quando
    ela própria vai para a revisão por outro motivo."""
    return tuple(
        i for i in est.da_turma.get(turma, ())
        if i not in (sid, o.id)
        and not est.alunos[i].da_lista_piloto and est.alunos[i].status == "ativo"
        and est.turmas_de.get(i) == [turma]
        and matching.plausivel(est.alunos[i].nome, o.nome) == "forte")


def _classificar(db: Session, est: _Estado, sid: int) -> Item:
    s = est.alunos[sid]
    turmas = est.turmas_de.get(sid, [])
    if len(turmas) != 1:                                           # (g)
        return Item(sid, REVISAR, "matriculas_multiplas")
    turma = turmas[0]
    ts = est.tokens[sid]
    fortes = est.fortes_com(sid)
    da_lista = [i for i in fortes if est.alunos[i].da_lista_piloto]
    oficiais = [i for i in da_lista
                if est.alunos[i].status == "ativo" and est.turmas_de.get(i) == [turma]]
    if not oficiais:
        if da_lista:
            return Item(sid, REVISAR, "oficial_em_outra_turma", turma_id=turma,
                        relacionados=tuple(da_lista))
        parecidas = tuple(
            i for i in sorted(est.oficiais_da_turma.get(turma, ()))
            if matching.plausivel(s.nome, est.alunos[i].nome) in ("parcial", "fraco")
            or _pode_ser_a_dona(ts, est.tokens[i]))
        if parecidas:
            return Item(sid, REVISAR, "nome_parecido_na_turma", turma_id=turma,
                        relacionados=parecidas)
        return Item(sid, SEM_PAR, turma_id=turma)
    if len(oficiais) > 1:                                          # (b) gêmeos
        return Item(sid, REVISAR, "varias_oficiais", turma_id=turma,
                    relacionados=tuple(oficiais))
    oid = oficiais[0]
    o = est.alunos[oid]
    par = {"oficial_id": oid, "turma_id": turma}
    id_s, id_o = identidade_do_aluno(s), identidade_do_aluno(o)
    if matching.conflito_identidade(id_s, id_o):                   # (a)
        return Item(sid, REVISAR, "identificador_divergente", **par)
    if sid in est.escolhidas_por_humano:                           # (f)
        return Item(sid, REVISAR, "decisao_humana_na_sombra", **par)
    pres_s = est.presenca(sid)
    contas_s = est.contas.get(sid, {})
    irmas = _irmas(est, sid, o, turma)
    if sid in est.contestadas:                                     # (d)
        return Item(sid, CONFLITO, "conta_contestada", **par)
    if (pres_s & est.presenca(oid)
            or any(len(lst) > 1 for lst in contas_s.values())):
        return Item(sid, CONFLITO, "duas_contas_mesma_plataforma", **par)
    dividem = tuple(i for i in irmas if est.presenca(i) & pres_s)
    if dividem:
        return Item(sid, CONFLITO, "duas_contas_mesma_plataforma",
                    relacionados=dividem, **par)
    if any(st == "aposentada" for lst in contas_s.values() for _i, st in lst):
        # Aposentar uma conta é decisão de gente sobre ESTA ficha: ela já não é
        # uma sombra anônima (o mesmo critério de ``_oficial_entre_duplicatas``).
        return Item(sid, REVISAR, "conta_aposentada_na_sombra", **par)
    forma = _forma_do_nome(ts, est.tokens[oid])                    # (b2)
    if forma not in ("identico", "truncado"):
        return Item(sid, REVISAR, forma, **par)
    if forma == "identico" and pres_s:                             # (e)
        return Item(sid, REVISAR, "nome_identico_com_conta", **par)

    # (c) Quem mais pode ser a dona desta ficha.
    sem_chamada_s = replace(id_s, chamada=None)

    def estavel_diverge(fid: int) -> bool:
        # Identificador ESTÁVEL divergente prova que é outra criança (a chamada é
        # numeração da sala e, fora dela, não prova nada).
        return matching.conflito_identidade(
            sem_chamada_s, replace(identidade_do_aluno(est.alunos[fid]), chamada=None))

    distintas = tuple(i for i in irmas if estavel_diverge(i))
    if distintas:
        # Duas "sombras" da mesma oficial que são crianças DIFERENTES: no máximo
        # uma é a oficial — escolher pela ordem dos ids seria fundir no escuro.
        return Item(sid, REVISAR, "sombras_distintas", relacionados=distintas, **par)
    com_conta_propria: list[int] = []
    bloqueadoras: list[int] = []
    for fid in fortes:
        if fid == oid or fid in irmas or estavel_diverge(fid):
            continue
        f = est.alunos[fid]
        # Só a ficha FORA da Lista Piloto, de OUTRA turma, com conta própria em
        # todas as plataformas da sombra, fica de fora: é a sombra de outra
        # criança, com a conta dela. Na Lista Piloto ou na mesma turma, conta
        # própria não prova nada — a criança pode ter ganhado uma 2ª conta.
        if (not f.da_lista_piloto and turma not in est.turmas_de.get(fid, ())
                and contas_s and all(est.tem_efetiva(fid, p) for p in contas_s)):
            com_conta_propria.append(fid)
            continue
        bloqueadoras.append(fid)
    if bloqueadoras:
        return Item(sid, REVISAR, "compativel_em_outra_ficha",
                    relacionados=tuple(bloqueadoras), **par)
    vistas = {sid, oid, *irmas, *fortes}
    parecidas = tuple(i for i in est.da_turma.get(turma, ())
                      if i not in vistas and _pode_ser_a_dona(ts, est.tokens[i])
                      and not estavel_diverge(i))
    if parecidas:
        return Item(sid, REVISAR, "nome_parecido_na_turma",
                    relacionados=(oid, *parecidas), **par)
    if _quest_nos_dois(db, sid, oid):
        return Item(sid, REVISAR, "quest_nos_dois", **par)
    evidencias = {
        "regra": REGRA,
        "relacao_nome": "nome_identico" if forma == "identico" else "abreviacao",
        "turma_id": turma,
        "plataformas_da_sombra": sorted(pres_s),
        "identificadores_divergentes": False,
        "outras_compativeis_com_conta_propria": com_conta_propria,
        "outras_sombras_da_mesma_oficial": list(irmas),
    }
    return Item(sid, CONSOLIDAR, "", relacionados=irmas, evidencias=evidencias,
                assinatura=_assinatura(est, s, o, turma), **par)


def _travas_do_grupo(itens: dict[int, Item]) -> None:
    """Irmã que não vai para a MESMA oficial: se ela pode ser outra criança, a
    sombra também pode ser dela → revisão (no lugar). Repete até estabilizar:
    rebaixar uma sombra pode rebaixar a irmã dela. (Duas sombras da mesma
    oficial na mesma plataforma já saem CONFLITO em ``_classificar``.)"""
    mudou = True
    while mudou:
        mudou = False
        for item in list(itens.values()):
            if item.classe != CONSOLIDAR:
                continue
            for irma in item.relacionados:
                outra = itens.get(irma)
                if (outra is None or outra.classe != CONSOLIDAR
                        or outra.oficial_id != item.oficial_id):
                    itens[item.sombra_id] = replace(
                        item, classe=REVISAR, motivo="sombra_irma_em_revisao",
                        relacionados=(irma,), evidencias={}, assinatura=())
                    mudou = True
                    break


def planejar(db: Session, escola_id: int) -> Plano:
    """SOMENTE LEITURA: o destino de cada ficha ATIVA, FORA da Lista Piloto e
    matriculada no ano ativo da escola. Não grava nada."""
    est = _carregar(db, escola_id)
    alvos = [i for i, a in est.alunos.items()
             if a.status == "ativo" and not a.da_lista_piloto and i in est.turmas_de]
    itens = {sid: _classificar(db, est, sid) for sid in alvos}
    _travas_do_grupo(itens)
    return Plano(escola_id=escola_id, ano=est.ano,
                 itens=[itens[sid] for sid in sorted(itens)])


# ---------------------------------------------------------------------------
# Aplicação
# ---------------------------------------------------------------------------

def _recalcular(db: Session, escola_id: int) -> None:
    """O recálculo da fusão em lote (Alunos › Fundir duplicatas) — notas e
    rankings da escola —, mas DENTRO da transação das fusões (``commit=False``):
    se ele falha, as fusões caem junto, e a criança nunca fica fundida com a nota
    velha (a da sombra, com a Matemática, apagada; a da oficial sem ela)."""
    from app.services import scoring
    scoring.recalcular_escola(db, escola_id, commit=False)


def _invalidar_cache(escola_id: int) -> None:
    from app.routers.publico import invalidar_cache_painel
    invalidar_cache_painel(escola_id)


def _linhas_da_ficha(db: Session, aluno_id: int) -> dict[str, list[int]]:
    return {nome: sorted(db.execute(select(modelo.id)
                                    .where(modelo.aluno_id == aluno_id)).scalars())
            for nome, modelo in _TABELAS_DA_FICHA}


def _destino_das_linhas(db: Session, antes: dict[str, list[int]]
                        ) -> tuple[dict[str, list[int]], dict[str, list[int]]]:
    """Das linhas que eram da sombra: as que sobreviveram (foram para a oficial)
    e as que a fusão descartou (repetidas). Chamado DEPOIS do flush do delete
    da sombra — o que não foi movido já caiu em cascata."""
    movidas: dict[str, list[int]] = {}
    descartadas: dict[str, list[int]] = {}
    modelos = dict(_TABELAS_DA_FICHA)
    for nome, ids in antes.items():
        vivas = set(db.execute(select(modelos[nome].id)
                               .where(modelos[nome].id.in_(ids))).scalars()) if ids else set()
        movidas[nome] = [i for i in ids if i in vivas]
        descartadas[nome] = [i for i in ids if i not in vivas]
    return movidas, descartadas


def aplicar(db: Session, plano: Plano, *, usuario_id: int | None, origem: str,
            recalcular: bool = True) -> dict:
    """Funde cada par CONSOLIDAR do ``plano`` — e só eles: REVISAR, CONFLITO e
    SEM_PAR nunca chegam à fusão.

    COMPARE-AND-SET: antes de cada fusão o par é planejado de novo a partir do
    banco ATUAL (com as duas fichas travadas no Postgres e relidas do banco,
    não do identity map). Se a sombra já não é CONSOLIDAR para a mesma oficial,
    ou o retrato do par mudou (nome, status, identificadores, contas, dados), o
    par é PULADO e o salto fica auditado (``aluno.consolidacao_pulada``). A trava
    de importação da escola serializa a consolidação com importação/sincronização
    concorrente.

    Cada fusão é a da tela (``alunos_fusao.fundir_par``: move snapshots,
    leituras, eventos, contas, matrícula/nota, Quest; audita ``aluno.fundido``
    com a foto pré-fusão e a ORIGEM automática) mais a auditoria
    ``aluno.consolidado_automatico`` com as evidências e os ids das linhas
    movidas/descartadas. ``usuario_id`` é quem pediu de verdade (None no
    agendador e no script): nenhuma pessoa vira autora de uma fusão que não fez.

    UMA transação: fusões, auditoria e o recálculo da escola (só se fundiu)
    caem juntos num único commit; qualquer falha propaga e quem chamou desfaz
    tudo (rollback). O cache do painel é invalidado depois do commit."""
    from app.core.database import bloquear_escola_para_importacao
    escola_id = plano.escola_id
    bloquear_escola_para_importacao(db, escola_id)
    consolidados: list[dict] = []
    pulados: list[dict] = []
    for item in plano.consolidar:
        travadas = set(db.execute(
            select(Aluno.id).where(Aluno.escola_id == escola_id,
                                   Aluno.id.in_((item.sombra_id, item.oficial_id)))
            .with_for_update()).scalars())
        atual = (planejar(db, escola_id).item_da_sombra(item.sombra_id)
                 if travadas == {item.sombra_id, item.oficial_id} else None)
        if (atual is None or atual.classe != CONSOLIDAR
                or atual.assinatura != item.assinatura):
            pulado = {"sombra_id": item.sombra_id, "oficial_id": item.oficial_id,
                      "classe_atual": atual.classe if atual else None,
                      "motivo_atual": (atual.motivo or None) if atual else "ficha_inexistente"}
            registrar(db, "aluno.consolidacao_pulada", escola_id=escola_id,
                      usuario_id=usuario_id, entidade="aluno", entidade_id=item.sombra_id,
                      detalhes={**pulado, "origem": origem, "motivo": "estado_mudou"})
            pulados.append(pulado)
            continue
        sombra = db.get(Aluno, item.sombra_id)
        oficial = db.get(Aluno, item.oficial_id)
        plataformas = list(atual.evidencias["plataformas_da_sombra"])
        antes = _linhas_da_ficha(db, item.sombra_id)
        r = alunos_fusao.fundir_par(db, escola_id, oficial, sombra, usuario_id,
                                    origem=f"consolidacao_automatica:{origem}")
        db.flush()               # o delete da sombra cai agora (cascata do resto)
        movidas, descartadas = _destino_das_linhas(db, antes)
        detalhes = {
            "sombra_id": item.sombra_id, "oficial_id": item.oficial_id,
            "turma_id": item.turma_id, "motivo": REGRA, "origem": origem,
            "evidencias": dict(atual.evidencias), "plataformas_movidas": plataformas,
            "identidades_movidas": r["identidades_movidas"],
            "snapshots_matific": r["snapshots_matific"],
            "snapshots_elefante": r["snapshots_elefante"],
            "leituras_movidas": r["leituras_movidas"],
            "eventos_movidos": r["eventos_movidos"],
            "linhas_movidas": movidas,
            "linhas_descartadas": descartadas,
        }
        registrar(db, "aluno.consolidado_automatico", escola_id=escola_id,
                  usuario_id=usuario_id, entidade="aluno", entidade_id=item.oficial_id,
                  detalhes=detalhes)
        db.flush()               # o próximo par é planejado já sem esta sombra
        consolidados.append({"sombra_id": item.sombra_id, "oficial_id": item.oficial_id,
                             "plataformas_movidas": plataformas})
    recalculou = bool(consolidados and recalcular)
    if recalculou:
        _recalcular(db, escola_id)
    db.commit()
    if recalculou:
        _invalidar_cache(escola_id)
    return {"escola_id": escola_id, "consolidados": consolidados, "pulados": pulados}
