"""Rede / Secretaria de Educação — o tier municipal (acima da escola).

Isolamento REAL: toda rota de dados passa por ``exigir_rede``, que só libera a
rede do próprio usuário (``usuario.rede_id``) ou o admin global. Uma secretaria
NUNCA lê os dados de outra rede (IDOR entre redes barrado). Só AGREGA — não
reimplementa scoring, não toca em pesos/fórmulas e não expõe PII de criança.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import exigir_admin_global, exigir_rede, get_usuario_atual
from app.models import Escola, Rede, Usuario
from app.schemas import (
    EscolaLocalIn,
    RedeCreate,
    RedeEscolasIn,
    RedeOut,
    RedeUpdate,
    RedeUsuariosIn,
)
from app.services import geocodificacao as svc_geo
from app.services import rede as svc_rede
from app.services.audit import registrar

router = APIRouter(prefix="/redes", tags=["Rede / Secretaria"])


@router.get("")
def listar_redes(
    usuario: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db),
):
    """Redes visíveis ao usuário: o admin global vê todas; um usuário de rede vê
    só a sua; um usuário de escola única não vê nenhuma (lista vazia)."""
    consulta = select(Rede).where(Rede.status == "ativa").order_by(Rede.nome)
    if not usuario.is_global:
        if usuario.rede_id is None:
            return []
        consulta = consulta.where(Rede.id == usuario.rede_id)
    return [
        {"id": r.id, "nome": r.nome, "uf": r.uf, "codigo_ibge": r.codigo_ibge}
        for r in db.execute(consulta).scalars().all()
    ]


# --- CRUD / provisionamento (só admin global) -------------------------------
# Criar uma rede, decidir QUAIS escolas entram nela (e onde ficam no mapa) e
# QUEM é a Secretaria: tudo exclusivo do admin global — uma rede cruza várias
# escolas, então só o administrador supremo a provisiona.

@router.get("/gerenciar")
def gerenciar(
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Tudo que a tela de gestão de redes precisa numa viagem: as redes, TODAS
    as escolas (com o vínculo e as coordenadas atuais) e os usuários candidatos
    a Secretaria. Só o admin global enxerga esta visão completa."""
    redes = db.execute(select(Rede).order_by(Rede.nome)).scalars().all()
    escolas = db.execute(select(Escola).order_by(Escola.nome)).scalars().all()
    usuarios = db.execute(
        select(Usuario).where(Usuario.status == "ativo").order_by(Usuario.nome)
    ).scalars().all()
    return {
        "redes": [
            {"id": r.id, "nome": r.nome, "uf": r.uf,
             "codigo_ibge": r.codigo_ibge, "status": r.status}
            for r in redes
        ],
        "escolas": [
            {"id": e.id, "nome": e.nome, "cidade": e.cidade, "estado": e.estado,
             "status": e.status, "rede_id": e.rede_id,
             "latitude": e.latitude, "longitude": e.longitude}
            for e in escolas
        ],
        "usuarios": [
            {"id": u.id, "nome": u.nome, "email": u.email, "cargo": u.cargo,
             "is_global": u.is_global, "escola_id": u.escola_id,
             "rede_id": u.rede_id}
            for u in usuarios
        ],
    }


