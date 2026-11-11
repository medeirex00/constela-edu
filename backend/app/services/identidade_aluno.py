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

Duas travas antes do nome (``decidir``):
  * NOME INCOMPLETO (Matific sem o nome cheio — só o abreviado do Placar,
    "ANNA E", porque o uuid não veio no student-leaderboard ou a competição veio
    vazia): a linha só vale pela conta já vinculada, pelo RA ou por uma decisão
    humana anterior; pelo nome abreviado ela NUNCA associa nem cria — vai para a
    revisão ``nome_incompleto``;
  * ID EXTERNO REPETIDO no mesmo relatório sem que a conta prove de quem é
    cada linha — nomes diferentes, ou números diferentes na linha de retrato
    (``marcar_ids_em_conflito``) —, ou com disputa ainda aberta na fila: nenhuma
    linha dessa conta aplica número em ficha nenhuma — revisão
    ``id_externo_duplicado``, uma pendência por nome.

E uma depois do nome (``marcar_fichas_disputadas``): DUAS CONTAS AINDA SEM
VÍNCULO, no mesmo relatório, que levariam à MESMA ficha (ou criariam a mesma
ficha nova) não decidem pela ordem do arquivo — nenhuma leva a ficha, as duas vão
para a revisão.

TURMA E ANO LETIVO (onde a ficha nova pode nascer — ``_turma_para_criar``):
  * só turmas do ANO LETIVO ATIVO da escola entram no contexto (as matrículas
    também: ``carregar_contexto``); turma escolhida de outro ano não serve de
    destino (revisão ``turma_fora_do_ano_letivo``);
  * turma ARQUIVADA nunca recebe ficha nem matrícula nova (revisão
    ``turma_arquivada``) — mas a criança que JÁ está nela continua recebendo os
    dados da plataforma na própria ficha (associar não mexe em matrícula);
  * o reconhecimento da sala pela série (``Contexto.sala_efetiva``) compara
    também a ETAPA: rótulo de ANO nunca vira turma de FASE (Educação Infantil),
    nem o contrário — e a turma de destino, da sala ou escolhida, também é
    conferida contra a etapa da turma do relatório (revisão
    ``turma_de_outra_etapa``), já na prévia.

Nunca escolhe "o primeiro" candidato, nunca funde fichas (fusão é ação
administrativa explícita) e nunca cria ficha nova quando a identidade externa
pertence a uma ficha existente — nem se ela estiver inativa. Ficha EXCLUÍDA não
é reutilizada: não é candidata e não segura identidade externa. Ficha
TRANSFERIDA (ou arquivada, fora da Lista Piloto) não é reativada por aqui:
qualquer caminho que chegue a ela vira revisão (``STATUS_INATIVOS``).

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
from app.services.importacao import chave_nome, nome_abreviado, tokens_nome
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
        "nenhum aluno corresponde e a política desta escola não deixa a plataforma "
        "criar ficha — nem pela sincronização nem pela importação de relatório (a "
        "matrícula vem da Lista Piloto)",
    "nome_incompleto":
        "a plataforma mandou só o nome abreviado (ou de uma palavra só), sem o nome "
        "completo, e nada já vinculado (conta da plataforma, RA) diz quem é a "
        "criança — esse nome não basta para associar nem para criar ficha",
    "contas_repetidas_no_relatorio":
        "duas contas diferentes da plataforma vieram no mesmo relatório com o mesmo "
        "nome, e nenhuma ficha corresponde — podem ser a mesma criança (conta "
        "duplicada) ou duas crianças; nada foi criado",
    "id_externo_duplicado":
        "o mesmo identificador da plataforma veio em mais de uma linha do "
        "relatório, com nomes ou números diferentes (ou já há uma pendência assim "
        "aberta para ele) — não dá para saber de qual criança são os números",
    "turma_arquivada":
        "a turma do relatório está arquivada no cadastro: ficha e matrícula nova "
        "não nascem em turma arquivada (reative a turma em Turmas, se ela deve "
        "receber alunos)",
    "turma_fora_do_ano_letivo":
        "a turma escolhida não é do ano letivo ativo da escola",
    "turma_de_outra_etapa":
        "a turma onde a ficha nova nasceria (a da sala do relatório, ou a escolhida) "
        "é de outra etapa que a turma do relatório (ex.: Educação Infantil x "
        "Fundamental): ficha e matrícula nova não nascem nela. Escolha uma turma da "
        "mesma etapa (se ela ainda não existe, cadastre-a com um nome que diga a "
        "etapa, como “1º Ano A”: o nome curto “1ºA” pode já ser o da turma da outra "
        "etapa)",
    # D11 (item E): orientação, sem fluxo novo — a confirmação manual não encerra
    # a pendência; quem decide é a Revisão de identidade (Admin Global, D10).
    "identidade_de_outra_escola":
        "a conta da plataforma já está vinculada a um aluno de OUTRA escola do "
        "Constela — nada foi aplicado aqui e a outra escola não foi alterada; "
        "confira se a credencial e a turma são desta escola antes de vincular. A "
        "confirmação é feita em Revisão de identidade, pelo Admin Global: escolher "
        "a ficha na importação manual não encerra esta pendência",
}

# D10: o aviso de quem (o Admin Global) faz uma conta EFETIVA em outra escola
# valer também aqui — no /resolver, na importação manual, na reativação e na
# restauração do backup. A outra
# escola não é alterada, mas a coleta seguinte dela manda a conta para a revisão.
# A coleta seguinte DESTA escola associa quando a decisão ficou na memória (o
# /resolver e a reativação de ficha ATIVA a gravam; a restauração não decide por
# ficha nenhuma e não grava).
# O texto diz só o que existe hoje: a conta deixa de valer numa escola quando a
# ficha dali é excluída ou quando a criança dali tem OUTRA conta efetiva e esta é
# aposentada. A conta única não pode ser aposentada (``identidade_efetiva.
# definir_efetiva`` recusa) e "Marcar como transferido" não a libera.
AVISO_CONTA_DE_OUTRA_ESCOLA = (
    "Atenção: esta conta da plataforma continua vinculada a um aluno de outra "
    "escola do Constela, que não foi alterada. Na próxima coleta daquela escola, "
    "a conta vai para a Revisão de identidade de lá (e a criança deixa de ser "
    "atualizada lá) até alguém decidir com as duas escolas. Hoje a conta só deixa "
    "de valer numa escola quando a ficha dela ali é excluída, ou quando a criança "
    "ali tem outra conta efetiva e esta é aposentada: marcar a ficha como "
    "transferida não libera a conta, e a conta única de uma criança não pode ser "
    "aposentada.")

