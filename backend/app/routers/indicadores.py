"""Indicadores oficiais de referência da rede — o ICA (etapas E2 e E3) e o SARESP
oficial da SEDUC (IEE, SARESP por município e por instância — etapa E4; a leitura
para a tela, etapa E5).

* LER (``GET /redes/{id}/indicadores/ica`` e ``.../saresp``): ``exigir_rede`` — a
  Secretaria da PRÓPRIA rede e o admin global, a mesma regra de
  ``/redes/{id}/avaliacoes/...``. Coordenador e professor de escola (sem rede)
  recebem 403.
* IMPORTAR e DESFAZER: só o admin global (``exigir_admin_global``) — decisão D4 do dono
  (17/10), definitiva (ver "Permissões definitivas" abaixo).

Prévia → aplicação → desfazer (ver ``services/indicadores/pipeline``). A prévia
não grava número nenhum; a aplicação exige o MESMO arquivo da prévia (sha256).
O arquivo é a planilha oficial (XLSX) OU o pacote recortado dos microdados que a
linha de comando ``python -m app.services.indicadores.preparar`` gera (E3) — o
servidor refaz a validação do pacote. Desfazer é pelo id da importação.

Ideb e Saeb POR ESCOLA (E6a, ``.../indicadores/ideb/...``): só o PACOTE que o
``preparar`` gera do zip do INEP nesta máquina (o zip de ~100 MB nunca sobe), pela
mesma prévia → aplicação → desfazer do SARESP oficial (``pipeline_ideb``), com as
mesmas permissões. A leitura para a tela (E8a, ``GET .../indicadores/ideb``) segue a
regra de leitura do ICA e do SARESP (``exigir_rede``). O Ideb do MUNICÍPIO, da UF e do
BRASIL (E6b) entra pelas MESMAS rotas (o pacote diz o parser).

Planilha do SAEB (E7, ``.../indicadores/saeb/...``): o pacote do ``preparar`` (médias e
níveis do 5º ano do município, de SP e do Brasil; 2º ano amostral de SP e do Brasil),
pelo mesmo fluxo de famílias (``pipeline_saeb``) e com as mesmas permissões.

PERMISSÕES DEFINITIVAS (E9 — decisões D4 e D5 do dono, 17/10):

* importar, aplicar, listar importações e DESFAZER (de qualquer indicador): SÓ o admin
  global (``exigir_admin_global``), em todas as rotas acima;
* ler a REDE (``GET /redes/{id}/indicadores/...``): a Secretaria da PRÓPRIA rede e o
  admin global (``exigir_rede``);
* ler a ESCOLA (``GET /escolas/{id}/indicadores``, ``router_escola``): o coordenador (ou o
  admin) da PRÓPRIA escola, a Secretaria da rede da escola e o admin global — os números
  oficiais da escola e as referências da rede, de SP e do Brasil (o ICA só como
  indicador da rede). Professor, coordenador de outra escola e Secretaria de outra rede:
  403;
* painel público: nada.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import exigir_admin_global, exigir_rede, get_usuario_atual
from app.models import Escola, Rede, Usuario
from app.services.audit import registrar
from app.services.avaliacoes import ImportacaoRecusada
from app.services.indicadores import (consulta, consulta_escola, consulta_ideb, consulta_saresp,
                                     pipeline, pipeline_ideb, pipeline_saeb, pipeline_seduc)

router = APIRouter(prefix="/redes", tags=["Indicadores oficiais"])
# A leitura da ESCOLA (E9) vive em /escolas/{id}/..., ao lado das outras telas da escola.
router_escola = APIRouter(prefix="/escolas", tags=["Indicadores oficiais"])

# Quem administra a escola: o coordenador e o admin DA ESCOLA (sem rede, não global).
_GESTAO_DA_ESCOLA = ("admin", "coordenador")

# As planilhas do ICA têm menos de 1 MB (a municipal de 2023, ~0,8 MB) e o pacote
# dos microdados, poucos KB. O teto barra o upload de outra coisa por engano sem
# segurar RAM à toa.
_MAX_BYTES = 20 * 1024 * 1024


def _rede(db: Session, rede_id: int) -> Rede:
    rede = db.get(Rede, rede_id)
    if rede is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rede não encontrada.")
    return rede


def _ler(arquivo: UploadFile) -> bytes:
    conteudo = arquivo.file.read(_MAX_BYTES + 1)
    if len(conteudo) > _MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            "Arquivo muito grande para a planilha ou o pacote do ICA (o "
                            "oficial tem < 1 MB). O zip inteiro dos microdados não sobe: "
                            "gere o pacote com o preparar.")
    return conteudo


def _data(texto: str | None) -> datetime | None:
    if not texto or not texto.strip():
        return None
    try:
        return datetime.fromisoformat(texto.strip().replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Data de coleta inválida (use AAAA-MM-DD).") from exc


@router.get("/{rede_id}/indicadores/ica")
def ica_da_rede(
    rede_id: int = Depends(exigir_rede),
    db: Session = Depends(get_db),
):
    """ICA oficial da rede municipal: série 2023–2025, metas 2024–2030, nível e
    participação, com SP e Brasil (rede pública) — cada número com a fonte, a
    edição e as datas do arquivo/da importação. Sem dado: listas vazias (a tela
    diz "sem resultado importado", nunca 0). Não existe ICA por escola."""
    return consulta.ica_da_rede(db, _rede(db, rede_id))


@router.post("/{rede_id}/indicadores/ica/previa")
def previa_ica(
    rede_id: int,
    arquivo: UploadFile = File(...),
    url_origem: str | None = Form(None),
    last_modified_origem: str | None = Form(None),
    coletado_em: str | None = Form(None),
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """PRÉVIA da planilha oficial do ICA (municípios ou UFs) ou do pacote dos
    microdados agregados (detectados pelo conteúdo): o que mudaria, sem gravar
    número nenhum. Fica registrada como importação ``previa`` (proveniência +
    sha256). No pacote, a URL e o Last-Modified são os do manifesto."""
    rede = _rede(db, rede_id)
    conteudo = _ler(arquivo)
    try:
        saida = pipeline.previa(
            db, rede, conteudo, arquivo.filename or "", usuario_id=usuario.id,
            url_origem=url_origem, last_modified_origem=last_modified_origem,
            coletado_em=_data(coletado_em))
    except ImportacaoRecusada as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    db.commit()
    return saida


@router.post("/{rede_id}/indicadores/ica/aplicar")
def aplicar_ica(
    rede_id: int,
    previa_id: int = Form(...),
    arquivo: UploadFile = File(...),
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """APLICA a prévia: reenvie o MESMO arquivo. Grava numa transação só;
    reaplicar o mesmo arquivo deixa o mesmo estado (idempotente)."""
    rede = _rede(db, rede_id)
    conteudo = _ler(arquivo)
    try:
        saida = pipeline.aplicar(db, rede, previa_id, conteudo, arquivo.filename or "",
                                 usuario_id=usuario.id)
        registrar(db, "indicador.importado", usuario_id=usuario.id,
                  entidade="importacao_indicador", entidade_id=saida["id"],
                  # No pacote, ``arquivo_sha256`` é o da entrada ORIGINAL do zip do
                  # INEP; o que a aplicação conferiu é o ``pacote_sha256``.
                  detalhes={"rede_id": rede.id, "arquivo": saida["arquivo_nome"],
                            "sha256": saida["arquivo_sha256"], "modo": saida["modo"],
                            **({"pacote_sha256": saida["pacote_sha256"]}
                               if saida.get("pacote_sha256") else {}),
                            "contadores": saida["contadores"]})
        db.commit()
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ImportacaoRecusada as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except IntegrityError as exc:   # outra aplicação simultânea gravou a mesma chave
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Outra importação do ICA foi gravada ao mesmo tempo. Gere a "
                            "prévia de novo. Nada foi gravado.") from exc
    return saida


@router.get("/{rede_id}/indicadores/importacoes")
def listar_importacoes(
    rede_id: int,
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Importações do ICA recortadas para esta rede (prévias, aplicadas, desfeitas)."""
    return pipeline.listar(db, _rede(db, rede_id))


