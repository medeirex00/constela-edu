"""Ideb e Saeb do INEP (anos iniciais, 2005–AAAA) pela MESMA prévia → aplicação →
desfazer do fluxo de famílias (``pipeline_seduc``):

* POR ESCOLA (E6a, ``inep_ideb_escolas``): Ideb e Saeb do 5º ano em
  ``resultados_avaliacao``; N, P, aprovação e metas em ``indicadores_referencia``;
* do MUNICÍPIO, da UF e do BRASIL (E6b, ``inep_ideb_municipios`` e
  ``inep_ideb_uf_brasil``): tudo em ``indicadores_referencia`` (abrangência
  ``municipio``/``uf``/``brasil``, na rede de ensino da coluna REDE) — o mesmo
  pacote, a mesma rota, detectado pelo parser do manifesto.

O que sobe é só o PACOTE recortado que a linha de comando ``preparar`` gera nesta
máquina a partir do zip do INEP (``pacote_ideb``); o servidor refaz a validação com
o mesmo parser e nunca abre o arquivo do INEP. O zip inteiro, a planilha crua e
o pacote de outra fonte são recusados com a causa.

Diferença para o SARESP (``Familia.manual_igual_fica``): o Ideb e o Saeb de 2023 que
a produção já tem vieram do MESMO arquivo oficial pelo botão de 1 clique,
sem ``importacao_id``. Número igual ao oficial fica COMO ESTÁ (nem a fonte muda) —
reimportar 2023 não cria nenhuma linha nova com valor; só as ausências que o arquivo
declara ("-") e as edições 2005–2021. Número DIFERENTE sem proveniência oficial é
substituição explícita (``substituir_calculadas``), como na D2.

PRECEDÊNCIA (plano, 4.3/4.5: vale o arquivo oficial mais recente): a edição mais nova
vence; na MESMA edição, a data interna da planilha no zip do INEP (``arquivo_data``)
— o INEP retifica fora de época com o mesmo nome de arquivo. O pacote da versão
anterior vira ``mantida`` (a prévia avisa) e não desfaz a retificação, seja qual for
a ordem de importação (``Familia.desempate_por_data``). Assim, o arquivo de 2025
(2005–2025) vale sobre o de 2023 nas edições que os dois trazem; número igual não
mexe em nada, número diferente vira ``alterada`` com o ANTES × DEPOIS na prévia.

Importar e desfazer: só o admin global (a regra mais restrita até a D4).
"""
from __future__ import annotations

import io
import zipfile

from sqlalchemy.orm import Session

from app.models import Rede
from app.services.avaliacoes import ImportacaoRecusada
from app.services.indicadores import (aeeb, ideb, ideb_territorio, pacote_ideb, pipeline,
                                      pipeline_seduc, saeb_planilha)

FONTE_NOME = "INEP — Ideb por escola, anos iniciais (Ideb, Saeb do 5º ano e rendimento)"
CITACAO = ("Fonte: Instituto Nacional de Estudos e Pesquisas Educacionais Anísio Teixeira "
           "(Inep) — Índice de Desenvolvimento da Educação Básica (Ideb) por escola, Ensino "
           "Fundamental Regular, anos iniciais: taxa de aprovação, Saeb e Ideb.")
FONTE_NOME_TERRITORIO = {
    ideb_territorio.PARSER_MUNICIPIOS: "INEP — Ideb por município, anos iniciais (rede municipal)",
    ideb_territorio.PARSER_UF_BRASIL: "INEP — Ideb de Brasil, regiões e UFs, anos iniciais",
}
CITACAO_TERRITORIO = {
    ideb_territorio.PARSER_MUNICIPIOS: (
        "Fonte: Instituto Nacional de Estudos e Pesquisas Educacionais Anísio Teixeira (Inep) "
        "— Índice de Desenvolvimento da Educação Básica (Ideb) por município e rede, Ensino "
        "Fundamental Regular, anos iniciais: taxa de aprovação, Saeb e Ideb."),
    ideb_territorio.PARSER_UF_BRASIL: (
        "Fonte: Instituto Nacional de Estudos e Pesquisas Educacionais Anísio Teixeira (Inep) "
        "— Índice de Desenvolvimento da Educação Básica (Ideb) de Brasil, regiões e UFs por "
        "rede, Ensino Fundamental Regular, anos iniciais: taxa de aprovação, Saeb e Ideb."),
}
PARSERS = (ideb.PARSER, *ideb_territorio.PARSERS)

_MSG_PREPARAR = ("gere o pacote recortado nesta máquina com “python -m "
                 "app.services.indicadores.preparar --ibge <código> --zip "
                 "<divulgacao_anos_iniciais_escolas_AAAA.zip>” (ou o zip de municípios, de "
                 "UF/regiões ou de Brasil) e envie o pacote (.zip de poucos KB). Nada foi "
                 "gravado.")


def fonte_curta(edicao_arquivo: int) -> str:
    return f"Ideb/Saeb oficial (INEP, divulgação {edicao_arquivo})"


