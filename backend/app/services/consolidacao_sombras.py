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
diferentes (gêmeos, irmãos, homônimos). Sem limiar numérico de similaridade: só
as relações que o motor único (``matching``) já define. Uma sombra S é
CONSOLIDADA na oficial O quando TODAS valem:

  (a) S está ativa e fora da Lista Piloto, e nenhum identificador (nº de
      chamada, nascimento, RA) diverge do de O (``matching.conflito_identidade``);
  (b) O é a ÚNICA ficha da Lista Piloto, ativa, na MESMA turma do ano ativo com
      ``matching.plausivel(S, O) == "forte"`` — nome igual ou forma
      abreviada/truncada dele. Duas oficiais compatíveis (gêmeos) → revisão.
      Grafia diferente (RICADO × RICARDO) nunca é "forte", então uma letra
      diferente no prenome NUNCA consolida (decisão 3 do dono, 12/10: esse caso
      segue na revisão manual);
  (c) nenhuma OUTRA ficha da escola — qualquer turma, Lista Piloto ou não, ativa
      ou não — é "forte" com S sem ter conta PRÓPRIA (efetiva) nas plataformas
      em que S tem conta. Se houver, S pode ser a criança da outra turma (o irmão
      da 4ºA com o mesmo prenome): revisão. Homônimo com conta própria na
      plataforma não bloqueia — a conta de S não é a dele. As outras sombras da
      MESMA oficial não bloqueiam, desde que elas também sejam consolidáveis;
  (d) S não tem conta (efetiva ou aposentada) numa plataforma em que O já tem
      conta, nem duas contas numa mesma plataforma, nem divide plataforma com
      outra sombra da mesma O — a criança ficaria com duas contas, e qual delas
      é ela é decisão de gente (CONFLITO). Pendência de revisão que CONTESTA a
      conta de S ("o aluno já tem outra conta nesta plataforma", "a identidade
      já pertence a outro aluno") também é CONFLITO;
  (e) nome IDÊNTICO ao de O (mesmos tokens) só consolida se S não tiver conta em
      NENHUMA plataforma: com conta, pode ser outra criança real de mesmo nome
      (a mesma regra de ``_oficial_entre_duplicatas``);
  (f) nenhuma revisão resolvida por HUMANO escolheu S como destino — uma pessoa
      já tratou S como ficha própria;
  (g) S tem uma única matrícula no ano ativo, na turma de O.

E uma trava de "nunca perder dado": se as DUAS fichas têm perfil ou credencial
do Quest, a fusão descartaria um deles (com o progresso) — revisão.

O DESTINO de cada ficha ativa fora da Lista Piloto matriculada no ano ativo:
CONSOLIDAR (com as evidências), REVISAR (motivo), CONFLITO (motivo) ou SEM_PAR
(nenhuma ficha da Lista Piloto em que ela possa ser — é outra criança).

``planejar`` só LÊ. ``aplicar`` reconfere cada par contra o banco ATUAL antes de
fundir (compare-and-set), funde com ``alunos_fusao.fundir_par`` (a MESMA fusão
da tela), audita ``aluno.consolidado_automatico``, faz UM commit e UM recálculo
da escola. Rodar de novo não acha nada: a sombra fundida deixou de existir.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Aluno, Escola, IdentidadeExterna, Matricula, RevisaoIdentidade
from app.services import alunos_fusao, matching
from app.services.audit import registrar
from app.services.identidade_aluno import identidade_do_aluno
from app.services.importacao import chave_nome, tokens_nome

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
    "nome_parecido_na_turma": "na turma há ficha da Lista Piloto de nome só parecido "
                              "(grafia diferente ou nome parcial)",
    "identificador_divergente": "nº de chamada, nascimento ou RA divergem dos da "
                                "ficha oficial",
    "decisao_humana_na_sombra": "uma pessoa já escolheu esta ficha numa revisão de "
                                "identidade",
    "conta_aposentada_na_sombra": "uma pessoa já aposentou uma conta desta ficha",
    "nome_identico_com_conta": "nome idêntico ao da oficial e com conta de plataforma: "
                               "pode ser outra criança de mesmo nome",
    "compativel_em_outra_ficha": "outra ficha da escola, sem conta própria nesta "
                                 "plataforma, também corresponde ao nome",
    "sombra_irma_em_revisao": "outra ficha-sombra da mesma oficial não pode ser "
                              "consolidada",
    "quest_nos_dois": "as duas fichas têm perfil/credencial do Quest — a fusão "
                      "descartaria um deles",
    "duas_contas_mesma_plataforma": "a criança ficaria com duas contas na mesma "
                                    "plataforma",
    "conta_contestada": "há revisão pendente contestando a conta desta ficha",
}

