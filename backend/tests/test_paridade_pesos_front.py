"""Paridade dos PESOS exibidos à escola com os pesos oficiais do motor.

Até 31/10/2026 a explicação "Como funciona?"
(apps/web/src/components/ComoFuncionaPontuacao.tsx) mostrava os pesos da Nota de
Leitura e da Nota de Matemática como TEXTO fixo no front (constantes
``PESOS_LEITURA``/``PESOS_MATEMATICA``), e este teste comparava esse espelho com
``scoring.PESOS_PADRAO``.

Na identidade visual v2 o espelho deixou de existir: a tela de Critérios, o
"Como funciona?", o Suporte e as Configurações leem os pesos EFETIVOS do motor em
``GET /escolas/{id}/configuracoes/pontuacao/regra`` — e
``tests/test_regra_pontuacao.py`` prova que essa rota devolve exatamente
``scoring.PESOS_PADRAO`` na régua institucional. A paridade passou a ser garantida
pela FONTE ÚNICA, não por comparação de cópias.

O que este arquivo trava agora é a volta do espelho: um peso escrito à mão no
front (no formato antigo ``["livros únicos", 35]`` ou numa constante
``PESOS_LEITURA``/``PESOS_MATEMATICA``) volta a poder divergir do motor sem
ninguém perceber. Se a tela precisar de um peso, ele vem da rota.
"""
import pathlib
import re

from app.services import scoring

RAIZ_REPO = pathlib.Path(__file__).resolve().parents[2]
WEB_SRC = RAIZ_REPO / "apps" / "web" / "src"
ARQUIVO_FRONT = WEB_SRC / "components" / "ComoFuncionaPontuacao.tsx"

MSG = "a explicação dos pesos da escola voltou a ter números escritos à mão"

# Rótulos que a tela usa para cada indicador (os mesmos do espelho antigo).
ROTULOS = ("livros únicos", "dificuldade dos livros", "questões", "tempo de leitura",
           "atividades finalizadas", "pontuação média", "estrelas")
_RE_PAR = re.compile(r'\[\s*"(' + "|".join(map(re.escape, ROTULOS)) + r')"\s*,\s*\d')
_RE_CONSTANTE = re.compile(r"\bconst\s+PESOS_(LEITURA|MATEMATICA)\b")


def _fontes_do_app() -> list[pathlib.Path]:
    """Código do app web (sem testes nem mocks: fixtures podem citar pesos)."""
    return [
        p for p in sorted(WEB_SRC.rglob("*"))
        if p.suffix in (".ts", ".tsx")
        and "test" not in p.parts and "__mocks__" not in p.parts
    ]


def test_o_motor_ainda_tem_os_pesos_que_a_rota_devolve():
    # Âncora: a rota /pontuacao/regra (test_regra_pontuacao.py) devolve estes
    # dicionários na régua institucional; se as chaves sumirem, a tela fica sem peso.
    assert set(scoring.PESOS_PADRAO["pesos.elefante"]) == {
        "livros", "dificuldade", "questoes", "tempo"}
    assert set(scoring.PESOS_PADRAO["pesos.matific"]) == {
        "atividades", "media", "estrelas"}


def test_como_funciona_le_os_pesos_da_rota_e_nao_de_constante():
    fonte = ARQUIVO_FRONT.read_text(encoding="utf-8")
    assert "pontuacao/regra" in fonte, (
        f"{MSG}: ComoFuncionaPontuacao.tsx deixou de citar a rota /pontuacao/regra "
        "como origem dos pesos")
    assert not _RE_CONSTANTE.search(fonte), f"{MSG}: constante PESOS_* voltou"
    assert not _RE_PAR.search(fonte), f"{MSG}: par [\"rótulo\", número] voltou"


def test_nenhuma_tela_espelha_os_pesos_do_motor():
    achados = []
    for caminho in _fontes_do_app():
        texto = caminho.read_text(encoding="utf-8", errors="ignore")
        if _RE_CONSTANTE.search(texto) or _RE_PAR.search(texto):
            achados.append(caminho.relative_to(RAIZ_REPO).as_posix())
    assert not achados, (
        f"{MSG}: {achados}. Leia os pesos de GET /configuracoes/pontuacao/regra "
        "(fonte única, ver tests/test_regra_pontuacao.py).")
