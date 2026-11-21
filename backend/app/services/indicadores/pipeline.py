"""Prévia, aplicação e desfazer da importação do ICA (indicadores de referência).

Dois tipos de arquivo entram pelo MESMO fluxo (detectados pelo conteúdo):

* a planilha oficial de resultados e metas (XLSX; parsers ``inep_ica_*``, E2);
* o PACOTE recortado dos microdados agregados (``inep_aeeb_agregados``, E3), que a
  linha de comando ``preparar`` gera nesta máquina — o servidor refaz a validação
  (``pacote.ler_pacote``). O zip inteiro dos microdados e qualquer arquivo de aluno
  são recusados.

Fluxo (só o admin global — a regra mais restrita até a decisão D4):

1. **Prévia** — lê o arquivo, recorta o território da rede e mostra o que mudaria
   (novas, alteradas com antes/depois, iguais, ausências, avisos). Registra a
   importação com ``status='previa'`` e o sha256, e NÃO grava nenhum número.
2. **Aplicação** — exige reenviar o MESMO arquivo (mesmo sha256 — o do pacote, no
   caso do pacote; o servidor não guarda arquivos). Recalcula o plano sobre o
   estado ATUAL e grava numa transação só, guardando o estado anterior de cada
   linha tocada e as chaves que a importação viu.
3. **Desfazer pelo id** — devolve exatamente o estado anterior: apaga o que a
   importação criou e restaura o que ela alterou. Pode ser QUALQUER importação
   aplicada, desde que nenhuma aplicada DEPOIS dela tenha visto um dos números que
   ela tocou (nem como "igual": a posterior pode ter decidido a precedência com o
   valor desta). Havendo esse conflito, recusa e diz qual desfazer antes — a
   última aplicada sempre pode ser desfeita. E só se as linhas ainda estiverem
   como ela deixou.

PRECEDÊNCIA quando o mesmo número vem de arquivos diferentes (ex. SINTÉTICO: o
resultado de 2023 de um município é 26 no arquivo de 2025, 26,2 no de 2024 e
26,18 no de 2023):

* CAPA (``valor``) = o do arquivo mais recente da série — maior ANO da avaliação
  (``edicao_arquivo``); na mesma edição, a data interna mais recente do arquivo
  (v3 depois da v2); empate exato (o mesmo arquivo de novo) → fica o que já
  estava, para reimportar não mexer em nada. A versão mais recente traz os números
  REVISADOS. Arquivo SEM data interna (``arquivo_data`` nulo) fica atrás de
  qualquer versão datada da mesma edição — nunca vence por uma data inventada.
* DETALHE (``valor_detalhado``) = as casas decimais de OUTRO arquivo, só quando o
  arredondamento delas bate com a capa (26,18 → 26); entre vários, o de mais casas
  PUBLICADAS (a precisão da coluna no arquivo: 27,90 numa coluna de 2 casas tem 2;
  26,18 vence 26,2); no empate de casas, a planilha antes dos microdados (a mesma
  prioridade da capa, abaixo) e depois o arquivo mais recente. Se não bater, o
  detalhe é descartado e a prévia avisa "divergência entre arquivos". A precisão do
  detalhe fica em ``casas_decimais_detalhe`` (o float perde o zero final).
* A ordem em que os arquivos são importados não muda o resultado final — nem o
  valor, nem a fonte (``importacao_id``/``detalhe_importacao_id``).
* MICRODADOS AGREGADOS (E3): os decimais do TS_MUNICIPIO/TS_ESTADO (ex. SINTÉTICO:
  30 na planilha, 30,20 nos microdados) entram pela MESMA regra de detalhe, com a
  data interna da entrada do zip. Na CAPA, a planilha de resultados vem SEMPRE
  antes (``_PRIORIDADE_CAPA``): os microdados só são capa de um número que nenhuma
  planilha traz (a média de LP, os níveis, "SP só redes municipais") — ou enquanto
  a planilha não foi importada. A mesma prioridade desempata o DETALHE com o mesmo
  número de casas (planilha de 2 casas × microdados de 2 casas: fica a planilha),
  e assim a ordem de importação continua sem mudar o resultado.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.orm import Session, undefer

from app.models import ImportacaoIndicador, IndicadorReferencia, Rede
from app.services.avaliacoes import ImportacaoRecusada, obter_avaliacao
from app.services.indicadores import aeeb, ica, pacote

CHAVE_AVALIACAO = "ica"
FONTE_NOME = "INEP — Indicador Criança Alfabetizada"
CITACAO = ("Fonte: Instituto Nacional de Estudos e Pesquisas Educacionais Anísio Teixeira "
           "(Inep) — Indicador Criança Alfabetizada, resultados e metas.")
FONTE_NOME_MICRODADOS = "INEP — Microdados da avaliação da alfabetização"
CITACAO_MICRODADOS = ("Fonte: Instituto Nacional de Estudos e Pesquisas Educacionais Anísio "
                      "Teixeira (Inep) — Microdados da avaliação da alfabetização, tabelas "
                      "agregadas TS_MUNICIPIO e TS_ESTADO.")
LICENCA = ("Dado público do Inep (citar a fonte). O portal gov.br aplica a licença "
           "CC BY-ND 3.0: o arquivo não é copiado nem redistribuído pelo Constela.")

# Quem pode ser CAPA: a planilha de resultados (1) vem antes dos microdados
# agregados (0), qualquer que seja a data — e, no DETALHE, desempata o mesmo
# número de casas. Importação apagada (SET NULL): 0.
_PRIORIDADE_CAPA = {ica.PARSER_MUNICIPIOS: 1, ica.PARSER_UFS: 1, aeeb.PARSER: 0}

# Campos de VALOR (comparados para "alterada") e de proveniência ("fonte").
_CAMPOS_VALOR = ("valor", "casas_decimais", "operador", "motivo_ausencia", "unidade",
                 "desenho", "valor_detalhado", "casas_decimais_detalhe")
_CAMPOS_FONTE = ("importacao_id", "detalhe_importacao_id")
_CAMPOS_CHAVE = ("edicao", "indicador", "abrangencia", "codigo_territorio", "codigo_inep",
                 "rede_ensino", "localizacao", "etapa", "componente", "nivel")
_MINIMO = datetime(1, 1, 1)


def _agora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def codigo_ibge_da_rede(rede: Rede) -> str | None:
    return ica.normalizar_codigo_ibge(rede.codigo_ibge)


def feita_pela_rede(imp: ImportacaoIndicador, rede: Rede) -> bool:
    """A importação é DESTA rede: recortada pelo município dela e, quando guardou quem a
    fez (``resumo['rede_id']``), feita por ela. O cadastro recusa o código IBGE de outra
    rede, mas duas redes antigas podem repetir o código: sem a marca, uma listaria,
    aplicaria e desfaria a importação da outra (e a consulta conferiria as escolas de
    uma contra o arquivo importado pela outra). As importações de antes da marca
    continuam valendo pelo município."""
    if imp.codigo_territorio_alvo != codigo_ibge_da_rede(rede):
        return False
    dona = (imp.resumo or {}).get("rede_id")
    return dona is None or dona == rede.id


def _exigir_codigo(rede: Rede) -> str:
    codigo = codigo_ibge_da_rede(rede)
    if codigo is None:
        raise ImportacaoRecusada(
            f"A rede “{rede.nome}” não tem o código IBGE do município cadastrado (7 "
            "dígitos; Caraguatatuba = 3510500). O ICA municipal é recortado por esse "
            "código e o Constela não o adivinha: cadastre o código da rede e envie a "
            "prévia de novo. Nada foi gravado.")
    return codigo


# --- Precedência --------------------------------------------------------------

@dataclass(frozen=True)
class _Candidato:
    """Um valor de uma importação, com a posição dela na série."""

    valor: float | None
    casas: int | None
    operador: str | None
    motivo: str | None
    unidade: str
    desenho: str | None
    importacao_id: int | None
    ordem: tuple            # (edicao_arquivo, data do arquivo, -id): maior = mais recente
    prioridade: int = 1     # planilha de resultados (1) antes dos microdados (0): na
                            # capa e no empate de casas do detalhe


def _ordem(imp: ImportacaoIndicador | None) -> tuple:
    if imp is None:                  # importação apagada (SET NULL): fica por último
        return (-1, _MINIMO, 0)
    return (imp.edicao_arquivo, imp.arquivo_data or _MINIMO, -(imp.id or 0))


def _prioridade(imp: ImportacaoIndicador | None) -> int:
    return 0 if imp is None else _PRIORIDADE_CAPA.get(imp.parser, 1)


def _bate(detalhe: float, capa: float, casas: int) -> bool:
    return abs(ica.arredondar(detalhe, casas) - capa) < 1e-9


def _resolver(candidatos: list[_Candidato]) -> tuple[dict, list[str]]:
    """Estado final (campos da linha) a partir de TODOS os valores conhecidos."""
    capa = max(candidatos, key=lambda c: (c.prioridade, c.ordem))
    elegiveis, divergentes = [], []
    if capa.valor is not None:
        casas_capa = capa.casas or 0
        for c in candidatos:
            if c is capa or c.valor is None or (c.casas or 0) <= casas_capa:
                continue
            if c.operador == capa.operador and _bate(c.valor, capa.valor, casas_capa):
                elegiveis.append(c)
            else:
                divergentes.append(c)
    # No empate de casas, a MESMA prioridade da capa (planilha antes dos
    # microdados) e só depois o mais recente: um candidato que a capa derrubou
    # (casas <= as da capa) fica sempre atrás dela também aqui — por isso guardar
    # só a capa e o detalhe de cada linha basta, e a ordem de importação não muda
    # nem o valor nem a fonte do detalhe.
    detalhe = max(elegiveis, key=lambda c: ((c.casas or 0), c.prioridade, c.ordem),
                  default=None)
    estado = {
        "valor": capa.valor, "casas_decimais": capa.casas, "operador": capa.operador,
        "motivo_ausencia": capa.motivo, "unidade": capa.unidade, "desenho": capa.desenho,
        "importacao_id": capa.importacao_id,
        "valor_detalhado": detalhe.valor if detalhe else None,
        "casas_decimais_detalhe": detalhe.casas if detalhe else None,
        "detalhe_importacao_id": detalhe.importacao_id if detalhe else None,
    }
    avisos = [f"divergência entre arquivos: {c.valor} não arredonda para {capa.valor} "
              "(o número de capa) — decimal descartado" for c in divergentes]
    return estado, avisos


def casas_do_detalhe(linha: IndicadorReferencia) -> int | None:
    """Precisão publicada do detalhe (gravada); sem ela, a do próprio valor."""
    if linha.valor_detalhado is None:
        return None
    if linha.casas_decimais_detalhe is not None:
        return linha.casas_decimais_detalhe
    return ica.precisao(linha.valor_detalhado)[1]


def _candidatos_da_linha(linha: IndicadorReferencia,
                         importacoes: dict[int, ImportacaoIndicador]) -> list[_Candidato]:
    capa = importacoes.get(linha.importacao_id)
    saida = [_Candidato(linha.valor, linha.casas_decimais, linha.operador,
                        linha.motivo_ausencia, linha.unidade, linha.desenho,
                        linha.importacao_id, _ordem(capa), _prioridade(capa))]
    if linha.valor_detalhado is not None:
        detalhe = importacoes.get(linha.detalhe_importacao_id)
        saida.append(_Candidato(linha.valor_detalhado, casas_do_detalhe(linha),
                                linha.operador, None, linha.unidade, linha.desenho,
                                linha.detalhe_importacao_id, _ordem(detalhe),
                                _prioridade(detalhe)))
    return saida


def _estado_da_linha(linha: IndicadorReferencia) -> dict:
    return {c: getattr(linha, c) for c in (*_CAMPOS_VALOR, *_CAMPOS_FONTE)}


def _chave_dict(chave: tuple) -> dict:
    return dict(zip(_CAMPOS_CHAVE, chave))


def _chave_da_linha(linha: IndicadorReferencia) -> tuple:
    return tuple(getattr(linha, c) for c in _CAMPOS_CHAVE)


def _chave_tupla(chave: dict) -> tuple:
    return tuple(chave[c] for c in _CAMPOS_CHAVE)


def nome_territorio(territorios: dict, codigo: str, abrangencia: str, rede_ensino: str) -> str:
    """Nome para a tela: o do arquivo; senão "UF 35"/"Brasil". A UF nas redes
    municipais (microdados) diz isso — não é a mesma linha da UF na rede pública."""
    nome = territorios.get(codigo) or ("Brasil" if codigo == ica.CODIGO_BRASIL
                                       else f"UF {codigo}" if len(codigo) == 2 else codigo)
    if abrangencia == "uf" and rede_ensino == "municipal":
        return f"{nome} (redes municipais)"
    return nome


def _rotulo_numero(indicador: str, nivel: str, edicao: int) -> str:
    return f"{indicador}{f' {nivel}' if nivel else ''} {edicao}"


# --- Leitura do arquivo enviado (planilha OU pacote) ---------------------------

@dataclass
class _Arquivo:
    """A leitura e a proveniência do que foi enviado."""

    leitura: ica.LeituraICA
    versao_parser: str
    fonte_nome: str = FONTE_NOME
    citacao: str = CITACAO
    modo: str = "upload"
    arquivo_nome: str | None = None
    arquivo_sha256: str | None = None
    arquivo_bytes: int | None = None
    versao_rotulo: str | None = None
    url_origem: str | None = None
    last_modified_origem: str | None = None
    coletado_em: datetime | None = None
    pacote_sha256: str | None = None
    manifesto: dict | None = None


_MSG_MICRODADOS_CRUS = (
    "Este é um arquivo dos microdados da avaliação da alfabetização do INEP "
    "(TS_MUNICIPIO/TS_ESTADO). O servidor não recebe o arquivo cru: gere o pacote "
    "recortado nesta máquina com “python -m app.services.indicadores.preparar --ibge "
    "<código> --zip <zip do INEP>” (ou --url) e envie o pacote (.zip). Nada foi gravado.")


def _ler_arquivo(conteudo: bytes, nome: str, codigo: str) -> _Arquivo:
    """Despacha pelo CONTEÚDO: pacote recortado (zip com manifesto.json) ou planilha
    XLSX. Zip dos microdados inteiro (com TS_ALUNO) e arquivo de aluno: recusa."""
    if pacote.eh_pacote(conteudo):
        lido = pacote.ler_pacote(conteudo, nome, codigo_ibge=codigo)
        m = lido.meta
        return _Arquivo(
            leitura=lido.leitura, versao_parser=aeeb.VERSAO_PARSER,
            fonte_nome=FONTE_NOME_MICRODADOS, citacao=CITACAO_MICRODADOS, modo=m["modo"],
            arquivo_nome=m["arquivo_nome"], arquivo_sha256=m["arquivo_sha256"],
            arquivo_bytes=m["arquivo_bytes"], versao_rotulo=m["versao_rotulo"],
            url_origem=_texto(m["url_origem"], 500),
            last_modified_origem=_texto(m["last_modified_origem"], 64),
            coletado_em=m["coletado_em"], pacote_sha256=m["pacote_sha256"],
            manifesto=lido.manifesto)
    aluno = pacote.zip_com_entrada_de_aluno(conteudo)
    if aluno:
        raise ImportacaoRecusada(
            f"O arquivo é o zip dos microdados com a entrada “{aluno}”, que {aeeb.MSG_ALUNO} "
            "O zip inteiro nunca vai ao servidor: gere o pacote recortado com o preparar.")
    if "TS_ALUNO" in (nome or "").upper():        # a tabela de alunos do INEP, pelo nome
        aeeb.recusar_se_for_de_aluno(nome)
    if not conteudo.startswith(b"PK") and aeeb.parece_tabela_aeeb(conteudo):
        aeeb.recusar_se_for_de_aluno(nome, aeeb.cabecalho(conteudo))
        raise ImportacaoRecusada(_MSG_MICRODADOS_CRUS)
    leitura = ica.ler_planilha_ica(conteudo, nome, codigo_ibge=codigo)
    return _Arquivo(leitura=leitura, versao_parser=ica.VERSAO_PARSER)


# --- Plano (comum à prévia e à aplicação) ------------------------------------

def _planejar(db: Session, avaliacao_id: int, leitura: ica.LeituraICA,
              imp: ImportacaoIndicador) -> tuple[list[dict], list[str]]:
    """O que esta importação faria em cada chave: ``nova`` | ``alterada`` |
    ``fonte`` (só a proveniência muda) | ``igual``. Não grava nada."""
    chaves = [ln.chave for ln in leitura.linhas]
    if len(set(chaves)) != len(chaves):
        raise ImportacaoRecusada("O arquivo produziu o mesmo número duas vezes (linha "
                                 "repetida). Nada foi gravado.")
    territorios = {ln.codigo_territorio for ln in leitura.linhas}
    existentes: dict[tuple, IndicadorReferencia] = {}
    if territorios:
        for linha in db.execute(select(IndicadorReferencia).where(
                IndicadorReferencia.avaliacao_id == avaliacao_id,
                IndicadorReferencia.codigo_territorio.in_(territorios))).scalars():
            existentes[_chave_da_linha(linha)] = linha
    ids = {i for ln in existentes.values()
           for i in (ln.importacao_id, ln.detalhe_importacao_id) if i is not None}
    importacoes = {i.id: i for i in db.execute(select(ImportacaoIndicador).where(
        ImportacaoIndicador.id.in_(ids))).scalars()} if ids else {}

    plano: list[dict] = []
    avisos: list[str] = []
    for ln in leitura.linhas:
        novo = _Candidato(ln.valor, ln.casas_decimais, ln.operador, ln.motivo_ausencia,
                          ln.unidade, ln.desenho, imp.id, _ordem(imp), _prioridade(imp))
        atual = existentes.get(ln.chave)
        candidatos = [novo] if atual is None else [*_candidatos_da_linha(atual, importacoes),
                                                   novo]
        depois, divergencias = _resolver(candidatos)
        territorio = nome_territorio(leitura.territorios, ln.codigo_territorio,
                                     ln.abrangencia, ln.rede_ensino)
        rotulo = f"{territorio} · {_rotulo_numero(ln.indicador, ln.nivel, ln.edicao)}"
        avisos.extend(f"{rotulo}: {d}" for d in divergencias)
        if atual is None:
            tipo, antes = "nova", None
        else:
            antes = _estado_da_linha(atual)
            if any(antes[c] != depois[c] for c in _CAMPOS_VALOR):
                tipo = "alterada"
            elif any(antes[c] != depois[c] for c in _CAMPOS_FONTE):
                tipo = "fonte"
            else:
                tipo = "igual"
        plano.append({"chave": ln.chave, "tipo": tipo, "antes": antes, "depois": depois,
                      "rotulo": rotulo, "linha": atual})
    return plano, avisos


def _contadores(plano: list[dict], leitura: ica.LeituraICA) -> dict:
    tipos = [p["tipo"] for p in plano]
    return {
        "lidas": leitura.linhas_lidas,            # linhas de dados do arquivo inteiro
        "recortadas": len(plano),                 # números do território da rede
        "novas": tipos.count("nova"),
        "alteradas": tipos.count("alterada"),
        "fonte_atualizada": tipos.count("fonte"),  # metadado: não conta como alterada
        "iguais": tipos.count("igual"),
        "ausentes": sum(1 for ln in leitura.linhas if ln.valor is None),
        "territorios": len({ln.codigo_territorio for ln in leitura.linhas}),
    }


def _mudancas_para_tela(plano: list[dict], leitura: ica.LeituraICA) -> list[dict]:
    nomes = leitura.territorios
    saida = []
    for p in plano:
        if p["tipo"] == "igual":
            continue
        chave = _chave_dict(p["chave"])
        antes, depois = p["antes"] or {}, p["depois"]
        saida.append({
            "tipo": p["tipo"],
            "territorio": nome_territorio(nomes, chave["codigo_territorio"],
                                          chave["abrangencia"], chave["rede_ensino"]),
            "abrangencia": chave["abrangencia"], "rede_ensino": chave["rede_ensino"],
            "indicador": chave["indicador"], "nivel": chave["nivel"] or None,
            "edicao": chave["edicao"],
            "antes": antes.get("valor"), "antes_detalhe": antes.get("valor_detalhado"),
            "antes_casas": antes.get("casas_decimais"),
            "antes_casas_detalhe": antes.get("casas_decimais_detalhe"),
            "antes_motivo": antes.get("motivo_ausencia"),
            "depois": depois["valor"], "depois_detalhe": depois["valor_detalhado"],
            "depois_casas": depois["casas_decimais"],
            "depois_casas_detalhe": depois["casas_decimais_detalhe"],
            "depois_motivo": depois["motivo_ausencia"], "operador": depois["operador"],
        })
    ordem_abr = {"municipio": 0, "uf": 1, "brasil": 2}
    saida.sort(key=lambda m: (ordem_abr.get(m["abrangencia"], 9), m["rede_ensino"] != "publica",
                              m["indicador"], m["edicao"], int(m["nivel"] or -1)))
    return saida


# --- Prévia -------------------------------------------------------------------

def _texto(valor: str | None, maximo: int) -> str | None:
    valor = (valor or "").strip()
    return valor[:maximo] or None


# Nos arquivos do INEP, a data interna fica horas ANTES do Last-Modified do
# servidor (o arquivo é gravado e depois publicado). Data interna DEPOIS da
# publicação = arquivo salvo de novo depois de baixado.
_FOLGA_LAST_MODIFIED = timedelta(days=1)


def _aviso_data_depois_da_publicacao(arquivo_data: datetime | None,
                                     last_modified: str | None) -> str | None:
    """Confere a data interna com o Last-Modified informado (só avisa; a precedência
    continua pela data interna, e o Last-Modified é texto digitado)."""
    if arquivo_data is None or not (last_modified or "").strip():
        return None
    try:
        publicado = parsedate_to_datetime(last_modified.strip())
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if publicado.tzinfo is not None:
        publicado = publicado.astimezone(timezone.utc).replace(tzinfo=None)
    if arquivo_data <= publicado + _FOLGA_LAST_MODIFIED:
        return None
    return (f"A data interna do arquivo ({arquivo_data:%d/%m/%Y %H:%M} UTC) é posterior ao "
            f"Last-Modified informado ({last_modified.strip()}): o arquivo parece ter sido "
            "salvo de novo depois de baixado. Essa data decide qual versão da mesma edição "
            "vale — confira, ou suba a planilha como baixada do INEP.")


def previa(db: Session, rede: Rede, conteudo: bytes, nome: str, *, usuario_id: int | None,
           url_origem: str | None = None, last_modified_origem: str | None = None,
           coletado_em: datetime | None = None) -> dict:
    """Lê, recorta e compara com o banco. Registra a importação como ``previa``
    (proveniência) e NÃO grava nenhum número. LEVANTA ``ImportacaoRecusada``."""
    codigo = _exigir_codigo(rede)
    arq = _ler_arquivo(conteudo, nome, codigo)
    leitura = arq.leitura
    avaliacao = obter_avaliacao(db, CHAVE_AVALIACAO)
    if arq.modo == "upload":
        url_origem, last_modified_origem = _texto(url_origem, 500), _texto(last_modified_origem, 64)
        arquivo_nome, versao = (nome or "arquivo.xlsx")[:255], _versao_rotulo(nome)
        arquivo_sha256, arquivo_bytes = hashlib.sha256(conteudo).hexdigest(), len(conteudo)
    else:
        # Pacote: a origem é a do MANIFESTO (o zip do INEP), não o que foi digitado.
        url_origem, last_modified_origem = arq.url_origem, arq.last_modified_origem
        arquivo_nome, versao = arq.arquivo_nome, arq.versao_rotulo
        arquivo_sha256, arquivo_bytes = arq.arquivo_sha256, arq.arquivo_bytes or 0
        coletado_em = arq.coletado_em
    imp = ImportacaoIndicador(
        avaliacao_id=avaliacao.id, parser=leitura.parser, parser_versao=arq.versao_parser,
        fonte_nome=arq.fonte_nome, url_origem=url_origem, arquivo_nome=arquivo_nome,
        arquivo_sha256=arquivo_sha256, arquivo_bytes=arquivo_bytes,
        last_modified_origem=last_modified_origem,
        arquivo_data=leitura.arquivo_data, edicao_arquivo=leitura.edicao_arquivo,
        versao_rotulo=versao, codigo_territorio_alvo=codigo,
        citacao=arq.citacao, licenca=LICENCA, modo=arq.modo, status="previa",
        pacote_sha256=arq.pacote_sha256,
        usuario_id=usuario_id, coletado_em=coletado_em, contadores={}, resumo={})
    db.add(imp)
    db.flush()
    plano, divergencias = _planejar(db, avaliacao.id, leitura, imp)
    data_tardia = _aviso_data_depois_da_publicacao(leitura.arquivo_data, last_modified_origem)
    imp.contadores = _contadores(plano, leitura)
    imp.resumo = {"avisos": [*leitura.avisos, *divergencias, *filter(None, [data_tardia])],
                  "notas_arquivo": leitura.notas_arquivo,
                  "territorios": leitura.territorios, "aba": leitura.aba,
                  "rede_id": rede.id,      # quem importou (``feita_pela_rede``)
                  **({"pacote": _resumo_pacote(arq.manifesto)} if arq.manifesto else {})}
    return _saida(imp, mudancas=_mudancas_para_tela(plano, leitura))


def _resumo_pacote(manifesto: dict) -> dict:
    """O que fica do manifesto na importação (proveniência das entradas originais)."""
    origem = manifesto.get("origem") if isinstance(manifesto.get("origem"), dict) else {}
    campos = ("modo", "url", "arquivo_nome", "last_modified", "etag", "zip_bytes",
              "zip_sha256", "bytes_lidos")
    entradas = [{k: e.get(k) for k in ("tabela", "nome", "crc32", "bytes", "bytes_comprimidos",
                                       "data_interna", "sha256", "linhas_original",
                                       "linhas_recorte")}
                for e in manifesto.get("entradas") or [] if isinstance(e, dict)]
    return {"formato": manifesto.get("formato"), "gerado_em": manifesto.get("gerado_em"),
            "origem": {k: origem.get(k) for k in campos}, "entradas": entradas}


def _versao_rotulo(nome: str) -> str | None:
    base = (nome or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    base = base.rsplit(".", 1)[0]
    if base.lower().startswith("resultados_e_metas_"):
        base = base[len("resultados_e_metas_"):]
    return base[:60] or None


def _saida(imp: ImportacaoIndicador, *, mudancas: list[dict] | None = None) -> dict:
    resumo = imp.resumo or {}
    return {
        "id": imp.id, "status": imp.status,
        "arquivo_nome": imp.arquivo_nome, "arquivo_sha256": imp.arquivo_sha256,
        "arquivo_data": imp.arquivo_data.isoformat() if imp.arquivo_data else None,
        "edicao_arquivo": imp.edicao_arquivo, "versao_rotulo": imp.versao_rotulo,
        "url_origem": imp.url_origem, "last_modified_origem": imp.last_modified_origem,
        "codigo_territorio_alvo": imp.codigo_territorio_alvo,
        "parser": imp.parser, "modo": imp.modo, "pacote_sha256": imp.pacote_sha256,
        "contadores": imp.contadores or {}, "avisos": resumo.get("avisos", []),
        "notas_arquivo": resumo.get("notas_arquivo", []),
        "territorios": resumo.get("territorios", {}),
        "created_at": imp.created_at.isoformat() if imp.created_at else None,
        "aplicado_em": imp.aplicado_em.isoformat() if imp.aplicado_em else None,
        "desfeito_em": imp.desfeito_em.isoformat() if imp.desfeito_em else None,
        **({"mudancas": mudancas} if mudancas is not None else {}),
    }


def resumo_importacao(imp: ImportacaoIndicador) -> dict:
    return _saida(imp)


# --- Aplicação ----------------------------------------------------------------

def _isoformat(valor):
    return valor.isoformat() if isinstance(valor, datetime) else valor


def aplicar(db: Session, rede: Rede, previa_id: int, conteudo: bytes, nome: str, *,
            usuario_id: int | None) -> dict:
    """Grava o que a prévia mostrou (recalculado sobre o estado atual), numa
    transação só (o commit é do chamador). Reaplicar o mesmo arquivo não muda nada."""
    codigo = _exigir_codigo(rede)
    imp = db.get(ImportacaoIndicador, previa_id)
    avaliacao = obter_avaliacao(db, CHAVE_AVALIACAO)
    if imp is None or imp.avaliacao_id != avaliacao.id or not feita_pela_rede(imp, rede):
        raise LookupError("Prévia não encontrada para esta rede.")
    if imp.status != "previa":
        raise ImportacaoRecusada(
            f"Esta prévia já foi {'aplicada' if imp.status == 'aplicada' else imp.status}. "
            "Para importar de novo, gere uma prévia nova.")
    # O sha256 conferido é o do que foi ENVIADO: o da planilha, ou o do pacote
    # (``arquivo_sha256`` do pacote é o da entrada original do zip do INEP).
    if hashlib.sha256(conteudo).hexdigest() != (imp.pacote_sha256 or imp.arquivo_sha256):
        raise ImportacaoRecusada(
            "O arquivo enviado não é o mesmo da prévia (sha256 diferente). Envie o mesmo "
            "arquivo, ou gere uma prévia nova. Nada foi gravado.")
    leitura = _ler_arquivo(conteudo, nome, codigo).leitura
    plano, divergencias = _planejar(db, avaliacao.id, leitura, imp)
    agora = _agora()
    criadas, alteradas = [], []
    for p in plano:
        if p["tipo"] == "igual":
            continue
        chave = _chave_dict(p["chave"])
        if p["tipo"] == "nova":
            db.add(IndicadorReferencia(avaliacao_id=avaliacao.id, **chave, **p["depois"],
                                       created_at=agora, updated_at=agora))
            criadas.append({"chave": chave, "depois": p["depois"]})
            continue
        linha: IndicadorReferencia = p["linha"]
        alteradas.append({"chave": chave, "antes": {**p["antes"],
                                                    "updated_at": _isoformat(linha.updated_at)},
                          "depois": p["depois"]})
        for campo, valor in p["depois"].items():
            setattr(linha, campo, valor)
        linha.updated_at = agora
    imp.status = "aplicada"
    imp.aplicado_em = agora
    imp.usuario_id = usuario_id or imp.usuario_id
    data_tardia = _aviso_data_depois_da_publicacao(leitura.arquivo_data,
                                                   imp.last_modified_origem)
    imp.contadores = _contadores(plano, leitura)
    imp.resumo = {**(imp.resumo or {}),
                  "avisos": [*leitura.avisos, *divergencias, *filter(None, [data_tardia])],
                  "notas_arquivo": leitura.notas_arquivo, "territorios": leitura.territorios}
    # Fora do ``resumo`` (coluna própria, ``deferred``): as consultas não o leem.
    # ``chaves``: TODAS as que o plano viu (inclusive as iguais) — é o que decide o
    # conflito no desfazer de uma importação anterior.
    imp.desfazer = {"criadas": criadas, "alteradas": alteradas,
                    "chaves": [_chave_dict(p["chave"]) for p in plano]}
    db.flush()
    return _saida(imp, mudancas=_mudancas_para_tela(plano, leitura))


# --- Desfazer -----------------------------------------------------------------

def _linha_por_chave(db: Session, avaliacao_id: int, chave: dict) -> IndicadorReferencia | None:
    filtros = [IndicadorReferencia.avaliacao_id == avaliacao_id]
    filtros += [getattr(IndicadorReferencia, c) == chave[c] for c in _CAMPOS_CHAVE]
    return db.execute(select(IndicadorReferencia).where(*filtros)).scalar_one_or_none()


def _mesmo_estado(linha: IndicadorReferencia, esperado: dict) -> bool:
    return all(getattr(linha, c) == esperado.get(c) for c in (*_CAMPOS_VALOR, *_CAMPOS_FONTE))


def _posicao(imp: ImportacaoIndicador) -> tuple:
    return (imp.aplicado_em or _MINIMO, imp.id or 0)


def plano_desfazer(imp: ImportacaoIndicador) -> dict | None:
    """O plano de desfazer da aplicação (coluna ``desfazer``). Reserva: uma importação
    gravada quando o plano ficava em ``resumo['desfazer']`` (banco local que aplicou a
    0034 antes da coluna existir, depois do reparo descrito na 0034 — a coluna criada,
    nula; sem ela, nem a lista carrega). None = APLICADA SEM PLANO — não dá para desfazer
    exatamente (o desfazer recusa em vez de marcá-la desfeita sem restaurar nada)."""
    if imp.desfazer is not None:
        return imp.desfazer
    return (imp.resumo or {}).get("desfazer")


def carregar_planos(db: Session, importacoes: list[ImportacaoIndicador]) -> None:
    """Carrega a coluna ``desfazer`` (deferred) de várias importações num SELECT só
    (por lote de ids), em vez de um SELECT por importação a cada ``imp.desfazer`` — a
    lista e o desfazer conferem o conflito contra TODAS as aplicadas posteriores. O
    SELECT popula as instâncias que já estão na sessão."""
    ids = sorted({i.id for i in importacoes if "desfazer" in sa_inspect(i).unloaded})
    for inicio in range(0, len(ids), 500):
        db.execute(select(ImportacaoIndicador)
                   .where(ImportacaoIndicador.id.in_(ids[inicio:inicio + 500]))
                   .options(undefer(ImportacaoIndicador.desfazer))).scalars().all()


MSG_SEM_PLANO = ("Esta importação não guardou o estado anterior dos números (plano de "
                 "desfazer); desfazê-la não voltaria ao estado anterior. Nada foi alterado.")


def _tocadas(imp: ImportacaoIndicador) -> dict[tuple, dict]:
    """Chaves que a importação CRIOU ou ALTEROU (chave → chave em dict)."""
    plano = plano_desfazer(imp) or {}
    return {_chave_tupla(item["chave"]): item["chave"]
            for item in [*plano.get("criadas", []), *plano.get("alteradas", [])]}


def _vistas(imp: ImportacaoIndicador) -> set[tuple] | None:
    """TODAS as chaves que o plano da importação viu (desde a E3); None se a
    importação é anterior e não guardou a lista."""
    plano = plano_desfazer(imp) or {}
    if "chaves" not in plano:
        return None
    return {_chave_tupla(c) for c in plano["chaves"]}


def _conflito(imp: ImportacaoIndicador, posteriores: list[ImportacaoIndicador]):
    """``(posterior, chaves em comum)`` da 1ª importação aplicada DEPOIS de ``imp``
    que viu um número que ``imp`` tocou — ou None. Sem a lista de chaves (importação
    anterior à E3), é conservador: basta a posterior ter tocado o mesmo território."""
    tocadas = _tocadas(imp)
    if not tocadas:
        return None
    for posterior in posteriores:
        vistas = _vistas(posterior)
        if vistas is None:
            territorios = (set(((posterior.resumo or {}).get("territorios") or {}).keys())
                           | {k[3] for k in _tocadas(posterior)})
            comuns = [k for k in tocadas if k[3] in territorios]
        else:
            comuns = [k for k in tocadas if k in vistas]
        if comuns:
            return posterior, comuns
    return None


def _aplicadas(db: Session, avaliacao_id: int) -> list[ImportacaoIndicador]:
    return sorted(db.execute(select(ImportacaoIndicador).where(
        ImportacaoIndicador.avaliacao_id == avaliacao_id,
        ImportacaoIndicador.status == "aplicada")).scalars(), key=_posicao)


def desfazer(db: Session, rede: Rede, importacao_id: int, *, usuario_id: int | None) -> dict:
    """Volta EXATAMENTE ao estado anterior à aplicação desta importação (o commit é
    do chamador). Recusa se uma aplicada depois dela viu um número que ela tocou."""
    avaliacao = obter_avaliacao(db, CHAVE_AVALIACAO)
    imp = db.get(ImportacaoIndicador, importacao_id)
    if imp is None or imp.avaliacao_id != avaliacao.id or not feita_pela_rede(imp, rede):
        raise LookupError("Importação não encontrada para esta rede.")
    if imp.status != "aplicada":
        raise ImportacaoRecusada(
            "Só uma importação APLICADA pode ser desfeita "
            f"(esta está como “{imp.status}”).")
    posteriores = [i for i in _aplicadas(db, avaliacao.id) if _posicao(i) > _posicao(imp)]
    carregar_planos(db, [imp, *posteriores])
    if plano_desfazer(imp) is None:
        raise ImportacaoRecusada(MSG_SEM_PLANO)
    conflito = _conflito(imp, posteriores)
    if conflito:
        posterior, comuns = conflito
        exemplo = _chave_dict(comuns[0])
        raise ImportacaoRecusada(
            f"A importação #{posterior.id} ({posterior.arquivo_nome}), aplicada depois desta, "
            f"usa {len(comuns)} dos números que esta importação gravou (ex.: "
            f"{_rotulo_numero(exemplo['indicador'], exemplo['nivel'], exemplo['edicao'])} de "
            f"{exemplo['codigo_territorio']}). Desfazer esta agora não voltaria exatamente ao "
            f"estado anterior: desfaça antes a #{posterior.id} (e as que vierem depois dela "
            "nos mesmos números). Nada foi alterado.")
    plano = plano_desfazer(imp) or {}
    plano = {"criadas": plano.get("criadas", []), "alteradas": plano.get("alteradas", [])}
    alvos = []
    for item in plano["criadas"]:
        linha = _linha_por_chave(db, avaliacao.id, item["chave"])
        if linha is None or not _mesmo_estado(linha, item["depois"]):
            raise ImportacaoRecusada(_MSG_ESTADO_MUDOU)
        alvos.append(("apagar", linha, None))
    for item in plano["alteradas"]:
        linha = _linha_por_chave(db, avaliacao.id, item["chave"])
        if linha is None or not _mesmo_estado(linha, item["depois"]):
            raise ImportacaoRecusada(_MSG_ESTADO_MUDOU)
        alvos.append(("restaurar", linha, item["antes"]))
    # Conferido TUDO antes de mexer em qualquer linha (ou desfaz tudo, ou nada).
    for acao, linha, antes in alvos:
        if acao == "apagar":
            db.delete(linha)
            continue
        for campo in (*_CAMPOS_VALOR, *_CAMPOS_FONTE):
            setattr(linha, campo, antes[campo])
        quando = antes.get("updated_at")
        linha.updated_at = datetime.fromisoformat(quando) if quando else linha.updated_at
    imp.status = "desfeita"
    imp.desfeito_em = _agora()
    imp.contadores = {**(imp.contadores or {}),
                      "desfeitas": len(plano["criadas"]) + len(plano["alteradas"])}
    db.flush()
    return _saida(imp)


_MSG_ESTADO_MUDOU = ("Os números desta importação já não estão como ela os deixou; desfazer "
                     "agora não voltaria ao estado anterior. Nada foi alterado.")


def listar(db: Session, rede: Rede) -> list[dict]:
    """Importações do ICA recortadas para esta rede (mais recentes primeiro)."""
    codigo = codigo_ibge_da_rede(rede)
    if codigo is None:
        return []
    avaliacao = obter_avaliacao(db, CHAVE_AVALIACAO)
    # Do município, as feitas por ESTA rede (``feita_pela_rede``), as 50 mais recentes.
    linhas = [i for i in db.execute(
        select(ImportacaoIndicador)
        .where(ImportacaoIndicador.avaliacao_id == avaliacao.id,
               ImportacaoIndicador.codigo_territorio_alvo == codigo)
        .order_by(ImportacaoIndicador.created_at.desc(), ImportacaoIndicador.id.desc())
        ).scalars() if feita_pela_rede(i, rede)][:50]
    # O conflito é GLOBAL (UF e Brasil são compartilhados entre redes): conta toda
    # importação aplicada depois, de qualquer rede.
    aplicadas = _aplicadas(db, avaliacao.id)
    carregar_planos(db, planos_da_lista(linhas, aplicadas))
    saida = []
    for i in linhas:
        bloqueio = None
        if i.status == "aplicada":
            conflito = _conflito(i, [p for p in aplicadas if _posicao(p) > _posicao(i)])
            bloqueio = conflito[0].id if conflito else None
        saida.append({**_saida(i), "pode_desfazer": (i.status == "aplicada" and bloqueio is None
                                                     and plano_desfazer(i) is not None),
                      "bloqueada_por": bloqueio})
    return saida


def planos_da_lista(linhas: list[ImportacaoIndicador],
                     aplicadas: list[ImportacaoIndicador]) -> list[ImportacaoIndicador]:
    """As importações cujo plano a lista lê: as aplicadas listadas e toda aplicada
    POSTERIOR à mais antiga delas (as de antes nunca entram num conflito)."""
    listadas = [i for i in linhas if i.status == "aplicada"]
    if not listadas:
        return []
    inicio = min(_posicao(i) for i in listadas)
    return [*listadas, *(p for p in aplicadas if _posicao(p) > inicio)]
