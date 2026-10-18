"""Leitura do SARESP OFICIAL da rede — etapa E5 (``GET /redes/{id}/indicadores/saresp``).

O que a Secretaria lê (plano, 4.6, 4.8, 4.9 e 5.1), a partir do que a E4 grava:

* REDE MUNICIPAL por série (2º e 5º ano) × componente (LP, MT), em todas as edições
  importadas do SARESP por município (``indicadores_referencia``: abrangência
  ``municipio``, rede ``municipal``);
* comparação com o ESTADO na MESMA rede — as redes municipais de SP (instância
  ESTADO, DEPADM 2). A rede ESTADUAL (no município e no Estado) vem à parte, com
  ``mesma_rede = False`` e o nome da rede no rótulo: é OUTRA rede, só contexto;
* POR ESCOLA, a proficiência OFICIAL (o IEE traz o SARESP de 2024 e de 2025) com a
  participação, o TPS, a nota do IEE, a meta e o cumprimento — em ordem de NOME
  (sem ranking). Os números por escola SEM proveniência oficial (importação manual —
  ex.: a média do 5º ano de 2025 calculada pelo Constela, se a decisão D2 não a
  substituiu) vêm SEPARADOS, em ``estimativas``, nunca misturados com a oficial;
* cada número com a fonte: arquivo, edição, data do arquivo e da importação;
* COBERTURA por edição: escolas da rede sem resultado oficial (com o motivo quando a
  fonte o dá — "sem resultado" nunca é 0), escolas sem código INEP (pendência de
  cadastro) e as escolas do arquivo sem escola no cadastro — sempre pelo CÓDIGO,
  nunca pelo nome;
* CADASTRO QUE MUDOU DEPOIS DA IMPORTAÇÃO: um número por escola só vale se a
  importação aplicada da edição casou a escola com o código INEP ATUAL dela. Se o
  código foi cadastrado ou trocado depois, a linha não mostra número nenhum (nem a
  proficiência gravada pela escola, nem participação/IEE pelo código — seriam de
  linhas diferentes do arquivo) e o motivo pede a reimportação;
* NÍVEIS: os pontos de corte do SARESP estão "a confirmar" (``escalas``); sem corte
  confirmado, nenhuma média recebe nível (nem distância até o Adequado);
* QUEBRAS DE ESCALA: a série do 2º ano não é ligada de 2022 para 2023 (a TRI passou
  a ser calculada só no 2º, 5º e 9º ano em 2023 — plano, 4.9 e (1).8) nem de 2025
  para 2026 (a prova do 2º ano muda).

Só LÊ (nem cria a linha do catálogo). Sem dado importado, as listas vêm vazias e a
tela diz "sem resultado importado" — nunca 0.
"""
from __future__ import annotations

from datetime import datetime
from email.utils import parsedate_to_datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (AvaliacaoExterna, Escola, ImportacaoIndicador, IndicadorReferencia, Rede,
                        ResultadoAvaliacao)
from app.services.avaliacoes import CATALOGO, normalizar_inep
from app.services.indicadores import escalas, seduc
from app.services.indicadores.consulta import _fonte
from app.services.indicadores.pipeline import codigo_ibge_da_rede

ETAPAS = seduc.ETAPAS                               # ("2_ano", "5_ano")
COMPONENTES = ("lp", "mt")
# `resultados_avaliacao` grava o componente como as outras avaliações por escola.
_COMPONENTE_DA_ESCOLA = {seduc.COMPONENTE_ESCOLA[k]: v
                         for k, v in seduc.COMPONENTE_REFERENCIA.items()}   # portugues → lp
ROTULO_ETAPA = {"2_ano": "2º ano", "5_ano": "5º ano"}
ROTULO_COMPONENTE = {"lp": "Língua Portuguesa", "mt": "Matemática"}

# (chave, abrangência, rede de ensino, mesma rede da comparação?) — ORDEM FIXA.
_TERRITORIOS = (
    ("rede_municipal", "municipio", "municipal", True),
    ("estado_redes_municipais", "uf", "municipal", True),
    ("rede_estadual_no_municipio", "municipio", "estadual", False),
    ("estado_rede_estadual", "uf", "estadual", False),
)

