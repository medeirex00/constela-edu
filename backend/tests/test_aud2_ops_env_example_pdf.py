"""O ``backend/.env.example`` documenta os ajustes dos PDFs (pendência DESEMPENHO-4-doc).

``app/services/relatorios.py`` lê do ambiente ``PDF_NAVEGADORES_SIMULTANEOS`` (Chromium
abertos ao mesmo tempo por processo) e ``PDF_ESPERA_POR_NAVEGADOR_S`` (espera por uma
vaga antes da reserva simples). Quem opera o servidor só as acha no código. Aqui: as
duas estão no ``.env.example``, comentadas, com o valor PADRÃO do código — descomentar
a linha como está não muda nada.
"""
import os
import re

import pytest

from app.core.config import BASE_DIR
from app.services import relatorios

EXEMPLO = BASE_DIR / ".env.example"


def _documentadas() -> dict[str, str]:
    linhas = EXEMPLO.read_text(encoding="utf-8").splitlines()
    achadas = (re.match(r"^#\s*(PDF_[A-Z_]+)=(\S+)\s*$", linha) for linha in linhas)
    return {m.group(1): m.group(2) for m in achadas if m}


@pytest.mark.parametrize("variavel, valor_no_codigo", [
    ("PDF_NAVEGADORES_SIMULTANEOS", relatorios.NAVEGADORES_SIMULTANEOS),
    ("PDF_ESPERA_POR_NAVEGADOR_S", relatorios.ESPERA_POR_NAVEGADOR_S),
])
def test_ajuste_dos_pdfs_esta_no_env_example_com_o_padrao(variavel, valor_no_codigo):
    documentadas = _documentadas()
    assert variavel in documentadas, f"{variavel} fora do {EXEMPLO.name}"
    if os.environ.get(variavel, "").strip():
        pytest.skip(f"{variavel} definida neste ambiente: o valor do código não é o padrão")
    assert float(documentadas[variavel]) == float(valor_no_codigo)