# Motivos de revisão que dizem respeito à TURMA da linha, não à identidade — a
# auditoria os registra como "linha sem aluno vinculado" (``importacoes``).
MOTIVOS_DE_TURMA = frozenset({"sem_turma", "turma_nao_cadastrada", "turma_ambigua",
                              "turma_arquivada", "turma_fora_do_ano_letivo",
                              "turma_de_outra_etapa"})

# Motivos de IGNORAR que a ESCOLA já decidiu — a linha é descartada com o motivo
# próprio e não é pendência nem defeito: não entra em ``ignorados`` (a sync não
# desfaz o cursor de ninguém por ela), nem em 'sem_vinculo' (não vira
# "correspondência pendente" a cada coleta), nem conta como linha com defeito.
# Hoje: a conta da plataforma que a escola APOSENTOU (conta duplicada — achado 5
# da revisão e95, decisão D4).
MOTIVOS_DESCARTE_DECIDIDO = frozenset({"identidade_aposentada"})

# Vias de ASSOCIAR/REVISAR que NÃO dependem do nome recebido: a conta da
# plataforma já vinculada, o RA da escola e a decisão humana anterior. São as
# únicas que valem para a linha de NOME INCOMPLETO.
_VIAS_SEM_NOME = frozenset({"identidade", "ra", "revisao"})


def turma_ativa(turma) -> bool:
    """A turma recebe ficha/matrícula NOVA? Só a ativa (arquivar preserva o
    histórico sem receber ninguém)."""
    return getattr(turma, "status", "ativa") == "ativa"


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
    # A plataforma não entregou o nome COMPLETO, só o abreviado (Matific: o uuid
    # não veio no student-leaderboard). Marcado pelo analisador da API.
    nome_incompleto: bool = False
    # A turma que o RELATÓRIO informa, separada do DESTINO: com a turma escolhida
    # (``turma_id``), ``turma_nome`` é o nome dela, e a etapa do relatório se perdia
    # — a checagem de etapa comparava a turma escolhida com ela mesma. Vazio quando
    # o relatório não informa turma (aí não há etapa para comparar).
    turma_relatorio: str = ""


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
                   aluno_id: int | None = None,
                   turma_relatorio: str | None = None) -> LinhaIdentidade:
    """Monta a ``LinhaIdentidade`` a partir da linha importada — UM só lugar, usado
    pela prévia e pela confirmação (mesmos campos, mesma normalização).

    ``turma_relatorio``: a turma que o relatório informa. Sem ela (None), vale a
    própria ``turma_nome`` quando a linha não tem turma escolhida — na prévia são a
    mesma coisa; com a turma escolhida, quem chama informa a do relatório."""
    dados = dados or {}
    plat = plataforma_da_linha(dados, plataforma)
    if turma_relatorio is None:
        turma_relatorio = turma_nome if turma_id is None else ""
    return LinhaIdentidade(
        nome=nome or "", plataforma=plat, id_externo=id_externo_da_linha(plat, dados),
        turma_nome=(turma_nome or "").strip(), turma_id=turma_id,
        ra=str(dados.get("ra") or "").strip(), chamada=_chamada(dados),
        nascimento=_nascimento(dados), aluno_id=aluno_id,
        nome_incompleto=dados.get("nome_incompleto") is True,
        turma_relatorio=(turma_relatorio or "").strip())