# Pendências que CONTESTAM a conta de uma ficha (``identidade_aluno.MOTIVOS``): a
# fila guarda uma dúvida de "duas contas / conta de outro" que só gente resolve.
_MOTIVOS_DE_CONTA_CONTESTADA = ("outra_identidade_na_plataforma",
                                "identidade_de_outro_aluno")

# Regra registrada na auditoria de cada fusão automática.
REGRA = "ficha_sombra_da_lista_piloto"


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
# Estado da escola (lido uma vez por plano)
# ---------------------------------------------------------------------------

@dataclass
class _Estado:
    escola_id: int
    ano: int
    alunos: dict[int, Aluno] = field(default_factory=dict)        # não excluídos
    tokens: dict[int, list[str]] = field(default_factory=dict)
    turmas_de: dict[int, list[int]] = field(default_factory=dict)  # no ano ativo
    # aluno → plataforma → [(id_externo, status)] — efetivas E aposentadas
    contas: dict[int, dict[str, list[tuple[str, str]]]] = field(default_factory=dict)
    escolhidas_por_humano: set[int] = field(default_factory=set)
    contestadas: set[int] = field(default_factory=set)
    por_inicial: dict[str, set[int]] = field(default_factory=dict)
    por_tokens: dict[frozenset, set[int]] = field(default_factory=dict)
    # Fichas da Lista Piloto ATIVAS por turma do ano ativo (as oficiais possíveis).
    oficiais_da_turma: dict[int, list[int]] = field(default_factory=dict)

    def plataformas(self, aluno_id: int) -> set[str]:
        return set(self.contas.get(aluno_id, {}))

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
    escola = db.get(Escola, escola_id)
    est = _Estado(escola_id=escola_id, ano=(escola.ano_letivo_ativo if escola else 0) or 0)
    for aluno in db.execute(select(Aluno).where(Aluno.escola_id == escola_id,
                                                Aluno.status != "excluido")
                            .order_by(Aluno.id)).scalars():
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
        if a is not None and a.da_lista_piloto and a.status == "ativo" and len(turmas) == 1:
            est.oficiais_da_turma.setdefault(turmas[0], []).append(aluno_id)
    for aluno_id, plataforma, id_externo, status in db.execute(
            select(IdentidadeExterna.aluno_id, IdentidadeExterna.plataforma,
                   IdentidadeExterna.id_externo, IdentidadeExterna.status)
            .where(IdentidadeExterna.escola_id == escola_id)
            .order_by(IdentidadeExterna.id)).all():
        est.contas.setdefault(aluno_id, {}).setdefault(plataforma, []).append(
            (str(id_externo), status or "efetiva"))
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
    for (candidatos,) in db.execute(
            select(RevisaoIdentidade.candidatos)
            .where(RevisaoIdentidade.escola_id == escola_id,
                   RevisaoIdentidade.status == "pendente",
                   RevisaoIdentidade.motivo.in_(_MOTIVOS_DE_CONTA_CONTESTADA))).all():
        for c in candidatos or []:
            if isinstance(c, dict) and isinstance(c.get("aluno_id"), int):
                est.contestadas.add(c["aluno_id"])
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
    """O que precisa continuar IGUAL para o par ainda ser o par do plano."""
    def ident(a: Aluno) -> tuple:
        i = identidade_do_aluno(a)
        return (chave_nome(a.nome), a.status, bool(a.da_lista_piloto), i.chamada,
                i.nascimento, i.ra)
    contas = tuple(sorted((p, i, st) for p, lst in est.contas.get(s.id, {}).items()
                          for i, st in lst))
    return (s.id, o.id, turma_id, ident(s), ident(o), contas)


