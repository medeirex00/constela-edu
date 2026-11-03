"""Relação entre um indicador OFICIAL por escola e uma métrica das plataformas
(``GET /redes/{id}/analise/relacao``) — só leitura, só quando os critérios valem.

A resposta SEMPRE traz os ``pares`` (escola a escola, com o ano de cada lado), para a
tela mostrar os dois números "lado a lado" mesmo quando a associação não é calculável.
O coeficiente só sai quando TODOS os critérios de ``docs/analise/METODOLOGIA.md`` são
cumpridos — e cada recusa tem um motivo próprio:

* ``indicador_so_da_rede`` — o ICA é da rede: não existe por escola;
* ``so_estimativa`` — só há a "Estimativa Constela" — estimativa nunca entra em
  associação;
* ``so_sem_registro`` — só há números gravados antes, sem o registro do arquivo oficial
  (o Ideb e o Saeb do 1 clique) — a relação usa só números oficiais;
* ``sem_dado_oficial`` — nenhuma escola tem resultado oficial na edição;
* ``serie_incompativel`` — a série pedida para as plataformas não é a da avaliação
  (2_ano ↔ 2º ano, 5_ano ↔ 5º ano, anos iniciais/IEE ↔ escola inteira do 1º ao 5º);
* ``componente_incompativel`` — Língua Portuguesa ↔ Elefante, Matemática ↔ Matific;
* ``modulo_nao_contratado`` — a rede não contratou a plataforma da métrica;
* ``periodo_sem_sobreposicao`` — o período das plataformas não está DENTRO do ano
  letivo da edição (ou as escolas estão noutro ano letivo: outra coorte);
* ``n_insuficiente`` — menos de ``N_MINIMO`` escolas com os dois valores (célula com
  pelo menos ``K_MINIMO`` alunos);
* ``sem_variancia`` — um dos lados não varia entre as escolas.

Cada PAR tem ainda o motivo PRÓPRIO da escola (``motivo_escola``: sem resultado oficial,
número sem registro, média instável, IEE com TPS = 0, célula suprimida, sem dado da
plataforma, coleta parcial, questões de outro ano letivo), calculado sempre — também
quando um motivo geral bloqueia a relação (aí ``incluido`` é falso e o texto geral fica só
em ``textos``, sem se repetir em cada par).

O MÉTODO: correlação de postos de Spearman (Pearson dos postos, ``avaliacoes._pearson``;
empate = posto médio), com intervalo de 95% aproximado pela transformação z de Fisher e
erro-padrão 1,06/√(n−3). É associação entre ESCOLAS, nunca causa e efeito.
"""
from __future__ import annotations

from datetime import date, datetime
from math import atanh, sqrt, tanh

from sqlalchemy.orm import Session

from app.models import Rede
from app.services.analise import K_MINIMO, N_MINIMO, AnaliseInvalida, validar_anos
from app.services.analise import indicadores as ind_svc
from app.services.analise import plataformas as plat_svc
from app.services.avaliacoes import _pearson, nome_exibicao

METRICAS = {
    "livros_por_aluno": {"plataforma": "elefante", "campo": "livros_por_aluno",
                         "componente": "lp",
                         "rotulo": "Livros novos por aluno com conta (Elefante)"},
    "minutos_por_aluno": {"plataforma": "elefante", "campo": "minutos_por_aluno",
                          "componente": "lp",
                          "rotulo": "Minutos de leitura por aluno com conta (Elefante)"},
    "participacao_elefante": {"plataforma": "elefante", "campo": "participacao_pct",
                              "componente": "lp",
                              "rotulo": ("Participação no Elefante (% dos alunos com conta que "
                                         "leram)")},
    "taxa_acerto": {"plataforma": "elefante", "campo": "taxa_acerto_pct", "componente": "lp",
                    "rotulo": "Acerto nas questões do Elefante (%)"},
    "nivel_medio": {"plataforma": "elefante", "campo": "nivel_medio_posicao", "componente": "lp",
                    "rotulo": "Nível médio dos livros lidos (Elefante; posição AA = 0 … Z = 29)"},
    "atividades_por_aluno": {"plataforma": "matific", "campo": "atividades_por_aluno",
                             "componente": "mt",
                             "rotulo": "Atividades por aluno com dado no período (Matific)"},
    "estrelas_por_aluno": {"plataforma": "matific", "campo": "estrelas_por_aluno",
                           "componente": "mt",
                           "rotulo": "Estrelas por aluno com dado no período (Matific)"},
    "desempenho_medio": {"plataforma": "matific", "campo": "desempenho_medio", "componente": "mt",
                         "rotulo": "Estrelas por atividade (Matific, 0 a 5)"},
    "participacao_matific": {"plataforma": "matific", "campo": "participacao_pct",
                             "componente": "mt",
                             "rotulo": ("Participação no Matific (% dos alunos com dado no "
                                        "período que fizeram atividade)")},
}