# A tendência NÃO é traçada entre `de` e `para` nesta série (a tela quebra a linha).
QUEBRAS_DE_ESCALA = (
    {"etapa": "2_ano", "de": 2022, "para": 2023,
     "motivo": ("Possível quebra de escala no 2º ano: em 2023 a SEDUC passou a calcular a "
                "proficiência (TRI) só no 2º, no 5º e no 9º ano. Por isso a linha de 2022 "
                "para 2023 não é traçada — compare 2022 com cuidado (a confirmar com a "
                "SEDUC).")},
    {"etapa": "2_ano", "de": 2025, "para": 2026,
     "motivo": ("A prova do 2º ano muda em 2026 (itens de resposta construída): a tendência "
                "de 2025 para 2026 só será traçada depois da nota técnica da SEDUC.")},
)

AVISOS = {
    "escala": ("O SARESP tem escala própria, da SEDUC-SP: as médias não se comparam com o "
               "Saeb nem com o ICA."),
    "segundo_ano_x_ica": (
        "O SARESP do 2º ano NÃO é comparável ao ICA, o indicador de alfabetização do INEP: "
        "a escala e o corte são outros, e não está confirmado que a Língua Portuguesa do 2º "
        "ano do SARESP esteja na escala de alfabetização do Saeb. Não cruze os dois números."),
    "comparacao": (
        "A comparação com o Estado é na MESMA rede: as redes municipais de São Paulo. A rede "
        "estadual (no município e no Estado) aparece à parte, só como contexto — é outra "
        "rede."),
    "sem_ranking": ("A tabela por escola está em ordem alfabética: não é ranking e não serve "
                    "para ordenar escolas."),
    "tps": ("TPS = 0: a escola não atingiu a taxa mínima de participação do SARESP; a média "
            "dela é instável."),
    "estimativa": (
        "Estas médias por escola NÃO são os números oficiais da SEDUC: foram calculadas pelo "
        "Constela ou importadas à mão, sem a prévia oficial. Ficam separadas e não entram na "
        "tabela oficial; a troca pela média oficial é feita na importação do IEE (decisão "
        "D2), com prévia e desfazer."),
}

_IND_ESCOLA = {seduc.IND_PARTICIPACAO, seduc.IND_TPS, seduc.IND_IEE, seduc.IND_META,
               seduc.IND_ICM}

# Motivos de "sem resultado" por escola, além dos da fonte (``nao_divulgado``...):
MOTIVO_SEM_INEP = "sem_codigo_inep"
MOTIVO_FORA_DO_ARQUIVO = "fora_do_arquivo"
MOTIVO_SEM_IMPORTACAO = "sem_importacao"
# o código INEP atual está no arquivo, mas a importação aplicada não casou a escola
# com ele (cadastrado ou trocado DEPOIS): só a reimportação da edição resolve.
MOTIVO_CADASTRADO_DEPOIS = "cadastrado_depois_da_importacao"
MOTIVO_INEP_ALTERADO = "codigo_inep_alterado"
MOTIVOS_REIMPORTAR = (MOTIVO_CADASTRADO_DEPOIS, MOTIVO_INEP_ALTERADO)
# D2 "não": o número oficial está no arquivo, mas não foi gravado — a estimativa do
# Constela foi mantida (e fica no bloco separado).
MOTIVO_ESTIMATIVA_D2 = "estimativa_mantida_d2"
_CONECTIVOS = {"de", "da", "do", "das", "dos", "e"}


def _iso(valor):
    return valor.isoformat() if valor else None


def _nome_proprio(texto: str | None) -> str | None:
    """'CARAGUATATUBA' → 'Caraguatatuba'; 'SAO JOSE DOS CAMPOS' → 'Sao Jose dos Campos'
    (o arquivo da SEDUC grafa o município em maiúsculas)."""
    palavras = (texto or "").split()
    if not palavras:
        return None
    return " ".join(p.lower() if i and p.lower() in _CONECTIVOS else p.capitalize()
                    for i, p in enumerate(palavras))


