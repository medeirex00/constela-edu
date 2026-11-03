"""Leitura do Ideb e do Saeb da REDE MUNICIPAL, de SP e do Brasil — etapa E8b (dentro de
``GET /redes/{id}/indicadores/ideb``; ``consulta_ideb`` junta este bloco ao por escola).

O que a E6b e a E7 gravam em ``indicadores_referencia`` e o que esta leitura devolve
(plano, 4.6, 4.8, 4.9 e 5.1):

* IDEB DO TERRITÓRIO (avaliação ``ideb``; arquivos do Ideb por município e de UF/Brasil):
  por edição, o Ideb, a meta do 1º ciclo (2007–2021; meta × observado na precisão
  publicada, a MESMA regra das escolas — ``comparar_meta``), N, P, a aprovação do 1º ao
  5º ano e a NOTA DO SAEB que entra no Ideb (``nota_saeb``). Essa nota fica SÓ aqui, com
  o rótulo do universo do INEP (as escolas urbanas — ``ideb_territorio.rotulo_universo``)
  e nunca é cruzada com a média da planilha do Saeb;
* COMPARAÇÃO SEMPRE NA MESMA REDE (plano, 4.8): a rede municipal do município × o Brasil
  nas redes municipais. O arquivo de UF do INEP NÃO traz a rede municipal da UF: a UF
  entra na rede PÚBLICA com ``mesma_rede = False`` e o rótulo "outra rede, só contexto",
  e a API diz por quê. Se um arquivo futuro trouxer a rede municipal da UF, ela entra
  como comparação na mesma rede (e a pública sai);
* SAEB DO 5º ANO PELA PLANILHA (avaliação ``saeb``): a média (LP e MT) e a distribuição
  por nível (LP 0–9, MT 0–10) da rede municipal, da UF e do Brasil nas redes municipais
  (a mesma dependência), na localização TOTAL — explícita na resposta —, nas edições
  importadas; e a régua dos níveis com a fonte dos cortes (``escalas``);
* CONTEXTO AMOSTRAL: as médias do Saeb do 2º ano e a taxa de alfabetização de 2021, só
  da UF e do Brasil (redes municipais), rotuladas "amostral, só contexto" e "não é o
  ICA" — nunca número da rede nem da escola;
* o que AINDA FALTA, sem "aguardando": a planilha do Saeb de 2023 (RAR/XLSB), ADIADA; e
  o que esta base não importou, pelo nome do arquivo.

A UF e o Brasil são referência PÚBLICA, pelo código (``indicadores_referencia`` não tem
rede): os números deles que uma rede importou valem para as outras redes. Por isso o que
é "da rede" — ``rede_municipal.tem_dados`` e a planilha do Saeb em ``pendentes`` — olha
só o território do MUNICÍPIO (e as importações desta rede), nunca a UF e o Brasil.

Só LÊ (nem cria a linha do catálogo). Ausência ≠ 0: sem número, valor nulo e o motivo
da fonte. A ordem é FIXA (nunca por valor): as comparações na mesma rede primeiro, o
contexto de outra rede por último.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AvaliacaoExterna, IndicadorReferencia
from app.services.indicadores import escalas, ica, ideb, ideb_territorio, saeb_planilha
from app.services.indicadores import leituras_da_requisicao as leituras
from app.services.indicadores.consulta import comparar

ABR_MUNICIPIO, ABR_UF, ABR_BRASIL = "municipio", "uf", "brasil"
PROVENIENCIA_OFICIAL = "oficial"

# Por que a edição não tem meta para comparar (a regra das escolas e da rede).
SEM_META_DEPOIS_DO_CICLO = "depois_do_1o_ciclo"     # o INEP não definiu meta (2023, 2025)
SEM_META_ANTES_DO_CICLO = "antes_das_metas"         # 2005 é o ano de referência
SEM_META_SEM_ARQUIVO = "sem_arquivo_oficial"        # escola: só números do 1 clique
SEM_META_NO_ARQUIVO = "sem_meta_no_arquivo"         # território: o arquivo não traz meta

# Precisão publicada (piso): o Ideb, a meta e a aprovação com 1 casa; as médias e as
# notas do Saeb com 2. Acima do piso, as casas que a importação gravou.
_CASAS_MINIMAS = {ideb.IND_IDEB: 1, ideb.IND_META: 1, ideb.IND_APROVACAO: 1,
                  ideb_territorio.IND_NOTA_SAEB: 2, saeb_planilha.IND_PROFICIENCIA: 2}
_IND_IDEB = (ideb.IND_IDEB, ideb.IND_META, ideb.IND_NOTA_N, ideb.IND_RENDIMENTO_P,
             ideb.IND_APROVACAO, ideb_territorio.IND_NOTA_SAEB)
COMPONENTES = ("lp", "mt")
LOCALIZACAO_CAPA = "total"
ROTULO_LOCALIZACAO = "Total (escolas urbanas e rurais)"
DESENHO_AMOSTRAL = "amostral"

# A planilha do Saeb que existe por edição (E7). A de 2023 (RAR com XLSB) está ADIADA.
EDICOES_PLANILHA_SAEB = (2019, 2021, 2025)
EDICAO_PLANILHA_ADIADA = 2023
EDICAO_TAXA_ALFABETIZACAO = 2021

# (chave, abrangência, rede de ensino, mesma rede da comparação?, posição fixa)
_IDEB_MUNICIPIO = ("rede_municipal", ABR_MUNICIPIO, "municipal", True, 0)
_IDEB_UF_MUNICIPAL = ("uf_redes_municipais", ABR_UF, "municipal", True, 1)
_IDEB_UF_PUBLICA = ("uf_rede_publica", ABR_UF, "publica", False, 1)
_IDEB_BRASIL = ("brasil_redes_municipais", ABR_BRASIL, "municipal", True, 2)
_SAEB = (("rede_municipal", ABR_MUNICIPIO), ("uf_redes_municipais", ABR_UF),
         ("brasil_redes_municipais", ABR_BRASIL))
_AMOSTRAL = (("uf_redes_municipais", ABR_UF), ("brasil_redes_municipais", ABR_BRASIL))

# Arquivos do INEP de cada parte (para dizer o que esta base NÃO importou).
ARQUIVO_IDEB_ESCOLAS = "divulgacao_anos_iniciais_escolas_AAAA.zip"
ARQUIVO_IDEB_MUNICIPIOS = "divulgacao_anos_iniciais_municipios_AAAA.zip"
ARQUIVO_IDEB_UF = "divulgacao_regioes_ufs_ideb_AAAA.zip"
ARQUIVO_IDEB_BRASIL = "divulgacao_brasil_ideb_AAAA.zip"
# A planilha do Saeb tem um nome por edição (o de 2019 é outro molde, noutra pasta do INEP).
ARQUIVO_PLANILHA_SAEB = {
    2019: "Resultados_Saeb_2019_Brasil_Estados_Municipios.xlsx",
    2021: "saeb_2021_brasil_estados_municipios.xlsx",
    2025: "saeb_2025_brasil_estados_municipios_censitario.xlsx",
}
ARQUIVO_PLANILHA_TAXA = "saeb_2021_brasil_estados_municipios_c_tx_alfabetizado.xlsx"
ARQUIVO_PLANILHA_2023 = "planilha_de_resultados_2023.rar"

SITUACAO_SEM_IMPORTACAO = "sem_importacao"
SITUACAO_ADIADO = "adiado"

AVISOS = {
    "mesma_rede": (
        "A comparação é na MESMA rede: a rede municipal do município × o Brasil nas redes "
        "municipais (no Ideb) e × o estado e o Brasil nas redes municipais (no Saeb da "
        "planilha). A ordem é fixa — não é ranking."),
    "universo": (
        "A nota do Saeb que entra no Ideb do território é a das escolas URBANAS (o universo "
        "do INEP no Ideb; o arquivo não diz — conferido contra a planilha do Saeb nas edições "
        "que ela cobre). O Ideb e o N saem dessa nota. Ela fica só na seção do Ideb e nunca se "
        "compara com a média “Total” da planilha do Saeb, que inclui as escolas rurais."),
    "saeb_planilha": (
        "Média e distribuição por nível do Saeb do 5º ano pela planilha de resultados do INEP, "
        "na localização Total (escolas urbanas e rurais) e por rede (dependência "
        "administrativa). Não é a nota do Saeb do Ideb (só urbanas): são números diferentes, "
        "que não se cruzam."),
    "niveis": (
        "A distribuição por nível vem do arquivo oficial (percentual de alunos em cada "
        "nível; cada barra soma cerca de 100% pelo arredondamento do INEP). O Constela não "
        "calcula nível."),
    "saeb_2023": (
        "Saeb 2023 pela planilha do INEP (RAR com XLSB): adiado. Sem ela, a média e os "
        "níveis de 2023 não aparecem no bloco do Saeb; em 2023 só há a nota do Saeb do Ideb "
        "(só escolas urbanas), na seção do Ideb."),
    "amostral": (
        "O Saeb do 2º ano é AMOSTRAL: o INEP divulga só o estado e o Brasil, nunca a rede "
        "municipal nem a escola. Aqui é só contexto — não é número da rede."),
    "nao_e_ica": (
        "A taxa de alfabetização do Saeb 2021 (2º ano, amostral) NÃO é o Indicador Criança "
        "Alfabetizada (ICA) e não se compara com ele: o ICA da rede está na aba do ICA."),
}


# --- Regras comuns (escola e território) --------------------------------------------

def motivo_sem_meta(edicao: int, anos_meta: list[int],
                    sem_metas: str = SEM_META_SEM_ARQUIVO) -> str | None:
    """Por que a edição não tem meta: antes do 1º ciclo, depois dele ou ``sem_metas``
    quando não há meta nenhuma (a escola só com números do 1 clique; o território sem
    meta no arquivo)."""
    if edicao in anos_meta:
        return None
    if not anos_meta:
        return sem_metas
    return SEM_META_DEPOIS_DO_CICLO if edicao > max(anos_meta) else SEM_META_ANTES_DO_CICLO


def comparar_meta(edicao: int, observado: dict | None, meta: dict | None) -> dict | None:
    """Ideb × meta da MESMA edição, na precisão publicada (a diferença pela conta do ICA,
    ``consulta.comparar``). A SITUAÇÃO segue a leitura do INEP — Ideb ≥ meta = meta
    atingida —, não o "inconclusivo" do ICA: lá o empate na capa inteira pode se inverter
    com o decimal; aqui o Ideb de 1 casa É o número oficial e a meta foi definida com 1
    casa, sem valor oficial mais preciso que desfaça o empate."""
    if not observado or not meta or observado["valor"] is None or meta["valor"] is None:
        return None
    c = comparar({"edicao": edicao, "valor": observado["valor"],
                  "casas_decimais": observado["casas_decimais"], "detalhe": None},
                 {"edicao": edicao, "valor": meta["valor"],
                  "casas_decimais": meta["casas_decimais"], "operador": None, "detalhe": None})
    if c is None:
        return None
    diferenca = c["diferenca_pp"] + 0.0           # nunca "-0.0" na resposta
    return {"observado": c["resultado"], "meta": c["meta"], "diferenca": diferenca,
            "casas_decimais": c["casas_decimais"],
            "situacao": "atingiu" if diferenca >= 0 else "nao_atingiu"}


# --- Leitura ---------------------------------------------------------------------

def _avaliacao(db: Session, chave: str) -> AvaliacaoExterna | None:
    return leituras.avaliacao(db, chave)


def _alvos(codigo: str) -> dict[str, str]:
    """Código de cada abrangência para a rede: o município, a UF dele e o Brasil."""
    return {ABR_MUNICIPIO: codigo, ABR_UF: codigo[:2], ABR_BRASIL: ica.CODIGO_BRASIL}


def _linhas(db: Session, avaliacao: AvaliacaoExterna | None, codigo: str,
            indicadores: tuple[str, ...]) -> list[IndicadorReferencia]:
    if avaliacao is None:
        return []
    alvos = _alvos(codigo)
    linhas = db.execute(select(IndicadorReferencia).where(
        IndicadorReferencia.avaliacao_id == avaliacao.id,
        IndicadorReferencia.abrangencia.in_(tuple(alvos)),
        IndicadorReferencia.codigo_territorio.in_(tuple(alvos.values())),
        IndicadorReferencia.indicador.in_(indicadores))).scalars()
    # O par (abrangência, código) — nunca um código de outra abrangência.
    return [ln for ln in linhas if alvos.get(ln.abrangencia) == ln.codigo_territorio]


def _numero(ln: IndicadorReferencia | None) -> dict | None:
    if ln is None:
        return None
    casas = ln.casas_decimais
    if ln.valor is not None and ln.indicador in _CASAS_MINIMAS:
        casas = max(_CASAS_MINIMAS[ln.indicador], casas or 0)
    return {"valor": ln.valor, "casas_decimais": casas if ln.valor is not None else None,
            "motivo_ausencia": ln.motivo_ausencia, "proveniencia": PROVENIENCIA_OFICIAL,
            "fonte_id": ln.importacao_id}


def nome_da_uf(codigo_uf: str) -> str:
    return ideb_territorio.UFS.get(codigo_uf, (f"UF {codigo_uf}",))[0]


def _universo(abrangencia: str, rede_ensino: str) -> dict:
    return {"chave": ideb_territorio.universo_saeb(abrangencia, rede_ensino),
            "rotulo": ideb_territorio.rotulo_universo(abrangencia, rede_ensino),
            "indicadores": list(ideb_territorio.INDICADORES_DO_UNIVERSO)}


# --- Ideb do território -------------------------------------------------------------

def _serie_ideb(minhas: list[IndicadorReferencia]) -> tuple[list[dict], list[int]]:
    por = {(ln.edicao, ln.indicador, ln.etapa, ln.componente): ln for ln in minhas}
    anos_meta = sorted({ln.edicao for ln in minhas if ln.indicador == ideb.IND_META})
    edicoes = sorted({ln.edicao for ln in minhas if ln.indicador != ideb.IND_META})

    def n(ed: int, indicador: str, etapa: str = ideb.ETAPA_IDEB, comp: str = "") -> dict | None:
        return _numero(por.get((ed, indicador, etapa, comp)))

    serie = []
    for ed in edicoes:
        observado, meta = n(ed, ideb.IND_IDEB), n(ed, ideb.IND_META)
        serie.append({
            "edicao": ed, "ideb": observado, "meta": meta,
            "sem_meta": (motivo_sem_meta(ed, anos_meta, SEM_META_NO_ARQUIVO)
                         if meta is None else None),
            "comparacao_meta": comparar_meta(ed, observado, meta),
            "nota_saeb": {c: n(ed, ideb_territorio.IND_NOTA_SAEB, ideb.ETAPA_SAEB, c)
                          for c in COMPONENTES},
            "nota_n": n(ed, ideb.IND_NOTA_N), "rendimento_p": n(ed, ideb.IND_RENDIMENTO_P),
            "aprovacao": n(ed, ideb.IND_APROVACAO, ideb.ETAPA_IDEB),
        })
    return serie, anos_meta


def _territorio_ideb(definicao: tuple, linhas: list[IndicadorReferencia], alvos: dict,
                     nome_mun: str | None, uf_importada: bool) -> dict:
    """``uf_importada``: há linhas do arquivo de UF. Só aí se SABE que ele não traz a rede
    municipal da UF — sem ele, nada de afirmar o que o arquivo traz (``motivo_contexto``
    nulo; o que falta está em ``pendentes``)."""
    chave, abrangencia, rede_ensino, mesma, posicao = definicao
    codigo = alvos[abrangencia]
    minhas = [ln for ln in linhas if (ln.abrangencia, ln.rede_ensino) == (abrangencia, rede_ensino)]
    serie, anos_meta = _serie_ideb(minhas)
    nome, rotulo = _nome_rotulo(chave, abrangencia, codigo, nome_mun)
    saida = {
        "chave": chave, "abrangencia": abrangencia, "codigo_territorio": codigo,
        "rede_ensino": rede_ensino, "mesma_rede": mesma, "contexto": not mesma,
        "posicao": posicao, "nome": nome, "rotulo": rotulo,
        "universo_saeb": _universo(abrangencia, rede_ensino),
        "serie": serie, "anos_meta": anos_meta,
        "tem_dados": any(ln.valor is not None for ln in minhas),
        "rotulo_contexto": None, "motivo_contexto": None,
    }
    if not mesma:
        saida["rotulo_contexto"] = "outra rede, só contexto"
    if not mesma and uf_importada:
        saida["motivo_contexto"] = (
            f"O arquivo do Ideb por UF do INEP não traz a rede municipal de {nome}: {nome} "
            "aparece na rede PÚBLICA (estadual e municipal), que é OUTRA rede — só contexto, "
            "não é comparação na mesma rede.")
    return saida


def _nome_rotulo(chave: str, abrangencia: str, codigo: str, nome_mun: str | None) -> tuple[str, str]:
    if abrangencia == ABR_MUNICIPIO:
        nome = nome_mun or "Município"
        return nome, f"{nome_mun} — rede municipal" if nome_mun else "Rede municipal"
    if abrangencia == ABR_BRASIL:
        return "Brasil", "Brasil — redes municipais"
    nome = nome_da_uf(codigo)
    if chave == _IDEB_UF_PUBLICA[0]:
        return nome, f"{nome} — rede pública (estadual e municipal)"
    return nome, f"{nome} — redes municipais"


_NOME_REDE = {"total": "total", "publica": "pública", "estadual": "estadual",
              "municipal": "municipal"}


def _lista_redes(redes: set[str]) -> str:
    ordem = list(_NOME_REDE)
    nomes = [_NOME_REDE.get(r, r) for r in sorted(redes, key=lambda r: (
        ordem.index(r) if r in _NOME_REDE else len(ordem), r))]
    return nomes[0] if len(nomes) == 1 else f"{', '.join(nomes[:-1])} e {nomes[-1]}"


def _ideb(db: Session, codigo: str, nome_mun: str | None) -> dict:
    linhas = _linhas(db, _avaliacao(db, ideb.AVALIACAO_IDEB), codigo, _IND_IDEB)
    alvos = _alvos(codigo)
    tem_uf = {ln.rede_ensino for ln in linhas if ln.abrangencia == ABR_UF}
    # A UF na MESMA rede só se o arquivo a trouxer; senão a rede pública, como contexto.
    uf_municipal = "municipal" in tem_uf
    definicoes = [_IDEB_MUNICIPIO, _IDEB_UF_MUNICIPAL if uf_municipal else _IDEB_UF_PUBLICA,
                  _IDEB_BRASIL]
    territorios = [_territorio_ideb(d, linhas, alvos, nome_mun, bool(tem_uf)) for d in definicoes]
    territorios.sort(key=lambda t: (not t["mesma_rede"], t["posicao"]))
    uf = nome_da_uf(alvos[ABR_UF])
    return {
        "territorios": territorios,
        "edicoes": sorted({e["edicao"] for t in territorios for e in t["serie"]}),
        "anos_meta": sorted({a for t in territorios for a in t["anos_meta"]}),
        # O arquivo de UF foi importado (há linhas da UF) mas não traz a rede municipal.
        "uf_sem_rede_municipal": bool(tem_uf) and not uf_municipal,
        "texto_uf_sem_rede_municipal": (
            f"O arquivo do Ideb por UF do INEP não traz a rede municipal de {uf} (redes "
            f"importadas da UF: {_lista_redes(tem_uf)}): {uf} aparece na rede pública, como "
            "contexto rotulado — outra rede, não é comparação. O Constela não estima a rede "
            "municipal da UF." if tem_uf and not uf_municipal else None),
        "tem_dados": any(t["tem_dados"] for t in territorios),
    }


# --- Saeb do 5º ano (planilha) ------------------------------------------------------

def regua_saeb_5() -> dict:
    """Os cortes dos níveis do 5º ano (LP 0–9, MT 0–10) e a fonte deles."""
    def faixas(comp: str) -> list[dict]:
        saida = []
        for k in escalas.NIVEIS_SAEB[("5_ano", comp)]:
            inicio, fim = escalas.faixa_nivel_saeb("5_ano", comp, k)
            saida.append({"nivel": k, "inicio": inicio, "fim": fim})
        return saida
    return {"lp": faixas("lp"), "mt": faixas("mt"), "fonte": escalas.FONTE_CORTES_SAEB_5,
            "edicoes_com_cortes_no_arquivo": list(escalas.EDICOES_CORTES_SAEB_5_NO_ARQUIVO),
            "texto_outras_edicoes": escalas.TEXTO_CORTES_SAEB_5_OUTRAS_EDICOES,
            "unidade": escalas.ESCALA_SAEB}


def _distribuicao(itens: list[IndicadorReferencia]) -> dict:
    """Os níveis em ordem (0, 1, ... 10 — pelo número, não pelo texto) e a soma, só
    quando todos têm número (ausência ≠ 0)."""
    niveis = []
    for ln in sorted(itens, key=lambda x: int(x.nivel or 0)):
        inicio, fim = escalas.faixa_nivel_saeb(ln.etapa, ln.componente, int(ln.nivel or 0))
        niveis.append({"nivel": int(ln.nivel or 0), **_numero(ln), "inicio": inicio, "fim": fim})
    com_valor = [x["valor"] for x in niveis if x["valor"] is not None]
    return {"niveis": niveis,
            "soma": round(sum(com_valor), 2) if niveis and len(com_valor) == len(niveis) else None}


def _planilhas_da_rede(db: Session, codigo: str) -> list[int]:
    """As edições da planilha do Saeb do 5º ano que ESTA rede importou e não desfez: a
    importação viu alguma linha do 5º ano (``resumo.etapas_vistas``: as etapas de TODAS
    as chaves do plano, as iguais inclusive — sem ler o plano de desfazer, que é grande)
    — a planilha da taxa de alfabetização, só do 2º ano, não conta. Vale mesmo quando o
    arquivo não traz linha do município (o pacote nem leva a aba sem o território): aí
    a planilha foi importada, só não tem número da rede."""
    edicoes: set[int] = set()
    for imp in leituras.aplicadas_do_territorio(db, codigo, (saeb_planilha.PARSER,)):
        resumo = imp.resumo or {}
        if "5_ano" in (resumo.get("etapas_vistas") or []):
            edicoes.update(resumo.get("edicoes") or [imp.edicao_arquivo])
    return sorted(edicoes)


def _saeb(db: Session, codigo: str, nome_mun: str | None) -> dict:
    av = _avaliacao(db, saeb_planilha.AVALIACAO)
    linhas = [ln for ln in _linhas(db, av, codigo, (saeb_planilha.IND_PROFICIENCIA,
                                                   saeb_planilha.IND_PCT_NIVEL))
              if (ln.rede_ensino, ln.localizacao, ln.etapa) == ("municipal", LOCALIZACAO_CAPA,
                                                                 "5_ano")]
    alvos = _alvos(codigo)
    territorios = []
    for posicao, (chave, abrangencia) in enumerate(_SAEB):
        minhas = [ln for ln in linhas if ln.abrangencia == abrangencia]
        edicoes = []
        for ed in sorted({ln.edicao for ln in minhas}):
            da_ed = [ln for ln in minhas if ln.edicao == ed]
            medias = {ln.componente: ln for ln in da_ed
                      if ln.indicador == saeb_planilha.IND_PROFICIENCIA}
            edicoes.append({
                "edicao": ed,
                "media": {c: _numero(medias.get(c)) for c in COMPONENTES},
                "niveis": {c: _distribuicao([ln for ln in da_ed if ln.componente == c and
                                             ln.indicador == saeb_planilha.IND_PCT_NIVEL])
                           for c in COMPONENTES},
            })
        nome, rotulo = _nome_rotulo(chave, abrangencia, alvos[abrangencia], nome_mun)
        territorios.append({
            "chave": chave, "abrangencia": abrangencia, "codigo_territorio": alvos[abrangencia],
            "rede_ensino": "municipal", "localizacao": LOCALIZACAO_CAPA, "mesma_rede": True,
            "posicao": posicao, "nome": nome, "rotulo": rotulo, "edicoes": edicoes,
            "tem_dados": any(ln.valor is not None for ln in minhas),
        })
    return {
        "territorios": territorios,
        "edicoes": sorted({e["edicao"] for t in territorios for e in t["edicoes"]}),
        "localizacao": LOCALIZACAO_CAPA, "rotulo_localizacao": ROTULO_LOCALIZACAO,
        "regua": regua_saeb_5(),
        # A planilha que ESTA rede importou (a UF e o Brasil podem vir da de outra rede).
        "edicoes_importadas_rede": _planilhas_da_rede(db, codigo),
        "tem_dados": any(t["tem_dados"] for t in territorios),
    }


# --- Contexto amostral: 2º ano e taxa de alfabetização (UF e Brasil) ------------------

def _contexto_amostral(db: Session, codigo: str) -> dict:
    av = _avaliacao(db, saeb_planilha.AVALIACAO)
    linhas = [ln for ln in _linhas(db, av, codigo, (saeb_planilha.IND_PROFICIENCIA,
                                                   saeb_planilha.IND_TX_ALFABETIZADO))
              if (ln.rede_ensino, ln.localizacao, ln.etapa) == ("municipal", LOCALIZACAO_CAPA,
                                                                 "2_ano")
              and ln.abrangencia != ABR_MUNICIPIO]       # amostral: nunca por município
    alvos = _alvos(codigo)
    territorios = []
    for posicao, (chave, abrangencia) in enumerate(_AMOSTRAL):
        minhas = [ln for ln in linhas if ln.abrangencia == abrangencia]
        edicoes = []
        for ed in sorted({ln.edicao for ln in minhas}):
            da_ed = {(ln.indicador, ln.componente): ln for ln in minhas if ln.edicao == ed}
            edicoes.append({
                "edicao": ed,
                "media": {c: _numero(da_ed.get((saeb_planilha.IND_PROFICIENCIA, c)))
                          for c in COMPONENTES},
                "tx_alfabetizado": _numero(da_ed.get((saeb_planilha.IND_TX_ALFABETIZADO, "lp"))),
            })
        nome, rotulo = _nome_rotulo(chave, abrangencia, alvos[abrangencia], None)
        territorios.append({
            "chave": chave, "abrangencia": abrangencia, "codigo_territorio": alvos[abrangencia],
            "rede_ensino": "municipal", "localizacao": LOCALIZACAO_CAPA,
            "desenho": DESENHO_AMOSTRAL, "posicao": posicao, "nome": nome,
            "rotulo": f"{rotulo} (amostral, só contexto)", "edicoes": edicoes,
            "tem_dados": any(ln.valor is not None for ln in minhas),
        })
    return {
        "territorios": territorios,
        "edicoes": sorted({e["edicao"] for t in territorios for e in t["edicoes"]}),
        "desenho": DESENHO_AMOSTRAL, "etapa": "2_ano",
        "unidade_media": saeb_planilha.UNIDADE_MEDIA["2_ano"],
        "aviso": AVISOS["amostral"], "nao_e_ica": AVISOS["nao_e_ica"],
        "tem_dados": any(t["tem_dados"] for t in territorios),
    }


# --- O que ainda falta ----------------------------------------------------------------

def pendentes(edicoes_escolas: list[int], ideb_rede: dict, saeb_rede: dict,
              contexto: dict) -> list[dict]:
    """O que esta base não importou (pelo nome do arquivo do INEP) e o que está ADIADO.
    Nada aqui diz "aguardando": os arquivos são públicos; falta só a importação."""
    saida = []

    def sem(chave: str, arquivo: str, texto: str, edicao: int | None = None) -> None:
        saida.append({"chave": chave, "edicao": edicao, "situacao": SITUACAO_SEM_IMPORTACAO,
                      "arquivo": arquivo, "texto": texto})

    if 2025 not in edicoes_escolas:
        sem("ideb_escolas_2025", ARQUIVO_IDEB_ESCOLAS.replace("AAAA", "2025"),
            "Ideb e Saeb 2025 por escola: o arquivo oficial do INEP "
            "(divulgacao_anos_iniciais_escolas_2025.zip) não foi importado para esta rede.", 2025)
    terr = {t["abrangencia"]: t for t in ideb_rede["territorios"]}
    for abrangencia, chave, arquivo, quem in (
            (ABR_MUNICIPIO, "ideb_municipio", ARQUIVO_IDEB_MUNICIPIOS, "da rede municipal"),
            (ABR_UF, "ideb_uf", ARQUIVO_IDEB_UF, "da UF"),
            (ABR_BRASIL, "ideb_brasil", ARQUIVO_IDEB_BRASIL, "do Brasil")):
        if not (terr.get(abrangencia) or {}).get("serie"):
            sem(chave, arquivo, f"Ideb {quem}: o arquivo oficial do INEP ({arquivo}) não foi "
                "importado para esta rede.")
    # Só o que é DESTA rede: a UF e o Brasil da planilha valem para todas as redes da UF
    # (referência pública) e não dizem que a planilha foi importada para esta.
    importadas = set(saeb_rede.get("edicoes_importadas_rede") or []) | {
        e["edicao"] for t in saeb_rede["territorios"] if t["abrangencia"] == ABR_MUNICIPIO
        for e in t["edicoes"]}
    for ed in EDICOES_PLANILHA_SAEB:
        if ed not in importadas:
            sem(f"saeb_planilha_{ed}", ARQUIVO_PLANILHA_SAEB[ed],
                f"Saeb {ed} pela planilha do INEP (médias e níveis do 5º ano): não foi importado "
                "para esta rede.", ed)
    tem_taxa = any(e["tx_alfabetizado"] is not None for t in contexto["territorios"]
                   for e in t["edicoes"])
    if not tem_taxa:
        sem("saeb_2021_taxa", ARQUIVO_PLANILHA_TAXA,
            "Taxa de alfabetização do Saeb 2021 (2º ano, amostral, só estado e Brasil): a "
            f"planilha do INEP ({ARQUIVO_PLANILHA_TAXA}) não foi importada para esta rede.",
            EDICAO_TAXA_ALFABETIZACAO)
    saida.append({"chave": "saeb_planilha_2023", "edicao": EDICAO_PLANILHA_ADIADA,
                  "situacao": SITUACAO_ADIADO, "arquivo": ARQUIVO_PLANILHA_2023,
                  "texto": AVISOS["saeb_2023"]})
    return saida


# --- Entrada ---------------------------------------------------------------------

def _do_municipio(bloco: dict) -> bool:
    return any(t["tem_dados"] for t in bloco["territorios"] if t["abrangencia"] == ABR_MUNICIPIO)


def rede_municipal(db: Session, codigo: str | None, nome_mun: str | None) -> tuple[dict, dict]:
    """``(rede_municipal, contexto_amostral)`` — sem o código IBGE da rede, tudo vazio
    (nada é recortado sem ele). ``tem_dados`` do bloco = há número DA REDE MUNICIPAL (o
    Ideb ou o Saeb do município); a UF e o Brasil sozinhos (referência pública, que outra
    rede pode ter importado) não contam — esses ficam no ``tem_dados`` do Ideb e do Saeb."""
    if codigo is None:
        vazio_ideb = {"territorios": [], "edicoes": [], "anos_meta": [],
                      "uf_sem_rede_municipal": False, "texto_uf_sem_rede_municipal": None,
                      "tem_dados": False}
        vazio_saeb = {"territorios": [], "edicoes": [], "localizacao": LOCALIZACAO_CAPA,
                      "rotulo_localizacao": ROTULO_LOCALIZACAO, "regua": regua_saeb_5(),
                      "edicoes_importadas_rede": [], "tem_dados": False}
        contexto = {"territorios": [], "edicoes": [], "desenho": DESENHO_AMOSTRAL,
                    "etapa": "2_ano", "unidade_media": saeb_planilha.UNIDADE_MEDIA["2_ano"],
                    "aviso": AVISOS["amostral"], "nao_e_ica": AVISOS["nao_e_ica"],
                    "tem_dados": False}
        return ({"ideb": vazio_ideb, "saeb": vazio_saeb, "avisos": dict(AVISOS),
                 "tem_dados": False}, contexto)
    ideb_rede = _ideb(db, codigo, nome_mun)
    saeb_rede = _saeb(db, codigo, nome_mun)
    contexto = _contexto_amostral(db, codigo)
    return ({"ideb": ideb_rede, "saeb": saeb_rede, "avisos": dict(AVISOS),
             "tem_dados": _do_municipio(ideb_rede) or _do_municipio(saeb_rede)}, contexto)


def ids_de_importacao(rede: dict, contexto: dict) -> set[int]:
    """Os ``fonte_id`` de todos os números do bloco (para a lista de fontes)."""
    ids: set[int] = set()

    def add(n: dict | None) -> None:
        if n and n.get("fonte_id") is not None:
            ids.add(n["fonte_id"])

    for t in rede["ideb"]["territorios"]:
        for e in t["serie"]:
            for campo in ("ideb", "meta", "nota_n", "rendimento_p", "aprovacao"):
                add(e[campo])
            for n in e["nota_saeb"].values():
                add(n)
    for t in rede["saeb"]["territorios"]:
        for e in t["edicoes"]:
            for c in COMPONENTES:
                add(e["media"][c])
                for n in e["niveis"][c]["niveis"]:
                    add(n)
    for t in contexto["territorios"]:
        for e in t["edicoes"]:
            add(e["tx_alfabetizado"])
            for n in e["media"].values():
                add(n)
    return ids
