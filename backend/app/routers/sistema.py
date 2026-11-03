"""Utilidades transversais: pesquisa global (§21), notificações (§22),
simulador de pontuação (§44) e o diagnóstico operacional (admin global)."""
import time
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import escola_autorizada, exigir_admin_global, get_usuario_atual
from app.models import Aluno, Escola, Livro, LogAuditoria, Matricula, Professor, Turma, Usuario
from app.services import dificuldade_livro, permissoes, scoring

router = APIRouter(prefix="/escolas/{escola_id}", tags=["Sistema"])
# Fora do escopo de escola: diagnóstico do PROCESSO (infra), só admin global.
router_diagnostico = APIRouter(prefix="/sistema", tags=["Sistema"])


# --- Diagnóstico operacional (antes público em /api/health) ---------------------

def _bloco_cifra(db: Session) -> dict:
    """Prontidão da cifra em repouso (A1 L3 e §3.2): booleanos e números — nenhum
    valor de chave nem de segredo. ``contagens`` é o mesmo ``--contar`` do
    scripts.recifrar_segredos (None se a leitura falhar: nunca derruba o resto)."""
    import logging

    from app.core.security import diagnostico_cifra
    from app.services import recifragem

    bloco = diagnostico_cifra()
    try:
        contagens = recifragem.contar(db)
        bloco["contagens"] = contagens
        bloco["pendentes"] = recifragem.pendentes(contagens)
    except Exception as exc:  # noqa: BLE001 — diagnóstico nunca vira 500
        db.rollback()
        logging.getLogger("constela").warning(
            "Diagnóstico da cifra: contagem indisponível (%s).", type(exc).__name__)
        bloco["contagens"] = None
        bloco["pendentes"] = None
    return bloco


@router_diagnostico.get("/diagnostico")
def diagnostico(_: Usuario = Depends(exigir_admin_global), db: Session = Depends(get_db)):
    """Estado operacional do processo — o que /api/health expunha a qualquer um.

    O IP/ASN/cidade de SAÍDA do robô e o diagnóstico das páginas de login
    ajudam a investigar o reCAPTCHA do Matific, mas mapeiam a infraestrutura para
    quem quiser atacá-la: ficam só para o admin global. Nenhum segredo sai daqui
    (nem DATABASE_URL, nem tokens: de METRICS_TOKEN só se diz se existe)."""
    from app.core import armazenamento, automacao
    from app.core import observabilidade as obs
    from app.core.database import engine
    from app.core.prontidao import INICIO, prontidao
    from app.sync import scheduler as sync_scheduler

    pronto, motivo, estado = prontidao.avaliar(engine)
    robo = automacao.status()
    return {
        "app": settings.APP_NAME,
        "versao": settings.APP_VERSION,
        "modo": "producao" if settings.em_producao else "dev",
        "uptime_s": round(time.time() - INICIO, 1),
        "banco": "inacessivel" if motivo == "banco_inacessivel" else "ok",
        "schema": {
            "pronto": pronto, "motivo": motivo,
            "revisoes_banco": list(estado.banco) if estado else None,
            "revisoes_codigo": list(estado.codigo) if estado else None,
            "desconhecidas": list(estado.desconhecidas) if estado else None,
        },
        "sentry": obs.sentry_ativo(),
        # true/false = robô abre o Chromium; null = ainda verificando no boot ou, com
        # AUTOMACAO_VERIFICAR_NO_BOOT=false (testes e E2E), verificação desligada: aí
        # fica null para sempre e o automacao_detalhe diz que foi desligada.
        "automacao_navegador": robo["navegador"],
        "automacao_detalhe": robo.get("detalhe"),
        # Diagnóstico (sem credenciais) das páginas de login das plataformas.
        "login_paginas": robo.get("login"),
        # IP/ASN de saída do robô (evidência: datacenter x residencial).
        "egress": robo.get("egress"),
        # Agendador de sincronização: habilitado (env) e efetivamente rodando.
        # Se habilitado=true e ativo=false, o processo precisa ser reiniciado.
        "scheduler_sync": {"habilitado": settings.SYNC_SCHEDULER_ENABLED,
                           "ativo": sync_scheduler.ativo()},
        "metricas": {"habilitadas": settings.METRICS_ENABLED,
                     "token_configurado": bool(settings.METRICS_TOKEN.strip()),
                     "publico_sem_token": settings.METRICS_PUBLICO and not settings.em_producao},
        "docs_habilitados": settings.DOCS_HABILITADOS,
        "armazenamento": armazenamento.diagnostico(settings),
        # DEK ativa/longa/distinta, chaves anteriores ainda configuradas, SECRET_KEY
        # efêmera e as cifras por chave (primaria/anterior/ilegivel/vazio).
        "cifra": _bloco_cifra(db),
    }


# --- Pesquisa global (PRD §21) --------------------------------------------------

