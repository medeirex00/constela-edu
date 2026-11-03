"""Expressões sem retrocesso catastrófico nos leitores de relatório (achado [17],
rodada de 01/11).

A estratégia POSICIONAL do leitor genérico (``importacao._LINHA_POSICIONAL``) aninhava
quantificadores: numa linha que NÃO casa, o ``re`` tentava todos os jeitos de repartir
uma sequência de dígitos em até 8 números. ~50 caracteres com dígitos no fim levavam
~2 s, ~70 levavam minutos — e o ``re`` segura a GIL, então o processo da API inteiro
congelava. O texto chega lá por qualquer PDF que nenhum perfil reconheça, pelo texto
colado e pelo upload .txt. O medidor de PDF tinha o mesmo defeito
(``perfis_pdf._RE_SO_ESPACOS``): 2^N para N espaços entre ">>" e "stream".

As expressões novas casam o MESMO que as antigas (conferido aqui em amostras fixas e
sorteadas com semente fixa, e na rodada nas linhas dos PDFs reais) e o tempo cresce em
linha reta com o tamanho da linha.

Tudo fictício. Linhas pequenas para a expressão antiga (a de referência) não demorar.
"""
import faulthandler
import random
import re
import time
from contextlib import contextmanager

import pytest

from app.services import importacao as svc
from app.services import perfis_pdf

# As expressões de ANTES (referência do resultado esperado; nunca usadas com linhas
# grandes aqui — com elas, é justamente o que travava).
_POSICIONAL_ANTIGA = re.compile(r"^\s*([^\d]{5,}?)\s+((?:[\d.,%]+\s*){1,8})$")
_ESP = rb" \t\r\n\x0b\x0c\x00"
_SO_ESPACOS_ANTIGA = re.compile(rb"(?:[" + _ESP + rb"]+|%[^\r\n]*)*")


@contextmanager
def _no_maximo(segundos: float):
    """Falha se o bloco passar de ``segundos``. O ``re`` segura a GIL e não há como
    interrompê-lo por dentro: se a expressão voltar a travar, um vigia do
    ``faulthandler`` (que não precisa da GIL) derruba o processo com o traceback depois
    de 60 s, em vez de a suíte ficar parada para sempre."""
    faulthandler.dump_traceback_later(60, exit=True)
    inicio = time.perf_counter()
    try:
        yield
    finally:
        faulthandler.cancel_dump_traceback_later()
    gasto = time.perf_counter() - inicio
    assert gasto < segundos, f"levou {gasto:.2f} s (teto {segundos} s)"


# --- Estratégia posicional: tempo --------------------------------------------

@pytest.mark.parametrize("linha", [
    "Aluno Teste " + "1" * 80 + " x",          # 80 dígitos e uma letra no fim (não casa)
    "Aluno Teste " + "1" * 78,                 # 78 dígitos que casam
    "Aluno Teste " + "1 " * 40 + "x",          # 40 números e uma letra no fim
    "Aluno Teste " + "1.2,3%" * 13 + "x",      # pontuação de número grudada
], ids=["digitos_e_letra", "digitos_que_casam", "numeros_e_letra", "pontuacao_grudada"])
def test_linha_com_muitos_digitos_e_analisada_em_menos_de_1s(linha):
    """Antes: ~2 s com 50 caracteres e minutos com ~70 (aqui, ~90 com 80 dígitos)."""
    assert 85 <= len(linha) <= 95
    with _no_maximo(1.0):
        svc.analisar_texto(linha + "\n", "matific")


def test_lacunas_enormes_sao_analisadas_em_menos_de_2s():
    """15 linhas com 10 mil espaços cada: antes, ~1,2 s POR LINHA (quadrático)."""
    texto = "\n".join("a" + " " * 10_000 + "a" for _ in range(15))
    with _no_maximo(2.0):
        svc.analisar_texto(texto, "matific")


@pytest.mark.parametrize("linha", [
    " " * 1_000 + "ab cd" + " " * 1_000 + "x",   # espaço no começo e lacuna depois
    "a" + " " * 50_000 + "a",                     # uma lacuna só, enorme
    "aaaaa " + ". " * 20_000 + "x",               # pontuação de número, sem dígito
    "Aluno Teste " + "1" * 100_000 + " x",        # dígitos sem fim
], ids=["espaco_no_comeco", "lacuna_enorme", "pontuacao", "digitos_sem_fim"])
def test_a_expressao_cresce_em_linha_reta(linha):
    """A expressão sozinha (sem o teto de linha nem o corte de lacunas): mesmo linhas de
    dezenas de milhares de caracteres levam milissegundos."""
    with _no_maximo(0.5):
        svc._LINHA_POSICIONAL.match(linha)


