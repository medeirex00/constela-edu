"""Rede / Secretaria de Educação — o tier municipal (acima da escola).

Isolamento REAL: toda rota de dados passa por ``exigir_rede``, que só libera a
rede do próprio usuário (``usuario.rede_id``) ou o admin global. Uma secretaria
NUNCA lê os dados de outra rede (IDOR entre redes barrado). Só AGREGA — não
reimplementa scoring, não toca em pesos/fórmulas e não expõe PII de criança.
"""
from datetime import datetime, timezone

from fastapi import (APIRouter, Depends, File, HTTPException, Query, Response,
                     UploadFile, status)
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db, leitura_sem_transacao
from app.core.deps import exigir_admin_global, exigir_rede, get_usuario_atual
from app.core.tempo import hoje_br
from app.models import Escola, Rede, TokenResetSenha, Usuario
from app.routers.admin import _invalidar_links_emitidos
from app.routers.publico import base_do_link_publico
from app.schemas import (
    EscolaLocalIn,
    MetaRedeIn,
    RedeCreate,
    RedeEscolasIn,
    RedeOut,
    RedePublicoIn,
    RedeUpdate,
    RedeUsuariosIn,
)
from app.services import avaliacoes as svc_avaliacoes
from app.services import casamento_inep as svc_inep
from app.services import frescor_ranking
from app.services import geocodificacao as svc_geo
from app.services import modulos as svc_modulos
from app.services import permissoes
from app.services import push as svc_push
from app.services import relatorios as svc_relatorios
from app.services import rede as svc_rede
from app.services.audit import registrar

_MAX_BYTES_INEP = 150 * 1024 * 1024  # mesmo teto do IDEB (arquivo oficial ~97 MB)

router = APIRouter(prefix="/redes", tags=["Rede / Secretaria"])


