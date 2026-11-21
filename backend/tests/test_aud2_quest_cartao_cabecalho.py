"""Quest — cabeçalho dos cartões: data de Brasília e sem traço solto (G_QUEST-7).

1. O "gerado em" do topo da página usava ``datetime.now(timezone.utc)``: das 21h às
   23h59 de Brasília o PDF dizia que os cartões foram gerados no dia seguinte. Os
   demais PDFs usam ``agora_br()`` (app.core.tempo).
2. O cartão individual (POST /alunos/{id}/cartao) é gerado com ``turma_nome=""`` e o
   cabeçalho montava ``f"{escola} - {turma}"`` sem conferir: saía "ESCOLA -" no
   cartão e "Cartoes de acesso -  - gerado em" no topo.

O PDF é lido de volta (pdfplumber). Dados fictícios.
"""
import io
from datetime import datetime, timezone

import pdfplumber

from app.core import tempo
from app.quest.services import cartoes_pdf


class _Relogio(datetime):
    """10/11/2026 às 22:30 em Brasília = 11/11/2026 01:30 UTC."""

    @classmethod
    def now(cls, tz=None):
        momento = datetime(2026, 11, 11, 1, 30, tzinfo=timezone.utc)
        return momento if tz is None else momento.astimezone(tz)


def _linhas(turma_nome: str, com_pagina_professor: bool = True) -> list[str]:
    pdf = cartoes_pdf.gerar_cartoes_pdf(
        "Escola Ficticia", "#7C6FF0", turma_nome,
        [{"nome": "Ana Ficticia", "apelido": "Estrela Valente", "codigo": "SOL-LUA-314",
          "qr_url": "https://quest.exemplo.test/entrar?qr=ficticio"}],
        com_pagina_professor=com_pagina_professor)
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        return [ln for p in doc.pages for ln in (p.extract_text() or "").splitlines()]


def test_gerado_em_usa_a_data_de_brasilia(monkeypatch):
    monkeypatch.setattr(tempo, "datetime", _Relogio)
    monkeypatch.setattr(cartoes_pdf, "datetime", _Relogio, raising=False)
    topo = [ln for ln in _linhas("3o Ano A") if "gerado em" in ln]
    assert topo == ["Constela Quest - Cartoes de acesso - 3o Ano A - gerado em 10/11/2026"]


def test_cartao_individual_sem_turma_nao_deixa_traco_solto():
    linhas = _linhas("", com_pagina_professor=False)
    topo = [ln for ln in linhas if "Cartoes de acesso" in ln]
    assert len(topo) == 1 and topo[0].startswith("Constela Quest - Cartoes de acesso - gerado em ")
    assert "Escola Ficticia" in linhas
    assert not any(ln.rstrip().endswith(" -") or "- -" in ln for ln in linhas), linhas


def test_folha_do_professor_com_turma_continua_igual():
    linhas = _linhas("3o Ano A")
    assert "Escola Ficticia - 3o Ano A" in linhas
    assert any(ln.startswith("Escola Ficticia - 3o Ano A - códigos de acesso") for ln in linhas)
