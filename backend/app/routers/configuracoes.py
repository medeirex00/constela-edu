"""Configurações de métricas — o coração da flexibilidade do sistema.

Tudo que o motor de cálculo usa é editável por aqui (PRD §5, §29, §58–§62).
Qualquer alteração dispara recálculo integral (PRD §43) e fica no log.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import (
    escola_autorizada,
    exigir_admin_global,
    exigir_papeis,
    exigir_papeis_escola,
)
from app.models import (
    Configuracao,
    DificuldadeTurma,
    NivelDificuldade,
    PontuacaoNivelTurma,
    ReferenciaNormalizacao,
    Turma,
    Usuario,
)
from app.models.configuracao import slug_nivel
from pydantic import BaseModel, Field
from app.schemas import (
    DificuldadeUpdate,
    ElefanteExtraOut,
    ElefanteExtraUpdate,
    NivelCreate,
    NivelOut,
    NivelUpdate,
    PesosOut,
    PesosUpdate,
    ReferenciasOut,
    ReferenciasUpdate,
)
from app.services import provisionamento, scoring
from app.services.audit import registrar

router = APIRouter(prefix="/escolas/{escola_id}/configuracoes", tags=["Configurações"])

NAMESPACES_PESOS = {"matific", "elefante", "questoes", "geral"}
MODOS_PERFIL_SCORING = {"institucional", "personalizado"}


# --- Perfil de scoring: institucional (rede) × personalizado (interno) -------

class PerfilScoringOut(BaseModel):
    modo: str  # "institucional" | "personalizado"


class PerfilScoringIn(BaseModel):
    modo: str = Field(description='"institucional" (padrão Constela) ou "personalizado"')


@router.get("/perfil-scoring", response_model=PerfilScoringOut)
def obter_perfil_scoring(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
):
    """Régua do ranking INTERNO da escola: ``institucional`` (padrão Constela) ou
    ``personalizado`` (config da própria escola). NÃO afeta o ranking da rede."""
    modo = scoring.obter_config(db, escola_id, scoring.PERFIL_SCORING_NS, "modo",
                                "institucional")
    return PerfilScoringOut(modo=str(modo))


@router.put("/perfil-scoring", response_model=PerfilScoringOut)
def definir_perfil_scoring(
    dados: PerfilScoringIn,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis_escola("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Escolhe a régua do ranking INTERNO da escola. IMPORTANTE: personalizar NÃO
    muda a posição da escola no ranking da REDE — esse usa sempre a régua
    institucional (colunas ``nota_*_institucional``). Dispara recálculo."""
    modo = str(dados.modo).strip().lower()
    if modo not in MODOS_PERFIL_SCORING:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            'modo deve ser "institucional" ou "personalizado".')
    row = db.execute(
        select(Configuracao).where(
            Configuracao.escola_id == escola_id,
            Configuracao.namespace == scoring.PERFIL_SCORING_NS,
            Configuracao.chave == "modo",
        )
    ).scalar_one_or_none()
    anterior = str(row.valor) if row else "institucional"
    if row is None:
        row = Configuracao(escola_id=escola_id, namespace=scoring.PERFIL_SCORING_NS,
                           chave="modo", valor=modo)
        db.add(row)
    else:
        row.valor = modo
    registrar(db, "pesos.alterados", escola_id=escola_id, usuario_id=usuario.id,
              entidade="configuracao",
              detalhes={"perfil_scoring": {"de": anterior, "para": modo}})
    db.commit()
    scoring.recalcular_escola(db, escola_id)
    return PerfilScoringOut(modo=modo)


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


# --- Pontos extras por livro lido na escola (Elefante) ----------------------
# Config própria (namespace pesos.elefante_extra) — NÃO usa /pesos, que exige
# soma 100%. A regra de horário (janela do turno) vive no scoring.

@router.get("/elefante-extra", response_model=ElefanteExtraOut)
def obter_elefante_extra(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
):
    v = scoring.obter_config(db, escola_id, "pesos.elefante_extra", "valores",
                             {"ativo": False, "pontos_por_livro": 0.0})
    return ElefanteExtraOut(ativo=bool(v.get("ativo", False)),
                            pontos_por_livro=float(v.get("pontos_por_livro", 0) or 0))