def turma_de_outra_etapa(turma_relatorio: str, turma) -> bool:
    """A turma de DESTINO é de outra etapa que a turma do RELATÓRIO (Educação
    Infantil × Fundamental — ``matriculas.etapa_da_sala``)? A do relatório lida pelo
    nome; a de destino pelo nome e pelo ``ano_escolar``. Sem turma no relatório não
    há base: não é de outra etapa."""
    from app.services.matriculas import etapa_da_sala
    if not (turma_relatorio or "").strip() or turma is None:
        return False
    return (etapa_da_sala(turma_relatorio)
            != etapa_da_sala(turma.nome, getattr(turma, "ano_escolar", "") or ""))


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
    # Turmas ATIVAS por (ETAPA, SÉRIE) — (fundamental, 4) → [164]. Só para
    # reconhecer a sala do relatório numa escola que cadastrou a turma sem a
    # letra — ver ``sala_efetiva``. A ETAPA entra na chave porque a série sozinha
    # não separa "1ª Fase" (Educação Infantil) de "1º Ano": as duas valem 1.
    turmas_por_serie: dict[tuple[str, int], list[int]] = field(default_factory=dict)
    # As ARQUIVADAS, no mesmo formato: nunca viram a sala de ninguém, só servem
    # para dizer à revisão "a turma existe, mas está arquivada"
    # (``sala_arquivada``).
    turmas_arquivadas_por_serie: dict[tuple[str, int], list[int]] = field(
        default_factory=dict)
    # (plataforma, id_externo) que vieram repetidos DESTE relatório sem que a conta
    # prove de quem é cada linha — preenchido por ``marcar_ids_em_conflito``.
    ids_em_conflito: set[tuple[str, str]] = field(default_factory=set)
    # (plataforma, aluno_id) que mais de uma conta AINDA SEM VÍNCULO deste relatório
    # levaria — e (plataforma, nome, sala) da ficha NOVA que duas contas criariam.
    # Preenchidos por ``marcar_fichas_disputadas``: a primeira linha não leva nada.
    fichas_disputadas: set[tuple[str, int]] = field(default_factory=set)
    criacoes_disputadas: set[tuple[str, str, str]] = field(default_factory=set)
    # (plataforma, id_externo) com pendência "id_externo_duplicado" ainda aberta na
    # escola: a disputa já foi vista (noutro arquivo da mesma coleta — o histórico
    # de leituras vem depois do resumo — ou numa coleta anterior) e só um humano a
    # encerra. Até lá nenhuma linha dessa conta aplica número.
    ids_em_disputa: set[tuple[str, str]] = field(default_factory=set)
    # (plataforma, aluno_id) → contas com pendência "outra_identidade_na_plataforma"
    # ainda ABERTA que apontam esta ficha. É a disputa de ``marcar_fichas_disputadas``
    # (ou a de uma conta já vinculada) vista DEPOIS do relatório que a abriu: o
    # arquivo seguinte da mesma coleta (o histórico de leituras vem depois do resumo)
    # trazia só uma das contas, e ela levava a ficha — quem decidia era qual conta
    # aparecia no arquivo de leituras. Lido de ``carregar_contexto``; consultado por
    # ``contas_rivais`` (motor e triagem).
    contas_em_disputa: dict[tuple[str, int], set[str]] = field(default_factory=dict)
    # (plataforma, nome, sala) → contas com pendência "contas_repetidas_no_relatorio"
    # ainda ABERTA: as duas contas sem ficha que criariam a MESMA ficha nova. A mesma
    # trava de ``criacoes_disputadas``, para os arquivos seguintes.
    criacoes_em_disputa: dict[tuple[str, str, str], set[str]] = field(default_factory=dict)
    # (plataforma, id_externo) deste relatório que já são EFETIVOS em OUTRA escola
    # do Constela → id dessa escola. Preenchido por ``marcar_ids_de_outra_escola``
    # (com as linhas em mãos: o estado da rede inteira não é carregado).
    ids_de_outra_escola: dict[tuple[str, str], int] = field(default_factory=dict)
    # Quem confirma a importação pode fixar a ficha de uma conta EFETIVA em outra
    # escola (decisão D10: só o Admin Global). Falso por padrão: a escolha
    # explícita dessa conta vai para a revisão 'identidade_de_outra_escola'.
    confirma_conta_de_outra_escola: bool = False
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
        from app.services.matriculas import etapa_da_sala, serie_da_sala
        self.turmas[turma.id] = turma
        ids = self.turmas_da_sala.setdefault(chave_sala(turma.nome), [])
        if turma.id not in ids:
            ids.append(turma.id)
            ids.sort()
        # Índice por (etapa, série) — só quando o rótulo marca a série. As ATIVAS
        # num índice, as arquivadas noutro: uma turma arquivada não recebe aluno.
        ano_escolar = getattr(turma, "ano_escolar", "") or ""
        serie = serie_da_sala(turma.nome, ano_escolar)
        if serie is None:
            return
        indice = (self.turmas_por_serie if turma_ativa(turma)
                  else self.turmas_arquivadas_por_serie)
        da_serie = indice.setdefault((etapa_da_sala(turma.nome, ano_escolar), serie), [])
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
        identificador, candidato único), com a mesma proteção contra homônimo.

        A turma única é contada DENTRO DA ETAPA do relatório (``etapa_da_sala``):
        "1 ANO A TARDE ANUAL" só procura turmas do Fundamental, "1ª Fase" só as
        da Educação Infantil. Sem isso, com o "1º Ano" arquivado a única turma
        ativa da série 1 era a "1ª Fase" e a criança do 1º Ano caía na Fase; e,
        com as duas ativas, a série 1 parecia ter "duas turmas" e o 1º Ano inteiro
        ia para a revisão. Rótulo de Ano nunca vira turma de Fase, nem o
        contrário."""
        ids = self._da_serie(self.turmas_por_serie, chave, turma_nome)
        if len(ids) != 1:                      # nenhuma ou várias: não escolhe
            return chave
        if self._letras_se_contradizem(chave, ids[0]):
            return chave                       # letras declaradas e divergentes
        return chave_sala(self.turmas[ids[0]].nome)

    def sala_arquivada(self, chave: str, turma_nome: str = "") -> int | None:
        """A turma ARQUIVADA que seria a sala do relatório, quando a sala não tem
        turma ativa nenhuma: a da própria chave (todas arquivadas) ou, pelo mesmo
        critério de ``sala_efetiva`` (etapa + série, letras que não se
        contradizem), a ÚNICA arquivada da série quando a etapa não tem turma
        ativa. Só informa — nunca é destino de ficha nem de matrícula; serve para
        a revisão dizer "a turma existe, mas está arquivada" em vez de "não está
        cadastrada"."""
        if not chave:
            return None
        da_sala = self.turmas_da_sala.get(chave, [])
        if da_sala:
            if any(turma_ativa(self.turmas[i]) for i in da_sala):
                return None
            return da_sala[0]
        if self._da_serie(self.turmas_por_serie, chave, turma_nome):
            return None                        # há turma ativa da etapa/série
        ids = self._da_serie(self.turmas_arquivadas_por_serie, chave, turma_nome)
        if len(ids) != 1 or self._letras_se_contradizem(chave, ids[0]):
            return None
        return ids[0]

    def _da_serie(self, indice: dict, chave: str, turma_nome: str) -> list[int]:
        """Turmas do ``indice`` com a mesma (etapa, série) da sala do RELATÓRIO —
        só quando ela não é uma sala já cadastrada e o rótulo marca a série."""
        from app.services.matriculas import etapa_da_sala, serie_da_sala
        if not chave or chave in self.turmas_da_sala or not turma_nome:
            return []
        serie = serie_da_sala(turma_nome)
        if serie is None:
            return []
        return indice.get((etapa_da_sala(turma_nome), serie), [])

    def _letras_se_contradizem(self, chave: str, turma_id: int) -> bool:
        """O relatório e o cadastro declaram a LETRA da sala e elas divergem
        ("4 ANO B" × "4ºA")? Então são salas diferentes."""
        letra_relatorio = chave.partition("|")[2]
        letra_cadastro = chave_sala(self.turmas[turma_id].nome).partition("|")[2]
        return bool(letra_relatorio and letra_cadastro
                    and letra_relatorio != letra_cadastro)

    def _ainda_sem_dono(self, plataforma: str, contas, aluno_id: int | None,
                        id_externo: str) -> set[str]:
        """As ``contas`` (de pendências abertas) que ainda disputam: não são a da
        própria linha, não foram aposentadas e não estão vinculadas a OUTRA ficha
        (a vinculada a esta mesma ficha já é a trava de ``ids_do_aluno``)."""
        saida: set[str] = set()
        for conta in contas or ():
            if conta == id_externo or (plataforma, conta) in self.aposentadas:
                continue
            dono = self.identidade.get((plataforma, conta))
            if dono is None or dono == aluno_id:
                saida.add(conta)
        return saida

    def contas_rivais(self, plataforma: str, aluno_id: int, id_externo: str) -> set[str]:
        """OUTRAS contas desta plataforma, ainda sem vínculo, com pendência aberta de
        "duas contas para a mesma ficha" (``outra_identidade_na_plataforma``) que
        aponta ``aluno_id``. Enquanto um humano não decide, nenhuma delas leva a
        ficha sozinha — em nenhum arquivo."""
        return self._ainda_sem_dono(plataforma,
                                    self.contas_em_disputa.get((plataforma, aluno_id)),
                                    aluno_id, id_externo)

    def criacao_rival(self, plataforma: str, nome: str, sala: str, id_externo: str) -> bool:
        """Outra conta sem ficha, com pendência aberta ``contas_repetidas_no_relatorio``,
        criaria a MESMA ficha nova (mesmo nome, mesma sala)?"""
        return bool(self._ainda_sem_dono(
            plataforma, self.criacoes_em_disputa.get((plataforma, nome, sala)), None,
            id_externo))

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
    for (chave_ident, revisao_id, motivo, plataforma, id_externo, candidatos, nome,
         turma_informada) in db.execute(
            select(RevisaoIdentidade.chave_identidade, RevisaoIdentidade.id,
                   RevisaoIdentidade.motivo, RevisaoIdentidade.plataforma,
                   RevisaoIdentidade.id_externo, RevisaoIdentidade.candidatos,
                   RevisaoIdentidade.nome_recebido, RevisaoIdentidade.turma_informada)
            .where(RevisaoIdentidade.escola_id == escola_id,
                   RevisaoIdentidade.status == "pendente")
            .order_by(RevisaoIdentidade.id)).all():
        ctx.pendentes.setdefault(chave_ident, []).append(revisao_id)
        if motivo == "id_externo_duplicado" and id_externo:
            ctx.ids_em_disputa.add((plataforma, str(id_externo)))
        elif motivo == "outra_identidade_na_plataforma" and id_externo:
            for c in candidatos or ():
                if isinstance(c, dict) and c.get("aluno_id"):
                    ctx.contas_em_disputa.setdefault(
                        (plataforma, int(c["aluno_id"])), set()).add(str(id_externo))
        elif motivo == "contas_repetidas_no_relatorio" and id_externo:
            # A mesma chave (nome sem o sufixo de turma, sala reconhecida) que
            # ``decidir`` usa no passo 5 para a linha que traria esta conta.
            sala_rel = chave_sala(turma_informada or "")
            sala = ctx.sala_efetiva(sala_rel, turma_informada or "")
            ctx.criacoes_em_disputa.setdefault(
                (plataforma, chave_nome(_nome_para_casar(nome or "", sala, sala_rel)), sala),
                set()).add(str(id_externo))
    return ctx


