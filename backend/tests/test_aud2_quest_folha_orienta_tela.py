"""Quest — a folha "SÓ DO PROFESSOR" manda o professor a uma ação que existe na tela.

A folha orientava: "Perdeu ou caiu em mãos erradas? Gere o cartão dela com
'regenerar'". Nenhuma tela do Edu oferecia isso: o painel da turma só reimprimia os
cartões da turma (mesmo código e QR), e o cartão perdido seguia entrando enquanto
ninguém chamasse a API à mão (G_QUEST-1). Agora o menu do aluno no painel da turma tem
a ação, que chama o cartão individual com ``regenerar=true``, e a folha diz o nome
dela.

Lê o PDF gerado (pdfplumber) e o código-fonte da tela; sem banco. Dados fictícios.
"""
import io
import re
import unicodedata

import pdfplumber

from app.core.config import PROJECT_ROOT
from app.quest.services import cartoes_pdf

_TELA = PROJECT_ROOT / "apps" / "web" / "src" / "pages" / "TurmaDetalhe.tsx"


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto)
                   if unicodedata.category(c) != "Mn").lower()


def _folha_do_professor() -> str:
    pdf = cartoes_pdf.gerar_cartoes_pdf(
        escola_nome="Escola Ficticia", cor="#7C6FF0", turma_nome="3o Ano A",
        cartoes=[{"nome": "Aluno Ficticio", "apelido": "Estrela Valente",
                  "codigo": "LUA-FAROL-731",
                  "qr_url": "https://quest.exemplo.test/entrar?qr=ficticio"}])
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        return " ".join((doc.pages[-1].extract_text() or "").split())


def test_folha_nomeia_a_acao_do_menu_do_aluno_que_revoga_o_cartao():
    folha = _folha_do_professor()
    trecho = folha[folha.index("Perdeu"):]
    acoes = re.findall(r"'([^']+)'", trecho)
    tela = _TELA.read_text(encoding="utf-8")
    # Rótulos de item: rotulo="..." ou rotulo={cond ? "..." : "..."}.
    rotulos = {_sem_acento(r) for r in re.findall(r'rotulo="([^"]+)"', tela)}
    for expressao in re.findall(r"rotulo=\{([^}]*)\}", tela):
        rotulos |= {_sem_acento(r) for r in re.findall(r'"([^"]+)"', expressao)}

    # A folha cita a ação pelo nome que aparece no menu do aluno...
    assert acoes, f"a folha não diz que ação usar: {trecho!r}"
    citadas_na_tela = [a for a in acoes if _sem_acento(a) in rotulos]
    assert citadas_na_tela, (
        f"a folha manda usar {acoes}, mas o menu do aluno não tem ação com esse nome "
        f"(rótulos da tela: {sorted(rotulos)})")
    # ... e essa ação revoga de fato: cartão individual com regenerar=true.
    assert re.search(r"baixarCartaoDoAluno\([^)]*,\s*true\s*\)", tela), (
        "o painel da turma não chama o cartão individual com regenerar=true")
    # O efeito continua dito na folha (o que o professor precisa saber).
    assert "codigo e QR novos" in trecho
    assert "os antigos param de entrar" in trecho