def _recusar_o_que_nao_e_pacote(conteudo: bytes, nome: str) -> None:
    """Explica por que o arquivo enviado não entra (nunca cai no parser)."""
    parser = pacote_ideb.parser_do_pacote(conteudo)
    if parser is not None:
        # Em português e dizendo onde o arquivo entra: a recusa aparece na tela como
        # veio, sem identificador interno de parser.
        if parser == aeeb.PARSER:
            outro = ("o pacote dos microdados do ICA (ele entra na importação do ICA, no "
                     "cartão do ICA)")
        elif parser == saeb_planilha.PARSER:
            outro = "o pacote da planilha do Saeb (na importação, escolha “Saeb (pacote)”)"
        else:
            outro = "um pacote de indicadores de outro tipo"
        raise ImportacaoRecusada(f"Este arquivo é {outro}; aqui entra o pacote do Ideb (por "
                                 "escola, do município, da UF ou do Brasil). Nada foi gravado.")
    if conteudo.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
                nomes = z.namelist()
        except zipfile.BadZipFile:
            nomes = []
        if "[Content_Types].xml" in nomes:
            tipo = "uma planilha (a do INEP não sobe crua)"
        elif any(n.lower().endswith((".xlsx", ".ods")) for n in nomes):
            tipo = "o zip do INEP inteiro (ele não sobe para o servidor)"
        else:
            tipo = "um zip que não é o pacote do preparar"
        raise ImportacaoRecusada(f"O arquivo “{nome or 'sem nome'}” é {tipo}: {_MSG_PREPARAR}")
    raise ImportacaoRecusada(
        f"Não reconheci o arquivo “{nome or 'sem nome'}”: aqui entra só o pacote do Ideb. Para "
        f"gerá-lo, {_MSG_PREPARAR}")


def _ler(db: Session, rede: Rede, conteudo: bytes, nome: str,
         edicao: int | None) -> pipeline_seduc.Lido:
    codigo = pipeline._exigir_codigo(rede)
    parser = pacote_ideb.parser_do_pacote(conteudo)
    if parser == ideb.PARSER:
        lido = pacote_ideb.ler_pacote(conteudo, nome, codigo_ibge=codigo)
        leitura, extra = ideb.recortar(lido.leitura, pipeline_seduc.escolas_por_inep(db, rede),
                                       codigo_ibge=codigo)
        fonte_nome, citacao, versao = FONTE_NOME, CITACAO, ideb.VERSAO_PARSER
    elif parser in ideb_territorio.PARSERS:
        lido = pacote_ideb.ler_pacote_territorio(conteudo, nome, codigo_ibge=codigo)
        leitura, extra = ideb_territorio.recortar(lido.leitura)
        fonte_nome, citacao = FONTE_NOME_TERRITORIO[parser], CITACAO_TERRITORIO[parser]
        versao = ideb_territorio.VERSAO_PARSER
    else:
        _recusar_o_que_nao_e_pacote(conteudo, nome)
    leitura.avisos = [*(f"No preparo: {a}" for a in lido.avisos_preparo), *leitura.avisos]
    m = lido.meta
    return pipeline_seduc.Lido(
        leitura=leitura, versao_parser=versao, fonte_nome=fonte_nome,
        citacao=citacao, licenca=pipeline.LICENCA,
        fonte_curta=fonte_curta(leitura.edicao_arquivo), modo=m["modo"],
        arquivo_nome=m["arquivo_nome"], arquivo_sha256=m["arquivo_sha256"],
        arquivo_bytes=m["arquivo_bytes"], arquivo_data=m["arquivo_data"],
        versao_rotulo=m["versao_rotulo"], url_origem=m["url_origem"],
        last_modified_origem=m["last_modified_origem"], coletado_em=m["coletado_em"],
        pacote_sha256=m["pacote_sha256"],
        resumo_extra={**extra, "pacote": pacote_ideb.resumo_do_manifesto(lido.manifesto)})


FAMILIA = pipeline_seduc.Familia(rotulo="Ideb/Saeb", parsers=PARSERS,
                                 avaliacao_importacao=ideb.AVALIACAO_IDEB, ler=_ler,
                                 manual_igual_fica=True, desempate_por_data=True)


def previa(db: Session, rede: Rede, conteudo: bytes, nome: str, *,
           usuario_id: int | None) -> dict:
    """PRÉVIA do pacote: o que mudaria, sem gravar número nenhum (fica registrada
    como importação ``previa``, com a proveniência do manifesto)."""
    return pipeline_seduc.previa(db, rede, conteudo, nome, usuario_id=usuario_id,
                                 familia=FAMILIA)


def aplicar(db: Session, rede: Rede, previa_id: int, conteudo: bytes, nome: str, *,
            usuario_id: int | None, substituir_calculadas: bool | None = None) -> dict:
    """APLICA a prévia (o MESMO pacote, pelo sha256). Reaplicar não muda nada."""
    return pipeline_seduc.aplicar(db, rede, previa_id, conteudo, nome, usuario_id=usuario_id,
                                  substituir_calculadas=substituir_calculadas, familia=FAMILIA)


def desfazer(db: Session, rede: Rede, importacao_id: int, *, usuario_id: int | None) -> dict:
    """DESFAZ pelo id: volta exatamente ao estado anterior."""
    return pipeline_seduc.desfazer(db, rede, importacao_id, usuario_id=usuario_id,
                                   familia=FAMILIA)


def listar(db: Session, rede: Rede) -> list[dict]:
    """Importações do Ideb/Saeb (por escola e do território) desta rede (mais recentes
    primeiro)."""
    return pipeline_seduc.listar(db, rede, familia=FAMILIA)