@router.post("", response_model=RedeOut, status_code=status.HTTP_201_CREATED)
def criar_rede(
    dados: RedeCreate,
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    nome = dados.nome.strip()
    # Nome repetido criaria duas redes indistinguíveis no seletor — recusa aqui
    # (um clique duplo/reenvio nunca duplica a rede).
    repetida = db.execute(
        select(Rede).where(func.lower(Rede.nome) == nome.lower())
    ).scalar_one_or_none()
    if repetida is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Já existe uma rede chamada “{repetida.nome}”.")
    rede = Rede(nome=nome, uf=(dados.uf or None), codigo_ibge=(dados.codigo_ibge or None))
    db.add(rede)
    db.flush()
    registrar(db, "rede.criada", usuario_id=usuario.id, entidade="rede",
              entidade_id=rede.id, detalhes={"nome": rede.nome})
    db.commit()
    db.refresh(rede)
    return rede


@router.patch("/{rede_id}", response_model=RedeOut)
def atualizar_rede(
    rede_id: int,
    dados: RedeUpdate,
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    rede = db.get(Rede, rede_id)
    if rede is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rede não encontrada.")
    alteracoes = dados.model_dump(exclude_unset=True)
    if "nome" in alteracoes:
        alteracoes["nome"] = alteracoes["nome"].strip()
    for campo, valor in alteracoes.items():
        setattr(rede, campo, valor)
    registrar(db, "rede.atualizada", usuario_id=usuario.id, entidade="rede",
              entidade_id=rede.id, detalhes=alteracoes)
    db.commit()
    db.refresh(rede)
    return rede


@router.put("/{rede_id}/escolas")
def definir_escolas(
    rede_id: int,
    dados: RedeEscolasIn,
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Define o conjunto de escolas da rede. Idempotente: as escolas da lista
    passam a pertencer à rede; as que estavam nela e não vieram são
    desvinculadas (rede_id = NULL). Ignora ids de escola inexistentes."""
    rede = db.get(Rede, rede_id)
    if rede is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rede não encontrada.")
    alvo = set(dados.escola_ids)
    validas = db.execute(
        select(Escola).where(Escola.id.in_(alvo))
    ).scalars().all() if alvo else []
    ids_validos = {e.id for e in validas}
    # Desvincula quem saiu; o que continua na lista é revinculado abaixo.
    atuais = db.execute(
        select(Escola).where(Escola.rede_id == rede_id)
    ).scalars().all()
    for escola in atuais:
        if escola.id not in ids_validos:
            escola.rede_id = None
    for escola in validas:
        escola.rede_id = rede_id
    registrar(db, "rede.escolas_definidas", usuario_id=usuario.id, entidade="rede",
              entidade_id=rede_id, detalhes={"escola_ids": sorted(ids_validos)})
    db.commit()
    return {"rede_id": rede_id, "escola_ids": sorted(ids_validos)}


@router.patch("/escolas/{escola_id}")
def atualizar_local_escola(
    escola_id: int,
    dados: EscolaLocalIn,
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Cidade/UF e coordenadas de uma escola (para o mapa da Secretaria)."""
    escola = db.get(Escola, escola_id)
    if escola is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Escola não encontrada.")
    alteracoes = dados.model_dump(exclude_unset=True)
    for campo, valor in alteracoes.items():
        setattr(escola, campo, valor)
    registrar(db, "escola.local_atualizado", escola_id=escola.id, usuario_id=usuario.id,
              entidade="escola", entidade_id=escola.id, detalhes=alteracoes)
    db.commit()
    db.refresh(escola)
    return {"id": escola.id, "cidade": escola.cidade, "estado": escola.estado,
            "latitude": escola.latitude, "longitude": escola.longitude}


@router.put("/{rede_id}/usuarios")
def definir_usuarios(
    rede_id: int,
    dados: RedeUsuariosIn,
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Define QUEM é a Secretaria desta rede. Idempotente: os usuários da lista
    recebem o rede_id; os que estavam na rede e saíram voltam a ficar sem rede.
    Ignora ids inexistentes."""
    rede = db.get(Rede, rede_id)
    if rede is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rede não encontrada.")
    alvo = set(dados.usuario_ids)
    validos = db.execute(
        select(Usuario).where(Usuario.id.in_(alvo))
    ).scalars().all() if alvo else []
    ids_validos = {u.id for u in validos}
    atuais = db.execute(
        select(Usuario).where(Usuario.rede_id == rede_id)
    ).scalars().all()
    for alvo_u in atuais:
        if alvo_u.id not in ids_validos:
            alvo_u.rede_id = None
    for alvo_u in validos:
        alvo_u.rede_id = rede_id
    registrar(db, "rede.usuarios_definidos", usuario_id=usuario.id, entidade="rede",
              entidade_id=rede_id, detalhes={"usuario_ids": sorted(ids_validos)})
    db.commit()
    return {"rede_id": rede_id, "usuario_ids": sorted(ids_validos)}


@router.post("/{rede_id}/geocodificar")
def geocodificar(
    rede_id: int,
    forcar: bool = Query(default=False),
    limite: int = Query(default=6, ge=1, le=10),
    depois_de: int = Query(default=0, ge=0),
    usuario: Usuario = Depends(exigir_admin_global),
    geocoder: svc_geo.Geocoder = Depends(svc_geo.get_geocoder),
    intervalo: float = Depends(svc_geo.get_intervalo_geocode),
    db: Session = Depends(get_db),
):
    """Preenche lat/long das escolas da rede via OSM (as SEM coordenada, ou todas
    com ``?forcar``). Processa em lotes de ``limite`` para a requisição não ficar
    longa (o OSM pede ~1s por escola).

    Paginação por CURSOR de id (``depois_de``): cada lote avança pelas escolas
    com ``id`` maior que o cursor — INDEPENDENTE de a geocodificação ter dado
    certo. Isso é essencial porque uma escola que o OSM não localiza continua sem
    coordenada; sem o cursor ela voltaria à mesma janela e o lote nunca avançaria
    (martelando o OSM e nunca alcançando as escolas seguintes). O front chama em
    sequência passando ``depois_de=ultimo_id`` até ``restantes``=0. Só admin
    global; o ajuste manual (PATCH /redes/escolas/{id}) corrige o não localizado."""
    rede = db.get(Rede, rede_id)
    if rede is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rede não encontrada.")

    def pendentes_apos(cursor: int):
        q = select(Escola).where(Escola.rede_id == rede_id, Escola.id > cursor)
        return q if forcar else q.where(Escola.latitude.is_(None))

    lote = db.execute(
        pendentes_apos(depois_de).order_by(Escola.id).limit(limite)
    ).scalars().all()
    resultado = svc_geo.geocodificar_lote(lote, geocoder, intervalo)
    ultimo_id = lote[-1].id if lote else depois_de
    # Quantas ainda faltam ALÉM deste lote — contadas por id (falha ou sucesso já
    # ficaram para trás do cursor), então este número decresce a cada lote.
    restantes = db.execute(
        select(func.count()).select_from(pendentes_apos(ultimo_id).subquery())
    ).scalar() or 0
    registrar(db, "rede.geocodificada", usuario_id=usuario.id, entidade="rede",
              entidade_id=rede_id,
              detalhes={"processadas": len(lote), "ultimo_id": ultimo_id, **resultado})
    db.commit()
    return {
        "processadas": len(lote),
        "encontradas": resultado["encontradas"],
        "falhas": resultado["falhas"],
        "restantes": restantes,
        "ultimo_id": ultimo_id,
    }


@router.get("/{rede_id}/dashboard")
def dashboard(
    rede_id: int = Depends(exigir_rede),
    db: Session = Depends(get_db),
):
    """Painel municipal: totais da rede, equidade entre escolas, escolas em
    atenção e o cartão de cada escola (com lat/lng para o mapa). Só dados
    agregados por escola — nada de PII de criança."""
    return svc_rede.dashboard_rede(db, rede_id)


@router.get("/{rede_id}/ranking")
def ranking(
    rede_id: int = Depends(exigir_rede),
    limite: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Ranking municipal POR ESCOLA (privacidade: não expõe ranking individual de
    crianças entre escolas). Ordena por média geral e adoção."""
    return svc_rede.ranking_escolas(db, rede_id, limite=limite)
