"""Documentação do Quest × o que ``regenerar`` o cartão faz desde a revisão e97.

Desde a correção do achado 1 do módulo quest (e97), ``regenerar`` troca o código E o
QR do cartão e incrementa o ``token_version`` (``credenciais.revogar_cartao``): o
cartão antigo e toda sessão aberta com ele param de entrar. A Seção 21 e o Apêndice B
foram alinhados, mas a Seção 12 da bible (aprovada) ainda trazia, como regra
"decidida", que o código "não é rotacionado" e que a regeneração "troca só o QR"; o
``INDICE.md`` (12.32, 21.19, 21.20) e o ``docs/quest/04-integracao-edu.md`` diziam que
"o código nunca muda". Quem dá suporte lendo esses trechos diria à escola que o código
da criança continua o mesmo depois de regenerar — a orientação errada que deu origem
ao achado.

Regressão do bloqueio da revisão (afirmações antigas listadas com linha): nenhum texto
da bible ou do docs/quest afirma a semântica antiga, os trechos donos dizem a nova, e a
Seção 12 declara que a regra decidida mudou e pede a ratificação do dono.

Só leitura de arquivos do repositório.
"""
from __future__ import annotations

import re

import pytest

from app.core.config import PROJECT_ROOT

_DOCS = PROJECT_ROOT / "docs"
_BIBLE = _DOCS / "bible"
_SECAO_12 = _BIBLE / "12-seguranca-privacidade.md"
_INDICE = _BIBLE / "INDICE.md"
_INTEGRACAO = _DOCS / "quest" / "04-integracao-edu.md"

# A semântica antiga, como regra em vigor (presente), em qualquer redação vista na bible e
# no docs/quest (PT e EN). O relato no passado ("não era rotacionado", "trocava só o QR"),
# que a §15 da Seção 12 usa para pedir a ratificação, não é afirmação em vigor.
_RE_SEMANTICA_ANTIGA = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"c[óo]digo n[ãa]o (?:é|e) rotacionad",
    r"code is not rotated",
    r"troca(?:r|m|ndo)? s[óo] o QR",
    r"s[óo] o QR (?:(?:é|e) )?troca",
    r"only swaps the QR",
    r"c[óo]digo (?:\w+ ){0,2}nunca muda",
    r"code (?:\w+ ){0,2}never changes",
    r"c[óo]digo imut[áa]vel",
    r"tem o QR regenerado",
    r"has its QR regenerated",
    r"the QR is regenerated and",
    r"mant[ée]\w* o c[óo]digo (?:que a criança|decorado)",
    r"keep\w* the (?:memorized )?code",
    r"revoga\w* (?:de |o )?QR",
    r"revoke the QR",
))


def _plano(texto: str) -> str:
    """Sem negrito/itálico/crase e com espaços colapsados (a quebra de linha não esconde)."""
    return " ".join(texto.replace("**", "").replace("`", "").split())


def _afirmacoes_antigas(texto: str) -> list[str]:
    plano = _plano(texto)
    return [plano[max(0, m.start() - 70):m.end() + 30]
            for regex in _RE_SEMANTICA_ANTIGA for m in regex.finditer(plano)]


def _ler(caminho) -> str:
    return caminho.read_text(encoding="utf-8")


def _metade(texto: str, lingua: str) -> str:
    """A metade PT (antes do cabeçalho 🇬🇧) ou EN (depois) de um capítulo bilíngue."""
    pt, en = texto.split("\n## 🇬🇧 ", 1)
    return pt if lingua == "pt" else en


def _parte(texto: str, cabecalho: str) -> str:
    """O conteúdo de uma parte '### N. ...' até a próxima parte."""
    inicio = texto.index(cabecalho)
    fim = texto.find("\n### ", inicio + len(cabecalho))
    return texto[inicio:fim if fim != -1 else len(texto)]


def _linha_do_indice(numero: str) -> str:
    linhas = [ln for ln in _ler(_INDICE).splitlines() if ln.startswith(f"| {numero} |")]
    assert len(linhas) == 1, linhas
    return _plano(linhas[0])


# --- 1. Nenhum texto da bible ou do docs/quest afirma a semântica antiga ------------