def _data_do_arquivo(imp: ImportacaoIndicador) -> tuple[str | None, str | None]:
    """(dia do arquivo, de onde veio). O CSV da SEDUC não traz data interna: vale o
    Last-Modified do servidor informado na importação. Sem nenhum, ``None`` — nunca a
    hora da leitura."""
    if imp.arquivo_data:
        return imp.arquivo_data.date().isoformat(), "interna"
    texto = (imp.last_modified_origem or "").strip()
    if not texto:
        return None, None
    try:
        return parsedate_to_datetime(texto).date().isoformat(), "last_modified"
    except (TypeError, ValueError, IndexError):
        pass
    try:
        return datetime.fromisoformat(texto[:10]).date().isoformat(), "last_modified"
    except ValueError:
        return None, None


def _fonte_seduc(imp: ImportacaoIndicador | None) -> dict | None:
    if imp is None:
        return None
    dia, origem = _data_do_arquivo(imp)
    return {**_fonte(imp), "data_arquivo": dia, "data_arquivo_origem": origem}


def _nivel(valor: float | None, edicao: int, etapa: str, componente: str) -> dict:
    """O nível em que cai a MÉDIA — só com o corte da edição CONFIRMADO (hoje, nenhum:
    ``situacao = "a_confirmar"`` e nível nulo)."""
    r = escalas.classificar_saresp(valor, edicao, etapa, componente)
    return {"situacao": r["situacao"], "nivel": r["nivel"],
            "distancia_adequado": r["distancia_adequado"],
            "calculo_do_constela": r["calculo_do_constela"]}


def _numero(*, edicao: int, valor, casas, unidade: str, motivo, imp, proficiencia=None) -> dict:
    saida = {"edicao": edicao, "valor": valor, "casas_decimais": casas, "unidade": unidade,
             "motivo_ausencia": motivo, "fonte": _fonte_seduc(imp)}
    if proficiencia is not None:                # (etapa, componente)
        saida["nivel"] = _nivel(valor, edicao, *proficiencia)
    return saida


def _casas(valor: float | None, unidade: str | None) -> int | None:
    """Casas de um número de `resultados_avaliacao` (a tabela não guarda a precisão
    publicada): as do float, até 2. A média do SARESP é publicada com 1 casa (o CSV
    omite o ",0": 123 é 123,0), então na escala SARESP nunca menos de 1."""
    if valor is None:
        return None
    texto = f"{valor:.4f}".rstrip("0").rstrip(".")
    casas = min(len(texto.split(".", 1)[1]) if "." in texto else 0, 2)
    return max(casas, 1) if unidade == seduc.UNIDADE_SARESP else casas


def _avaliacao(db: Session, chave: str) -> AvaliacaoExterna | None:
    return db.execute(select(AvaliacaoExterna).where(
        AvaliacaoExterna.chave == chave)).scalar_one_or_none()


# --- Blocos -------------------------------------------------------------------

def _territorios(linhas: list[IndicadorReferencia], imps: dict, codigo: str,
                 nome_mun: str | None) -> list[dict]:
    rotulo_mun = nome_mun or "Município"
    rotulos = {
        "rede_municipal": f"{nome_mun} — rede municipal" if nome_mun else "Rede municipal",
        "estado_redes_municipais": "Estado de São Paulo — redes municipais",
        "rede_estadual_no_municipio": f"{rotulo_mun} — rede estadual no município",
        "estado_rede_estadual": "Estado de São Paulo — rede estadual",
    }
    saida = []
    for chave, abrangencia, rede_ensino, mesma in _TERRITORIOS:
        cod = codigo if abrangencia == "municipio" else codigo[:2]
        minhas = [ln for ln in linhas if (ln.abrangencia, ln.codigo_territorio, ln.rede_ensino)
                  == (abrangencia, cod, rede_ensino)]
        series = []
        for etapa in ETAPAS:
            for comp in COMPONENTES:
                numeros = [_numero(edicao=ln.edicao, valor=ln.valor, casas=ln.casas_decimais,
                                   unidade=ln.unidade, motivo=ln.motivo_ausencia,
                                   imp=imps.get(ln.importacao_id), proficiencia=(etapa, comp))
                           for ln in sorted(minhas, key=lambda x: x.edicao)
                           if (ln.etapa, ln.componente) == (etapa, comp)]
                series.append({"etapa": etapa, "componente": comp, "numeros": numeros})
        saida.append({
            "chave": chave, "abrangencia": abrangencia, "codigo_territorio": cod,
            "rede_ensino": rede_ensino, "mesma_rede": mesma,
            "nome": (nome_mun if abrangencia == "municipio" else "Estado de São Paulo"),
            "rotulo": rotulos[chave], "series": series, "tem_dados": bool(minhas),
        })
    return saida


