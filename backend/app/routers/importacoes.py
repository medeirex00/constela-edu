"""Importação de relatórios das plataformas (PRD §15–§16, §50–§52).

Fluxo em duas etapas: `analisar` devolve a prévia (nada é gravado) e
`confirmar` grava somente as linhas aprovadas pelo usuário, registrando
tudo em `importacoes` e guardando o arquivo original em /uploads (§15).
"""
import shutil
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import escola_autorizada, exigir_papeis, get_usuario_atual
from app.models import (
    Aluno,
    Importacao,
    Leitura,
    Livro,
    Matricula,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
    Usuario,
)
from app.schemas import AnaliseOut, ImportacaoConfirm, ImportacaoOut, ImportacaoResultadoOut
from app.services import importacao as svc
from app.services import scoring
from app.services.audit import registrar

router = APIRouter(prefix="/escolas/{escola_id}/importacoes", tags=["Importações"])

TAMANHO_MAXIMO = 10 * 1024 * 1024  # 10 MB


def _snapshot_atual(db: Session, escola_id: int, aluno_id: int, modelo):
    return db.execute(
        select(modelo)
        .where(modelo.escola_id == escola_id, modelo.aluno_id == aluno_id)
        .order_by(modelo.id.desc())
        .limit(1)
    ).scalar_one_or_none()


# --- Etapa 1: prévia (PRD §51) ------------------------------------------------

@router.post("/analisar", response_model=AnaliseOut)
async def analisar(
    escola_id: int = Depends(escola_autorizada),
    arquivo: UploadFile | None = File(default=None),
    texto: str | None = Form(default=None),
    plataforma: str | None = Form(default=None),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    if plataforma not in (None, "", "matific", "elefante"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Plataforma desconhecida.")
    plataforma = plataforma or None

    arquivo_token = None
    arquivo_nome = None
    if arquivo is not None:
        conteudo = await arquivo.read()
        if len(conteudo) > TAMANHO_MAXIMO:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                                "Arquivo acima de 10 MB.")
        arquivo_nome = arquivo.filename or "relatorio"
        eh_pdf = arquivo_nome.lower().endswith(".pdf") or arquivo.content_type == "application/pdf"
        if eh_pdf:
            try:
                texto = svc.extrair_texto_pdf(conteudo)
            except Exception:
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    "Não foi possível ler o PDF. O arquivo está íntegro?")
            # Guarda o original em /uploads/temporarios até a confirmação (§15)
            arquivo_token = f"{uuid.uuid4().hex}.pdf"
            destino = settings.UPLOADS_DIR / "temporarios" / arquivo_token
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(conteudo)
            tipo = "pdf"
        else:
            texto = conteudo.decode("utf-8", errors="replace")
            tipo = "texto"
    elif texto and texto.strip():
        tipo = "texto"
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Envie um arquivo PDF ou cole o texto do relatório.")

    analise = svc.analisar_texto(texto, plataforma)
    if analise.linhas:
        svc.casar_nomes(db, escola_id, analise.linhas)

    return AnaliseOut(
        plataforma=analise.plataforma,
        formato=analise.formato,
        tipo=tipo,
        arquivo_token=arquivo_token,
        arquivo_nome=arquivo_nome,
        total_linhas=len(analise.linhas),
        total_erros=sum(1 for l in analise.linhas if l.erros) + len(analise.erros_gerais),
        erros_gerais=analise.erros_gerais,
        linhas=[
            {
                "numero": l.numero,
                "nome": l.nome,
                "dados": l.dados,
                "erros": l.erros,
                "avisos": l.avisos,
                "correspondencia": l.correspondencia,
            }
            for l in analise.linhas
        ],
    )


# --- Etapa 2: confirmação -----------------------------------------------------

