"""Escalas e níveis de proficiência, versionados por ANO (plano, 4.9) — etapa E4.

ESCALAS NÃO SE MISTURAM: Saeb 5º ano (``escala_saeb``), escala do 2º ano/ICA
(``escala_alfabetizacao``, corte de 743 — ``aeeb.CORTE_ALFABETIZADO``) e SARESP
(``escala_saresp``) ficam separados. Em particular, o SARESP do 2º ano NUNCA é
cruzado com o ICA: até a SEDUC/INEP esclarecerem se a LP do 2º ano do SARESP está
na escala de alfabetização do Saeb, comparar os dois é inventar (plano, 8.3).
``exigir_mesma_escala`` barra a comparação entre escalas diferentes.

PONTOS DE CORTE DO SARESP — A CONFIRMAR. Os arquivos abertos que temos (SARESP por
município/instância, IEE e o dicionário do IEE) NÃO trazem os pontos de corte nem a
distribuição por nível. O plano (4.9) cita os cortes do Sumário Executivo SARESP
2024 da FDE, mas esse PDF não está entre os arquivos baixados (item 24 da seção
7.2) e os de 2022, 2023 e 2025 nem saíram/foram lidos. Por isso nenhum corte entra
como número aqui: a estrutura fica pronta, toda edição marcada ``a_confirmar``, e
``classificar`` não devolve nível enquanto o corte não for confirmado na fonte.
Quando o Sumário for conferido, cada corte entra com a fonte e
``situacao="confirmado"`` — por ano, porque a escala do 2º ano pode ter quebrado
entre 2022 e 2023 (TRI recalculada) e a prova do 2º ano muda em 2026.

O Constela não calcula distribuição por nível do SARESP (os dados abertos não
trazem; os microdados de aluno nunca são usados): no máximo, com o corte
confirmado, "o nível em que cai a MÉDIA" e a "distância até o Adequado", sempre
rotulados como cálculo do Constela.
"""
from __future__ import annotations

from dataclasses import dataclass

ESCALA_SAEB = "escala_saeb"
ESCALA_ALFABETIZACAO = "escala_alfabetizacao"
ESCALA_SARESP = "escala_saresp"
ESCALAS = (ESCALA_SAEB, ESCALA_ALFABETIZACAO, ESCALA_SARESP)

# Níveis do SARESP (nomenclatura da SEDUC), do mais baixo ao mais alto.
NIVEIS_SARESP = ("abaixo_do_basico", "basico", "adequado", "avancado")
ROTULO_NIVEL_SARESP = {"abaixo_do_basico": "Abaixo do Básico", "basico": "Básico",
                       "adequado": "Adequado", "avancado": "Avançado"}

SITUACAO_CONFIRMADO = "confirmado"
SITUACAO_A_CONFIRMAR = "a_confirmar"

_FONTE_A_CONFIRMAR = ("Pontos de corte não confirmados nos arquivos disponíveis: conferir no "
                      "Sumário Executivo do SARESP da edição (FDE) antes de usar.")


@dataclass(frozen=True)
class CortesSaresp:
    """Início de cada nível acima de "Abaixo do Básico" (pontos na escala SARESP)."""

    edicao: int
    etapa: str              # 2_ano | 5_ano
    componente: str         # lp | mt
    basico: float | None = None
    adequado: float | None = None
    avancado: float | None = None
    situacao: str = SITUACAO_A_CONFIRMAR
    fonte: str = _FONTE_A_CONFIRMAR

    @property
    def confirmado(self) -> bool:
        return (self.situacao == SITUACAO_CONFIRMADO
                and None not in (self.basico, self.adequado, self.avancado))


# Edições com dado aberto (2022–2025), 2º e 5º ano, LP e MT: TODAS a confirmar.
_EDICOES = (2022, 2023, 2024, 2025)
CORTES_SARESP: dict[tuple[int, str, str], CortesSaresp] = {
    (edicao, etapa, comp): CortesSaresp(edicao=edicao, etapa=etapa, componente=comp)
    for edicao in _EDICOES for etapa in ("2_ano", "5_ano") for comp in ("lp", "mt")
}


def cortes_saresp(edicao: int, etapa: str, componente: str) -> CortesSaresp:
    """Os cortes da edição (ou a estrutura vazia "a confirmar", se a edição nem
    está no catálogo)."""
    return CORTES_SARESP.get((edicao, etapa, componente),
                             CortesSaresp(edicao=edicao, etapa=etapa, componente=componente))


