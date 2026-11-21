"""A recusa de "Corrigir turmas duplicadas" aponta um caminho que existe na tela
(REV2-LGPD-2, sobre G_MODULOS-8).

O DEFEITO. O 409 (e o aviso do grupo na prévia, que a tela Turmas mostra como veio)
mandava o Admin Global a "Configurações › Pontuação por turma". Esse caminho não
existe: o editor da pontuação por nível de cada turma (``PontuacaoPorTurma``) fica em
Critérios (/metricas) › Elefante Letrado › Dificuldade por turma; Configurações
(/configuracoes) não o mostra.

O teste lê o caminho entre parênteses do texto e confere cada passo no código da
web: o 1º é um item do menu (``Layout.tsx``) que leva a /metricas, e os demais são
abas da página de /metricas, que mostra o editor. Dados fictícios.
"""
import pathlib
import re

from tests.test_aud2_lgpd_turmas_pontuacao import _consolidar, _pontuar, cena  # noqa: F401

WEB = pathlib.Path(__file__).resolve().parents[2] / "apps" / "web" / "src"
LAYOUT_TSX = WEB / "components" / "Layout.tsx"
METRICAS_TSX = WEB / "pages" / "configuracoes" / "Metricas.tsx"


def _caminho_da_recusa(texto: str) -> list[str]:
    achado = re.search(r"\(([^()]*›[^()]*)\)", texto)
    assert achado, f"a recusa não diz onde resolver: {texto}"
    return [passo.strip() for passo in achado.group(1).split("›")]


def test_a_recusa_aponta_o_caminho_real_do_editor_da_pontuacao_por_turma(
        db, cena, cliente, cliente_global):  # noqa: F811
    _pontuar(cliente_global, cena, cena["dup"], {"D": 10})
    r = _consolidar(cliente, cena)
    assert r.status_code == 409, r.text
    passos = _caminho_da_recusa(r.json()["detail"])
    print("CAMINHO DA RECUSA:", passos)

    layout = LAYOUT_TSX.read_text(encoding="utf-8")
    menu = re.search(rf'rotulo: "{re.escape(passos[0])}", caminho: "([^"]+)"', layout)
    assert menu, f"o menu não tem o item “{passos[0]}”"
    assert menu.group(1) == "/metricas", (
        f"“{passos[0]}” leva a {menu.group(1)}, que não mostra a pontuação por turma")

    metricas = METRICAS_TSX.read_text(encoding="utf-8")
    assert "<PontuacaoPorTurma" in metricas
    for aba in passos[1:]:
        assert f'rotulo: "{aba}"' in metricas, f"a página /metricas não tem a aba “{aba}”"
    assert passos == ["Critérios", "Elefante Letrado", "Dificuldade por turma"]
