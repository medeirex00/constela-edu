"""Leitura do ICA oficial da rede: série 2023–2025, metas 2024–2030, nível,
participação, SP e Brasil — cada número com a fonte (arquivo, edição, datas).

Desde a E3, também o que vem dos microdados agregados (TS_MUNICIPIO/TS_ESTADO):
a média de LP, a distribuição por nível 0–8 (desde 2024) e a UF SÓ NAS REDES
MUNICIPAIS (``uf_municipal``) — a comparação justa com o município (plano, 4.8).
Os ``territorios`` continuam os três de sempre, cada um na SUA rede (município
municipal, UF e Brasil públicas); a UF municipal vem à parte, rotulada.

Só LÊ (nem cria a linha do catálogo). Sem dado importado, a lista vem vazia e a
tela diz "sem resultado importado" — nunca 0. A comparação resultado × meta é
feita SEMPRE na mesma precisão, a PUBLICADA (``casas_decimais`` e
``casas_decimais_detalhe``, não as casas do float). Exemplos SINTÉTICOS: 30 − 32 =
−2 p.p. na capa; 21,84 − 25,36 = −3,52 p.p. no detalhe; 27,90 × 27,86 publicados
com 2 casas = +0,04 ("atingiu" — com 1 casa seria um empate). Empate na precisão
divulgada é "inconclusivo", não "atingiu" (23 × 23 pode ser 22,6 × 23,3).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ImportacaoIndicador, IndicadorReferencia, Rede
from app.services.avaliacoes import CATALOGO
from app.services.indicadores import aeeb, ica
from app.services.indicadores import leituras_da_requisicao as leituras
from app.services.indicadores.pipeline import (CHAVE_AVALIACAO, casas_do_detalhe,
                                               codigo_ibge_da_rede)

AVISO_REDE = ("O ICA é o indicador da REDE municipal: o INEP não publica o ICA por "
              "escola. Ele não serve para comparar nem ordenar escolas.")

# Faixas oficiais do nível do município — aba "Variáveis" dos arquivos do INEP.
# Só LEGENDA: o Constela não calcula o nível, mostra o campo oficial.
LEGENDA_NIVEL = [
    {"nivel": 0, "rotulo": "Abaixo do nível 1", "faixa": "até 40%"},
    {"nivel": 1, "rotulo": "Nível 1", "faixa": "entre 40% e 50%"},
    {"nivel": 2, "rotulo": "Nível 2", "faixa": "entre 50% e 60%"},
    {"nivel": 3, "rotulo": "Nível 3", "faixa": "entre 60% e 70%"},
    {"nivel": 4, "rotulo": "Nível 4", "faixa": "entre 70% e 80%"},
    {"nivel": 5, "rotulo": "Nível 5", "faixa": "acima de 80%"},
]

_ORDEM_ABRANGENCIA = ("municipio", "uf", "brasil")


def _iso(valor):
    return valor.isoformat() if valor else None


def _fonte(imp: ImportacaoIndicador | None) -> dict | None:
    if imp is None:
        return None
    return {
        "importacao_id": imp.id, "fonte_nome": imp.fonte_nome,
        "arquivo_nome": imp.arquivo_nome, "arquivo_data": _iso(imp.arquivo_data),
        "last_modified_origem": imp.last_modified_origem, "url_origem": imp.url_origem,
        "edicao_arquivo": imp.edicao_arquivo, "versao_rotulo": imp.versao_rotulo,
        "importado_em": _iso(imp.aplicado_em), "coletado_em": _iso(imp.coletado_em),
        "citacao": imp.citacao, "licenca": imp.licenca,
        # inep_ica_* (planilha de resultados) | inep_aeeb_agregados (microdados)
        "parser": imp.parser, "modo": imp.modo,
        "notas": list((imp.resumo or {}).get("notas_arquivo") or [])[:10],
    }


def _numero(linha: IndicadorReferencia, imps: dict[int, ImportacaoIndicador]) -> dict:
    detalhe = None
    if linha.valor_detalhado is not None:
        detalhe = {"valor": linha.valor_detalhado,
                   "casas_decimais": casas_do_detalhe(linha),   # a publicada, não a do float
                   "fonte": _fonte(imps.get(linha.detalhe_importacao_id))}
    return {
        "edicao": linha.edicao, "valor": linha.valor, "casas_decimais": linha.casas_decimais,
        "nivel": linha.nivel or None,
        "operador": linha.operador, "unidade": linha.unidade,
        "motivo_ausencia": linha.motivo_ausencia,
        "fonte": _fonte(imps.get(linha.importacao_id)), "detalhe": detalhe,
    }


def _preciso(numero: dict) -> tuple[float, int]:
    """O valor mais preciso conhecido: o detalhe, se houver, senão a capa."""
    if numero["detalhe"]:
        return numero["detalhe"]["valor"], numero["detalhe"]["casas_decimais"]
    return numero["valor"], numero["casas_decimais"] or 0


def _diferenca(r: float, cr: int, m: float, cm: int) -> tuple[float, int]:
    casas = min(cr, cm)
    return round(ica.arredondar(r, casas) - ica.arredondar(m, casas), casas), casas


def _decidir(diferenca: float) -> str | None:
    """Decisivo só quando os dois números DIFEREM na precisão comparada: valores
    arredondados diferentes na mesma precisão não podem se inverter (26 × 27 é
    "não atingiu" qualquer que seja a casa decimal). Igual → não dá para afirmar
    (vale também para a meta "> 80" com resultado 80)."""
    if diferenca > 0:
        return "atingiu"
    if diferenca < 0:
        return "nao_atingiu"
    return None


def comparar(resultado: dict, meta: dict) -> dict | None:
    """Resultado × meta da mesma edição: diferença em p.p. na capa e, quando houver
    casas decimais dos dois lados, no detalhe; situação "atingiu" | "nao_atingiu" |
    "inconclusivo" (empate na melhor precisão disponível)."""
    if resultado["valor"] is None or meta["valor"] is None:
        return None
    dif, casas = _diferenca(resultado["valor"], resultado["casas_decimais"] or 0,
                            meta["valor"], meta["casas_decimais"] or 0)
    rp, crp = _preciso(resultado)
    mp, cmp_ = _preciso(meta)
    dif_det, casas_det = _diferenca(rp, crp, mp, cmp_)
    tem_detalhe = casas_det > casas
    situacao = (_decidir(dif) or (_decidir(dif_det) if tem_detalhe else None)
                or "inconclusivo")
    return {
        "edicao": resultado["edicao"], "resultado": resultado["valor"],
        "meta": meta["valor"], "operador": meta["operador"],
        "diferenca_pp": dif, "casas_decimais": casas,
        "diferenca_pp_detalhe": dif_det if tem_detalhe else None,
        "casas_decimais_detalhe": casas_det if tem_detalhe else None,
        "situacao": situacao,
    }


def _distribuicao(niveis: list[dict]) -> list[dict]:
    """``pct_nivel`` agrupado por edição, níveis 0–8 em ordem (ausência ≠ 0)."""
    por_edicao: dict[int, list[dict]] = {}
    for n in niveis:
        por_edicao.setdefault(n["edicao"], []).append(n)
    saida = []
    for edicao in sorted(por_edicao):
        itens = sorted(por_edicao[edicao], key=lambda n: int(n["nivel"] or 0))
        com_valor = [n["valor"] for n in itens if n["valor"] is not None]
        saida.append({"edicao": edicao, "niveis": itens,
                      "soma": round(sum(com_valor), 2) if len(com_valor) == len(itens) else None})
    return saida


def _territorio(abrangencia: str, codigo: str, nome: str, linhas: list[IndicadorReferencia],
                imps: dict[int, ImportacaoIndicador], rede_ensino: str | None = None) -> dict:
    por_indicador: dict[str, list[dict]] = {}
    for linha in sorted(linhas, key=lambda ln: (ln.edicao, int(ln.nivel or 0))):
        por_indicador.setdefault(linha.indicador, []).append(_numero(linha, imps))
    resultados = por_indicador.get(ica.IND_RESULTADO, [])
    metas = por_indicador.get(ica.IND_META, [])
    meta_por_ano = {m["edicao"]: m for m in metas}
    comparacoes = [c for r in resultados
                   if (m := meta_por_ano.get(r["edicao"])) and (c := comparar(r, m))]
    com_valor = [r for r in resultados if r["valor"] is not None]
    destaque = None
    if com_valor:
        ultimo = com_valor[-1]
        destaque = {"resultado": ultimo, "meta": meta_por_ano.get(ultimo["edicao"]),
                    "comparacao": next((c for c in comparacoes
                                        if c["edicao"] == ultimo["edicao"]), None)}
    return {
        "abrangencia": abrangencia, "codigo_territorio": codigo, "nome": nome,
        "rede_ensino": rede_ensino or ("municipal" if abrangencia == "municipio" else "publica"),
        "resultados": resultados, "metas": metas,
        "nivel": por_indicador.get(ica.IND_NIVEL, []),
        "participacao": por_indicador.get(ica.IND_PARTICIPACAO, []),
        "media_lp": por_indicador.get(aeeb.IND_MEDIA_LP, []),
        "distribuicao_niveis": _distribuicao(por_indicador.get(aeeb.IND_PCT_NIVEL, [])),
        "comparacoes": comparacoes, "destaque": destaque,
        "tem_dados": bool(linhas),
    }


def ica_da_rede(db: Session, rede: Rede) -> dict:
    catalogo = CATALOGO[CHAVE_AVALIACAO]
    codigo = codigo_ibge_da_rede(rede)
    saida = {
        "rede_id": rede.id, "rede_nome": rede.nome, "codigo_ibge": codigo,
        "indicador": {"chave": CHAVE_AVALIACAO, "nome": catalogo["nome"],
                      "orgao": catalogo["orgao"], "descricao": catalogo["descricao"]},
        "aviso_rede": AVISO_REDE, "legenda_nivel": LEGENDA_NIVEL,
        "corte_alfabetizado": aeeb.CORTE_ALFABETIZADO,
        "pendencia": None if codigo else "codigo_ibge",
        "territorios": [], "uf_municipal": None, "fontes": [], "tem_dados": False,
    }
    if codigo is None:
        return saida
    codigos = {"municipio": codigo, "uf": codigo[:2], "brasil": ica.CODIGO_BRASIL}
    av = leituras.avaliacao(db, CHAVE_AVALIACAO)
    linhas: list[IndicadorReferencia] = []
    if av is not None:
        # Só a MESMA rede de ensino em cada nível: municipal no município, pública
        # na UF e no Brasil — e a UF nas redes municipais, à parte e rotulada
        # (comparar redes diferentes exigiria rótulo explícito).
        if leituras.ativa(db):
            # O mesmo filtro, sobre as linhas lidas uma vez na requisição (com os INEPs da
            # rede: o SARESP e o Ideb da escola usam as de escola da mesma leitura).
            territorios = set(codigos.values())
            candidatas = [ln for ln in leituras.referencias(
                db, codigo, leituras.ineps_da_rede(db, rede.id))
                if ln.avaliacao_id == av.id and ln.codigo_territorio in territorios
                and ln.codigo_inep == "" and ln.localizacao == "total"]
        else:
            candidatas = db.execute(select(IndicadorReferencia).where(
                IndicadorReferencia.avaliacao_id == av.id,
                IndicadorReferencia.codigo_territorio.in_(set(codigos.values())),
                IndicadorReferencia.codigo_inep == "",
                IndicadorReferencia.localizacao == "total")).scalars()
        linhas = [ln for ln in candidatas
                  if (ln.abrangencia, ln.codigo_territorio, ln.rede_ensino) in {
                      ("municipio", codigos["municipio"], "municipal"),
                      ("uf", codigos["uf"], "publica"),
                      ("uf", codigos["uf"], "municipal"),
                      ("brasil", codigos["brasil"], "publica")}]
    ids = {i for ln in linhas for i in (ln.importacao_id, ln.detalhe_importacao_id) if i}
    imps = leituras.importacoes_por_id(db, ids, codigo=codigo)
    nomes = {}
    for imp in sorted(imps.values(), key=lambda i: i.id):
        nomes.update((imp.resumo or {}).get("territorios") or {})
    padrao = {"municipio": rede.nome, "uf": f"UF {codigos['uf']}", "brasil": "Brasil"}
    for abrangencia in _ORDEM_ABRANGENCIA:
        cod = codigos[abrangencia]
        saida["territorios"].append(_territorio(
            abrangencia, cod, nomes.get(cod) or padrao[abrangencia],
            [ln for ln in linhas if ln.abrangencia == abrangencia
             and ln.rede_ensino == ("municipal" if abrangencia == "municipio" else "publica")],
            imps))
    saida["uf_municipal"] = _territorio(
        "uf", codigos["uf"], nomes.get(codigos["uf"]) or padrao["uf"],
        [ln for ln in linhas if ln.abrangencia == "uf" and ln.rede_ensino == "municipal"],
        imps, rede_ensino="municipal")
    saida["fontes"] = [_fonte(i) for i in sorted(
        imps.values(), key=lambda i: (i.edicao_arquivo, i.arquivo_data or i.created_at),
        reverse=True)]
    saida["tem_dados"] = bool(linhas)
    return saida