def classificar_saresp(media: float | None, edicao: int, etapa: str,
                       componente: str) -> dict:
    """O nível em que cai a MÉDIA e a distância até o Adequado — SÓ com o corte
    confirmado. Sem corte confirmado (hoje, todas as edições): ``nivel`` nulo e
    ``situacao="a_confirmar"`` — nunca um nível calculado com corte suposto."""
    cortes = cortes_saresp(edicao, etapa, componente)
    base = {"edicao": edicao, "etapa": etapa, "componente": componente,
            "situacao": cortes.situacao, "fonte": cortes.fonte, "nivel": None,
            "distancia_adequado": None, "calculo_do_constela": True}
    if media is None or not cortes.confirmado:
        return base
    if media >= cortes.avancado:
        nivel = "avancado"
    elif media >= cortes.adequado:
        nivel = "adequado"
    elif media >= cortes.basico:
        nivel = "basico"
    else:
        nivel = "abaixo_do_basico"
    distancia = round(max(cortes.adequado - media, 0.0), 1)
    return {**base, "nivel": nivel, "distancia_adequado": distancia}


# --- Níveis do SAEB (metodologia pública do INEP; plano, 4.9) -----------------------
# A DISTRIBUIÇÃO por nível vem SEMPRE do arquivo oficial (``pct_nivel``, etapa E7): aqui
# fica só a régua para validar o arquivo e rotular a tela. 5º ano (``escala_saeb``):
# LP do nível 0 (abaixo de 125) ao 9 (325 ou mais) e MT do 0 ao 10 (350 ou mais), em
# faixas de 25 pontos — a régua do Dicionário da planilha do Saeb 2025. 2º ano (escala
# de alfabetização, amostral): níveis 0 a 8 em LP e em MT (a planilha não traz os cortes).
NIVEIS_SAEB: dict[tuple[str, str], tuple[int, ...]] = {
    ("5_ano", "lp"): tuple(range(10)), ("5_ano", "mt"): tuple(range(11)),
    ("2_ano", "lp"): tuple(range(9)), ("2_ano", "mt"): tuple(range(9)),
}
_INICIO_NIVEL_1_SAEB_5 = 125.0
_LARGURA_NIVEL_SAEB_5 = 25.0

# FONTE DOS CORTES do 5º ano (etapa E8b): eles estão ESCRITOS no Dicionário da planilha de
# resultados do Saeb 2025 do INEP — cada ``nivel_k_LP5``/``nivel_k_MT5`` é descrito como o
# percentual de alunos com desempenho "menor que 125", "maior ou igual a 125 e menor que
# 150" ... "maior ou igual a 325" (LP) e "maior ou igual a 350" (MT): a régua acima. As
# planilhas de 2019 e 2021 não têm Dicionário: trazem os mesmos níveis só pelo número
# ("Nível 0" ... "Nível 9"/"Nível 10"), sem escrever os cortes.
FONTE_CORTES_SAEB_5 = (
    "INEP — Dicionário da planilha de resultados do Saeb 2025 (Brasil, estados e "
    "municípios): percentual de alunos do 5º ano com desempenho menor que 125, de 125 a "
    "menos de 150, e assim por diante, de 25 em 25 pontos, até 325 ou mais em Língua "
    "Portuguesa e até 350 ou mais em Matemática.")
EDICOES_CORTES_SAEB_5_NO_ARQUIVO = (2025,)
TEXTO_CORTES_SAEB_5_OUTRAS_EDICOES = (
    "As planilhas de 2019 e 2021 trazem os mesmos níveis (0 a 9 em Língua Portuguesa, 0 a 10 "
    "em Matemática) só pelo número, sem escrever os cortes: a régua mostrada é a do "
    "Dicionário de 2025.")


def faixa_nivel_saeb(etapa: str, componente: str, nivel: int) -> tuple[float | None, float | None]:
    """``(início, fim)`` do nível na escala do Saeb do 5º ano (fim aberto no último;
    início nulo no nível 0). Fora do 5º ano (sem cortes na planilha) ou nível fora da
    régua: ``(None, None)``."""
    niveis = NIVEIS_SAEB.get((etapa, componente))
    if etapa != "5_ano" or niveis is None or nivel not in niveis:
        return None, None
    inicio = None if nivel == 0 else _INICIO_NIVEL_1_SAEB_5 + _LARGURA_NIVEL_SAEB_5 * (nivel - 1)
    fim = (None if nivel == niveis[-1]
           else _INICIO_NIVEL_1_SAEB_5 + _LARGURA_NIVEL_SAEB_5 * nivel)
    return inicio, fim


def exigir_mesma_escala(unidade_a: str, unidade_b: str) -> None:
    """Comparar/traçar dois números exige a MESMA escala (ex.: nunca SARESP do 2º
    ano × ICA/escala de alfabetização). LEVANTA ``ValueError``."""
    if unidade_a not in ESCALAS or unidade_b not in ESCALAS:
        raise ValueError(f"Unidade que não é escala de proficiência: {unidade_a}, {unidade_b}.")
    if unidade_a != unidade_b:
        raise ValueError(
            f"Escalas diferentes ({unidade_a} × {unidade_b}) não se comparam: cada uma tem o "
            "seu gráfico (o SARESP do 2º ano não se cruza com o ICA).")
