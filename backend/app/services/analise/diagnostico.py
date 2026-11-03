"""Diagnóstico pedagógico EXPLORATÓRIO por escola (``GET /redes/{id}/analise/diagnostico``)
— só leitura, nada é gravado.

O QUE É: para CADA escola da rede (em ordem alfabética — nunca ranking), junta o que a
análise já mede em dois lugares e diz, com regras escritas e rastreáveis, onde as duas
fontes apontam para o mesmo lado e onde divergem:

* as avaliações OFICIAIS da escola (IEE, Ideb, SARESP do 2º e do 5º ano, Saeb do 5º ano) —
  a última edição com número oficial de cada série, contra a REDE MUNICIPAL na mesma
  edição e contra a edição oficial anterior da mesma série;
* o uso das plataformas (Elefante → Língua Portuguesa; Matific → Matemática) no período
  pedido, contra a soma da REDE na mesma janela.

COMO (sem regra nova de leitura): os números oficiais saem de
``indicadores.indicadores_da_escola`` (as séries da escola e a rede municipal como
referência, já com a proveniência, as metas oficiais, o "instável" e as quebras) e as
plataformas de ``plataformas.plataformas_da_rede`` (a janela, a cobertura e a supressão
k = 5 da rota de plataformas — a MESMA decisão, então nenhuma escola pequena reaparece
aqui). Este módulo não relê tabela oficial nem mede plataforma: só COMBINA as saídas e
aplica as regras abaixo (``docs/analise/METODOLOGIA.md``, seção 7).

AS REGRAS (todas declaradas na resposta, em ``criterios``):

* "na média" = diferença MENOR que a tolerância (participação 5 p.p.; intensidade 15% do
  valor da rede; Ideb 0,2; IEE 0,2 — só tendência, o IEE não existe para a rede; SARESP e
  Saeb 5 pontos). A diferença é a das casas PUBLICADAS (a conta do ICA), então a
  tolerância é comparada com o número que a tela mostra;
* média instável (TPS = 0) — e o IEE calculado com ela — nunca gera sinal de posição nem
  de tendência (aparece como sinal de DADOS);
* a tendência nunca atravessa uma quebra de escala declarada pela consulta oficial (o
  2º ano do SARESP em 2022→2023 e 2025→2026);
* a posição de plataforma só existe com a cobertura da escola em dia e com pelo menos
  ``N_MINIMO_ESCOLAS`` escolas da rede com a métrica (abaixo disso a "rede" é quase a
  própria escola);
* a estimativa e o número sem registro do arquivo oficial nunca entram em ``oficiais``:
  viram sinal de dados;
* "mesmo ano" só quando todos os sinais com direção da avaliação são do ano letivo das
  plataformas, com todas as escolas nele e o período dentro dele; senão, exploratória.

POR QUE "EXPLORATÓRIO": hoje as avaliações oficiais são de outra edição (e de outra coorte
de crianças) que o uso das plataformas. A leitura diz isso em ``comparabilidade``; mesmo no
mesmo ano letivo, é associação, nunca causa e efeito — e nada de dispersão: anos diferentes
fariam uma relação inválida (a relação estatística, com os critérios dela, é a de
``relacao``).

Nenhuma resposta traz ``aluno_id``, nome de aluno ou turma; o k é o da análise.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.orm import Session

from app.core.tempo import agora_br
from app.models import Escola, Rede
from app.services.analise import K_MINIMO, validar_anos
from app.services.analise import indicadores as ind_svc
from app.services.analise import plataformas as plat_svc
from app.services.avaliacoes import normalizar_inep
from app.services.indicadores import consulta
from app.services.indicadores.ica import arredondar

# --- Critérios ------------------------------------------------------------------------

# As séries oficiais do diagnóstico, na ordem FIXA da tabela: (indicador, etapa, componente).
# O ICA fica de fora: ele não existe por escola.
SERIES_OFICIAIS = (
    ("iee", "anos_iniciais", None),
    ("ideb", "anos_iniciais", None),
    ("saresp", "5_ano", "lp"), ("saresp", "5_ano", "mt"),
    ("saresp", "2_ano", "lp"), ("saresp", "2_ano", "mt"),
    ("saeb", "5_ano", "lp"), ("saeb", "5_ano", "mt"),
)
NOME_CURTO = {"iee": "IEE", "ideb": "Ideb", "saresp": "SARESP", "saeb": "Saeb"}
ETAPA_CURTA = {"2_ano": "2º ano", "5_ano": "5º ano", "anos_iniciais": "anos iniciais"}
COMPONENTE_CURTO = {"lp": "LP", "mt": "MT"}
AREA = {"lp": "Língua Portuguesa", "mt": "Matemática"}
UNIDADE_TEXTO = {"saresp": " pontos", "saeb": " pontos", "ideb": "", "iee": ""}

# "Na média" = diferença MENOR que isto (na precisão publicada).
TOLERANCIAS = {"ideb": 0.2, "iee": 0.2, "saresp": 5.0, "saeb": 5.0}
TOLERANCIA_PARTICIPACAO_PP = 5.0
TOLERANCIA_INTENSIDADE_PCT = 15.0
# Posição de plataforma só com pelo menos isto de escolas da rede com a métrica.
N_MINIMO_ESCOLAS = 3
# O IEE não existe para a rede: só tendência e meta. O Ideb, o SARESP e o Saeb têm a rede
# municipal como referência comparável.
COM_POSICAO = ("ideb", "saresp", "saeb")
COM_META = ("iee", "ideb")

PLATAFORMAS = {
    "elefante": {"nome": "Elefante", "componente": "lp", "intensidade": "livros_por_aluno",
                 "rotulo_intensidade": "livros novos por aluno",
                 "metricas": ("participacao_pct", "livros_por_aluno", "minutos_por_aluno",
                              "taxa_acerto_pct")},
    "matific": {"nome": "Matific", "componente": "mt", "intensidade": "atividades_por_aluno",
                "rotulo_intensidade": "atividades por aluno",
                "metricas": ("participacao_pct", "atividades_por_aluno", "desempenho_medio")},
}
PLATAFORMA_DO_COMPONENTE = {"lp": "elefante", "mt": "matific"}

NIVEIS = ("prioritario", "acompanhar", "oportunidade", "dados_insuficientes", "sem_sinal")
CATEGORIAS = ("convergente_favoravel", "convergente_atencao", "divergente_uso_alto",
              "divergente_uso_baixo", "inconclusiva")
# Motivo das plataformas que é a supressão k (a escola, a série ou o subconjunto pequeno).
_MOTIVOS_K = (plat_svc.POUCOS_MEDIDOS, plat_svc.SERIES_SUPRIMIDAS)

TEXTO_IEE_SEM_REDE = ("o IEE é um índice por escola: não existe número da rede para "
                      "comparar (só a meta oficial e a tendência)")
TEXTO_INSTAVEL = ("média instável (TPS = 0: participação abaixo do mínimo do SARESP): não se "
                  "compara com a rede nem com a edição anterior")
TEXTO_IEE_TPS_ZERO = ("IEE calculado com médias de TPS = 0 (participação abaixo do mínimo): não "
                      "gera sinal de tendência")
# Só a edição ANTERIOR é instável: a atual é estável e tem posição contra a rede — o motivo
# da tendência cita a anterior (os de cima diriam, ao lado da posição, que a média mostrada
# "não se compara com a rede").
TEXTO_ANTERIOR_INSTAVEL = ("a edição anterior ({edicao}) tem média instável (TPS = 0: "
                           "participação abaixo do mínimo do SARESP): não se traça tendência")
TEXTO_IEE_ANTERIOR_TPS_ZERO = ("o IEE da edição anterior ({edicao}) foi calculado com médias de "
                               "TPS = 0 (participação abaixo do mínimo): não gera sinal de "
                               "tendência")
TEXTO_PRIMEIRA = "primeira edição com número oficial: não há anterior para comparar"
TEXTO_EXPLORATORIA = ("Resultados oficiais de outra edição/coorte e uso das plataformas em outro "
                      "ano: leitura exploratória — não mede a mesma população nem o mesmo "
                      "período.")
TEXTO_MESMO_ANO = ("Avaliação e plataformas do mesmo ano letivo: ainda assim é associação "
                   "entre números, nunca causa e efeito.")
TEXTO_SEM_COMPARABILIDADE = ("Falta um dos lados (avaliação ou plataforma): não há o que "
                             "comparar.")
TEXTO_AVALIACAO_SEM_DIRECAO = ("Avaliação de {ano} sem sinal favorável nem de atenção (na média "
                               "da rede ou estável): nenhuma edição decide a leitura, então não "
                               "há o que pôr ao lado das plataformas.")
TEXTO_METRICA_PROTEGIDA = ("número escondido para proteger as crianças (soma um grupo de poucos "
                           "alunos): não aparece nem se compara com a rede")

REGRAS = [
    ("Por escola, entra a ÚLTIMA edição com número oficial de cada série: IEE, Ideb (anos "
     "iniciais), SARESP do 5º e do 2º ano (LP e MT) e Saeb do 5º ano (LP e MT). A Estimativa "
     "Constela e os números gravados sem o registro do arquivo oficial não entram: aparecem "
     "como sinal de dados."),
    ("Posição contra a rede municipal (Ideb, SARESP e Saeb), na mesma edição e na precisão "
     "publicada: “na média” quando a diferença é menor que a tolerância (Ideb 0,2; SARESP e "
     "Saeb 5 pontos); acima é favorável e abaixo pede atenção. O IEE não existe para a rede: "
     "só a meta oficial e a tendência."),
    ("Tendência contra a edição oficial anterior da mesma série (IEE e Ideb 0,2; SARESP e Saeb "
     "5 pontos): subiu é favorável, caiu pede atenção, diferença menor que a tolerância é "
     "estável. Não se traça tendência através de uma quebra de escala."),
    ("Meta oficial: o IEE pelo ICM da SEDUC (1 = cumpriu) e o Ideb pela meta do INEP (só até "
     "2021). Meta cumprida é favorável; não cumprida pede atenção."),
    ("Média instável (TPS = 0) e o IEE calculado com ela nunca geram sinal de posição nem de "
     "tendência."),
    (f"Plataformas no período pedido (Elefante → Língua Portuguesa; Matific → Matemática): "
     f"participação e intensidade (livros novos por aluno no Elefante; atividades por aluno no "
     f"Matific) contra a soma da rede na mesma janela — “na média” abaixo de "
     f"{TOLERANCIA_PARTICIPACAO_PP:.0f} p.p. na participação e de "
     f"{TOLERANCIA_INTENSIDADE_PCT:.0f}% do valor da rede na intensidade. Só com a coleta da "
     f"escola em dia e com pelo menos {N_MINIMO_ESCOLAS} escolas da rede com a métrica."),
    ("Leitura por componente: o estado das avaliações sai dos sinais do componente (SARESP e "
     "Saeb de LP ou de MT); sem nenhum, dos gerais (IEE e Ideb). Favorável e favorável = "
     "convergente favorável; atenção e atenção = convergente de atenção; avaliação de atenção "
     "com uso alto = divergente (uso alto); avaliação favorável com uso baixo = divergente "
     "(uso baixo); sinais nos dois sentidos ou sem sinal = inconclusiva. “Mesmo ano” só quando "
     "todos os sinais favoráveis ou de atenção da avaliação são do ano letivo das plataformas, "
     "com todas as escolas nesse ano letivo e o período dentro dele; senão, leitura "
     "exploratória (com os anos)."),
    ("Nível de acompanhamento: prioritário (alguma leitura convergente de atenção); acompanhar "
     "(alguma divergente de uso alto, ou meta oficial do IEE ou do Ideb não atingida); "
     "oportunidade (alguma divergente de uso baixo); dados insuficientes (sem número oficial e "
     "sem plataforma medida); sem sinal (o resto)."),
]

METODOLOGIA = [
    ("Hipótese exploratória, calculada pelo Constela: não é causa e efeito. O diagnóstico "
     "aponta onde olhar primeiro — a conversa com a escola decide."),
    ("Os números oficiais são os das consultas oficiais (os mesmos das telas de indicadores); "
     "as plataformas, os da tela de uso das plataformas no mesmo período, com a mesma proteção "
     "das crianças."),
    "Sem ranking: as escolas aparecem sempre em ordem alfabética.",
    ("Ausência não é zero: sem número, o campo vem vazio com o motivo — e a falta vira sinal "
     "de dados, nunca sinal de atenção."),
    ("Cada sinal diz a natureza (oficial, calculado pelo Constela, plataforma ou dados), a "
     "direção e a referência (indicador, edição, etapa e componente; ou plataforma e "
     "período), para ser conferido até o número."),
]

LIMITACOES = [
    ("Anos diferentes: as avaliações oficiais por escola vão até edições anteriores e as "
     "plataformas são do ano letivo em curso. Mesma escola e mesma série não são as mesmas "
     "crianças (o 5º ano avaliado já saiu do Fundamental I)."),
    ("A referência das plataformas é a soma da rede na mesma janela, com a própria escola "
     "dentro; a da avaliação é a rede municipal na mesma edição."),
    ("Saeb: o da escola vem do arquivo do Ideb por escola e o da rede, da planilha de "
     "resultados do INEP (localização Total) — mesma escala e mesma rede de ensino, fontes "
     "diferentes."),
    ("Ideb e Saeb: 2021 foi a edição da pandemia, e o universo avaliado e os critérios mudaram "
     "ao longo das edições (aviso da consulta oficial, que vale para a série toda). A "
     "tendência é calculada — não há quebra de escala declarada —, mas deve ser lida com "
     "cuidado."),
    ("Coleta parcial, coleta ausente ou poucos alunos (k = 5) deixam a plataforma sem posição: "
     "sem dado não é zero."),
    ("Tolerâncias são critérios do Constela para não chamar de diferença o que é ruído de "
     "arredondamento ou de escola pequena — não são critérios oficiais."),
    "Nada disto é causa e efeito: escolas diferem em muitas coisas além do uso das plataformas.",
]


# --- Utilidades ------------------------------------------------------------------------

def _fmt(valor: float | None, casas: int | None) -> str:
    """Número para o TEXTO, em pt-BR, nas casas publicadas (a tela formata os campos)."""
    if valor is None:
        return "—"
    c = casas or 0
    return f"{arredondar(valor, c):.{c}f}".replace(".", ",")


def _data_br(iso: str | None) -> str | None:
    return date.fromisoformat(iso[:10]).strftime("%d/%m/%Y") if iso else None


def referencia_oficial(chave: str, etapa: str, componente: str | None, edicao) -> str:
    """"IEE 2025", "Ideb 2023", "SARESP 2025 · 5º ano · LP" — o caminho até o número."""
    if chave in ("iee", "ideb"):
        return f"{NOME_CURTO[chave]} {edicao}"
    partes = [f"{NOME_CURTO[chave]} {edicao}", ETAPA_CURTA[etapa]]
    if componente:
        partes.append(COMPONENTE_CURTO[componente])
    return " · ".join(partes)


def rotulo_serie(chave: str, etapa: str, componente: str | None) -> str:
    if chave in ("iee", "ideb"):
        return NOME_CURTO[chave]
    partes = [NOME_CURTO[chave], ETAPA_CURTA[etapa]]
    if componente:
        partes.append(COMPONENTE_CURTO[componente])
    return " · ".join(partes)


def posicao(diferenca: float | None, tolerancia: float, *, sim="acima", nao="abaixo",
            meio="na_media") -> str | None:
    """"na média" quando a diferença é MENOR que a tolerância (ou zero); senão o sentido.
    A diferença chega já arredondada às casas publicadas — a fronteira é exata."""
    if diferenca is None:
        return None
    if diferenca == 0 or abs(diferenca) < tolerancia:
        return meio
    return sim if diferenca > 0 else nao


def _sinal(codigo: str, eixo: str, componente: str, natureza: str, direcao: str, texto: str,
           referencia: str, *, ano: int | None = None, indicador: str | None = None,
           plataforma: str | None = None) -> dict:
    return {"codigo": codigo, "eixo": eixo, "componente": componente, "natureza": natureza,
            "direcao": direcao, "texto": texto, "referencia": referencia, "ano": ano,
            "indicador": indicador, "plataforma": plataforma}


# --- Avaliações oficiais ----------------------------------------------------------------

def _series_da_escola(itens: list[dict], chave: str, etapa: str, comp: str | None
                      ) -> tuple[dict | None, dict | None, list[dict]]:
    """(série da escola, série da rede municipal, quebras) de uma (indicador, etapa,
    componente), na saída de ``indicadores_da_escola``."""
    item = next((i for i in itens if i["chave"] == chave), None)
    if item is None:
        return None, None, []
    da_escola = da_rede = None
    for s in item["series"]:
        if (s["etapa"], s["componente"]) != (etapa, comp):
            continue
        if s["abrangencia"] == "escola":
            da_escola = s
        elif s["id"] == "rede_municipal":
            da_rede = s
    quebras = [q for q in item["quebras"] if q["etapa"] == etapa]
    return da_escola, da_rede, quebras


def _quebra_entre(quebras: list[dict], de: int, ate: int) -> dict | None:
    """A quebra de escala declarada pela consulta oficial que cai ENTRE duas edições."""
    return next((q for q in quebras if de <= q["entre"][0] and q["entre"][1] <= ate), None)


def _linha_oficial(chave: str, etapa: str, comp: str | None, da_escola: dict,
                   da_rede: dict | None, quebras: list[dict]) -> dict | None:
    """A última edição OFICIAL da série da escola, com a rede e a anterior — ou None."""
    oficiais = [p for p in da_escola["pontos"] if ind_svc.e_oficial(p)]
    if not oficiais:
        return None
    u = oficiais[-1]
    instavel = bool(u["instavel"] or u.get("tps_zero"))
    linha = {
        "indicador": chave, "rotulo": rotulo_serie(chave, etapa, comp), "etapa": etapa,
        "componente": comp, "edicao": u["edicao"], "valor": u["valor"], "casas": u["casas"],
        "meta": u["meta"], "meta_casas": u["meta_casas"], "situacao_meta": u["situacao_meta"],
        "instavel": bool(u["instavel"]), "tps_zero": bool(u.get("tps_zero")),
        "fonte_id": u["fonte_id"], "referencia": referencia_oficial(chave, etapa, comp,
                                                                    u["edicao"]),
        "valor_rede": None, "casas_rede": None, "fonte_rede_id": None, "diferenca_rede": None,
        "casas_diferenca": None, "posicao_rede": None, "motivo_sem_comparacao": None,
        "anterior": None, "tendencia": None, "diferenca_anterior": None,
        "motivo_sem_tendencia": None,
    }
    # Posição contra a rede municipal, na MESMA edição (só a série comparável).
    p_rede = None
    if da_rede is not None:
        p_rede = next((p for p in da_rede["pontos"]
                       if p["edicao"] == u["edicao"] and ind_svc.e_oficial(p)), None)
    if chave not in COM_POSICAO:
        linha["motivo_sem_comparacao"] = TEXTO_IEE_SEM_REDE
    elif instavel:
        linha["motivo_sem_comparacao"] = TEXTO_INSTAVEL
    elif da_rede is not None and not da_rede["comparavel"]:
        linha["motivo_sem_comparacao"] = da_rede["motivo_nao_comparavel"]
    elif p_rede is None:
        linha["motivo_sem_comparacao"] = (f"a rede municipal não tem resultado oficial do "
                                          f"{NOME_CURTO[chave]} em {u['edicao']}")
    else:
        dif, casas = consulta._diferenca(u["valor"], u["casas"] or 0, p_rede["valor"],
                                         p_rede["casas"] or 0)
        linha.update(valor_rede=p_rede["valor"], casas_rede=p_rede["casas"],
                     fonte_rede_id=p_rede["fonte_id"], diferenca_rede=dif + 0.0,
                     casas_diferenca=casas, posicao_rede=posicao(dif, TOLERANCIAS[chave]))
    # Tendência contra a edição oficial anterior da MESMA série, sem atravessar quebra.
    if len(oficiais) < 2:
        linha["motivo_sem_tendencia"] = TEXTO_PRIMEIRA
        return linha
    a = oficiais[-2]
    quebra = _quebra_entre(quebras, a["edicao"], u["edicao"])
    if quebra is not None:
        linha["motivo_sem_tendencia"] = quebra["texto"]
        return linha
    linha["anterior"] = {"edicao": a["edicao"], "valor": a["valor"], "casas": a["casas"],
                         "instavel": bool(a["instavel"] or a.get("tps_zero"))}
    if instavel:
        # A edição ATUAL é instável: o mesmo motivo da posição (a tela não o repete).
        linha["motivo_sem_tendencia"] = (TEXTO_IEE_TPS_ZERO if chave == "iee" else
                                         TEXTO_INSTAVEL)
        return linha
    if linha["anterior"]["instavel"]:
        # Só a ANTERIOR é instável: a posição contra a rede da atual (estável) vale e foi
        # calculada acima — o motivo cita a anterior, senão a mesma célula diria "acima da
        # rede" e "não se compara com a rede".
        linha["motivo_sem_tendencia"] = (
            TEXTO_IEE_ANTERIOR_TPS_ZERO if chave == "iee"
            else TEXTO_ANTERIOR_INSTAVEL).format(edicao=a["edicao"])
        return linha
    dif, casas = consulta._diferenca(u["valor"], u["casas"] or 0, a["valor"], a["casas"] or 0)
    linha["diferenca_anterior"] = dif + 0.0
    linha["tendencia"] = posicao(dif, TOLERANCIAS[chave], sim="subiu", nao="caiu",
                                 meio="estavel")
    return linha


def _sinais_da_linha(linha: dict) -> list[dict]:
    """Os sinais de UMA série oficial: meta (oficial), posição e tendência (calculados) e a
    média instável (dados)."""
    chave, etapa, comp = linha["indicador"], linha["etapa"], linha["componente"]
    componente = comp or "geral"
    ed, ref, tol = linha["edicao"], linha["referencia"], TOLERANCIAS[chave]
    tol_txt = _fmt(tol, 0 if tol == int(tol) else 1)          # "5" pontos; "0,2" no índice
    un, casas = UNIDADE_TEXTO[chave], linha["casas"]
    v = _fmt(linha["valor"], casas)
    comum = {"ano": ed, "indicador": chave}
    saida = []
    if chave in COM_META and linha["situacao_meta"] in ("atingiu", "nao_atingiu"):
        atingiu = linha["situacao_meta"] == "atingiu"
        meta = _fmt(linha["meta"], linha["meta_casas"])
        if chave == "iee":
            quem = "pelo ICM oficial da SEDUC"
            texto = (f"IEE {ed}: {v}, com meta {meta} — meta "
                     f"{'cumprida' if atingiu else 'não cumprida'} ({quem}).")
        else:
            texto = (f"Ideb {ed}: {v}, com meta {meta} — meta "
                     f"{'atingida' if atingiu else 'não atingida'} (Ideb ≥ meta, leitura do "
                     "INEP).")
        saida.append(_sinal("meta_atingida" if atingiu else "meta_nao_atingida", "avaliacao",
                            componente, "oficial", "favoravel" if atingiu else "atencao", texto,
                            ref, **comum))
    if linha["posicao_rede"] is not None:
        d = _fmt(abs(linha["diferenca_rede"]), linha["casas_diferenca"])
        vr = _fmt(linha["valor_rede"], linha["casas_rede"])
        pos = linha["posicao_rede"]
        if pos == "na_media":
            texto = (f"{ref}: {v}{un} — na média da rede municipal ({vr}; diferença de {d}, "
                     f"menor que {tol_txt}).")
        else:
            texto = f"{ref}: {v}{un} — {d} {pos} da rede municipal ({vr})."
        codigo = {"acima": "acima_da_rede", "abaixo": "abaixo_da_rede",
                  "na_media": "na_media_da_rede"}[pos]
        direcao = {"acima": "favoravel", "abaixo": "atencao", "na_media": "informativo"}[pos]
        saida.append(_sinal(codigo, "avaliacao", componente, "calculado", direcao, texto, ref,
                            **comum))
    if linha["tendencia"] is not None:
        a = linha["anterior"]
        va = _fmt(a["valor"], a["casas"])
        ref_t = referencia_oficial(chave, etapa, comp, f"{a['edicao']} e {ed}")
        rot = linha["rotulo"]
        if linha["tendencia"] == "estavel":
            texto = (f"{rot}: estável — {va} ({a['edicao']}) e {v} ({ed}), diferença menor que "
                     f"{tol_txt}.")
        else:
            verbo = "subiu" if linha["tendencia"] == "subiu" else "caiu"
            texto = f"{rot}: {verbo} de {va} ({a['edicao']}) para {v} ({ed})."
        direcao = {"subiu": "favoravel", "caiu": "atencao",
                   "estavel": "informativo"}[linha["tendencia"]]
        saida.append(_sinal(linha["tendencia"], "avaliacao", componente, "calculado", direcao,
                            texto, ref_t, **comum))
    if linha["instavel"] or linha["tps_zero"]:
        texto = (f"{ref}: {TEXTO_IEE_TPS_ZERO}." if chave == "iee" and not linha["instavel"]
                 else f"{ref}: {TEXTO_INSTAVEL}.")
        saida.append(_sinal("media_instavel", "dados", componente, "dados", "informativo", texto,
                            ref, **comum))
    return saida


def _oficiais_da_escola(L: ind_svc.Leituras, escola: Escola, inep: str | None
                        ) -> tuple[list[dict], list[dict], set[int]]:
    """(linhas oficiais, sinais das avaliações e dos dados oficiais, fontes citadas)."""
    itens, _fontes = ind_svc.indicadores_da_escola(L, escola)
    linhas, sinais, fontes = [], [], set()
    edicoes_oficiais_saresp: set[int] = set()
    for chave, etapa, comp in SERIES_OFICIAIS:
        da_escola, da_rede, quebras = _series_da_escola(itens, chave, etapa, comp)
        if da_escola is None:
            continue
        linha = _linha_oficial(chave, etapa, comp, da_escola, da_rede, quebras)
        if linha is not None:
            linhas.append(linha)
            sinais.extend(_sinais_da_linha(linha))
            fontes |= {i for i in (linha["fonte_id"], linha["fonte_rede_id"]) if i is not None}
        if chave == "saresp":
            edicoes_oficiais_saresp |= {p["edicao"] for p in da_escola["pontos"]
                                         if ind_svc.e_oficial(p)}
        # O número gravado antes, sem o registro do arquivo oficial, nas edições sem número
        # oficial: aparece como sinal de dados (nunca em ``oficiais`` e nunca "estimativa").
        oficiais_eds = {p["edicao"] for p in da_escola["pontos"] if ind_svc.e_oficial(p)}
        for p in da_escola["pontos"]:
            if ind_svc.e_sem_registro(p) and p["edicao"] not in oficiais_eds:
                ref = referencia_oficial(chave, etapa, comp, p["edicao"])
                sinais.append(_sinal(
                    "numero_sem_registro", "dados", comp or "geral", "dados", "informativo",
                    (f"{ref}: {ind_svc.TEXTO_SEM_REGISTRO} — não entra no diagnóstico (importe "
                     "o arquivo oficial desta edição)."), ref, ano=p["edicao"], indicador=chave))
    # A Estimativa Constela do SARESP (calculada pelo Constela) nas edições sem número
    # oficial da escola: sinal de dados, uma vez por edição × componente.
    vistos = set()
    for est in L.saresp["estimativas"]:
        if est["escola_id"] != escola.id or est["edicao"] in edicoes_oficiais_saresp:
            continue
        comp = est["componente"] if est["componente"] in ("lp", "mt") else None
        if (est["edicao"], comp) in vistos:
            continue
        vistos.add((est["edicao"], comp))
        ref = f"SARESP {est['edicao']} · Estimativa Constela"
        sinais.append(_sinal(
            "so_estimativa", "dados", comp or "geral", "dados", "informativo",
            (f"SARESP {est['edicao']}: só há a Estimativa Constela (calculada pelo Constela) — "
             "ela não é o resultado oficial e não entra no diagnóstico."), ref,
            ano=est["edicao"], indicador="saresp"))
    if not inep:
        sinais.append(_sinal("sem_codigo_inep", "dados", "geral", "dados", "informativo",
                             ("Escola sem código INEP no cadastro: os números oficiais dela não "
                              "podem ser casados."), "Cadastro da escola"))
    if not linhas:
        sinais.append(_sinal("sem_resultado_oficial", "dados", "geral", "dados", "informativo",
                             ("Nenhum resultado oficial da escola no IEE, no Ideb, no SARESP (2º "
                              "e 5º ano) nem no Saeb (5º ano)."), "Avaliações externas"))
    return linhas, sinais, fontes


# --- Plataformas ---------------------------------------------------------------------------

def _periodo(janela: dict) -> str:
    if janela.get("inicio") and janela.get("fim"):
        return f"{_data_br(janela['inicio'])}–{_data_br(janela['fim'])}"
    return janela.get("rotulo") or "período"


def _referencias_plataformas(plat: dict) -> dict:
    """A REDE de cada plataforma na janela (a soma das escolas visíveis com a coleta em dia
    — a mesma da rota de plataformas) e quantas escolas têm cada métrica comparável."""
    saida = {}
    for p, cfg in PLATAFORMAS.items():
        if not plat["modulos"][p]:
            saida[p] = None
            continue
        bloco = plat["rede"].get(p)
        contagem = {}
        for chave in ("participacao_pct", cfg["intensidade"]):
            contagem[chave] = sum(
                1 for e in plat["escolas"]
                if not e["suprimido"] and e.get(p) and (e["cobertura"] or {}).get(p)
                == plat_svc.COBERTURA_OK and e[p].get(chave) is not None)
        # Rede suprimida (menos de k alunos no total): o bloco nem existe — o texto é o dela.
        motivo = ((plat["rede"]["texto_supressao"] or "o total da rede está protegido")
                  if bloco is None else bloco.get("texto_sem_dado"))
        saida[p] = {
            "participacao_pct": bloco.get("participacao_pct") if bloco else None,
            cfg["intensidade"]: bloco.get(cfg["intensidade"]) if bloco else None,
            "escolas_com_participacao": contagem["participacao_pct"],
            "escolas_com_intensidade": contagem[cfg["intensidade"]],
            "motivo_sem_dado": motivo,
        }
    return saida


def _comparar_plataforma(valor, rede_valor, n_escolas: int, motivo_base: str | None, *,
                         intensidade: bool) -> tuple[str | None, float | None, str | None]:
    """(posição, diferença, motivo sem comparação) de UMA métrica contra a rede."""
    if motivo_base:
        return None, None, motivo_base
    if valor is None:
        return None, None, "a escola não tem este número no período"
    if rede_valor is None:
        return None, None, "a rede não tem este número no período (protegido ou sem coleta)"
    if n_escolas < N_MINIMO_ESCOLAS:
        return None, None, (f"só {n_escolas} escola(s) da rede com este número no período; a "
                            f"comparação exige pelo menos {N_MINIMO_ESCOLAS}")
    if intensidade:
        if rede_valor == 0:
            return ("na_media" if valor == 0 else "acima"), None, None
        dif = arredondar(100 * (valor - rede_valor) / rede_valor, 1) + 0.0
        return posicao(dif, TOLERANCIA_INTENSIDADE_PCT), dif, None
    dif = arredondar(valor - rede_valor, 1) + 0.0
    return posicao(dif, TOLERANCIA_PARTICIPACAO_PP), dif, None


def _plataformas_da_escola(e_plat: dict | None, plat: dict, refs: dict, janela: dict
                           ) -> tuple[dict, list[dict], bool]:
    """(bloco ``plataformas`` da escola, sinais de plataforma e de dados, se alguma
    plataforma foi medida)."""
    suprimida = bool(e_plat is None or e_plat["suprimido"])
    cobertura = None if suprimida else e_plat["cobertura"]
    saida = {"cobertura": cobertura,
             "ultima_coleta": None if suprimida else e_plat["ultima_coleta"],
             "suprimido": suprimida,
             "motivo_supressao": plat_svc.SUPRIMIDO if suprimida else None,
             "texto_supressao": plat_svc.TEXTO_SUPRESSAO if suprimida else None}
    sinais, medida = [], False
    periodo = _periodo(janela)
    ano = janela.get("ano_letivo")
    for p, cfg in PLATAFORMAS.items():
        nome, comp, chave_int = cfg["nome"], cfg["componente"], cfg["intensidade"]
        ref = f"{nome} · {periodo}"
        comum = {"ano": ano, "plataforma": p}
        if not plat["modulos"][p]:
            saida[p] = None
            sinais.append(_sinal("modulo_nao_contratado", "dados", comp, "dados", "informativo",
                                 (f"{nome}: a rede não contratou este módulo — sem dado de "
                                  f"plataforma para {AREA[comp]}."), nome, **comum))
            continue
        bloco = None if suprimida else e_plat.get(p)
        cob = None if suprimida else (cobertura or {}).get(p)
        protegidas = list((bloco or {}).get("metricas_protegidas") or [])
        motivo_dado = (bloco or {}).get("motivo_sem_dado")
        k = suprimida or motivo_dado in _MOTIVOS_K or bool(
            {"participacao_pct", chave_int} & set(protegidas))
        item = {m: (bloco or {}).get(m) for m in cfg["metricas"]}
        item.update(suprimido=k, cobertura=cob,
                    coleta_parcial=bool((bloco or {}).get("coleta_parcial")),
                    coberto_ate=(bloco or {}).get("coberto_ate"),
                    motivo_sem_dado=plat_svc.SUPRIMIDO if suprimida else motivo_dado,
                    texto_sem_dado=(plat_svc.TEXTO_SUPRESSAO if suprimida
                                    else (bloco or {}).get("texto_sem_dado")),
                    metricas_protegidas=protegidas)
        if item["participacao_pct"] is not None:
            medida = True
        # Por que NÃO se compara (antes de olhar os números): a supressão, a cobertura.
        if suprimida:
            motivo_base = "poucos alunos: os números não aparecem, para proteger as crianças"
        elif cob == plat_svc.COLETA_PARCIAL:
            motivo_base = (f"coleta parcial: os números valem só até "
                           f"{_data_br(item['coberto_ate']) or '—'} e não se comparam com a rede")
        elif cob != plat_svc.COBERTURA_OK:
            motivo_base = (plat_svc.TEXTOS_COBERTURA.get(cob, "sem coleta no período")
                           if cob else "sem coleta no período")
        elif motivo_dado:
            motivo_base = item["texto_sem_dado"] or "sem número no período"
        else:
            motivo_base = None
        ref_rede = refs[p]
        # A média escondida em complemento (k) não é "a escola não tem este número": ela
        # existe e não aparece, para proteger as crianças.
        motivo_p, motivo_i = (
            TEXTO_METRICA_PROTEGIDA if motivo_base is None and m in protegidas else motivo_base
            for m in ("participacao_pct", chave_int))
        pos_p, dif_p, mot_p = _comparar_plataforma(
            item["participacao_pct"], ref_rede["participacao_pct"],
            ref_rede["escolas_com_participacao"], motivo_p, intensidade=False)
        pos_i, dif_i, mot_i = _comparar_plataforma(
            item[chave_int], ref_rede[chave_int], ref_rede["escolas_com_intensidade"],
            motivo_i, intensidade=True)
        item.update(posicao_participacao=pos_p, diferenca_participacao=dif_p,
                    posicao_intensidade=pos_i, diferenca_intensidade_pct=dif_i,
                    motivo_sem_comparacao=mot_p if pos_p is None else (
                        mot_i if pos_i is None else None))
        saida[p] = item
        # Sinais de plataforma (natureza "plataforma"): participação e intensidade.
        if pos_p is not None:
            v, vr = _fmt(item["participacao_pct"], 1), _fmt(ref_rede["participacao_pct"], 1)
            if pos_p == "na_media":
                texto = (f"{ref}: participação de {v}%, na média da rede ({vr}%; diferença "
                         f"menor que {_fmt(TOLERANCIA_PARTICIPACAO_PP, 0)} p.p.).")
            else:
                texto = (f"{ref}: participação de {v}%, {_fmt(abs(dif_p), 1)} p.p. {pos_p} da "
                         f"rede ({vr}%).")
            sinais.append(_sinal(f"participacao_{_sufixo(pos_p)}", "plataforma", comp,
                                 "plataforma", _direcao(pos_p), texto, ref, **comum))
        if pos_i is not None:
            v, vr = _fmt(item[chave_int], 2), _fmt(ref_rede[chave_int], 2)
            rot = cfg["rotulo_intensidade"]
            if pos_i == "na_media":
                texto = (f"{ref}: {v} {rot}, na média da rede ({vr}; diferença menor que "
                         f"{_fmt(TOLERANCIA_INTENSIDADE_PCT, 0)}% do valor da rede).")
            elif dif_i is None:
                texto = f"{ref}: {v} {rot}, {pos_i} da rede ({vr})."
            else:
                texto = f"{ref}: {v} {rot}, {_fmt(abs(dif_i), 1)}% {pos_i} da rede ({vr})."
            sinais.append(_sinal(f"intensidade_{_sufixo(pos_i)}", "plataforma", comp,
                                 "plataforma", _direcao(pos_i), texto, ref, **comum))
        # Sinais de dados: por que a plataforma não tem posição.
        if k:
            sinais.append(_sinal("celula_protegida", "dados", comp, "dados", "informativo",
                                 (f"{ref}: poucos alunos — os números não aparecem ou não se "
                                  f"comparam, para proteger as crianças (k = {plat['k_minimo']})."),
                                 ref, **comum))
        elif cob == plat_svc.COLETA_PARCIAL:
            sinais.append(_sinal("coleta_parcial", "dados", comp, "dados", "informativo",
                                 f"{ref}: {motivo_base}.", ref, **comum))
        elif cob in (plat_svc.SEM_COLETA, plat_svc.SEM_COLETA_NO_PERIODO):
            sinais.append(_sinal("sem_coleta_no_periodo", "dados", comp, "dados", "informativo",
                                 f"{ref}: {motivo_base}.", ref, **comum))
        elif cob == plat_svc.SEM_ALUNOS:
            sinais.append(_sinal("sem_alunos_no_recorte", "dados", comp, "dados", "informativo",
                                 f"{ref}: {motivo_base}.", ref, **comum))
        elif motivo_dado == plat_svc.SEM_CONTA:
            sinais.append(_sinal("sem_conta_na_plataforma", "dados", comp, "dados",
                                 "informativo", f"{ref}: {motivo_base}.", ref, **comum))
    return saida, sinais, medida


def _sufixo(pos: str) -> str:
    return {"acima": "acima_da_rede", "abaixo": "abaixo_da_rede", "na_media": "na_media"}[pos]


def _direcao(pos: str) -> str:
    return {"acima": "favoravel", "abaixo": "atencao", "na_media": "informativo"}[pos]


# --- Leituras e acompanhamento ---------------------------------------------------------------

def estado(sinais: list[dict]) -> str:
    """"favoravel" (só favoráveis), "atencao" (só atenção), "misto" (os dois) ou
    "sem_dado" (nenhum sinal favorável nem de atenção — sem número, ou só sinais
    informativos: na média, estável)."""
    fav = any(s["direcao"] == "favoravel" for s in sinais)
    ate = any(s["direcao"] == "atencao" for s in sinais)
    if fav and ate:
        return "misto"
    return "favoravel" if fav else "atencao" if ate else "sem_dado"


def categoria(aval: str, plat: str) -> str:
    if aval == "favoravel" and plat == "favoravel":
        return "convergente_favoravel"
    if aval == "atencao" and plat == "atencao":
        return "convergente_atencao"
    if aval == "atencao" and plat == "favoravel":
        return "divergente_uso_alto"
    if aval == "favoravel" and plat == "atencao":
        return "divergente_uso_baixo"
    return "inconclusiva"


def _por_que_sem_dado(sinais: list[dict], neutro: str, lado: str, sem_numero: str) -> str:
    """Por que um eixo ficou sem sinal: há número, mas só sinais informativos (na média,
    estável) — o que NÃO é falta de dado —, ou não há número comparável (com o motivo)."""
    if sinais:
        return f"{neutro} (nenhum sinal favorável nem de atenção)"
    return f"{lado}: {sem_numero}"


def _lista_anos(anos: list[int]) -> str:
    """"2025" · "2023 e 2025" · "2023, 2025 e 2026"."""
    txt = [str(a) for a in anos]
    return txt[0] if len(txt) == 1 else ", ".join(txt[:-1]) + " e " + txt[-1]


def _janela_num_ano_so(janela: dict, ano: int) -> bool:
    """As plataformas medem UM ano letivo, o ``ano``: todas as escolas nele e o período
    dentro dele — a mesma exigência da relação (``relacao._sobrepoe``)."""
    anos_letivos = janela.get("anos_letivos") or []
    ini, fim = janela.get("inicio"), janela.get("fim")
    return (bool(anos_letivos) and all(a == ano for a in anos_letivos)
            and bool(ini) and bool(fim) and ini[:4] == fim[:4] == str(ano))


def _texto_plataformas(janela: dict, ano: int) -> str:
    """O ano das plataformas no texto da comparabilidade, dizendo por que não é UM só."""
    anos_letivos = janela.get("anos_letivos") or []
    if len(anos_letivos) > 1:
        return f"{_lista_anos(anos_letivos)} (escolas em anos letivos diferentes)"
    if not _janela_num_ano_so(janela, ano):
        return f"{ano} (período {_periodo(janela)}, que não cabe no ano de {ano})"
    return str(ano)


def leitura(c: str, sinais: list[dict], plataformas: dict, janela: dict) -> dict:
    """A leitura de UM componente (lp | mt): o estado das avaliações e o da plataforma, a
    categoria, o texto e a comparabilidade dos anos (``janela`` = a da rota de plataformas)."""
    ano_plataforma = janela.get("ano_letivo")
    p = PLATAFORMA_DO_COMPONENTE[c]
    nome = PLATAFORMAS[p]["nome"]
    do_comp = [s for s in sinais if s["eixo"] == "avaliacao" and s["componente"] == c]
    gerais = [s for s in sinais if s["eixo"] == "avaliacao" and s["componente"] == "geral"]
    if do_comp:
        base, aval = "componente", do_comp
    elif gerais:
        base, aval = "geral", gerais
    else:
        base, aval = None, []
    plat = [s for s in sinais if s["eixo"] == "plataforma" and s["componente"] == c]
    ea, ep = estado(aval), estado(plat)
    cat = categoria(ea, ep)
    # Os anos da avaliação são os dos sinais que DECIDEM o estado (favorável/atenção — o mesmo
    # filtro de ``referencias``): um "na média" de 2026 não faz "mesmo ano" de uma atenção do
    # Saeb 2025. Sem nenhum sinal com direção, os anos de todos — só para exibir: nenhuma
    # edição decide a leitura, então ela nunca é "mesmo ano".
    com_direcao = [s for s in aval if s["direcao"] != "informativo"]
    anos_aval = sorted({s["ano"] for s in (com_direcao or aval) if s["ano"] is not None})
    anos = {"avaliacao": anos_aval[-1] if anos_aval else None,
            "plataforma": ano_plataforma if plat else None}
    # "Mesmo ano" = todos esses anos iguais ao ano letivo das plataformas, com todas as escolas
    # nele e o período dentro dele (a relação recusaria o par de outro jeito).
    mesmo_periodo = (anos["plataforma"] is not None and anos_aval == [anos["plataforma"]]
                     and _janela_num_ano_so(janela, anos["plataforma"]))
    if anos["avaliacao"] is None or anos["plataforma"] is None:
        comparabilidade, texto_comp = None, TEXTO_SEM_COMPARABILIDADE
    elif mesmo_periodo and com_direcao:
        comparabilidade, texto_comp = "mesmo_ano", TEXTO_MESMO_ANO
    elif mesmo_periodo:
        comparabilidade = None
        texto_comp = TEXTO_AVALIACAO_SEM_DIRECAO.format(ano=anos["avaliacao"])
    else:
        comparabilidade = "exploratoria"
        texto_comp = (f"Avaliação de {_lista_anos(anos_aval)}; plataformas de "
                      f"{_texto_plataformas(janela, anos['plataforma'])}. " + TEXTO_EXPLORATORIA)
    motivo = None
    if cat == "inconclusiva":
        partes = []
        if ea == "misto":
            partes.append("as avaliações têm sinais nos dois sentidos")
        elif ea == "sem_dado":
            partes.append(_por_que_sem_dado(
                aval, "as avaliações estão na média da rede ou estáveis", "avaliações",
                "sem resultado oficial comparável"))
        if ep == "misto":
            partes.append(f"o uso do {nome} tem sinais nos dois sentidos")
        elif ep == "sem_dado":
            bloco = plataformas.get(p)
            sem = ("a rede não contratou este módulo" if bloco is None
                   else bloco.get("motivo_sem_comparacao") or "sem posição contra a rede")
            partes.append(_por_que_sem_dado(plat, f"o uso do {nome} está na média da rede",
                                            f"uso do {nome}", sem))
        motivo = "; ".join(partes)
    area = AREA[c]
    # O lado da AVALIAÇÃO não diz "em relação à rede": o sinal favorável ou de atenção pode
    # ser a meta oficial ou a tendência (contra a edição anterior), não só a posição. O da
    # PLATAFORMA é sempre contra a rede (o único sinal com direção ali). E nada de "mas": as
    # duas fontes são postas lado a lado, sem sugerir que uma deveria mover a outra.
    textos = {
        "convergente_favoravel": (f"{area}: as avaliações oficiais têm sinais favoráveis e o uso "
                                  f"do {nome} está acima da rede — as duas fontes apontam para o "
                                  "mesmo lado."),
        "convergente_atencao": (f"{area}: as avaliações oficiais pedem atenção e o uso do {nome} "
                                "está abaixo da rede — as duas fontes apontam para o mesmo lado."),
        "divergente_uso_alto": (f"{area}: as avaliações oficiais pedem atenção e o uso do {nome} "
                                "está acima da rede — as duas fontes apontam para lados opostos."),
        "divergente_uso_baixo": (f"{area}: as avaliações oficiais têm sinais favoráveis e o uso "
                                 f"do {nome} está abaixo da rede — as duas fontes apontam para "
                                 "lados opostos."),
        "inconclusiva": f"{area}: leitura inconclusiva — {motivo}.",
    }
    return {"avaliacao": ea, "base": base, "plataforma": ep, "categoria": cat, "motivo": motivo,
            "texto": textos[cat], "anos": anos, "comparabilidade": comparabilidade,
            "texto_comparabilidade": texto_comp,
            "referencias": sorted({s["referencia"] for s in aval + plat
                                   if s["direcao"] != "informativo"})}


def acompanhamento(leituras: dict, sinais: list[dict], tem_oficial: bool,
                   plataforma_medida: bool) -> dict:
    """O nível de acompanhamento e os motivos (cada um com a referência do sinal)."""
    cats = {c: leituras[c]["categoria"] for c in ("lp", "mt")}

    def motivos_da(cat: str) -> list[str]:
        return [f"{leituras[c]['texto']} Referências: {'; '.join(leituras[c]['referencias'])}."
                for c in ("lp", "mt") if cats[c] == cat]

    metas = [s for s in sinais if s["codigo"] == "meta_nao_atingida"]
    if "convergente_atencao" in cats.values():
        return {"nivel": "prioritario", "motivos": motivos_da("convergente_atencao")}
    if "divergente_uso_alto" in cats.values() or metas:
        return {"nivel": "acompanhar",
                "motivos": motivos_da("divergente_uso_alto") + [s["texto"] for s in metas]}
    if "divergente_uso_baixo" in cats.values():
        return {"nivel": "oportunidade", "motivos": motivos_da("divergente_uso_baixo")}
    if not tem_oficial and not plataforma_medida:
        return {"nivel": "dados_insuficientes",
                "motivos": [("Sem resultado oficial da escola e sem uso das plataformas medido "
                             "no período: não há o que diagnosticar.")]}
    # "Sem sinal" sem NENHUM sinal com direção não é "tudo bem": os números da escola estão na
    # média, estáveis ou sem comparação válida (média instável, primeira edição, coleta
    # parcial, k) — o motivo diz isso, para a falta de comparação não passar por tranquilidade.
    if not any(s["direcao"] != "informativo" for s in sinais):
        return {"nivel": "sem_sinal",
                "motivos": [("Nenhum sinal favorável nem de atenção: os números da escola estão "
                             "na média, estáveis ou sem comparação válida (veja os sinais de "
                             "dados).")]}
    return {"nivel": "sem_sinal",
            "motivos": [("Nenhuma leitura convergente de atenção, nenhuma divergência e "
                         "nenhuma meta oficial não atingida.")]}


# --- Entrada ------------------------------------------------------------------------------

def _referencias_rede(L: ind_svc.Leituras, escolas: list[dict]) -> tuple[list[dict], set[int]]:
    """A rede municipal nas edições usadas nas comparações e na mais recente de cada série
    (os números da série ``rede_municipal`` das consultas oficiais)."""
    usadas: dict[tuple, set[int]] = {}
    for e in escolas:
        for ln in e["oficiais"]:
            if ln["valor_rede"] is not None:
                usadas.setdefault((ln["indicador"], ln["etapa"], ln["componente"]),
                                  set()).add(ln["edicao"])
    saida, fontes = [], set()
    for chave, etapa, comp in SERIES_OFICIAIS:
        if chave not in COM_POSICAO:
            continue
        ind = ind_svc.INDICADORES[chave]
        rede = next((s for s in ind.series_rede(L, etapa, comp) if s["id"] == "rede_municipal"),
                    None)
        if rede is None or not rede["comparavel"]:
            continue
        pontos = [p for p in rede["pontos"] if ind_svc.e_oficial(p)]
        if not pontos:
            continue
        eds = usadas.get((chave, etapa, comp), set()) | {pontos[-1]["edicao"]}
        for p in pontos:
            if p["edicao"] in eds:
                saida.append({"indicador": chave, "rotulo": rotulo_serie(chave, etapa, comp),
                              "etapa": etapa, "componente": comp, "edicao": p["edicao"],
                              "valor": p["valor"], "casas": p["casas"], "fonte_id": p["fonte_id"],
                              "referencia": referencia_oficial(chave, etapa, comp, p["edicao"])})
                if p["fonte_id"] is not None:
                    fontes.add(p["fonte_id"])
    return saida, fontes


def diagnostico(db: Session, rede: Rede, *, preset: str = "ano_letivo",
                inicio: date | None = None, fim: date | None = None, hoje: date,
                k: int = K_MINIMO, agora: datetime | None = None) -> dict:
    validar_anos(inicio=inicio, fim=fim)
    # As plataformas primeiro: valida o período (400/422) antes de qualquer outra conta.
    plat = plat_svc.plataformas_da_rede(db, rede, preset=preset, inicio=inicio, fim=fim,
                                        hoje=hoje, k=k)
    janela = plat["janela"]
    ano_plataforma = janela.get("ano_letivo")
    refs_plat = _referencias_plataformas(plat)
    por_id = {e["escola_id"]: e for e in plat["escolas"]}
    L = ind_svc.Leituras(db, rede)
    fontes_citadas: set[int] = set()
    escolas = []
    for escola in ind_svc.escolas_da_rede(db, rede):       # ordem alfabética (sem ranking)
        inep = normalizar_inep(escola.codigo_inep)
        oficiais, sinais, fontes = _oficiais_da_escola(L, escola, inep)
        fontes_citadas |= fontes
        bloco_plat, sinais_plat, medida = _plataformas_da_escola(por_id.get(escola.id), plat,
                                                                refs_plat, janela)
        sinais = sinais + sinais_plat
        leituras = {c: leitura(c, sinais, bloco_plat, janela) for c in ("lp", "mt")}
        escolas.append({
            "id": escola.id, "nome": escola.nome, "codigo_inep": inep, "status": escola.status,
            "pendencias": [] if inep else ["sem_codigo_inep"],
            "oficiais": oficiais, "plataformas": bloco_plat, "sinais": sinais,
            "leituras": leituras,
            "acompanhamento": acompanhamento(leituras, sinais, bool(oficiais), medida),
            "_medida": medida,
        })
    referencias, fontes_rede = _referencias_rede(L, escolas)
    fontes_citadas |= fontes_rede
    mapa_fontes: dict[int, dict] = {}
    for chave in ("saresp", "iee", "ideb", "saeb"):
        mapa_fontes.update(ind_svc.INDICADORES[chave].fontes(L))
    edicoes = [ln["edicao"] for e in escolas for ln in e["oficiais"]]
    resumo = {
        "por_nivel": {n: sum(1 for e in escolas if e["acompanhamento"]["nivel"] == n)
                      for n in NIVEIS},
        "por_categoria": {c: {cat: sum(1 for e in escolas
                                       if e["leituras"][c]["categoria"] == cat)
                              for cat in CATEGORIAS} for c in ("lp", "mt")},
        "escolas_total": len(escolas),
        "escolas_com_oficial": sum(1 for e in escolas if e["oficiais"]),
        "escolas_com_plataforma": sum(1 for e in escolas if e["_medida"]),
        "anos": {"avaliacao_mais_recente": max(edicoes) if edicoes else None,
                 "plataforma": ano_plataforma},
    }
    for e in escolas:
        e.pop("_medida")
    limitacoes = list(LIMITACOES)
    if len(janela.get("anos_letivos") or []) > 1:
        limitacoes.append("As escolas da rede estão em anos letivos diferentes ("
                          + ", ".join(map(str, janela["anos_letivos"]))
                          + "): o período de cada uma é o do ano dela.")
    return {
        "rede": {"id": rede.id, "nome": rede.nome},
        "janela": janela,
        "gerado_em": (agora or agora_br()).isoformat(timespec="seconds"),
        "k_minimo": plat["k_minimo"],
        "modulos": plat["modulos"],
        "criterios": {
            "tolerancias": {"participacao_pp": TOLERANCIA_PARTICIPACAO_PP,
                            "intensidade_pct_da_rede": TOLERANCIA_INTENSIDADE_PCT,
                            **TOLERANCIAS},
            "n_minimo_escolas_comparacao": N_MINIMO_ESCOLAS,
            "regras": list(REGRAS),
        },
        "referencias_rede": referencias,
        "referencias_plataformas": refs_plat,
        "escolas": escolas,
        "resumo": resumo,
        "limitacoes": limitacoes,
        "metodologia": list(METODOLOGIA),
        "fontes": {str(i): mapa_fontes[i] for i in sorted(fontes_citadas) if i in mapa_fontes},
    }
