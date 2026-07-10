"""Assistente Pedagógico (PRD §155–§172).

Regras inegociáveis:
  * O contexto é montado AQUI, no backend, somente com dados da escola do
    usuário — o isolamento multi-escolas vale também para a IA (§169).
  * O modelo recebe instruções para responder apenas com base nesse
    contexto e recusar qualquer outra coisa.
  * Toda conversa fica registrada em `conversas_ia`/`mensagens_ia`.
  * Se o provedor externo falhar, o provedor local responde — o assistente
    nunca sai do ar por causa de terceiros.

Provedor externo e LGPD (dados de crianças — decisão documentada):
  * O provedor PADRÃO é `local`: determinístico, sem rede, sem chave. Por
    padrão NENHUM dado de aluno sai da infraestrutura.
  * Um provedor externo (Anthropic/OpenAI) só é usado quando a escola o
    configura explicitamente com uma chave própria (opt-in por escola).
  * Minimização de dados: mesmo nesse opt-in, NOMES REAIS de alunos NUNCA são
    enviados ao provedor externo. O contexto e a conversa são pseudonimizados
    (nome -> "Aluno NNN") antes de sair; a resposta é reidentificada aqui, no
    backend. O provedor externo vê apenas rótulos, turmas e notas.
  * A pseudonimização usa casamento EXATO de nome (fronteira de palavra), sem
    heurística de NER. Limitação conhecida e aceita: se o usuário digitar
    apenas um fragmento do nome na pergunta (ex.: só o primeiro nome), esse
    fragmento não é trocado por token — some da cobertura. É o mesmo requisito
    do modo local (que também casa pelo nome como aparece no contexto).
"""
from __future__ import annotations

import logging
import re

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

logger = logging.getLogger("constela.ia")

from app.core.security import cifrar_segredo, decifrar_segredo
from app.models import (
    Aluno,
    Configuracao,
    ConversaIA,
    Escola,
    Matricula,
    MensagemIA,
    Nota,
    Turma,
)
from app.services import evolucao, insights
from app.services.ia import ErroProvedorIA, obter_provedor
from app.services.ia.provedores import LocalProvedor

PROVEDORES_VALIDOS = ("local", "anthropic", "openai")


def _config_row(db: Session, escola_id: int) -> Configuracao | None:
    return db.execute(
        select(Configuracao).where(Configuracao.escola_id == escola_id,
                                   Configuracao.namespace == "assistente",
                                   Configuracao.chave == "valores")
    ).scalar_one_or_none()


def config_assistente(db: Session, escola_id: int) -> dict:
    """Configuração do assistente salva pela interface (sem expor a chave).
    Escola sem configuração própria espelha o AMBIENTE — o que o status mostra
    é o que de fato responde."""
    from app.core.config import settings

    row = _config_row(db, escola_id)
    valores = dict(row.valor or {}) if row else {}
    if not valores.get("provedor"):
        return {
            "provedor": settings.AI_PROVIDER.strip().lower() or "local",
            "modelo": settings.AI_MODEL or "",
            "chave_definida": bool(settings.AI_API_KEY),
        }
    return {
        "provedor": valores["provedor"],
        "modelo": valores.get("modelo") or "",
        "chave_definida": bool(valores.get("api_key_cifrada")),
    }


def salvar_config_assistente(db: Session, escola_id: int, provedor: str,
                             api_key: str | None, modelo: str | None) -> dict:
    """Grava provedor/modelo e a chave de API CIFRADA (Fernet na SECRET_KEY).
    `api_key` vazio mantém a chave já salva DO MESMO provedor; ao trocar de
    provedor a chave antiga é descartada (a chave de um fornecedor nunca pode
    ser enviada a outro). Levanta ValueError quando falta a chave.
    NÃO faz commit — quem chama registra a auditoria e commita junto."""
    row = _config_row(db, escola_id)
    valores = dict(row.valor or {}) if row else {}
    api_key = (api_key or "").strip()
    provedor_anterior = valores.get("provedor") or "local"
    if provedor != provedor_anterior and not api_key:
        valores.pop("api_key_cifrada", None)
    if provedor != "local" and not api_key and not valores.get("api_key_cifrada"):
        raise ValueError("Informe a chave de API do provedor escolhido.")

    valores["provedor"] = provedor
    valores["modelo"] = (modelo or "").strip()
    if api_key:
        valores["api_key_cifrada"] = cifrar_segredo(api_key)
    if row is None:
        row = Configuracao(escola_id=escola_id, namespace="assistente",
                           chave="valores", valor=valores)
        db.add(row)
    else:
        row.valor = valores
    db.flush()
    return {
        "provedor": provedor,
        "modelo": valores["modelo"],
        "chave_definida": bool(valores.get("api_key_cifrada")),
    }