def _docs_do_quest():
    return sorted([*_BIBLE.rglob("*.md"), *(_DOCS / "quest").rglob("*.md")])


@pytest.mark.parametrize("caminho", _docs_do_quest(),
                         ids=lambda p: p.relative_to(_DOCS).as_posix())
def test_nenhum_doc_diz_que_regenerar_mantem_o_codigo(caminho):
    assert _afirmacoes_antigas(_ler(caminho)) == []


def test_o_detector_pega_as_redacoes_antigas():
    """As frases que o bloqueio listou (com a quebra de linha original) são pegas."""
    antigas = [
        "risco residual aceito** (o código **não é rotacionado** — a criança o decora); "
        "a regeneração troca só o **QR**",
        "a lost card has its **QR regenerated** and sessions dropped",
        "risk** (the code is **not rotated** — the child memorizes it); regeneration "
        "only swaps the **QR**",
        "- **Lost/stolen card:** the **QR is regenerated** and sessions drop",
        "com código imutável e só o QR trocando.",
        "o código nunca muda (a criança decora), só o QR é trocado.",
        "turma); o código nunca muda (a criança decora),\n   só o QR.",
        "| 21.20 | Cartão perdido/roubado e revogação de QR |",
    ]
    for frase in antigas:
        assert _afirmacoes_antigas(frase), frase
    # O relato da regra antiga no passado (pedido de ratificação) não é afirmação em vigor.
    relato = ("dizia que o código **não era rotacionado** e que a regeneração trocava só o QR; "
              "said the code **was not rotated** and that regeneration only swapped the QR")
    assert _afirmacoes_antigas(relato) == []


# --- 2. Os trechos donos dizem a semântica nova -------------------------------------

@pytest.mark.parametrize("lingua, termos", [
    ("pt", ("código e QR", "token_version", "folha")),
    ("en", ("code and QR", "token_version", "sheet")),
])
def test_secao_12_regra_de_negocio_diz_codigo_e_qr_novos(lingua, termos):
    metade = _metade(_ler(_SECAO_12), lingua)
    cabecalho = "### 9. Regras de negócio" if lingua == "pt" else "### 9. Business rules"
    regras = _plano(_parte(metade, cabecalho))
    marca = ("Modelo de ameaça do login código-só" if lingua == "pt"
             else "Code-only login threat model")
    item = regras[regras.index(marca):]
    item = item[:item.index(" - ", 1)]          # até o próximo item da lista
    for termo in termos:
        assert termo in item, (termo, item)


@pytest.mark.parametrize("lingua, cabecalho, termos", [
    ("pt", "### 12. Casos extremos", ("código e QR novos", "folha")),
    ("en", "### 12. Edge cases", ("new code and QR", "sheet")),
])
def test_secao_12_caso_extremo_do_cartao_perdido(lingua, cabecalho, termos):
    casos = _plano(_parte(_metade(_ler(_SECAO_12), lingua), cabecalho))
    for termo in termos:
        assert termo in casos, (termo, casos)


@pytest.mark.parametrize("lingua, cabecalho, termos", [
    ("pt", "### 15. Questões em aberto", ("revisão e97", "ratific", "não era rotacionado")),
    ("en", "### 15. Open questions", ("e97 review", "ratif", "was not rotated")),
])
def test_secao_12_declara_que_a_regra_decidida_mudou(lingua, cabecalho, termos):
    """A regra 'decidida' (§9) foi substituída por força da revisão: o dono ratifica."""
    abertas = _plano(_parte(_metade(_ler(_SECAO_12), lingua), cabecalho))
    for termo in termos:
        assert termo in abertas, (termo, abertas)


@pytest.mark.parametrize("numero", ["12.32", "21.19", "21.20"])
def test_indice_diz_que_regenerar_troca_codigo_e_qr(numero):
    assert "código e QR" in _linha_do_indice(numero)


def test_integracao_edu_orienta_esquecido_e_perdido():
    texto = _plano(_ler(_INTEGRACAO))
    passo = texto[texto.index("5. Cartão"):texto.index("6. Aluno transferido")]
    assert "esquecido" in passo and "só do professor" in passo
    assert "código e QR novos" in passo
    assert "individual" in passo