# A série das plataformas que corresponde à etapa avaliada (None = a escola do 1º ao 5º).
SERIE_DA_ETAPA = {"2_ano": 2, "5_ano": 5, "anos_iniciais": None}
PLATAFORMA_DO_COMPONENTE = {"lp": "elefante", "mt": "matific"}

TEXTOS = {
    "indicador_so_da_rede": ("O ICA é da rede municipal: o INEP não publica o ICA por escola, "
                             "então ele não pode ser relacionado, escola a escola, com as "
                             "plataformas."),
    "so_estimativa": ("Só há a Estimativa Constela (calculada pelo Constela): estimativa não "
                      "entra em associação estatística."),
    "so_sem_registro": ("Nesta edição só há números gravados antes, sem o registro do arquivo "
                        "oficial: a relação usa só números oficiais (importe o arquivo "
                        "oficial)."),
    "sem_dado_oficial": "Nenhuma escola da rede tem resultado oficial nesta edição.",
    "serie_incompativel": ("A série escolhida para as plataformas não é a série avaliada: só "
                           "se relaciona a mesma série (2º ano com 2º ano, 5º com 5º; Ideb e "
                           "IEE com a escola inteira, do 1º ao 5º ano)."),
    "componente_incompativel": ("A métrica é de outra área: Língua Portuguesa se relaciona com "
                                "o Elefante (leitura) e Matemática com o Matific."),
    "modulo_nao_contratado": "A rede não contratou a plataforma desta métrica.",
    "periodo_sem_sobreposicao": ("Período sem sobreposição: a avaliação é de {edicao} e o "
                                 "período das plataformas é {periodo}. Só se relacionam números "
                                 "do MESMO ano letivo — senão as crianças nem são as mesmas."),
    "n_insuficiente": ("Escolas insuficientes: {n} escola(s) com os dois números; o mínimo é "
                       "{minimo}."),
    "sem_variancia": ("Um dos lados não varia entre as escolas: sem variação não há associação "
                      "a medir."),
}
_BLOQUEIOS = ("indicador_so_da_rede", "so_estimativa", "so_sem_registro", "sem_dado_oficial",
              "serie_incompativel", "componente_incompativel", "modulo_nao_contratado",
              "periodo_sem_sobreposicao")
# O par que entraria, mas fica de fora por um motivo GERAL (o texto dele está em `textos`).
FORA_PELO_MOTIVO_GERAL = "fica de fora pelo motivo geral da relação"

CAUSALIDADE = ("Correlação não é causalidade: escolas que leem mais podem ser diferentes em "
               "muitas outras coisas (turmas, frequência, contexto). A associação descreve as "
               "escolas, não o efeito da plataforma.")
METODOLOGIA = (
    "Unidade: a escola. Entram só números oficiais, com o registro do arquivo oficial (a "
    "Estimativa Constela e os números gravados antes, sem esse registro, ficam de fora), na "
    "mesma série dos dois lados (2º ano com 2º ano, 5º com 5º; Ideb e IEE com a escola "
    "inteira, do 1º ao 5º ano) e no mesmo ano letivo (o período das plataformas dentro do "
    "ano da avaliação). Cada escola precisa de pelo menos {k} alunos medidos na plataforma e "
    "da coleta em dia no período; médias instáveis (TPS = 0) e o IEE calculado com elas ficam "
    "de fora, e o acerto nas questões só vale se as coletas forem do mesmo ano letivo. São "
    "precisas pelo menos {n_min} escolas com os dois números e variação dos dois lados. "
    "Coeficiente: correlação de postos de Spearman (cada escola recebe a sua posição; empates "
    "ficam com a posição média). Intervalo de 95% aproximado pela transformação z de Fisher, "
    "com erro-padrão 1,06/√(n−3). Se o intervalo inclui o zero, não dá para afirmar que os "
    "dois números andam juntos. Correlação não é causalidade: a relação descreve as escolas, "
    "não o efeito da plataforma.")