def _provedor_da_escola(db: Session, escola_id: int):
    """Provedor conforme a configuração da escola; sem ela, o do ambiente."""
    row = _config_row(db, escola_id)
    valores = dict(row.valor or {}) if row else {}
    if not valores.get("provedor"):
        return obter_provedor()
    return obter_provedor(
        provedor=valores["provedor"],
        api_key=decifrar_segredo(valores.get("api_key_cifrada")),
        modelo=valores.get("modelo") or None,
    )

MAX_MENSAGENS_CONTEXTO = 12  # últimas mensagens da conversa enviadas ao modelo

INSTRUCOES = """Você é o Assistente Pedagógico do Constela Edu (sistema de
gestão e premiação escolar) de uma escola brasileira de ensino fundamental.

REGRAS OBRIGATÓRIAS:
1. Responda SOMENTE com base nos dados do sistema apresentados abaixo.
   Eles são a única fonte de verdade. Se a informação não estiver lá,
   diga claramente que não há dados suficientes no sistema.
2. Nunca invente números, nomes ou fatos. Nunca use conhecimento externo
   sobre alunos ou escolas.
3. Recuse com educação perguntas fora do contexto pedagógico desta escola.
4. Responda em português do Brasil, em tom profissional e acolhedor,
   pensado para professores e coordenadores.
5. Ao citar um dado, seja específico (nome, número, posição).

DADOS DO SISTEMA (fonte única de verdade):
"""


def montar_contexto(db: Session, escola_id: int) -> str:
    """Fotografia textual dos dados da escola — tudo que a IA pode "ver"."""
    escola = db.get(Escola, escola_id)
    ano = escola.ano_letivo_ativo

    ranking = db.execute(
        select(Nota, Aluno, Turma)
        .join(Aluno, Nota.aluno_id == Aluno.id)
        .join(Matricula, (Matricula.aluno_id == Aluno.id) & (Matricula.ano_letivo == ano))
        .join(Turma, Matricula.turma_id == Turma.id)
        # Aluno.status: aluno arquivado/inativo NUNCA entra no contexto da IA —
        # sua Nota órfã (arquivar não a apaga) não pode reintroduzir o nome dele,
        # inclusive na ida ao provedor externo. Mesmo filtro do ranking/painel.
        .where(Nota.escola_id == escola_id, Nota.ano_letivo == ano,
               Aluno.status == "ativo")
        .order_by(Nota.posicao)
    ).all()

    linhas_ranking = [
        f"- {nota.posicao}º: {aluno.nome} ({turma.nome}) — geral {nota.nota_geral:.1f}, "
        f"Matific {nota.nota_matific:.1f}, Elefante {nota.nota_elefante:.1f}"
        for nota, aluno, turma in ranking[:15]
    ]
    # Pódios por PLATAFORMA — para perguntas "melhores do Matific/Elefante".
    def podio(metrica) -> list[str]:
        ordenado = sorted(ranking, key=lambda r: metrica(r[0]), reverse=True)
        return [
            f"- {i}º: {aluno.nome} ({turma.nome}) — nota {metrica(nota):.1f}"
            for i, (nota, aluno, turma) in enumerate(ordenado[:10], start=1)
        ]
    linhas_matific = podio(lambda n: n.nota_matific)
    linhas_elefante = podio(lambda n: n.nota_elefante)
    linhas_alunos = [
        f"- {aluno.nome}: turma {turma.nome}, {nota.posicao}º lugar, "
        f"geral {nota.nota_geral:.1f}, Matific {nota.nota_matific:.1f}, "
        f"Elefante {nota.nota_elefante:.1f}"
        for nota, aluno, turma in ranking
    ]

    itens_evolucao = evolucao.ranking_evolucao(db, escola_id, dias=30)[:10]
    linhas_evolucao = [
        f"- {item.posicao}º: {item.nome} ({item.turma}) — evolução {item.nota_evolucao:.1f} "
        f"(+{item.ganhos['atividades']:.0f} atividades, +{item.ganhos['livros']:.0f} livros)"
        for item in itens_evolucao
    ]

    indices = insights.indices_da_escola(db, escola_id)
    linhas_indices = [
        f"- {item['nome']} ({item['turma']}): engajamento {item['engajamento']}, "
        f"evolução {item['evolucao']}, persistência {item['persistencia']}"
        for item in indices
    ]

    alertas = insights.alertas_da_escola(db, escola_id)
    linhas_alertas = [f"- [{alerta['gravidade']}] {alerta['texto']}" for alerta in alertas]

    resumo_escola = evolucao.resumo_escola(db, escola_id)
    linhas_turmas = [
        f"- {t['turma']['nome']} ({t['turma']['ano_escolar']}): {t['total_alunos']} alunos, "
        f"média geral {t['media_geral']:.1f}, {t['indicadores']['livros_unicos']} livros lidos"
        for t in resumo_escola["turmas"] if t
    ]

    def secao(nome: str, linhas: list[str], vazio: str) -> str:
        corpo = "\n".join(linhas) if linhas else vazio
        return f"### {nome}\n{corpo}\n"

    return "\n".join([
        secao("RESUMO", [
            f"- Escola: {escola.nome} (ano letivo {ano})",
            f"- Alunos com nota: {len(ranking)}",
            f"- Turmas: {len(resumo_escola['turmas'])}",
            f"- Alertas ativos: {len(alertas)}",
        ], "- Sem dados."),
        secao("RANKING", linhas_ranking, "- Nenhuma nota calculada ainda."),
        secao("RANKING_MATIFIC", linhas_matific, "- Nenhuma nota calculada ainda."),
        secao("RANKING_ELEFANTE", linhas_elefante, "- Nenhuma nota calculada ainda."),
        secao("EVOLUCAO", linhas_evolucao, "- Sem dados de evolução no período."),
        secao("INDICES", linhas_indices, "- Sem índices calculados."),
        secao("ALERTAS", linhas_alertas, "- Nenhum alerta no momento."),
        secao("TURMAS", linhas_turmas, "- Nenhuma turma cadastrada."),
        secao("ALUNOS", linhas_alunos, "- Nenhum aluno com nota."),
    ])


