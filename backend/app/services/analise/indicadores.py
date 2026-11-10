"""Indicadores OFICIAIS na forma única da análise educacional (só leitura).

``GET /redes/{id}/analise/indicadores`` (o catálogo: o que existe, desde quando, com o
quê comparar) e ``GET /redes/{id}/analise/indicadores/{chave}`` (as séries de UM
indicador, ou a visão por escolas de uma edição).

COMO: nada aqui relê as tabelas oficiais. Os números saem das MESMAS leituras das telas
de indicadores — ``consulta.ica_da_rede`` (ICA), ``consulta_saresp.saresp_da_rede``
(SARESP e IEE) e ``consulta_ideb.ideb_da_rede`` (Ideb e Saeb, com o bloco da rede
municipal de ``consulta_ideb_rede``) — e este módulo só NORMALIZA a saída delas num
formato comum: série → pontos ``{edicao, valor, casas, motivo_ausencia, meta,
diferenca_meta, situacao_meta, instavel, fonte_id}``. Os números, as ausências (com o
motivo), as metas e as comparações com a meta são os que as consultas devolvem — a
regra de cada indicador continua lá (o "inconclusivo" do ICA no empate, o "Ideb ≥ meta"
do INEP, as metas do Ideb só até 2021...). As únicas contas feitas aqui são a
diferença IEE − meta (na precisão publicada, pela conta do ICA) e a situação da meta do
IEE, que é o ICM OFICIAL da SEDUC (1 = cumpriu), nunca uma comparação nova.

O QUE É OFICIAL: só número com importação oficial (``importacao_id``) ou do território
(``indicadores_referencia``). Dois casos ficam de fora dos destaques e da relação, cada um
com o seu nome — nunca confundidos:

* a "Estimativa Constela" (``crianca_alfabetizada`` e as médias do SARESP calculadas pelo
  Constela) não entra em série oficial nenhuma: aparece só em ``estimativas``, com o tipo
  ``estimativa_constela``;
* o Ideb e o Saeb por escola gravados ANTES pelo botão de 1 clique, sem ``importacao_id``
  (a importação oficial os mantém quando são iguais ao arquivo), aparecem nas séries e na
  visão por escolas como a consulta oficial os mostra — com ``proveniencia =
  "sem_registro"``, ``texto_proveniencia`` e ``difere_do_oficial`` — e são listados em
  ``sem_registro_oficial``; nunca são chamados de estimativa.

COMPARABILIDADE: cada série diz o PAPEL (``principal`` — a rede ou a escola escolhida;
``referencia`` — a mesma rede de ensino noutro território, comparável; ``contexto`` —
outra rede de ensino, ``comparavel = False`` com o motivo). A ordem das séries é fixa e
a das escolas, alfabética: nada aqui é ranking.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AvaliacaoExterna, Escola, Rede, ResultadoAvaliacao
from app.services.analise import K_MINIMO, N_MINIMO, AnaliseInvalida
from app.services.avaliacoes import CATALOGO, _EXIBICAO, nome_exibicao, normalizar_inep
from app.services.indicadores import (consulta, consulta_ideb, consulta_ideb_rede,
                                      consulta_saresp, seduc)
from app.services.indicadores import leituras_da_requisicao as leituras
from app.services.indicadores.pipeline import codigo_ibge_da_rede

PRINCIPAL, REFERENCIA, CONTEXTO = "principal", "referencia", "contexto"
VISOES = ("serie", "escolas")

ROTULO_ETAPA = {"2_ano": "2º ano", "5_ano": "5º ano",
                "anos_iniciais": "anos iniciais (1º ao 5º ano)"}
ROTULO_COMPONENTE = {"lp": "Língua Portuguesa", "mt": "Matemática"}

MOTIVO_SEM_RESULTADO = "sem_resultado"
# O único registro da escola nesta edição é uma AUSÊNCIA gravada antes, sem o registro do
# arquivo oficial (o número sem registro, com valor, aparece no ponto, marcado).
MOTIVO_SEM_REGISTRO = "sem_registro_oficial"

# Proveniência de cada número com valor (a de ``consulta_ideb._numero_resultado``).
PROVENIENCIA_OFICIAL = consulta_ideb.PROVENIENCIA_OFICIAL
PROVENIENCIA_SEM_REGISTRO = consulta_ideb.PROVENIENCIA_SEM_REGISTRO
TEXTO_SEM_REGISTRO = "número gravado antes, sem o registro do arquivo oficial"
TEXTO_DIFERE = "difere do arquivo oficial"
# A edição não tem meta oficial (ICA antes de 2024; Ideb fora do 1º ciclo...).
SEM_META_NA_EDICAO = "sem_meta_na_edicao"

TEXTOS_AUSENCIA = {
    "nao_divulgado": "não divulgado no arquivo oficial",
    "participacao_baixa": "sem resultado: participação abaixo do mínimo da fonte",
    "sem_meta": "sem meta definida no arquivo oficial",
    "fora_do_arquivo": "a escola não está no arquivo oficial importado desta edição",
    "sem_importacao": "nenhum arquivo oficial desta edição foi importado",
    "sem_codigo_inep": "a escola está sem código INEP no cadastro",
    "cadastrado_depois_da_importacao": ("o código INEP foi cadastrado depois da importação; "
                                        "reimporte o arquivo oficial desta edição"),
    "codigo_inep_alterado": ("o código INEP da escola mudou depois da importação; reimporte o "
                             "arquivo oficial desta edição"),
    "estimativa_mantida_d2": ("o número oficial não foi gravado: a estimativa do Constela foi "
                              "mantida (decisão D2)"),
    MOTIVO_SEM_RESULTADO: "sem resultado nesta edição",
    MOTIVO_SEM_REGISTRO: ("o único registro desta edição foi gravado antes, sem o registro "
                          "do arquivo oficial"),
}
_TEXTOS_AUSENCIA_ICA = {"participacao_baixa": "sem resultado: participação abaixo de 70%"}

TEXTOS_SEM_META = {
    consulta_ideb_rede.SEM_META_DEPOIS_DO_CICLO: "o INEP não definiu meta do Ideb depois de 2021",
    consulta_ideb_rede.SEM_META_ANTES_DO_CICLO: ("sem meta nesta edição (as metas do Ideb "
                                                 "começam em 2007)"),
    consulta_ideb_rede.SEM_META_SEM_ARQUIVO: "metas só com o arquivo oficial importado",
    consulta_ideb_rede.SEM_META_NO_ARQUIVO: "o arquivo do INEP não traz meta para esta rede",
    "sem_meta": "sem meta definida no arquivo oficial",
    SEM_META_NA_EDICAO: "não há meta oficial para esta edição",
}

TEXTOS_INDISPONIVEL = {
    "sem_codigo_ibge": ("a rede não tem o código IBGE do município cadastrado: os números da "
                        "rede não podem ser recortados"),
    "sem_importacao": "nenhum arquivo oficial deste indicador foi importado para esta rede",
    "so_estimativa": ("só há a Estimativa Constela (calculada pelo Constela): ela não é o "
                      "indicador oficial"),
    "so_sem_registro": ("só há números gravados antes, sem o registro do arquivo oficial: "
                        "importe o arquivo oficial desta edição"),
}

# A metodologia em linguagem simples, para a tela (sem caminho de arquivo nem nome de
# campo; o documento completo é docs/analise/METODOLOGIA.md).
METODOLOGIA_RESUMO = [
    ("Oficial × estimativa: só os números com o registro do arquivo oficial entram nos "
     "destaques e na relação com as plataformas. A Estimativa Constela aparece à parte; os "
     "números gravados antes, sem o registro do arquivo oficial, aparecem marcados."),
    ("Sem resultado não é zero: cada falta vem com o motivo, e nenhum número é inventado, "
     "interpolado ou preenchido."),
    "Sem ranking: as escolas aparecem sempre em ordem alfabética.",
    ("Escalas e redes diferentes não se comparam: SARESP, Saeb e ICA têm escalas próprias; a "
     "rede pública ou estadual aparece só como contexto da rede municipal."),
    (f"Plataformas: entram só os alunos que a plataforma conhece no período; recortes com "
     f"menos de {K_MINIMO} alunos não aparecem (e recortes vizinhos podem ficar escondidos "
     "junto); a soma da rede é só das escolas mostradas, com a coleta em dia."),
    (f"Relação com as avaliações: por escola, com números oficiais, na mesma série e no mesmo "
     f"ano letivo, com pelo menos {N_MINIMO} escolas; correlação de postos de Spearman com "
     "intervalo de 95%. Descreve associação entre escolas, nunca causa e efeito."),
]

_OUTRA_REDE_PUBLICA = ("Outra rede: o INEP publica este território na rede PÚBLICA (estadual "
                       "e municipal). Só contexto — não é comparação com a rede municipal.")
_OUTRA_REDE_ESTADUAL = ("Outra rede: é a rede ESTADUAL. Só contexto — não é comparação com a "
                        "rede municipal.")


def texto_ausencia(motivo: str | None, chave: str | None = None) -> str | None:
    if not motivo:
        return None
    if chave == "ica" and motivo in _TEXTOS_AUSENCIA_ICA:
        return _TEXTOS_AUSENCIA_ICA[motivo]
    return TEXTOS_AUSENCIA.get(motivo, "sem resultado")


def _fid(fonte) -> int | None:
    return fonte.get("importacao_id") if isinstance(fonte, dict) else None


def _casas(numero: dict | None) -> int | None:
    return numero.get("casas_decimais") if numero else None


def ordem_nome(nome: str | None, escola_id: int) -> tuple[str, int]:
    """A ordem das escolas em TODA a análise: alfabética, sem acento e sem caixa (a
    mesma das consultas oficiais) — nunca por valor."""
    return seduc.sem_acento(nome or "").casefold(), escola_id


# --- Formato comum -----------------------------------------------------------------

def ponto(edicao: int, *, chave: str, valor=None, casas=None, motivo=None, fonte_id=None,
          valor_detalhado=None, casas_detalhe=None, fonte_detalhe_id=None,
          meta=None, meta_casas=None, operador_meta=None, sem_meta=None, fonte_meta_id=None,
          diferenca=None, diferenca_casas=None, diferenca_detalhe=None, situacao=None,
          instavel=False, proveniencia=PROVENIENCIA_OFICIAL, difere=False, **extra) -> dict:
    """Um ponto da série. Sem valor, SEMPRE um motivo (ausência ≠ zero); a diferença e
    a situação da meta só existem com o valor e a meta. Com valor, a PROVENIÊNCIA: o
    número oficial ou o gravado antes, sem o registro do arquivo oficial (marcado)."""
    if valor is not None:
        motivo = None
    elif not motivo:
        motivo = MOTIVO_SEM_RESULTADO
    tem_comparacao = valor is not None and meta is not None
    sem_registro = valor is not None and proveniencia == PROVENIENCIA_SEM_REGISTRO
    texto_prov = None
    if sem_registro:
        texto_prov = TEXTO_SEM_REGISTRO + (f"; {TEXTO_DIFERE}" if difere else "")
    return {
        "edicao": edicao, "valor": valor, "casas": casas if valor is not None else None,
        "valor_detalhado": valor_detalhado if valor is not None else None,
        "casas_detalhe": casas_detalhe if valor_detalhado is not None else None,
        "motivo_ausencia": motivo, "texto_ausencia": texto_ausencia(motivo, chave),
        "meta": meta, "meta_casas": meta_casas if meta is not None else None,
        "operador_meta": operador_meta if meta is not None else None,
        "motivo_sem_meta": sem_meta if meta is None else None,
        "texto_sem_meta": TEXTOS_SEM_META.get(sem_meta) if meta is None and sem_meta else None,
        "diferenca_meta": (diferenca + 0.0) if tem_comparacao and diferenca is not None else None,
        "diferenca_casas": diferenca_casas if tem_comparacao and diferenca is not None else None,
        "diferenca_meta_detalhe": diferenca_detalhe if tem_comparacao else None,
        "situacao_meta": situacao if tem_comparacao else None,
        "instavel": bool(instavel and valor is not None),
        "fonte_id": fonte_id, "fonte_meta_id": fonte_meta_id if meta is not None else None,
        "fonte_detalhe_id": fonte_detalhe_id if valor_detalhado is not None else None,
        "proveniencia": proveniencia if valor is not None else None,
        "texto_proveniencia": texto_prov,
        "difere_do_oficial": bool(sem_registro and difere),
        **extra,
    }


def e_oficial(p: dict) -> bool:
    """O ponto tem número OFICIAL (com o registro do arquivo oficial)."""
    return p["valor"] is not None and p.get("proveniencia") == PROVENIENCIA_OFICIAL


def e_sem_registro(p: dict) -> bool:
    """O ponto tem um número gravado antes, sem o registro do arquivo oficial."""
    return p["valor"] is not None and p.get("proveniencia") == PROVENIENCIA_SEM_REGISTRO


def serie(id_: str, *, rotulo: str, papel: str, abrangencia: str, rede_ensino: str,
          mesma_rede: bool, comparavel: bool, pontos: list[dict],
          motivo_nao_comparavel: str | None = None, escola_id: int | None = None,
          etapa: str | None = None, componente: str | None = None, **extra) -> dict:
    return {
        "id": id_, "rotulo": rotulo, "papel": papel, "abrangencia": abrangencia,
        "escola_id": escola_id, "rede_ensino": rede_ensino, "mesma_rede": mesma_rede,
        "comparavel": comparavel,
        "motivo_nao_comparavel": None if comparavel else motivo_nao_comparavel,
        "etapa": etapa, "componente": componente,
        "pontos": sorted(pontos, key=lambda p: p["edicao"]), **extra,
    }


class Leituras:
    """As leituras OFICIAIS da rede, cada uma feita no máximo UMA vez por requisição."""

    def __init__(self, db: Session, rede: Rede):
        self.db, self.rede = db, rede
        self._cache: dict[str, dict] = {}

    def _ler(self, nome: str, funcao) -> dict:
        if nome not in self._cache:
            self._cache[nome] = funcao(self.db, self.rede)
        return self._cache[nome]

    @property
    def ica(self) -> dict:
        return self._ler("ica", consulta.ica_da_rede)

    @property
    def saresp(self) -> dict:
        return self._ler("saresp", consulta_saresp.saresp_da_rede)

    @property
    def ideb(self) -> dict:
        return self._ler("ideb", consulta_ideb.ideb_da_rede)


# --- Indicadores ---------------------------------------------------------------------

class _Indicador:
    chave = ""
    unidade = ""
    escala = ""
    abrangencias: tuple[str, ...] = ()
    por_escola = False
    etapas: tuple[str, ...] = ()
    componentes: tuple[str, ...] = ()
    tem_meta = False

    @property
    def nome(self) -> str:
        return CATALOGO[self.chave]["nome"]

    @property
    def orgao(self) -> str:
        return CATALOGO[self.chave]["orgao"]

    def combos(self) -> list[tuple[str, str | None]]:
        return [(et, c) for et in self.etapas for c in (self.componentes or (None,))]

    # O que cada indicador implementa ------------------------------------------------
    def codigo_ausente(self, L: Leituras) -> bool:
        return codigo_ibge_da_rede(L.rede) is None

    def series_rede(self, L: Leituras, etapa: str, comp: str | None) -> list[dict]:
        return []

    def linhas(self, L: Leituras) -> list[dict]:
        return []

    def pontos_escola(self, L: Leituras, linha: dict, etapa: str, comp: str | None) -> list[dict]:
        return []

    def fontes(self, L: Leituras) -> dict[int, dict]:
        return {}

    def quebras(self, etapa: str | None) -> list[dict]:
        return []

    def avisos(self, L: Leituras, etapa: str | None = None, comp: str | None = None, *,
               escola: bool = False) -> list[str]:
        return []

    def estimativas_na_edicao(self, L: Leituras, edicao: int, etapa: str,
                              comp: str | None) -> int:
        return 0

    def sem_registro_na_edicao(self, L: Leituras, edicao: int, etapa: str,
                               comp: str | None) -> int:
        return 0

    # Derivados (iguais para todos) --------------------------------------------------
    def _principal(self, L: Leituras, etapa: str, comp: str | None) -> dict | None:
        return next((s for s in self.series_rede(L, etapa, comp) if s["papel"] == PRINCIPAL),
                    None)

    def tem_oficial(self, L: Leituras) -> bool:
        for etapa, comp in self.combos():
            p = self._principal(L, etapa, comp)
            if p and any(e_oficial(pt) for pt in p["pontos"]):
                return True
            for linha in self.linhas(L):
                if any(e_oficial(pt) for pt in self.pontos_escola(L, linha, etapa, comp)):
                    return True
        return False

    def tem_estimativa(self, L: Leituras) -> bool:
        return False

    def tem_sem_registro(self, L: Leituras) -> bool:
        return False

    def disponibilidade(self, L: Leituras) -> tuple[bool, str | None]:
        if self.tem_oficial(L):
            return True, None
        if self.tem_estimativa(L):
            return False, "so_estimativa"
        if self.tem_sem_registro(L):
            return False, "so_sem_registro"
        if self.codigo_ausente(L):
            return False, "sem_codigo_ibge"
        return False, "sem_importacao"

    def edicoes(self, L: Leituras) -> list[int]:
        """As edições com algum número OFICIAL (da rede ou de escola)."""
        eds: set[int] = set()
        for etapa, comp in self.combos():
            p = self._principal(L, etapa, comp)
            eds |= {pt["edicao"] for pt in (p["pontos"] if p else []) if e_oficial(pt)}
            for linha in self.linhas(L):
                eds |= {pt["edicao"] for pt in self.pontos_escola(L, linha, etapa, comp)
                        if e_oficial(pt)}
        return sorted(eds)

    def item(self, L: Leituras) -> dict:
        disponivel, motivo = self.disponibilidade(L)
        edicoes = self.edicoes(L)
        return {
            "chave": self.chave, "nome": self.nome, "orgao": self.orgao, "oficial": True,
            "unidade": self.unidade, "escala": self.escala,
            "disponivel": disponivel, "motivo_indisponivel": motivo,
            "texto_indisponivel": TEXTOS_INDISPONIVEL.get(motivo) if motivo else None,
            "abrangencias": list(self.abrangencias), "por_escola": self.por_escola,
            "etapas": list(self.etapas), "componentes": list(self.componentes),
            "rotulos_etapas": {et: ROTULO_ETAPA[et] for et in self.etapas},
            "rotulos_componentes": {c: ROTULO_COMPONENTE[c] for c in self.componentes},
            "edicoes": edicoes, "edicao_mais_recente": edicoes[-1] if edicoes else None,
            "tem_meta": self.tem_meta, "avisos": self.avisos(L),
        }

    def rotulo_destaque(self, etapa: str, comp: str | None) -> str:
        partes = [ROTULO_ETAPA[etapa]] + ([ROTULO_COMPONENTE[comp]] if comp else [])
        return f"{self.nome} da rede — {', '.join(partes)}"

    def destaque(self, L: Leituras) -> dict | None:
        """O número mais recente DA REDE (série principal), com a meta e a minitendência.
        Entre as séries (etapa × componente), a de edição mais nova; no empate, a ordem
        fixa do indicador."""
        melhor = None
        for etapa, comp in self.combos():
            p = self._principal(L, etapa, comp)
            com_valor = [pt for pt in (p["pontos"] if p else []) if e_oficial(pt)]
            if com_valor and (melhor is None or com_valor[-1]["edicao"] > melhor[2]["edicao"]):
                melhor = (etapa, comp, com_valor[-1], p)
        if melhor is None:
            return None
        etapa, comp, ultimo, p = melhor
        return {
            "indicador": self.chave, "rotulo": self.rotulo_destaque(etapa, comp),
            "etapa": etapa, "componente": comp, "edicao": ultimo["edicao"],
            "valor": ultimo["valor"], "casas": ultimo["casas"], "unidade": self.unidade,
            "meta": ultimo["meta"], "meta_casas": ultimo["meta_casas"],
            "diferenca_meta": ultimo["diferenca_meta"],
            "diferenca_casas": ultimo["diferenca_casas"],
            "situacao_meta": ultimo["situacao_meta"],
            "motivo_sem_meta": ultimo["motivo_sem_meta"],
            "texto_sem_meta": ultimo["texto_sem_meta"],
            "fonte_id": ultimo["fonte_id"],
            "serie": [{"edicao": pt["edicao"], "valor": pt["valor"], "casas": pt["casas"],
                       "motivo_ausencia": pt["motivo_ausencia"]} for pt in p["pontos"]],
            "quebras": self.quebras(etapa),
        }


def escola_da_linha(linha: dict) -> dict:
    inep = linha.get("codigo_inep")
    return {"escola_id": linha["escola_id"], "nome": linha["nome"], "codigo_inep": inep,
            "pendencia": None if inep else "sem_codigo_inep"}


# --- ICA ----------------------------------------------------------------------------

class _ICA(_Indicador):
    chave = "ica"
    unidade = "%"
    escala = "percentual"
    abrangencias = ("rede",)
    etapas = ("2_ano",)
    componentes = ("lp",)
    tem_meta = True

    def rotulo_destaque(self, etapa, comp):
        return "ICA da rede (2º ano)"

    def avisos(self, L, etapa=None, comp=None, *, escola=False):
        return [consulta.AVISO_REDE,
                ("SP e Brasil: o INEP publica o ICA na rede PÚBLICA (estadual e municipal) — "
                 "outra rede, só contexto. A comparação na mesma rede é com a UF nas redes "
                 "municipais."),
                ("Resultado × meta na precisão divulgada: o empate é “inconclusivo” (23 × 23 "
                 "pode ser 22,6 × 23,3), não “atingiu”.")]

    def _pontos(self, t: dict | None) -> list[dict]:
        if not t:
            return []
        metas = {m["edicao"]: m for m in t["metas"]}
        comps = {c["edicao"]: c for c in t["comparacoes"]}
        saida = []
        for r in t["resultados"]:
            m, c, det = metas.get(r["edicao"]), comps.get(r["edicao"]), r["detalhe"] or {}
            sem_meta = (m["motivo_ausencia"] or "sem_meta") if m and m["valor"] is None else (
                SEM_META_NA_EDICAO if m is None else None)
            saida.append(ponto(
                r["edicao"], chave=self.chave, valor=r["valor"], casas=r["casas_decimais"],
                motivo=r["motivo_ausencia"], fonte_id=_fid(r["fonte"]),
                valor_detalhado=det.get("valor"), casas_detalhe=det.get("casas_decimais"),
                fonte_detalhe_id=_fid(det.get("fonte")),
                meta=m["valor"] if m else None, meta_casas=_casas(m),
                operador_meta=m["operador"] if m else None, sem_meta=sem_meta,
                fonte_meta_id=_fid(m["fonte"]) if m else None,
                diferenca=c["diferenca_pp"] if c else None,
                diferenca_casas=c["casas_decimais"] if c else None,
                diferenca_detalhe=c["diferenca_pp_detalhe"] if c else None,
                situacao=c["situacao"] if c else None))
        return saida

    @staticmethod
    def _metas(t: dict | None) -> list[dict]:
        return [{"edicao": m["edicao"], "valor": m["valor"], "casas": m["casas_decimais"],
                 "operador": m["operador"], "motivo_ausencia": m["motivo_ausencia"],
                 "fonte_id": _fid(m["fonte"])} for m in (t or {}).get("metas", [])]

    def series_rede(self, L, etapa, comp):
        d = L.ica
        terr = {t["abrangencia"]: t for t in d["territorios"]}
        mun = terr.get("municipio")
        nome_mun = (mun or {}).get("nome") or d["rede_nome"]
        saida = [serie("rede_municipal", rotulo=f"{nome_mun} — rede municipal", papel=PRINCIPAL,
                       abrangencia="rede", rede_ensino="municipal", mesma_rede=True,
                       comparavel=True, pontos=self._pontos(mun), etapa="2_ano",
                       componente="lp", metas=self._metas(mun))]
        uf_mun = d.get("uf_municipal")
        if uf_mun and uf_mun["resultados"]:
            saida.append(serie("uf_redes_municipais", rotulo=f"{uf_mun['nome']} — redes municipais",
                               papel=REFERENCIA, abrangencia="uf", rede_ensino="municipal",
                               mesma_rede=True, comparavel=True, pontos=self._pontos(uf_mun),
                               etapa="2_ano", componente="lp", metas=self._metas(uf_mun)))
        for abr, id_, rotulo in (("uf", "uf_rede_publica", "rede pública"),
                                 ("brasil", "brasil_rede_publica", "rede pública")):
            t = terr.get(abr)
            if t and t["resultados"]:
                saida.append(serie(id_, rotulo=f"{t['nome']} — {rotulo}", papel=CONTEXTO,
                                   abrangencia=abr, rede_ensino="publica", mesma_rede=False,
                                   comparavel=False, motivo_nao_comparavel=_OUTRA_REDE_PUBLICA,
                                   pontos=self._pontos(t), etapa="2_ano", componente="lp",
                                   metas=self._metas(t)))
        return saida

    def fontes(self, L):
        return {f["importacao_id"]: f for f in L.ica["fontes"] if f}


# --- SARESP e IEE (a mesma leitura: consulta_saresp) -----------------------------------

_SARESP_TERRITORIOS = {
    # chave da consulta → (id na análise, papel, abrangência, motivo de não comparar)
    "rede_municipal": ("rede_municipal", PRINCIPAL, "rede", None),
    "estado_redes_municipais": ("uf_redes_municipais", REFERENCIA, "uf", None),
    "rede_estadual_no_municipio": ("rede_estadual_no_municipio", CONTEXTO, "rede",
                                   _OUTRA_REDE_ESTADUAL),
    "estado_rede_estadual": ("uf_rede_estadual", CONTEXTO, "uf", _OUTRA_REDE_ESTADUAL),
}

class _SARESP(_Indicador):
    chave = "saresp"
    unidade = "pontos"
    escala = "escala_saresp"
    abrangencias = ("rede", "escola")
    por_escola = True
    etapas = ("5_ano", "2_ano")
    componentes = ("lp", "mt")

    def codigo_ausente(self, L):
        return "codigo_ibge" in L.saresp["pendencias"]

    def avisos(self, L, etapa=None, comp=None, *, escola=False):
        a = consulta_saresp.AVISOS
        saida = [a["escala"], a["comparacao"], a["tps"]]
        if etapa in (None, "2_ano"):
            saida.append(a["segundo_ano_x_ica"])
        # O aviso dos níveis é o da consulta: muda quando um corte é confirmado.
        saida.append(L.saresp["niveis"]["aviso"])
        return saida

    def quebras(self, etapa):
        return [{"entre": [q["de"], q["para"]], "etapa": q["etapa"], "texto": q["motivo"]}
                for q in consulta_saresp.QUEBRAS_DE_ESCALA if etapa is None or q["etapa"] == etapa]

    def series_rede(self, L, etapa, comp):
        d = L.saresp
        por_chave = {t["chave"]: t for t in d["territorios"]}
        saida = []
        for chave_consulta, (id_, papel, abr, motivo_nc) in _SARESP_TERRITORIOS.items():
            t = por_chave.get(chave_consulta)
            numeros = []
            if t:
                s = next((s for s in t["series"] if (s["etapa"], s["componente"]) == (etapa, comp)),
                         None)
                numeros = s["numeros"] if s else []
            pontos = [ponto(n["edicao"], chave=self.chave, valor=n["valor"],
                            casas=n["casas_decimais"], motivo=n["motivo_ausencia"],
                            fonte_id=_fid(n["fonte"])) for n in numeros]
            if papel != PRINCIPAL and not pontos:
                continue
            rotulo = t["rotulo"] if t else f"{d['municipio'] or d['rede_nome']} — rede municipal"
            saida.append(serie(id_, rotulo=rotulo, papel=papel, abrangencia=abr,
                               rede_ensino=t["rede_ensino"] if t else "municipal",
                               mesma_rede=t["mesma_rede"] if t else True,
                               comparavel=motivo_nc is None,
                               motivo_nao_comparavel=motivo_nc, pontos=pontos,
                               etapa=etapa, componente=comp))
        return saida

    def linhas(self, L):
        return L.saresp["escolas"]["linhas"]

    def pontos_escola(self, L, linha, etapa, comp):
        saida = []
        for ed in sorted(linha["por_edicao"], key=lambda e: e["edicao"]):
            n = ed["proficiencia"][etapa][comp]
            part = ed["participacao"][etapa]
            tps = ed["tps"]
            if n is not None and n["valor"] is not None:
                valor, casas, motivo = n["valor"], n["casas_decimais"], None
            else:
                valor = casas = None
                motivo = (n or {}).get("motivo_ausencia") or ed["motivo"] or MOTIVO_SEM_RESULTADO
            saida.append(ponto(
                ed["edicao"], chave=self.chave, valor=valor, casas=casas, motivo=motivo,
                fonte_id=_fid((n or {}).get("fonte")),
                # TPS = 0 (critério mínimo de participação não atingido): média instável.
                instavel=bool(tps and tps["valor"] == 0),
                participacao=part["valor"] if part else None,
                participacao_casas=_casas(part)))
        return saida

    def fontes(self, L):
        return {f["importacao_id"]: f for f in L.saresp["fontes"] if f}

    def tem_estimativa(self, L):
        return bool(L.saresp["estimativas"])

    def estimativas_na_edicao(self, L, edicao, etapa, comp):
        return sum(1 for e in L.saresp["estimativas"]
                   if e["edicao"] == edicao and (e["etapa"] in (etapa, None))
                   and e["componente"] in (comp, None))



class _IEE(_SARESP):
    chave = "iee"
    unidade = "índice"
    escala = "indice_iee"
    abrangencias = ("escola",)
    etapas = ("anos_iniciais",)
    componentes = ()
    tem_meta = True

    def rotulo_destaque(self, etapa, comp):
        return "IEE"

    def avisos(self, L, etapa=None, comp=None, *, escola=False):
        return [("O IEE (Índice de Excelência Educacional, SEDUC-SP) é um índice POR ESCOLA, "
                 "calculado a partir do SARESP do 2º e do 5º ano: não é proficiência e não "
                 "existe para a rede."),
                ("Meta cumprida ou não: o ICM (Índice de Cumprimento de Meta) oficial da SEDUC "
                 "(1 = cumpriu). A diferença IEE − meta é só a conta na precisão publicada."),
                ("IEE de escola com TPS = 0 (participação abaixo do mínimo do SARESP): o índice "
                 "é o oficial, mas foi calculado com médias instáveis — ele fica fora da "
                 "relação com as plataformas.")]

    def quebras(self, etapa):
        return []

    def series_rede(self, L, etapa, comp):
        return []                      # o IEE não tem número da rede

    def pontos_escola(self, L, linha, etapa, comp):
        saida = []
        for ed in sorted(linha["por_edicao"], key=lambda e: e["edicao"]):
            iee, meta, icm = ed["iee"], ed["meta"], ed["icm"]
            if iee is not None and iee["valor"] is not None:
                valor, casas, motivo = iee["valor"], iee["casas_decimais"], None
            else:
                valor = casas = None
                motivo = (iee or {}).get("motivo_ausencia") or ed["motivo"] or MOTIVO_SEM_RESULTADO
            m_valor = meta["valor"] if meta else None
            dif = dif_casas = None
            if valor is not None and m_valor is not None:
                dif, dif_casas = consulta._diferenca(valor, casas or 0, m_valor,
                                                     meta["casas_decimais"] or 0)
            situacao = None
            if icm is not None and icm["valor"] is not None:
                situacao = "atingiu" if icm["valor"] == 1 else "nao_atingiu"
            saida.append(ponto(
                ed["edicao"], chave=self.chave, valor=valor, casas=casas, motivo=motivo,
                fonte_id=_fid((iee or {}).get("fonte")), meta=m_valor, meta_casas=_casas(meta),
                sem_meta=None if m_valor is not None else SEM_META_NA_EDICAO,
                fonte_meta_id=_fid((meta or {}).get("fonte")),
                diferenca=dif, diferenca_casas=dif_casas, situacao=situacao,
                icm=icm["valor"] if icm else None,
                # O IEE sai das médias do 2º e do 5º ano: com TPS = 0 elas são instáveis.
                # O número oficial NÃO é marcado instável (seria regra nova sobre ele); a
                # relação o exclui pelo motivo próprio.
                tps_zero=bool(ed["tps"] and ed["tps"]["valor"] == 0)))
        return saida

    def tem_estimativa(self, L):
        return False

    def estimativas_na_edicao(self, L, edicao, etapa, comp):
        return 0


# --- Ideb e Saeb (a mesma leitura: consulta_ideb + consulta_ideb_rede) ---------------

_IDEB_TERRITORIOS = {
    "rede_municipal": ("rede_municipal", PRINCIPAL, "rede"),
    "uf_redes_municipais": ("uf_redes_municipais", REFERENCIA, "uf"),
    "uf_rede_publica": ("uf_rede_publica", CONTEXTO, "uf"),
    "brasil_redes_municipais": ("brasil_redes_municipais", REFERENCIA, "brasil"),
}
_CAMPO_SAEB = {"lp": "saeb_lp", "mt": "saeb_mt"}


def _numero_ideb(numero: dict | None, motivo_padrao: str | None) -> dict:
    """Os campos de ``ponto`` para um número de ``consulta_ideb``, como a consulta o
    mostra: o oficial com a fonte; o gravado antes, sem o registro do arquivo oficial, com
    o valor e ``proveniencia = "sem_registro"`` (e ``difere`` quando uma importação oficial
    recusou trocá-lo pelo número do arquivo); sem número, a ausência com o motivo."""
    sem_registro = (numero is not None
                    and numero.get("proveniencia") == PROVENIENCIA_SEM_REGISTRO)
    if numero is not None and numero["valor"] is not None:
        return {"valor": numero["valor"], "casas": numero["casas_decimais"], "motivo": None,
                "fonte_id": None if sem_registro else numero.get("fonte_id"),
                "proveniencia": (PROVENIENCIA_SEM_REGISTRO if sem_registro
                                 else PROVENIENCIA_OFICIAL),
                "difere": bool(sem_registro and numero.get("difere_do_oficial"))}
    if sem_registro:
        return {"valor": None, "casas": None, "motivo": MOTIVO_SEM_REGISTRO, "fonte_id": None}
    motivo = (numero or {}).get("motivo_ausencia") or motivo_padrao or MOTIVO_SEM_RESULTADO
    return {"valor": None, "casas": None, "motivo": motivo,
            "fonte_id": (numero or {}).get("fonte_id")}


class _Ideb(_Indicador):
    chave = "ideb"
    unidade = "índice"
    escala = "indice_ideb"
    abrangencias = ("rede", "escola")
    por_escola = True
    etapas = ("anos_iniciais",)
    componentes = ()
    tem_meta = True

    def codigo_ausente(self, L):
        return "codigo_ibge" in L.ideb["pendencias"]

    def rotulo_destaque(self, etapa, comp):
        return "Ideb da rede (anos iniciais)"

    def _aviso_sem_registro(self, L) -> list[str]:
        return ([L.ideb["avisos"]["sem_registro"]] if L.ideb["sem_registro_oficial"]["total"]
                else [])

    def avisos(self, L, etapa=None, comp=None, *, escola=False):
        # Os textos da consulta oficial (o período da comparabilidade é o das edições reais).
        a = L.ideb["avisos"]
        return [a["comparabilidade"], a["pandemia"], a["metas"], a["precisao"],
                *self._aviso_sem_registro(L)]

    def series_rede(self, L, etapa, comp):
        saida = []
        for t in L.ideb["rede_municipal"]["ideb"]["territorios"]:
            id_, papel, abr = _IDEB_TERRITORIOS.get(
                t["chave"], (t["chave"], CONTEXTO, t["abrangencia"]))
            pontos = []
            for e in t["serie"]:
                n = _numero_ideb(e["ideb"], None)
                meta, c = e["meta"], e["comparacao_meta"]
                pontos.append(ponto(
                    e["edicao"], chave=self.chave, **n,
                    meta=meta["valor"] if meta else None, meta_casas=_casas(meta),
                    sem_meta=e["sem_meta"], fonte_meta_id=(meta or {}).get("fonte_id"),
                    diferenca=c["diferenca"] if c else None,
                    diferenca_casas=c["casas_decimais"] if c else None,
                    situacao=c["situacao"] if c else None))
            if papel != PRINCIPAL and not pontos:
                continue
            comparavel = bool(t["mesma_rede"])
            saida.append(serie(id_, rotulo=t["rotulo"], papel=papel, abrangencia=abr,
                               rede_ensino=t["rede_ensino"], mesma_rede=bool(t["mesma_rede"]),
                               comparavel=comparavel,
                               motivo_nao_comparavel=(t.get("motivo_contexto")
                                                      or _OUTRA_REDE_PUBLICA),
                               pontos=pontos, etapa="anos_iniciais"))
        if not any(s["papel"] == PRINCIPAL for s in saida):
            saida.insert(0, serie("rede_municipal", rotulo="Rede municipal", papel=PRINCIPAL,
                                  abrangencia="rede", rede_ensino="municipal", mesma_rede=True,
                                  comparavel=True, pontos=[], etapa="anos_iniciais"))
        return saida

    def linhas(self, L):
        return L.ideb["escolas"]

    def pontos_escola(self, L, linha, etapa, comp):
        saida = []
        for ed in linha["serie"]:
            n = _numero_ideb(ed["ideb"], ed["motivo"])
            meta = ed["meta"]
            # A comparação com a meta é a da consulta oficial (que também a faz com o número
            # sem registro — marcado no ponto).
            c = ed["comparacao_meta"] if n["valor"] is not None else None
            saida.append(ponto(
                ed["edicao"], chave=self.chave, **n,
                meta=meta["valor"] if meta else None, meta_casas=_casas(meta),
                sem_meta=ed["sem_meta"], fonte_meta_id=(meta or {}).get("fonte_id"),
                diferenca=c["diferenca"] if c else None,
                diferenca_casas=c["casas_decimais"] if c else None,
                situacao=c["situacao"] if c else None))
        return saida

    def fontes(self, L):
        return {f["importacao_id"]: f for f in L.ideb["fontes"] if f}

    def _campo(self, comp):
        return "ideb"

    def tem_estimativa(self, L):
        return False                  # o Ideb e o Saeb não têm Estimativa Constela

    @staticmethod
    def _sem_registro(ed, campo) -> bool:
        n = ed[campo]
        return bool(n and n["proveniencia"] == PROVENIENCIA_SEM_REGISTRO
                    and n["valor"] is not None)

    def tem_sem_registro(self, L):
        return any(self._sem_registro(ed, self._campo(c))
                   for linha in L.ideb["escolas"] for ed in linha["serie"]
                   for c in (self.componentes or (None,)))

    def sem_registro_na_edicao(self, L, edicao, etapa, comp):
        campo = self._campo(comp)
        return sum(1 for linha in L.ideb["escolas"] for ed in linha["serie"]
                   if ed["edicao"] == edicao and self._sem_registro(ed, campo))



class _Saeb(_Ideb):
    chave = "saeb"
    unidade = "pontos"
    escala = "escala_saeb"
    etapas = ("5_ano",)
    componentes = ("lp", "mt")
    tem_meta = False

    def rotulo_destaque(self, etapa, comp):
        return f"Saeb da rede — 5º ano, {ROTULO_COMPONENTE[comp]}"

    def avisos(self, L, etapa=None, comp=None, *, escola=False):
        a = consulta_ideb_rede.AVISOS
        origem = ("A nota do Saeb da escola é a média dela, do arquivo do Ideb por escola; a "
                  "da rede vem da planilha de resultados do INEP (localização Total)."
                  if escola else
                  "O Saeb POR ESCOLA vem do arquivo do Ideb por escola; o da REDE, da planilha "
                  "de resultados do INEP (localização Total).")
        return [L.ideb["avisos"]["escala"], a["saeb_planilha"], a["amostral"], origem,
                *self._aviso_sem_registro(L)]

    def _campo(self, comp):
        return _CAMPO_SAEB[comp]

    def series_rede(self, L, etapa, comp):
        saida = []
        for t in L.ideb["rede_municipal"]["saeb"]["territorios"]:
            id_, papel, abr = _IDEB_TERRITORIOS.get(
                t["chave"], (t["chave"], REFERENCIA, t["abrangencia"]))
            pontos = []
            for e in t["edicoes"]:
                pontos.append(ponto(e["edicao"], chave=self.chave,
                                    **_numero_ideb(e["media"].get(comp), None)))
            if papel != PRINCIPAL and not pontos:
                continue
            saida.append(serie(id_, rotulo=t["rotulo"], papel=papel, abrangencia=abr,
                               rede_ensino=t["rede_ensino"], mesma_rede=True, comparavel=True,
                               pontos=pontos, etapa="5_ano", componente=comp,
                               localizacao=t.get("localizacao")))
        if not any(s["papel"] == PRINCIPAL for s in saida):
            saida.insert(0, serie("rede_municipal", rotulo="Rede municipal", papel=PRINCIPAL,
                                  abrangencia="rede", rede_ensino="municipal", mesma_rede=True,
                                  comparavel=True, pontos=[], etapa="5_ano", componente=comp))
        return saida

    def pontos_escola(self, L, linha, etapa, comp):
        campo = self._campo(comp)
        saida = []
        for ed in linha["serie"]:
            motivo_padrao = None if ed["tem_ideb"] else ed["motivo"]
            saida.append(ponto(ed["edicao"], chave=self.chave,
                               **_numero_ideb(ed[campo], motivo_padrao)))
        return saida


INDICADORES: dict[str, _Indicador] = {i.chave: i for i in (_ICA(), _SARESP(), _IEE(), _Ideb(),
                                                            _Saeb())}
ORDEM = ("ica", "saresp", "iee", "ideb", "saeb")
# Chaves de séries que só existem como estimativa (nunca indicador oficial).
CHAVES_ESTIMATIVA = frozenset(_EXIBICAO)
# A "Estimativa Constela": as séries de ``_EXIBICAO`` e as médias do SARESP por escola sem
# importação oficial (calculadas pelo Constela). O Ideb e o Saeb sem registro NÃO são
# estimativa: são números gravados antes, sem o registro do arquivo (``sem_registro``).
_ESTIMATIVA_SARESP = ("SARESP — Estimativa Constela: médias por escola calculadas pelo "
                      "Constela (não são o indicador oficial)")


def indicador(chave: str) -> _Indicador:
    ind = INDICADORES.get(chave)
    if ind is None:
        raise AnaliseInvalida(
            f"Indicador “{chave}” não existe. Os oficiais são: {', '.join(ORDEM)}.", 404)
    return ind


# --- Estimativas e escolas ---------------------------------------------------------------

def estimativas(db: Session, rede: Rede) -> list[dict]:
    """A "Estimativa Constela" por escola (``crianca_alfabetizada`` e as médias do SARESP
    calculadas pelo Constela): só a lista — o nome deixa claro que não é o indicador
    oficial, e nenhuma delas entra numa série oficial nem na relação. O Ideb e o Saeb sem
    registro do arquivo NÃO estão aqui (``sem_registro_oficial``)."""
    if leituras.ativa(db):                       # as escolas já lidas nesta requisição
        ids = [e.id for e in leituras.escolas_da_rede(db, rede.id)]
    else:
        ids = [eid for (eid,) in db.execute(select(Escola.id).where(Escola.rede_id == rede.id))]
    if not ids:
        return []
    chaves = sorted(set(_EXIBICAO) | {"saresp"})
    linhas = db.execute(
        select(AvaliacaoExterna.chave, AvaliacaoExterna.nome, ResultadoAvaliacao.edicao,
               func.count(func.distinct(ResultadoAvaliacao.escola_id)))
        .join(ResultadoAvaliacao, ResultadoAvaliacao.avaliacao_id == AvaliacaoExterna.id)
        .where(ResultadoAvaliacao.escola_id.in_(ids),
               AvaliacaoExterna.chave.in_(chaves),
               ResultadoAvaliacao.importacao_id.is_(None),
               ResultadoAvaliacao.valor.isnot(None))
        .group_by(AvaliacaoExterna.chave, AvaliacaoExterna.nome, ResultadoAvaliacao.edicao)
    ).all()
    por_chave: dict[str, dict] = {}
    for chave, nome, edicao, escolas in linhas:
        rotulo = nome_exibicao(chave, nome) if chave in _EXIBICAO else _ESTIMATIVA_SARESP
        item = por_chave.setdefault(chave, {"chave": chave, "nome": rotulo,
                                            "tipo": "estimativa_constela",
                                            "oficial": False, "edicoes": set(), "escolas": 0})
        item["edicoes"].add(edicao)
        item["escolas"] = max(item["escolas"], int(escolas))
    return [{**v, "edicoes": sorted(v["edicoes"])}
            for _, v in sorted(por_chave.items())]


def sem_registro_oficial(L: Leituras) -> list[dict]:
    """O Ideb e o Saeb por escola gravados ANTES, sem o registro do arquivo oficial (os
    números que a consulta oficial marca ``sem_registro``): quantas escolas por edição e
    quantos números diferem do arquivo. Eles aparecem nas séries, marcados, e nunca nos
    destaques nem na relação — e não são estimativa."""
    saida = []
    for chave in ("ideb", "saeb"):
        ind = INDICADORES[chave]
        por_edicao: dict[int, set[int]] = {}
        numeros = difere = 0
        for linha in ind.linhas(L):
            for etapa, comp in ind.combos():
                for p in ind.pontos_escola(L, linha, etapa, comp):
                    if e_sem_registro(p):
                        por_edicao.setdefault(p["edicao"], set()).add(linha["escola_id"])
                        numeros += 1
                        difere += int(p["difere_do_oficial"])
        if por_edicao:
            saida.append({
                "chave": chave,
                "nome": f"{ind.nome} — números gravados antes, sem o registro do arquivo oficial",
                "tipo": PROVENIENCIA_SEM_REGISTRO, "oficial": False,
                "edicoes": sorted(por_edicao),
                "escolas_por_edicao": {str(ed): len(ids) for ed, ids in sorted(por_edicao.items())},
                "numeros": numeros, "difere_do_oficial": difere,
                "texto": (f"{TEXTO_SEM_REGISTRO[0].upper()}{TEXTO_SEM_REGISTRO[1:]}: aparece "
                          "marcado nas séries e na visão por escolas e não entra nos destaques "
                          "nem na relação com as plataformas."),
            })
    return saida


def escolas_da_rede(db: Session, rede: Rede) -> list[Escola]:
    # Dentro de ``leituras_da_requisicao`` (o catálogo, um indicador, a análise da escola), as
    # escolas que o SARESP e o Ideb também leem: uma leitura só na requisição.
    lidas = (leituras.escolas_da_rede(db, rede.id) if leituras.ativa(db)
             else db.execute(select(Escola).where(Escola.rede_id == rede.id)).scalars())
    return sorted(lidas, key=lambda e: ordem_nome(e.nome, e.id))


def resumo_escola(e: Escola) -> dict:
    inep = normalizar_inep(e.codigo_inep)
    return {"id": e.id, "nome": e.nome, "codigo_inep": inep, "status": e.status,
            "pendencia": None if inep else "sem_codigo_inep"}


# --- Endpoint 1: catálogo ---------------------------------------------------------------

def _alertas(L: Leituras, itens: list[dict], escolas: list[dict], ano_plataformas: int | None
             ) -> list[dict]:
    saida = []
    if codigo_ibge_da_rede(L.rede) is None:
        saida.append({"tipo": "cadastro", "indicador": None, "escolas": [],
                      "texto": ("A rede não tem o código IBGE do município cadastrado: os "
                                "números da rede (ICA, SARESP, Ideb e Saeb) não podem ser "
                                "recortados. Quem cadastra é o administrador global.")})
    if not (L.rede.codigo_municipio_estadual or "").strip():
        saida.append({"tipo": "cadastro", "indicador": "saresp", "escolas": [],
                      "texto": ("A rede não tem o código do município na SEDUC (CODMUN): o "
                                "SARESP da rede por município não pode ser recortado.")})
    sem_inep = [e["id"] for e in escolas if e["pendencia"] == "sem_codigo_inep"]
    if sem_inep:
        saida.append({"tipo": "cadastro", "indicador": None, "escolas": sem_inep,
                      "texto": (f"{len(sem_inep)} escola(s) sem código INEP no cadastro: os "
                                "números oficiais dessas escolas não podem ser casados.")})
    for item in itens:
        if not item["disponivel"]:
            saida.append({"tipo": "ausente", "indicador": item["chave"], "escolas": [],
                          "texto": f"{item['nome']}: {item['texto_indisponivel']}."})
            continue
        ind = INDICADORES[item["chave"]]
        if not ind.por_escola or item["edicao_mais_recente"] is None:
            continue
        edicao = item["edicao_mais_recente"]
        linhas = ind.linhas(L)
        sem, sem_registro, difere = [], [], 0
        for linha in linhas:
            pontos = [pt for etapa, comp in ind.combos()
                      for pt in ind.pontos_escola(L, linha, etapa, comp)
                      if pt["edicao"] == edicao]
            if any(e_oficial(pt) for pt in pontos):
                continue
            marcados = [pt for pt in pontos if e_sem_registro(pt)]
            if marcados:
                sem_registro.append(linha["escola_id"])
                difere += sum(1 for pt in marcados if pt["difere_do_oficial"])
            else:
                sem.append(linha["escola_id"])
        if sem:
            saida.append({"tipo": "insuficiente", "indicador": item["chave"], "escolas": sem,
                          "texto": (f"{item['nome']} {edicao}: {len(sem)} de {len(linhas)} "
                                    "escola(s) sem resultado oficial — o motivo de cada uma "
                                    "está na visão por escolas (sem resultado não é zero).")})
        if sem_registro:
            # Não é "sem resultado": o número existe, só falta o registro do arquivo oficial.
            saida.append({"tipo": "sem_registro", "indicador": item["chave"],
                          "escolas": sem_registro,
                          "texto": (f"{item['nome']} {edicao}: {len(sem_registro)} de "
                                    f"{len(linhas)} escola(s) com {TEXTO_SEM_REGISTRO} — o "
                                    "número aparece marcado e não entra nos destaques nem na "
                                    "relação"
                                    + (f" ({difere} {'difere' if difere == 1 else 'diferem'} do "
                                       "arquivo oficial)" if difere else "") + ".")})
    for p in L.ideb["pendentes"]:
        if p["situacao"] != consulta_ideb_rede.SITUACAO_SEM_IMPORTACAO:
            continue
        # Texto próprio, sem o nome do arquivo: a fonte documental fica em "Detalhes e
        # fontes" e na área de importação (/rede/avaliacoes).
        if p["chave"].startswith("ideb_escolas"):
            texto = (f"Ideb e Saeb {p['edicao']} por escola: o resultado por escola ainda não "
                     "foi importado para esta rede.")
        elif p["chave"] == "ideb_municipio":
            texto = ("Ideb da rede municipal: o resultado oficial da rede ainda não foi "
                     "importado.")
        else:
            continue
        saida.append({"tipo": "desatualizado", "indicador": "ideb", "escolas": [],
                      "texto": texto})
    edicoes_escola = [ed for item in itens if item["disponivel"] and item["por_escola"]
                      for ed in item["edicoes"]]
    if ano_plataformas is not None and ano_plataformas not in edicoes_escola:
        ultima = max(edicoes_escola) if edicoes_escola else None
        texto = (f"As plataformas (Elefante e Matific) têm dados do ano letivo {ano_plataformas}"
                 + (f"; as avaliações oficiais por escola vão até {ultima}" if ultima else
                    "; não há avaliação oficial por escola importada")
                 + ". A relação entre as duas só é calculada no MESMO ano letivo — por enquanto "
                   "elas aparecem só lado a lado.")
        saida.append({"tipo": "metodologia", "indicador": None, "escolas": [], "texto": texto})
    return saida


def ano_letivo_de_referencia(escolas: list[Escola]) -> int | None:
    """O ano letivo ativo mais comum entre as escolas da rede (no empate, o mais novo)."""
    anos: dict[int, int] = {}
    for e in escolas:
        anos[e.ano_letivo_ativo] = anos.get(e.ano_letivo_ativo, 0) + 1
    return max(anos, key=lambda a: (anos[a], a)) if anos else None


def catalogo(db: Session, rede: Rede) -> dict:
    L = Leituras(db, rede)
    escolas_modelo = escolas_da_rede(db, rede)
    escolas = [resumo_escola(e) for e in escolas_modelo]
    itens = [INDICADORES[ch].item(L) for ch in ORDEM]
    destaques = [d for ch in ORDEM if (d := INDICADORES[ch].destaque(L))]
    fontes_todas: dict[int, dict] = {}
    for ch in ORDEM:
        fontes_todas.update(INDICADORES[ch].fontes(L))
    return {
        "rede": {"id": rede.id, "nome": rede.nome, "codigo_ibge": codigo_ibge_da_rede(rede),
                 "codigo_municipio_estadual": rede.codigo_municipio_estadual or None,
                 "municipio": L.saresp["municipio"] or L.ideb["municipio"]},
        "indicadores": itens,
        "destaques": destaques,
        "estimativas": estimativas(db, rede),
        "sem_registro_oficial": sem_registro_oficial(L),
        "escolas": escolas,
        "alertas": _alertas(L, itens, escolas, ano_letivo_de_referencia(escolas_modelo)),
        "metodologia_resumo": list(METODOLOGIA_RESUMO),
        "fontes": {str(d["fonte_id"]): fontes_todas[d["fonte_id"]] for d in destaques
                   if d["fonte_id"] in fontes_todas},
    }


# --- Endpoint 2: um indicador -------------------------------------------------------------

def validar_filtros(ind: _Indicador, etapa: str | None, componente: str | None
                    ) -> tuple[str, str | None]:
    etapa = etapa or ind.etapas[0]
    if etapa not in ind.etapas:
        raise AnaliseInvalida(
            f"O {ind.nome} não tem a etapa “{etapa}”. As etapas dele: "
            f"{', '.join(ind.etapas)}.")
    if ind.componentes:
        componente = componente or ind.componentes[0]
        if componente not in ind.componentes:
            raise AnaliseInvalida(
                f"O {ind.nome} não tem o componente “{componente}”. Os componentes dele: "
                f"{', '.join(ind.componentes)}.")
    elif componente:
        raise AnaliseInvalida(f"O {ind.nome} não tem componente (é um índice só).")
    return etapa, componente


def _ids_de_fonte(pontos: list[dict]) -> set[int]:
    return {i for p in pontos for i in (p.get("fonte_id"), p.get("fonte_meta_id"),
                                        p.get("fonte_detalhe_id")) if i is not None}


def _no_intervalo(p: dict, de: int | None, ate: int | None) -> bool:
    return (de is None or p["edicao"] >= de) and (ate is None or p["edicao"] <= ate)


def serie_da_escola(ind: _Indicador, L: Leituras, linha: dict | None, escola: dict,
                    etapa: str, comp: str | None) -> dict:
    pontos = ind.pontos_escola(L, linha, etapa, comp) if linha else []
    return serie(f"escola_{escola['escola_id']}", rotulo=escola["nome"], papel=PRINCIPAL,
                 abrangencia="escola", rede_ensino="municipal", mesma_rede=True,
                 comparavel=True, pontos=pontos, escola_id=escola["escola_id"],
                 etapa=etapa, componente=comp)


def detalhe(db: Session, rede: Rede, chave: str, *, etapa: str | None = None,
            componente: str | None = None, escola_id: int | None = None,
            de: int | None = None, ate: int | None = None, visao: str = "serie",
            edicao: int | None = None) -> dict:
    ind = indicador(chave)
    etapa, componente = validar_filtros(ind, etapa, componente)
    visao = visao or "serie"
    if visao not in VISOES:
        raise AnaliseInvalida(f"Visão “{visao}” não existe. Use: {', '.join(VISOES)}.")
    if de is not None and ate is not None and de > ate:
        raise AnaliseInvalida(f"O ano inicial ({de}) é posterior ao final ({ate}).")
    if not ind.por_escola and (escola_id is not None or visao == "escolas"):
        raise AnaliseInvalida(
            "O ICA não existe por escola: o INEP publica o ICA só da rede municipal. Ele "
            "não serve para comparar nem ordenar escolas.")
    if visao == "escolas" and edicao is None:
        raise AnaliseInvalida("A visão por escolas exige a edição (ex.: edicao=2025).")
    escolas_rede = {e.id: e for e in escolas_da_rede(db, rede)}
    if escola_id is not None and escola_id not in escolas_rede:
        raise AnaliseInvalida("Escola não encontrada nesta rede.", 404)

    L = Leituras(db, rede)
    linhas = ind.linhas(L)
    linha_de = {ln["escola_id"]: ln for ln in linhas}
    series: list[dict] = []
    escolas_saida: list[dict] = []
    if visao == "serie":
        da_rede = ind.series_rede(L, etapa, componente)
        if escola_id is not None:
            e = escolas_rede[escola_id]
            info = escola_da_linha(linha_de[escola_id]) if escola_id in linha_de else {
                "escola_id": e.id, "nome": e.nome}
            series.append(serie_da_escola(ind, L, linha_de.get(escola_id), info, etapa, componente))
            for s in da_rede:
                if s["papel"] == PRINCIPAL:
                    s["papel"] = REFERENCIA
        series.extend(da_rede)
        for s in series:
            s["pontos"] = [p for p in s["pontos"] if _no_intervalo(p, de, ate)]
        series = [s for s in series if s["papel"] == PRINCIPAL or s["pontos"]]
    else:
        for linha in linhas:
            pts = {p["edicao"]: p for p in ind.pontos_escola(L, linha, etapa, componente)}
            p = pts.get(edicao) or ponto(edicao, chave=ind.chave, motivo="sem_importacao")
            escolas_saida.append({**escola_da_linha(linha), **p})

    pontos_vistos = [p for s in series for p in s["pontos"]] + escolas_saida
    mapa_fontes = ind.fontes(L)
    edicoes_combo = set()
    principal = ind._principal(L, etapa, componente)
    edicoes_combo |= {p["edicao"] for p in (principal["pontos"] if principal else [])}
    opcoes_escolas = []
    for linha in linhas:
        pts = ind.pontos_escola(L, linha, etapa, componente)
        edicoes_combo |= {p["edicao"] for p in pts}
        opcoes_escolas.append({"id": linha["escola_id"], "nome": linha["nome"],
                               "codigo_inep": linha.get("codigo_inep"),
                               "tem_dado": any(p["valor"] is not None for p in pts)})
    avisos = list(ind.avisos(L, etapa, componente, escola=escola_id is not None))
    if visao == "escolas":
        avisos.append(consulta_saresp.AVISOS["sem_ranking"])
    if ind.chave == "iee" and visao == "serie" and escola_id is None:
        avisos.append("O IEE é por escola: escolha uma escola ou use a visão por escolas.")
    return {
        "indicador": ind.item(L),
        "filtros": {"etapa": etapa, "componente": componente, "escola_id": escola_id,
                    "de": de, "ate": ate, "visao": visao, "edicao": edicao},
        "opcoes": {"etapas": list(ind.etapas), "componentes": list(ind.componentes),
                   "edicoes": sorted(edicoes_combo), "escolas": opcoes_escolas},
        "series": series,
        "escolas": escolas_saida,
        "quebras": ind.quebras(etapa),
        "avisos": avisos,
        "fontes": {str(i): mapa_fontes[i] for i in sorted(_ids_de_fonte(pontos_vistos))
                   if i in mapa_fontes},
    }


# --- Usado pela relação e pela visão da escola --------------------------------------------

def valores_por_escola(L: Leituras, ind: _Indicador, etapa: str, comp: str | None,
                       edicao: int) -> list[dict]:
    """O ponto OFICIAL de cada escola da rede numa edição (ou a ausência, com o motivo), em
    ordem de nome."""
    saida = []
    for linha in ind.linhas(L):
        pts = {p["edicao"]: p for p in ind.pontos_escola(L, linha, etapa, comp)}
        saida.append({**escola_da_linha(linha),
                      "ponto": pts.get(edicao) or ponto(edicao, chave=ind.chave,
                                                        motivo="sem_importacao")})
    return saida


def indicadores_da_escola(L: Leituras, escola: Escola) -> tuple[list[dict], dict[str, dict]]:
    """Para a visão de UMA escola: as séries dela em cada indicador por escola (todas as
    etapas × componentes), a REDE MUNICIPAL como referência (só ela — nenhuma outra escola)
    e o ICA só como referência da rede. Devolve (itens, fontes usadas)."""
    itens, ids, fontes = [], set(), {}
    for chave in ORDEM:
        ind = INDICADORES[chave]
        linha = next((ln for ln in ind.linhas(L) if ln["escola_id"] == escola.id), None)
        info = escola_da_linha(linha) if linha else {"escola_id": escola.id, "nome": escola.nome}
        series = []
        for etapa, comp in ind.combos():
            if ind.por_escola:
                series.append(serie_da_escola(ind, L, linha, info, etapa, comp))
            for s in ind.series_rede(L, etapa, comp):
                if s["id"] != "rede_municipal":
                    continue                        # só a rede da escola, como referência
                s["papel"] = REFERENCIA
                if s["pontos"]:
                    series.append(s)
        pontos = [p for s in series for p in s["pontos"]]
        ids |= _ids_de_fonte(pontos)
        fontes.update(ind.fontes(L))
        # Há número para mostrar (oficial ou o gravado antes, marcado).
        disponivel = any(p["valor"] is not None for p in pontos)
        itens.append({"chave": chave, "nome": ind.nome, "orgao": ind.orgao,
                      "por_escola": ind.por_escola, "unidade": ind.unidade,
                      "disponivel": disponivel, "series": series,
                      "quebras": ind.quebras(None), "avisos": ind.avisos(L, escola=True)})
    return itens, {str(i): fontes[i] for i in sorted(ids) if i in fontes}
