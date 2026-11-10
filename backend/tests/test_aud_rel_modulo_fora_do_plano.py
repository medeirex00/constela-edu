"""Módulo NÃO contratado não aparece nos PDFs: cartaz do Ranking Geral e Boletim da Rede.

"O que a rede não contratou não existe para ela — nem na interface, nem na API"
(``services/modulos``). O cartaz geral já tirava a coluna "Nota Matific", mas mantinha o
cartão "ATIVIDADES" (Matific) somando de qualquer forma; o Boletim da Rede tinha a coluna
fixa "Matific" com 0,0 em todas as escolas e o rodapé "Matific · Elefante · Geral".
Achado RELATORIOS-3. Sem Chromium: confere o HTML que seria impresso.
"""
import inspect
import re
from datetime import datetime

from app.models import (Importacao, ModuloRede, Nota, Rede, SnapshotElefante,
                        SnapshotMatific)
from app.routers import relatorios as rota_relatorios
from app.services import rede as svc_rede
from app.services import relatorios as svc

_RE_TILE = re.compile(
    r'<div class="tile"><div class="n">(.*?)</div><div class="r">(.*?)</div></div>')


def _rede_com(db, escola, desligado: str) -> Rede:
    rede = Rede(nome="Rede Fictícia de Um Módulo")
    db.add(rede)
    db.flush()
    db.add(ModuloRede(rede_id=rede.id, modulo=desligado, ativo=False))
    db.get(type(escola), escola.id).rede_id = rede.id
    return rede


def _dados(db, escola_completa):
    """Os três alunos concorrem (Nota); todos têm Elefante e Matific."""
    escola = escola_completa["escola"]
    imp = Importacao(escola_id=escola.id, plataforma="elefante", tipo="seed")
    db.add(imp)
    db.flush()
    for i, aluno in enumerate(escola_completa["alunos"]):
        db.add_all([
            Nota(escola_id=escola.id, aluno_id=aluno.id, ano_letivo=2026,
                 nota_matific=50.0, nota_elefante=60.0 + i, nota_geral=55.0 + i,
                 posicao=3 - i, aferido_matematica=True, aferido_leitura=True),
            SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                             data_referencia=datetime(2026, 10, 1, 12),
                             livros_unicos=5, tempo_leitura_min=50),
            SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                            data_referencia=datetime(2026, 10, 1, 12),
                            atividades=7, estrelas=20),
        ])


def _espiar(monkeypatch) -> list[dict]:
    chamadas: list[dict] = []
    original = svc.gerar_cartaz_ranking
    assinatura = inspect.signature(original)

    def _espia(*args, **kwargs):
        chamadas.append(dict(assinatura.bind(*args, **kwargs).arguments))
        return original(*args, **kwargs)

    monkeypatch.setattr(rota_relatorios.svc, "gerar_cartaz_ranking", _espia)
    return chamadas


def _documento(chamada: dict) -> str:
    return svc._cartaz_documento_html(
        chamada["escola_nome"], chamada["ano_letivo"], chamada["linhas"],
        chamada["estatisticas"], materia=chamada.get("materia"),
        cabecalho=chamada["cabecalho"], modulos=chamada.get("modulos"))


def test_cartaz_geral_de_rede_so_leitura_nao_mostra_cartao_do_matific(
        cliente, db, escola_completa, monkeypatch):
    escola = escola_completa["escola"]
    _rede_com(db, escola, "matematica")
    _dados(db, escola_completa)
    db.commit()
    chamadas = _espiar(monkeypatch)
    assert cliente.get(f"/api/v1/escolas/{escola.id}/ranking/cartaz").status_code == 200
    assert cliente.get(f"/api/v1/escolas/{escola.id}/relatorios/ranking",
                       params={"formato": "pdf"}).status_code == 200
    assert len(chamadas) == 2
    for chamada in chamadas:
        assert "Nota Matific" not in chamada["cabecalho"]
        assert "atividades" not in chamada["estatisticas"]
        html = _documento(chamada)
        tiles = _RE_TILE.findall(html)
        # Os cartões da Leitura, como no cartaz de Leitura (livros + tempo).
        assert tiles[:2] == [("15", "livros lidos"), ("2h 30min", "tempo de leitura")]
        assert "atividades" not in html.lower() and "matific" not in html.lower(), (
            "o cartão do Matific continua no cartaz")