# ---------------------------------------------------------------------------
# Chaves da fila de revisão
# ---------------------------------------------------------------------------

def chave_identidade_da_conta(plataforma: str, id_externo: str) -> str:
    """A chave da memória das decisões humanas para uma CONTA da plataforma — a
    mesma que ``chave_identidade`` dá à linha que traz essa conta. Usada por quem
    grava a decisão fora do ``/resolver`` (``identidade_efetiva``, D10)."""
    return f"{plataforma}|id:{id_externo}"


def chave_identidade(linha: LinhaIdentidade, chave: str) -> str:
    """Quem é esta linha, independentemente do arquivo: a identidade externa
    quando existe; senão nome + sala. É a memória das decisões humanas."""
    if linha.id_externo:
        return chave_identidade_da_conta(linha.plataforma, linha.id_externo)
    return f"{linha.plataforma}|nome:{chave_nome(linha.nome)}|sala:{chave}"


def _nome_comparavel(nome: str) -> str:
    """O nome para dizer "são nomes DIFERENTES?" entre linhas do mesmo id: a chave
    de sempre (``chave_nome``) sem os tokens com dígito — o sufixo de turma que o
    professor digita junto ("… 2B") não faz de ninguém outra criança."""
    return " ".join(t for t in tokens_nome(nome) if not any(c.isdigit() for c in t))


def _linha_por_livro(dados: dict) -> bool:
    """Linha do histórico de LEITURAS (uma por livro): o mesmo aluno aparece em
    várias, cada uma com o seu livro — repetir o id ali é o normal."""
    return "livro" in (dados or {})


def _assinatura_retrato(dados: dict) -> str:
    """Os NÚMEROS de uma linha de retrato (resumo do Elefante, Placar do Matific),
    sem a turma: duas linhas do mesmo id com a mesma assinatura são a mesma linha
    repetida; com assinaturas diferentes, ninguém sabe qual vale."""
    return json.dumps({k: v for k, v in (dados or {}).items() if k != "turma_relatorio"},
                      sort_keys=True, ensure_ascii=False, default=str)


