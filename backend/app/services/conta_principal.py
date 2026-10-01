"""Qual das contas duplicadas da MESMA plataforma é a principal.

Decisão de produto: **a conta com a atividade mais recente**. Nada mais.

O que esta regra proíbe, explicitamente, porque foi assim que o sistema errou
antes: escolher por ordem do banco, por UUID (maior ou menor), pelo primeiro ou
último registro criado, pela ordem da importação, pelo nome, por similaridade de
texto, pela quantidade de registros ou pela posição na Lista Piloto. A escolha
implícita que existia era ``linhas_aluno[-1]`` — a última linha do arquivo
vencia em silêncio. Qualquer um desses critérios é um desempate inventado.

Quando a atividade não desempata, esta função **não escolhe**: devolve
``EMPATE_ATIVIDADE`` ou ``SEM_ATIVIDADE_PARA_DESEMPATE`` e o caso vai para
decisão humana. Devolver "não sei" é resposta; chutar não é.

O que conta como atividade
--------------------------
Atividade REAL registrada na plataforma — a data em que a criança leu o livro ou
resolveu a atividade —, nunca a data em que o Constela sincronizou. Hoje, no
banco, isso existe só para o Elefante: o coletor traz ``lastReadWhen`` junto do
``studentId`` na mesma linha. O Matific **não devolve timestamp algum** por
aluno, só contadores acumulados; por isso toda colisão de Matific cai, e vai
continuar caindo, em ``SEM_ATIVIDADE_PARA_DESEMPATE``. Isso não é limitação
desta função: é ausência do dado na origem.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

#: A conta foi determinada pela atividade mais recente.
DETERMINADA = "CONTA_PRINCIPAL_DETERMINADA"
#: Duas ou mais contas têm exatamente a mesma atividade mais recente.
EMPATE = "EMPATE_ATIVIDADE"
#: Nenhuma conta tem atividade datada — não há com o que desempatar.
SEM_ATIVIDADE = "SEM_ATIVIDADE_PARA_DESEMPATE"


@dataclass(frozen=True)
class Conta:
    """Uma conta externa e a última atividade REAL dela (``None`` = sem dado)."""

    id_externo: str
    ultima_atividade: datetime | None = None
    status: str = "efetiva"


@dataclass(frozen=True)
class Decisao:
    classificacao: str
    principal: str | None
    aposentar: tuple[str, ...]
    motivo: str

    @property
    def precisa_de_humano(self) -> bool:
        return self.classificacao != DETERMINADA


def decidir(contas: list[Conta] | tuple[Conta, ...]) -> Decisao:
    """A conta com a atividade mais recente vence. Empate ou ausência de
    atividade → decisão humana.

    Uma conta COM atividade vence uma conta SEM atividade: "nunca" é mais antigo
    que qualquer data. Isso não é desempate inventado — é a própria regra, com um
    dos lados vazio.

    >>> from datetime import datetime as dt
    >>> d = decidir([Conta("A", dt(2026, 5, 18)), Conta("B", dt(2026, 9, 23))])
    >>> d.classificacao, d.principal, d.aposentar
    ('CONTA_PRINCIPAL_DETERMINADA', 'B', ('A',))
    """
    if len(contas) < 2:
        raise ValueError("decidir() é para colisão: precisa de 2+ contas")

    com_data = [c for c in contas if c.ultima_atividade is not None]
    if not com_data:
        return Decisao(SEM_ATIVIDADE, None, (),
                       "nenhuma das contas tem atividade datada — não há com o "
                       "que desempatar, e escolher por qualquer outro critério "
                       "(UUID, ordem, volume) seria inventar")

    recente = max(c.ultima_atividade for c in com_data)
    vencedoras = [c for c in com_data if c.ultima_atividade == recente]
    if len(vencedoras) > 1:
        nomes = ", ".join(sorted(c.id_externo for c in vencedoras))
        return Decisao(EMPATE, None, (),
                       f"{len(vencedoras)} contas com a MESMA última atividade "
                       f"({recente:%d/%m/%Y %H:%M}): {nomes}")

    vencedora = vencedoras[0]
    perdedoras = tuple(sorted(c.id_externo for c in contas
                              if c.id_externo != vencedora.id_externo))
    return Decisao(DETERMINADA, vencedora.id_externo, perdedoras,
                   f"atividade mais recente ({recente:%d/%m/%Y %H:%M}); as "
                   f"demais ficaram para trás")