def _niveis(edicoes: set[int]) -> dict:
    todas = sorted(edicoes | {e for (e, _, _) in escalas.CORTES_SARESP})
    cortes = []
    for edicao in todas:
        for etapa in ETAPAS:
            for comp in COMPONENTES:
                c = escalas.cortes_saresp(edicao, etapa, comp)
                confirmado = c.confirmado
                cortes.append({"edicao": edicao, "etapa": etapa, "componente": comp,
                               "situacao": c.situacao if confirmado else escalas.SITUACAO_A_CONFIRMAR,
                               "basico": c.basico if confirmado else None,
                               "adequado": c.adequado if confirmado else None,
                               "avancado": c.avancado if confirmado else None,
                               "fonte": c.fonte})
    a_confirmar = sorted({c["edicao"] for c in cortes
                          if c["situacao"] != escalas.SITUACAO_CONFIRMADO})
    algum_confirmado = any(c["situacao"] == escalas.SITUACAO_CONFIRMADO for c in cortes)
    sem_distribuicao = "Os dados abertos não trazem a distribuição dos alunos por nível."
    if not algum_confirmado:
        aviso = ("Os pontos de corte dos níveis do SARESP (Abaixo do Básico, Básico, Adequado "
                 "e Avançado) ainda não foram conferidos na fonte oficial (Sumário Executivo "
                 "do SARESP, da FDE) para estas edições: o Constela não diz em que nível cai "
                 f"cada média nem a distância até o Adequado. {sem_distribuicao}")
    elif a_confirmar:
        aviso = ("Os pontos de corte dos níveis do SARESP foram conferidos na fonte oficial "
                 "só onde a tabela mostra o corte, com a fonte. Onde está \"a confirmar\" "
                 f"(edições {', '.join(map(str, a_confirmar))}), o Constela não diz em que "
                 "nível cai a média nem a distância até o Adequado. O nível e a distância são "
                 f"cálculo do Constela. {sem_distribuicao}")
    else:
        aviso = ("Os pontos de corte dos níveis do SARESP foram conferidos na fonte oficial "
                 "(a fonte está na tabela). O nível em que cai cada média e a distância até o "
                 f"Adequado são cálculo do Constela. {sem_distribuicao}")
    return {
        "rotulos": [{"nivel": n, "rotulo": escalas.ROTULO_NIVEL_SARESP[n]}
                    for n in escalas.NIVEIS_SARESP],
        "cortes": cortes, "edicoes_a_confirmar": a_confirmar, "aviso": aviso,
    }


def _ultimas_iee(db: Session, codigo: str | None) -> dict[int, ImportacaoIndicador]:
    """A importação APLICADA mais recente do IEE de cada edição, para esta rede."""
    if codigo is None:
        return {}
    imps = db.execute(select(ImportacaoIndicador).where(
        ImportacaoIndicador.parser == seduc.PARSER_IEE,
        ImportacaoIndicador.status == "aplicada",
        ImportacaoIndicador.codigo_territorio_alvo == codigo)).scalars().all()
    saida: dict[int, ImportacaoIndicador] = {}
    for imp in sorted(imps, key=lambda i: (i.aplicado_em or datetime.min, i.id)):
        saida[imp.edicao_arquivo] = imp
    return saida