@router.post("/{rede_id}/indicadores/importacoes/{importacao_id}/desfazer")
def desfazer_importacao(
    rede_id: int,
    importacao_id: int,
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """DESFAZ uma importação aplicada do ICA, pelo id: volta exatamente ao estado
    anterior (apaga o que ela criou, restaura o que ela alterou). Recusa (400) se
    uma importação aplicada depois dela usa os mesmos números — a mensagem diz
    qual desfazer antes."""
    rede = _rede(db, rede_id)
    try:
        saida = pipeline.desfazer(db, rede, importacao_id, usuario_id=usuario.id)
        registrar(db, "indicador.desfeito", usuario_id=usuario.id,
                  entidade="importacao_indicador", entidade_id=importacao_id,
                  detalhes={"rede_id": rede.id, "arquivo": saida["arquivo_nome"],
                            "contadores": saida["contadores"]})
        db.commit()
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ImportacaoRecusada as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return saida


# --- SARESP oficial (SEDUC-SP) — etapa E4 -------------------------------------
# IEE por escola, SARESP por município e por instância (Estado), detectados pelo
# cabeçalho. Mesmo fluxo e mesmas permissões do ICA: importar e desfazer só o admin
# global. A aplicação que SUBSTITUI números por escola gravados sem proveniência
# oficial (a média do SARESP calculada pelo Constela) exige `substituir_calculadas`
# explícito (sim/não) — decisão D2 do dono; sem resposta, 400 e nada gravado.

# Os arquivos da SEDUC têm até ~1,4 MB (o SARESP por município de 2022).
_MAX_BYTES_SEDUC = 20 * 1024 * 1024


def _ler_seduc(arquivo: UploadFile) -> bytes:
    conteudo = arquivo.file.read(_MAX_BYTES_SEDUC + 1)
    if len(conteudo) > _MAX_BYTES_SEDUC:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            "Arquivo muito grande para os CSVs da SEDUC (os oficiais têm "
                            "poucos MB).")
    return conteudo