@router.get("")
@leitura_sem_transacao
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
        {"id": r.id, "nome": r.nome, "uf": r.uf, "codigo_ibge": r.codigo_ibge,
         "codigo_municipio_estadual": r.codigo_municipio_estadual}
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
             "codigo_ibge": r.codigo_ibge,
             "codigo_municipio_estadual": r.codigo_municipio_estadual, "status": r.status}
            for r in redes
        ],
        "escolas": [
            {"id": e.id, "nome": e.nome, "cidade": e.cidade, "estado": e.estado,
             "bairro": e.bairro, "endereco": e.endereco,
             "status": e.status, "rede_id": e.rede_id,
             "latitude": e.latitude, "longitude": e.longitude,
             "codigo_inep": e.codigo_inep}
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
    rede = Rede(nome=nome, uf=(dados.uf or None), codigo_ibge=(dados.codigo_ibge or None),
                codigo_municipio_estadual=(dados.codigo_municipio_estadual or None))
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
    if "codigo_municipio_estadual" in alteracoes:
        # "" limpa (o SARESP por município volta a pedir o código na prévia).
        alteracoes["codigo_municipio_estadual"] = alteracoes["codigo_municipio_estadual"] or None
    for campo, valor in alteracoes.items():
        setattr(rede, campo, valor)
    registrar(db, "rede.atualizada", usuario_id=usuario.id, entidade="rede",
              entidade_id=rede.id, detalhes=alteracoes)
    db.commit()
    db.refresh(rede)
    return rede


@router.get("/{rede_id}/modulos")
def listar_modulos(
    rede_id: int = Depends(exigir_rede),
    db: Session = Depends(get_db),
):
    """Catálogo de módulos COM o estado de contratação da rede. Visível também à
    Secretaria (ela precisa saber o próprio plano para montar a interface); só o
    admin global ALTERA (PUT abaixo)."""
    return svc_modulos.catalogo_da_rede(db, rede_id)


@router.put("/{rede_id}/modulos")
def definir_modulos(
    rede_id: int,
    dados: dict[str, bool],
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Liga/desliga os módulos contratados da rede (Admin Global).

    Recebe ``{"leitura": true, "matematica": false}``. Efeito imediato: a rede
    passa a operar só com os módulos ligados — médias, ranking, adoção e
    interface. Fica na trilha de auditoria (é uma mudança contratual).

    **Recalcula as notas das escolas da rede** no mesmo pedido: ``pesos.geral``
    depende do contrato, então a nota GRAVADA de cada aluno precisa passar a
    refletir só o que foi contratado (rede só de Leitura ⇒ ``geral = leitura``).
    O retorno traz ``recalculo`` com o que foi refeito e o que falhou; a
    operação é idempotente, então reenviar o mesmo corpo refaz com segurança o
    que ficou para trás (ver ``services/modulos.aplicar_contrato``)."""
    if db.get(Rede, rede_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rede não encontrada.")
    desconhecidos = set(dados) - set(svc_modulos.CATALOGO)
    if desconhecidos:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Módulo(s) desconhecido(s): {', '.join(sorted(desconhecidos))}.")
    # Rede sem NENHUM módulo é um estado que o produto não sabe explicar: o
    # contrato diria "nada contratado", mas `pesos.geral` cairia no fallback de
    # segurança (mantém os pesos originais em vez de zerar a nota de todo mundo)
    # e o aluno continuaria recebendo nota das duas plataformas. Barramos aqui,
    # que é onde a intenção ainda é do operador e dá para explicar.
    if not svc_modulos.resultado_do_contrato(db, rede_id, dados):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "A rede precisa de pelo menos um módulo contratado. "
            "Para encerrar o uso, desative a rede em vez de remover os módulos.")
    return svc_modulos.aplicar_contrato(db, rede_id, dados, usuario_id=usuario.id)


@router.put("/{rede_id}/escolas")
def definir_escolas(
    rede_id: int,
    dados: RedeEscolasIn,
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Define o conjunto de escolas da rede. Idempotente: as escolas da lista
    passam a pertencer à rede; as que estavam nela e não vieram são
    desvinculadas (rede_id = NULL). Ignora ids de escola inexistentes.

    **Recalcula as notas das escolas cujo CONTRATO mudou com o vínculo**: a
    escola que entra, sai (sem rede = todos os módulos) ou troca de rede e,
    com isso, passa a ter outro conjunto de módulos. A Nota gravada precisa
    acompanhar o contrato, como em ``PUT /redes/{id}/modulos``; o módulo é a
    única entrada do motor que vem da rede. Quem já era da rede, ou mudou de
    rede sem mudar de módulos, não é recalculado (vincular uma rede inteira com
    o contrato padrão não roda o motor). O retorno traz ``recalculo`` (mesmo
    formato do PUT de módulos). Uma falha não desfaz o vínculo e o perfil já
    filtra pelo contrato de agora; como o reenvio não muda mais o vínculo, quem
    acerta a escola que falhou é o recálculo dela (ou o PUT de módulos)."""
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
    # {escola_id: (nome, rede de antes, rede de depois)} de quem muda de rede.
    mudaram: dict[int, tuple[str, int | None, int | None]] = {}
    for escola in atuais:
        if escola.id not in ids_validos:
            mudaram[escola.id] = (escola.nome, escola.rede_id, None)
            escola.rede_id = None
    for escola in validas:
        if escola.rede_id != rede_id:
            mudaram[escola.id] = (escola.nome, escola.rede_id, rede_id)
        escola.rede_id = rede_id
    registrar(db, "rede.escolas_definidas", usuario_id=usuario.id, entidade="rede",
              entidade_id=rede_id, detalhes={"escola_ids": sorted(ids_validos)})
    db.commit()  # o VÍNCULO é a fonte da verdade; daqui para baixo é cache
    contratos: dict[int | None, set[str]] = {}

    def _contrato(rid: int | None) -> set[str]:
        if rid not in contratos:
            contratos[rid] = svc_modulos.modulos_da_rede(db, rid)
        return contratos[rid]

    a_recalcular = sorted((eid, nome) for eid, (nome, de, para) in mudaram.items()
                          if _contrato(de) != _contrato(para))
    recalculo = svc_modulos.recalcular_escolas(
        db, a_recalcular, f"vínculo com a rede {rede_id}")
    return {"rede_id": rede_id, "escola_ids": sorted(ids_validos), "recalculo": recalculo}


def _exigir_inep_livre(db: Session, escola: Escola, codigo: str) -> None:
    """409 quando o código INEP (já normalizado) pertence a OUTRA escola — de
    qualquer rede: o INEP identifica uma escola só, e duas com o mesmo código fariam
    a importação oficial escolher em silêncio de quem é o resultado. A comparação é
    pelo código NORMALIZADO (um cadastro antigo com "035012345" também conta); o
    índice único ``uq_escolas_codigo_inep`` (0035) é a trava final no banco."""
    for outra_id, outra_nome, outro_codigo in db.execute(
            select(Escola.id, Escola.nome, Escola.codigo_inep).where(
                Escola.id != escola.id, Escola.codigo_inep.isnot(None))):
        if svc_avaliacoes.normalizar_inep(outro_codigo) == codigo:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"O código INEP {codigo} já pertence à escola “{outra_nome}” (id "
                f"{outra_id}). Cada escola tem o seu INEP: confira o código ou corrija "
                "primeiro a outra escola. Nada foi alterado.")


@router.patch("/escolas/{escola_id}")
def atualizar_local_escola(
    escola_id: int,
    dados: EscolaLocalIn,
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Cidade/UF, coordenadas e código INEP de uma escola (mapa + avaliações)."""
    escola = db.get(Escola, escola_id)
    if escola is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Escola não encontrada.")
    alteracoes = dados.model_dump(exclude_unset=True)
    if "codigo_inep" in alteracoes:
        bruto = (alteracoes["codigo_inep"] or "").strip()
        # "" limpa; caso contrário normaliza p/ 8 dígitos (recusa lixo).
        alteracoes["codigo_inep"] = svc_avaliacoes.normalizar_inep(bruto) if bruto else None
        if alteracoes["codigo_inep"]:
            _exigir_inep_livre(db, escola, alteracoes["codigo_inep"])
    for campo, valor in alteracoes.items():
        setattr(escola, campo, valor)
    registrar(db, "escola.local_atualizado", escola_id=escola.id, usuario_id=usuario.id,
              entidade="escola", entidade_id=escola.id, detalhes=alteracoes)
    try:
        db.commit()
    except IntegrityError as exc:   # outra gravação simultânea levou o mesmo código
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "O código INEP acabou de ser gravado em outra escola. "
                            "Nada foi alterado.") from exc
    db.refresh(escola)
    return {"id": escola.id, "cidade": escola.cidade, "estado": escola.estado,
            "bairro": escola.bairro, "endereco": escola.endereco,
            "latitude": escola.latitude, "longitude": escola.longitude,
            "codigo_inep": escola.codigo_inep}


@router.post("/{rede_id}/casar-inep")
def casar_inep(
    rede_id: int,
    arquivo: UploadFile = File(...),
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Propõe o código INEP oficial para cada escola da rede, casando pelo NOME
    (dentro do mesmo município) contra o arquivo oficial do INEP. NÃO grava —
    devolve as propostas para o gestor conferir e salvar. Layout padrão = IDEB
    por escola (a coluna do nome/município/INEP já é conhecida)."""
    if db.get(Rede, rede_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rede não encontrada.")
    conteudo = arquivo.file.read(_MAX_BYTES_INEP + 1)
    if len(conteudo) > _MAX_BYTES_INEP:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            "Arquivo muito grande.")
    propostas = svc_inep.casar_inep(db, rede_id, conteudo, arquivo.filename or "")
    casadas = sum(1 for p in propostas if p["inep"] and p["confianca"] == "alta")
    revisar = sum(1 for p in propostas if p["inep"] and p["confianca"] == "revisar")
    return {"propostas": propostas, "total": len(propostas),
            "casadas": casadas, "revisar": revisar,
            "sem_correspondencia": len(propostas) - casadas - revisar}


@router.put("/{rede_id}/usuarios")
def definir_usuarios(
    rede_id: int,
    dados: RedeUsuariosIn,
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Define QUEM é a Secretaria desta rede. Idempotente: os usuários da lista
    recebem o rede_id; os que estavam na rede e saíram voltam a ficar sem rede.
    Ignora ids inexistentes. Exclusivo do admin global.

    A conta promovida MANTÉM o `escola_id` de origem — é o contexto de escola
    dela e apagá-lo mudaria dado de contas já existentes em produção. A
    consequência de segurança disso (o administrador daquela escola enxergava a
    conta institucional do município na lista de usuários e podia trocar a
    senha dela, sequestrando a leitura da rede inteira) é fechada em
    `admin._usuario_alvo`, que recusa qualquer alvo com `rede_id` para ator não
    global — e o router de administração inteiro nega a Secretaria
    (`deps.negar_secretaria`), independentemente do cargo dela.

    A conta que PASSA A TER o `rede_id` desta rede (promovida a Secretaria, ou
    vinda de outra rede) muda de alcance: as sessões abertas dela caem
    (`token_version`) e os links de redefinição pendentes deixam de valer — os
    dela e os que ela GEROU para outras contas da escola (a Secretaria não os
    poderia gerar; sem isto voltavam a valer se ela deixasse a rede) —, e
    nenhum token emitido para o alcance antigo sobrevive à promoção. Os
    aparelhos registrados por ela para o push da escola também são apagados
    (`dispositivos_removidos`). Cada promoção fica na auditoria
    (`usuario.promovido_a_secretaria`). A senha NÃO é trocada aqui.
    """
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
    agora = datetime.now(timezone.utc)
    promovidas: list[int] = []
    for alvo_u in validos:
        if alvo_u.rede_id != rede_id:
            # Promoção: alcance novo = sessões antigas caem e links pendentes morrem.
            rede_anterior = alvo_u.rede_id
            alvo_u.token_version = (alvo_u.token_version or 0) + 1
            links = db.execute(
                update(TokenResetSenha)
                .where(TokenResetSenha.usuario_id == alvo_u.id,
                       TokenResetSenha.usado_em.is_(None))
                .values(usado_em=agora)
                .execution_options(synchronize_session=False)).rowcount
            emitidos = _invalidar_links_emitidos(db, alvo_u.id, agora)
            # Os aparelhos registrados no alcance antigo (push da ESCOLA, com o
            # primeiro nome de criança) saem junto: a Secretaria não é equipe
            # da escola.
            aparelhos = svc_push.remover_aparelhos_da_conta(db, alvo_u.id)
            promovidas.append(alvo_u.id)
            registrar(db, "usuario.promovido_a_secretaria", escola_id=alvo_u.escola_id,
                      usuario_id=usuario.id, entidade="usuario", entidade_id=alvo_u.id,
                      detalhes={"rede_id": rede_id, "rede_anterior": rede_anterior,
                                "sessoes_encerradas": True,
                                "links_pendentes_invalidados": links,
                                "links_emitidos_invalidados": emitidos,
                                "dispositivos_removidos": aparelhos})
        alvo_u.rede_id = rede_id
    registrar(db, "rede.usuarios_definidos", usuario_id=usuario.id, entidade="rede",
              entidade_id=rede_id, detalhes={"usuario_ids": sorted(ids_validos),
                                             "promovidas": sorted(promovidas)})
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
@leitura_sem_transacao
def dashboard(
    rede_id: int = Depends(exigir_rede),
    usuario: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db),
):
    """Painel municipal: totais da rede, equidade entre escolas, escolas em
    atenção e o cartão de cada escola (com lat/lng para o mapa). Só dados
    agregados por escola — nada de PII de criança.

    SECRETARIA: a matéria de escola com menos de ``grupo_pequeno.K_MINIMO_TURMA``
    alunos com dado, ou com só 1 ou 2 que somam num total (ou com nota > 0),
    sai do cartão (nula, com ``grupo_pequeno``/``oculto``) e dos totais da rede,
    e a resposta ganha ``ocultas`` e ``totais.grupo_pequeno`` (ver
    ``rede.dashboard_rede``). O cartão da Secretaria não traz
    ``com_livros_premiaveis``/``com_estrelas_premiaveis``. O Admin Global recebe
    o painel de sempre."""
    return svc_rede.dashboard_rede(db, rede_id, secretaria=permissoes.e_secretaria(usuario))


@router.get("/{rede_id}/ranking")
def ranking(
    rede_id: int = Depends(exigir_rede),
    limite: int = Query(default=50, ge=1, le=200),
    metrica: str = Query(
        default="geral",
        pattern="^(geral|leitura|matematica|matific|elefante|engajamento|livros|estrelas"
                "|livros_aluno|estrelas_aluno|atividades_aluno"
                "|indice_geral|indice_leitura|indice_matematica)$"),
    usuario: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db),
):
    """Ranking municipal POR ESCOLA (privacidade: não expõe ranking individual de
    crianças entre escolas). A SEDUC escolhe o critério em ``metrica``.

    SECRETARIA: a escola cujo número desta métrica está escondido (grupo
    pequeno) sai da lista; a lista de quem ficou de fora vem em ``ocultas`` do
    ``/dashboard`` (ver ``rede.ranking_escolas``)."""
    return svc_rede.ranking_escolas(db, rede_id, limite=limite, metrica=metrica,
                                    secretaria=permissoes.e_secretaria(usuario))


@router.get("/{rede_id}/ranking/frescor")
@leitura_sem_transacao
def ranking_frescor(
    rede_id: int = Depends(exigir_rede),
    db: Session = Depends(get_db),
):
    """DE QUANDO é o dado de CADA escola do ranking da rede, por dimensão.

    Comparar uma escola cuja última coleta foi ontem com outra parada há três
    semanas é comparar retratos de épocas diferentes — o ranking per capita não
    tem como dizer isso sozinho. Esta rota devolve, por escola, o bloco de
    ``frescor_ranking`` (datas, estado e a última sincronização concluída) e o
    ``limite_dias``. Rota própria porque ``/ranking`` devolve uma LISTA (um
    envelope novo quebraria quem a consome). Só datas e contagens agregadas por
    escola — nenhum dado de criança. Mesmo isolamento por rede (``exigir_rede``)."""
    hoje = hoje_br()
    escolas = svc_rede.escolas_da_rede(db, rede_id)
    por_escola = frescor_ranking.frescor_das_escolas(
        db, escolas, hoje, contratados=svc_modulos.modulos_da_rede(db, rede_id))
    return {
        "limite_dias": frescor_ranking.LIMITE_DIAS_DADO_ATUAL,
        "hoje": hoje.isoformat(),
        "escolas": [{"escola_id": e.id, "nome": e.nome, **por_escola[e.id]}
                    for e in escolas],
    }


@router.get("/{rede_id}/destaques")
@leitura_sem_transacao
def destaques(
    rede_id: int = Depends(exigir_rede),
    usuario: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db),
):
    """ESCOLAS EM DESTAQUE da rede (Panorama da Rede): as mesmas da vitrine
    pública, pelo mesmo critério (``rede._top_escolas``), com o ``escola_id``
    para a tela levar à ficha de cada uma. Por matéria contratada (a outra sai
    ``null``): ``{escolas: [{escola_id, nome, valor}], fora_por_protecao}``,
    mais ``modulos``, ``limite`` e ``k_minimo``. Só agregado por escola — nada
    de dado de criança. Mesmo isolamento do ``/dashboard`` (``exigir_rede``).

    SECRETARIA: a escola com a matéria escondida no cartão dela (grupo pequeno)
    sai da lista dessa matéria e entra na contagem ``fora_por_protecao`` (ver
    ``rede.destaques_rede``). O Admin Global recebe a lista inteira."""
    return svc_rede.destaques_rede(db, rede_id, secretaria=permissoes.e_secretaria(usuario))


@router.get("/panorama-global")
def panorama_global(
    _: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Visão consolidada de TODAS as redes (Admin Global) — uma camada acima da
    Secretaria (que vê só a própria rede). Totais globais + cartão por rede +
    melhores escolas de toda a base. Só agregado, sem PII de criança."""
    return svc_rede.dashboard_global(db)


def _metas(db: Session, rede_id: int, usuario: Usuario) -> list[dict]:
    """Progresso das metas sobre os MESMOS totais do painel que o perfil vê: o
    "atual" da Secretaria vem dos totais sem as matérias escondidas (grupo
    pequeno) — com os totais cheios, a meta devolveria por subtração o que o
    painel esconde."""
    if not permissoes.e_secretaria(usuario):
        return svc_rede.metas_com_progresso(db, rede_id)
    return svc_rede.metas_com_progresso(
        db, rede_id, dados=svc_rede.dashboard_rede(db, rede_id, secretaria=True))


@router.get("/{rede_id}/metas")
def listar_metas(
    rede_id: int = Depends(exigir_rede),
    usuario: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db),
):
    """Metas da rede + PROGRESSO real (valor atual da rede / alvo). Sem meta
    cadastrada, devolve lista vazia — a UI mostra o convite para definir."""
    return _metas(db, rede_id, usuario)


@router.put("/{rede_id}/metas")
def definir_meta(
    dados: MetaRedeIn,
    rede_id: int = Depends(exigir_rede),
    usuario: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db),
):
    """Cadastra/atualiza uma meta da rede (upsert por métrica). Ação de quem tem a
    rede (Secretaria) ou o admin global — como a vitrine pública. A meta de uma
    plataforma cujo módulo a rede não contratou é recusada (400)."""
    try:
        svc_rede.definir_meta(db, rede_id, dados.metrica, dados.alvo, dados.descricao)
    except svc_rede.MetaForaDoPlano as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    registrar(db, "rede.meta_definida", usuario_id=usuario.id, entidade="rede",
              entidade_id=rede_id, detalhes={"metrica": dados.metrica, "alvo": dados.alvo})
    db.commit()
    return _metas(db, rede_id, usuario)


@router.delete("/{rede_id}/metas/{metrica}")
def remover_meta(
    metrica: str,
    rede_id: int = Depends(exigir_rede),
    usuario: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db),
):
    """Remove a meta de uma métrica da rede."""
    svc_rede.remover_meta(db, rede_id, metrica)
    registrar(db, "rede.meta_removida", usuario_id=usuario.id, entidade="rede",
              entidade_id=rede_id, detalhes={"metrica": metrica})
    db.commit()
    return _metas(db, rede_id, usuario)