# --- Pseudonimização para provedores externos (LGPD) --------------------------

# Provedores que enviam o contexto para fora da infraestrutura. Só para eles a
# pseudonimização é aplicada; o `local` roda no próprio backend com nomes reais.
_PROVEDORES_EXTERNOS = ("anthropic", "openai")

_NOTA_PSEUDONIMO = (
    "\n\nIMPORTANTE: cada aluno aparece por um identificador fixo "
    '(ex.: "Aluno 007"). Refira-se aos alunos EXATAMENTE por esse identificador, '
    "sem alterá-lo, traduzi-lo ou inventar nomes."
)


def _mapa_pseudonimos(db: Session, escola_id: int) -> dict[str, str]:
    """{nome_real: "Aluno NNN"} para TODOS os alunos da escola (QUALQUER status).

    Rede de segurança: o mapa cobre até arquivados/inativos de propósito — se
    algum nome escapar por qualquer seção do contexto, ele ainda é trocado por
    token antes de sair para o provedor externo (nunca vaza nome real).
    Ordem estável (por nome) e largura fixa com zeros à esquerda: nenhum token é
    prefixo de outro, então a reidentificação por substituição direta é exata."""
    nomes = db.execute(
        select(Aluno.nome).where(Aluno.escola_id == escola_id).order_by(Aluno.nome)
    ).scalars().all()
    largura = max(2, len(str(len(nomes) or 1)))
    return {nome: f"Aluno {i:0{largura}d}" for i, nome in enumerate(nomes, start=1)}


def _pseudonimizar(texto: str, mapa: dict[str, str]) -> str:
    """Troca cada nome real pelo token. Nome mais longo primeiro (não trocar
    "João" dentro de "João Pedro"), fronteira de palavra e SEM diferenciar
    maiúsculas/minúsculas (re.IGNORECASE) — o nome digitado pela pessoa em caixa
    diferente ("joão pereira") também é trocado antes de ir ao provedor externo.
    """
    for nome in sorted(mapa, key=len, reverse=True):
        texto = re.sub(rf"\b{re.escape(nome)}\b", mapa[nome], texto,
                       flags=re.IGNORECASE)
    return texto