def _classificar(db: Session, est: _Estado, sid: int) -> Item:
    s = est.alunos[sid]
    turmas = est.turmas_de.get(sid, [])
    if len(turmas) != 1:                                           # (g)
        return Item(sid, REVISAR, "matriculas_multiplas")
    turma = turmas[0]
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
            if matching.plausivel(s.nome, est.alunos[i].nome) in ("parcial", "fraco"))
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
    plats_s = est.plataformas(sid)
    if sid in est.contestadas:                                     # (d)
        return Item(sid, CONFLITO, "conta_contestada", **par)
    contas_s = est.contas.get(sid, {})
    if (plats_s & est.plataformas(oid)
            or any(len(lst) > 1 for lst in contas_s.values())):
        return Item(sid, CONFLITO, "duas_contas_mesma_plataforma", **par)
    if any(st == "aposentada" for lst in contas_s.values() for _i, st in lst):
        # Aposentar uma conta é decisão de gente sobre ESTA ficha: ela já não é
        # uma sombra anônima (o mesmo critério de ``_oficial_entre_duplicatas``).
        return Item(sid, REVISAR, "conta_aposentada_na_sombra", **par)
    identico = set(est.tokens[sid]) == set(est.tokens[oid])
    if identico and plats_s:                                       # (e)
        return Item(sid, REVISAR, "nome_identico_com_conta", **par)
    # (c) As OUTRAS fichas que casam "forte" com a sombra.
    irmas: list[int] = []
    com_conta_propria: list[int] = []
    bloqueadoras: list[int] = []
    sem_chamada_s = replace(id_s, chamada=None)
    for fid in fortes:
        if fid == oid:
            continue
        f = est.alunos[fid]
        # Identificador ESTÁVEL divergente prova que é outra criança (a chamada é
        # numeração da sala e, fora dela, não prova nada).
        if matching.conflito_identidade(sem_chamada_s,
                                        replace(identidade_do_aluno(f), chamada=None)):
            continue
        # Conta PRÓPRIA (efetiva) em TODAS as plataformas em que a sombra tem
        # conta: a conta da sombra não é a dessa ficha. Sem conta na sombra, não
        # há o que provar — qualquer ficha compatível bloqueia.
        if plats_s and all(est.tem_efetiva(fid, p) for p in plats_s):
            com_conta_propria.append(fid)
            continue
        if (not f.da_lista_piloto and f.status == "ativo"
                and est.turmas_de.get(fid) == [turma]
                and matching.plausivel(f.nome, o.nome) == "forte"):
            irmas.append(fid)                  # outra sombra da MESMA oficial
            continue
        bloqueadoras.append(fid)
    if bloqueadoras:
        return Item(sid, REVISAR, "compativel_em_outra_ficha",
                    relacionados=tuple(bloqueadoras), **par)
    if _quest_nos_dois(db, sid, oid):
        return Item(sid, REVISAR, "quest_nos_dois", **par)
    evidencias = {
        "regra": REGRA,
        "relacao_nome": "nome_identico" if identico else "abreviacao",
        "turma_id": turma,
        "plataformas_da_sombra": sorted(plats_s),
        "identificadores_divergentes": False,
        "outras_compativeis_com_conta_propria": com_conta_propria,
        "outras_sombras_da_mesma_oficial": irmas,
    }
    return Item(sid, CONSOLIDAR, "", relacionados=tuple(irmas), evidencias=evidencias,
                assinatura=_assinatura(est, s, o, turma), **par)