@router.get("/{rede_id}/avaliacoes/opcoes")
def avaliacoes_opcoes(
    rede_id: int = Depends(exigir_rede),
    db: Session = Depends(get_db),
):
    """Séries de avaliação disponíveis para as escolas da rede (para os seletores
    da tela de correlação) — só combinações que têm dado."""
    return svc_avaliacoes.opcoes_rede(db, rede_id)


@router.get("/{rede_id}/avaliacoes/correlacao")
def avaliacoes_correlacao(
    rede_id: int = Depends(exigir_rede),
    avaliacao: str = Query(...),
    indicador: str = Query(...),
    edicao: int = Query(...),
    etapa: str | None = Query(default=None),
    componente: str | None = Query(default=None),
    # Padrão = índice per capita (comparável entre escolas). `media_geral` segue
    # aceita como opção explícita, mas não é comparável (régua interna da escola).
    metrica: str = Query(default="pontuacao_geral",
                         pattern="^(pontuacao_geral|media_geral|adocao)$"),
    usuario: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db),
):
    """Cruza, por escola, a avaliação oficial × o engajamento nas plataformas:
    pontos do gráfico, correlação de Pearson e a evolução histórica. Sem afirmar
    causalidade (a tela deixa explícito). Só dados agregados por escola."""
    resultado = svc_avaliacoes.correlacao_rede(
        db, rede_id, avaliacao_chave=avaliacao, indicador=indicador, edicao=edicao,
        etapa=etapa, componente=componente, metrica=metrica)
    if permissoes.e_secretaria(usuario):
        _correlacao_da_secretaria(db, rede_id, resultado, metrica)
    return resultado


