"""Utilidades transversais: pesquisa global (§21), notificações (§22) e
simulador de pontuação (§44)."""
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import escola_autorizada, get_usuario_atual
from app.models import Aluno, Escola, Livro, LogAuditoria, Matricula, Professor, Turma, Usuario
from app.services import permissoes, scoring

router = APIRouter(prefix="/escolas/{escola_id}", tags=["Sistema"])


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
    pontuacao_media: float = Field(default=0, ge=0, le=100)
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
    """Calcula a nota de um aluno hipotético com as regras ATUAIS da escola.

    Nada é gravado: serve para testar o efeito de pesos e referências (§44).
    """
    permissoes.negar_restrito(db, escola_id, usuario)  # config do motor: só gestão
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
    mapa = scoring._mapa_dificuldade(db, escola_id)
    pontos_dif = scoring._pontos_dificuldade(livros_por_nivel, dados.ano_escolar, mapa)

    p_matific = scoring.obter_pesos(db, escola_id, "pesos.matific")
    p_elefante = scoring.obter_pesos(db, escola_id, "pesos.elefante")
    p_questoes = scoring.obter_pesos(db, escola_id, "pesos.questoes")
    p_geral = scoring.obter_pesos(db, escola_id, "pesos.geral")
    pct_matific = scoring.obter_pesos_brutos(db, escola_id, "pesos.matific")
    pct_elefante = scoring.obter_pesos_brutos(db, escola_id, "pesos.elefante")
    pct_questoes = scoring.obter_pesos_brutos(db, escola_id, "pesos.questoes")
    pct_geral = scoring.obter_pesos_brutos(db, escola_id, "pesos.geral")

    nota_m, linhas_m = scoring.calcular_matific(snap_m, refs, p_matific, pct_matific, k_vol)
    nota_e, linhas_e, det_q = scoring.calcular_elefante(
        snap_e, pontos_dif, refs, p_elefante, pct_elefante, p_questoes, pct_questoes, k_vol,
    )
    nota_geral = round(
        nota_m * p_geral.get("matific", 0) + nota_e * p_geral.get("elefante", 0), 2
    )
    return {
        "modo_normalizacao": modo,
        "referencias": refs,
        "pontos_dificuldade": pontos_dif,
        "matific": {"indicadores": linhas_m, "nota": nota_m},
        "elefante": {"indicadores": linhas_e, "questoes": det_q, "nota": nota_e},
        "geral": {"pesos": pct_geral, "nota": nota_geral},
    }
