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
ligar.

A FORMA DO NOME vem antes de qualquer comparação. O nome de cada ficha entra
sem o SUFIXO DA TURMA que o professor digitou na plataforma ("… ROSA 2B" na
2ºB; o MESMO ``identidade_aluno._nome_para_casar`` do motor, contra a sala da
própria ficha — sufixo de outra sala fica) e sem acento nem caixa (a vogal
acentuada que a plataforma perdeu e virou minúscula, "MAGALHaES", é
MAGALHÃES). E dois nomes que só diferem pelas partículas DE/DA/DO/DAS/DOS
("… SOARES SANTOS" × "… SOARES DOS SANTOS") são o MESMO nome — "idêntico",
com a regra (e). O "E" isolado NÃO entra nessa igualdade: no meio do nome ele
é ambíguo com uma INICIAL ("JULIETA E SAMPAIO" pode ser Julieta E[…] Sampaio),
e "JULIETA SAMPAIO" × "JULIETA E SAMPAIO" vai para a revisão. As partículas
não entram na forma ABREVIADA: o relatório corta por posição, e "TEOBALDO O"
não é a forma de "TEOBALDO DE OLIVEIRA" (seria "TEOBALDO D").

Uma sombra S é CONSOLIDADA na oficial O quando TODAS valem:

  (a) S está ativa e fora da Lista Piloto, e nenhum identificador (nº de
      chamada, nascimento, RA) diverge do de O (``matching.conflito_identidade``);
  (b) O é a ÚNICA ficha da Lista Piloto, ativa, na MESMA turma do ano ativo com
      nome "forte" com o de S (``matching.plausivel(S, O) == "forte"`` ou o
      mesmo nome sem as partículas). Duas oficiais compatíveis (gêmeos) →
      revisão;
  (b2) o nome de S é a FORMA DO RELATÓRIO do nome de O: o MESMO prenome, os
      nomes seguintes iguais por posição e só a última palavra reduzida à
      INICIAL ("ZULEICA R", "ZULEICA RAMONA T") — ou o mesmo nome, na mesma
      ordem (partículas à parte). "Forte" sozinho não basta: ele também aceita
      prefixo de nome inteiro, e GABRIEL × GABRIELA, LUIS × LUISA ou RICARD ×
      RICARDO são, na mesma sala, irmãos de sexo diferente. Fora da forma do
      relatório → revisão: prenome diferente, os mesmos nomes em outra ordem
      (MARIA CLARA × CLARA MARIA), nome cortado no meio, ou a OFICIAL é que
      está abreviada (a ficha fora da lista tem o nome mais completo — não é
      sombra de relatório). Uma letra diferente no prenome (RICADO × RICARDO)
      nem chega a "forte": decisão 3 do dono, 12/10 — segue na revisão manual,
      com qualquer continuidade de dados;
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
  (d) CONTAS: S não tem duas contas numa mesma plataforma nem conta CONTESTADA
      na fila (contestada é a conta de S que aparece numa pendência "o aluno já
      tem outra conta" / "a identidade é de outro aluno", ou numa pendência de
      OUTRA conta da mesma plataforma que lista S como candidata). E, em cada
      plataforma P em que S e O têm conta ou DADO (snapshot, leitura, evento —
      o gravado por NOME antes de existir a conta também conta):
        * O com conta própria em P (efetiva ou aposentada) → CONFLITO
          ``duas_contas_mesma_plataforma``: são duas contas reais;
        * O sem conta em P → só passa se for a MESMA conta CONTINUANDO da
          oficial para a sombra (``_continuidade``): (i) as duas têm snapshot
          de P; (ii) os retratos de P não se sobrepõem — todos os da ficha
          ANTERIOR em dia estritamente anterior ao primeiro da POSTERIOR; (ii')
          a anterior é a OFICIAL (``ordem_invertida``): nos pares medidos a
          ordem foi sempre oficial por nome ANTES, conta na sombra DEPOIS — uma
          conta que para e um dado por nome que começa na outra ficha é o
          retrato de duas contas; (iii) os contadores do LIMITE provam a mesma
          conta — e zero não prova nada (``contadores_zerados``: a conta nova
          de qualquer criança também começa ali). No Matific, cujos contadores
          (atividades, estrelas) são acumulados do ano, a anterior tem algum
          contador acima de zero e CADA contador da posterior é >= o MAIOR
          valor dele em todos os retratos da anterior, não só no último
          (``contador_regrediu``). No Elefante, NÃO: medido em produção
          (12/10), os contadores caem dentro da MESMA ficha (132 quedas de
          livros e 211 de minutos entre retratos seguidos), então "maior ou
          igual" não prova nada — o primeiro retrato da posterior tem de
          REPETIR EXATAMENTE o último da anterior nos quatro contadores
          (livros, minutos, questões tentadas e acertadas), com algum acima
          de zero (``contadores_diferentes_no_limite``,
          ``_SO_IGUALDADE_NO_LIMITE``); (iv) no máximo 31 dias entre o
          último retrato da anterior e o primeiro da posterior; (v) nenhum
          outro dado de P na anterior (leitura, evento) do dia do primeiro
          retrato da posterior em diante; (vi) o simétrico: todo dado de P
          da POSTERIOR (leitura, evento) de dia ANTERIOR ao do último retrato
          da anterior é CÓPIA de um dado da anterior — o histórico da conta
          reenviado. Um livro que a anterior não tem, lido enquanto ela ainda
          recebia retratos, prova duas contas ativas ao mesmo tempo. E, no
          Elefante, nenhum livro lido nas duas com data, tempo ou nível
          diferentes (a fusão descartaria uma das leituras). Qualquer falha →
          CONFLITO com o motivo dela.
      O padrão medido (12/10): a oficial tem o Matific ligado por NOME de abril
      a 31/07, a sombra o tem com a conta de 01/08 em diante e os contadores
      do limite são iguais (ou crescem) — é a mesma conta, não duas. No
      Elefante, 6 dos 8 pares reais têm o 1º retrato da sombra IDÊNTICO ao
      último da oficial nos quatro contadores; os 2 em que eles crescem ficam,
      de propósito, para a revisão humana. A mesma
      regra vale entre duas sombras da mesma O que dividem uma plataforma: as
      duas com conta nela → CONFLITO; só uma com conta → ela tem de ser a
      POSTERIOR (a por nome antes, a conta depois, como com a oficial); sem
      conta nenhuma, a continuidade vale nos dois sentidos — mas o MESMO
      sentido em todas as plataformas que elas dividem
      (``ordem_cruzada_entre_sombras``);
  (e) nome IDÊNTICO ao de O (após a forma do nome) com conta ou dado só
      consolida se, em TODAS as plataformas de S, a continuidade de (d) parte
      de dado ANTERIOR da própria O: a oficial tinha a conta antes, a sombra é
      a continuação. Sem esse dado anterior de O numa plataforma de S, pode
      ser outra criança real de mesmo nome → revisão (a mesma cautela de
      ``_oficial_entre_duplicatas``). Sem conta nem dado, consolida;
  (f) nenhuma revisão resolvida por HUMANO escolheu S como destino — uma pessoa
      já tratou S como ficha própria;
  (g) S tem uma única matrícula no ano ativo, na turma de O.

E uma trava de "nunca perder dado": se as DUAS fichas têm perfil ou credencial
do Quest, a fusão descartaria um deles (com o progresso) — revisão. A leitura do
mesmo livro nas duas fichas com data, tempo ou nível diferentes (que a fusão
descartaria) é CONFLITO em (d); a cópia idêntica da MESMA leitura (a plataforma
reenviou o histórico da conta) não perde nada. E "nunca dobrar": o evento dessa
leitura reenviada existe nas duas fichas com chaves DIFERENTES (a
``chave_natural`` leva o id da ficha), e a fusão sozinha o deixaria em dobro
na oficial — ``aplicar`` descarta a cópia e recalcula para a oficial a chave
dos eventos que só a sombra tinha (``_alinhar_eventos``).

O RISCO QUE A CONTINUIDADE NÃO ELIMINA. Datas e contadores fecham a criança
diferente que tinha dado ANTES de a oficial parar (vi), a que começa abaixo do
maior contador da oficial (iii), a oficial zerada (iii) e a ordem inversa
(ii'). No Matific, não fecham uma conta NOVA de outra criança que começa a
mandar dado só DEPOIS do último retrato da oficial e, até o primeiro retrato
dela (no máximo 31 dias), já passou de TODOS os contadores acumulados que a
oficial tinha no ano. Para a oficial com contador baixo isso é possível. No
Elefante a porta é mais estreita — a conta da outra criança teria de começar
com os QUATRO contadores iguais aos do último retrato da oficial —, mas, com
contadores baixos, não é impossível. O que segura esse caso é o resto da regra
(o nome na forma do relatório na mesma turma, ninguém mais que possa ser a
dona, a Lista Piloto) e a política da escola, que nasce "manual". Ver
``test_falsificacao_de_continuidade``.

O DESTINO de cada ficha ativa fora da Lista Piloto matriculada no ano ativo:
CONSOLIDAR (com as evidências), REVISAR (motivo), CONFLITO (motivo) ou SEM_PAR
(nenhuma ficha da Lista Piloto em que ela possa ser — é outra criança). As
evidências de um CONSOLIDAR guardam, por plataforma, a continuidade provada
(qual ficha veio antes, os dias do limite, o intervalo e os contadores dos dois
lados) e a forma do nome normalizada — só números, datas e rótulos, sem nome.

``planejar`` só LÊ. ``aplicar`` reconfere cada par contra o banco ATUAL antes de
fundir (compare-and-set), funde com ``alunos_fusao.fundir_par`` (a MESMA fusão
da tela, depois de alinhar os eventos), audita ``aluno.consolidado_automatico``
e recalcula a escola — tudo numa transação só, com UM commit: ou as fusões, a
auditoria e as notas ficam juntas, ou nada fica. As sombras da mesma oficial
que dividem uma plataforma são fundidas na ordem da continuidade (a anterior
primeiro), não na dos ids. Rodar de novo não acha nada: a sombra fundida deixou
de existir.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime

from sqlalchemy import func, select
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
    Turma,
)
from app.services import alunos_fusao, matching
from app.services._nomes import PARTICULAS
from app.services.audit import registrar
from app.services.eventos import chave_evento
from app.services.identidade_aluno import (
    _distancia_edicao,
    _forma_ortografica,
    _nome_para_casar,
    chave_sala,
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
    "nome_identico_com_conta": "nome idêntico ao da oficial e com conta ou dado numa "
                               "plataforma em que a oficial não tinha dado ANTES: pode "
                               "ser outra criança de mesmo nome",
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
    "duas_contas_mesma_plataforma": "as duas fichas têm conta própria na mesma "
                                    "plataforma (ou esta tem duas): são duas contas",
    "conta_contestada": "há revisão pendente contestando a conta desta ficha",
    # Falhas da CONTINUIDADE da conta (``_continuidade``): as duas fichas têm dado
    # da mesma plataforma e não dá para provar que é a mesma conta continuando.
    "continuidade_sem_retrato": "as duas fichas têm dado da mesma plataforma, mas "
                                "falta retrato (snapshot) numa delas para provar que "
                                "é a mesma conta continuando",
    "dados_simultaneos_mesma_plataforma": "as duas fichas recebem dado da mesma "
                                          "plataforma no mesmo período (retrato, "
                                          "leitura ou evento que a outra não tem): "
                                          "são duas contas, ou duas crianças",
    "ordem_invertida": "o dado da plataforma vem ANTES na ficha que deveria vir "
                       "depois (fora da lista antes da oficial, ou a conta antes do "
                       "dado por nome): uma conta que parou e outro dado que começou "
                       "na outra ficha são duas contas",
    "ordem_cruzada_entre_sombras": "duas fichas fora da lista dividem mais de uma "
                                   "plataforma e cada uma vem antes numa delas: não "
                                   "é uma conta só passando de uma ficha para a outra",
    "contadores_zerados": "todos os contadores da ficha anterior são zero: zero não "
                          "prova que a outra ficha continua a mesma conta",
    "contador_regrediu": "no limite entre as duas fichas um contador acumulado da "
                         "plataforma ficou abaixo do maior valor da ficha anterior: "
                         "não é a mesma conta continuando",
    "contadores_diferentes_no_limite": "nesta plataforma os contadores não são "
                                       "acumulados (podem cair na mesma conta): só o "
                                       "primeiro retrato de uma ficha REPETINDO o último "
                                       "da outra prova que é a mesma conta",
    "intervalo_longo": "mais de 31 dias entre o último retrato de uma ficha e o "
                       "primeiro da outra: não há como provar que é a mesma conta",
    "leitura_repetida_nas_duas_fichas": "o mesmo livro lido nas duas fichas com data, "
                                        "tempo ou nível diferentes: a fusão descartaria "
                                        "uma das leituras",
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

# Os contadores do ano que cada plataforma manda no snapshot. No Matific eles são
# ACUMULADOS: a MESMA conta nunca os vê diminuir de um retrato para o seguinte. No
# Elefante, na prática, não (``_SO_IGUALDADE_NO_LIMITE``). Plataforma fora daqui
# não tem retrato com que provar continuidade (→ CONFLITO).
_CONTADORES = {
    "matific": (SnapshotMatific, ("atividades", "estrelas")),
    "elefante": (SnapshotElefante, ("livros_unicos", "tempo_leitura_min",
                                    "questoes_tentativas", "questoes_acertos")),
}

# Plataformas cujos contadores do snapshot NÃO são acumulados na prática: medido
# em produção (12/10), há 132 quedas de livros_unicos e 211 de tempo_leitura_min
# entre retratos seguidos da MESMA ficha do Elefante. Aí "maior ou igual" não
# prova nada (a mesma conta cai; outra conta pode começar acima). Só vale a
# IGUALDADE do limite: o primeiro retrato da posterior repete, contador a
# contador, o último da anterior — nos pares reais do Elefante, os quatro: 6 dos
# 8 pares de sombra medidos repetem exatamente; os 2 em que os contadores crescem
# no limite ficam, de propósito, para a revisão humana.
_SO_IGUALDADE_NO_LIMITE = frozenset({"elefante"})

# Maior intervalo (em dias) entre o último retrato da ficha anterior e o primeiro
# da posterior em que a continuidade ainda é aceita. Medido em 12/10: nos pares
# reais a sombra começa no dia seguinte ao último retrato da oficial; um mês sem
# coleta já não prova que a conta é a mesma.
INTERVALO_MAXIMO_DIAS = 31


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

def _sem_particulas(toks: list[str], particulas=PARTICULAS) -> tuple[str, ...]:
    """O nome sem as partículas, na mesma ordem: a escola digita o nome na
    plataforma com ou sem a partícula ("… SOARES SANTOS" × "… SOARES DOS
    SANTOS"), e ela não distingue criança nenhuma."""
    return tuple(t for t in toks if t not in particulas)


# As partículas que a IGUALDADE de nome ("identico") ignora: as de PARTICULAS
# menos o "E". Isolado no meio do nome, o "E" é ambíguo com uma INICIAL ("JULIETA
# E SAMPAIO" pode ser Julieta E[…] Sampaio), e ignorá-lo faria de "JULIETA
# SAMPAIO" (ou de "BENEDITA E" × "BENEDITA") o MESMO nome. A relação "forte"
# (``_Estado.forte``) segue ignorando o "E": lá ela só AMPLIA quem segura o par.
_PARTICULAS_DO_IDENTICO = frozenset(PARTICULAS) - {"e"}


def _forma_do_nome(ts: list[str], to: list[str]) -> str:
    """Como o nome da ficha fora da lista (``ts``) se relaciona com o da oficial
    (``to``), sabendo que os dois já são "forte" (``_Estado.forte``). Os tokens
    já vêm sem acento, sem caixa e sem o sufixo da turma (``_carregar``).
    Devolve ``"identico"``, ``"truncado"`` (a forma que o relatório produz) ou o
    MOTIVO da revisão.

    Idêntico é o mesmo nome na mesma ordem, partículas DE/DA/DO/DAS/DOS à parte
    (o "E" isolado não: ``_PARTICULAS_DO_IDENTICO``). A forma do relatório é
    posicional e estreita (``casa_abreviado_posicional``): prenome idêntico, os
    nomes do meio idênticos por posição e só a ÚLTIMA palavra reduzida a uma
    inicial. É o que o Matific escreve ("WENDY S", "HEITOR O"); prefixo de nome
    inteiro (GABRIEL → GABRIELA) e corte no meio (RICARD → RICARDO) não são. A
    partícula fica na forma do relatório: ele corta por posição, e a partícula
    ocupa a posição dela."""
    ss = _sem_particulas(ts, _PARTICULAS_DO_IDENTICO)
    if ts == to or (ss and ss == _sem_particulas(to, _PARTICULAS_DO_IDENTICO)):
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

@dataclass(frozen=True)
class _Retrato:
    """Um snapshot de plataforma reduzido ao que a continuidade compara: o DIA da
    coleta e os contadores acumulados (na ordem de ``_CONTADORES``)."""
    dia: date
    contadores: tuple[int, ...]


@dataclass(frozen=True)
class _Continuidade:
    """Veredito da continuidade de UMA plataforma entre duas fichas: ``motivo``
    None = é a mesma conta continuando (``evidencia`` diz como); senão, o motivo
    do CONFLITO."""
    motivo: str | None
    evidencia: dict = field(default_factory=dict)


@dataclass
class _Estado:
    escola_id: int
    ano: int
    alunos: dict[int, Aluno] = field(default_factory=dict)        # não excluídos
    # O nome que ENTRA nas comparações: sem o sufixo da turma da própria ficha
    # (``_nome_para_casar``). O nome gravado não muda.
    nomes: dict[int, str] = field(default_factory=dict)
    com_sufixo_da_turma: set[int] = field(default_factory=set)
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
    por_sem_particulas: dict[tuple, set[int]] = field(default_factory=dict)
    # Fichas da Lista Piloto ATIVAS por turma do ano ativo (as oficiais possíveis).
    oficiais_da_turma: dict[int, list[int]] = field(default_factory=dict)
    # Lidos sob demanda, só para os pares que chegam à continuidade (``_continuidade``).
    retratos: dict[tuple[int, str], list[_Retrato]] = field(default_factory=dict)
    leituras: dict[int, dict[int, tuple]] = field(default_factory=dict)
    eventos: dict[tuple[int, str], list[tuple[date, tuple]]] = field(default_factory=dict)

    def plataformas(self, aluno_id: int) -> set[str]:
        """Plataformas em que a ficha tem CONTA (efetiva ou aposentada)."""
        return set(self.contas.get(aluno_id, {}))

    def presenca(self, aluno_id: int) -> set[str]:
        """Plataformas em que a ficha tem conta OU dado."""
        return self.plataformas(aluno_id) | self.dados.get(aluno_id, set())

    def tem_efetiva(self, aluno_id: int, plataforma: str) -> bool:
        return any(st != "aposentada"
                   for _i, st in self.contas.get(aluno_id, {}).get(plataforma, ()))

    def forte(self, a: int, b: int) -> bool:
        """Os nomes das duas fichas (sem o sufixo da turma, sem acento nem caixa)
        são "forte" um com o outro: o MESMO ``matching.plausivel`` do motor — ou o
        mesmo nome, na mesma ordem, a menos das partículas. A segunda relação só
        AMPLIA quem conta como "forte": mais oficiais possíveis (gêmeos →
        revisão) e mais fichas que podem ser a dona (→ revisão)."""
        sa, sb = _sem_particulas(self.tokens.get(a) or []), _sem_particulas(
            self.tokens.get(b) or [])
        if sa and sa == sb:
            return True
        return matching.plausivel(self.nomes[a], self.nomes[b]) == "forte"

    def fortes_com(self, aluno_id: int) -> list[int]:
        """Fichas (não excluídas) cujo nome é "forte" com o desta (``forte``). O
        índice só PODA quem não teria como ser forte, sem mudar o veredito:
        "forte" é o mesmo conjunto de tokens (``por_tokens``), o mesmo nome sem
        as partículas (``por_sem_particulas``) ou uma abreviação POSICIONAL, em
        que o 1º token de um é o começo do 1º token do outro — a mesma letra
        inicial (``por_inicial``)."""
        toks = self.tokens.get(aluno_id) or []
        if not toks:
            return []
        cands = (self.por_inicial.get(toks[0][0], set())
                 | self.por_tokens.get(frozenset(toks), set())
                 | self.por_sem_particulas.get(_sem_particulas(toks), set()))
        return sorted(i for i in cands if i != aluno_id and self.forte(aluno_id, i))


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
    # O NOME que entra nas comparações: sem o sufixo da turma que o professor
    # digitou na plataforma ("… ROSA 2B") — o MESMO ``_nome_para_casar`` do motor,
    # contra a sala da ÚNICA turma da ficha no ano ativo (sufixo de outra sala, ou
    # ficha sem turma única, fica como está). Acento e caixa já saem em
    # ``tokens_nome``: "MAGALHaES" (a vogal acentuada que a plataforma perdeu) e
    # "MAGALHÃES" dão o mesmo token.
    nome_da_turma = dict(db.execute(select(Turma.id, Turma.nome)
                                    .where(Turma.escola_id == escola_id)).all())
    for aluno_id, aluno in est.alunos.items():
        turmas = list(dict.fromkeys(est.turmas_de.get(aluno_id, ())))
        sala = chave_sala(nome_da_turma.get(turmas[0], "")) if len(turmas) == 1 else ""
        nome = _nome_para_casar(aluno.nome, sala) if sala else aluno.nome
        if nome != aluno.nome:
            est.com_sufixo_da_turma.add(aluno_id)
        est.nomes[aluno_id] = nome
        toks = tokens_nome(nome)
        est.tokens[aluno_id] = toks
        if toks:
            est.por_inicial.setdefault(toks[0][0], set()).add(aluno_id)
            est.por_tokens.setdefault(frozenset(toks), set()).add(aluno_id)
            est.por_sem_particulas.setdefault(_sem_particulas(toks), set()).add(aluno_id)
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


# ---------------------------------------------------------------------------
# Continuidade da conta: a mesma conta passando de uma ficha para a outra
# ---------------------------------------------------------------------------

def _dia(valor) -> date:
    return valor.date() if isinstance(valor, datetime) else valor


def _retratos(db: Session, est: _Estado, aluno_id: int, plataforma: str) -> list[_Retrato]:
    """Os snapshots da ficha na plataforma, em ordem de coleta. TODOS os da ficha
    — os que a fusão moveria —, lidos uma vez por plano."""
    chave = (aluno_id, plataforma)
    if chave not in est.retratos:
        modelo, campos = _CONTADORES.get(plataforma, (None, ()))
        linhas = [] if modelo is None else db.execute(
            select(modelo.data_referencia, *(getattr(modelo, c) for c in campos))
            .where(modelo.aluno_id == aluno_id)
            .order_by(modelo.data_referencia, modelo.id)).all()
        est.retratos[chave] = [_Retrato(_dia(linha[0]), tuple(int(v or 0) for v in linha[1:]))
                               for linha in linhas]
    return est.retratos[chave]


def _ultimo_outro_dado(db: Session, aluno_id: int, plataforma: str) -> date | None:
    """O dia do dado MAIS RECENTE da ficha na plataforma fora dos snapshots: a
    leitura (Elefante) e o evento da linha do tempo — o resto do que a fusão
    move para a plataforma (a conta não tem data)."""
    datas = [db.execute(select(func.max(EventoAluno.ocorrido_em))
                        .where(EventoAluno.aluno_id == aluno_id,
                               EventoAluno.plataforma == plataforma)).scalar()]
    if plataforma == "elefante":
        datas.append(db.execute(select(func.max(Leitura.data))
                                .where(Leitura.aluno_id == aluno_id)).scalar())
    dias = [_dia(d) for d in datas if d is not None]
    return max(dias) if dias else None


def _leituras(db: Session, est: _Estado, aluno_id: int) -> dict[int, tuple]:
    """As leituras da ficha: livro → (data, tempo, nível), lidas uma vez por plano."""
    if aluno_id not in est.leituras:
        est.leituras[aluno_id] = {
            livro: (quando, tempo, nivel) for livro, quando, tempo, nivel in db.execute(
                select(Leitura.livro_id, Leitura.data, Leitura.tempo_leitura_min,
                       Leitura.nivel_codigo).where(Leitura.aluno_id == aluno_id)).all()}
    return est.leituras[aluno_id]


def _leituras_divergentes(db: Session, est: _Estado, a: int, b: int) -> bool:
    """As duas fichas leram o MESMO livro com data, tempo ou nível diferentes? A
    fusão guarda uma leitura por livro (§35) e descartaria a outra com a data e
    o tempo dela. A cópia idêntica da MESMA leitura (a plataforma mandou o
    histórico da conta de novo) não perde nada."""
    la, lb = _leituras(db, est, a), _leituras(db, est, b)
    return any(la[livro] != lb[livro] for livro in la.keys() & lb.keys())


def _identidade_do_evento(plataforma: str, tipo: str, titulo: str | None,
                          quando: datetime) -> tuple:
    """O evento SEM a ficha: os mesmos campos que ``eventos.chave_evento`` hasheia
    — plataforma, tipo, título normalizado e o MINUTO —, menos o aluno. A chave
    gravada leva o id da ficha, então o MESMO evento da plataforma (o histórico
    da conta reenviado para a sombra) tem chave diferente em cada ficha; esta
    identidade é igual nas duas. (O ``extra`` da chave não é usado por nenhum
    importador.)"""
    return (plataforma, tipo, (titulo or "").strip().casefold(),
            quando.strftime("%Y-%m-%dT%H:%M"))


def _eventos(db: Session, est: _Estado, aluno_id: int, plataforma: str
             ) -> list[tuple[date, tuple]]:
    """Os eventos da ficha na plataforma: (dia, identidade sem a ficha)."""
    chave = (aluno_id, plataforma)
    if chave not in est.eventos:
        est.eventos[chave] = [
            (_dia(quando), _identidade_do_evento(plataforma, tipo, titulo, quando))
            for tipo, titulo, quando in db.execute(
                select(EventoAluno.tipo_evento, EventoAluno.conteudo_titulo,
                       EventoAluno.ocorrido_em)
                .where(EventoAluno.aluno_id == aluno_id,
                       EventoAluno.plataforma == plataforma)).all()]
    return est.eventos[chave]


def _dado_proprio_da_posterior(db: Session, est: _Estado, ant: int, post: int,
                               plataforma: str, ate: date) -> bool:
    """(vi) A ficha POSTERIOR tem dado da plataforma de dia ANTERIOR a ``ate`` (o
    dia do último retrato da anterior) que a anterior NÃO tem?

    A mesma conta, quando passa para a outra ficha, reenvia o histórico dela: o
    Elefante busca a lista inteira de livros do studentId novo, e o que é de
    antes do limite chega como CÓPIA do que a anterior já tinha (o evento com o
    mesmo título no mesmo minuto; a leitura do mesmo livro — data, tempo e
    nível iguais são conferidos por ``_leituras_divergentes``). Um livro ou um
    evento que a anterior não tem, datado enquanto ela ainda recebia retratos,
    é de OUTRA conta ativa no mesmo período: se fosse a mesma, o retrato da
    anterior já o contaria.

    O dia do último retrato fica de fora (``<``, não ``<=``): o retrato é datado
    pela hora da coleta (a agenda roda às 00:10), e o que a criança faz naquele
    dia, depois da coleta, só aparece na ficha seguinte — no Matific, é o que
    faz o contador crescer no limite. (No Elefante o limite tem de REPETIR os
    contadores, ``_SO_IGUALDADE_NO_LIMITE``: o par medido em que eles cresciam,
    129 → 135 livros, vai para a revisão humana por (iii), não por aqui.)
    ``<=`` não protegeria mais: a conta de outra criança que começa naquele dia
    é a mesma que começa no dia seguinte, e esta só é barrada pelos contadores
    (o risco de ``test_falsificacao_de_continuidade``)."""
    da_anterior = {ident for _dia_ev, ident in _eventos(db, est, ant, plataforma)}
    if any(dia < ate and ident not in da_anterior
           for dia, ident in _eventos(db, est, post, plataforma)):
        return True
    if plataforma != "elefante":
        return False
    livros_da_anterior = _leituras(db, est, ant)
    return any(_dia(quando) < ate and livro not in livros_da_anterior
               for livro, (quando, _tempo, _nivel) in _leituras(db, est, post).items())


def _continuidade(db: Session, est: _Estado, a: int, b: int, plataforma: str,
                  papeis: dict[int, str], *, anterior_exigida: int | None = None
                  ) -> _Continuidade:
    """Os dados de ``plataforma`` nas fichas ``a`` e ``b`` são a MESMA conta
    continuando de uma ficha para a outra — e não duas contas (ou duas
    crianças)? Quem chama já excluiu as duas com conta própria nela.

    O padrão real (12/10): a oficial tem o Matific ligado por NOME até 31/07; em
    01/08 a sincronização passou a receber a conta e criou a sombra, que segue
    dali. Os dois retratos do limite têm os MESMOS contadores do ano (no
    Matific, acumulados, também maiores do lado da sombra; no Elefante, só os
    mesmos): é a mesma conta, só que dividida em duas fichas. Duas contas
    reais, ao contrário, recebem dado no MESMO período, ou a segunda começa do
    zero.

    Aceita SOMENTE com tudo isto (cada falha tem o seu motivo):
      (i) as duas fichas têm snapshot da plataforma — leitura ou evento soltos
          não têm contador com que provar (``continuidade_sem_retrato``);
      (ii) os retratos não se sobrepõem: o último da ficha ANTERIOR (a que
          começou antes) é de dia estritamente anterior ao primeiro da
          POSTERIOR (``dados_simultaneos_mesma_plataforma``);
      (ii') se ``anterior_exigida`` foi dado, a anterior é ela
          (``ordem_invertida``): a oficial antes da sombra; a ficha sem a conta
          antes da que tem a conta;
      (iii) a anterior tem algum contador acima de zero (``contadores_zerados``)
          e, no limite, CADA contador da posterior é >= o MAIOR valor dele em
          todos os retratos da anterior (``contador_regrediu``). Zero não prova
          nada — a conta nova de qualquer criança começa ali —, e o maior valor
          (não só o último) impede que um último retrato que caiu abra a porta
          para uma conta que começa baixo. Nas plataformas de
          ``_SO_IGUALDADE_NO_LIMITE`` (Elefante, cujos contadores caem dentro da
          mesma conta) vale só a IGUALDADE: o ÚLTIMO retrato da anterior tem
          algum contador acima de zero (``contadores_zerados``) e o 1º retrato
          da posterior o repete em todos os contadores
          (``contadores_diferentes_no_limite``) — o máximo da anterior não
          entra: a queda DENTRO dela é a mesma conta, não prova nada;
      (iv) no máximo ``INTERVALO_MAXIMO_DIAS`` entre os dois (``intervalo_longo``);
      (v) a anterior não tem outro dado da plataforma (leitura, evento) do dia
          do primeiro retrato da posterior em diante
          (``dados_simultaneos_mesma_plataforma``);
      (vi) a posterior não tem dado da plataforma de antes do dia do último
          retrato da anterior que a anterior não tenha
          (``_dado_proprio_da_posterior``; ``dados_simultaneos_mesma_plataforma``);
      e, no Elefante, nenhum livro lido nas duas com data/tempo diferentes
      (``leitura_repetida_nas_duas_fichas``: a fusão descartaria uma leitura).
    Tudo em DIA de calendário: dois retratos do mesmo dia em fichas diferentes
    já são simultâneos. ``papeis`` só rotula a evidência ("oficial", "sombra")."""
    ra, rb = _retratos(db, est, a, plataforma), _retratos(db, est, b, plataforma)
    if not ra or not rb:
        return _Continuidade("continuidade_sem_retrato")
    (ant, r_ant), (post, r_post) = sorted(((a, ra), (b, rb)),
                                          key=lambda par: (par[1][0].dia, par[0]))
    ultimo, primeiro = r_ant[-1], r_post[0]
    if ultimo.dia >= primeiro.dia:
        return _Continuidade("dados_simultaneos_mesma_plataforma")
    if anterior_exigida is not None and ant != anterior_exigida:
        return _Continuidade("ordem_invertida")
    dias = (primeiro.dia - ultimo.dia).days
    if dias > INTERVALO_MAXIMO_DIAS:
        return _Continuidade("intervalo_longo")
    if plataforma in _SO_IGUALDADE_NO_LIMITE:
        # Contador que cai dentro da mesma conta: comparar com o máximo barraria
        # a conta legítima e "crescer" não provaria nada — só a repetição exata
        # do último retrato da anterior (com algo acima de zero) prova. A
        # referência é o último (não o máximo): a evidência sai sempre
        # "iguais", sem ``maximos_anterior``.
        maximos = ultimo.contadores
        if not any(ultimo.contadores):
            return _Continuidade("contadores_zerados")
        if primeiro.contadores != ultimo.contadores:
            return _Continuidade("contadores_diferentes_no_limite")
    else:
        maximos = tuple(max(valores) for valores in zip(*(r.contadores for r in r_ant)))
        if not any(maximos):
            return _Continuidade("contadores_zerados")
        if any(p < m for m, p in zip(maximos, primeiro.contadores)):
            return _Continuidade("contador_regrediu")
    outro = _ultimo_outro_dado(db, ant, plataforma)
    if outro is not None and outro >= primeiro.dia:
        return _Continuidade("dados_simultaneos_mesma_plataforma")
    if _dado_proprio_da_posterior(db, est, ant, post, plataforma, ultimo.dia):
        return _Continuidade("dados_simultaneos_mesma_plataforma")
    if plataforma == "elefante" and _leituras_divergentes(db, est, a, b):
        return _Continuidade("leitura_repetida_nas_duas_fichas")
    campos = _CONTADORES[plataforma][1]
    evidencia = {
        "ficha_anterior": papeis.get(ant, str(ant)),
        "ultimo_retrato_anterior": ultimo.dia.isoformat(),
        "primeiro_retrato_posterior": primeiro.dia.isoformat(),
        "dias_entre": dias,
        # "iguais" só quando o 1º retrato da posterior repete o último (que é
        # também o maior) da anterior; 0 → 0 em TODOS nunca chega aqui. No
        # Elefante (``_SO_IGUALDADE_NO_LIMITE``) só "iguais" chega aqui.
        "contadores": ("iguais" if primeiro.contadores == ultimo.contadores == maximos
                       else "crescentes"),
        "contadores_anterior": dict(zip(campos, ultimo.contadores)),
        "contadores_posterior": dict(zip(campos, primeiro.contadores)),
    }
    if maximos != ultimo.contadores:
        # O último retrato da anterior não era o maior (um contador caiu dentro
        # dela): a auditoria mostra contra o que a posterior foi comparada.
        evidencia["maximos_anterior"] = dict(zip(campos, maximos))
    return _Continuidade(None, evidencia)


def _assinatura(est: _Estado, s: Aluno, o: Aluno, turma_id: int) -> tuple:
    """O que precisa continuar IGUAL para o par ainda ser o par do plano. A
    presença de DADO nas plataformas não entra: a fusão da primeira sombra leva
    dado para a oficial e não pode pular a segunda — o choque de plataforma e a
    continuidade da conta são reavaliados pela própria classificação
    (``_classificar`` (d)), contra o banco atual."""
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
        and est.forte(i, o.id))


def _conflito_de_plataformas(db: Session, est: _Estado, sid: int, oid: int,
                             irmas: tuple[int, ...]) -> tuple[Item | None, dict, list]:
    """(d) As plataformas que a sombra DIVIDE com a oficial e com as outras
    sombras da mesma oficial. Devolve o CONFLITO (ou None) e, se não houver, a
    continuidade provada com a oficial (por plataforma) e com as irmãs.

    Com a oficial: conta própria dela na plataforma → duas contas reais; sem
    conta, só passa a MESMA conta continuando (``_continuidade``) DA OFICIAL
    PARA A SOMBRA — a ordem medida nos pares reais. Entre duas sombras: as duas
    com conta na plataforma → duas contas; só uma com conta → ela tem de ser a
    posterior (a por nome antes, a conta depois); sem conta, a continuidade vale
    nos dois sentidos, mas no MESMO sentido em todas as plataformas que elas
    dividem — senão nenhuma ordem de fusão junta as duas na oficial
    (``ordem_cruzada_entre_sombras``)."""
    pres_s, contas_s = est.presenca(sid), est.plataformas(sid)
    com_oficial: dict[str, dict] = {}
    for p in sorted(pres_s & est.presenca(oid)):
        if p in est.plataformas(oid):
            return (Item(sid, CONFLITO, "duas_contas_mesma_plataforma"), {}, [])
        c = _continuidade(db, est, oid, sid, p, {oid: "oficial", sid: "sombra"},
                          anterior_exigida=oid)
        if c.motivo:
            return Item(sid, CONFLITO, c.motivo), {}, []
        com_oficial[p] = c.evidencia
    falhas: list[tuple[int, str]] = []
    com_irmas: list[dict] = []
    for i in irmas:
        sentidos: set[str] = set()
        for p in sorted(est.presenca(i) & pres_s):
            conta_i, conta_s = p in est.plataformas(i), p in contas_s
            if conta_i and conta_s:
                falhas.append((i, "duas_contas_mesma_plataforma"))
                break
            # A ficha SEM a conta vem antes (como a oficial por nome antes da
            # conta na sombra); sem conta nas duas, qualquer sentido.
            exigida = sid if conta_i else i if conta_s else None
            c = _continuidade(db, est, i, sid, p, {i: "outra_sombra", sid: "sombra"},
                              anterior_exigida=exigida)
            if c.motivo:
                falhas.append((i, c.motivo))
                break
            sentidos.add(c.evidencia["ficha_anterior"])
            com_irmas.append({"sombra_id": i, "plataforma": p, **c.evidencia})
        else:
            if len(sentidos) > 1:
                falhas.append((i, "ordem_cruzada_entre_sombras"))
    if falhas:
        return (Item(sid, CONFLITO, falhas[0][1], relacionados=tuple(i for i, _m in falhas)),
                {}, [])
    return None, com_oficial, com_irmas


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
            if matching.plausivel(est.nomes[sid], est.nomes[i]) in ("parcial", "fraco")
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
    if any(len(lst) > 1 for lst in contas_s.values()):
        return Item(sid, CONFLITO, "duas_contas_mesma_plataforma", **par)
    conflito, continuidade, entre_sombras = _conflito_de_plataformas(
        db, est, sid, oid, irmas)
    if conflito is not None:
        return replace(conflito, **par)
    if any(st == "aposentada" for lst in contas_s.values() for _i, st in lst):
        # Aposentar uma conta é decisão de gente sobre ESTA ficha: ela já não é
        # uma sombra anônima (o mesmo critério de ``_oficial_entre_duplicatas``).
        return Item(sid, REVISAR, "conta_aposentada_na_sombra", **par)
    forma = _forma_do_nome(ts, est.tokens[oid])                    # (b2)
    if forma not in ("identico", "truncado"):
        return Item(sid, REVISAR, forma, **par)
    # (e) Nome idêntico com conta ou dado: só é a sombra se, em CADA plataforma
    # dela, a oficial tinha o dado ANTES e a sombra é a continuação (d). Sem
    # esse dado anterior da oficial, pode ser outra criança de mesmo nome.
    if forma == "identico" and any(
            continuidade.get(p, {}).get("ficha_anterior") != "oficial" for p in pres_s):
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
    # A forma do nome que precisou ser normalizada para o par casar (só rótulos).
    nome_normalizado = []
    if sid in est.com_sufixo_da_turma:
        nome_normalizado.append("sufixo_da_turma")
    if forma == "identico" and ts != est.tokens[oid]:
        nome_normalizado.append("particulas")
    evidencias = {
        "regra": REGRA,
        "relacao_nome": "nome_identico" if forma == "identico" else "abreviacao",
        "nome_normalizado": nome_normalizado,
        "turma_id": turma,
        "plataformas_da_sombra": sorted(pres_s),
        "identificadores_divergentes": False,
        "outras_compativeis_com_conta_propria": com_conta_propria,
        "outras_sombras_da_mesma_oficial": list(irmas),
        # A MESMA conta continuando, por plataforma dividida com a oficial — e
        # com as outras sombras dela: só dias e contadores, nenhum nome.
        "continuidade": continuidade,
        "continuidade_entre_sombras": entre_sombras,
    }
    return Item(sid, CONSOLIDAR, "", relacionados=irmas, evidencias=evidencias,
                assinatura=_assinatura(est, s, o, turma), **par)


def _travas_do_grupo(itens: dict[int, Item]) -> None:
    """Irmã que não vai para a MESMA oficial: se ela pode ser outra criança, a
    sombra também pode ser dela → revisão (no lugar). Repete até estabilizar:
    rebaixar uma sombra pode rebaixar a irmã dela. (Duas sombras da mesma
    oficial na mesma plataforma, sem continuidade da conta entre elas, já saem
    CONFLITO em ``_classificar``.)"""
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


def _ordem_de_fusao(itens: list[Item]) -> list[Item]:
    """Os pares CONSOLIDAR na ordem em que podem ser fundidos: dentro de cada
    oficial, a sombra ANTERIOR na continuidade entre sombras antes da
    posterior; o resto pela ordem dos ids.

    A ordem importa. Se a sombra com a CONTA fosse fundida antes da sombra que
    tem o mesmo dado POR NOME (a anterior), a oficial passaria a ter a conta e a
    segunda viraria "duas contas" — pulada no compare-and-set e presa nesse
    CONFLITO em toda execução seguinte. Fundindo a anterior primeiro, a oficial
    recebe o dado por nome e a posterior continua dela, como no plano. As
    evidências do plano dizem quem vem antes (``continuidade_entre_sombras``);
    o sentido cruzado já é CONFLITO, então não há ciclo — se houvesse, o resto
    seguiria pelos ids e o compare-and-set pularia o que não coubesse."""
    por_id = {i.sombra_id: i for i in itens}
    depois_de: dict[int, set[int]] = {sid: set() for sid in por_id}
    for item in itens:
        for ev in item.evidencias.get("continuidade_entre_sombras", ()):
            outra = ev.get("sombra_id")
            if outra not in por_id:
                continue
            if ev.get("ficha_anterior") == "outra_sombra":
                depois_de[item.sombra_id].add(outra)
            else:
                depois_de[outra].add(item.sombra_id)
    ordem: list[Item] = []
    feitos: set[int] = set()
    while len(ordem) < len(por_id):
        pendentes = [sid for sid in sorted(por_id) if sid not in feitos]
        sid = next((s for s in pendentes if depois_de[s] <= feitos), pendentes[0])
        ordem.append(por_id[sid])
        feitos.add(sid)
    return ordem


def _alinhar_eventos(db: Session, oficial_id: int, sombra_id: int) -> dict[str, list[int]]:
    """Prepara os eventos da sombra para a fusão — o que ``fundir_par`` sozinho
    não resolve, porque a ``chave_natural`` do evento leva o id da FICHA
    (``eventos.chave_evento``) e a fusão só descarta chave IGUAL:

      * o MESMO evento nas duas fichas (o histórico da conta que o Elefante
        reenviou para a sombra) tem chaves diferentes, e a fusão o deixaria em
        DOBRO na oficial — a linha do tempo e o ``eventos_leitura`` do
        Relatório por Período contariam a leitura duas vezes. Aqui a cópia da
        sombra é DESCARTADA pela identidade do evento sem a ficha
        (``_identidade_do_evento``), a mesma que o planejador exige em (vi);
      * o evento que só a sombra tem iria para a oficial com a chave da
        SOMBRA, e a próxima coleta da conta (agora da oficial, com a chave da
        oficial) o gravaria de novo. Aqui a chave é RECALCULADA para a oficial
        — só quando a gravada é exatamente a que o importador gera para a
        sombra (origem conhecida); a de outra origem (uma fusão anterior) fica.

    Devolve os ids descartados e os rechaveados, para a auditoria: a origem de
    cada evento rechaveado continua provável pelo log (o id da sombra está lá,
    e a chave antiga se recalcula dos campos do evento). Nenhuma leitura de
    data divergente chega aqui — é CONFLITO no plano —, então a restauração de
    leitura por evidência (``leituras_restauracao``) não perde o que provar."""
    da_oficial = {
        _identidade_do_evento(p, tipo, titulo, quando)
        for p, tipo, titulo, quando in db.execute(
            select(EventoAluno.plataforma, EventoAluno.tipo_evento,
                   EventoAluno.conteudo_titulo, EventoAluno.ocorrido_em)
            .where(EventoAluno.aluno_id == oficial_id)).all()}
    descartados: list[int] = []
    rechaveados: list[int] = []
    for ev in db.execute(select(EventoAluno).where(EventoAluno.aluno_id == sombra_id)
                         .order_by(EventoAluno.id)).scalars().all():
        evento_id = ev.id
        if _identidade_do_evento(ev.plataforma, ev.tipo_evento, ev.conteudo_titulo,
                                 ev.ocorrido_em) in da_oficial:
            db.delete(ev)
            descartados.append(evento_id)
            continue
        titulo = ev.conteudo_titulo or ""
        if ev.chave_natural == chave_evento(ev.plataforma, ev.tipo_evento, sombra_id,
                                            titulo, ev.ocorrido_em):
            ev.chave_natural = chave_evento(ev.plataforma, ev.tipo_evento, oficial_id,
                                            titulo, ev.ocorrido_em)
            rechaveados.append(evento_id)
    db.flush()
    return {"descartados": descartados, "rechaveados": rechaveados}


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
    com a foto pré-fusão e a ORIGEM automática), depois de alinhar os eventos
    da sombra com os da oficial (``_alinhar_eventos``: a cópia sai, a chave do
    resto passa a ser a da oficial), mais a auditoria
    ``aluno.consolidado_automatico`` com as evidências e os ids das linhas
    movidas/descartadas. Os pares vão na ordem da continuidade entre sombras
    (``_ordem_de_fusao``). ``usuario_id`` é quem pediu de verdade (None no
    agendador e no script): nenhuma pessoa vira autora de uma fusão que não fez.

    UMA transação: fusões, auditoria e o recálculo da escola (só se fundiu)
    caem juntos num único commit; qualquer falha propaga e quem chamou desfaz
    tudo (rollback). O cache do painel é invalidado depois do commit."""
    from app.core.database import bloquear_escola_para_importacao
    escola_id = plano.escola_id
    bloquear_escola_para_importacao(db, escola_id)
    consolidados: list[dict] = []
    pulados: list[dict] = []
    for item in _ordem_de_fusao(plano.consolidar):
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
        eventos = _alinhar_eventos(db, item.oficial_id, item.sombra_id)
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
            # O mesmo evento da plataforma que a oficial já tinha (descartado) e
            # o que mudou para a chave da oficial (``_alinhar_eventos``).
            "eventos_copia_descartados": eventos["descartados"],
            "eventos_rechaveados": eventos["rechaveados"],
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