def _reidentificar(texto: str, mapa: dict[str, str]) -> str:
    """Volta token -> nome real na resposta. Tokens têm largura fixa (nenhum é
    prefixo de outro), então a substituição direta é segura."""
    for nome, token in mapa.items():
        texto = texto.replace(token, nome)
    return texto


def perguntar(db: Session, escola_id: int, usuario_id: int,
              pergunta: str, conversa_id: int | None = None) -> dict:
    """Fluxo completo: contexto → provedor → registro da conversa."""
    if conversa_id is not None:
        conversa = db.get(ConversaIA, conversa_id)
        if conversa is None or conversa.escola_id != escola_id \
                or conversa.usuario_id != usuario_id:
            raise ValueError("Conversa não encontrada.")
    else:
        titulo = pergunta.strip()[:80] or "Nova conversa"
        conversa = ConversaIA(escola_id=escola_id, usuario_id=usuario_id, titulo=titulo)
        db.add(conversa)
        db.flush()

    historico = db.execute(
        select(MensagemIA).where(MensagemIA.conversa_id == conversa.id)
        .order_by(MensagemIA.id.desc()).limit(MAX_MENSAGENS_CONTEXTO)
    ).scalars().all()
    mensagens = [
        {"papel": m.papel, "conteudo": m.conteudo} for m in reversed(historico)
    ]
    mensagens.append({"papel": "usuario", "conteudo": pergunta})

    sistema = INSTRUCOES + montar_contexto(db, escola_id)

    try:
        # A criação pode falhar (ex.: chave ausente/errada) — por isso fica
        # dentro do try: o assistente nunca sai do ar.
        provedor = _provedor_da_escola(db, escola_id)
        if provedor.nome in _PROVEDORES_EXTERNOS:
            # LGPD: nomes reais de crianças NUNCA saem para provedor externo.
            # Pseudonimiza contexto + conversa; reidentifica a resposta aqui.
            mapa = _mapa_pseudonimos(db, escola_id)
            sistema_env = _pseudonimizar(sistema, mapa) + _NOTA_PSEUDONIMO
            mensagens_env = [
                {"papel": m["papel"], "conteudo": _pseudonimizar(m["conteudo"], mapa)}
                for m in mensagens
            ]
            resposta = _reidentificar(provedor.responder(sistema_env, mensagens_env), mapa)
        else:
            resposta = provedor.responder(sistema, mensagens)
        provedor_usado = provedor.nome
    except ErroProvedorIA as erro:
        logger.warning("Provedor de IA indisponível; usando modo local: %s",
                       erro, exc_info=True)
        resposta = LocalProvedor().responder(sistema, mensagens)
        provedor_usado = "local (contingência)"

    conversa.provedor = provedor_usado
    db.add(MensagemIA(conversa_id=conversa.id, papel="usuario", conteudo=pergunta))
    db.add(MensagemIA(conversa_id=conversa.id, papel="assistente", conteudo=resposta))
    db.commit()

    return {
        "conversa_id": conversa.id,
        "titulo": conversa.titulo,
        "provedor": provedor_usado,
        "resposta": resposta,
    }


def purgar_conversas_ia_expiradas(db: Session, dias: int | None = None) -> int:
    """Retenção LGPD (direito ao esquecimento / minimização): apaga conversas do
    assistente com created_at mais antigo que `dias` (padrão
    settings.IA_RETENCAO_DIAS). A cascata (migração 0003) remove as mensagens
    junto. Idempotente. Devolve o nº de conversas apagadas."""
    from app.core.config import settings
    dias = settings.IA_RETENCAO_DIAS if dias is None else dias
    # created_at é gravado em UTC mas a coluna DateTime (sem tz) devolve NAIVE do
    # banco (SQLite/Postgres); usa corte NAIVE em UTC para casar a comparação.
    # synchronize_session=False: DELETE puro em SQL (a cascata 0003 apaga as
    # mensagens), sem avaliar a condição contra objetos em memória.
    corte = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=dias)
    resultado = db.execute(
        delete(ConversaIA)
        .where(ConversaIA.created_at < corte)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return resultado.rowcount or 0