def _correlacao_da_secretaria(db: Session, rede_id: int, resultado: dict,
                              metrica: str) -> None:
    """O eixo X da Secretaria sai dos cartões que ELA vê (grupo pequeno,
    ``rede.cartoes_da_rede``): o índice e a média geral da escola com uma
    matéria escondida são os das matérias visíveis, e a escola sem nenhuma
    visível sai do gráfico. Com o X de ``_kpis_da_rede`` (o número cheio), o
    ponto da escola, ao lado do cartão dela no painel, devolveria a matéria
    escondida. A correlação é refeita sobre os pontos que sobram. IN PLACE."""
    # A métrica que o serviço de fato usou (ele normaliza a desconhecida).
    metrica = resultado.get("metrica", metrica)
    cartoes = {c["escola_id"]: c
               for c in svc_rede.cartoes_da_rede(db, rede_id, secretaria=True)}
    pontos = []
    for ponto in resultado.get("pontos", []):
        x = (cartoes.get(ponto["escola_id"]) or {}).get(metrica)
        if x is None:
            continue
        pontos.append({**ponto, "x": round(float(x), 1)})
    resultado["pontos"] = pontos
    resultado["n"] = len(pontos)
    # Mesma conta do serviço (Pearson; None com menos de 3 pontos).
    resultado["pearson"] = svc_avaliacoes._pearson([(p["x"], p["y"]) for p in pontos])