def linhas_divergentes(linhas: list[dict]) -> bool:
    """Linhas de RETRATO (não de livro) com números diferentes entre si — o que uma
    pendência ``id_externo_duplicado`` pode guardar quando o mesmo id veio duas
    vezes com o mesmo nome. Aplicar uma delas seria escolher no escuro."""
    assinaturas = {_assinatura_retrato(d) for d in linhas or () if not _linha_por_livro(d)}
    return len(assinaturas) > 1


def marcar_ids_em_conflito(ctx: Contexto, linhas, plataforma: str | None = None
                           ) -> set[tuple[str, str]]:
    """Marca em ``ctx`` os ids externos REPETIDOS neste relatório de um jeito que a
    conta não prova de quem é cada linha — e devolve o conjunto:

      * o mesmo id com nomes DIFERENTES (``_nome_comparavel``); ou
      * o mesmo id em duas linhas de RETRATO (uma por aluno: resumo do Elefante,
        Placar do Matific) com números DIFERENTES — no Matific o nome cheio vem do
        próprio uuid, então duas contas que a plataforma colou no mesmo uuid
        chegam aqui com o mesmo nome e números diferentes.

    O mesmo id com o MESMO nome em várias linhas de LIVRO é normal (histórico de
    leituras do Elefante), e a mesma linha de retrato repetida idêntica também não
    é conflito. ``decidir`` manda as linhas em conflito para a revisão
    ``id_externo_duplicado`` em vez de gravar os números de uma na ficha da outra
    (o importador guarda só a ÚLTIMA linha de cada aluno). Chamado pela prévia e
    pela confirmação, com as MESMAS linhas — prévia = confirmação."""
    nomes: dict[tuple[str, str], set[str]] = {}
    retratos: dict[tuple[str, str], set[str]] = {}
    for linha in linhas or ():
        dados = getattr(linha, "dados", None) or {}
        plat = plataforma_da_linha(dados, plataforma)
        id_ext = id_externo_da_linha(plat, dados)
        nome = _nome_comparavel(getattr(linha, "nome", "") or "")
        if not (id_ext and nome):
            continue
        nomes.setdefault((plat, id_ext), set()).add(nome)
        if not _linha_por_livro(dados):
            retratos.setdefault((plat, id_ext), set()).add(_assinatura_retrato(dados))
    ctx.ids_em_conflito = (
        {chave for chave, vistos in nomes.items() if len(vistos) > 1}
        | {chave for chave, vistas in retratos.items() if len(vistas) > 1})
    return ctx.ids_em_conflito


def marcar_fichas_disputadas(ctx: Contexto, idents) -> set[tuple[str, int]]:
    """DUAS CONTAS SEM VÍNCULO NO MESMO RELATÓRIO PARA A MESMA FICHA.

    Duas contas da mesma plataforma, nenhuma ainda vinculada, chegam no mesmo
    relatório e as duas casariam com a mesma ficha (o caso típico: a conta que a
    criança usa e outra pouco usada, com o mesmo nome). Linha a linha, a PRIMEIRA
    do arquivo levava a ficha e gravava o retrato; só a segunda ia para a revisão
    — e quem vencia era a ordem do arquivo, não a criança. É a trava
    ``outra_identidade_na_plataforma`` que já vale para conta JÁ vinculada
    (``_para_aluno`` e o passo 1), antecipada para o primeiro vínculo.

    Roda ANTES das linhas, junto de ``marcar_ids_em_conflito``, com as MESMAS
    linhas na prévia e na confirmação: decide cada conta sem vínculo contra o
    estado de agora (``decidir`` só lê) e marca a ficha que duas ou mais contas
    levariam — ``decidir`` manda TODAS para a revisão. Vale também para a ficha
    NOVA: duas contas sem ficha, mesmo nome e mesma sala, não criam a ficha da
    primeira (revisão ``contas_repetidas_no_relatorio``).

    Conta já vinculada (ou aposentada) não entra: o vínculo dela decide, como
    sempre. A mesma conta em várias linhas (histórico de leituras) conta uma vez."""
    ctx.fichas_disputadas = set()
    ctx.criacoes_disputadas = set()
    por_ficha: dict[tuple[str, int], set[str]] = {}
    por_criacao: dict[tuple[str, str, str], set[str]] = {}
    vistas: set[LinhaIdentidade] = set()
    for linha in idents:
        if linha is None or not (linha.plataforma and linha.id_externo):
            continue
        conta = (linha.plataforma, linha.id_externo)
        if conta in ctx.identidade or conta in ctx.aposentadas or linha in vistas:
            continue
        vistas.add(linha)
        dec = decidir(ctx, linha)
        if dec.acao == ASSOCIAR and dec.aluno_id is not None:
            por_ficha.setdefault((linha.plataforma, dec.aluno_id), set()).add(linha.id_externo)
        elif dec.acao == CRIAR:
            nome = chave_nome(_nome_para_casar(linha.nome, dec.chave_sala,
                                               chave_sala(linha.turma_nome)))
            por_criacao.setdefault((linha.plataforma, nome, dec.chave_sala),
                                   set()).add(linha.id_externo)
    ctx.fichas_disputadas = {k for k, contas in por_ficha.items() if len(contas) > 1}
    ctx.criacoes_disputadas = {k for k, contas in por_criacao.items() if len(contas) > 1}
    return ctx.fichas_disputadas


def marcar_ids_de_outra_escola(db: Session, ctx: Contexto, linhas,
                               plataforma: str | None = None) -> dict[tuple[str, str], int]:
    """Marca em ``ctx`` os ids externos DESTE relatório que já são a identidade
    EFETIVA de um aluno de OUTRA escola do Constela (vínculo não aposentado, ficha
    não excluída) — e devolve o mapa ``(plataforma, id) → escola``.

    O vínculo é único por escola (``uq_identidade_externa``), então nada impedia a
    MESMA conta de alimentar duas escolas: com a credencial de outra escola (ou uma
    conta que enxerga duas), os números de uma criança de lá entravam numa ficha
    daqui. ``decidir`` manda essas linhas para a revisão
    ``identidade_de_outra_escola`` — nada aplicado aqui e nada mexido lá. Chamado
    pela prévia e pela confirmação, com as MESMAS linhas — prévia = confirmação.
    Uma consulta por plataforma (em lotes), só dos ids que vieram."""
    ctx.ids_de_outra_escola = {}
    for plat, ids in contas_das_linhas(linhas, plataforma).items():
        for id_ext, escola_id in efetivas_em_outra_escola(db, ctx.escola_id, plat, ids).items():
            ctx.ids_de_outra_escola.setdefault((plat, id_ext), escola_id)
    return ctx.ids_de_outra_escola