def criterios() -> dict:
    return {"metodo": "Spearman", "n_minimo": N_MINIMO, "k_minimo_alunos": K_MINIMO,
            "exige_mesmo_ano_letivo": True, "exige_mesma_serie": True, "so_oficial": True,
            "mesma_escala": True, "unidade": "escola", "ic": "Fisher z, EP = 1,06/√(n−3)",
            "exclui_instavel": True, "exige_coleta_em_dia": True}


def postos(valores: list[float]) -> list[float]:
    """Postos 1..n; valores empatados recebem o posto MÉDIO (3 e 4 empatados → 3,5)."""
    ordem = sorted(range(len(valores)), key=lambda i: valores[i])
    saida = [0.0] * len(valores)
    i = 0
    while i < len(ordem):
        j = i
        while j + 1 < len(ordem) and valores[ordem[j + 1]] == valores[ordem[i]]:
            j += 1
        medio = (i + j) / 2 + 1
        for t in range(i, j + 1):
            saida[ordem[t]] = medio
        i = j + 1
    return saida


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Pearson dos postos (com empates) — a correlação de postos de Spearman, 3 casas."""
    return _pearson(list(zip(postos(xs), postos(ys))))


def intervalo_95(rho: float, n: int) -> dict:
    r = max(min(rho, 0.999999), -0.999999)
    z, ep = atanh(r), 1.06 / sqrt(n - 3)
    return {"inferior": round(tanh(z - 1.96 * ep), 3), "superior": round(tanh(z + 1.96 * ep), 3),
            "metodo": "Fisher z, EP = 1,06/√(n−3)"}


def _interpretacao(rho: float, ic: dict, metrica: str, indicador: str) -> str:
    if ic["inferior"] <= 0 <= ic["superior"]:
        return (f"O intervalo de 95% inclui o zero: com estas escolas, não dá para afirmar que "
                f"“{metrica}” e o {indicador} andem juntos.")
    sentido = "mais alto" if rho > 0 else "mais baixo"
    # O aviso de que correlação não é causalidade vai uma vez só, em ``avisos``.
    return (f"Entre as escolas da rede, as que têm “{metrica}” mais alto tendem a ter o "
            f"{indicador} {sentido} (associação de postos).")


def _rotulo_ano(janela) -> str:
    if janela.inicio is None or janela.fim is None:
        return janela.rotulo
    a, b = janela.inicio.year, janela.fim.year
    return str(a) if a == b else f"{a}–{b}"


def _sobrepoe(janela, edicao: int, anos_letivos: list[int]) -> bool:
    if janela.inicio is None or janela.fim is None:
        return False
    return (janela.inicio >= datetime(edicao, 1, 1)
            and janela.fim <= datetime(edicao, 12, 31, 23, 59, 59, 999999)
            and bool(anos_letivos) and all(a == edicao for a in anos_letivos))


def _motivo_oficial(p: dict, chave_indicador: str) -> str | None:
    """O motivo próprio do LADO OFICIAL do par (None = o número entra)."""
    if p["valor"] is None:
        return f"sem resultado oficial: {p['texto_ausencia']}"
    if not ind_svc.e_oficial(p):
        return f"sem registro oficial: {ind_svc.TEXTO_SEM_REGISTRO}"
    if p["instavel"]:
        return "média instável (TPS = 0: participação abaixo do mínimo do SARESP)"
    if chave_indicador == "iee" and p.get("tps_zero"):
        return "IEE calculado com médias de TPS = 0 (participação abaixo do mínimo)"
    return None


def _motivo_plataforma(info: dict | None, bloco: dict | None, dado: dict | None,
                       valor: float | None, chave_metrica: str, edicao: int) -> str | None:
    """O motivo próprio do LADO DAS PLATAFORMAS do par (None = o número entra)."""
    if info is None or bloco is None:
        return "a escola não tem alunos desta série no ano letivo"
    if bloco["suprimido"]:
        return f"célula suprimida: {bloco['texto_supressao']}"
    if dado is None:
        return "sem dado da plataforma: a rede não contratou o módulo"
    if dado.get("coleta_parcial"):
        return f"coleta parcial: {dado['texto_cobertura']}"
    if chave_metrica == "taxa_acerto":
        jq = dado.get("janela_questoes") or {}
        if jq.get("inicio") and date.fromisoformat(jq["inicio"][:10]) < date(edicao, 1, 1):
            return "as questões contam desde uma coleta de outro ano letivo"
    if valor is None:
        return ("sem dado da plataforma: " + dado["texto_sem_dado"] if dado.get("texto_sem_dado")
                else "a métrica não tem alunos suficientes para ser mostrada")
    return None


def _metrica(chave: str | None, componente: str | None) -> str:
    chave = chave or ("estrelas_por_aluno" if componente == "mt" else "livros_por_aluno")
    if chave not in METRICAS:
        raise AnaliseInvalida(f"Métrica “{chave}” não existe. As métricas: "
                              f"{', '.join(METRICAS)}.")
    return chave


def relacao(db: Session, rede: Rede, *, indicador: str, etapa: str | None = None,
            componente: str | None = None, edicao: int | None = None,
            metrica: str | None = None, periodo: str = "ano_letivo",
            inicio: date | None = None, fim: date | None = None, serie: int | None = None,
            hoje: date) -> dict:
    # A edição e as datas fora da faixa: 422 ANTES de medir a rede (antes, o ano 0 virava
    # erro 500 em ``_sobrepoe``, depois de ``celulas_da_rede`` medir todas as escolas).
    validar_anos(inicio=inicio, fim=fim, edicao=edicao)
    chave_metrica = _metrica(metrica, componente)
    meta_m = METRICAS[chave_metrica]
    saida = {
        "calculavel": False, "motivos": [], "textos": [], "avisos": [CAUSALIDADE],
        "criterios": criterios(), "indicador": None,
        "metrica": {"chave": chave_metrica, "rotulo": meta_m["rotulo"],
                    "plataforma": meta_m["plataforma"]},
        "metricas_disponiveis": [{"chave": k, "rotulo": v["rotulo"], "plataforma": v["plataforma"],
                                  "componente": v["componente"]} for k, v in METRICAS.items()],
        "filtros": {"indicador": indicador, "etapa": etapa, "componente": componente,
                    "edicao": edicao, "metrica": chave_metrica, "periodo": periodo,
                    "inicio": inicio.isoformat() if inicio else None,
                    "fim": fim.isoformat() if fim else None, "serie": serie},
        "janela": None, "pares": [], "n": 0, "coeficiente": None, "ic95": None,
        "interpretacao": None,
        "metodologia": METODOLOGIA.format(n_min=N_MINIMO, k=K_MINIMO),
    }

    def recusar(*motivos: str, **fmt) -> dict:
        for m in motivos:
            if m not in saida["motivos"]:
                saida["motivos"].append(m)
                saida["textos"].append(TEXTOS[m].format(**fmt) if fmt else TEXTOS[m])
        return saida

    if indicador in ind_svc.CHAVES_ESTIMATIVA:
        saida["indicador"] = {"chave": indicador, "nome": nome_exibicao(indicador, indicador),
                              "oficial": False}
        return recusar("so_estimativa")
    ind = ind_svc.indicador(indicador)
    L = ind_svc.Leituras(db, rede)
    saida["indicador"] = ind.item(L)
    if not ind.por_escola:
        return recusar("indicador_so_da_rede")
    if ind.componentes and componente is None and meta_m["componente"] in ind.componentes:
        componente = meta_m["componente"]
    etapa, componente = ind_svc.validar_filtros(ind, etapa, componente)
    if edicao is None:
        com_valor = sorted({p["edicao"] for linha in ind.linhas(L)
                            for p in ind.pontos_escola(L, linha, etapa, componente)
                            if ind_svc.e_oficial(p)})
        edicao = com_valor[-1] if com_valor else None
    saida["filtros"].update(etapa=etapa, componente=componente, edicao=edicao)

    cel = plat_svc.celulas_da_rede(db, rede, preset=periodo, inicio=inicio, fim=fim, hoje=hoje)
    janela = cel["janela"]
    saida["janela"] = {"preset": janela.preset, "rotulo": janela.rotulo,
                       "inicio": janela.inicio.date().isoformat() if janela.inicio else None,
                       "fim": janela.fim.date().isoformat() if janela.fim else None,
                       "ano_letivo": cel["ano_letivo"], "anos_letivos": cel["anos_letivos"]}
    alvo = SERIE_DA_ETAPA.get(etapa, -1)
    plataforma = meta_m["plataforma"]
    if alvo == -1 or (serie is not None and serie != alvo):
        recusar("serie_incompativel")
    if componente is not None and PLATAFORMA_DO_COMPONENTE[componente] != plataforma:
        recusar("componente_incompativel")
    if componente is None:
        saida["avisos"].append(
            f"O {ind.nome} junta Língua Portuguesa e Matemática: a relação com uma plataforma "
            "só olha uma das partes.")
    if not cel["modulos"][plataforma]:
        recusar("modulo_nao_contratado")
    if edicao is None:
        return recusar("so_estimativa" if ind.tem_estimativa(L)
                       else "so_sem_registro" if ind.tem_sem_registro(L)
                       else "sem_dado_oficial")
    if not _sobrepoe(janela, edicao, cel["anos_letivos"]):
        ano = cel["ano_letivo"]
        periodo = (janela.rotulo if str(ano) in janela.rotulo
                   else f"{janela.rotulo} (ano letivo {ano})")
        recusar("periodo_sem_sobreposicao", edicao=edicao, periodo=periodo)

    valores = ind_svc.valores_por_escola(L, ind, etapa, componente, edicao)
    if not any(ind_svc.e_oficial(v["ponto"]) for v in valores):
        recusar("so_estimativa" if ind.estimativas_na_edicao(L, edicao, etapa, componente)
                else "so_sem_registro" if ind.sem_registro_na_edicao(L, edicao, etapa,
                                                                      componente)
                else "sem_dado_oficial")
    bloqueado = bool(saida["motivos"])
    rotulo_ano = _rotulo_ano(janela)
    pares = []
    for v in valores:
        p = v["ponto"]
        info = cel["por_escola"].get(v["escola_id"])
        bloco = None
        if info is not None:
            # Escola suprimida (inteira) suprime todas as séries dela.
            bloco = (info["escola"] if alvo in (None, -1) or info["escola"]["suprimido"]
                     else info["series"].get(alvo))
        dado = bloco.get(plataforma) if bloco and not bloco["suprimido"] else None
        valor_plat = dado.get(meta_m["campo"]) if dado else None
        oficial = ind_svc.e_oficial(p)
        # O motivo PRÓPRIO da escola, sempre — também com a relação bloqueada.
        motivo_escola = (_motivo_oficial(p, ind.chave)
                         or _motivo_plataforma(info, bloco, dado, valor_plat, chave_metrica,
                                               edicao))
        incluido = motivo_escola is None and not bloqueado
        pares.append({
            "escola_id": v["escola_id"], "nome": v["nome"], "codigo_inep": v["codigo_inep"],
            # Só o número OFICIAL (o gravado antes, sem registro, fica de fora, com o motivo).
            "valor_oficial": p["valor"] if oficial else None,
            "casas_oficial": p["casas"] if oficial else None, "edicao": edicao,
            "texto_ausencia_oficial": p["texto_ausencia"], "instavel": p["instavel"],
            "valor_plataforma": valor_plat, "janela": rotulo_ano,
            "ano_plataforma": info["escola"]["ano_letivo"] if info else None,
            "incluido": incluido, "motivo_escola": motivo_escola,
            "motivo_exclusao": (motivo_escola if motivo_escola
                                else FORA_PELO_MOTIVO_GERAL if bloqueado else None),
        })
    saida["pares"] = pares
    if bloqueado:
        return saida
    incluidos = [p for p in pares if p["incluido"]]
    n = len(incluidos)
    if n < N_MINIMO:
        return recusar("n_insuficiente", n=n, minimo=N_MINIMO)
    xs = [p["valor_plataforma"] for p in incluidos]
    ys = [p["valor_oficial"] for p in incluidos]
    rho = spearman(xs, ys) if len(set(xs)) > 1 and len(set(ys)) > 1 else None
    if rho is None:
        return recusar("sem_variancia")
    ic = intervalo_95(rho, n)
    saida.update(calculavel=True, n=n, coeficiente=rho, ic95=ic,
                 interpretacao=_interpretacao(rho, ic, meta_m["rotulo"], ind.nome))
    return saida
