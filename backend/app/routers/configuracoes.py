"""Configurações de métricas — o coração da flexibilidade do sistema.

Tudo que o motor de cálculo usa é editável por aqui (PRD §5, §29, §58–§62).
Qualquer alteração dispara recálculo integral (PRD §43) e fica no log.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import escola_autorizada, exigir_papeis, exigir_papeis_escola
from app.models import (
    Configuracao,
    DificuldadeTurma,
    NivelDificuldade,
    PontuacaoNivelTurma,
    ReferenciaNormalizacao,
    Turma,
    Usuario,
)
from pydantic import BaseModel, Field
from app.schemas import (
    DificuldadeUpdate,
    NivelOut,
    PesosOut,
    PesosUpdate,
    ReferenciasOut,
    ReferenciasUpdate,
)
from app.services import scoring
from app.services.audit import registrar

router = APIRouter(prefix="/escolas/{escola_id}/configuracoes", tags=["Configurações"])

NAMESPACES_PESOS = {"matific", "elefante", "questoes", "geral"}


# --- Pesos (PRD §29, §59, §60) ----------------------------------------------

@router.get("/pesos/{namespace}", response_model=PesosOut)
def obter_pesos(
    namespace: str,
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
):
    if namespace not in NAMESPACES_PESOS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Grupo de pesos inexistente.")
    valores = scoring.obter_pesos_brutos(db, escola_id, f"pesos.{namespace}")
    return PesosOut(namespace=namespace, valores=valores, soma=round(sum(valores.values()), 2))


@router.put("/pesos/{namespace}", response_model=PesosOut)
def salvar_pesos(
    namespace: str,
    dados: PesosUpdate,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis_escola("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    if namespace not in NAMESPACES_PESOS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Grupo de pesos inexistente.")

    esperados = set(scoring.PESOS_PADRAO[f"pesos.{namespace}"].keys())
    if set(dados.valores.keys()) != esperados:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Indicadores esperados: {', '.join(sorted(esperados))}.",
        )
    soma = round(sum(dados.valores.values()), 2)
    if abs(soma - 100.0) > 0.01:
        # A soma dos pesos deve sempre resultar em 100% (PRD §33, §59)
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"A soma dos pesos deve ser 100%. Soma atual: {soma}%.",
        )

    chave_ns = f"pesos.{namespace}"
    row = db.execute(
        select(Configuracao).where(
            Configuracao.escola_id == escola_id,
            Configuracao.namespace == chave_ns,
            Configuracao.chave == "valores",
        )
    ).scalar_one_or_none()
    anterior = dict(row.valor) if row else scoring.PESOS_PADRAO[chave_ns]
    if row is None:
        row = Configuracao(escola_id=escola_id, namespace=chave_ns, chave="valores", valor=dados.valores)
        db.add(row)
    else:
        row.valor = dados.valores

    registrar(db, "pesos.alterados", escola_id=escola_id, usuario_id=usuario.id,
              entidade="configuracao", detalhes={"namespace": namespace, "de": anterior, "para": dados.valores})
    db.commit()
    scoring.recalcular_escola(db, escola_id)
    return PesosOut(namespace=namespace, valores=dados.valores, soma=soma)


# --- Referências de normalização (PRD §31, §62) -----------------------------

@router.get("/referencias", response_model=ReferenciasOut)
def obter_referencias(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
):
    row = db.execute(
        select(ReferenciaNormalizacao).where(ReferenciaNormalizacao.escola_id == escola_id)
    ).scalar_one_or_none()
    em_uso, modo = scoring.referencias_em_uso(db, escola_id)
    return ReferenciasOut(
        modo=row.modo if row else "auto",
        valores_manuais=row.valores_manuais if row else {},
        valores_em_uso=em_uso,
    )


@router.put("/referencias", response_model=ReferenciasOut)
def salvar_referencias(
    dados: ReferenciasUpdate,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis_escola("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    invalidas = set(dados.valores_manuais) - set(scoring.CHAVES_REFERENCIA)
    if invalidas:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Referências desconhecidas: {', '.join(sorted(invalidas))}.",
        )
    row = db.execute(
        select(ReferenciaNormalizacao).where(ReferenciaNormalizacao.escola_id == escola_id)
    ).scalar_one_or_none()
    if row is None:
        row = ReferenciaNormalizacao(escola_id=escola_id)
        db.add(row)
    row.modo = dados.modo
    row.valores_manuais = dados.valores_manuais

    registrar(db, "referencias.alteradas", escola_id=escola_id, usuario_id=usuario.id,
              entidade="referencia_normalizacao",
              detalhes={"modo": dados.modo, "valores": dados.valores_manuais})
    db.commit()
    scoring.recalcular_escola(db, escola_id)
    em_uso, _ = scoring.referencias_em_uso(db, escola_id)
    return ReferenciasOut(modo=row.modo, valores_manuais=row.valores_manuais, valores_em_uso=em_uso)


# --- Dificuldade por turma/série (PRD §39, §61) -----------------------------

@router.get("/dificuldade")
def obter_dificuldade(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
):
    niveis = db.execute(
        select(NivelDificuldade)
        .where(NivelDificuldade.escola_id == escola_id)
        .order_by(NivelDificuldade.ordem)
    ).scalars().all()
    series = [
        linha[0]
        for linha in db.execute(
            select(Turma.ano_escolar).where(Turma.escola_id == escola_id).distinct().order_by(Turma.ano_escolar)
        ).all()
    ]
    overrides = db.execute(
        select(DificuldadeTurma).where(DificuldadeTurma.escola_id == escola_id)
    ).scalars().all()
    mapa = {}
    for override in overrides:
        mapa.setdefault(override.ano_escolar, {})[override.nivel_id] = override.pontos

    tabelas = []
    for serie in series:
        pontos = {
            nivel.id: mapa.get(serie, {}).get(nivel.id, nivel.pontos_padrao)
            for nivel in niveis
        }
        tabelas.append({"ano_escolar": serie, "pontos": pontos})

    return {
        "niveis": [NivelOut.model_validate(n) for n in niveis],
        "series": tabelas,
    }


@router.put("/dificuldade")
def salvar_dificuldade(
    alteracoes: list[DificuldadeUpdate],
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis_escola("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    for alteracao in alteracoes:
        nivel = db.get(NivelDificuldade, alteracao.nivel_id)
        if nivel is None or nivel.escola_id != escola_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nível inválido para esta escola.")
        row = db.execute(
            select(DificuldadeTurma).where(
                DificuldadeTurma.escola_id == escola_id,
                DificuldadeTurma.ano_escolar == alteracao.ano_escolar,
                DificuldadeTurma.nivel_id == alteracao.nivel_id,
            )
        ).scalar_one_or_none()
        if row is None:
            row = DificuldadeTurma(
                escola_id=escola_id,
                ano_escolar=alteracao.ano_escolar,
                nivel_id=alteracao.nivel_id,
            )
            db.add(row)
        row.pontos = alteracao.pontos

    registrar(db, "dificuldade.alterada", escola_id=escola_id, usuario_id=usuario.id,
              entidade="dificuldade_turma",
              detalhes={"alteracoes": [a.model_dump() for a in alteracoes]})
    db.commit()
    scoring.recalcular_escola(db, escola_id)
    return {"mensagem": f"{len(alteracoes)} valores atualizados. Notas recalculadas."}


# --- Pontuação LIVRE por nível, por TURMA (PRD §39) --------------------------

class PontuacaoTurmaUpdate(BaseModel):
    turma_id: int
    # {"AA": 1.0, "M": 2.0, ...} — parcial; código ausente herda o padrão.
    pontos: dict[str, float] = Field(default_factory=dict)


def _catalogo_niveis(db: Session, escola_id: int) -> list[dict]:
    """Catálogo canônico e ORDENADO dos códigos de nível (AA..Z) da escola, com o
    ponto PADRÃO de cada um e a faixa a que pertence. Derivado das faixas
    (NivelDificuldade.codigos) — sem tabela nova, sem código fixo."""
    niveis = db.execute(
        select(NivelDificuldade)
        .where(NivelDificuldade.escola_id == escola_id)
        .order_by(NivelDificuldade.ordem)
    ).scalars().all()
    catalogo: list[dict] = []
    vistos: set[str] = set()
    for nivel in niveis:
        for codigo in (nivel.codigos or []):
            cod = str(codigo).strip().upper()
            if not cod or cod in vistos:
                continue
            vistos.add(cod)
            catalogo.append({"codigo": cod, "pontos_padrao": float(nivel.pontos_padrao),
                             "faixa": nivel.nome})
    return catalogo


@router.get("/pontuacao-turma")
def obter_pontuacao_turma(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
):
    """Catálogo de níveis (com padrões) + a config LIVRE já salva por turma."""
    catalogo = _catalogo_niveis(db, escola_id)
    turmas = db.execute(
        select(Turma).where(Turma.escola_id == escola_id, Turma.status == "ativa")
        .order_by(Turma.ano_escolar, Turma.nome)
    ).scalars().all()
    overrides = {
        row.turma_id: {str(k).upper(): float(v) for k, v in (row.pontos_por_codigo or {}).items()}
        for row in db.execute(
            select(PontuacaoNivelTurma).where(PontuacaoNivelTurma.escola_id == escola_id)
        ).scalars()
    }
    return {
        "catalogo": catalogo,
        "turmas": [{"turma_id": t.id, "nome": t.nome, "ano_escolar": t.ano_escolar,
                    "pontos": overrides.get(t.id, {})} for t in turmas],
    }


@router.put("/pontuacao-turma")
def salvar_pontuacao_turma(
    dados: PontuacaoTurmaUpdate,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis_escola("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Salva a tabela de pontos por nível de UMA turma. Guarda só o que difere do
    padrão (config esparsa); zera a linha se ficar vazia. Recalcula as notas."""
    turma = db.get(Turma, dados.turma_id)
    if turma is None or turma.escola_id != escola_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Turma inválida para esta escola.")
    validos = {c["codigo"] for c in _catalogo_niveis(db, escola_id)}
    limpos: dict[str, float] = {}
    for codigo, pontos in (dados.pontos or {}).items():
        cod = str(codigo).strip().upper()
        if cod not in validos:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Nível “{codigo}” não existe nesta escola.")
        if pontos is None or float(pontos) < 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pontos não podem ser negativos.")
        limpos[cod] = round(float(pontos), 2)

    row = db.execute(
        select(PontuacaoNivelTurma).where(
            PontuacaoNivelTurma.escola_id == escola_id,
            PontuacaoNivelTurma.turma_id == dados.turma_id)
    ).scalar_one_or_none()
    if row is None:
        row = PontuacaoNivelTurma(escola_id=escola_id, turma_id=dados.turma_id)
        db.add(row)
    row.pontos_por_codigo = limpos

    registrar(db, "pontuacao_turma.alterada", escola_id=escola_id, usuario_id=usuario.id,
              entidade="pontuacao_nivel_turma",
              detalhes={"turma_id": dados.turma_id, "n_codigos": len(limpos)})
    db.commit()
    scoring.recalcular_escola(db, escola_id)
    return {"mensagem": f"Pontuação da turma {turma.nome} salva. Notas recalculadas.",
            "turma_id": dados.turma_id, "pontos": limpos}
