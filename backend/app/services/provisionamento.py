"""Provisionamento inicial de uma escola.

Fonte ÚNICA da configuração de partida (pesos, critérios de desempate, níveis
de dificuldade e referências de normalização), usada tanto pelo script de seed
quanto pela criação de escola na interface.

Antes deste módulo, só o `scripts/seed.py` criava uma escola COM os níveis de
dificuldade; uma escola criada pela tela "Escolas" (POST /escolas) nascia sem
nenhum nível — e caía no beco de "Cadastre os níveis de dificuldade" tanto na
pontuação por turma quanto no "livros por nível" do Elefante. Provisionar aqui
garante que toda escola nova nasça pronta, venha de onde vier.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Configuracao, NivelDificuldade, ReferenciaNormalizacao
from app.services import scoring

# Configuração inicial dos níveis de dificuldade (PRD §38).
# (nome, código estável, códigos de letra agrupados, pontos por livro)
NIVEIS_PADRAO: list[tuple[str, str, list[str], float]] = [
    ("Pré-Leitor", "pre_leitor", ["AA", "BB", "CC", "DD"], 1.0),
    ("Nível 1", "nivel_1", ["A", "B", "C"], 2.0),
    ("Nível 2", "nivel_2", ["D", "E", "F", "G", "H", "I", "J"], 4.0),
    ("Nível 3", "nivel_3", ["K", "L", "M", "N", "O", "P", "Q", "R"], 8.0),
    ("Nível 4", "nivel_4", ["S", "T", "U", "V", "W", "X"], 12.0),
    ("Nível 5", "nivel_5", ["Y", "Z"], 16.0),
]


def semear_niveis_padrao(db: Session, escola_id: int) -> list[NivelDificuldade]:
    """Cria os níveis de dificuldade padrão da escola — apenas se ela ainda não
    tem nenhum (idempotente). Não faz commit: o chamador decide quando persistir.
    Retorna os níveis existentes (se já havia) ou os recém-criados, ordenados."""
    existentes = db.execute(
        select(NivelDificuldade)
        .where(NivelDificuldade.escola_id == escola_id)
        .order_by(NivelDificuldade.ordem)
    ).scalars().all()
    if existentes:
        return list(existentes)

    criados: list[NivelDificuldade] = []
    for ordem, (nome, codigo, codigos, pontos) in enumerate(NIVEIS_PADRAO):
        nivel = NivelDificuldade(
            escola_id=escola_id, nome=nome, codigo=codigo, codigos=list(codigos),
            pontos_padrao=pontos, ordem=ordem,
        )
        db.add(nivel)
        criados.append(nivel)
    db.flush()
    return criados


def semear_config_inicial(db: Session, escola_id: int) -> None:
    """Provisiona a configuração inicial de uma escola nova (idempotente): pesos
    por namespace, critérios de desempate, níveis de dificuldade e referências
    de normalização. Só adiciona o que ainda não existe — seguro de rechamar.
    Não faz commit: chame dentro da transação da criação da escola."""
    # Pesos por namespace (matific, elefante, questoes, geral).
    for namespace, valores in scoring.PESOS_PADRAO.items():
        existe = db.execute(
            select(Configuracao).where(
                Configuracao.escola_id == escola_id,
                Configuracao.namespace == namespace,
                Configuracao.chave == "valores",
            )
        ).scalar_one_or_none()
        if existe is None:
            db.add(Configuracao(escola_id=escola_id, namespace=namespace,
                                chave="valores", valor=valores))

    # Critérios de desempate.
    desempate = db.execute(
        select(Configuracao).where(
            Configuracao.escola_id == escola_id,
            Configuracao.namespace == "desempate",
            Configuracao.chave == "criterios",
        )
    ).scalar_one_or_none()
    if desempate is None:
        db.add(Configuracao(escola_id=escola_id, namespace="desempate",
                            chave="criterios", valor=scoring.CRITERIOS_DESEMPATE_PADRAO))

    # Níveis de dificuldade (padrão do Elefante Letrado).
    semear_niveis_padrao(db, escola_id)

    # Referências de normalização (modo automático).
    ref = db.execute(
        select(ReferenciaNormalizacao).where(ReferenciaNormalizacao.escola_id == escola_id)
    ).scalar_one_or_none()
    if ref is None:
        db.add(ReferenciaNormalizacao(escola_id=escola_id, modo="auto"))


def escola_sem_niveis(db: Session, escola_id: int) -> bool:
    """A escola não tem nenhum nível de dificuldade cadastrado?"""
    total = db.execute(
        select(func.count()).select_from(NivelDificuldade)
        .where(NivelDificuldade.escola_id == escola_id)
    ).scalar()
    return not total
