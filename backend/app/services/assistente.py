"""Assistente Pedagógico (PRD §155–§172).

Regras inegociáveis:
  * O contexto é montado AQUI, no backend, somente com dados da escola do
    usuário — o isolamento multi-escolas vale também para a IA (§169).
  * O modelo recebe instruções para responder apenas com base nesse
    contexto e recusar qualquer outra coisa.
  * Toda conversa fica registrada em `conversas_ia`/`mensagens_ia`.
  * Se o provedor externo falhar, o provedor local responde — o assistente
    nunca sai do ar por causa de terceiros.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger("constela.ia")

from app.models import (
    Aluno,
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
        .where(Nota.escola_id == escola_id, Nota.ano_letivo == ano)
        .order_by(Nota.posicao)
    ).all()

    linhas_ranking = [
        f"- {nota.posicao}º: {aluno.nome} ({turma.nome}) — geral {nota.nota_geral:.1f}, "
        f"Matific {nota.nota_matific:.1f}, Elefante {nota.nota_elefante:.1f}"
        for nota, aluno, turma in ranking[:15]
    ]
    linhas_alunos = [
        f"- {aluno.nome}: turma {turma.nome}, {nota.posicao}º lugar, nota geral {nota.nota_geral:.1f}"
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
        secao("EVOLUCAO", linhas_evolucao, "- Sem dados de evolução no período."),
        secao("INDICES", linhas_indices, "- Sem índices calculados."),
        secao("ALERTAS", linhas_alertas, "- Nenhum alerta no momento."),
        secao("TURMAS", linhas_turmas, "- Nenhuma turma cadastrada."),
        secao("ALUNOS", linhas_alunos, "- Nenhum aluno com nota."),
    ])


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
        # obter_provedor() pode falhar já na criação (ex.: chave ausente) —
        # por isso fica dentro do try: o assistente nunca sai do ar.
        provedor = obter_provedor()
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