def test_linha_maior_que_o_teto_e_pulada():
    """Uma linha de relatório real tem no máximo ~300 caracteres: acima do teto, a
    estratégia posicional nem tenta (o mesmo nome e números, com uma lacuna enorme,
    deixa de ser lido)."""
    curta = "Ana Beatriz Souza" + " " * 900 + "42 85,5 120"
    longa = "Ana Beatriz Souza" + " " * 1_000 + "42 85,5 120"
    assert len(curta) <= svc._MAX_LINHA_POSICIONAL < len(longa)
    lida = svc._estrategia_posicional([curta], "matific")
    assert lida is not None and [l.nome for l in lida.linhas] == ["Ana Beatriz Souza"]
    assert svc._estrategia_posicional([longa], "matific") is None


# --- Estratégia posicional: o mesmo resultado da expressão antiga --------------

_FIXAS = [
    "Ana Beatriz Souza 42 85,5 120",
    "Ana Beatriz Souza\t42\t85,5\t120",
    "  Ana Beatriz Souza   42   85,5   120   ",
    "Ana Beatriz Souza 42 85,5 120\n",
    "Ana Beatriz Souza 1.234 92% 7",
    "Ana Beatriz Souza 1 2 3 4 5 6 7 8",
    "Ana Beatriz Souza 1 2 3 4 5 6 7 8 9",       # 9 números: nenhuma casa
    "Ana Beatriz Souza 42 x",
    "Ana Beatriz Souza 4285120",
    "Ana Beatriz Souza 42,,85..120%%",
    "Ana Beatriz Souza . , %",
    "João Pedro Barbosa 10 70 35",
    "Bia Sá 3",
    "Bia 3",                                     # nome curto demais
    "   ab 12",                                  # a antiga casava com "   ab"
    "      12 3",
    "ab    12",
    "Total 52 155",
    "Ana-Lu D'Ávila 5 6",
    "Ana\xa0Maria\xa012 3",
    "Ana Maria ٣ 4",                             # dígito arábico-índico também é \d
    "",
    "     ",
    "12 34 56",
    "Ana Maria 12 Souza 34",
]
_ALFABETO = list("aaaBBé  \t\xa0 119٣..,%-:")


def _amostras(n: int = 4_000) -> list[str]:
    sorteio = random.Random(20261101)
    saida = list(_FIXAS)
    for _ in range(n):
        if sorteio.random() < 0.5:
            saida.append("".join(sorteio.choice(_ALFABETO)
                                 for _ in range(sorteio.randint(0, 22))))
            continue
        nome = sorteio.choice(["Ana Maria", "Jo", "Bia Sá", "  Ana", "Ana-Lu", "a b",
                               "Ana  Lu", " \t ab", "x"])
        numeros = [sorteio.choice(["1", "42", "85,5", "1.234", "92%", ".", ",", "9.", "٣"])
                   for _ in range(sorteio.randint(0, 10))]
        junta = sorteio.choice([" ", "  ", "", "\t"])
        while numeros and len(junta.join(numeros)) > 16:   # a antiga explode
            numeros.pop()
        saida.append(sorteio.choice(["", " "]) + nome + sorteio.choice([" ", "\t", ""])
                     + junta.join(numeros) + sorteio.choice(["", " ", "\n", " x", "a"]))
    return saida


def test_a_expressao_nova_casa_o_mesmo_que_a_antiga():
    """Onde as duas casam, os mesmos grupos (o grupo 2 só perdeu os espaços do fim). A
    antiga ainda casava num caso que a nova recusa: devolvendo ao nome o espaço do
    começo da linha, com um "nome" de menos de 5 letras visíveis — que
    ``_parece_nome`` sempre recusou. A nova nunca casa onde a antiga não casava."""
    so_antiga = 0
    for linha in _amostras():
        antiga, nova = _POSICIONAL_ANTIGA.match(linha), svc._LINHA_POSICIONAL.match(linha)
        if nova:
            assert antiga, repr(linha)
            assert nova.group(1) == antiga.group(1), repr(linha)
            assert nova.group(2) == antiga.group(2).rstrip(), repr(linha)
            assert nova.group(2).split() == antiga.group(2).split(), repr(linha)
        elif antiga:
            so_antiga += 1
            assert linha[:antiga.start(1) + 1].isspace(), repr(linha)
            assert len(antiga.group(1).strip()) < 5, repr(linha)
            assert not svc._parece_nome(antiga.group(1)), repr(linha)
    assert so_antiga > 0          # as amostras cobrem esse caso


def test_estrategia_posicional_da_o_mesmo_resultado(monkeypatch):
    """A estratégia inteira, com a expressão antiga e com a nova, sobre as amostras."""
    linhas = [l for l in _amostras() if l.strip()]

    def ler():
        analise = svc._estrategia_posicional(linhas, "elefante")
        return [(l.numero, l.nome, sorted(l.dados.items()), l.avisos, l.erros)
                for l in analise.linhas]

    nova = ler()
    monkeypatch.setattr(svc, "_LINHA_POSICIONAL", _POSICIONAL_ANTIGA)
    assert ler() == nova
    assert len(nova) > 100


# --- Lacunas cortadas antes da análise -------------------------------------------