def _arquivo_iee(imp: ImportacaoIndicador | None) -> dict | None:
    """O que a importação APLICADA da edição viu no arquivo, congelado no resumo:
    ``casadas`` (escola → código INEP com que foi casada) e ``linhas`` (as escolas do
    município no arquivo — casadas + fora do cadastro — pelo código). ``None`` sem
    importação (ou resumo sem a lista das casadas)."""
    resumo = (imp.resumo or {}) if imp is not None else {}
    if "escolas_casadas" not in resumo:
        return None
    casadas_lista = list(resumo.get("escolas_casadas") or [])
    casadas = {c.get("escola_id"): normalizar_inep(c.get("codigo_inep")) for c in casadas_lista}
    linhas: dict[str, dict] = {}
    for f in (*casadas_lista, *(resumo.get("fora_do_cadastro") or [])):
        inep = normalizar_inep(f.get("codigo_inep"))
        if inep:
            linhas.setdefault(inep, {"codigo_inep": inep, "cie": f.get("cie"),
                                     "nome_no_arquivo": f.get("nome_no_arquivo")})
    # D2 "não": as chaves (escola, etapa, componente) cujo número oficial NÃO foi
    # gravado porque a estimativa sem proveniência oficial foi mantida.
    mantidas = set()
    if resumo.get("substituir_calculadas") is False:
        # item = [avaliação, edição, indicador, escola, etapa, componente, ...]
        for item in resumo.get("substituicoes_previa") or []:
            if (len(item) >= 6 and item[1] == imp.edicao_arquivo
                    and item[2] == seduc.IND_PROFICIENCIA):
                mantidas.add((item[3], item[4], item[5]))
    return {"casadas": casadas, "linhas": linhas, "mantidas_d2": mantidas}


def _descarte(arquivo: dict | None, escola_id: int, inep: str | None) -> str | None:
    """``None`` = os números gravados da escola nesta edição valem para o código INEP
    ATUAL dela. Senão, o motivo de NÃO mostrá-los (eles seriam de outra linha do
    arquivo, ou de outra escola): sem código; código atual no arquivo, mas a
    importação casou a escola com outro código (ou não a casou) — reimportar resolve;
    ou o código atual nem está no arquivo."""
    if not inep:
        return MOTIVO_SEM_INEP
    if arquivo is None or arquivo["casadas"].get(escola_id) == inep:
        return None
    if inep in arquivo["linhas"]:
        return MOTIVO_INEP_ALTERADO if escola_id in arquivo["casadas"] else MOTIVO_CADASTRADO_DEPOIS
    return MOTIVO_FORA_DO_ARQUIVO


def _motivo_sem_resultado(prof: dict, no_arquivo: bool, descarte: str | None,
                          imp: ImportacaoIndicador | None) -> str:
    """Por que a escola não tem resultado oficial na edição (um motivo só, o mesmo na
    tabela por escola e na cobertura)."""
    if descarte is not None:
        return descarte
    if no_arquivo:
        motivos = {n["motivo_ausencia"] for et in ETAPAS for n in prof[et].values()
                   if n and n["motivo_ausencia"]}
        if MOTIVO_ESTIMATIVA_D2 in motivos:
            return MOTIVO_ESTIMATIVA_D2
        return min(motivos) if motivos else "nao_divulgado"
    return MOTIVO_FORA_DO_ARQUIVO if imp is not None else MOTIVO_SEM_IMPORTACAO


def _cobertura(linhas_escola: list[dict], edicoes: list[int],
               iee: dict[int, ImportacaoIndicador], arquivos: dict[int, dict | None],
               ineps_do_cadastro: set[str]) -> list[dict]:
    saida = []
    for edicao in edicoes:
        com, sem, sem_inep = [], [], []
        imp = iee.get(edicao)
        for linha in linhas_escola:
            base = {"escola_id": linha["escola_id"], "nome": linha["nome"],
                    "codigo_inep": linha["codigo_inep"]}
            if not linha["codigo_inep"]:
                sem_inep.append(base)
                continue
            ed = next(e for e in linha["por_edicao"] if e["edicao"] == edicao)
            if ed["tem_resultado"]:
                com.append(base)
                continue
            sem.append({**base, "motivo": ed["motivo"], "tem_estimativa": ed["tem_estimativa"]})
        # As escolas do arquivo SEM escola com esse código no cadastro de HOJE (o
        # código cadastrado depois da importação sai daqui: aparece na escola, com o
        # motivo "reimporte").
        arquivo = arquivos.get(edicao)
        if arquivo is not None:
            fora = [f for inep, f in sorted(arquivo["linhas"].items())
                    if inep not in ineps_do_cadastro]
        else:
            fora = [f for f in ((imp.resumo or {}).get("fora_do_cadastro") or [] if imp else [])
                    if normalizar_inep(f.get("codigo_inep")) not in ineps_do_cadastro]
        saida.append({
            "edicao": edicao, "total_escolas": len(linhas_escola), "com_resultado": len(com),
            "sem_resultado": sem, "sem_inep": sem_inep,
            "fora_do_cadastro": [{"codigo_inep": f.get("codigo_inep"), "cie": f.get("cie"),
                                  "nome_no_arquivo": f.get("nome_no_arquivo")} for f in fora],
            "fonte": _fonte_seduc(imp),
        })
    return saida


