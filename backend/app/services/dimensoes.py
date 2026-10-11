"""Leitura do desempenho POR DIMENSÃO de um aluno (Arquitetura 2).

Este módulo é o **lado de leitura** do que o motor carimba no recálculo
(`scoring._ordenar_por_dimensao`): ele não calcula nota nenhuma, não decide
régua e não escreve no banco. Existe para que os ~15 consumidores de nota de
aluno (perfil, turma, certificado, cartaz, telão, app, assistente, alertas)
leiam a MESMA estrutura, em vez de cada um remontar o bloco por dimensão do seu
jeito — que é exatamente como nasceram as "duas verdades" que a Arquitetura 2
veio eliminar.

Regras que este módulo preserva, e que não podem ser reinterpretadas aqui:

* **ausência ≠ zero** (spec §1.2, §12.3): sem snapshot da plataforma daquela
  dimensão, ``aferido=False``, ``nota=None`` e ``posicao=None``. A tela mostra
  ``—``. Nunca 0,0;
* **zero legítimo** (spec §12.4): com snapshot e indicadores zerados,
  ``aferido=True`` e ``nota=0.0``. Entra em último, e pesa;
* **cascata CONTRATO → DADO** (spec §3.5): dimensão de módulo não contratado não
  existe para a escola — ninguém é "não aferido" num produto que a rede não
  comprou;
* o discriminante é sempre a EXISTÊNCIA do snapshot (as colunas
  ``Nota.aferido_*``, carimbadas pelo motor), **jamais** ``nota > 0``.
"""
from sqlalchemy.orm import Session

from app.models import Nota
from app.schemas import AdocaoAlunoOut, DimensaoAlunoOut
from app.services import scoring

# dimensão → (coluna da nota, coluna de AFERIDO, coluna da posição carimbada).
# FONTE ÚNICA deste mapeamento no lado de leitura: alertas, contexto da IA,
# certificado, cartaz e telão leem daqui, para não existirem duas noções de "a
# coluna da Leitura" espalhadas pelo código.
COLUNAS = {
    "leitura": ("nota_elefante", "aferido_leitura", "posicao_leitura"),
    "matematica": ("nota_matific", "aferido_matematica", "posicao_matematica"),
}
_COLUNAS = COLUNAS

ROTULOS = {"leitura": "Leitura", "matematica": "Matemática"}


def aferido(nota, dimensao: str) -> bool:
    """Existe snapshot atual da plataforma daquela dimensão para este aluno.

    É o ÚNICO discriminante permitido entre ausência e zero legítimo — nunca
    `nota > 0` (spec §12.4)."""
    return bool(nota is not None and getattr(nota, COLUNAS[dimensao][1]))


def valor(nota, dimensao: str) -> float | None:
    """A nota da dimensão, ou `None` quando não aferido (o `—` da tela)."""
    return getattr(nota, COLUNAS[dimensao][0]) if aferido(nota, dimensao) else None


def bloco(nota: Nota | None, dimensao: str,
          contratada: bool = True) -> DimensaoAlunoOut:
    """Monta o bloco de UMA dimensão a partir da linha de `notas`.

    Prefere o detalhe gravado pelo motor (``detalhes.dimensoes``, que traz os
    dados brutos, o ``snapshot_em`` e o ``n_aferidos``) e cai nas COLUNAS quando
    a escola ainda não foi recalculada nesta arquitetura — o carimbo
    ``detalhes.composicao`` é justamente o detector desse estado (spec §14,
    risco 2). Nos dois caminhos o corte de aferido vem da coluna, que é o que o
    ranking também usa: assim a tela nunca discorda da lista.
    """
    plataforma = scoring.DIMENSOES[dimensao]
    coluna_nota, coluna_aferido, coluna_posicao = _COLUNAS[dimensao]
    if nota is None or not contratada:
        return DimensaoAlunoOut(dimensao=dimensao, plataforma=plataforma,
                                contratada=contratada)
    tem_dado = bool(getattr(nota, coluna_aferido))
    detalhe = ((nota.detalhes or {}).get("dimensoes") or {}).get(dimensao) or {}
    return DimensaoAlunoOut(
        dimensao=dimensao,
        plataforma=plataforma,
        contratada=contratada,
        aferido=tem_dado,
        # `None` (e não 0,0) quando não aferido: é o `—` da tela.
        nota=(getattr(nota, coluna_nota) if tem_dado else None),
        posicao=(getattr(nota, coluna_posicao) if tem_dado else None),
        n_aferidos=int(detalhe.get("n_aferidos") or 0),
        snapshot_em=detalhe.get("snapshot_em"),
        dados=(detalhe.get("dados") or {}) if tem_dado else {},
    )


def blocos(db: Session, escola, nota: Nota | None) -> list[DimensaoAlunoOut]:
    """Os blocos de TODAS as dimensões CONTRATADAS pela rede da escola.

    Só as contratadas: a dimensão que a rede não assinou não vira "—" na tela do
    aluno, ela simplesmente não existe para aquela escola (cascata contrato →
    dado)."""
    contratadas = scoring.dimensoes_contratadas(db, escola)
    return [bloco(nota, d, contratada=True) for d in scoring.DIMENSOES
            if d in contratadas]


def adocao(db: Session, escola, nota: Nota | None) -> AdocaoAlunoOut:
    """Cobertura do aluno: |D| / |P| × 100 (spec §3.2).

    Reusa o bloco gravado pelo motor quando existe; senão recompõe das colunas
    de aferido, com o mesmo denominador (as dimensões CONTRATADAS)."""
    contratadas = scoring.dimensoes_contratadas(db, escola)
    gravado = (nota.detalhes or {}).get("adocao") if nota is not None else None
    if gravado:
        return AdocaoAlunoOut(
            contratadas=list(gravado.get("contratadas") or contratadas),
            com_dados=list(gravado.get("com_dados") or []),
            pct=float(gravado.get("pct") or 0.0),
        )
    com_dados = [d for d in contratadas
                 if nota is not None and getattr(nota, _COLUNAS[d][1])]
    return AdocaoAlunoOut(
        contratadas=list(contratadas), com_dados=com_dados,
        pct=round(len(com_dados) / len(contratadas) * 100, 2) if contratadas else 0.0,
    )


def com_desempenho(db: Session, escola, nota: Nota | None) -> list[DimensaoAlunoOut]:
    """As dimensões que o aluno de fato TEM para mostrar: contratadas, aferidas
    e com nota > 0.

    É o conjunto que sustenta um documento de MÉRITO (certificado): sem
    nenhuma, não há o que certificar — e um documento oficial com brasão
    afirmando "0,0" é constrangedor, que é a razão original da guarda de
    `relatorios.certificado`."""
    return [b for b in blocos(db, escola, nota)
            if b.aferido and (b.nota or 0.0) > 0]
