"""Cartaz do Ranking Geral: os cartões somam SÓ quem está na tabela do cartaz.

A tabela (``linhas_ranking``) só traz quem concorre: ativo, matriculado no ano numa
turma premiável (1º ao 5º ano) e com Nota do ano. Os cartões "atividades" e "livros
lidos" somavam todo ativo matriculado — inclusive a Educação Infantil e quem ainda não
tem nota —, e o pôster dizia "43 livros lidos" ao lado de uma lista com 3. Achado
RELATORIOS-2.
"""
import inspect
import re
from datetime import datetime

from app.models import (Aluno, Importacao, Matricula, Nota, SnapshotElefante,
                        SnapshotMatific, Turma)
from app.routers import relatorios as rota_relatorios
from app.services import relatorios as svc

_RE_TILE = re.compile(
    r'<div class="tile"><div class="n">(.*?)</div><div class="r">(.*?)</div></div>')


def _snaps(db, escola_id, aluno_id, livros, atividades):
    imp = Importacao(escola_id=escola_id, plataforma="elefante", tipo="seed")
    db.add(imp)
    db.flush()
    db.add_all([
        SnapshotElefante(escola_id=escola_id, aluno_id=aluno_id, importacao_id=imp.id,
                         data_referencia=datetime(2026, 9, 30, 12, 0),
                         livros_unicos=livros, tempo_leitura_min=10 * livros),
        SnapshotMatific(escola_id=escola_id, aluno_id=aluno_id, importacao_id=imp.id,
                        data_referencia=datetime(2026, 9, 30, 12, 0),
                        atividades=atividades, estrelas=atividades),
    ])


def _cenario(db, escola_completa):
    """Ana (3º ano, com Nota): 3 livros, 7 atividades — a única linha do cartaz.
    João (3º ano, ativo, ainda sem Nota): 2 livros, 4 atividades — fora da tabela.
    Criança do Pré II (Educação Infantil, não concorre): 40 livros, 100 atividades."""
    escola = escola_completa["escola"]
    ana, joao, _sofia = escola_completa["alunos"]
    db.add(Nota(escola_id=escola.id, aluno_id=ana.id, ano_letivo=2026,
                nota_matific=50, nota_elefante=50, nota_geral=50, posicao=1,
                aferido_matematica=True, aferido_leitura=True))
    _snaps(db, escola.id, ana.id, 3, 7)
    _snaps(db, escola.id, joao.id, 2, 4)
    pre = Turma(escola_id=escola.id, nome="Pré II A", ano_escolar="Pré II",
                ano_letivo=2026)
    ei = Aluno(escola_id=escola.id, nome="Criança da Educação Infantil")
    db.add_all([pre, ei])
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=ei.id, turma_id=pre.id,
                     ano_letivo=2026))
    _snaps(db, escola.id, ei.id, 40, 100)
    db.commit()
    return escola, ana


def test_cartoes_do_cartaz_geral_somam_so_quem_esta_na_tabela(db, escola_completa):
    escola, ana = _cenario(db, escola_completa)
    _cab, linhas = svc.linhas_ranking(db, escola.id)
    assert [linha[1] for linha in linhas] == [ana.nome]

    est = svc.estatisticas_cartaz(db, escola.id)
    assert est == {"atividades": 7, "livros": 3}, (
        f"o cartaz lista 1 estudante com 3 livros/7 atividades, mas os cartões dizem {est}")
    html = svc._cartaz_documento_html(escola.nome, 2026, linhas, est)
    assert _RE_TILE.findall(html)[:3] == [("7", "atividades"), ("3", "livros lidos"),
                                          ("1", "estudantes ranqueados")]


def test_recorte_do_professor_soma_so_as_linhas_dele(db, escola_completa):
    escola, _ana = _cenario(db, escola_completa)
    turma = escola_completa["turma"]
    assert svc.estatisticas_cartaz(db, escola.id, turma_ids=[turma.id]) == {
        "atividades": 7, "livros": 3}
    assert svc.estatisticas_cartaz(db, escola.id, turma_ids=[]) == {
        "atividades": 0, "livros": 0}


def _espiar(monkeypatch) -> list[dict]:
    chamadas: list[dict] = []
    original = svc.gerar_cartaz_ranking
    assinatura = inspect.signature(original)

    def _espia(*args, **kwargs):
        chamadas.append(dict(assinatura.bind(*args, **kwargs).arguments))
        return original(*args, **kwargs)

    monkeypatch.setattr(rota_relatorios.svc, "gerar_cartaz_ranking", _espia)
    return chamadas


def test_as_duas_rotas_do_cartaz_geral_mandam_os_totais_da_tabela(cliente, db,
                                                                  escola_completa,
                                                                  monkeypatch):
    escola, _ana = _cenario(db, escola_completa)
    chamadas = _espiar(monkeypatch)
    assert cliente.get(f"/api/v1/escolas/{escola.id}/ranking/cartaz").status_code == 200
    assert cliente.get(f"/api/v1/escolas/{escola.id}/relatorios/ranking",
                       params={"formato": "pdf"}).status_code == 200
    assert len(chamadas) == 2
    for chamada in chamadas:
        assert chamada["estatisticas"] == {"atividades": 7, "livros": 3}
        assert len(chamada["linhas"]) == 1
