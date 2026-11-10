"""As mensagens de turma arquivada citam o texto que a tela Turmas MOSTRA.

Importação da Lista Piloto, cadastro, transferência e revisão de identidade
recusam turma arquivada e dizem como reativá-la. Citavam “Mostrar turmas
arquivadas e de outros anos letivos” — o nome acessível do interruptor, que não
aparece na tela. Ao lado dele está escrito “Mostrar arquivadas e de outros anos”
(``apps/web/src/pages/Turmas.tsx``), o mesmo que a tela de Revisões de identidade
já cita (``RevisoesIdentidade.test.tsx``). Dados fictícios.
"""
import pathlib
import re

import pytest

from app.models import Turma
from app.services import matriculas, turma_arquivada

TURMAS_TSX = (pathlib.Path(__file__).resolve().parents[2]
              / "apps" / "web" / "src" / "pages" / "Turmas.tsx")


def _mensagens() -> list[str]:
    turma = Turma(nome="2º Ano Z", ano_escolar="2º Ano", ano_letivo=2026, status="arquivada")
    return [
        matriculas.aviso_turma_arquivada("2º Ano Z", 3, previa=True),
        matriculas.aviso_turma_arquivada("2º Ano Z", 3),
        turma_arquivada.mensagem_turma_arquivada(turma),
    ]


@pytest.mark.parametrize("mensagem", _mensagens())
def test_mensagem_cita_o_texto_visivel_do_interruptor(mensagem):
    fonte = TURMAS_TSX.read_text(encoding="utf-8")
    citado = re.search(r"ligue “([^”]+)”", mensagem)
    assert citado, mensagem
    rotulo = citado.group(1)
    assert rotulo == "Mostrar arquivadas e de outros anos"
    # Texto que está na tela (entre tags), não só o nome acessível do interruptor.
    assert re.search(rf">\s*{re.escape(rotulo)}\s*<", fonte), rotulo
    assert "Minha Escola › Turmas" in mensagem
    assert "“Reativar”" in mensagem and '"Reativar"' in fonte
    assert "Mostrar turmas arquivadas e de outros anos letivos" not in mensagem