def _travas_do_grupo(est: _Estado, itens: dict[int, Item]) -> None:
    """Regras que olham as sombras de uma MESMA oficial em conjunto (no lugar).

      * irmã que não vai para a mesma oficial: se ela pode ser outra criança, a
        sombra também pode ser dela → revisão;
      * duas sombras da mesma oficial com conta na mesma plataforma: a criança
        ficaria com duas contas → conflito.
    Repete até estabilizar: rebaixar uma sombra pode rebaixar a irmã dela."""
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
        grupos: dict[int, list[Item]] = defaultdict(list)
        for item in itens.values():
            if item.classe == CONSOLIDAR:
                grupos[item.oficial_id].append(item)
        for grupo in grupos.values():
            por_plataforma: dict[str, list[Item]] = defaultdict(list)
            for item in grupo:
                for p in est.plataformas(item.sombra_id):
                    por_plataforma[p].append(item)
            for repetidas in por_plataforma.values():
                if len(repetidas) < 2:
                    continue
                ids = tuple(i.sombra_id for i in repetidas)
                for item in repetidas:
                    if itens[item.sombra_id].classe != CONSOLIDAR:
                        continue
                    itens[item.sombra_id] = replace(
                        item, classe=CONFLITO, motivo="duas_contas_mesma_plataforma",
                        relacionados=tuple(i for i in ids if i != item.sombra_id),
                        evidencias={}, assinatura=())
                    mudou = True


def planejar(db: Session, escola_id: int) -> Plano:
    """SOMENTE LEITURA: o destino de cada ficha ATIVA, FORA da Lista Piloto e
    matriculada no ano ativo da escola. Não grava nada."""
    est = _carregar(db, escola_id)
    alvos = [i for i, a in est.alunos.items()
             if a.status == "ativo" and not a.da_lista_piloto and i in est.turmas_de]
    itens = {sid: _classificar(db, est, sid) for sid in alvos}
    _travas_do_grupo(est, itens)
    return Plano(escola_id=escola_id, ano=est.ano,
                 itens=[itens[sid] for sid in sorted(itens)])


# ---------------------------------------------------------------------------
# Aplicação
# ---------------------------------------------------------------------------

def _recalcular(db: Session, escola_id: int) -> None:
    """O MESMO recálculo da fusão em lote (Alunos › Fundir duplicatas): notas e
    rankings da escola + cache do painel."""
    from app.routers.academico import _recalcular_escola
    _recalcular_escola(db, escola_id)


def aplicar(db: Session, plano: Plano, *, usuario_id: int | None, origem: str,
            recalcular: bool = True) -> dict:
    """Funde cada par CONSOLIDAR do ``plano`` — e só eles: REVISAR, CONFLITO e
    SEM_PAR nunca chegam à fusão.

    COMPARE-AND-SET: antes de cada fusão o par é planejado de novo a partir do
    banco ATUAL (com as duas fichas travadas no Postgres). Se a sombra já não é
    CONSOLIDAR para a mesma oficial, ou o retrato do par mudou (nome, status,
    identificadores, contas), o par é PULADO e o salto fica auditado
    (``aluno.consolidacao_pulada``). A trava de importação da escola serializa a
    consolidação com importação/sincronização concorrente.

    Cada fusão é a da tela (``alunos_fusao.fundir_par``: move snapshots,
    leituras, eventos, contas, matrícula/nota, Quest; audita ``aluno.fundido``
    com a foto pré-fusão) mais a auditoria ``aluno.consolidado_automatico`` com
    as evidências. UM commit no fim e UM recálculo da escola (só se fundiu)."""
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
        r = alunos_fusao.fundir_par(db, escola_id, oficial, sombra, usuario_id)
        detalhes = {
            "sombra_id": item.sombra_id, "oficial_id": item.oficial_id,
            "turma_id": item.turma_id, "motivo": REGRA, "origem": origem,
            "evidencias": dict(atual.evidencias), "plataformas_movidas": plataformas,
            "identidades_movidas": r["identidades_movidas"],
            "snapshots_matific": r["snapshots_matific"],
            "snapshots_elefante": r["snapshots_elefante"],
            "leituras_movidas": r["leituras_movidas"],
            "eventos_movidos": r["eventos_movidos"],
        }
        registrar(db, "aluno.consolidado_automatico", escola_id=escola_id,
                  usuario_id=usuario_id, entidade="aluno", entidade_id=item.oficial_id,
                  detalhes=detalhes)
        db.flush()               # o próximo par é planejado já sem esta sombra
        consolidados.append({"sombra_id": item.sombra_id, "oficial_id": item.oficial_id,
                             "plataformas_movidas": plataformas})
    db.commit()
    if consolidados and recalcular:
        _recalcular(db, escola_id)
    return {"escola_id": escola_id, "consolidados": consolidados, "pulados": pulados}