def _sim_ou_nao(texto: str | None) -> bool | None:
    if texto is None or not texto.strip():
        return None
    valor = texto.strip().casefold()
    if valor in ("sim", "true", "1", "s"):
        return True
    if valor in ("nao", "não", "false", "0", "n"):
        return False
    raise HTTPException(status.HTTP_400_BAD_REQUEST,
                        "substituir_calculadas deve ser “sim” ou “nao”.")


@router.get("/{rede_id}/indicadores/saresp")
def saresp_da_rede(
    rede_id: int = Depends(exigir_rede),
    db: Session = Depends(get_db),
):
    """SARESP OFICIAL da rede (etapa E5): a rede municipal por série × componente em
    cada edição, o Estado na MESMA rede (redes municipais) e, à parte e rotulada, a
    rede estadual; por escola, a proficiência oficial do IEE com participação, TPS,
    IEE e meta (ordem por nome, sem ranking) e, SEPARADAS, as médias sem proveniência
    oficial (estimativa); a cobertura (sem resultado ≠ 0; escola sem INEP =
    pendência de cadastro). Cada número com a fonte, a edição e a data do arquivo.
    Mesma regra de leitura do ICA: Secretaria da PRÓPRIA rede e admin global."""
    return consulta_saresp.saresp_da_rede(db, _rede(db, rede_id))