def contas_das_linhas(linhas, plataforma: str | None = None) -> dict[str, set[str]]:
    """``plataforma → ids externos`` das linhas que trazem a conta da plataforma
    (uuid do Matific, studentId do Elefante). Linha sem id fica de fora."""
    por_plataforma: dict[str, set[str]] = {}
    for linha in linhas or ():
        dados = getattr(linha, "dados", None) or {}
        plat = plataforma_da_linha(dados, plataforma)
        id_ext = id_externo_da_linha(plat, dados)
        if plat and id_ext:
            por_plataforma.setdefault(plat, set()).add(id_ext)
    return por_plataforma


def _identidades_efetivas(plataforma: str, ids_lote):
    """Consulta ``(id_externo, escola_id)`` das identidades EFETIVAS destes ids:
    vínculo não aposentado e ficha não excluída. Base única de
    ``efetivas_em_outra_escola`` e ``efetivas_na_escola`` (esta acrescenta, só do
    lado "desta escola", que a ficha não esteja inativa — ver lá).

    A ficha INATIVA (transferida, arquivada, fora da Lista Piloto) continua
    segurando a conta AQUI de propósito: é ela que faz a conta de uma criança
    marcada como transferida numa escola ir para a revisão
    ``identidade_de_outra_escola`` na outra, e é ela que o D10 protege. Não
    filtrar ``STATUS_INATIVOS`` nesta base."""
    return (select(IdentidadeExterna.id_externo, IdentidadeExterna.escola_id)
            .join(Aluno, Aluno.id == IdentidadeExterna.aluno_id)
            .where(IdentidadeExterna.plataforma == plataforma,
                   IdentidadeExterna.status != "aposentada",
                   Aluno.status != "excluido",
                   IdentidadeExterna.id_externo.in_(ids_lote)))


def efetivas_em_outra_escola(db: Session, escola_id: int, plataforma: str,
                             ids) -> dict[str, int]:
    """``id → escola``: os ids desta plataforma que já são a identidade EFETIVA de
    um aluno de OUTRA escola do Constela (vínculo não aposentado, ficha não
    excluída). Regra ÚNICA de "conta de outra escola": a revisão
    ``identidade_de_outra_escola`` (``marcar_ids_de_outra_escola``), a recusa da
    coleta em que todas as contas são de outra escola (``sync.service``, D8) e a
    confirmação só pelo Admin Global (D10) no ``/resolver``, na escolha explícita
    da ficha na importação manual (``decidir``, passo 0), na volta de uma conta
    aposentada (``identidade_efetiva.reativar``/``definir_efetiva``) e na volta
    de uma ficha EXCLUÍDA (``identidade_efetiva.trava_ficha_sai_de_excluido``,
    nas ações de status da gestão e na reativação pela Lista Piloto). Em lotes
    de 500."""
    saida: dict[str, int] = {}
    lista = sorted({str(i) for i in ids or () if i})
    for i in range(0, len(lista), 500):
        for id_ext, outra in db.execute(
                _identidades_efetivas(plataforma, lista[i:i + 500])
                .where(IdentidadeExterna.escola_id != escola_id)
                .order_by(IdentidadeExterna.id)).all():
            saida.setdefault(str(id_ext), int(outra))
    return saida


def efetivas_na_escola(db: Session, escola_id: int, plataforma: str, ids) -> set[str]:
    """Os ids desta plataforma que são a identidade EFETIVA de um aluno ATIVO
    DESTA escola. Serve só ao lado "desta escola" da recusa do D8
    (``sync.service._recusar_contas_de_outra_escola``): basta um id daqui para a
    coleta seguir como mista, então só conta a conta de uma criança que ESTÁ na
    escola. NÃO contam: a identidade aposentada (a conta duplicada que a escola
    descartou), a presa a uma ficha excluída e a presa a uma ficha INATIVA
    (``STATUS_INATIVOS``: transferida, arquivada, fora da Lista Piloto). Esta
    última é a criança que saiu desta escola: "Marcar como transferido" troca só o
    status da ficha e a conta continua efetiva (a conta única de uma criança não
    pode ser aposentada, ``identidade_efetiva.definir_efetiva``). Sem esse filtro,
    a conta dela salvava da recusa a coleta feita com a credencial da outra escola,
    e os nomes das crianças de lá iam para a fila de revisão daqui.

    Não é o espelho de ``efetivas_em_outra_escola``: lá a ficha inativa CONTINUA
    contando (``_identidades_efetivas``), porque é a conta da criança transferida
    numa escola que manda a mesma conta para a revisão ``identidade_de_outra_escola``
    na outra, e é ela que a trava do D10 protege. Em lotes de 500."""
    saida: set[str] = set()
    lista = sorted({str(i) for i in ids or () if i})
    for i in range(0, len(lista), 500):
        for id_ext, _escola in db.execute(
                _identidades_efetivas(plataforma, lista[i:i + 500])
                .where(IdentidadeExterna.escola_id == escola_id,
                       Aluno.status.notin_(STATUS_INATIVOS))).all():
            saida.add(str(id_ext))
    return saida


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
        # Também a OUTRA conta sem vínculo que, neste mesmo relatório, levaria esta
        # mesma ficha (``marcar_fichas_disputadas``): a ordem do arquivo não decide.
        # E a que disputa esta ficha numa pendência ainda aberta (``contas_rivais``):
        # o arquivo seguinte da coleta, com só uma das contas, também não decide.
        if (outras or (linha.plataforma, aluno.id) in ctx.fichas_disputadas
                or ctx.contas_rivais(linha.plataforma, aluno.id, linha.id_externo)):
            return Decisao(REVISAR, aluno.id, via, "outra_identidade_na_plataforma",
                           cands, chave_sala=chave)
    return Decisao(ASSOCIAR, aluno.id, via, candidatos=(aluno.id,), chave_sala=chave)


