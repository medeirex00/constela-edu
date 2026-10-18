"""Leitura dos indicadores oficiais de UMA escola — etapa E9
(``GET /escolas/{id}/indicadores``).

Quem lê (decisão D5 do dono, 17/10): o coordenador (ou o admin) da PRÓPRIA escola, a
Secretaria da rede da escola e o admin global. O professor não lê; o painel público não
mostra nada disto.

O que a escola vê (plano, 5.2):

* os números OFICIAIS da própria escola — o SARESP do 2º e do 5º ano (proficiência do
  IEE, participação, TPS, IEE e meta) e o Ideb e o Saeb do 5º ano (com N, P, aprovação
  e a meta do 1º ciclo), com o MOTIVO quando não há número (nunca 0);
* as REFERÊNCIAS: a rede municipal, o Estado de São Paulo e o Brasil (os mesmos blocos
  da tela da Secretaria — SARESP por território, Ideb e Saeb da rede);
* o ICA SÓ como indicador DA REDE: o INEP não publica o ICA por escola, e ele vem
  rotulado assim (``papel = "referencia_da_rede"``) — nunca como "o ICA da escola";
* a FONTE de cada número (arquivo, edição, datas), como na tela da rede.

O que a escola NÃO vê: as outras escolas. Nada de tabela por escola, de cobertura
nominal ("escolas sem resultado", "escolas do arquivo fora do cadastro") nem das
estimativas de outra escola — sem ranking, nem implícito.

COMO: os números saem das MESMAS leituras da rede (``consulta_saresp``, ``consulta_ideb``
e ``consulta``), e daqui só se copia o que é da escola e das referências — por lista
de campos permitidos, nunca "tudo menos as outras escolas". Assim a escola vê
exatamente o número (e o motivo da ausência) que a Secretaria vê para ela.

Só LÊ (nem cria a linha do catálogo).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Escola, Rede
from app.services.avaliacoes import normalizar_inep
from app.services.indicadores import consulta, consulta_ideb, consulta_saresp
from app.services.indicadores.pipeline import codigo_ibge_da_rede

PAPEL_REFERENCIA_REDE = "referencia_da_rede"

AVISOS = {
    "escopo": ("Esta seção mostra só esta escola, com as referências da rede municipal, do "
               "Estado de São Paulo e do Brasil. Não é ranking: as outras escolas não "
               "aparecem."),
    "ica_da_rede": ("O Indicador Criança Alfabetizada (ICA) é da REDE municipal: o INEP não "
                    "publica o ICA por escola. O número aparece só como referência da rede — "
                    "não é o resultado desta escola."),
    "ausencia": ("Sem resultado não é zero: quando a escola não tem número numa edição, a "
                 "tela diz o motivo (não divulgado, fora do arquivo, sem código INEP...)."),
    "sem_rede": ("A escola não está vinculada a uma rede no cadastro: as referências oficiais "
                 "(recortadas pelo código IBGE da rede) e os números da escola não aparecem. "
                 "Quem vincula é o administrador global."),
}

# Avisos das leituras da rede que falam da TABELA de escolas — fora da visão da escola.
_AVISOS_SO_DA_REDE = {"sem_ranking"}


def _ids_de_fonte(obj, ids: set[int] | None = None) -> set[int]:
    """Os ids de importação citados num bloco: ``fonte.importacao_id`` (SARESP, ICA) e
    ``fonte_id`` (Ideb/Saeb) — para a lista de fontes trazer só as usadas."""
    ids = set() if ids is None else ids
    if isinstance(obj, dict):
        for chave, valor in obj.items():
            if chave == "fonte_id" and isinstance(valor, int):
                ids.add(valor)
            elif chave == "fonte" and isinstance(valor, dict):
                if isinstance(valor.get("importacao_id"), int):
                    ids.add(valor["importacao_id"])
            else:
                _ids_de_fonte(valor, ids)
    elif isinstance(obj, list):
        for item in obj:
            _ids_de_fonte(item, ids)
    return ids


def _avisos(avisos: dict) -> dict:
    return {k: v for k, v in (avisos or {}).items() if k not in _AVISOS_SO_DA_REDE}


def _saresp(dados: dict, escola_id: int) -> dict:
    linha = next((ln for ln in dados["escolas"]["linhas"] if ln["escola_id"] == escola_id),
                 None)
    # O arquivo do IEE de cada edição (a fonte do "sem resultado"): da cobertura, só a fonte.
    fonte_da_edicao = {c["edicao"]: c["fonte"] for c in dados["cobertura"]}
    por_edicao = [{**ed, "fonte_da_edicao": fonte_da_edicao.get(ed["edicao"])}
                  for ed in (linha["por_edicao"] if linha else [])]
    estimativas = [{k: v for k, v in est.items() if k not in ("escola_id", "nome", "codigo_inep")}
                   for est in dados["estimativas"] if est["escola_id"] == escola_id]
    territorios = dados["territorios"]
    ids = _ids_de_fonte(por_edicao) | _ids_de_fonte(territorios)
    return {
        "indicador": dados["indicador"], "municipio": dados["municipio"],
        "pendencias": list(dados["pendencias"]), "avisos": _avisos(dados["avisos"]),
        "etapas": dados["etapas"], "componentes": dados["componentes"],
        "edicoes": [ed["edicao"] for ed in por_edicao],
        "por_edicao": por_edicao, "estimativas": estimativas,
        "territorios": territorios, "edicoes_rede": dados["edicoes_rede"],
        "quebras_de_escala": dados["quebras_de_escala"], "niveis": dados["niveis"],
        "fontes": [f for f in dados["fontes"] if f and f.get("importacao_id") in ids],
        "tem_dados_escola": any(ed["no_arquivo"] for ed in por_edicao),
        "tem_dados": (any(ed["no_arquivo"] for ed in por_edicao)
                      or any(t["tem_dados"] for t in territorios)),
    }


def _ideb(dados: dict, escola_id: int) -> dict:
    linha = next((ln for ln in dados["escolas"] if ln["escola_id"] == escola_id), None)
    # O arquivo que vale para cada edição (a fonte do "sem resultado"): da cobertura, só o id.
    arquivo_da_edicao = {c["edicao"]: c["fonte_id"] for c in dados["cobertura"]}
    serie = [{**ed, "fonte_da_edicao_id": arquivo_da_edicao.get(ed["edicao"])}
             for ed in (linha["serie"] if linha else [])]
    rede_municipal = dados["rede_municipal"]
    ids = _ids_de_fonte(serie) | _ids_de_fonte(rede_municipal) | {
        ed["fonte_da_edicao_id"] for ed in serie if ed["fonte_da_edicao_id"] is not None}
    tem_escola = any(ed["no_arquivo"] for ed in serie)
    return {
        "indicadores": dados["indicadores"], "municipio": dados["municipio"],
        "pendencias": list(dados["pendencias"]), "avisos": _avisos(dados["avisos"]),
        "campos": dados["campos"], "edicoes": [ed["edicao"] for ed in serie],
        "anos_meta": dados["anos_meta"], "serie": serie,
        "tem_sem_registro": bool(linha and linha["tem_sem_registro"]),
        "participacao": dados["participacao"],
        "rede_municipal": rede_municipal,
        "fontes": [f for f in dados["fontes"] if f and f.get("importacao_id") in ids],
        "tem_dados_escola": tem_escola,
        "tem_dados": (tem_escola or rede_municipal["tem_dados"]
                      or rede_municipal["ideb"]["tem_dados"]
                      or rede_municipal["saeb"]["tem_dados"]),
    }


def _ica(dados: dict) -> dict:
    """O ICA inteiro da rede (não há nada de escola nele), rotulado como referência."""
    return {
        "papel": PAPEL_REFERENCIA_REDE, "aviso": AVISOS["ica_da_rede"],
        **{k: dados[k] for k in ("indicador", "aviso_rede", "legenda_nivel",
                                 "corte_alfabetizado", "pendencia", "territorios",
                                 "uf_municipal", "fontes", "tem_dados")},
    }


def indicadores_da_escola(db: Session, escola: Escola) -> dict:
    inep = normalizar_inep(escola.codigo_inep)
    saida = {
        "escola": {"id": escola.id, "nome": escola.nome, "codigo_inep": inep,
                   "status": escola.status, "pendencia": None if inep else "codigo_inep"},
        "rede": None, "avisos": {k: v for k, v in AVISOS.items() if k != "sem_rede"},
        "pendencias": [] if inep else ["codigo_inep"],
        "saresp": None, "ideb": None, "ica": None,
        "tem_dados_escola": False, "tem_dados": False,
    }
    rede = db.get(Rede, escola.rede_id) if escola.rede_id is not None else None
    if rede is None:
        saida["pendencias"].append("sem_rede")
        saida["avisos"]["sem_rede"] = AVISOS["sem_rede"]
        return saida
    saresp = _saresp(consulta_saresp.saresp_da_rede(db, rede), escola.id)
    ideb = _ideb(consulta_ideb.ideb_da_rede(db, rede), escola.id)
    ica = _ica(consulta.ica_da_rede(db, rede))
    saida.update(
        rede={"id": rede.id, "nome": rede.nome,
              "codigo_ibge": codigo_ibge_da_rede(rede),
              "municipio": saresp["municipio"] or ideb["municipio"]},
        saresp=saresp, ideb=ideb, ica=ica,
        tem_dados_escola=saresp["tem_dados_escola"] or ideb["tem_dados_escola"],
        tem_dados=saresp["tem_dados"] or ideb["tem_dados"] or ica["tem_dados"])
    if saida["rede"]["codigo_ibge"] is None:
        saida["pendencias"].append("codigo_ibge")
    return saida
