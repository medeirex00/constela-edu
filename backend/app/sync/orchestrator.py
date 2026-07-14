"""Orquestrador — cola o conector ao PIPELINE DE IMPORTAÇÃO EXISTENTE.

Recebe um ``ArquivoObtido`` (bytes idênticos a um upload manual) e o entrega ao
mesmo caminho ``analisar`` → ``confirmar`` que o humano usa. Assim tudo o que já
funciona é reaproveitado SEM duplicação: parser multi-estratégia, casamento de
nomes, snapshots imutáveis, scoring/rankings, push, Quest e medalhas
(recalculados por ``scoring.recalcular_escola`` dentro do ``confirmar``).

DECISÃO ARQUITETURAL (justificativa): não refatoramos ``confirmar`` — o
orquestrador o CHAMA diretamente, com um "ator" resolvido (o usuário que pediu
a sync manual, ou um admin/coordenador da escola quando é o scheduler). Isso
preserva o pipeline 100% (zero risco de regressão). A verdade de auditoria de
"quem/como disparou" (manual × scheduler) vive em ``SincronizacaoExecucao``.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Usuario
from app.models.academico import Turma
from app.models.escola import Escola
from app.routers import importacoes as imp  # reuso: confirmar, _guardar_temporario
from app.schemas.importacao import ImportacaoConfirm, LinhaConfirmacao
from app.services import importacao as svc
from app.services import perfis_pdf, planilhas, professores
from app.sync.interfaces import ArquivoObtido, Contexto


# Marcador do conteúdo JSON vindo da API interna do Elefante (overall-course-
# report) — roteia direto para o analisador da API, SEM tocar na detecção do
# upload manual (pdf/xlsx/texto), que fica intacta.
CT_ELEFANTE_API = "application/x-elefante-course-report"
# Marcador do JSON vindo da API interna do Matific (Placar da Escola). Roteia
# direto para o analisador da API, sem tocar na detecção do upload manual.
CT_MATIFIC_API = "application/x-matific-leaderboard"


def _parsear(arquivo: ArquivoObtido):
    """Detecta o formato pelos bytes (mesma regra do ``analisar``) e roteia para
    o parser certo. Devolve (analise, tipo)."""
    conteudo = arquivo.conteudo
    plataforma = arquivo.plataforma
    nome = arquivo.nome_arquivo or ""
    # Sync do Elefante pela API interna: o conteúdo é JSON do relatório de turma
    # (não um arquivo binário). Vai direto p/ o analisador da API.
    if arquivo.content_type == CT_ELEFANTE_API:
        import json
        payload = json.loads(conteudo.decode("utf-8"))
        # "texto" é o tipo aceito pelo ImportacaoConfirm (^pdf|texto|xlsx$) para
        # conteúdo não-binário; o arquivamento cai no ramo padrão.
        return svc.analisar_elefante_api(payload, plataforma or "elefante"), "texto"
    # Sync do Matific pela API interna (Placar da Escola): conteúdo é JSON já com
    # o nome completo casado; uma turma por arquivo.
    if arquivo.content_type == CT_MATIFIC_API:
        import json
        payload = json.loads(conteudo.decode("utf-8"))
        return svc.analisar_matific_api(payload), "texto"
    # Mesma detecção do upload manual (fonte única) — nunca divergem.
    tipo = svc.detectar_tipo(conteudo, nome, arquivo.content_type)
    if tipo == "pdf":
        return perfis_pdf.analisar_pdf(conteudo, plataforma, nome_arquivo=nome), "pdf"
    if tipo == "xlsx":
        return planilhas.analisar_planilha(conteudo, plataforma, nome_arquivo=nome), "xlsx"
    return svc.analisar_texto(conteudo.decode("utf-8", errors="replace"), plataforma), "texto"


def _resolver_ator(db: Session, escola_id: int, usuario_id: int | None) -> Usuario | None:
    """Ator da importação: o usuário informado (sync manual) ou o primeiro
    admin/coordenador ATIVO da escola (scheduler). Isolado por ``escola_id``."""
    if usuario_id is not None:
        u = db.get(Usuario, usuario_id)
        if u is not None and u.escola_id == escola_id:
            return u
    return db.execute(
        select(Usuario)
        .where(Usuario.escola_id == escola_id,
               Usuario.cargo.in_(("admin", "coordenador")),
               Usuario.status == "ativo")
        .order_by(Usuario.id)
    ).scalars().first()


def aplicar_arquivo(db: Session, escola: Escola, arquivo: ArquivoObtido, *,
                    usuario_id: int | None, recalcular: bool,
                    contexto: Contexto) -> dict:
    """Interpreta e importa UM arquivo obtido, reusando ``confirmar``.

    Retorna contadores (qtd_alunos, qtd_erros, qtd_turmas, importacao_id, avisos,
    sem_dados) para o histórico da execução."""
    # NÃO logar o nome do arquivo: relatórios individuais trazem o nome do aluno
    # (PII de menor) no nome, e o log é retido (LGPD/§14 — mesma política do
    # upload manual em routers/importacoes.py). Logamos só a plataforma.
    contexto.log("parser", "info", f"Interpretando relatório da {arquivo.plataforma}…")
    analise, tipo = _parsear(arquivo)
    if not analise.linhas:
        contexto.log("parser", "warn",
                     "Nenhuma linha reconhecida no relatório obtido.")
        return {"qtd_alunos": 0, "qtd_erros": 0, "qtd_turmas": 0,
                "importacao_id": None, "avisos": ["Relatório sem linhas."],
                "sem_dados": True}

    contexto.log("validacao", "info",
                 f"{len(analise.linhas)} linha(s); casando nomes…")
    svc.casar_nomes(db, escola.id, analise.linhas)

    # Arquiva a fonte no MESMO diretório temporário do upload manual (o
    # confirmar move para a pasta definitiva — trilha/§15 LGPD idêntica).
    token = imp._guardar_temporario(arquivo.conteudo, tipo if tipo in ("pdf", "xlsx") else "pdf")

    turmas_novas = set()
    linhas: list[LinhaConfirmacao] = []
    for l in analise.linhas:
        corr = l.correspondencia or {}
        # Só auto-vincula match confiante (exato/provável). Não-encontrado cai
        # na turma detectada (mesmo comportamento do auto-import individual).
        confiante = corr.get("status") in ("exato", "provavel")
        aluno_id = corr.get("aluno_id") if confiante else None
        turma_nome = analise.turma_detectada if aluno_id is None else None
        if turma_nome:
            turmas_novas.add(turma_nome)
        linhas.append(LinhaConfirmacao(nome=l.nome, dados=l.dados,
                                       aluno_id=aluno_id,
                                       criar_em_turma_nome=turma_nome))

    confirm = ImportacaoConfirm(
        plataforma=analise.plataforma or arquivo.plataforma,
        formato=analise.formato or arquivo.formato_hint or "resumo",
        tipo=tipo,
        arquivo_token=token,
        arquivo_nome=arquivo.nome_arquivo,
        periodo_inicio=arquivo.periodo_inicio,
        periodo_fim=arquivo.periodo_fim,
        linhas=linhas,
        recalcular=recalcular,
    )

    ator = _resolver_ator(db, escola.id, usuario_id)
    if ator is None:
        raise RuntimeError(
            "A escola não tem admin/coordenador ativo para atribuir a "
            "importação automática.")

    contexto.log("importacao", "info",
                 f"Aplicando {len(linhas)} linha(s) pelo pipeline existente…")
    resultado = imp.confirmar(dados=confirm, escola_id=escola.id,
                              usuario=ator, db=db)
    contexto.log("ranking", "info",
                 f"{resultado.qtd_alunos} aluno(s) atualizado(s)"
                 + (" e notas recalculadas." if recalcular else "."))

    # Cria automaticamente a conta de login dos PROFESSORES da turma detectada
    # (login = NomeSobrenome, senha = Primeiro nome + 123) e vincula o titular
    # para o RBAC. Acessório e idempotente: roda numa transação própria (o
    # confirmar já commitou os alunos) e NUNCA derruba a sync se falhar.
    professor_txt = getattr(analise, "professor_detectado", "") or ""
    turma_txt = getattr(analise, "turma_detectada", "") or ""
    if professor_txt and turma_txt:
        try:
            turma_obj = db.execute(
                select(Turma).where(
                    Turma.escola_id == escola.id,
                    func.lower(Turma.nome) == turma_txt.strip().lower())
            ).scalars().first()
            n_prof = professores.garantir_professores_da_turma(
                db, escola.id, turma_obj, professor_txt)
            db.commit()
            if n_prof:
                contexto.log("professores", "info",
                             f"{n_prof} conta(s) de professor criada(s) "
                             "automaticamente (usuário = NomeSobrenome).")
        except Exception:  # noqa: BLE001 — professor é acessório; aluno é o essencial
            db.rollback()
            contexto.log("professores", "warn",
                         "Não foi possível criar as contas de professor da turma.")
    # Surfaça (SEM PII — só a contagem) linhas não casadas/ignoradas, para o gestor
    # perceber alunos que ficaram de fora em vez de sumirem em silêncio.
    if resultado.avisos:
        contexto.log("validacao", "warn",
                     f"{len(resultado.avisos)} aviso(s): linhas não casadas ou "
                     "ignoradas nesta turma (ver detalhes na importação).")
    return {
        "qtd_alunos": resultado.qtd_alunos,
        "qtd_erros": resultado.qtd_erros,
        "qtd_turmas": len(turmas_novas),
        "importacao_id": resultado.importacao_id,
        "avisos": resultado.avisos,
        "sem_dados": False,
    }
