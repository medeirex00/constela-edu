"""Quest — o cartão e a folha do professor escrevem o nome da criança como ele é (G_QUEST-6).

``_latin1`` fazia ``encode("latin-1", "replace")``: todo caractere fora do latin-1
virava '?'. O apóstrofo tipográfico (’), que o teclado do celular e do Mac põe sozinho
em Sant’Anna, Dall’Agnol e D’Ávila, saía "Ana Sant?Anna Dall?Agnol" no cartão que a
criança guarda e na tabela "SO DO PROFESSOR". O PDF já declara as fontes nativas como
WinAnsi (cp1252), que tem ’ “ ” – …; agora o texto é codificado em cp1252 e o que ainda
ficar de fora vira a letra sem o sinal (ő → o, Ł → L) antes de cair no '?'.

O PDF é lido de volta (pdfplumber). Dados fictícios.
"""
import io

import pdfplumber
import pytest

from app.quest.services import cartoes_pdf


def _textos(nome: str) -> tuple[str, str]:
    pdf = cartoes_pdf.gerar_cartoes_pdf(
        "Escola Ficticia D’Oeste", "#7C6FF0", "3o Ano A",
        [{"nome": nome, "apelido": "Estrela Valente", "codigo": "SOL-LUA-314",
          "qr_url": "https://quest.exemplo.test/entrar?qr=ficticio"}])
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        return doc.pages[0].extract_text() or "", doc.pages[-1].extract_text() or ""


def _sem_interrogacao(texto: str, *trechos: str) -> bool:
    """Nenhuma linha do nome (ou da escola) tem '?'. O roteiro da folha tem as suas
    perguntas ("Esqueceu o cartao?"), que não contam."""
    linhas = [ln for ln in texto.splitlines() if any(t in ln for t in trechos)]
    return bool(linhas) and not any("?" in ln for ln in linhas)


def test_apostrofo_tipografico_sai_no_cartao_e_na_folha():
    nome = "Ana Sant’Anna Dall’Agnol"
    cartao, folha = _textos(nome)
    assert nome in cartao, cartao
    assert nome in folha, folha
    assert "Escola Ficticia D’Oeste" in cartao
    assert _sem_interrogacao(cartao, "Ana Sant", "Escola Ficticia")
    assert _sem_interrogacao(folha, "Ana Sant", "Escola Ficticia")


@pytest.mark.parametrize("nome, impresso", [
    ("Zoë Łucja Nováková", "Zoë Lucja Nováková"),     # Ł fora do cp1252: vira L
    ("Gergő Erdoğan", "Gergo Erdogan"),                # ő e ğ: a letra sem o sinal
])
def test_letra_fora_do_cp1252_vira_a_letra_sem_o_sinal(nome, impresso):
    cartao, folha = _textos(nome)
    assert impresso in cartao, cartao
    assert impresso in folha, folha
    primeiro = impresso.split()[0]
    assert _sem_interrogacao(cartao, primeiro) and _sem_interrogacao(folha, primeiro)


def test_caractere_invisivel_nao_vira_interrogacao():
    # Espaço de largura zero (U+200B) colado junto do nome: some, sem '?'.
    cartao, folha = _textos("Bia\u200b Ficticia")
    assert "Bia Ficticia" in cartao
    assert "Bia Ficticia" in folha
    assert _sem_interrogacao(cartao, "Bia") and _sem_interrogacao(folha, "Bia")


def test_acento_digitado_a_parte_sai_junto_da_letra():
    # "José" com o acento como caractere separado (forma decomposta, NFD).
    cartao, folha = _textos("Jose\u0301 Ficticio")
    assert "José Ficticio" in cartao
    assert "José Ficticio" in folha