def _turma_para_criar(ctx: Contexto, linha: LinhaIdentidade, chave: str
                      ) -> tuple[int | None, str]:
    """Turma CADASTRADA onde a ficha nova nasce — determinística, nunca "a primeira":
    a escolhida explicitamente; senão a única turma da sala; havendo várias, a do
    código externo (SED/Censo) ou a de nome idêntico. Devolve (turma_id, motivo):
    motivo "turma_ambigua" quando não dá para decidir, "" quando decidiu ou quando
    a sala ainda não tem turma (o chamador cria, se o fluxo permitir).

    Só turma ATIVA do ANO LETIVO ATIVO é destino: a escolhida de outro ano (fora
    de ``ctx.turmas``) dá "turma_fora_do_ano_letivo"; a arquivada — escolhida, a
    única da sala ou a única da etapa/série (``Contexto.sala_arquivada``) — dá
    "turma_arquivada". Numa sala com uma arquivada e uma ativa, vale a ativa.

    Nem turma de OUTRA ETAPA que a turma do relatório (``turma_de_outra_etapa``):
    "1 ANO A" e a "1ºA" da Fase (o nome que ``nome_turma_exibicao`` dá a "Fase
    1A") têm a mesma sala 1|A, mas a ficha do 1º Ano não nasce na Educação
    Infantil, nem o contrário. Na sala, a de outra etapa não é candidata — com uma
    da etapa certa ao lado, vale ela; só com as de outra etapa, "turma_de_outra_etapa".
    A escolhida de outra etapa também. É a decisão da prévia e da confirmação (a
    rede de segurança de ``_resolver_aluno`` continua para a turma achada pelo nome
    na gravação)."""
    if linha.turma_id is not None:
        escolhida = ctx.turmas.get(linha.turma_id)
        if escolhida is None:
            return None, "turma_fora_do_ano_letivo"
        if not turma_ativa(escolhida):
            return None, "turma_arquivada"
        if turma_de_outra_etapa(linha.turma_relatorio, escolhida):
            return None, "turma_de_outra_etapa"
        return linha.turma_id, ""
    ativas = [i for i in ctx.turmas_da_sala.get(chave, []) if turma_ativa(ctx.turmas[i])]
    if not ativas:
        if ctx.sala_arquivada(chave, linha.turma_nome) is not None:
            return None, "turma_arquivada"
        return None, ""
    ids = [i for i in ativas if not turma_de_outra_etapa(linha.turma_relatorio, ctx.turmas[i])]
    if not ids:
        return None, "turma_de_outra_etapa"
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
    "… TRAVINI 4A"); esse sufixo não é nome de criança e, mantido, transformava o nome
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


# O mesmo sufixo no fim da palavra CRUA (com o ordinal que ``tokens_nome`` lê
# como letra: "3ºA", "3°A").
_SUFIXO_CRU = re.compile(r"\d{1,2}[ºª°]?[A-Za-z]$")


