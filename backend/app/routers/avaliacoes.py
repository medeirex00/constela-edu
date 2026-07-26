"""Avaliações externas — catálogo e importação de resultados oficiais.

MVP: importação de ARQUIVO oficial (XLSX/CSV) — nenhuma das fontes (SAEB/IDEB/
SARESP/Criança Alfabetizada) tem API self-serve. Fluxo: `analisar` mostra a grade
crua (o gestor escolhe a linha de dados e mapeia as colunas), `importar` grava
casando escola por CÓDIGO INEP. Só admin/coordenador; o alcance segue o perfil
(global = todas; rede = escolas da rede; escola = a própria).
"""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import exigir_admin_global, exigir_papeis, get_usuario_atual
from app.models import AvaliacaoExterna, Escola, FonteAvaliacao, Usuario
from app.services import avaliacoes as svc
from app.services.audit import registrar

router = APIRouter(prefix="/avaliacoes", tags=["Avaliações externas"])

# O arquivo oficial do IDEB por escola é grande (ZIP de "anos iniciais" ~97 MB).
# O caminho principal é o robô baixar sozinho pelo servidor; este teto cobre o
# upload manual (plano B) sem estourar a RAM. Ver _MAX_DOWNLOAD no serviço.
_MAX_BYTES = 150 * 1024 * 1024


def _escopo_escolas(db: Session, usuario: Usuario) -> set[int] | None:
    """Escolas que este usuário pode gravar resultado: None = todas (global);
    conjunto = escolas da rede (Secretaria) ou a própria escola; vazio = nada."""
    if usuario.is_global:
        return None
    if usuario.rede_id is not None:
        return set(db.execute(
            select(Escola.id).where(Escola.rede_id == usuario.rede_id)).scalars())
    if usuario.escola_id is not None:
        return {usuario.escola_id}
    return set()


@router.get("")
def catalogo(usuario: Usuario = Depends(get_usuario_atual), db: Session = Depends(get_db)):
    """Catálogo de avaliações/indicadores (materializa o catálogo inicial)."""
    for chave in svc.CATALOGO:
        svc.obter_avaliacao(db, chave)
    db.commit()
    return [
        {"chave": a.chave, "nome": a.nome, "tipo": a.tipo, "orgao": a.orgao,
         "descricao": a.descricao}
        for a in db.execute(
            select(AvaliacaoExterna).order_by(AvaliacaoExterna.tipo, AvaliacaoExterna.nome)
        ).scalars()
    ]


# Endpoints SÍNCRONOS de propósito: o parse (openpyxl) e a gravação são CPU/DB
# bound; como `def` (não `async def`), o FastAPI os roda numa thread do pool, sem
# travar o event loop durante um arquivo grande. Por isso lemos o arquivo pelo
# objeto síncrono (arquivo.file.read()).

@router.post("/analisar")
def analisar(
    arquivo: UploadFile = File(...),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
):
    """Prévia: grade crua das primeiras linhas — a tela usa para escolher a linha
    de dados e mapear as colunas (por índice). Robusto a pré-âmbulo/edição."""
    conteudo = arquivo.file.read(_MAX_BYTES + 1)  # limitado: o teto limita a RAM
    if len(conteudo) > _MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            "Arquivo muito grande. Extraia/reduza a planilha antes de subir.")
    return svc.analisar_planilha(conteudo, arquivo.filename or "")


