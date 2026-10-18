"""A planilha do SAEB (Brasil, estados e municípios: médias e distribuição por nível do
5º ano; o 2º ano amostral e a taxa de alfabetização de 2021 só de UF e Brasil) pela
MESMA prévia → aplicação → desfazer do fluxo de famílias (``pipeline_seduc``) — etapa
E7. Tudo vai para ``indicadores_referencia`` (avaliação ``saeb``); nada por escola.

O que sobe é só o PACOTE recortado que a linha de comando ``preparar`` gera nesta
máquina a partir da planilha do INEP (``pacote_saeb``); o servidor refaz a validação
com o mesmo parser (``saeb_planilha``) e nunca abre a planilha (até ~150 MB de XML).

PRECEDÊNCIA: cada planilha traz uma edição; a de 2021 com a taxa de alfabetização
repete as médias do 2º ano de Brasil e UF da planilha de 2021 — na MESMA edição, vale
a data interna mais nova da planilha (``Familia.desempate_por_data``); número igual
não mexe em nada. Importar e desfazer: só o admin global (até a D4).
"""
from __future__ import annotations

import io
import zipfile

from sqlalchemy.orm import Session

from app.models import Rede
from app.services.avaliacoes import ImportacaoRecusada
from app.services.indicadores import (aeeb, ideb, pacote_ideb, pacote_saeb, pipeline,
                                      pipeline_seduc, saeb_planilha)

FONTE_NOME = "INEP — Saeb: resultados de Brasil, estados e municípios (planilha)"
CITACAO = ("Fonte: Instituto Nacional de Estudos e Pesquisas Educacionais Anísio Teixeira "
           "(Inep) — Sistema de Avaliação da Educação Básica (Saeb), planilha de resultados "
           "por Brasil, Unidades da Federação e municípios.")

_MSG_PREPARAR = ("gere o pacote recortado nesta máquina com “python -m "
                 "app.services.indicadores.preparar --ibge <código> --planilha "
                 "<saeb_AAAA_brasil_estados_municipios.xlsx>” e envie o pacote (.zip de poucos "
                 "KB). Nada foi gravado.")


def fonte_curta(edicao_arquivo: int) -> str:
    return f"Saeb {edicao_arquivo} oficial (INEP, planilha de resultados)"


# Pacote de OUTRA família enviado aqui: o nome dele em português e onde ele entra
# (a recusa aparece na tela como veio — sem identificador interno de parser).
_OUTRO_PACOTE = {
    ideb.PARSER: "o pacote do Ideb por escola (na importação, escolha “Ideb (pacote)”)",
    ideb.PARSER_MUNICIPIOS: "o pacote do Ideb do município (na importação, escolha “Ideb (pacote)”)",
    ideb.PARSER_UF_BRASIL: ("o pacote do Ideb da UF ou do Brasil (na importação, escolha "
                            "“Ideb (pacote)”)"),
    aeeb.PARSER: "o pacote dos microdados do ICA (ele entra na importação do ICA, no cartão do ICA)",
}


def _recusar_o_que_nao_e_pacote(conteudo: bytes, nome: str) -> None:
    parser = pacote_ideb.parser_do_pacote(conteudo)
    if parser is not None:
        outro = _OUTRO_PACOTE.get(parser, "um pacote de indicadores de outro tipo")
        raise ImportacaoRecusada(
            f"Este arquivo é {outro}; aqui entra o pacote da planilha do Saeb. Nada foi gravado.")
    if conteudo.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
                nomes = z.namelist()
        except zipfile.BadZipFile:
            nomes = []
        tipo = ("a planilha do INEP crua (ela não sobe para o servidor)"
                if "[Content_Types].xml" in nomes else "um zip que não é o pacote do preparar")
        raise ImportacaoRecusada(f"O arquivo “{nome or 'sem nome'}” é {tipo}: {_MSG_PREPARAR}")
    raise ImportacaoRecusada(
        f"Não reconheci o arquivo “{nome or 'sem nome'}”: aqui entra só o pacote da planilha do "
        f"Saeb. Para gerá-lo, {_MSG_PREPARAR}")


def _ler(db: Session, rede: Rede, conteudo: bytes, nome: str,
         edicao: int | None) -> pipeline_seduc.Lido:
    codigo = pipeline._exigir_codigo(rede)
    if pacote_ideb.parser_do_pacote(conteudo) != saeb_planilha.PARSER:
        _recusar_o_que_nao_e_pacote(conteudo, nome)
    lido = pacote_saeb.ler_pacote(conteudo, nome, codigo_ibge=codigo)
    leitura, extra = saeb_planilha.recortar(lido.leitura)
    leitura.avisos = [*(f"No preparo: {a}" for a in lido.avisos_preparo), *leitura.avisos]
    m = lido.meta
    return pipeline_seduc.Lido(
        leitura=leitura, versao_parser=saeb_planilha.VERSAO_PARSER, fonte_nome=FONTE_NOME,
        citacao=CITACAO, licenca=pipeline.LICENCA,
        fonte_curta=fonte_curta(leitura.edicao_arquivo), modo=m["modo"],
        arquivo_nome=m["arquivo_nome"], arquivo_sha256=m["arquivo_sha256"],
        arquivo_bytes=m["arquivo_bytes"], arquivo_data=m["arquivo_data"],
        versao_rotulo=m["versao_rotulo"], url_origem=m["url_origem"],
        last_modified_origem=m["last_modified_origem"], coletado_em=m["coletado_em"],
        pacote_sha256=m["pacote_sha256"],
        resumo_extra={**extra, "pacote": pacote_saeb.resumo_do_manifesto(lido.manifesto)})


FAMILIA = pipeline_seduc.Familia(rotulo="Saeb (planilha)", parsers=(saeb_planilha.PARSER,),
                                 avaliacao_importacao=saeb_planilha.AVALIACAO, ler=_ler,
                                 desempate_por_data=True)


def previa(db: Session, rede: Rede, conteudo: bytes, nome: str, *,
           usuario_id: int | None) -> dict:
    """PRÉVIA do pacote: o que mudaria, sem gravar número nenhum."""
    return pipeline_seduc.previa(db, rede, conteudo, nome, usuario_id=usuario_id,
                                 familia=FAMILIA)


def aplicar(db: Session, rede: Rede, previa_id: int, conteudo: bytes, nome: str, *,
            usuario_id: int | None) -> dict:
    """APLICA a prévia (o MESMO pacote, pelo sha256). Reaplicar não muda nada."""
    return pipeline_seduc.aplicar(db, rede, previa_id, conteudo, nome, usuario_id=usuario_id,
                                  familia=FAMILIA)


def desfazer(db: Session, rede: Rede, importacao_id: int, *, usuario_id: int | None) -> dict:
    """DESFAZ pelo id: volta exatamente ao estado anterior."""
    return pipeline_seduc.desfazer(db, rede, importacao_id, usuario_id=usuario_id,
                                   familia=FAMILIA)


def listar(db: Session, rede: Rede) -> list[dict]:
    """Importações da planilha do Saeb desta rede (mais recentes primeiro)."""
    return pipeline_seduc.listar(db, rede, familia=FAMILIA)
