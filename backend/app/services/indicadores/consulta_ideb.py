"""Leitura do Ideb e do Saeb do 5º ano POR ESCOLA (etapa E8a) e da REDE MUNICIPAL
(etapa E8b) — ``GET /redes/{id}/indicadores/ideb``.

O que a Secretaria e o admin global leem (plano, 2.2, 3.2, 4.6, 4.7, 4.8 e 5.1;
"Correções da revisão" (2).4 e (2).5), a partir do que a E6a, a E6b e a E7 gravam:

* POR ESCOLA da rede, em ordem de NOME (sem ranking), a série 2005–2025 do Ideb, do
  Saeb do 5º ano (LP e MT), de N, de P, da aprovação (1º ao 5º ano e por série) e da
  meta do 1º ciclo (2007–2021) — o Ideb e o Saeb de ``resultados_avaliacao``; o resto
  de ``indicadores_referencia``;
* META × OBSERVADO na precisão PUBLICADA (o Ideb e a meta com 1 casa, mesmo quando a
  coluna do arquivo só tem números inteiros): "atingiu" (Ideb ≥ meta — o empate nessa
  precisão conta como meta atingida) ou "nao_atingiu". Não há "inconclusivo" como no
  ICA: o Ideb de 1 casa É o número oficial, e não existe valor oficial mais preciso que
  desfaça o empate. Depois de 2021 o INEP não definiu meta: nada é comparado;
* AUSÊNCIA ≠ ZERO: o "-" e o "ND" do arquivo são valor nulo + ``nao_divulgado`` ("Ideb
  não divulgado"); a escola sem linha no arquivo, sem código INEP ou com o código
  cadastrado/trocado depois da importação diz o motivo — nunca 0;
* PROVENIÊNCIA em cada número: ``fonte_id`` → ``fontes`` (arquivo, edição, data do
  arquivo e da importação). Os números gravados ANTES pelo botão de 1 clique (sem
  ``importacao_id``) vêm MARCADOS ``sem_registro``, com o texto da fonte antiga e a
  data da gravação — e ``difere_do_oficial`` quando uma importação oficial recusou
  (resposta "não") trocá-los pelo número diferente do arquivo;
* CADASTRO QUE MUDOU DEPOIS DA IMPORTAÇÃO (a regra do SARESP, ``consulta_saresp``):
  um número oficial só vale se a importação aplicada da edição que traz a linha da
  escola casou a escola com o código INEP ATUAL dela; senão, nada dela nessa edição e
  o motivo pede a reimportação. O arquivo mais novo que não traz uma escola não apaga
  o número dela (o pipeline não apaga): ele continua na tela, com a fonte da
  importação que o gravou; "fora do arquivo" só quando nenhuma importação aplicada da
  edição trouxe a escola;
* COBERTURA por edição: escolas com Ideb e com Saeb, sem resultado (com o motivo),
  sem linha no arquivo, sem código INEP, e os códigos do arquivo sem escola no
  cadastro — sempre pelo CÓDIGO, nunca pelo nome;
* PARTICIPAÇÃO por escola: não existe nos arquivos autorizados (só no boletim do
  Sistema Saeb, que depende da decisão D8). A API diz isso e não infere
  "participação baixa" (plano, 4.6 e (2).5);
* REDE MUNICIPAL, SP e BRASIL (E8b, ``consulta_ideb_rede``): o Ideb da rede com as
  metas e a comparação na MESMA rede (Brasil nas redes municipais; a UF, que o arquivo
  do INEP só traz na rede pública, como contexto rotulado de OUTRA rede); o Saeb do 5º
  ano da planilha (média e níveis, localização Total) da rede, da UF e do Brasil nas
  redes municipais; o contexto AMOSTRAL do 2º ano e a taxa de alfabetização de 2021 (não
  é o ICA). A nota do Saeb que vem DENTRO do Ideb fica só na seção do Ideb, com o
  universo (escolas urbanas), e nunca se cruza com a média da planilha. O Constela não
  calcula a média das escolas no lugar do número oficial da rede;
* PENDENTES, sem "aguardando": o que a base não importou (pelo nome do arquivo) e o
  que está adiado (a planilha do Saeb 2023, RAR/XLSB).

Só LÊ (nem cria a linha do catálogo). Sem dado importado, as listas vêm vazias e a
tela diz "sem resultado importado" — nunca 0.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (AvaliacaoExterna, ImportacaoIndicador, IndicadorReferencia, Rede,
                        ResultadoAvaliacao)
from app.services.avaliacoes import CATALOGO, normalizar_inep
from app.services.indicadores import consulta_ideb_rede, ica, ideb, saeb_planilha, seduc
from app.services.indicadores import leituras_da_requisicao as leituras
from app.services.indicadores.consulta import _fonte
# As regras de meta valem para a escola e para o território (``consulta_ideb_rede``).
from app.services.indicadores.consulta_ideb_rede import (SEM_META_ANTES_DO_CICLO,  # noqa: F401
                                                         SEM_META_DEPOIS_DO_CICLO,
                                                         SEM_META_SEM_ARQUIVO)
from app.services.indicadores.consulta_ideb_rede import comparar_meta as _comparacao
from app.services.indicadores.consulta_saresp import (MOTIVO_CADASTRADO_DEPOIS,
                                                      MOTIVO_FORA_DO_ARQUIVO,
                                                      MOTIVO_INEP_ALTERADO,
                                                      MOTIVO_SEM_IMPORTACAO,
                                                      _arquivo_da_escola, _descarte)
from app.services.indicadores.pipeline import codigo_ibge_da_rede, feita_pela_rede

# Campos por escola em `resultados_avaliacao` (componente gravado → campo da API).
CAMPOS_RESULTADO = ("ideb", "saeb_lp", "saeb_mt")
_CAMPO_DO_COMPONENTE = {"portugues": "saeb_lp", "matematica": "saeb_mt"}
ETAPAS_APROVACAO = ("anos_iniciais", "1_ano", "2_ano", "3_ano", "4_ano", "5_ano")
_IND_REFERENCIA = (ideb.IND_NOTA_N, ideb.IND_RENDIMENTO_P, ideb.IND_APROVACAO, ideb.IND_META)

# Precisão PUBLICADA pelo INEP no arquivo (conferida no de 2023: Ideb e meta com 1 casa
# em todas as edições; Saeb com 2). `resultados_avaliacao` não guarda a precisão e o
# float perde os zeros finais (6,0 → 6; 412,50 → 412,5): sem esta tabela, a tela
# escreveria "6" e "412,5" e a comparação com a meta sairia noutra precisão.
CASAS_PUBLICADAS = {"ideb": 1, "saeb_lp": 2, "saeb_mt": 2}
# O mesmo piso para a meta e a aprovação de `indicadores_referencia` (formato "0.0" do
# INEP). A E6a grava as casas da COLUNA pelas casas escritas no recorte: se todas as
# metas (ou aprovações) da rede numa edição são inteiras, a planilha devolve int e a
# coluna sai com 0 casas — e 1,5 × meta 2 viraria 2 × 2, com "meta 2" na tela.
CASAS_MINIMAS_REFERENCIA = {ideb.IND_META: CASAS_PUBLICADAS["ideb"], ideb.IND_APROVACAO: 1}

CAMPOS = {
    "ideb": {"rotulo": "Ideb", "unidade": ideb.UNIDADE_IDEB, "casas_publicadas": 1},
    "saeb_lp": {"rotulo": "Saeb do 5º ano — Língua Portuguesa", "unidade": ideb.UNIDADE_SAEB,
                "casas_publicadas": 2},
    "saeb_mt": {"rotulo": "Saeb do 5º ano — Matemática", "unidade": ideb.UNIDADE_SAEB,
                "casas_publicadas": 2},
    "nota_n": {"rotulo": "Nota média padronizada (N)", "unidade": ideb.UNIDADE_IDEB},
    "rendimento_p": {"rotulo": "Indicador de rendimento (P)", "unidade": ideb.UNIDADE_P},
    "aprovacao": {"rotulo": "Taxa de aprovação", "unidade": ideb.UNIDADE_APROVACAO},
    "meta": {"rotulo": "Meta do Ideb (1º ciclo)", "unidade": ideb.UNIDADE_IDEB},
}

PROVENIENCIA_OFICIAL = "oficial"
PROVENIENCIA_SEM_REGISTRO = "sem_registro"
# A escola casou com o arquivo, mas não há número dela nesta edição.
MOTIVO_SEM_RESULTADO = "sem_resultado"

def periodo(edicoes: list[int]) -> str:
    """"2019–2023"; com uma edição só, só o ano ("2023", não "2023–2023")."""
    if not edicoes:
        return "2005–2023"
    return str(edicoes[0]) if len(edicoes) == 1 else f"{edicoes[0]}–{edicoes[-1]}"


def _avisos(edicoes: list[int]) -> dict:
    return {
        "comparabilidade": (
            f"A série do Ideb e do Saeb do 5º ano ({periodo(edicoes)}) não é comparável em "
            "todo o período: o universo avaliado e os critérios mudaram ao longo das edições "
            "(o mínimo de alunos, a entrada das escolas rurais, o critério de divulgação — "
            "detalhes nas notas técnicas do INEP). O aviso vale para a série TODA, não só "
            "para 2021: compare edições com cuidado."),
        "pandemia": ("2021 foi aplicado na pandemia: o INEP publicou uma nota própria sobre o "
                     "modo de ler o Ideb e o Saeb dessa edição (ver as notas do arquivo oficial)."),
        "sem_ranking": ("A tabela por escola está em ordem alfabética: não é ranking e não "
                        "serve para ordenar escolas."),
        "ausencia": ("Sem resultado não é zero: “não divulgado” é o “-” ou o “ND” do arquivo "
                     "do INEP (a legenda do INEP explica cada ND); o Constela não inventa a "
                     "causa."),
        "participacao": (
            "A participação dos alunos de cada escola no Saeb não aparece: ela não está no "
            "arquivo do Ideb por escola, só no boletim da escola do Sistema Saeb, que depende "
            "de uma decisão ainda pendente (D8). Sem ela, a falta de resultado fica como "
            "“não divulgado”, sem supor participação baixa."),
        "metas": ("Metas do Ideb: só as do 1º ciclo, de 2007 a 2021. Depois de 2021 (de 2023 "
                  "em diante) o INEP não definiu meta: o Constela não compara."),
        "precisao": ("Atingiu ou não a meta: o Ideb e a meta comparados na precisão publicada "
                     "pelo INEP (1 casa decimal). Ideb igual ou acima da meta nessa precisão = "
                     "atingiu."),
        "escala": ("O Saeb do 5º ano tem escala própria: não se compara com o SARESP nem com o "
                   "ICA."),
        "sem_registro": (
            "Números marcados “sem registro oficial” foram gravados antes, pelo botão de "
            "importação em 1 clique, sem prévia nem registro do arquivo. A importação oficial "
            "só os mantém quando são iguais aos do arquivo; um número diferente só é trocado "
            "com confirmação explícita."),
        "media_das_escolas": ("O Constela não calcula a média das escolas no lugar do número "
                              "oficial da rede: o Ideb e o Saeb da rede vêm dos arquivos do "
                              "INEP."),
    }


def _iso(valor):
    return valor.isoformat() if valor else None


_PARSERS_COM_NOME = (ideb.PARSER, ideb.PARSER_MUNICIPIOS, saeb_planilha.PARSER)


def _nome_do_municipio(db: Session, codigo: str | None,
                       aplicadas_ideb: list[ImportacaoIndicador] | None = None) -> str | None:
    """O nome do município como no arquivo do INEP (o resumo da importação aplicada mais
    nova do Ideb ou da planilha do Saeb que o recortou); sem importação, None.

    ``aplicadas_ideb``: as do Ideb por escola já lidas nesta requisição (``_aplicadas``)
    — não são buscadas de novo; só as dos outros parsers."""
    if codigo is None:
        return None
    parsers = _PARSERS_COM_NOME if aplicadas_ideb is None else tuple(
        p for p in _PARSERS_COM_NOME if p != ideb.PARSER)
    lidas = list(aplicadas_ideb or []) + leituras.aplicadas_do_territorio(db, codigo,
                                                                          tuple(parsers))
    nome = None
    for imp in sorted(lidas, key=lambda i: (i.edicao_arquivo, i.id)):
        nome = ((imp.resumo or {}).get("territorios") or {}).get(codigo) or nome
    return nome


def _avaliacao(db: Session, chave: str) -> AvaliacaoExterna | None:
    return leituras.avaliacao(db, chave)


def _casas(valor: float | None, campo: str) -> int | None:
    """A precisão publicada do campo; mais casas só se o próprio número tiver (até 4)."""
    if valor is None:
        return None
    texto = f"{valor:.6f}".rstrip("0").rstrip(".")
    proprias = len(texto.split(".", 1)[1]) if "." in texto else 0
    return max(CASAS_PUBLICADAS[campo], min(proprias, 4))


def _mesmo_inep(r: ResultadoAvaliacao, inep: str | None) -> bool:
    return bool(inep) and (r.codigo_inep is None or normalizar_inep(r.codigo_inep) == inep)


# --- Importações -----------------------------------------------------------------

def _aplicadas(db: Session, rede: Rede, codigo: str | None) -> list[ImportacaoIndicador]:
    """As importações APLICADAS do Ideb por escola para o município da rede, feitas por
    ESTA rede (``feita_pela_rede``): as escolas de outra rede com o mesmo código IBGE não
    estão nas casadas da importação dela, e conferi-las contra ela esconderia o Ideb
    oficial com o motivo falso "cadastrada depois da importação"."""
    if codigo is None:
        return []
    return sorted((i for i in leituras.aplicadas_do_territorio(db, codigo, (ideb.PARSER,))
                   if feita_pela_rede(i, rede)),
                  key=lambda i: (i.aplicado_em or datetime.min, i.id))


def _da_edicao(aplicadas: list[ImportacaoIndicador], edicao: int) -> list[ImportacaoIndicador]:
    """As importações aplicadas que trazem a edição, na precedência do pipeline (a que
    VALE primeiro): a divulgação mais nova; na mesma, a data interna mais nova; depois,
    a aplicada por último."""
    candidatas = [i for i in aplicadas if edicao in ((i.resumo or {}).get("edicoes") or [])]
    return sorted(candidatas, reverse=True,
                  key=lambda i: (i.edicao_arquivo, i.arquivo_data or datetime.min,
                                 i.aplicado_em or datetime.min, i.id))


def _arquivo_da_edicao(aplicadas: list[ImportacaoIndicador], edicao: int):
    """O arquivo que VALE para a edição (o 1º de ``_da_edicao``); None sem importação."""
    candidatas = _da_edicao(aplicadas, edicao)
    return candidatas[0] if candidatas else None


def _conteudo(imp: ImportacaoIndicador) -> dict:
    """O que a importação viu no arquivo, congelado no resumo: ``casadas`` (escola →
    INEP com que casou) e ``linhas`` (as escolas da rede no arquivo, pelo código)."""
    resumo = imp.resumo or {}
    casadas_lista = list(resumo.get("escolas_casadas") or [])
    linhas: dict[str, dict] = {}
    for f in (*casadas_lista, *(resumo.get("fora_do_cadastro") or [])):
        inep = normalizar_inep(f.get("codigo_inep"))
        if inep:
            linhas.setdefault(inep, {"codigo_inep": inep,
                                     "nome_no_arquivo": f.get("nome_no_arquivo")})
    return {"casadas": {c.get("escola_id"): normalizar_inep(c.get("codigo_inep"))
                        for c in casadas_lista},
            "linhas": linhas}


def _recusadas(aplicadas: list[ImportacaoIndicador]) -> dict[tuple, dict]:
    """Números sem proveniência oficial que uma importação aplicada NÃO trocou pelo do
    arquivo (resposta "não" à substituição): chave → ANTES visto e a importação."""
    saida: dict[tuple, dict] = {}
    for imp in aplicadas:                     # em ordem de aplicação: a mais nova vence
        resumo = imp.resumo or {}
        if resumo.get("substituir_calculadas") is not False:
            continue
        # item = [avaliação, edição, indicador, escola, etapa, componente, valor, motivo, ...]
        for item in resumo.get("substituicoes_previa") or []:
            if len(item) >= 8:
                saida[tuple(item[:6])] = {"valor": item[6], "motivo": item[7],
                                          "importacao_id": imp.id}
    return saida


# --- Números ---------------------------------------------------------------------

def _numero_resultado(r: ResultadoAvaliacao, campo: str, imps: dict,
                      recusadas: dict[tuple, dict]) -> dict:
    oficial = r.importacao_id is not None
    saida = {"valor": r.valor, "casas_decimais": _casas(r.valor, campo),
             "motivo_ausencia": r.motivo_ausencia,
             "proveniencia": PROVENIENCIA_OFICIAL if oficial else PROVENIENCIA_SEM_REGISTRO,
             "fonte_id": r.importacao_id if oficial and r.importacao_id in imps else None}
    if not oficial:
        recusa = recusadas.get((r.avaliacao_id, r.edicao, r.indicador, r.escola_id, r.etapa,
                                r.componente))
        difere = bool(recusa and recusa["valor"] == r.valor
                      and recusa["motivo"] == r.motivo_ausencia)
        saida.update(fonte_texto=r.fonte, gravado_em=_iso(r.created_at),
                     difere_do_oficial=difere,
                     recusado_na_importacao=recusa["importacao_id"] if difere else None)
    return saida


def _ref(referencia: dict, imps: dict, chave: tuple[str, int] | None, indicador: str,
         etapa: str = ideb.ETAPA_IDEB) -> dict | None:
    """N, P, aprovação ou meta da escola (``chave`` = (INEP, edição); None = descarte).
    A meta e a aprovação nunca abaixo da precisão publicada (``CASAS_MINIMAS_REFERENCIA``)."""
    ln = referencia.get((*chave, indicador, etapa)) if chave is not None else None
    if ln is None:
        return None
    casas = ln.casas_decimais
    if indicador in CASAS_MINIMAS_REFERENCIA:
        casas = max(CASAS_MINIMAS_REFERENCIA[indicador], casas or 0)
    return {"valor": ln.valor, "casas_decimais": casas,
            "motivo_ausencia": ln.motivo_ausencia, "proveniencia": PROVENIENCIA_OFICIAL,
            "fonte_id": ln.importacao_id if ln.importacao_id in imps else None}


def _sem_meta(edicao: int, anos_meta: list[int]) -> str | None:
    """A regra comum (``consulta_ideb_rede.motivo_sem_meta``): a escola sem meta nenhuma
    só tem números do 1 clique."""
    return consulta_ideb_rede.motivo_sem_meta(edicao, anos_meta, SEM_META_SEM_ARQUIVO)


def _motivo(ideb_numero: dict | None, descarte: str | None,
            imp_arquivo: ImportacaoIndicador | None) -> str:
    """Por que a escola não tem Ideb na edição (um motivo só, o mesmo na tabela e na
    cobertura)."""
    if ideb_numero is not None and ideb_numero["valor"] is None:
        return ideb_numero["motivo_ausencia"] or ideb.MOTIVO
    if descarte is not None:
        return descarte
    if imp_arquivo is None:
        return MOTIVO_SEM_IMPORTACAO
    return MOTIVO_SEM_RESULTADO


def _variacao(serie: list[dict]) -> None:
    """Variação do Ideb desde a edição ANTERIOR da série (na precisão publicada), só
    quando as duas têm número — sem número, nada (nunca contra 0)."""
    anterior = None
    for ed in serie:
        atual = ed["ideb"]["valor"] if ed["ideb"] else None
        ed["variacao_ideb"] = None
        if atual is not None and anterior is not None:
            casas = CASAS_PUBLICADAS["ideb"]
            ed["variacao_ideb"] = {
                "desde": anterior[0],
                "diferenca": round(ica.arredondar(atual, casas) - ica.arredondar(anterior[1], casas),
                                   casas),
                "casas_decimais": casas}
        anterior = (ed["edicao"], atual) if atual is not None else None


# --- Entrada ---------------------------------------------------------------------

def ideb_da_rede(db: Session, rede: Rede) -> dict:
    codigo = codigo_ibge_da_rede(rede)
    av_ideb = _avaliacao(db, ideb.AVALIACAO_IDEB)
    av_saeb = _avaliacao(db, ideb.AVALIACAO_SAEB)

    # ORDEM POR NOME (sem ranking), a mesma no SQLite e no PostgreSQL: sem acento e
    # sem caixa, no Python (a ordenação do banco depende da collation).
    escolas = sorted(leituras.escolas_da_rede(db, rede.id),
                     key=lambda e: (seduc.sem_acento(e.nome or "").casefold(), e.id))
    inep_de = {e.id: normalizar_inep(e.codigo_inep) for e in escolas}
    ineps = {i for i in inep_de.values() if i}

    # resultados_avaliacao: o Ideb (anos iniciais) e o Saeb do 5º ano (LP e MT), por escola.
    resultados: dict[tuple[int, int, str], ResultadoAvaliacao] = {}
    sem_turma = or_(ResultadoAvaliacao.turma.is_(None), ResultadoAvaliacao.turma == "")
    # Com a leitura única ligada, os mesmos filtros sobre o que a requisição já leu (os
    # resultados sem turma das escolas da rede; as referências do município e das escolas).
    lote = leituras.ativa(db)
    if escolas and av_ideb is not None:
        if lote:
            lidos = [r for r in leituras.resultados_sem_turma(db, set(inep_de), av_ideb.id)
                     if r.indicador == ideb.IND_IDEB and r.etapa == ideb.ETAPA_IDEB
                     and r.componente in (None, "")]
        else:
            lidos = db.execute(select(ResultadoAvaliacao).where(
                ResultadoAvaliacao.avaliacao_id == av_ideb.id,
                ResultadoAvaliacao.escola_id.in_(set(inep_de)),
                ResultadoAvaliacao.indicador == ideb.IND_IDEB,
                ResultadoAvaliacao.etapa == ideb.ETAPA_IDEB,
                or_(ResultadoAvaliacao.componente.is_(None), ResultadoAvaliacao.componente == ""),
                sem_turma)).scalars()
        for r in lidos:
            resultados[(r.escola_id, r.edicao, "ideb")] = r
    if escolas and av_saeb is not None:
        if lote:
            lidos = [r for r in leituras.resultados_sem_turma(db, set(inep_de), av_saeb.id)
                     if r.indicador == ideb.IND_PROFICIENCIA and r.etapa == ideb.ETAPA_SAEB
                     and r.componente in tuple(_CAMPO_DO_COMPONENTE)]
        else:
            lidos = db.execute(select(ResultadoAvaliacao).where(
                ResultadoAvaliacao.avaliacao_id == av_saeb.id,
                ResultadoAvaliacao.escola_id.in_(set(inep_de)),
                ResultadoAvaliacao.indicador == ideb.IND_PROFICIENCIA,
                ResultadoAvaliacao.etapa == ideb.ETAPA_SAEB,
                ResultadoAvaliacao.componente.in_(tuple(_CAMPO_DO_COMPONENTE)),
                sem_turma)).scalars()
        for r in lidos:
            resultados[(r.escola_id, r.edicao, _CAMPO_DO_COMPONENTE[r.componente])] = r

    # indicadores_referencia: N, P, aprovação e meta da escola, pelo código INEP.
    referencia: dict[tuple[str, int, str, str], IndicadorReferencia] = {}
    if codigo is not None and av_ideb is not None and ineps:
        if lote:
            linhas = [ln for ln in leituras.referencias(db, codigo, frozenset(ineps))
                      if ln.avaliacao_id == av_ideb.id and ln.abrangencia == "escola"
                      and ln.codigo_territorio == codigo and ln.rede_ensino == "municipal"
                      and ln.localizacao == "total" and ln.codigo_inep in ineps
                      and ln.indicador in _IND_REFERENCIA]
        else:
            linhas = db.execute(select(IndicadorReferencia).where(
                IndicadorReferencia.avaliacao_id == av_ideb.id,
                IndicadorReferencia.abrangencia == "escola",
                IndicadorReferencia.codigo_territorio == codigo,
                IndicadorReferencia.rede_ensino == "municipal",
                IndicadorReferencia.localizacao == "total",
                IndicadorReferencia.codigo_inep.in_(ineps),
                IndicadorReferencia.indicador.in_(_IND_REFERENCIA))).scalars()
        for ln in linhas:
            referencia[(ln.codigo_inep, ln.edicao, ln.indicador, ln.etapa)] = ln

    aplicadas = _aplicadas(db, rede, codigo)
    # A REDE MUNICIPAL, a UF e o Brasil (E8b): Ideb do território, Saeb da planilha e o
    # contexto amostral — pelo código IBGE, nunca pela média das escolas.
    nome_mun = _nome_do_municipio(db, codigo, aplicadas)
    rede_mun, contexto = consulta_ideb_rede.rede_municipal(db, codigo, nome_mun)
    ids = ({r.importacao_id for r in resultados.values()}
           | {ln.importacao_id for ln in referencia.values()}
           | {i.id for i in aplicadas}
           | consulta_ideb_rede.ids_de_importacao(rede_mun, contexto)) - {None}
    # As aplicadas já estão lidas: só as outras fontes vão ao banco.
    imps = {i.id: i for i in aplicadas}
    faltam = ids - set(imps)
    if faltam:
        imps.update(leituras.importacoes_por_id(db, faltam))

    edicoes = sorted({ed for (_, ed, _) in resultados}
                     | {ed for (_, ed, ind, _) in referencia if ind != ideb.IND_META}
                     | {ed for i in aplicadas for ed in ((i.resumo or {}).get("edicoes") or [])})
    anos_meta = sorted({a for i in aplicadas for a in ((i.resumo or {}).get("anos_meta") or [])}
                       | {ed for (_, ed, ind, _) in referencia if ind == ideb.IND_META})
    arquivo_de = {ed: _arquivo_da_edicao(aplicadas, ed) for ed in edicoes}
    conteudos = {i.id: _conteudo(i) for i in aplicadas}
    # Todas as aplicadas de cada edição, na precedência: a escola se confere contra a
    # que traz a linha dela (``_arquivo_da_escola``), não só contra a mais nova.
    arquivos_da_edicao = {ed: [conteudos[i.id] for i in _da_edicao(aplicadas, ed)]
                          for ed in edicoes}
    recusadas = _recusadas(aplicadas)

    linhas = []
    for e in escolas:
        inep = inep_de[e.id]
        serie = []
        for ed in edicoes:
            imp_arquivo = arquivo_de[ed]
            # O cadastro mudou depois da importação? Então nenhum número OFICIAL da
            # escola nesta edição (seria de outra linha do arquivo). Os números sem
            # registro oficial (1 clique) valem pelo código com que foram gravados. A
            # conferência é contra a importação que traz a linha da escola.
            descarte = _descarte(_arquivo_da_escola(arquivos_da_edicao[ed], inep), e.id, inep)
            numeros: dict[str, dict | None] = {}
            for campo in CAMPOS_RESULTADO:
                r = resultados.get((e.id, ed, campo))
                if r is None or not _mesmo_inep(r, inep):
                    numeros[campo] = None
                elif r.importacao_id is not None and descarte is not None:
                    numeros[campo] = None
                else:
                    numeros[campo] = _numero_resultado(r, campo, imps, recusadas)

            # N, P, aprovação e meta: pelo código INEP atual, só sem descarte.
            chave_ref = None if descarte is not None else (inep, ed)
            meta = _ref(referencia, imps, chave_ref, ideb.IND_META)
            aprovacao = {et: _ref(referencia, imps, chave_ref, ideb.IND_APROVACAO, et)
                         for et in ETAPAS_APROVACAO}
            entrada = {
                "edicao": ed, **numeros,
                "nota_n": _ref(referencia, imps, chave_ref, ideb.IND_NOTA_N),
                "rendimento_p": _ref(referencia, imps, chave_ref, ideb.IND_RENDIMENTO_P),
                "aprovacao": aprovacao, "meta": meta,
                "sem_meta": _sem_meta(ed, anos_meta) if meta is None else None,
                "comparacao_meta": _comparacao(ed, numeros["ideb"], meta),
            }
            todos = [*numeros.values(), entrada["nota_n"], entrada["rendimento_p"], meta,
                     *aprovacao.values()]
            entrada["no_arquivo"] = any(n is not None for n in todos)
            entrada["tem_ideb"] = bool(numeros["ideb"] and numeros["ideb"]["valor"] is not None)
            entrada["tem_saeb"] = any(numeros[c] and numeros[c]["valor"] is not None
                                      for c in ("saeb_lp", "saeb_mt"))
            entrada["motivo"] = (None if entrada["tem_ideb"]
                                 else _motivo(numeros["ideb"], descarte, imp_arquivo))
            serie.append(entrada)
        _variacao(serie)
        tem_algum = any(ed["no_arquivo"] or ed["motivo"] in (MOTIVO_CADASTRADO_DEPOIS,
                                                             MOTIVO_INEP_ALTERADO)
                        for ed in serie)
        if e.status != "ativa" and not tem_algum:
            continue                     # escola inativa sem número: fora da tela
        linhas.append({
            "escola_id": e.id, "nome": e.nome, "codigo_inep": inep, "status": e.status,
            "pendencia": None if inep else "codigo_inep", "serie": serie,
            "tem_sem_registro": any(ed[c] and ed[c]["proveniencia"] == PROVENIENCIA_SEM_REGISTRO
                                    for ed in serie for c in CAMPOS_RESULTADO),
        })

    cobertura = _cobertura(linhas, edicoes, arquivo_de, conteudos, ineps, imps)
    sem_registro = Counter(ed["edicao"] for linha in linhas for ed in linha["serie"]
                           for c in CAMPOS_RESULTADO
                           if ed[c] and ed[c]["proveniencia"] == PROVENIENCIA_SEM_REGISTRO)
    difere = sum(1 for linha in linhas for ed in linha["serie"] for c in CAMPOS_RESULTADO
                 if ed[c] and ed[c].get("difere_do_oficial"))
    fontes = [_fonte(i) for i in sorted(imps.values(),
                                        key=lambda i: (-i.edicao_arquivo, -(i.id or 0)))]
    # O aviso de comparabilidade vale para a série TODA: a das escolas e a da rede.
    avisos = _avisos(sorted({*edicoes, *rede_mun["ideb"]["edicoes"],
                             *rede_mun["saeb"]["edicoes"]}))
    tem_escolas = any(ed["no_arquivo"] for linha in linhas for ed in linha["serie"])
    return {
        "rede_id": rede.id, "rede_nome": rede.nome, "codigo_ibge": codigo,
        "municipio": nome_mun,
        "indicadores": {chave: {"chave": chave, "nome": CATALOGO[chave]["nome"],
                                "orgao": CATALOGO[chave]["orgao"],
                                "descricao": CATALOGO[chave]["descricao"]}
                        for chave in (ideb.AVALIACAO_IDEB, ideb.AVALIACAO_SAEB)},
        "pendencias": [] if codigo else ["codigo_ibge"],
        "avisos": avisos,
        "campos": CAMPOS, "edicoes": edicoes, "anos_meta": anos_meta,
        "escolas": linhas, "cobertura": cobertura,
        "sem_registro_oficial": {"total": sum(sem_registro.values()),
                                 "por_edicao": {str(k): v for k, v in sorted(sem_registro.items())},
                                 "difere_do_oficial": difere},
        "participacao": {"disponivel": False, "decisao": "D8",
                         "texto": avisos["participacao"]},
        "rede_municipal": rede_mun, "contexto_amostral": contexto,
        "pendentes": consulta_ideb_rede.pendentes(edicoes, rede_mun["ideb"], rede_mun["saeb"],
                                                  contexto),
        "fontes": fontes,
        "tem_dados_escolas": tem_escolas,
        # Há o que mostrar: escola, a rede ou a referência (UF e Brasil; o 2º ano amostral).
        "tem_dados": (tem_escolas or rede_mun["tem_dados"] or rede_mun["ideb"]["tem_dados"]
                      or rede_mun["saeb"]["tem_dados"] or contexto["tem_dados"]),
    }


def _cobertura(linhas: list[dict], edicoes: list[int], arquivo_de: dict, conteudos: dict,
               ineps_do_cadastro: set[str], imps: dict) -> list[dict]:
    """Por edição (a mais nova primeiro): com Ideb, com Saeb, sem resultado (com o
    motivo), sem linha no arquivo, sem código INEP e os códigos do arquivo sem escola
    no cadastro de HOJE (o código cadastrado depois sai daqui e aparece na escola, com
    o motivo "reimporte")."""
    saida = []
    for ed in reversed(edicoes):
        imp = arquivo_de.get(ed)
        arquivo = conteudos.get(imp.id) if imp is not None else None
        com_ideb = com_saeb = 0
        sem_resultado, sem_linha, sem_inep = [], [], []
        for linha in linhas:
            base = {"escola_id": linha["escola_id"], "nome": linha["nome"],
                    "codigo_inep": linha["codigo_inep"]}
            if not linha["codigo_inep"]:
                sem_inep.append(base)
                continue
            entrada = next(x for x in linha["serie"] if x["edicao"] == ed)
            com_saeb += entrada["tem_saeb"]
            if entrada["tem_ideb"]:
                com_ideb += 1
            elif entrada["motivo"] == MOTIVO_FORA_DO_ARQUIVO:
                sem_linha.append(base)
            else:
                sem_resultado.append({**base, "motivo": entrada["motivo"]})
        fora = ([f for inep, f in sorted(arquivo["linhas"].items())
                 if inep not in ineps_do_cadastro] if arquivo is not None else [])
        saida.append({
            "edicao": ed, "total_escolas": len(linhas), "com_ideb": com_ideb,
            "com_saeb": com_saeb, "sem_resultado": sem_resultado,
            "sem_linha_no_arquivo": sem_linha, "sem_inep": sem_inep,
            "fora_do_cadastro": fora, "arquivo_importado": imp is not None,
            "fonte_id": imp.id if imp is not None and imp.id in imps else None,
        })
    return saida