@router.post("/importar")
def importar(
    arquivo: UploadFile = File(...),
    avaliacao: str = Form(...),
    edicao: int = Form(...),
    indicador: str = Form(...),
    unidade: str = Form(...),
    linha_dados: int = Form(...),
    col_inep: int = Form(...),
    col_valor: int = Form(...),
    col_etapa: int | None = Form(None),
    col_componente: int | None = Form(None),
    col_turma: int | None = Form(None),
    etapa_fixa: str | None = Form(None),
    componente_fixo: str | None = Form(None),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Importa os resultados casando escola por CÓDIGO INEP (dentro do alcance do
    perfil). Idempotente por (avaliação, edição, indicador, escola, etapa,
    componente, turma). Só grava os níveis que o arquivo fornece."""
    if avaliacao not in svc.CATALOGO:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Avaliação desconhecida: {avaliacao}.")
    if linha_dados < 0 or col_inep < 0 or col_valor < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mapeamento inválido.")
    conteudo = arquivo.file.read(_MAX_BYTES + 1)  # limitado: o teto limita a RAM
    if len(conteudo) > _MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Arquivo muito grande.")

    resultado = svc.importar_resultados(
        db, conteudo, arquivo.filename or "",
        avaliacao_chave=avaliacao, edicao=edicao, indicador=indicador, unidade=unidade,
        linha_dados=linha_dados, col_inep=col_inep, col_valor=col_valor,
        col_etapa=col_etapa, col_componente=col_componente, col_turma=col_turma,
        etapa_fixa=etapa_fixa, componente_fixo=componente_fixo,
        escopo_escolas=_escopo_escolas(db, usuario))
    registrar(db, "avaliacao.importada", usuario_id=usuario.id,
              entidade="avaliacao_externa", detalhes=resultado)
    db.commit()
    return resultado


# --- Fontes de COLETA AUTOMÁTICA (o "robô") — só admin global -----------------
# A Secretaria não sobe nada: o admin global cadastra a RECEITA uma vez (URL do
# arquivo oficial + o mapeamento de colunas, travado ao subir o arquivo real na
# tela) e o software passa a baixar/importar sozinho, casando por INEP.

class _MapeamentoIn(BaseModel):
    linha_dados: int = 0
    col_inep: int = 0
    col_valor: int = 0
    col_etapa: int | None = None
    col_componente: int | None = None
    col_turma: int | None = None
    etapa_fixa: str | None = None
    componente_fixo: str | None = None


class _FonteIn(BaseModel):
    avaliacao: str
    nome: str
    url: str
    edicao: int
    indicador: str
    unidade: str
    cadencia: str = "manual"  # manual (coleta sob demanda) | mensal (agendada)
    mapeamento: _MapeamentoIn


def _fonte_saida(f: FonteAvaliacao, av: AvaliacaoExterna | None) -> dict:
    return {
        "id": f.id, "avaliacao": av.chave if av else None,
        "avaliacao_nome": av.nome if av else None,
        "nome": f.nome, "url": f.url, "edicao": f.edicao,
        "indicador": f.indicador, "unidade": f.unidade,
        "cadencia": f.cadencia, "ativo": f.ativo, "mapeamento": f.mapeamento,
        "ultima_coleta": f.ultima_coleta.isoformat() if f.ultima_coleta else None,
        "proxima_coleta": f.proxima_coleta.isoformat() if f.proxima_coleta else None,
        "ultimo_status": f.ultimo_status, "ultimo_erro": f.ultimo_erro,
        "ultimo_resumo": f.ultimo_resumo,
    }


@router.get("/fontes")
def listar_fontes(
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Lista as fontes cadastradas com o último status de coleta (para o painel)."""
    fontes = db.execute(
        select(FonteAvaliacao).order_by(FonteAvaliacao.nome)).scalars().all()
    avs = {a.id: a for a in db.execute(select(AvaliacaoExterna)).scalars()}
    return [_fonte_saida(f, avs.get(f.avaliacao_id)) for f in fontes]


@router.post("/fontes", status_code=status.HTTP_201_CREATED)
def criar_fonte(
    dados: _FonteIn,
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Cadastra a receita do robô (URL + mapeamento). ``mensal`` já agenda a 1ª
    coleta para agora (o scheduler pega no próximo tick)."""
    if dados.avaliacao not in svc.CATALOGO:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Avaliação desconhecida: {dados.avaliacao}.")
    if not dados.url.strip().lower().startswith("https://"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "A URL precisa ser https:// (endereço oficial do arquivo).")
    if dados.mapeamento.linha_dados < 0 or dados.mapeamento.col_inep < 0 \
            or dados.mapeamento.col_valor < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mapeamento inválido.")
    av = svc.obter_avaliacao(db, dados.avaliacao)
    cadencia = "mensal" if dados.cadencia == "mensal" else "manual"
    fonte = FonteAvaliacao(
        avaliacao_id=av.id, nome=dados.nome.strip(), url=dados.url.strip(),
        edicao=dados.edicao, indicador=dados.indicador.strip(),
        unidade=dados.unidade.strip(), cadencia=cadencia,
        mapeamento=dados.mapeamento.model_dump(),
        proxima_coleta=svc._agora() if cadencia == "mensal" else None)
    db.add(fonte)
    db.flush()
    registrar(db, "avaliacao.fonte.criada", usuario_id=usuario.id,
              entidade="fonte_avaliacao", entidade_id=fonte.id,
              detalhes={"nome": fonte.nome, "url": fonte.url})
    db.commit()
    db.refresh(fonte)
    return _fonte_saida(fonte, av)


@router.post("/fontes/{fonte_id}/coletar")
def coletar_agora(
    fonte_id: int,
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Dispara a coleta AGORA (baixa o arquivo oficial e importa). Nunca levanta
    por erro de rede/parse: devolve o status para a tela mostrar."""
    fonte = db.get(FonteAvaliacao, fonte_id)
    if fonte is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fonte não encontrada.")
    resumo = svc.coletar_fonte(db, fonte)
    registrar(db, "avaliacao.fonte.coletada", usuario_id=usuario.id,
              entidade="fonte_avaliacao", entidade_id=fonte.id, detalhes=resumo)
    db.commit()
    db.refresh(fonte)
    return _fonte_saida(fonte, db.get(AvaliacaoExterna, fonte.avaliacao_id))


@router.put("/fontes/{fonte_id}")
def atualizar_fonte(
    fonte_id: int,
    ativo: bool | None = None,
    cadencia: str | None = None,
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Liga/desliga a fonte ou troca a cadência (pausar a coleta agendada)."""
    fonte = db.get(FonteAvaliacao, fonte_id)
    if fonte is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fonte não encontrada.")
    if ativo is not None:
        fonte.ativo = ativo
    if cadencia is not None:
        fonte.cadencia = "mensal" if cadencia == "mensal" else "manual"
    # Invariante (reconciliado após tratar AMBOS os campos): fonte mensal ATIVA
    # sempre tem proxima_coleta; qualquer outra fica None. Sem isto, reativar uma
    # fonte mensal (só ?ativo=true) a deixaria com proxima_coleta=None e o
    # scheduler a ignoraria em silêncio.
    if fonte.ativo and fonte.cadencia == "mensal":
        fonte.proxima_coleta = fonte.proxima_coleta or svc._agora()
    else:
        fonte.proxima_coleta = None
    db.commit()
    db.refresh(fonte)
    return _fonte_saida(fonte, db.get(AvaliacaoExterna, fonte.avaliacao_id))


@router.delete("/fontes/{fonte_id}")
def excluir_fonte(
    fonte_id: int,
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Remove a receita (não apaga os resultados já importados)."""
    fonte = db.get(FonteAvaliacao, fonte_id)
    if fonte is not None:
        registrar(db, "avaliacao.fonte.excluida", usuario_id=usuario.id,
                  entidade="fonte_avaliacao", entidade_id=fonte.id,
                  detalhes={"nome": fonte.nome})
        db.delete(fonte)
        db.commit()
    return {"ok": True}