@router.post("/{rede_id}/indicadores/saresp/previa")
def previa_saresp(
    rede_id: int,
    arquivo: UploadFile = File(...),
    edicao: int | None = Form(None),
    url_origem: str | None = Form(None),
    last_modified_origem: str | None = Form(None),
    coletado_em: str | None = Form(None),
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """PRÉVIA de um arquivo aberto da SEDUC (IEE, SARESP por município ou por
    instância): o que mudaria — inclusive o ANTES × DEPOIS de cada número por escola
    sem proveniência oficial que seria substituído —, sem gravar número nenhum."""
    rede = _rede(db, rede_id)
    conteudo = _ler_seduc(arquivo)
    try:
        saida = pipeline_seduc.previa(
            db, rede, conteudo, arquivo.filename or "", usuario_id=usuario.id,
            edicao=edicao, url_origem=url_origem, last_modified_origem=last_modified_origem,
            coletado_em=_data(coletado_em))
    except ImportacaoRecusada as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    db.commit()
    return saida


@router.post("/{rede_id}/indicadores/saresp/aplicar")
def aplicar_saresp(
    rede_id: int,
    previa_id: int = Form(...),
    arquivo: UploadFile = File(...),
    substituir_calculadas: str | None = Form(None),
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """APLICA a prévia (reenvie o MESMO arquivo — o nome que vale é o da prévia). Se a
    prévia substitui números sem proveniência oficial, responda
    ``substituir_calculadas`` = sim | nao."""
    rede = _rede(db, rede_id)
    conteudo = _ler_seduc(arquivo)
    substituir = _sim_ou_nao(substituir_calculadas)
    try:
        saida = pipeline_seduc.aplicar(db, rede, previa_id, conteudo, arquivo.filename or "",
                                       usuario_id=usuario.id, substituir_calculadas=substituir)
        registrar(db, "indicador.importado", usuario_id=usuario.id,
                  entidade="importacao_indicador", entidade_id=saida["id"],
                  detalhes={"rede_id": rede.id, "parser": saida["parser"],
                            "arquivo": saida["arquivo_nome"], "sha256": saida["arquivo_sha256"],
                            "substituir_calculadas": substituir,
                            "contadores": saida["contadores"]})
        db.commit()
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ImportacaoRecusada as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Outra importação gravou os mesmos números ao mesmo tempo. Gere "
                            "a prévia de novo. Nada foi gravado.") from exc
    return saida


@router.get("/{rede_id}/indicadores/saresp/importacoes")
def listar_importacoes_saresp(
    rede_id: int,
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Importações do SARESP/IEE desta rede (prévias, aplicadas, desfeitas)."""
    return pipeline_seduc.listar(db, _rede(db, rede_id))


@router.post("/{rede_id}/indicadores/saresp/importacoes/{importacao_id}/desfazer")
def desfazer_importacao_saresp(
    rede_id: int,
    importacao_id: int,
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """DESFAZ uma importação aplicada do SARESP/IEE: volta exatamente ao estado
    anterior — inclusive a média calculada que ela substituiu."""
    rede = _rede(db, rede_id)
    try:
        saida = pipeline_seduc.desfazer(db, rede, importacao_id, usuario_id=usuario.id)
        registrar(db, "indicador.desfeito", usuario_id=usuario.id,
                  entidade="importacao_indicador", entidade_id=importacao_id,
                  detalhes={"rede_id": rede.id, "parser": saida["parser"],
                            "arquivo": saida["arquivo_nome"],
                            "contadores": saida["contadores"]})
        db.commit()
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ImportacaoRecusada as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return saida


# --- Ideb e Saeb por escola (INEP) — etapa E6a --------------------------------
# Só o PACOTE recortado do ``preparar`` (poucos KB); o zip do INEP e a
# planilha crua são recusados. Mesmo fluxo e mesmas permissões do SARESP oficial: os
# números de 2023 já gravados pelo 1 clique, IGUAIS aos do arquivo, ficam como estão;
# um número diferente sem proveniência oficial só é trocado com
# ``substituir_calculadas`` explícito.

_MAX_BYTES_IDEB = 5 * 1024 * 1024


@router.get("/{rede_id}/indicadores/ideb")
def ideb_da_rede(
    rede_id: int = Depends(exigir_rede),
    db: Session = Depends(get_db),
):
    """IDEB e SAEB oficiais POR ESCOLA (E8a) e da REDE MUNICIPAL (E8b). Por escola, em
    ordem de nome (sem ranking), a série 2005–2025 do Ideb, do Saeb do 5º ano (LP e MT),
    de N, P, aprovação e das metas 2007–2021 (meta × observado na precisão publicada);
    ausência com o motivo (nunca 0); cobertura; números sem proveniência oficial (1
    clique) marcados. Da rede: o Ideb da rede municipal com as metas, comparado na MESMA
    rede com o Brasil (a UF, só na rede pública no arquivo do INEP, vem como contexto
    rotulado de outra rede); o Saeb do 5º ano da planilha (média e níveis, localização
    Total) da rede, da UF e do Brasil nas redes municipais; o contexto amostral do 2º ano
    e a taxa de alfabetização de 2021 (não é o ICA). A fonte, a edição e a data do arquivo
    de cada número. Mesma regra de leitura do ICA e do SARESP: Secretaria da PRÓPRIA rede
    e admin global."""
    return consulta_ideb.ideb_da_rede(db, _rede(db, rede_id))


def _ler_ideb(arquivo: UploadFile) -> bytes:
    conteudo = arquivo.file.read(_MAX_BYTES_IDEB + 1)
    if len(conteudo) > _MAX_BYTES_IDEB:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            "Arquivo muito grande para o pacote do Ideb (o real tem poucos "
                            "KB). O zip do INEP não sobe: gere o pacote com o "
                            "preparar nesta máquina.")
    return conteudo


@router.post("/{rede_id}/indicadores/ideb/previa")
def previa_ideb(
    rede_id: int,
    arquivo: UploadFile = File(...),
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """PRÉVIA do pacote do Ideb por escola: o que mudaria em cada escola e edição
    (Ideb e Saeb em ``resultados_avaliacao``; N, P, aprovação e metas em
    ``indicadores_referencia``), sem gravar número nenhum. A origem (URL,
    Last-Modified, sha256 do zip do INEP) é a do manifesto."""
    rede = _rede(db, rede_id)
    conteudo = _ler_ideb(arquivo)
    try:
        saida = pipeline_ideb.previa(db, rede, conteudo, arquivo.filename or "",
                                     usuario_id=usuario.id)
    except ImportacaoRecusada as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    db.commit()
    return saida


@router.post("/{rede_id}/indicadores/ideb/aplicar")
def aplicar_ideb(
    rede_id: int,
    previa_id: int = Form(...),
    arquivo: UploadFile = File(...),
    substituir_calculadas: str | None = Form(None),
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """APLICA a prévia (reenvie o MESMO pacote). Reaplicar deixa o mesmo estado."""
    rede = _rede(db, rede_id)
    conteudo = _ler_ideb(arquivo)
    substituir = _sim_ou_nao(substituir_calculadas)
    try:
        saida = pipeline_ideb.aplicar(db, rede, previa_id, conteudo, arquivo.filename or "",
                                      usuario_id=usuario.id, substituir_calculadas=substituir)
        registrar(db, "indicador.importado", usuario_id=usuario.id,
                  entidade="importacao_indicador", entidade_id=saida["id"],
                  detalhes={"rede_id": rede.id, "parser": saida["parser"],
                            "arquivo": saida["arquivo_nome"], "sha256": saida["arquivo_sha256"],
                            "pacote_sha256": saida["pacote_sha256"], "modo": saida["modo"],
                            "substituir_calculadas": substituir,
                            "contadores": saida["contadores"]})
        db.commit()
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ImportacaoRecusada as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Outra importação gravou os mesmos números ao mesmo tempo. Gere "
                            "a prévia de novo. Nada foi gravado.") from exc
    return saida


@router.get("/{rede_id}/indicadores/ideb/importacoes")
def listar_importacoes_ideb(
    rede_id: int,
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Importações do Ideb/Saeb por escola desta rede (prévias, aplicadas, desfeitas)."""
    return pipeline_ideb.listar(db, _rede(db, rede_id))


@router.post("/{rede_id}/indicadores/ideb/importacoes/{importacao_id}/desfazer")
def desfazer_importacao_ideb(
    rede_id: int,
    importacao_id: int,
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """DESFAZ uma importação aplicada do Ideb/Saeb: volta exatamente ao estado anterior."""
    rede = _rede(db, rede_id)
    try:
        saida = pipeline_ideb.desfazer(db, rede, importacao_id, usuario_id=usuario.id)
        registrar(db, "indicador.desfeito", usuario_id=usuario.id,
                  entidade="importacao_indicador", entidade_id=importacao_id,
                  detalhes={"rede_id": rede.id, "parser": saida["parser"],
                            "arquivo": saida["arquivo_nome"],
                            "contadores": saida["contadores"]})
        db.commit()
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ImportacaoRecusada as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return saida


# --- Planilha do Saeb (INEP: Brasil, estados e municípios) — etapa E7 -------------
# Só o PACOTE recortado do ``preparar`` (poucos KB): a planilha do INEP (até ~150 MB de
# XML) não sobe. Tudo vai para ``indicadores_referencia``; nada por escola.


def _ler_saeb(arquivo: UploadFile) -> bytes:
    conteudo = arquivo.file.read(_MAX_BYTES_IDEB + 1)
    if len(conteudo) > _MAX_BYTES_IDEB:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            "Arquivo muito grande para o pacote da planilha do Saeb (o real tem "
                            "poucos KB). A planilha do INEP não sobe: gere o pacote com o "
                            "preparar nesta máquina.")
    return conteudo

@router.post("/{rede_id}/indicadores/saeb/previa")
def previa_saeb(
    rede_id: int,
    arquivo: UploadFile = File(...),
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """PRÉVIA do pacote da planilha do Saeb: o que mudaria (médias e níveis do município,
    da UF e do Brasil, por rede e localização), sem gravar número nenhum. A origem (URL,
    Last-Modified, sha256 da planilha do INEP) é a do manifesto."""
    rede = _rede(db, rede_id)
    conteudo = _ler_saeb(arquivo)
    try:
        saida = pipeline_saeb.previa(db, rede, conteudo, arquivo.filename or "",
                                     usuario_id=usuario.id)
    except ImportacaoRecusada as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    db.commit()
    return saida


@router.post("/{rede_id}/indicadores/saeb/aplicar")
def aplicar_saeb(
    rede_id: int,
    previa_id: int = Form(...),
    arquivo: UploadFile = File(...),
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """APLICA a prévia (reenvie o MESMO pacote). Reaplicar deixa o mesmo estado."""
    rede = _rede(db, rede_id)
    conteudo = _ler_saeb(arquivo)
    try:
        saida = pipeline_saeb.aplicar(db, rede, previa_id, conteudo, arquivo.filename or "",
                                      usuario_id=usuario.id)
        registrar(db, "indicador.importado", usuario_id=usuario.id,
                  entidade="importacao_indicador", entidade_id=saida["id"],
                  detalhes={"rede_id": rede.id, "parser": saida["parser"],
                            "arquivo": saida["arquivo_nome"], "sha256": saida["arquivo_sha256"],
                            "pacote_sha256": saida["pacote_sha256"], "modo": saida["modo"],
                            "contadores": saida["contadores"]})
        db.commit()
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ImportacaoRecusada as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Outra importação gravou os mesmos números ao mesmo tempo. Gere "
                            "a prévia de novo. Nada foi gravado.") from exc
    return saida


@router.get("/{rede_id}/indicadores/saeb/importacoes")
def listar_importacoes_saeb(
    rede_id: int,
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Importações da planilha do Saeb desta rede (prévias, aplicadas, desfeitas)."""
    return pipeline_saeb.listar(db, _rede(db, rede_id))


@router.post("/{rede_id}/indicadores/saeb/importacoes/{importacao_id}/desfazer")
def desfazer_importacao_saeb(
    rede_id: int,
    importacao_id: int,
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """DESFAZ uma importação aplicada da planilha do Saeb: volta exatamente ao estado
    anterior."""
    rede = _rede(db, rede_id)
    try:
        saida = pipeline_saeb.desfazer(db, rede, importacao_id, usuario_id=usuario.id)
        registrar(db, "indicador.desfeito", usuario_id=usuario.id,
                  entidade="importacao_indicador", entidade_id=importacao_id,
                  detalhes={"rede_id": rede.id, "parser": saida["parser"],
                            "arquivo": saida["arquivo_nome"],
                            "contadores": saida["contadores"]})
        db.commit()
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ImportacaoRecusada as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return saida


# --- Indicadores oficiais da ESCOLA — etapa E9 -------------------------------------


def escola_com_indicadores_legiveis(
    escola_id: int = Path(...),
    usuario: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db),
) -> Escola:
    """Quem LÊ os indicadores oficiais de uma escola (decisão D5): o admin global (qualquer
    escola); a Secretaria (conta com rede, não global) só as escolas DA SUA rede; o
    coordenador ou o admin DA PRÓPRIA escola. O professor não lê (nem os da escola dele):
    os indicadores oficiais são da gestão. Escola inexistente: 404 (a mesma ordem de
    ``escola_autorizada``)."""
    escola = db.get(Escola, escola_id)
    if escola is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Escola não encontrada.")
    if usuario.is_global:
        return escola
    if usuario.rede_id is not None:                       # Secretaria
        if escola.rede_id != usuario.rede_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "Acesso negado: a escola não é da sua rede.")
        return escola
    if usuario.cargo not in _GESTAO_DA_ESCOLA:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Os indicadores oficiais da escola são da coordenação e da "
                            "Secretaria; o seu perfil não tem acesso.")
    if usuario.escola_id != escola_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Acesso negado aos dados desta escola.")
    return escola


@router_escola.get("/{escola_id}/indicadores")
def indicadores_da_escola(
    escola: Escola = Depends(escola_com_indicadores_legiveis),
    db: Session = Depends(get_db),
):
    """Indicadores OFICIAIS da escola (E9): o SARESP do 2º e do 5º ano (proficiência do
    IEE, participação, TPS, IEE e meta) e o Ideb e o Saeb do 5º ano, com o motivo de cada
    ausência (nunca 0), e as REFERÊNCIAS da rede municipal, do Estado e do Brasil — o ICA
    só como indicador da rede (o INEP não o publica por escola). A fonte em cada número.
    Sem ranking: nenhuma outra escola aparece."""
    return consulta_escola.indicadores_da_escola(db, escola)