def _resolver_aluno(db: Session, escola_id: int, ano: int, linha, avisos: list[str]) -> Aluno | None:
    if linha.aluno_id is not None:
        aluno = db.get(Aluno, linha.aluno_id)
        if aluno is None or aluno.escola_id != escola_id:
            avisos.append(f"Linha “{linha.nome}”: aluno não pertence a esta escola — ignorada.")
            return None
        return aluno
    if linha.criar_em_turma_id is not None:
        turma = db.get(Turma, linha.criar_em_turma_id)
        if turma is None or turma.escola_id != escola_id:
            avisos.append(f"Linha “{linha.nome}”: turma inválida — ignorada.")
            return None
        aluno = Aluno(escola_id=escola_id, nome=linha.nome.strip())
        db.add(aluno)
        db.flush()
        db.add(Matricula(escola_id=escola_id, aluno_id=aluno.id,
                         turma_id=turma.id, ano_letivo=ano))
        return aluno
    avisos.append(f"Linha “{linha.nome}”: sem aluno vinculado — ignorada.")
    return None


def _importar_matific(db, escola_id, importacao, aluno, dados, data_referencia):
    db.add(SnapshotMatific(
        escola_id=escola_id, aluno_id=aluno.id, importacao_id=importacao.id,
        data_referencia=data_referencia,
        atividades=int(dados.get("atividades", 0)),
        estrelas=int(dados.get("estrelas", 0)),
        pontuacao_media=float(dados.get("pontuacao_media", 0.0)),
    ))


def _importar_elefante_resumo(db, escola_id, importacao, aluno, dados, data_referencia):
    anterior = _snapshot_atual(db, escola_id, aluno.id, SnapshotElefante)
    por_nivel = dados.get("livros_por_nivel")
    if por_nivel is None:
        # Relatório sem a coluna de níveis: preserva a distribuição conhecida
        por_nivel = anterior.livros_por_nivel if anterior else {}
    livros = dados.get("livros_unicos")
    if livros is None:
        livros = sum(por_nivel.values()) if por_nivel else (anterior.livros_unicos if anterior else 0)
    db.add(SnapshotElefante(
        escola_id=escola_id, aluno_id=aluno.id, importacao_id=importacao.id,
        data_referencia=data_referencia,
        livros_unicos=int(livros),
        tempo_leitura_min=int(dados.get("tempo_leitura_min",
                                        anterior.tempo_leitura_min if anterior else 0)),
        questoes_tentativas=int(dados.get("questoes_tentativas",
                                          anterior.questoes_tentativas if anterior else 0)),
        questoes_acertos=int(dados.get("questoes_acertos",
                                       anterior.questoes_acertos if anterior else 0)),
        livros_por_nivel=por_nivel,
    ))


def _importar_elefante_leituras(db, escola_id, importacao, aluno, linhas, data_referencia, avisos):
    """Formato "uma linha por livro concluído": registra leituras únicas (§35)."""
    for linha in linhas:
        titulo = str(linha.dados.get("livro", "")).strip()
        nivel = str(linha.dados.get("nivel", "")).strip().upper()
        if not titulo:
            avisos.append(f"Linha {linha.nome}: livro sem título — ignorada.")
            continue
        livro = db.execute(
            select(Livro).where(Livro.escola_id == escola_id,
                                Livro.titulo.ilike(titulo))
        ).scalar_one_or_none()
        if livro is None:
            if not nivel:
                avisos.append(f"Livro “{titulo}” é novo e veio sem nível — ignorado.")
                continue
            livro = Livro(escola_id=escola_id, titulo=titulo, nivel_codigo=nivel)
            db.add(livro)
            db.flush()
        ja_lido = db.execute(
            select(Leitura).where(Leitura.aluno_id == aluno.id, Leitura.livro_id == livro.id)
        ).scalar_one_or_none()
        if ja_lido:
            avisos.append(f"“{titulo}” já constava para {aluno.nome} — releitura não pontua (§35).")
            continue
        db.add(Leitura(escola_id=escola_id, aluno_id=aluno.id,
                       livro_id=livro.id, data=data_referencia))
    db.flush()

    # Snapshot derivado do total de leituras registradas
    leituras = db.execute(
        select(Livro.nivel_codigo)
        .join(Leitura, Leitura.livro_id == Livro.id)
        .where(Leitura.aluno_id == aluno.id)
    ).scalars().all()
    por_nivel: dict[str, int] = {}
    for codigo in leituras:
        por_nivel[codigo] = por_nivel.get(codigo, 0) + 1
    anterior = _snapshot_atual(db, escola_id, aluno.id, SnapshotElefante)
    db.add(SnapshotElefante(
        escola_id=escola_id, aluno_id=aluno.id, importacao_id=importacao.id,
        data_referencia=data_referencia,
        livros_unicos=len(leituras),
        tempo_leitura_min=anterior.tempo_leitura_min if anterior else 0,
        questoes_tentativas=anterior.questoes_tentativas if anterior else 0,
        questoes_acertos=anterior.questoes_acertos if anterior else 0,
        livros_por_nivel=por_nivel,
    ))