@router.put("/elefante-extra", response_model=ElefanteExtraOut)
def salvar_elefante_extra(
    dados: ElefanteExtraUpdate,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis_escola("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Liga/desliga os pontos extras e define quanto cada livro lido na escola
    vale. Desligar NÃO apaga nenhuma leitura — só deixa de somar o bônus. Recalcula."""
    valor = {"ativo": bool(dados.ativo), "pontos_por_livro": round(float(dados.pontos_por_livro), 2)}
    row = db.execute(
        select(Configuracao).where(
            Configuracao.escola_id == escola_id,
            Configuracao.namespace == "pesos.elefante_extra",
            Configuracao.chave == "valores")
    ).scalar_one_or_none()
    if row is None:
        row = Configuracao(escola_id=escola_id, namespace="pesos.elefante_extra",
                           chave="valores", valor=valor)
        db.add(row)
    else:
        row.valor = valor
    registrar(db, "elefante_extra.alterado", escola_id=escola_id, usuario_id=usuario.id,
              entidade="configuracao", detalhes=valor)
    db.commit()
    scoring.recalcular_escola(db, escola_id)
    return ElefanteExtraOut(**valor)


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


# --- Cadastro dos níveis de dificuldade (faixas) — CRUD (PRD §38) ------------
# As faixas (NivelDificuldade) são a BASE de tudo no Elefante: sem elas, não há
# catálogo de códigos para pontuar por turma nem para informar "livros por
# nível". Estas rotas permitem cadastrá-las/editá-las pela interface (antes,
# só o seed criava faixas — escola criada pela tela ficava sem nenhuma).

def _normalizar_codigos(codigos: list[str] | None) -> list[str]:
    """Códigos de letra em MAIÚSCULA, sem espaços, sem vazios nem repetidos."""
    limpos: list[str] = []
    vistos: set[str] = set()
    for bruto in codigos or []:
        cod = str(bruto).strip().upper()
        if cod and cod not in vistos:
            vistos.add(cod)
            limpos.append(cod)
    return limpos


@router.post("/niveis", response_model=NivelOut, status_code=status.HTTP_201_CREATED)
def criar_nivel(
    dados: NivelCreate,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_admin_global),  # níveis = referência: só admin global edita
    db: Session = Depends(get_db),
):
    ordem_max = db.execute(
        select(func.max(NivelDificuldade.ordem)).where(NivelDificuldade.escola_id == escola_id)
    ).scalar()
    nome = dados.nome.strip()
    nivel = NivelDificuldade(
        escola_id=escola_id,
        nome=nome,
        codigo=slug_nivel(nome),
        codigos=_normalizar_codigos(dados.codigos),
        pontos_padrao=float(dados.pontos_padrao),
        ordem=0 if ordem_max is None else ordem_max + 1,
    )
    db.add(nivel)
    registrar(db, "nivel.criado", escola_id=escola_id, usuario_id=usuario.id,
              entidade="nivel_dificuldade",
              detalhes={"nome": nome, "codigos": nivel.codigos, "pontos": nivel.pontos_padrao})
    db.commit()
    db.refresh(nivel)
    scoring.recalcular_escola(db, escola_id)
    return NivelOut.model_validate(nivel)


@router.put("/niveis/{nivel_id}", response_model=NivelOut)
def atualizar_nivel(
    nivel_id: int,
    dados: NivelUpdate,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_admin_global),  # níveis = referência: só admin global edita
    db: Session = Depends(get_db),
):
    nivel = db.get(NivelDificuldade, nivel_id)
    if nivel is None or nivel.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nível não encontrado nesta escola.")
    if dados.nome is not None:
        nivel.nome = dados.nome.strip()
        nivel.codigo = slug_nivel(nivel.nome)
    if dados.codigos is not None:
        nivel.codigos = _normalizar_codigos(dados.codigos)
    if dados.pontos_padrao is not None:
        nivel.pontos_padrao = float(dados.pontos_padrao)
    if dados.ordem is not None:
        nivel.ordem = dados.ordem
    registrar(db, "nivel.alterado", escola_id=escola_id, usuario_id=usuario.id,
              entidade="nivel_dificuldade", entidade_id=nivel.id,
              detalhes={"nome": nivel.nome, "codigos": nivel.codigos, "pontos": nivel.pontos_padrao})
    db.commit()
    db.refresh(nivel)
    scoring.recalcular_escola(db, escola_id)
    return NivelOut.model_validate(nivel)


@router.delete("/niveis/{nivel_id}")
def excluir_nivel(
    nivel_id: int,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_admin_global),  # níveis = referência: só admin global edita
    db: Session = Depends(get_db),
):
    nivel = db.get(NivelDificuldade, nivel_id)
    if nivel is None or nivel.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nível não encontrado nesta escola.")
    nome = nivel.nome
    # Remove antes os pontos por série que referenciam este nível (FK) — de forma
    # explícita, sem depender do CASCADE do banco (portável entre SQLite/Postgres).
    db.execute(delete(DificuldadeTurma).where(
        DificuldadeTurma.escola_id == escola_id, DificuldadeTurma.nivel_id == nivel_id))
    db.delete(nivel)
    registrar(db, "nivel.excluido", escola_id=escola_id, usuario_id=usuario.id,
              entidade="nivel_dificuldade", entidade_id=nivel_id, detalhes={"nome": nome})
    db.commit()
    scoring.recalcular_escola(db, escola_id)
    return {"mensagem": f"Nível “{nome}” removido. Notas recalculadas."}


@router.post("/niveis/padrao")
def restaurar_niveis_padrao(
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_admin_global),  # níveis = referência: só admin global edita
    db: Session = Depends(get_db),
):
    """Cria os níveis de dificuldade PADRÃO do Elefante Letrado — atalho de 1
    clique para escolas que nasceram sem faixas. Se já houver níveis, não mexe
    (não duplica); devolve os atuais."""
    vazia = provisionamento.escola_sem_niveis(db, escola_id)
    niveis = provisionamento.semear_niveis_padrao(db, escola_id)
    if vazia:
        registrar(db, "niveis.padrao_criados", escola_id=escola_id, usuario_id=usuario.id,
                  entidade="nivel_dificuldade", detalhes={"quantidade": len(niveis)})
        db.commit()
        for n in niveis:
            db.refresh(n)
        scoring.recalcular_escola(db, escola_id)
    return {
        "criados": len(niveis) if vazia else 0,
        "niveis": [NivelOut.model_validate(n) for n in niveis],
    }


# --- Pontuação LIVRE por nível, por TURMA (PRD §39) --------------------------

class PontuacaoTurmaUpdate(BaseModel):
    turma_id: int
    # {"AA": 1.0, "M": 2.0, ...} — parcial; código ausente herda o padrão.
    pontos: dict[str, float] = Field(default_factory=dict)
    # Replicar a MESMA configuração para estas OUTRAS turmas (opcional). Cada uma
    # continua editável individualmente depois.
    aplicar_em: list[int] = Field(default_factory=list)


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
    """Salva a tabela de pontos por nível de UMA turma e, opcionalmente, REPLICA a
    mesma config para outras turmas (aplicar_em) — cada uma continua editável
    depois. Guarda só o que difere do padrão (config esparsa). UM recálculo no fim."""
    # Turmas-alvo = a principal + as marcadas para replicar (sem repetir).
    alvos = list(dict.fromkeys([dados.turma_id, *dados.aplicar_em]))
    turmas: dict[int, Turma] = {}
    for tid in alvos:
        t = db.get(Turma, tid)
        if t is None or t.escola_id != escola_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Turma inválida para esta escola.")
        turmas[tid] = t

    validos = {c["codigo"] for c in _catalogo_niveis(db, escola_id)}
    limpos: dict[str, float] = {}
    for codigo, pontos in (dados.pontos or {}).items():
        cod = str(codigo).strip().upper()
        if cod not in validos:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Nível “{codigo}” não existe nesta escola.")
        if pontos is None or float(pontos) < 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pontos não podem ser negativos.")
        limpos[cod] = round(float(pontos), 2)

    for tid in alvos:
        row = db.execute(
            select(PontuacaoNivelTurma).where(
                PontuacaoNivelTurma.escola_id == escola_id,
                PontuacaoNivelTurma.turma_id == tid)
        ).scalar_one_or_none()
        if row is None:
            row = PontuacaoNivelTurma(escola_id=escola_id, turma_id=tid)
            db.add(row)
        row.pontos_por_codigo = dict(limpos)

    registrar(db, "pontuacao_turma.alterada", escola_id=escola_id, usuario_id=usuario.id,
              entidade="pontuacao_nivel_turma",
              detalhes={"turmas": alvos, "n_codigos": len(limpos)})
    db.commit()
    scoring.recalcular_escola(db, escola_id)   # 1 recálculo, mesmo replicando em N turmas

    n = len(alvos)
    msg = (f"Pontuação aplicada a {n} turmas. Notas recalculadas." if n > 1
           else f"Pontuação da turma {turmas[dados.turma_id].nome} salva. Notas recalculadas.")
    return {"mensagem": msg, "turma_id": dados.turma_id, "turmas": alvos, "pontos": limpos}
