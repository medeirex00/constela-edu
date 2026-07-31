"""Inteligência Pedagógica e Assistente de IA (PRD §129–§172)."""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import escola_autorizada, exigir_papeis, get_usuario_atual
from app.models import ConversaIA, Escola, MensagemIA, Usuario
from app.services import assistente, evolucao, insights, permissoes
from app.services.audit import registrar

router = APIRouter(prefix="/escolas/{escola_id}", tags=["Inteligência Pedagógica"])


# --- Insights e alertas (PRD §129–§153) ----------------------------------------

@router.get("/insights")
def insights_da_escola(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Índices de engajamento/evolução/persistência + alertas automáticos.
    Professor recebe apenas os alunos das turmas dele."""
    # Varreduras CARAS e independentes da janela (snapshots Matific/Elefante,
    # mapa de dificuldade, DISTINCT de leituras): carrega UMA vez e injeta em
    # AMBOS os serviços. Antes, índices e alertas releiam os snapshots por conta
    # própria — trabalho duplicado que ajudava /insights a estourar o timeout.
    serie_m, serie_e, mapa_dif = evolucao.series_e_dificuldade(db, escola_id)
    alunos_com_leituras = evolucao._alunos_com_leituras(db, escola_id)
    resultado = {
        "indices": insights.indices_da_escola(
            db, escola_id, serie_m=serie_m, serie_e=serie_e, mapa_dif=mapa_dif,
            alunos_com_leituras=alunos_com_leituras),
        "alertas": insights.alertas_da_escola(
            db, escola_id, serie_m=serie_m, serie_e=serie_e),
    }
    permitidas = permissoes.turmas_permitidas(db, escola_id, usuario)
    if permitidas is not None:
        escola = db.get(Escola, escola_id)
        alunos = permissoes.alunos_permitidos(db, escola_id,
                                              escola.ano_letivo_ativo, permitidas)
        resultado["indices"] = permissoes.filtrar_por_aluno(resultado["indices"], alunos)
        resultado["alertas"] = permissoes.filtrar_por_aluno(resultado["alertas"], alunos)
    return resultado


# --- Assistente Pedagógico (PRD §155–§172) --------------------------------------

class PerguntaIn(BaseModel):
    pergunta: str = Field(min_length=2, max_length=2000)
    conversa_id: int | None = None


@router.post("/assistente")
def perguntar(
    dados: PerguntaIn,
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Chat com contexto montado no backend — a IA só vê dados desta escola.
    O contexto é da ESCOLA TODA, então professor não acessa."""
    permissoes.negar_restrito(db, escola_id, usuario)
    try:
        resultado = assistente.perguntar(
            db, escola_id, usuario.id, dados.pergunta, dados.conversa_id
        )
    except ValueError as erro:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(erro))
    registrar(db, "assistente.pergunta", escola_id=escola_id, usuario_id=usuario.id,
              entidade="conversa_ia", entidade_id=resultado["conversa_id"],
              detalhes={"provedor": resultado["provedor"]})
    db.commit()
    return resultado


@router.get("/assistente/conversas")
def listar_conversas(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Histórico de conversas do usuário logado (PRD §160)."""
    conversas = db.execute(
        select(ConversaIA)
        .where(ConversaIA.escola_id == escola_id, ConversaIA.usuario_id == usuario.id)
        .order_by(ConversaIA.id.desc())
        .limit(30)
    ).scalars().all()
    return [
        {"id": c.id, "titulo": c.titulo, "provedor": c.provedor, "created_at": c.created_at}
        for c in conversas
    ]


@router.get("/assistente/conversas/{conversa_id}")
def mensagens_da_conversa(
    conversa_id: int,
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    conversa = db.get(ConversaIA, conversa_id)
    if conversa is None or conversa.escola_id != escola_id \
            or conversa.usuario_id != usuario.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversa não encontrada.")
    mensagens = db.execute(
        select(MensagemIA).where(MensagemIA.conversa_id == conversa_id)
        .order_by(MensagemIA.id)
    ).scalars().all()
    return {
        "id": conversa.id,
        "titulo": conversa.titulo,
        "provedor": conversa.provedor,
        "mensagens": [
            {"papel": m.papel, "conteudo": m.conteudo, "created_at": m.created_at}
            for m in mensagens
        ],
    }


@router.get("/assistente/status")
def status_do_assistente(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
):
    """Qual provedor está configurado (sem expor chaves) — config de gestão."""
    config = assistente.config_assistente(db, escola_id)
    return {"provedor": config["provedor"], "modelo": config["modelo"] or "padrão"}


# --- Configuração do assistente (admin) — chave de API pela interface ---------

class ConfigAssistenteIn(BaseModel):
    provedor: str = Field(pattern="^(local|anthropic|openai)$")
    # Vazio/ausente mantém a chave já salva (a chave nunca volta ao navegador).
    api_key: str | None = Field(default=None, max_length=300)
    modelo: str | None = Field(default=None, max_length=100)


@router.get("/assistente/config")
def obter_config_assistente(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_papeis("admin")),
):
    return assistente.config_assistente(db, escola_id)


@router.put("/assistente/config")
def salvar_config_assistente(
    dados: ConfigAssistenteIn,
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_papeis("admin")),
):
    """Salva o provedor de IA da escola. A chave é gravada CIFRADA e nunca é
    devolvida — só o indicador de que existe."""
    try:
        resultado = assistente.salvar_config_assistente(
            db, escola_id, dados.provedor, dados.api_key, dados.modelo)
    except ValueError as erro:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(erro))
    registrar(db, "assistente.configurado", escola_id=escola_id, usuario_id=usuario.id,
              detalhes={"provedor": dados.provedor,
                        "chave_alterada": bool((dados.api_key or "").strip())})
    db.commit()
    return resultado


@router.post("/assistente/config/testar")
def testar_config_assistente(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_papeis("admin")),
):
    """Faz UMA chamada mínima ao provedor configurado para validar a chave."""
    from app.services.ia import ErroProvedorIA

    try:
        provedor = assistente._provedor_da_escola(db, escola_id)
        resposta = provedor.responder(
            "Você é um verificador de configuração. Responda apenas: OK",
            [{"papel": "usuario", "conteudo": "Está funcionando?"}])
        return {"ok": True, "provedor": provedor.nome,
                "resposta": (resposta or "")[:120]}
    except ErroProvedorIA as erro:
        return {"ok": False, "erro": str(erro)[:300]}