def nome_sem_sufixo_de_turma(nome: str, chave: str = "", chave_alt: str = "") -> str:
    """O nome que a ficha NOVA grava: o recebido, sem o sufixo de turma que
    ``_nome_para_casar`` tira do casamento — a MESMA regra (só sai o sufixo da
    sala da própria linha, como palavra solta ou grudado no último nome) —, mas
    com a grafia de quem digitou (caixa, acento). Antes o sufixo só saía do
    casamento e a ficha nascia "… LIMA 3A". Sem sufixo, ou se só sobraria o
    sufixo, devolve o nome como veio (só sem os espaços das pontas, como antes)."""
    partes = (nome or "").split()
    saida: list[str] = []
    mudou = False
    for parte in partes:
        toks = tokens_nome(parte)
        if len(toks) != 1:
            saida.append(parte)
            continue
        token = toks[0]
        if _SUFIXO_TURMA.fullmatch(token) and (_sufixo_da_sala(token, chave)
                                               or _sufixo_da_sala(token, chave_alt)):
            mudou = True
            continue
        colado = _SUFIXO_TURMA_COLADO.fullmatch(token)
        cru = _SUFIXO_CRU.search(parte)
        if (colado is not None and cru is not None
                and (_sufixo_da_sala(colado.group(2), chave)
                     or _sufixo_da_sala(colado.group(2), chave_alt))):
            saida.append(parte[:cru.start()])
            mudou = True
            continue
        saida.append(parte)
    if not mudou or not saida:
        return (nome or "").strip()          # o de sempre: nada muda sem sufixo
    return " ".join(saida)


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
         sobrenomes e se distinguem pelo PRENOME — ODETE ALICE × ODETE ALINE
         ALVETTI PERONI —, então uma letra diferente no prenome é revisão. Não
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
    "… ALVETTI DE PERONI", "… PERONI" ou como o stub "ODETE A", e a linha ia
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
    Lista Piloto "LEONORA VALERIA MORETES TESTA" e, na mesma sala, a ficha
    "LEONORA V" que a sincronização do Matific criou quando só recebia o nome
    abreviado. O Elefante manda o nome completo com um typo no meio ("MORETEZ"),
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
    fundido: a duplicata continua existindo, com a conta dela, até a fusão
    administrativa."""
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
    # NOME INCOMPLETO (Matific sem o nome cheio — só "ANNA E"): roda a decisão de
    # sempre e só aceita o que NÃO depende do nome — a conta já vinculada, o RA, a
    # decisão humana anterior para esta identidade, a conta aposentada. Qualquer
    # outro desfecho (associar por abreviação, criar a ficha "ANNA E", revisão por
    # nome) vira revisão "nome_incompleto", com os candidatos que o motor achou
    # para quem for decidir. Escolha explícita de um humano (``aluno_id``) segue o
    # caminho de sempre.
    if linha.nome_incompleto and linha.aluno_id is None:
        base = decidir(ctx, replace(linha, nome_incompleto=False))
        if base.acao == IGNORAR or base.via in _VIAS_SEM_NOME:
            return base
        return Decisao(REVISAR, base.aluno_id, base.via, "nome_incompleto",
                       base.candidatos, chave_sala=base.chave_sala)

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
            # D10 (risco V) também na importação manual: fixar a ficha de uma conta
            # que já é a identidade EFETIVA de um aluno de OUTRA escola criaria o
            # vínculo aqui e mandaria a criança de lá para a revisão na coleta
            # seguinte. Só o Admin Global decide (o router avisa e audita); a
            # gestão da escola vê a linha ir para a revisão própria, com a ficha
            # escolhida como sugestão — a mesma regra do /resolver.
            if ((linha.plataforma, linha.id_externo) in ctx.ids_de_outra_escola
                    and not ctx.confirma_conta_de_outra_escola):
                return Decisao(REVISAR, aluno.id, "explicito", "identidade_de_outra_escola",
                               (aluno.id,), chave_sala=chave)
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

    # 0c) ID EXTERNO DUPLICADO (neste relatório — ``marcar_ids_em_conflito`` — ou
    # numa disputa ainda aberta na fila): a conta não prova de quem é ESTA linha
    # (nem a ficha que já tem o vínculo é certamente a dona dos números dela).
    # Nenhuma das linhas associa nem cria — revisão, com a dona atual da conta (se
    # houver) como candidata.
    if linha.id_externo and (
            (linha.plataforma, linha.id_externo) in ctx.ids_em_conflito
            or (linha.plataforma, linha.id_externo) in ctx.ids_em_disputa):
        dono = ctx.ativo(ctx.identidade.get((linha.plataforma, linha.id_externo)))
        cands = (dono.id,) if dono is not None else ()
        return Decisao(REVISAR, dono.id if dono is not None else None, "identidade",
                       "id_externo_duplicado", cands, chave_sala=chave)

    # 0d) Conta já EFETIVA em OUTRA escola do Constela (``marcar_ids_de_outra_escola``):
    # credencial ou turma de outra escola, ou criança que mudou de escola. Nada é
    # aplicado aqui nem mexido lá — revisão, até um gestor DESTA escola confirmar
    # (uma vez) que a conta é de uma criança daqui; a confirmação fica na memória
    # das decisões e a próxima coleta associa pelo vínculo. Os candidatos que o
    # NOME acharia vão junto, só como sugestão para quem decide.
    if linha.id_externo and (linha.plataforma, linha.id_externo) in ctx.ids_de_outra_escola:
        dono = ctx.ativo(ctx.identidade.get((linha.plataforma, linha.id_externo)))
        if dono is None or not _confirmado_por_humano(ctx, linha, chave, dono.id, chave_alt):
            if dono is not None:
                cands = (dono.id,)
            else:
                pelo_nome = decidir(ctx, replace(linha, id_externo="", nome_incompleto=False))
                cands = pelo_nome.candidatos or (
                    (pelo_nome.aluno_id,) if pelo_nome.aluno_id is not None else ())
            return Decisao(REVISAR, cands[0] if cands else None, "identidade",
                           "identidade_de_outra_escola", tuple(cands), chave_sala=chave)

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
        # candidato único ("ROMUADO"/"ROMUALDO": 1º nome e último sobrenome idênticos)
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
    #
    # Antes, NOME ABREVIADO (``nome_abreviado``: "ZEFA Q", uma palavra só, inicial
    # solta) não vira ficha — venha de onde vier: Placar do Matific sem o
    # ``nome_abrev``, Elefante, planilha, PDF. Era assim que nasciam as fichas
    # "LORENA D" ao lado da oficial. Vai para a revisão ``nome_incompleto``, sem
    # candidato, e quem decide pode criar a ficha pela fila. Só a CRIAÇÃO é barrada:
    # associar por abreviação (passos 3 e 4) continua como sempre.
    if nome_abreviado(nome_casar):
        return Decisao(REVISAR, None, "novo", "nome_incompleto", (), chave_sala=chave,
                       vetados=vetados)
    # Duas contas sem vínculo, mesmo nome e mesma sala, no mesmo relatório: a ficha
    # não nasce com os números da primeira (``marcar_fichas_disputadas``). Nem no
    # arquivo seguinte, que traz só uma delas, enquanto a pendência da outra estiver
    # aberta (``criacao_rival``).
    if linha.id_externo and (
            (linha.plataforma, alvo_nome, chave) in ctx.criacoes_disputadas
            or ctx.criacao_rival(linha.plataforma, alvo_nome, chave, linha.id_externo)):
        return Decisao(REVISAR, None, "novo", "contas_repetidas_no_relatorio", (),
                       chave_sala=chave, vetados=vetados)
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
        if decisao.motivo == "id_externo_duplicado":
            # Uma pendência POR NOME: as linhas do mesmo id são, até prova em
            # contrário, crianças diferentes — juntá-las numa pendência só faria a
            # resolução aplicar os números de uma na ficha da outra.
            ident = f"{ident}|nome:{chave_nome(linha.nome)}"
        chave = chave_pendencia(ident, self.formato,
                                str(self.contexto.get("periodo_inicio") or ""),
                                str(self.contexto.get("periodo_fim") or ""))
        pend = self.pendencias.get(chave)
        if pend is None:
            turma_id = decisao.turma_id
            if turma_id is None:
                # A turma SUGERIDA para a ficha nova: só a única ATIVA da sala, da
                # etapa da turma do relatório — turma arquivada não recebe ficha nem
                # matrícula nova, e a de outra etapa é justamente a que foi recusada.
                ids = [i for i in ctx.turmas_da_sala.get(decisao.chave_sala, [])
                       if turma_ativa(ctx.turmas[i])
                       and not turma_de_outra_etapa(linha.turma_relatorio, ctx.turmas[i])]
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