def test_cartaz_geral_de_rede_so_matematica_nao_mostra_cartao_do_elefante(
        cliente, db, escola_completa, monkeypatch):
    escola = escola_completa["escola"]
    _rede_com(db, escola, "leitura")
    _dados(db, escola_completa)
    db.commit()
    chamadas = _espiar(monkeypatch)
    assert cliente.get(f"/api/v1/escolas/{escola.id}/ranking/cartaz").status_code == 200
    (chamada,) = chamadas
    html = _documento(chamada)
    assert _RE_TILE.findall(html)[:2] == [("21", "atividades"), ("60", "estrelas")]
    assert "livro" not in html.lower() and "elefante" not in html.lower()


def test_cartaz_geral_com_os_dois_modulos_nao_muda():
    linhas = [[1, "Ana", "3º Ano A", "3º Ano", 50.0, 60.0, 55.0]]
    est = {"atividades": 7, "livros": 5}
    for modulos in (None, {"leitura", "matematica"}):
        tiles = _RE_TILE.findall(svc._cartaz_documento_html(
            "Escola", 2026, linhas, est, modulos=modulos))
        assert tiles[:2] == [("7", "atividades"), ("5", "livros lidos")]


def _boletim(db, escola_completa, desligado: str) -> tuple[dict, str]:
    escola = escola_completa["escola"]
    rede = _rede_com(db, escola, desligado)
    _dados(db, escola_completa)
    db.commit()
    dados = svc_rede.dashboard_rede(db, rede.id)
    return dados, svc._shell_boletim_rede(rede.nome, dados)


def test_boletim_de_rede_so_leitura_nao_cita_o_matific(db, escola_completa):
    dados, html = _boletim(db, escola_completa, "matematica")
    assert "Matific" not in html and "MATIFIC" not in html, (
        "o boletim cita o módulo não contratado")
    ranking = html.split("Ranking das escolas", 1)[1].split("</table>", 1)[0]
    assert "<th>Elefante</th>" in ranking and "<th>Geral</th>" in ranking
    assert "<b>Elefante · Geral</b> (0–100)" in html
    cabecalho, linhas = svc.linhas_boletim_rede(dados)
    assert cabecalho == ["#", "Escola", "Alunos", "Adoção %", "Índice", "Elefante", "Geral"]
    assert all(len(linha) == len(cabecalho) for linha in linhas)


def test_boletim_de_rede_so_matematica_nao_cita_o_elefante(db, escola_completa):
    dados, html = _boletim(db, escola_completa, "leitura")
    assert "Elefante" not in html
    assert "<b>Matific · Geral</b> (0–100)" in html
    cabecalho, _linhas = svc.linhas_boletim_rede(dados)
    assert cabecalho == ["#", "Escola", "Alunos", "Adoção %", "Índice", "Matific", "Geral"]


def test_boletim_com_os_dois_modulos_mantem_as_colunas():
    dados = {"escolas": [{"nome": "EM Alfa", "posicao": 1, "total_alunos": 10,
                          "adocao": 90.0, "pontuacao_geral": 1000.0, "media_matific": 40.0,
                          "media_elefante": 50.0, "media_geral": 45.0}]}
    cabecalho, linhas = svc.linhas_boletim_rede(dados)
    assert cabecalho == ["#", "Escola", "Alunos", "Adoção %", "Índice", "Matific",
                         "Elefante", "Geral"]
    assert linhas[0][5:] == ["40,0", "50,0", "45,0"]
    html = svc._shell_boletim_rede("Rede", dados)
    assert "<b>Matific · Elefante · Geral</b> (0–100)" in html