@router.post("/confirmar", response_model=ImportacaoResultadoOut)
def confirmar(
    dados: ImportacaoConfirm,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    inicio = time.monotonic()
    from app.models import Escola

    escola = db.get(Escola, escola_id)
    if escola is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Escola não encontrada.")
    if not dados.linhas:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nenhuma linha para importar.")

    data_referencia = dados.data_referencia or datetime.now(timezone.utc)
    avisos: list[str] = []

    # Move o arquivo original de /temporarios para a pasta definitiva (§15)
    arquivo_final = None
    if dados.arquivo_token:
        origem = settings.UPLOADS_DIR / "temporarios" / dados.arquivo_token
        if origem.exists():
            nome = f"{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_{dados.arquivo_nome or dados.arquivo_token}"
            destino = settings.UPLOADS_DIR / dados.plataforma / nome
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(origem), str(destino))
            arquivo_final = f"uploads/{dados.plataforma}/{nome}"

    importacao = Importacao(
        escola_id=escola_id, usuario_id=usuario.id,
        plataforma=dados.plataforma, tipo=dados.tipo,
        arquivo_original=arquivo_final or dados.arquivo_nome,
        status="concluida",
    )
    db.add(importacao)
    db.flush()

    # Agrupa por aluno resolvido; no formato "leituras" um aluno tem várias linhas
    resolvidos: dict[int, tuple[Aluno, list]] = {}
    for linha in dados.linhas:
        aluno = _resolver_aluno(db, escola_id, escola.ano_letivo_ativo, linha, avisos)
        if aluno is None:
            continue
        resolvidos.setdefault(aluno.id, (aluno, []))[1].append(linha)

    for aluno, linhas_aluno in resolvidos.values():
        if dados.plataforma == "matific":
            _importar_matific(db, escola_id, importacao, aluno,
                              linhas_aluno[-1].dados, data_referencia)
        elif dados.formato == "leituras":
            _importar_elefante_leituras(db, escola_id, importacao, aluno,
                                        linhas_aluno, data_referencia, avisos)
        else:
            _importar_elefante_resumo(db, escola_id, importacao, aluno,
                                      linhas_aluno[-1].dados, data_referencia)

    importacao.qtd_alunos = len(resolvidos)
    importacao.qtd_erros = len(dados.linhas) - sum(len(l) for _, l in resolvidos.values())
    importacao.tempo_ms = int((time.monotonic() - inicio) * 1000)

    registrar(db, "importacao.concluida", escola_id=escola_id, usuario_id=usuario.id,
              entidade="importacao", entidade_id=importacao.id,
              detalhes={"plataforma": dados.plataforma, "tipo": dados.tipo,
                        "alunos": importacao.qtd_alunos, "avisos": avisos})
    db.commit()
    scoring.recalcular_escola(db, escola_id)

    return ImportacaoResultadoOut(
        mensagem=f"Importação concluída: {importacao.qtd_alunos} alunos atualizados. "
                 f"Notas recalculadas automaticamente.",
        importacao_id=importacao.id,
        qtd_alunos=importacao.qtd_alunos,
        qtd_erros=importacao.qtd_erros,
        avisos=avisos,
    )


# --- Histórico (PRD §15) ------------------------------------------------------

@router.get("", response_model=list[ImportacaoOut])
def listar(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    linhas = db.execute(
        select(Importacao, Usuario.nome)
        .outerjoin(Usuario, Importacao.usuario_id == Usuario.id)
        .where(Importacao.escola_id == escola_id)
        .order_by(Importacao.id.desc())
        .limit(100)
    ).all()
    saida = []
    for importacao, usuario_nome in linhas:
        item = ImportacaoOut.model_validate(importacao)
        item.usuario_nome = usuario_nome
        saida.append(item)
    return saida
