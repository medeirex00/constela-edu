"""Paridade dos PESOS exibidos à escola com os pesos oficiais do motor.

A explicação "Como funciona?" (apps/web/src/components/ComoFuncionaPontuacao.tsx)
mostra à escola quanto cada indicador pesa na Nota de Leitura e na Nota de
Matemática. Esses números são TEXTO fixo no front; a fonte da verdade é
``scoring.PESOS_PADRAO`` (régua institucional). Se alguém mudar um lado sem o
outro, a escola passa a ler uma regra que não é a usada na conta — este teste
falha antes disso chegar à tela.

Formato esperado no front (uma linha por indicador):
    ["livros únicos", 35],
"""
import pathlib
import re

from app.services import scoring

RAIZ_REPO = pathlib.Path(__file__).resolve().parents[2]
ARQUIVO_FRONT = RAIZ_REPO / "apps" / "web" / "src" / "components" / "ComoFuncionaPontuacao.tsx"

MSG = "a explicação Como funciona? da escola ficou desatualizada"

# Rótulo exibido na tela → chave em PESOS_PADRAO (mapeamento EXPLÍCITO).
LEITURA = {
    "livros únicos": "livros",
    "dificuldade dos livros": "dificuldade",
    "questões": "questoes",
    "tempo de leitura": "tempo",
}
MATEMATICA = {
    "atividades finalizadas": "atividades",
    "pontuação média": "media",
    "estrelas": "estrelas",
}

_RE_PAR = re.compile(r'\[\s*"([^"]+)"\s*,\s*(\d+(?:\.\d+)?)\s*\]')


def _constante(fonte: str, nome: str) -> dict[str, float]:
    """Extrai ``const NOME: ... = [ ["rótulo", n], ... ];`` como {rótulo: n}."""
    bloco = re.search(rf"const\s+{nome}\s*(?::[^=]*)?=\s*\[(.*?)\]\s*;", fonte, re.DOTALL)
    assert bloco, (f"{MSG}: constante {nome} não encontrada em {ARQUIVO_FRONT} "
                   "(o formato mudou? esperado `[\"rótulo\", número],`)")
    pares = _RE_PAR.findall(bloco.group(1))
    assert pares, f"{MSG}: {nome} sem pares [\"rótulo\", número] reconhecíveis"
    rotulos = [r for r, _ in pares]
    assert len(rotulos) == len(set(rotulos)), f"{MSG}: rótulo repetido em {nome}: {rotulos}"
    return {rotulo: float(valor) for rotulo, valor in pares}


def _fonte() -> str:
    assert ARQUIVO_FRONT.is_file(), f"{MSG}: arquivo não encontrado: {ARQUIVO_FRONT}"
    return ARQUIVO_FRONT.read_text(encoding="utf-8")


def _conferir(nome: str, no_front: dict[str, float], mapa: dict[str, str],
              oficial: dict[str, float]) -> None:
    assert set(no_front) == set(mapa), (
        f"{MSG}: {nome} tem os rótulos {sorted(no_front)}, esperado {sorted(mapa)}")
    assert set(mapa.values()) == set(oficial), (
        f"{MSG}: o mapeamento de {nome} cobre {sorted(mapa.values())}, "
        f"mas o motor usa {sorted(oficial)}")
    divergentes = {
        rotulo: (no_front[rotulo], float(oficial[chave]))
        for rotulo, chave in mapa.items()
        if abs(no_front[rotulo] - float(oficial[chave])) > 1e-9
    }
    assert not divergentes, (
        f"{MSG}: {nome} diverge do motor (rótulo: (tela, motor)) {divergentes}")


def test_pesos_de_leitura_batem_com_o_motor():
    _conferir("PESOS_LEITURA", _constante(_fonte(), "PESOS_LEITURA"), LEITURA,
              scoring.PESOS_PADRAO["pesos.elefante"])


def test_pesos_de_matematica_batem_com_o_motor():
    _conferir("PESOS_MATEMATICA", _constante(_fonte(), "PESOS_MATEMATICA"), MATEMATICA,
              scoring.PESOS_PADRAO["pesos.matific"])


def test_extrator_detecta_divergencia():
    """O teste não pode passar em branco: um peso trocado na tela é pego."""
    fonte = _fonte().replace('["livros únicos", 35]', '["livros únicos", 36]')
    try:
        _conferir("PESOS_LEITURA", _constante(fonte, "PESOS_LEITURA"), LEITURA,
                  scoring.PESOS_PADRAO["pesos.elefante"])
    except AssertionError as exc:
        assert MSG in str(exc)
    else:  # pragma: no cover - só falha se o extrator ficar cego
        raise AssertionError("a divergência de peso não foi detectada")
