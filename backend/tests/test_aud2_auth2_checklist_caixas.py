"""O checklist pré-deploy das senhas derivadas manda conferir a senha de cada
administrador global em QUALQUER combinação de maiúsculas e minúsculas
(REV2-AUTH2-3, sobre o 0048d4c8).

A contagem (``senhas_derivadas --contagens``) só confere 4 caixas, mas a trava do
login recusa o nome ou o @ + "123" em qualquer uma: a conta global com a senha numa
caixa que a contagem não viu recebe o 403 depois do deploy, sem volta garantida. A
frase do §3 do PRODUCAO-ENV-E-MIGRACOES.md dizia "em caixa nenhuma" — numa pergunta
afirmativa, o contrário do que se quer (o aviso do script, ``AVISO_CAIXAS``, é uma
negação e está certo). Só leitura de arquivos do repositório.
"""
from __future__ import annotations

import re

from app.core.config import PROJECT_ROOT

_DOC = PROJECT_ROOT / "docs" / "operacao" / "PRODUCAO-ENV-E-MIGRACOES.md"


def _norm(texto: str) -> str:
    return " ".join(texto.split())


def _pergunta_aos_globais() -> str:
    texto = _norm(_DOC.read_text(encoding="utf-8"))
    achadas = re.findall(r"pergunte a cada administrador global[^.]*\.", texto)
    assert len(achadas) == 1, achadas
    return achadas[0]


def test_pergunta_aos_globais_cobre_qualquer_combinacao_de_caixa():
    pergunta = _pergunta_aos_globais()
    assert "caixa nenhuma" not in pergunta, pergunta
    assert "em qualquer combinação de maiúsculas e minúsculas" in pergunta, pergunta
    assert "se for, troque antes" in pergunta, pergunta
