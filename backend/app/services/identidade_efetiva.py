"""Conta duplicada na mesma plataforma: qual identidade vale para o aluno.

A criança tem DUAS contas na mesma plataforma — foi assim que os dados dela
passaram a se dividir entre duas fontes, e o retrato da ficha ficou mostrando o
de uma só. Quando a escola não tem acesso administrativo à plataforma, não dá
para apagar a duplicada lá; e apagá-la AQUI seria pior, porque se perderia a
prova de que aquele id externo era daquela criança.

Então o Constela guarda as duas e diz qual é a EFETIVA. A aposentada continua
existindo, com todo o histórico: só deixa de casar na importação, de alimentar
retrato/pontuação e de voltar a se associar sozinha.

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
from app.services.audit import registrar

EFETIVA = "efetiva"
APOSENTADA = "aposentada"


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

    def como_dict(self) -> dict:
        return {"aluno_id": self.aluno_id, "plataforma": self.plataforma,
                "identidade_efetiva": self.efetiva,
                "identidades_aposentadas": list(self.aposentadas),
                "revisoes_encerradas": list(self.revisoes_encerradas),
                "motivo": self.motivo}


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
                    usuario_id: int | None) -> Resultado:
    """Fixa a identidade EFETIVA do aluno nesta plataforma e aposenta as outras.

    Não apaga nada, não toca em snapshot, leitura, evento ou nota, e não altera
    nenhuma outra plataforma. Faz parte da transação de quem chama — o commit é
    do chamador, para a decisão e a auditoria caírem juntas.
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

    momento = agora()
    escolhida = por_id[id_externo_efetivo]
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
    return Resultado(aluno_id=aluno_id, plataforma=plataforma,
                     efetiva=id_externo_efetivo, aposentadas=tuple(pedidas),
                     revisoes_encerradas=tuple(encerradas), motivo=motivo)


def reativar(db: Session, escola_id: int, *, aluno_id: int, plataforma: str,
             id_externo: str, motivo: str, usuario_id: int | None) -> Resultado:
    """Desfaz uma aposentadoria — só quando isso não cria duas efetivas."""
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
    return Resultado(aluno_id, plataforma, id_externo, (), (), motivo)
