"""Inteligência Pedagógica e Assistente de IA (PRD §129–§172)."""
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import escola_autorizada, exigir_papeis, get_usuario_atual
from app.models import ConversaIA, Escola, MensagemIA, Usuario
from app.services import assistente, evolucao, insights, permissoes, scoring
from app.services.audit import registrar
from app.services.ia import ErroProvedorIA

logger = logging.getLogger("constela.ia")

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
    # A rota só LÊ: num bloco único de ``leituras_da_requisicao``, configuração,
    # contrato e coorte saem do banco uma vez por requisição, não uma vez por
    # serviço (DESEMPENHO-2).
    with scoring.leituras_da_requisicao(db):
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
    O contexto é da ESCOLA TODA, então professor não acessa. A Secretaria também
    não: o contexto inclui dado individual de criança, que a IA poderia revelar."""
    permissoes.negar_dado_individual(db, escola_id, usuario)
    try:
        resultado = assistente.perguntar(
            db, escola_id, usuario.id, dados.pergunta, dados.conversa_id
        )
    except assistente.ConversaNaoEncontrada as erro:
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
    # As respostas do Assistente reidentificam nome+situação de criança; a
    # Secretaria não acessa (nem as próprias conversas antigas, se virou Secretaria).
    permissoes.negar_dado_individual(db, escola_id, usuario)
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
    permissoes.negar_dado_individual(db, escola_id, usuario)  # respostas reidentificam PII
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
    """Qual provedor responde de fato (sem expor chaves) — o selo da tela do
    Assistente. Provedor externo sem chave utilizável (a salva não abre mais com
    a chave de cifra do servidor, ou o ambiente não tem AI_API_KEY) aparece como
    ``local``: é o modo local que responde, e o selo não pode dizer o contrário.
    O estado da configuração (e o "sem chave utilizável") fica em GET /config."""
    config = assistente.config_assistente(db, escola_id)
    em_uso = assistente.provedor_em_uso(config)
    modelo = config["modelo"] if em_uso != "local" else ""
    return {"provedor": em_uso, "modelo": modelo or "padrão"}


# --- Configuração do assistente (admin) — chave de API pela interface ---------
#
# Quem liga o provedor EXTERNO (P9, análogo ao D7): Anthropic/OpenAI recebem o
# contexto pseudonimizado da escola (turmas, notas, índices, alertas) em
# servidores fora do país. Ligar, reconfigurar (modelo) ou gravar a chave de um
# provedor externo é exclusivo do Admin Global. O admin da escola continua
# VENDO o estado (GET /config e /status) e pode DESLIGAR: salvar o provedor
# `local` (sem rede), que ele já podia antes e que descarta a chave gravada.

class ConfigAssistenteIn(BaseModel):
    provedor: str = Field(pattern="^(local|anthropic|openai)$")
    # Vazio/ausente mantém a chave já salva (a chave nunca volta ao navegador).
    api_key: str | None = Field(default=None, max_length=300)
    modelo: str | None = Field(default=None, max_length=100)


_MSG_EXTERNO_SO_GLOBAL = (
    "Ligar ou configurar um provedor de IA externo (Anthropic/OpenAI) e gravar "
    "a chave de API é exclusivo do Admin Global: o assistente externo envia "
    "dados pseudonimizados da escola para fora do país. O administrador da "
    "escola pode manter ou voltar ao modo local (sem rede).")


# Vai depois de "O provedor não respondeu: " na tela de configuração.
_MSG_FALHA_INESPERADA_NO_TESTE = (
    "falha inesperada na consulta ao provedor. Tente de novo em instantes.")


def _exigir_global_para_externo(dados: ConfigAssistenteIn, usuario: Usuario) -> None:
    """403 para quem não é Admin Global e pede QUALQUER coisa além do modo local
    sem chave. Roda antes de gravar: a configuração da escola fica intocada."""
    if usuario.is_global:
        return
    if dados.provedor != "local" or (dados.api_key or "").strip():
        raise HTTPException(status.HTTP_403_FORBIDDEN, _MSG_EXTERNO_SO_GLOBAL)


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
    devolvida — só o indicador de que existe.

    Provedor externo (anthropic/openai), o modelo dele e a chave: só o Admin
    Global (403 aos demais, antes de gravar). O admin da escola só salva `local`
    (desligar), o que descarta a chave do provedor externo anterior."""
    _exigir_global_para_externo(dados, usuario)
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
    """Faz UMA chamada mínima ao provedor configurado para validar a chave.
    Qualquer falha do provedor volta como ``{ok: false}``, nunca como 500."""
    try:
        provedor = assistente._provedor_da_escola(db, escola_id)
    except ErroProvedorIA as erro:
        return {"ok": False, "erro": str(erro)[:300]}
    # Só leu: encerra a transação antes da rede, e a conexão do banco volta ao pool.
    db.rollback()
    try:
        resposta = provedor.responder(
            "Você é um verificador de configuração. Responda apenas: OK",
            [{"papel": "usuario", "conteudo": "Está funcionando?"}])
    except ErroProvedorIA as erro:
        return {"ok": False, "erro": str(erro)[:300]}
    except Exception:  # noqa: BLE001 — exceção que o provedor não converteu
        logger.exception("Falha inesperada ao testar o provedor de IA externo")
        return {"ok": False, "erro": _MSG_FALHA_INESPERADA_NO_TESTE}
    return {"ok": True, "provedor": provedor.nome, "resposta": (resposta or "")[:120]}