# --- Entrada ------------------------------------------------------------------

def saresp_da_rede(db: Session, rede: Rede) -> dict:
    codigo = codigo_ibge_da_rede(rede)
    catalogo = CATALOGO[seduc.AVALIACAO_SARESP]
    pendencias = []
    if codigo is None:
        pendencias.append("codigo_ibge")
    if not (rede.codigo_municipio_estadual or "").strip():
        pendencias.append("codigo_municipio_estadual")
    av = _avaliacao(db, seduc.AVALIACAO_SARESP)
    av_iee = _avaliacao(db, seduc.AVALIACAO_IEE)

    # ORDEM POR NOME (sem ranking), a mesma no SQLite e no PostgreSQL: sem acento e
    # sem caixa, no Python (a ordenação do banco depende da collation).
    escolas = sorted(db.execute(select(Escola).where(Escola.rede_id == rede.id)).scalars(),
                     key=lambda e: (seduc.sem_acento(e.nome or "").casefold(), e.id))
    inep_de = {e.id: normalizar_inep(e.codigo_inep) for e in escolas}
    ineps = {i for i in inep_de.values() if i}

    # indicadores_referencia: território (proficiência) e escola (participação, TPS, IEE...)
    territorio: list[IndicadorReferencia] = []
    por_inep: dict[str, list[IndicadorReferencia]] = {}
    ids_avaliacao = {a.id: a.chave for a in (av, av_iee) if a is not None}
    if codigo is not None and ids_avaliacao:
        for ln in db.execute(select(IndicadorReferencia).where(
                IndicadorReferencia.avaliacao_id.in_(set(ids_avaliacao)),
                IndicadorReferencia.codigo_territorio.in_({codigo, codigo[:2]}),
                IndicadorReferencia.localizacao == "total")).scalars():
            chave = ids_avaliacao[ln.avaliacao_id]
            if (ln.abrangencia in ("municipio", "uf") and ln.codigo_inep == ""
                    and chave == seduc.AVALIACAO_SARESP
                    and ln.indicador == seduc.IND_PROFICIENCIA
                    and ln.etapa in ETAPAS and ln.componente in COMPONENTES
                    and ln.codigo_territorio == (codigo if ln.abrangencia == "municipio"
                                                 else codigo[:2])):
                territorio.append(ln)
            elif (ln.abrangencia == "escola" and ln.codigo_territorio == codigo
                  and ln.codigo_inep in ineps and ln.indicador in _IND_ESCOLA):
                por_inep.setdefault(ln.codigo_inep, []).append(ln)

    # resultados_avaliacao: a proficiência por escola (oficial × sem proveniência oficial)
    oficiais: dict[int, list[ResultadoAvaliacao]] = {}
    estimativas: dict[int, list[ResultadoAvaliacao]] = {}
    if av is not None and escolas:
        for r in db.execute(select(ResultadoAvaliacao).where(
                ResultadoAvaliacao.avaliacao_id == av.id,
                ResultadoAvaliacao.escola_id.in_(set(inep_de)),
                ResultadoAvaliacao.indicador == seduc.IND_PROFICIENCIA,
                or_(ResultadoAvaliacao.turma.is_(None), ResultadoAvaliacao.turma == ""),
                )).scalars():
            if r.importacao_id is not None:
                if r.etapa in ETAPAS and r.componente in _COMPONENTE_DA_ESCOLA:
                    oficiais.setdefault(r.escola_id, []).append(r)
            elif r.valor is not None and (r.etapa in ETAPAS or not r.etapa):
                estimativas.setdefault(r.escola_id, []).append(r)

    iee = _ultimas_iee(db, codigo)
    ids_imp = ({ln.importacao_id for ln in territorio}
               | {ln.importacao_id for lns in por_inep.values() for ln in lns}
               | {r.importacao_id for rs in oficiais.values() for r in rs}
               | {i.id for i in iee.values()}) - {None}
    imps = {i.id: i for i in db.execute(select(ImportacaoIndicador).where(
        ImportacaoIndicador.id.in_(ids_imp))).scalars()} if ids_imp else {}

    nomes: dict[str, str] = {}
    for imp in sorted(imps.values(), key=lambda i: (i.edicao_arquivo, i.id)):
        nomes.update((imp.resumo or {}).get("territorios") or {})
    nome_mun = _nome_proprio(nomes.get(codigo)) if codigo else None

    edicoes_escola = sorted({r.edicao for rs in oficiais.values() for r in rs}
                            | {ln.edicao for lns in por_inep.values() for ln in lns}
                            | set(iee), reverse=True)
    arquivos = {edicao: _arquivo_iee(iee.get(edicao)) for edicao in edicoes_escola}
    linhas_escola = []
    for e in escolas:
        inep = inep_de[e.id]
        por_edicao = []
        for edicao in edicoes_escola:
            arquivo = arquivos[edicao]
            imp_iee = iee.get(edicao)
            # O cadastro mudou depois da importação? Então nada desta escola nesta
            # edição: a proficiência gravada (pela escola) e a participação/IEE (pelo
            # código atual) seriam de linhas diferentes do arquivo.
            descarte = _descarte(arquivo, e.id, inep)
            prof = {et: {c: None for c in COMPONENTES} for et in ETAPAS}
            participacao = {et: None for et in ETAPAS}
            outros = {seduc.IND_TPS: None, seduc.IND_IEE: None, seduc.IND_META: None,
                      seduc.IND_ICM: None}
            if descarte is None:
                for r in oficiais.get(e.id, []):
                    if r.edicao == edicao:
                        comp = _COMPONENTE_DA_ESCOLA[r.componente]
                        prof[r.etapa][comp] = _numero(
                            edicao=edicao, valor=r.valor, casas=_casas(r.valor, r.unidade),
                            unidade=r.unidade, motivo=r.motivo_ausencia,
                            imp=imps.get(r.importacao_id), proficiencia=(r.etapa, comp))
                for ln in por_inep.get(inep, []):
                    if ln.edicao != edicao:
                        continue
                    n = _numero(edicao=edicao, valor=ln.valor, casas=ln.casas_decimais,
                                unidade=ln.unidade, motivo=ln.motivo_ausencia,
                                imp=imps.get(ln.importacao_id))
                    if ln.indicador == seduc.IND_PARTICIPACAO and ln.etapa in ETAPAS:
                        participacao[ln.etapa] = n
                    elif ln.indicador in outros:
                        outros[ln.indicador] = n
                # D2 "não": o oficial está no arquivo e não foi gravado (a estimativa
                # ficou, no bloco separado). A célula diz isso — não "sem resultado".
                for r in estimativas.get(e.id, []):
                    if (arquivo is not None and r.edicao == edicao and r.etapa in ETAPAS
                            and r.componente in _COMPONENTE_DA_ESCOLA
                            and (e.id, r.etapa, r.componente) in arquivo["mantidas_d2"]):
                        comp = _COMPONENTE_DA_ESCOLA[r.componente]
                        if prof[r.etapa][comp] is None:
                            prof[r.etapa][comp] = _numero(
                                edicao=edicao, valor=None, casas=None,
                                unidade=seduc.UNIDADE_SARESP, motivo=MOTIVO_ESTIMATIVA_D2,
                                imp=imp_iee, proficiencia=(r.etapa, comp))
            numeros = [n for et in ETAPAS for n in prof[et].values() if n]
            tem_resultado = any(n["valor"] is not None for n in numeros)
            no_arquivo = bool(numeros) or any(
                v is not None for v in (*participacao.values(), *outros.values()))
            por_edicao.append({
                "edicao": edicao, "proficiencia": prof, "participacao": participacao,
                "tps": outros[seduc.IND_TPS], "iee": outros[seduc.IND_IEE],
                "meta": outros[seduc.IND_META], "icm": outros[seduc.IND_ICM],
                "tem_resultado": tem_resultado, "no_arquivo": no_arquivo,
                "motivo": (None if tem_resultado
                           else _motivo_sem_resultado(prof, no_arquivo, descarte, imp_iee)),
                # Estimativa do Constela DESTA edição (a frase da tela é por edição).
                "tem_estimativa": any(r.edicao == edicao for r in estimativas.get(e.id, [])),
            })
        minhas_estimativas = [{
            "escola_id": e.id, "nome": e.nome, "codigo_inep": inep, "edicao": r.edicao,
            "etapa": r.etapa or None,
            "componente": _COMPONENTE_DA_ESCOLA.get(r.componente, r.componente),
            "valor": r.valor, "casas_decimais": _casas(r.valor, r.unidade),
            "unidade": r.unidade, "fonte_texto": r.fonte, "gravado_em": _iso(r.created_at),
        } for r in estimativas.get(e.id, [])]
        tem_algum = (any(ed["no_arquivo"] or ed["motivo"] in MOTIVOS_REIMPORTAR
                         for ed in por_edicao) or bool(minhas_estimativas))
        if e.status != "ativa" and not tem_algum:
            continue                     # escola inativa sem número: fora da tela
        linhas_escola.append({
            "escola_id": e.id, "nome": e.nome, "codigo_inep": inep, "status": e.status,
            "pendencia": None if inep else "codigo_inep",
            "por_edicao": por_edicao, "_estimativas": minhas_estimativas,
        })

    cobertura = _cobertura(linhas_escola, edicoes_escola, iee, arquivos, ineps)
    # A MESMA ordem das escolas (sem acento e sem caixa) — não a do ponto de código.
    lista_estimativas = sorted(
        (est for linha in linhas_escola for est in linha["_estimativas"]),
        key=lambda x: (seduc.sem_acento(x["nome"] or "").casefold(), x["escola_id"],
                       -x["edicao"], x["etapa"] or "", x["componente"] or ""))
    for linha in linhas_escola:
        linha["tem_estimativa"] = bool(linha.pop("_estimativas"))

    territorios = _territorios(territorio, imps, codigo, nome_mun) if codigo else []
    edicoes_rede = sorted({ln.edicao for ln in territorio})
    fontes = [_fonte_seduc(i) for i in sorted(
        imps.values(), key=lambda i: (-i.edicao_arquivo, i.parser, i.id))]
    return {
        "rede_id": rede.id, "rede_nome": rede.nome, "codigo_ibge": codigo,
        "codigo_municipio_estadual": (rede.codigo_municipio_estadual or None),
        "municipio": nome_mun,
        "indicador": {"chave": seduc.AVALIACAO_SARESP, "nome": catalogo["nome"],
                      "orgao": catalogo["orgao"], "descricao": catalogo["descricao"]},
        "pendencias": pendencias, "avisos": AVISOS,
        "etapas": [{"chave": et, "rotulo": ROTULO_ETAPA[et]} for et in ETAPAS],
        "componentes": [{"chave": c, "rotulo": ROTULO_COMPONENTE[c]} for c in COMPONENTES],
        "edicoes_rede": edicoes_rede, "territorios": territorios,
        "quebras_de_escala": [dict(q) for q in QUEBRAS_DE_ESCALA],
        "niveis": _niveis(set(edicoes_rede) | set(edicoes_escola)),
        "escolas": {"edicoes": edicoes_escola, "linhas": linhas_escola},
        "estimativas": lista_estimativas, "cobertura": cobertura, "fontes": fontes,
        "tem_dados": bool(territorio) or any(ed["no_arquivo"] for linha in linhas_escola
                                             for ed in linha["por_edicao"]),
    }