def _painel_publico_saida(rede: Rede | None, origem: str | None = None) -> dict:
    """Estado da vitrine com o link — a base é a mesma do telão da escola
    (``publico.base_do_link_publico``): quem decide é o servidor, e ``origem`` (a origem
    da tela) só vale em loopback, sem ``PUBLIC_BASE_URL`` definido de propósito."""
    token = rede.token_publico if rede else None
    return {
        "ativo": bool(token),
        "token": token,
        "url": f"{base_do_link_publico(origem)}/rede/p/{token}" if token else None,
    }


@router.get("/{rede_id}/publico")
@leitura_sem_transacao
def painel_publico_config(
    origem: str | None = None,
    rede_id: int = Depends(exigir_rede),
    db: Session = Depends(get_db),
):
    """Estado da vitrine pública da rede (ligada/desligada + link)."""
    return _painel_publico_saida(db.get(Rede, rede_id), origem)


@router.put("/{rede_id}/publico")
def painel_publico_definir(
    dados: RedePublicoIn,
    origem: str | None = None,
    rede_id: int = Depends(exigir_rede),
    usuario: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db),
):
    """Liga (gera token) ou desliga (invalida o link) a vitrine pública da rede —
    top 5 escolas em leitura e matemática, SEM PII de criança. Ação de quem tem a
    rede (Secretaria) ou o admin global."""
    svc_rede.definir_painel_publico(db, rede_id, dados.ativo)
    registrar(db, "rede.painel_publico", usuario_id=usuario.id, entidade="rede",
              entidade_id=rede_id, detalhes={"ativo": dados.ativo})
    db.commit()
    return _painel_publico_saida(db.get(Rede, rede_id), origem)


@router.get("/{rede_id}/boletim")
def boletim(
    rede_id: int = Depends(exigir_rede),
    usuario: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db),
):
    """Boletim da rede em PDF — documento de vitrine para a Secretaria levar a
    reuniões: panorama, equidade, escolas em atenção e ranking das escolas. Só
    dados AGREGADOS por escola (sem PII de criança). Acesso: a própria Secretaria
    (``exigir_rede``) ou o admin global."""
    rede = db.get(Rede, rede_id)
    # O MESMO painel que o perfil vê na tela (Secretaria: sem os grupos pequenos).
    dados = svc_rede.dashboard_rede(db, rede_id, secretaria=permissoes.e_secretaria(usuario))
    conteudo = svc_relatorios.gerar_boletim_rede(rede.nome, dados)
    registrar(db, "rede.boletim_exportado", usuario_id=usuario.id, entidade="rede",
              entidade_id=rede_id, detalhes={"escolas": dados["totais"]["escolas"]})
    db.commit()
    momento = datetime.now(timezone.utc)
    nome_arquivo = f"boletim_rede_{rede_id}_{momento:%Y%m%d}.pdf"
    return Response(
        content=conteudo,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )
