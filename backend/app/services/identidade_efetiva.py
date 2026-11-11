"""Conta duplicada na mesma plataforma: qual identidade vale para o aluno.

A criança tem DUAS contas na mesma plataforma — foi assim que os dados dela
passaram a se dividir entre duas fontes, e o retrato da ficha ficou mostrando o
de uma só. Quando a escola não tem acesso administrativo à plataforma, não dá
para apagar a duplicada lá; e apagá-la AQUI seria pior, porque se perderia a
prova de que aquele id externo era daquela criança.

Então o Constela guarda as duas e diz qual é a EFETIVA. A aposentada continua
existindo, com todo o histórico: só deixa de casar na importação (não chega
retrato NOVO dela) e de voltar a se associar sozinha.

O QUE APOSENTAR NÃO FAZ (ainda): tirar da ficha o que JÁ veio da conta
aposentada. Nem o retrato (``SnapshotMatific``/``SnapshotElefante``) nem a leitura
(``Leitura``) guardam de qual conta vieram, então:

* as leituras do Elefante trazidas por ela continuam contando (livros novos e
  tempo do período, bônus de leitura na escola);
* o retrato atual da ficha só muda quando entrar uma coleta da conta efetiva, e
  o ganho de um período que começa antes disso ainda pode comparar uma conta com
  a outra;
* no Matific, se a aposentada tinha números maiores, a trava contra queda da
  coleta automática (``orchestrator.reter_quedas_matific``) retém a coleta da
  efetiva enquanto ela ficar abaixo deles; a importação manual do relatório
  oficial não passa por essa trava.

Separar exige a coluna da conta no retrato e na leitura (migração: decisão do
dono, ALUNOS-4). Por isso a fusão de duas fichas com contas
diferentes da mesma plataforma é recusada (``alunos_fusao.contas_em_conflito``):
é ela que juntava as duas séries.

DISTINÇÃO QUE NÃO PODE SE PERDER: aposentar aqui NÃO desativa nada na
plataforma. A conta continua lá, e a próxima sincronização vai continuar trazendo
a linha dela — que o motor de identidade passa a IGNORAR, com aviso, em vez de
reabrir a mesma duplicidade a cada rodada.

Reversível de propósito: ``reativar`` devolve a identidade ao estado efetivo,
desde que isso não crie duas efetivas ao mesmo tempo.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Aluno, IdentidadeExterna, RevisaoIdentidade
from app.models.base import agora
from app.services import identidade_aluno as ida
from app.services.audit import registrar

EFETIVA = "efetiva"
APOSENTADA = "aposentada"

# D10 (risco V): fazer VALER de novo aqui uma conta que já é a identidade efetiva
# de um aluno de OUTRA escola do Constela é só do Admin Global (a rota traduz este
# código em 403) — a mesma regra do /resolver e da importação manual.
CODIGO_CONTA_DE_OUTRA_ESCOLA = "conta_de_outra_escola"
MENSAGEM_CONTA_DE_OUTRA_ESCOLA = (
    "Esta conta da plataforma já é a identidade de um aluno de OUTRA escola do "
    "Constela. Fazê-la valer de novo aqui faria a criança de lá deixar de ser "
    "atualizada (a conta cai em revisão na próxima coleta daquela escola): só o "
    "Admin Global decide, depois de conferir com as duas escolas.")


class ErroIdentidade(ValueError):
    """Falha de validação com um código estável para a rota traduzir."""

    def __init__(self, mensagem: str, *, codigo: str):
        super().__init__(mensagem)
        self.codigo = codigo


@dataclass(frozen=True)
class Resultado:
    aluno_id: int
    plataforma: str
    efetiva: str
    aposentadas: tuple[str, ...]
    revisoes_encerradas: tuple[int, ...]
    motivo: str
    avisos: tuple[str, ...] = ()

    def como_dict(self) -> dict:
        return {"aluno_id": self.aluno_id, "plataforma": self.plataforma,
                "identidade_efetiva": self.efetiva,
                "identidades_aposentadas": list(self.aposentadas),
                "revisoes_encerradas": list(self.revisoes_encerradas),
                "motivo": self.motivo, "avisos": list(self.avisos)}


def _trava_conta_de_outra_escola(db: Session, escola_id: int, plataforma: str,
                                 id_externo: str, admin_global: bool) -> int | None:
    """A conta APOSENTADA aqui vai voltar a ser efetiva. Se ela já é a identidade
    EFETIVA de um aluno de OUTRA escola (``identidade_aluno.efetivas_em_outra_escola``,
    a regra única do D10): para quem não é Admin Global, ``ErroIdentidade``
    ``conta_de_outra_escola`` (nada muda); para o Admin Global, devolve o id da
    outra escola (segue, com ``_registrar_conta_de_outra_escola``)."""
    outra = ida.efetivas_em_outra_escola(db, escola_id, plataforma,
                                         [id_externo]).get(id_externo)
    if outra is not None and not admin_global:
        raise ErroIdentidade(MENSAGEM_CONTA_DE_OUTRA_ESCOLA,
                             codigo=CODIGO_CONTA_DE_OUTRA_ESCOLA)
    return outra


ATIVO = "ativo"
# Origem da revisão que guarda uma decisão do Admin Global tomada FORA da fila de
# Revisões (``_gravar_memoria_da_decisao``). A tela a mostra entre as resolvidas.
ORIGEM_CONFIRMACAO_ADMIN = "confirmacao_admin"
MOTIVO_CONTA_DE_OUTRA_ESCOLA = "identidade_de_outra_escola"


def _gravar_memoria_da_decisao(db: Session, escola_id: int, *, aluno_id: int,
                               plataforma: str, id_externo: str, usuario_id: int | None,
                               acao: str) -> int:
    """A confirmação do D10 pelo Admin Global vale para a coleta seguinte DESTA
    escola, como a do ``/resolver``.

    O passo 0d de ``identidade_aluno.decidir`` só associa uma conta efetiva em
    outra escola quando há MEMÓRIA humana para ela: uma ``RevisaoIdentidade``
    resolvida, com ``aluno_escolhido_id`` e sem ``automatica: true``, que
    ``carregar_contexto`` põe em ``ctx.resolvidas``. Sem esta linha, a ficha que o
    Admin Global acabou de reativar voltava para a revisão
    ``identidade_de_outra_escola`` daqui na coleta seguinte — e a gestão leva 403
    no ``/resolver``. A linha é a mesma que o ``/resolver`` deixaria: resolvida,
    ``chave_identidade`` da conta, ``aluno_escolhido_id`` = a ficha,
    ``resolvida_por_id`` = o Admin Global e ``resolucao`` {acao: associar,
    automatica: False, resolvida_na: <ação>}. Quem chama só grava para ficha
    ATIVA: com memória, a ficha arquivada ou transferida passaria a receber dado
    pelo passo 1. Devolve o id da revisão (vai na auditoria)."""
    aluno = db.get(Aluno, aluno_id)
    chave_ident = ida.chave_identidade_da_conta(plataforma, id_externo)
    momento = agora()
    rev = RevisaoIdentidade(
        escola_id=escola_id, chave=ida.chave_pendencia(chave_ident, ""),
        chave_identidade=chave_ident[:400], plataforma=plataforma, formato="",
        id_externo=id_externo, nome_recebido=(aluno.nome if aluno is not None else "")[:200],
        motivo=MOTIVO_CONTA_DE_OUTRA_ESCOLA, candidatos=[], linhas=[], contexto={},
        origem=ORIGEM_CONFIRMACAO_ADMIN, ocorrencias=1, status="resolvida",
        aluno_escolhido_id=aluno_id, resolvida_por_id=usuario_id, resolvida_em=momento,
        resolucao={"acao": "associar", "aluno_id": aluno_id, "automatica": False,
                   "resolvida_na": acao},
        created_at=momento, atualizada_em=momento)
    db.add(rev)
    db.flush()
    return rev.id


def _registrar_conta_de_outra_escola(db: Session, escola_id: int, *, aluno_id: int,
                                     plataforma: str, id_externo: str, outra: int | None,
                                     usuario_id: int | None, acao: str,
                                     motivo: str) -> tuple[str, ...]:
    """Trilha própria da decisão do Admin Global (quem, qual conta, qual outra
    escola) e o aviso do efeito lá — a outra escola não é alterada. Com a ficha
    ATIVA, a decisão vira memória (``_gravar_memoria_da_decisao``) e a coleta
    seguinte desta escola associa a conta; com a ficha inativa, não."""
    if outra is None:
        return ()
    aluno = db.get(Aluno, aluno_id)
    memoria = (_gravar_memoria_da_decisao(
        db, escola_id, aluno_id=aluno_id, plataforma=plataforma, id_externo=id_externo,
        usuario_id=usuario_id, acao=acao)
        if aluno is not None and aluno.status == ATIVO else None)
    registrar(db, "identidade.reativacao_outra_escola_confirmada", escola_id=escola_id,
              usuario_id=usuario_id, entidade="aluno", entidade_id=aluno_id,
              detalhes={"plataforma": plataforma, "id_externo": id_externo,
                        "outra_escola_id": outra, "acao": acao,
                        "motivo": (motivo or "")[:300],
                        "memoria_da_decisao": memoria,
                        "aviso": "conta continua efetiva na outra escola"})
    return (ida.AVISO_CONTA_DE_OUTRA_ESCOLA,)


# ---------------------------------------------------------------------------
# D10 pela FICHA: a ficha EXCLUÍDA que sai de "excluido"
# ---------------------------------------------------------------------------
# A regra única do D10 (``identidade_aluno.efetivas_em_outra_escola``) descarta de
# propósito a identidade presa a uma ficha EXCLUÍDA: excluída a ficha aqui, a
# outra escola pode vincular a mesma conta sem trava nenhuma, e isso está certo.
# Só que QUALQUER saída de "excluido" (reativar, arquivar, marcar como
# transferido, ou a Lista Piloto que reativa pelo RA) faz a identidade dessa ficha
# voltar a valer — e a conta passaria a ser efetiva nas duas escolas, o estado que
# o D10 só permite ao Admin Global. As funções abaixo são o ponto ÚNICO dessa
# conferência para os dois caminhos (``routers.academico.acoes_em_alunos`` e
# ``routers.importacoes._persistir_linhas``). A restauração do backup, que também
# tira fichas de "excluido", tem a conferência própria (``conferir_restauracao``,
# mais abaixo), sobre a mesma regra.
EXCLUIDO = "excluido"
AUDITORIA_FICHA_OUTRA_ESCOLA = "aluno.reativacao_outra_escola_confirmada"
MENSAGEM_FICHA_COM_CONTA_DE_OUTRA_ESCOLA = (
    "{quem} tem uma conta da plataforma que hoje é a identidade de um aluno de "
    "OUTRA escola do Constela. Tirar a ficha de “excluído” faria essa conta valer "
    "de novo aqui, e a criança de lá deixaria de ser atualizada (a conta cai em "
    "revisão na próxima coleta daquela escola): só o Admin Global decide, depois "
    "de conferir com as duas escolas. Nenhum aluno foi alterado.")


@dataclass(frozen=True)
class ContaDeOutraEscola:
    """Uma conta (não aposentada) de uma ficha excluída DAQUI que hoje é a
    identidade efetiva de um aluno de outra escola."""
    aluno_id: int
    plataforma: str
    id_externo: str
    outra_escola_id: int


def contas_de_outra_escola_da_ficha(db: Session, escola_id: int, alunos,
                                    novo_status: str) -> list[ContaDeOutraEscola]:
    """Só LÊ. Para cada ficha da lista que está EXCLUÍDA e cujo ``novo_status`` não
    é "excluido", junta as ``IdentidadeExterna`` não aposentadas dela e devolve as
    que já são a identidade EFETIVA de um aluno de OUTRA escola
    (``identidade_aluno.efetivas_em_outra_escola``, a regra única do D10). A
    aposentada fica de fora: ela não volta a valer com a ficha (a volta dela tem a
    trava própria, ``reativar``/``definir_efetiva``). Ficha que não está excluída
    não muda de efetividade (a inativa já conta) e não é conferida."""
    if novo_status == EXCLUIDO:
        return []
    saindo = sorted({a.id for a in alunos if a.status == EXCLUIDO})
    if not saindo:
        return []
    idents: list[IdentidadeExterna] = []
    for i in range(0, len(saindo), 500):
        idents.extend(db.execute(select(IdentidadeExterna).where(
            IdentidadeExterna.escola_id == escola_id,
            IdentidadeExterna.aluno_id.in_(saindo[i:i + 500]),
            IdentidadeExterna.status != APOSENTADA)
            .order_by(IdentidadeExterna.id)).scalars())
    return _contas_que_valem_em_outra_escola(db, escola_id, idents)


def _contas_que_valem_em_outra_escola(db: Session, escola_id: int,
                                      idents) -> list[ContaDeOutraEscola]:
    """Das identidades informadas (desta escola), as que já são a identidade
    EFETIVA de um aluno de OUTRA escola — pela regra única do D10
    (``identidade_aluno.efetivas_em_outra_escola``), plataforma a plataforma."""
    por_plataforma: dict[str, list[IdentidadeExterna]] = {}
    for ident in idents:
        por_plataforma.setdefault(ident.plataforma, []).append(ident)
    conflitos: list[ContaDeOutraEscola] = []
    for plataforma in sorted(por_plataforma):
        idents = por_plataforma[plataforma]
        outras = ida.efetivas_em_outra_escola(db, escola_id, plataforma,
                                              [i.id_externo for i in idents])
        conflitos.extend(
            ContaDeOutraEscola(i.aluno_id, plataforma, str(i.id_externo),
                               outras[str(i.id_externo)])
            for i in idents if str(i.id_externo) in outras)
    return conflitos


def _quem(alunos, conflitos: list[ContaDeOutraEscola]) -> str:
    """Quem trava: a ficha excluída de Fulano, ou as N fichas excluídas (até 5
    nomes). Só nomes desta escola (a gestão já os vê); nada da outra escola."""
    nome_de = {a.id: a.nome for a in alunos}
    nomes = list(dict.fromkeys(nome_de.get(c.aluno_id, "") for c in conflitos))
    if len(nomes) == 1:
        return f"A ficha excluída de “{nomes[0]}”"
    lista = ", ".join(f"“{n}”" for n in nomes[:5]) + (", …" if len(nomes) > 5 else "")
    return f"Cada uma destas {len(nomes)} fichas excluídas ({lista})"


def trava_ficha_sai_de_excluido(db: Session, escola_id: int, alunos, novo_status: str, *,
                                admin_global: bool, usuario_id: int | None,
                                acao: str) -> tuple[str, ...]:
    """D10 pela ficha, nas ações explícitas da gestão (``/alunos/acoes``): chamar
    ANTES de trocar o status. Se alguma ficha excluída da lista vai sair de
    "excluido" com uma conta que hoje é efetiva em OUTRA escola
    (``contas_de_outra_escola_da_ficha``):

      * quem não é Admin Global recebe ``ErroIdentidade`` ``conta_de_outra_escola``
        (a rota responde 403) e nada muda — a ação em massa inteira é recusada;
      * o Admin Global segue: uma auditoria ``aluno.reativacao_outra_escola_confirmada``
        por conta (aluno, plataforma, conta, outra escola, ação; sem nome) e o
        aviso ``identidade_aluno.AVISO_CONTA_DE_OUTRA_ESCOLA`` devolvido para a
        resposta. A outra escola não é alterada. Quando a ficha volta ATIVA
        (``reativar``), a decisão vira memória (``_gravar_memoria_da_decisao``) e
        a coleta seguinte desta escola associa a conta à ficha; arquivar ou marcar
        como transferido não grava memória (a ficha inativa não recebe dado).

    Sem conflito, devolve ``()`` e não registra nada."""
    conflitos = contas_de_outra_escola_da_ficha(db, escola_id, alunos, novo_status)
    if not conflitos:
        return ()
    if not admin_global:
        raise ErroIdentidade(
            MENSAGEM_FICHA_COM_CONTA_DE_OUTRA_ESCOLA.format(quem=_quem(alunos, conflitos)),
            codigo=CODIGO_CONTA_DE_OUTRA_ESCOLA)
    for c in conflitos:
        memoria = (_gravar_memoria_da_decisao(
            db, escola_id, aluno_id=c.aluno_id, plataforma=c.plataforma,
            id_externo=c.id_externo, usuario_id=usuario_id, acao=acao)
            if novo_status == ATIVO else None)
        registrar(db, AUDITORIA_FICHA_OUTRA_ESCOLA, escola_id=escola_id,
                  usuario_id=usuario_id, entidade="aluno", entidade_id=c.aluno_id,
                  detalhes={"plataforma": c.plataforma, "id_externo": c.id_externo,
                            "outra_escola_id": c.outra_escola_id, "acao": acao,
                            "status_anterior": EXCLUIDO, "status_novo": novo_status,
                            "memoria_da_decisao": memoria,
                            "aviso": "conta continua efetiva na outra escola"})
    return (ida.AVISO_CONTA_DE_OUTRA_ESCOLA,)


# ---------------------------------------------------------------------------
# D10 na RESTAURAÇÃO do backup da escola
# ---------------------------------------------------------------------------
# ``backup.restaurar`` recria as fichas com o status do arquivo e as identidades
# delas. Uma ficha excluída DEPOIS do backup, cuja conta outra escola vinculou
# nesse meio-tempo, volta a valer aqui: a conta fica efetiva nas duas escolas — o
# estado que o D10 só permite ao Admin Global, com aviso e auditoria. A rota de
# restauração já é só do Admin Global (``admin.exigir_admin_global_para_restaurar``),
# então nada é recusado: ``conferir_restauracao`` dá a trilha e o aviso. A
# restauração não decide por ficha nenhuma, então NÃO grava a memória da decisão:
# a coleta seguinte desta escola também manda a conta para a revisão
# ``identidade_de_outra_escola``, e quem decide é o Admin Global, no /resolver.
ACAO_RESTAURAR_BACKUP = "restaurar_backup"


def contas_restauradas_de_outra_escola(db: Session,
                                       escola_id: int) -> list[ContaDeOutraEscola]:
    """Só LÊ. As identidades NÃO aposentadas de fichas NÃO excluídas desta escola
    que também são a identidade efetiva de um aluno de OUTRA escola. Chamar depois
    de ``backup.restaurar`` inserir as linhas (mesma transação)."""
    idents = db.execute(
        select(IdentidadeExterna)
        .join(Aluno, Aluno.id == IdentidadeExterna.aluno_id)
        .where(IdentidadeExterna.escola_id == escola_id,
               IdentidadeExterna.status != APOSENTADA,
               Aluno.status != EXCLUIDO)
        .order_by(IdentidadeExterna.id)).scalars().all()
    return _contas_que_valem_em_outra_escola(db, escola_id, idents)


def conferir_restauracao(db: Session, escola_id: int, *,
                         usuario_id: int | None) -> tuple[str, ...]:
    """D10 depois da restauração: para cada conta que passou a valer nas duas
    escolas (``contas_restauradas_de_outra_escola``), a auditoria
    ``aluno.reativacao_outra_escola_confirmada`` (ação ``restaurar_backup``,
    plataforma, conta, outra escola; sem nome) e o aviso
    ``identidade_aluno.AVISO_CONTA_DE_OUTRA_ESCOLA`` para a resposta. A outra
    escola não é alterada. Sem conflito, devolve ``()`` e não registra nada."""
    conflitos = contas_restauradas_de_outra_escola(db, escola_id)
    for c in conflitos:
        registrar(db, AUDITORIA_FICHA_OUTRA_ESCOLA, escola_id=escola_id,
                  usuario_id=usuario_id, entidade="aluno", entidade_id=c.aluno_id,
                  detalhes={"plataforma": c.plataforma, "id_externo": c.id_externo,
                            "outra_escola_id": c.outra_escola_id,
                            "acao": ACAO_RESTAURAR_BACKUP,
                            "aviso": "conta continua efetiva na outra escola"})
    return (ida.AVISO_CONTA_DE_OUTRA_ESCOLA,) if conflitos else ()


def identidades_do_aluno(db: Session, escola_id: int, aluno_id: int,
                         plataforma: str) -> list[IdentidadeExterna]:
    return list(db.execute(
        select(IdentidadeExterna).where(
            IdentidadeExterna.escola_id == escola_id,
            IdentidadeExterna.aluno_id == aluno_id,
            IdentidadeExterna.plataforma == plataforma)
        .order_by(IdentidadeExterna.id)).scalars())


def definir_efetiva(db: Session, escola_id: int, *, aluno_id: int, plataforma: str,
                    id_externo_efetivo: str, aposentar: list[str], motivo: str,
                    usuario_id: int | None, admin_global: bool = False) -> Resultado:
    """Fixa a identidade EFETIVA do aluno nesta plataforma e aposenta as outras.

    Não apaga nada, não toca em snapshot, leitura, evento ou nota, e não altera
    nenhuma outra plataforma. Consequência: o que já veio da conta aposentada
    continua na ficha (nem o retrato nem a leitura guardam a conta de origem) e o
    retrato atual só muda quando entrar uma coleta da efetiva — ver o cabeçalho do
    módulo. Faz parte da transação de quem chama — o commit é
    do chamador, para a decisão e a auditoria caírem juntas.

    Escolher uma conta APOSENTADA a faz voltar a valer: se ela já é efetiva em
    outra escola, só o Admin Global (``admin_global``) segue, com aviso e
    auditoria (D10, ``_conta_volta_a_valer``).
    """
    motivo = (motivo or "").strip()
    if not motivo:
        raise ErroIdentidade("Explique por que esta conta foi escolhida.",
                             codigo="motivo_obrigatorio")
    aluno = db.get(Aluno, aluno_id)
    if aluno is None or aluno.escola_id != escola_id:
        raise ErroIdentidade("O aluno não pertence a esta escola.",
                             codigo="aluno_de_outra_escola")

    todas = identidades_do_aluno(db, escola_id, aluno_id, plataforma)
    por_id = {i.id_externo: i for i in todas}
    if id_externo_efetivo not in por_id:
        raise ErroIdentidade(
            f"A conta {id_externo_efetivo} não está vinculada a este aluno "
            f"em {plataforma}.", codigo="identidade_inexistente")

    pedidas = [x for x in dict.fromkeys(aposentar) if x]      # dedup preservando ordem
    if id_externo_efetivo in pedidas:
        raise ErroIdentidade("A conta escolhida não pode ser aposentada ao mesmo tempo.",
                             codigo="efetiva_e_aposentada")
    for x in pedidas:
        if x not in por_id:
            # Aposentar a conta de OUTRA ficha por engano é o erro mais caro aqui.
            dona = db.execute(select(IdentidadeExterna).where(
                IdentidadeExterna.escola_id == escola_id,
                IdentidadeExterna.plataforma == plataforma,
                IdentidadeExterna.id_externo == x)).scalars().first()
            if dona is not None:
                raise ErroIdentidade(
                    f"A conta {x} pertence a outra ficha ({dona.aluno_id}) — "
                    "aposente-a a partir daquele aluno.",
                    codigo="identidade_de_outro_aluno")
            raise ErroIdentidade(f"A conta {x} não existe em {plataforma}.",
                                 codigo="identidade_inexistente")

    antes = {i.id_externo: i.status for i in todas}
    # Uma efetiva por (aluno, plataforma): tudo que não foi escolhido e não foi
    # pedido explicitamente continua como está — só o que o gestor listou muda.
    sobrando = [i for i in todas
                if i.id_externo != id_externo_efetivo
                and i.id_externo not in pedidas and i.status == EFETIVA]
    if sobrando:
        raise ErroIdentidade(
            "Ficariam duas contas efetivas para o mesmo aluno: "
            f"{[i.id_externo for i in sobrando]}. Informe todas as que devem "
            "ser aposentadas.", codigo="duas_efetivas")

    escolhida = por_id[id_externo_efetivo]
    outra = (_trava_conta_de_outra_escola(db, escola_id, plataforma, id_externo_efetivo,
                                          admin_global)
             if escolhida.status == APOSENTADA else None)
    momento = agora()
    escolhida.status = EFETIVA
    escolhida.aposentada_em = None
    escolhida.aposentada_por_id = None
    escolhida.motivo_aposentadoria = None
    for x in pedidas:
        alvo = por_id[x]
        alvo.status = APOSENTADA
        alvo.aposentada_em = momento
        alvo.aposentada_por_id = usuario_id
        alvo.motivo_aposentadoria = motivo[:300]

    # A fila não pode continuar pedindo decisão sobre uma conta já decidida: as
    # pendências das aposentadas são ENCERRADAS como descartadas (não resolvidas
    # — resolver associaria os dados, que é justamente o que não se quer).
    encerradas: list[int] = []
    if pedidas:
        for rev in db.execute(select(RevisaoIdentidade).where(
                RevisaoIdentidade.escola_id == escola_id,
                RevisaoIdentidade.plataforma == plataforma,
                RevisaoIdentidade.status == "pendente",
                RevisaoIdentidade.id_externo.in_(pedidas))
                .order_by(RevisaoIdentidade.id)).scalars():
            rev.status = "descartada"
            rev.resolvida_por_id = usuario_id
            rev.resolvida_em = momento
            rev.resolucao = {"acao": "descartar",
                             "motivo": f"identidade aposentada: {motivo}"[:300],
                             "identidade_efetiva": id_externo_efetivo}
            encerradas.append(rev.id)

    db.flush()
    registrar(db, "identidade.efetiva_definida", escola_id=escola_id,
              usuario_id=usuario_id, entidade="aluno", entidade_id=aluno_id,
              detalhes={"plataforma": plataforma, "aluno": aluno.nome,
                        "identidade_efetiva": id_externo_efetivo,
                        "identidades_aposentadas": pedidas,
                        "estado_anterior": antes,
                        "estado_posterior": {i.id_externo: i.status for i in todas},
                        "revisoes_encerradas": encerradas, "motivo": motivo[:300],
                        "escopo": "decisao_interna_constela",
                        "observacao": ("a conta continua existindo na plataforma "
                                       "externa; nada foi desativado lá")})
    avisos = _registrar_conta_de_outra_escola(
        db, escola_id, aluno_id=aluno_id, plataforma=plataforma,
        id_externo=id_externo_efetivo, outra=outra, usuario_id=usuario_id,
        acao="definir_efetiva", motivo=motivo)
    return Resultado(aluno_id=aluno_id, plataforma=plataforma,
                     efetiva=id_externo_efetivo, aposentadas=tuple(pedidas),
                     revisoes_encerradas=tuple(encerradas), motivo=motivo, avisos=avisos)


def reativar(db: Session, escola_id: int, *, aluno_id: int, plataforma: str,
             id_externo: str, motivo: str, usuario_id: int | None,
             admin_global: bool = False) -> Resultado:
    """Desfaz uma aposentadoria — só quando isso não cria duas efetivas.

    D10: se a conta já é a identidade efetiva de um aluno de OUTRA escola, só o
    Admin Global (``admin_global``) reativa, com aviso e auditoria; os demais
    recebem ``ErroIdentidade`` ``conta_de_outra_escola`` (a rota responde 403)."""
    motivo = (motivo or "").strip()
    if not motivo:
        raise ErroIdentidade("Explique por que esta conta volta a valer.",
                             codigo="motivo_obrigatorio")
    todas = identidades_do_aluno(db, escola_id, aluno_id, plataforma)
    alvo = next((i for i in todas if i.id_externo == id_externo), None)
    if alvo is None:
        raise ErroIdentidade(f"A conta {id_externo} não está vinculada a este aluno.",
                             codigo="identidade_inexistente")
    if alvo.status == EFETIVA:
        return Resultado(aluno_id, plataforma, id_externo, (), (), motivo)
    outras = [i for i in todas if i.id is not alvo.id and i.status == EFETIVA]
    if outras:
        raise ErroIdentidade(
            "O aluno já tem uma conta efetiva nesta plataforma "
            f"({outras[0].id_externo}). Aposente-a antes de reativar esta.",
            codigo="duas_efetivas")
    outra = _trava_conta_de_outra_escola(db, escola_id, plataforma, id_externo,
                                         admin_global)
    antes = alvo.status
    alvo.status = EFETIVA
    alvo.aposentada_em = None
    alvo.aposentada_por_id = None
    alvo.motivo_aposentadoria = None
    db.flush()
    registrar(db, "identidade.reativada", escola_id=escola_id, usuario_id=usuario_id,
              entidade="aluno", entidade_id=aluno_id,
              detalhes={"plataforma": plataforma, "id_externo": id_externo,
                        "estado_anterior": antes, "estado_posterior": EFETIVA,
                        "motivo": motivo[:300], "escopo": "decisao_interna_constela"})
    avisos = _registrar_conta_de_outra_escola(
        db, escola_id, aluno_id=aluno_id, plataforma=plataforma, id_externo=id_externo,
        outra=outra, usuario_id=usuario_id, acao="reativar", motivo=motivo)
    return Resultado(aluno_id, plataforma, id_externo, (), (), motivo, avisos)