def test_lacunas_longas_sao_cortadas_no_teto():
    teto = svc._MAX_LACUNA
    assert svc._cortar_lacunas("a" + " " * 5_000 + "b") == "a" + " " * teto + "b"
    assert svc._cortar_lacunas("a" + " " * teto + "b") == "a" + " " * teto + "b"
    # Só ESPAÇOS contam na lacuna (a tabulação antes deles fica, e não entra na conta).
    assert svc._cortar_lacunas("a\t" + " " * 1_000 + "b") == "a\t" + " " * teto + "b"
    # Tabulações são separadores de coluna do TSV colado: nunca cortadas.
    assert svc._cortar_lacunas("a" + "\t" * 600 + "b") == "a" + "\t" * 600 + "b"
    # Nos PDFs reais a maior lacuna tem ~200: nada muda.
    texto = "Nome" + " " * 205 + "Atividades\nAna Souza" + " " * 199 + "42\n"
    assert svc._cortar_lacunas(texto) == texto


def test_analisar_texto_corta_as_lacunas_antes_das_estrategias(monkeypatch):
    """O corte vale no FLUXO: as quatro estratégias recebem as linhas já com a lacuna
    no teto. Sem a chamada de ``_cortar_lacunas`` em ``analisar_texto``, chegavam a
    elas os 5 mil espaços."""
    maiores: dict[str, int] = {}
    for nome in ("_estrategia_tabela", "_estrategia_vertical", "_estrategia_rotulos",
                 "_estrategia_posicional"):
        def _espia(linhas_texto, plataforma, _nome=nome, _real=getattr(svc, nome)):
            maiores[_nome] = max((len(m) for l in linhas_texto for m in re.findall(r" +", l)),
                                 default=0)
            return _real(linhas_texto, plataforma)
        monkeypatch.setattr(svc, nome, _espia)

    svc.analisar_texto("Nome" + " " * 5_000 + "42 85", "matific")

    assert set(maiores.values()) == {svc._MAX_LACUNA}
    assert len(maiores) == 4


def test_tsv_com_muitas_colunas_vazias_nao_desloca_as_colunas():
    """Tabela colada da planilha (TSV) com mais de ``_MAX_LACUNA`` células vazias
    seguidas: o corte antigo também encurtava a sequência de tabulações, o "42" e o
    "120" mudavam de coluna, a tabela não fechava e a posicional lia o 120 como
    pontuação média. Sem cortar tabulação, as colunas ficam no lugar."""
    cabecalho = ("Nome\t" + "\t".join(f"Extra {i}" for i in range(500))
                 + "\tAtividades\tEstrelas")
    linha = "Ana Beatriz Souza" + "\t" * 501 + "42\t120"
    analise = svc.analisar_texto(f"Relatório Matific\n{cabecalho}\n{linha}\n", "matific")
    assert analise.estrategia == "tabela"
    assert [(l.nome, l.dados) for l in analise.linhas] == [
        ("Ana Beatriz Souza", {"atividades": 42, "estrelas": 120})]


def test_lacuna_cortada_continua_separando_as_colunas():
    texto = ("Relatório Matific\nNome do aluno" + " " * 2_000 + "Atividades finalizadas"
             + "   Estrelas\nAna Beatriz Souza" + " " * 3_000 + "42   120\n")
    analise = svc.analisar_texto(texto, "matific")
    assert [(l.nome, l.dados.get("atividades")) for l in analise.linhas] == [
        ("Ana Beatriz Souza", 42)]


# --- Medidor de PDF: só espaços e comentários -----------------------------------

def test_medidor_so_espacos_sem_retrocesso():
    with _no_maximo(0.5):
        for trecho in (b" " * 5_000 + b"x", b"%" * 5_000 + b"\nx", b"% \n" * 3_000 + b"x",
                       b"\x00\x0b" * 3_000 + b">>"):
            assert perfis_pdf._RE_SO_ESPACOS.fullmatch(trecho) is None
        assert perfis_pdf._RE_SO_ESPACOS.fullmatch(b" %x\r\n\t%%\n" * 1_000)


def test_medidor_so_espacos_casa_o_mesmo_que_antes():
    sorteio = random.Random(1101)
    simbolos = [b" ", b"\t", b"\r", b"\n", b"\x00", b"%", b"x", b">"]
    for _ in range(4_000):
        trecho = b"".join(sorteio.choice(simbolos) for _ in range(sorteio.randint(0, 12)))
        assert (perfis_pdf._RE_SO_ESPACOS.fullmatch(trecho) is None) == (
            _SO_ESPACOS_ANTIGA.fullmatch(trecho) is None), trecho


def test_medidor_nao_trava_com_lixo_entre_o_dicionario_e_o_fluxo():
    """Um PDF de poucos bytes: 60 espaços e um "x" entre o dicionário e "stream". Antes,
    o medidor tentava 2^60 jeitos de repartir os espaços."""
    pdf = (b"%PDF-1.4\n1 0 obj\n<< /Length 4 >>" + b" " * 60 + b"x >>\nstream\nabcd\n"
           b"endstream\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n")
    with _no_maximo(2.0):
        try:
            perfis_pdf.exigir_pdf_contido(pdf)
        except perfis_pdf.PdfRecusado:
            pass                      # recusar também vale; o que não pode é travar