def _escapar_like(termo: str) -> str:
    """Neutraliza os curingas do LIKE (%, _) e o próprio escape."""
    return termo.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/pesquisa")
def pesquisa_global(
    q: str = Query(min_length=2, max_length=100),
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Busca por alunos, turmas, professores e livros — respeitando o papel.

    Professor vê apenas os alunos das turmas designadas a ele; itens de
    gestão (cadastro de professores, catálogo de livros) só aparecem para
    quem tem acesso total. Assim o resultado da busca nunca leva ninguém a
    um dado ou tela que o cargo não poderia abrir."""
    padrao = f"%{_escapar_like(q.strip())}%"
    escola = db.get(Escola, escola_id)
    ano = escola.ano_letivo_ativo if escola else 0
    permitidas = permissoes.turmas_permitidas(db, escola_id, usuario)
    gestor = permitidas is None

    # Alunos com a turma do ano ativo (desambigua homônimos: "3 Isabellas").
    consulta_alunos = (
        select(Aluno.id, Aluno.nome, Turma.nome)
        .outerjoin(Matricula, (Matricula.aluno_id == Aluno.id)
                   & (Matricula.ano_letivo == ano))
        .outerjoin(Turma, Turma.id == Matricula.turma_id)
        .where(Aluno.escola_id == escola_id, Aluno.status == "ativo",
               Aluno.nome.ilike(padrao, escape="\\"))
        .order_by(Aluno.nome).limit(10)
    )
    if not gestor:  # professor: só alunos das turmas dele
        consulta_alunos = consulta_alunos.where(Matricula.turma_id.in_(permitidas))
    alunos = db.execute(consulta_alunos).all()

    turmas: list = []
    professores: list = []
    livros: list = []
    if gestor:
        turmas = db.execute(
            select(Turma).where(Turma.escola_id == escola_id,
                                Turma.nome.ilike(padrao, escape="\\"))
            .order_by(Turma.nome).limit(5)
        ).scalars().all()
        professores = db.execute(
            select(Professor).where(Professor.escola_id == escola_id,
                                    Professor.nome.ilike(padrao, escape="\\"))
            .order_by(Professor.nome).limit(5)
        ).scalars().all()
        livros = db.execute(
            select(Livro).where(
                Livro.escola_id == escola_id,
                Livro.titulo.ilike(padrao, escape="\\")
                | Livro.autor.ilike(padrao, escape="\\"))
            .order_by(Livro.titulo).limit(5)
        ).scalars().all()

    return {
        "alunos": [{"id": aid, "nome": nome, "turma": turma}
                   for aid, nome, turma in alunos],
        "turmas": [{"id": t.id, "nome": t.nome} for t in turmas],
        "professores": [{"id": p.id, "nome": p.nome} for p in professores],
        "livros": [{"id": l.id, "nome": l.titulo} for l in livros],
    }


# --- Notificações (PRD §22) ----------------------------------------------------

_TEXTOS = {
    "importacao.concluida": "📥 Nova importação de dados concluída",
    "pesos.alterados": "⚖️ Pesos do cálculo foram alterados",
    "referencias.alteradas": "🎚️ Referências de normalização alteradas",
    "dificuldade.alterada": "📚 Pontuação de dificuldade por série alterada",
    "notas.recalculadas": "🧮 Notas recalculadas",
    "backup.gerado": "💾 Backup gerado",
    "backup.restaurado": "♻️ Backup restaurado",
    "usuario.criado": "👤 Novo usuário criado",
    "matific.editado": "✏️ Dados da Matific editados manualmente",
    "elefante.editado": "✏️ Dados do Elefante Letrado editados manualmente",
    "relatorio.exportado": "📄 Relatório exportado",
    "certificado.emitido": "🎓 Certificado emitido",
    "aluno.criado": "🧑‍🎓 Novo aluno cadastrado",
}


@router.get("/notificacoes")
def notificacoes(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Últimos acontecimentos relevantes da escola, derivados da auditoria."""
    permissoes.negar_restrito(db, escola_id, usuario)  # gestão: só admin/coord/global
    eventos = db.execute(
        select(LogAuditoria, Usuario.nome)
        .outerjoin(Usuario, LogAuditoria.usuario_id == Usuario.id)
        .where(LogAuditoria.escola_id == escola_id,
               LogAuditoria.acao.in_(list(_TEXTOS)))
        .order_by(LogAuditoria.id.desc())
        .limit(15)
    ).all()
    return [
        {
            "id": evento.id,
            "texto": _TEXTOS[evento.acao],
            "autor": autor,
            "data": evento.created_at,
        }
        for evento, autor in eventos
    ]


# --- Simulador de pontuação (PRD §44) -------------------------------------------

class SimulacaoIn(BaseModel):
    ano_escolar: str = Field(min_length=1, max_length=30)
    atividades: int = Field(default=0, ge=0)
    # Escala do MATIFIC (0–5, a mesma do snapshot importado). Aceitar até 100
    # deixava simular um aluno impossível — e a nota sairia de uma régua que
    # nenhum aluno real alcança.
    pontuacao_media: float = Field(default=0, ge=0, le=5)
    estrelas: int = Field(default=0, ge=0)
    livros_por_nivel: dict[str, int] = {}
    tempo_leitura_min: int = Field(default=0, ge=0)
    questoes_tentativas: int = Field(default=0, ge=0)
    questoes_acertos: int = Field(default=0, ge=0)


@router.post("/simulador")
def simular(
    dados: SimulacaoIn,
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Calcula a nota de um aluno hipotético com as regras que o MOTOR usa de fato.

    Nada é gravado: serve para testar o efeito de pesos e referências (§44).

    Cada insumo vem da MESMA fonte que ``scoring.recalcular_escola`` consulta,
    respeitando o perfil de scoring da escola — no perfil institucional (padrão)
    a configuração local de pesos/referências/faixas é IGNORADA pelo motor, então
    o simulador também a ignora; só no perfil ``personalizado`` ela vale:
      * pesos       → ``scoring.pesos_efetivos`` (todos os namespaces);
      * referências → ``scoring.contexto_normalizacao``;
      * dificuldade → ``dificuldade_livro.regra_da_escola``.
    Sem isto o simulador lia a config local enquanto a nota oficial (premiação,
    ranking) saía da régua institucional — o mesmo aluno com dois números.
    """
    permissoes.negar_restrito(db, escola_id, usuario)  # config do motor: só gestão
    perfil = "personalizado" if scoring._scoring_personalizado(db, escola_id) else "institucional"
    refs, modo, k_vol = scoring.contexto_normalizacao(db, escola_id)
    if not refs:
        refs = {chave: 0 for chave in scoring.CHAVES_REFERENCIA}

    snap_m = SimpleNamespace(
        atividades=dados.atividades,
        pontuacao_media=dados.pontuacao_media,
        estrelas=dados.estrelas,
    )
    livros_por_nivel = {c.upper(): int(q) for c, q in dados.livros_por_nivel.items()}
    snap_e = SimpleNamespace(
        livros_unicos=sum(livros_por_nivel.values()),
        tempo_leitura_min=dados.tempo_leitura_min,
        questoes_tentativas=dados.questoes_tentativas,
        questoes_acertos=dados.questoes_acertos,
    )
    # Fonte única de dificuldade (aluno hipotético: sem leituras itemizadas, cada
    # livro vale o típico do nível × série).
    pontos_dif = dificuldade_livro.regra_da_escola(db, escola_id).pontos_aluno(
        livros_por_nivel, dados.ano_escolar)

    # Pesos EFETIVOS (fonte única): institucionais fixos no perfil padrão, config
    # local só no perfil personalizado — exatamente o que o recálculo usa.
    p_matific, pct_matific = scoring.pesos_efetivos(db, escola_id, "pesos.matific")
    p_elefante, pct_elefante = scoring.pesos_efetivos(db, escola_id, "pesos.elefante")
    p_questoes, pct_questoes = scoring.pesos_efetivos(db, escola_id, "pesos.questoes")
    p_geral, _ = scoring.pesos_efetivos(db, escola_id, "pesos.geral")
    # Mesma regra do recálculo (scoring.recalcular_escola): a explicação da Nota
    # Geral é DERIVADA dos pesos efetivamente usados, senão o simulador mostra
    # uma conta que não fecha numa rede de um módulo só. O aluno HIPOTÉTICO tem
    # as duas dimensões informadas (quem simula digita os dois blocos), então a
    # renormalização por dimensão disponível é no-op aqui — mas passa pela mesma
    # função, para o simulador nunca voltar a ter uma cópia própria da fórmula.
    p_geral = scoring.pesos_geral_do_aluno(p_geral, {"matific", "elefante"})
    pct_geral = {chave: round(fracao * 100, 2) for chave, fracao in p_geral.items()
                 if fracao > 0}

    nota_m, linhas_m = scoring.calcular_matific(snap_m, refs, p_matific, pct_matific, k_vol)
    nota_e, linhas_e, det_q = scoring.calcular_elefante(
        snap_e, pontos_dif, refs, p_elefante, pct_elefante, p_questoes, pct_questoes, k_vol,
    )
    nota_geral = round(
        nota_m * p_geral.get("matific", 0) + nota_e * p_geral.get("elefante", 0), 2
    )
    return {
        # Qual régua produziu esta simulação: "institucional" (a da rede, fixa)
        # ou "personalizado" (config local autorizada pelo Admin Global).
        "perfil": perfil,
        "modo_normalizacao": modo,
        "referencias": refs,
        "pontos_dificuldade": pontos_dif,
        "matific": {"indicadores": linhas_m, "nota": nota_m},
        "elefante": {"indicadores": linhas_e, "questoes": det_q, "nota": nota_e},
        "geral": {"pesos": pct_geral, "nota": nota_geral},
    }
