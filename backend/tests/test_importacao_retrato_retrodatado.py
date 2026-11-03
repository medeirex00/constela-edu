"""Relatório RETRODATADO não herda campos do retrato MAIS NOVO (revisão do achado
[10], 31/10/2026).

A tela passou a exigir a data do relatório, e importar com data no passado virou
o fluxo normal. Só que ``_importar_matific`` e ``_importar_elefante_resumo``
completavam os campos que o arquivo NÃO traz com o retrato ATUAL (o mais novo),
mesmo quando o arquivo era mais antigo: retrato de 25/10 com 300 estrelas + Excel
por turma de agosto (sem estrelas) datado de 15/08 = ponto de agosto com as 300
estrelas de outubro. ``evolucao._janela`` usa o último retrato antes do início
como base, então a evolução, os rankings e as premiações de setembro ficavam
errados para sempre.

Agora, num relatório de um dia anterior ao retrato atual do aluno, o que falta vem
do retrato que VALIA naquela data (o do mesmo dia, complementado no lugar, ou o
último antes dela). Sem nenhum, não há de onde herdar com segurança: 422, nada
gravado. Relatório do mesmo dia do retrato atual ou mais novo: o de sempre.
"""
from datetime import datetime

from sqlalchemy import func, select

from app.models import Importacao, SnapshotElefante, SnapshotMatific
from app.services import evolucao

API = "/api/v1/escolas/{}/importacoes/confirmar"
OUTUBRO = "2026-10-25T12:00:00Z"
AGOSTO = "2026-08-15T02:59:59Z"      # fim do dia 14/08 em Brasília (o que a tela manda)
JULHO = "2026-07-10T15:00:00Z"


def _snaps(db, modelo, aluno_id: int) -> list:
    db.expire_all()
    return list(db.execute(
        select(modelo).where(modelo.aluno_id == aluno_id)
        .order_by(modelo.data_referencia, modelo.id)).scalars())


def _matific(cliente, escola_id: int, aluno_id: int, dados: dict, data_referencia: str,
             tipo: str = "xlsx"):
    return cliente.post(API.format(escola_id), json={
        "plataforma": "matific", "formato": "resumo", "tipo": tipo,
        "data_referencia": data_referencia,
        "linhas": [{"nome": "Ana Beatriz Souza", "aluno_id": aluno_id, "dados": dados}]})


def _elefante(cliente, escola_id: int, aluno, dados: dict, data_referencia: str):
    return cliente.post(API.format(escola_id), json={
        "plataforma": "elefante", "formato": "resumo", "tipo": "pdf",
        "data_referencia": data_referencia,
        "linhas": [{"nome": aluno.nome, "aluno_id": aluno.id, "dados": dados}]})


def _retrato(snap) -> tuple:
    return (snap.data_referencia.date().isoformat(), snap.atividades, snap.estrelas,
            snap.pontuacao_media, snap.importacao_id)


def _n_importacoes(db, escola_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Importacao)
                     .where(Importacao.escola_id == escola_id))


def test_poc_excel_de_agosto_sem_retrato_naquela_data_e_recusado(cliente, db, escola_completa):
    """O cenário EXATO do PoC do revisor. Antes: 200 e ponto de 15/08 com (20, 300).
    Agora: não há retrato da Ana em agosto (nem antes) de onde tirar as estrelas —
    422, nenhum ponto de agosto, e o retrato de outubro intacto."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    r = _matific(cliente, escola.id, ana.id,
                 {"atividades": 50, "estrelas": 300, "pontuacao_media": 3.0}, OUTUBRO)
    assert r.status_code == 200, r.text
    (outubro,) = _snaps(db, SnapshotMatific, ana.id)
    antes = _retrato(outubro)
    n_imp = _n_importacoes(db, escola.id)

    r = _matific(cliente, escola.id, ana.id, {"atividades": 20, "pontuacao_media": 2.0}, AGOSTO)

    assert r.status_code == 422, r.text
    detalhe = r.json()["detail"]
    assert "14/08/2026" in detalhe and "estrelas" in detalhe
    assert "Nada foi gravado" in detalhe
    assert "Ana" not in detalhe                       # sem dado pessoal na mensagem
    snaps = _snaps(db, SnapshotMatific, ana.id)
    assert [_retrato(s) for s in snaps] == [antes]    # sem ponto de agosto; outubro intacto
    assert not any(s.data_referencia.month == 8 for s in snaps)
    assert _n_importacoes(db, escola.id) == n_imp     # nem a importação recusada ficou


def test_excel_de_agosto_herda_do_retrato_que_valia_em_agosto(cliente, db, escola_completa):
    """Com um retrato de julho, o Excel de agosto entra: as estrelas que ele não traz
    vêm de JULHO (o que valia em agosto), nunca de outubro. O retrato de outubro fica
    intacto, e o ganho de estrelas de setembro–outubro é medido contra julho."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    assert _matific(cliente, escola.id, ana.id,
                    {"atividades": 10, "estrelas": 100, "pontuacao_media": 2.5},
                    JULHO).status_code == 200
    assert _matific(cliente, escola.id, ana.id,
                    {"atividades": 50, "estrelas": 300, "pontuacao_media": 3.0},
                    OUTUBRO).status_code == 200
    outubro_antes = _retrato(_snaps(db, SnapshotMatific, ana.id)[-1])

    r = _matific(cliente, escola.id, ana.id, {"atividades": 20, "pontuacao_media": 2.0}, AGOSTO)

    assert r.status_code == 200, r.text
    julho, agosto, outubro = _snaps(db, SnapshotMatific, ana.id)
    assert agosto.data_referencia.date().isoformat() == "2026-08-15"
    assert (agosto.atividades, agosto.estrelas, agosto.pontuacao_media) == (20, 100, 2.0)
    assert agosto.estrelas != 300                     # nunca as estrelas de outubro
    assert _retrato(outubro) == outubro_antes         # o atual segue o de outubro
    assert (julho.atividades, julho.estrelas) == (10, 100)
    # Premiação de setembro–outubro (régua justa): a base é o ponto de agosto.
    atual, base = evolucao._janela([julho, agosto, outubro], datetime(2026, 9, 1),
                                   datetime(2026, 10, 31, 23, 59, 59), base_no_periodo=True)
    assert base is agosto and atual is outubro
    assert evolucao._delta(atual, base, "estrelas") == 200
    assert evolucao._delta(atual, base, "atividades") == 30


def test_pdf_e_excel_do_mesmo_dia_antigo_se_complementam_no_lugar(cliente, db, escola_completa):
    """O PDF de agosto traz tudo (não precisa herdar: entra mesmo sem retrato antes);
    o Excel do MESMO dia complementa esse ponto no lugar — um ponto por dia, como no
    retrato atual —, com as estrelas do PDF e as atividades do Excel."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    assert _matific(cliente, escola.id, ana.id,
                    {"atividades": 50, "estrelas": 300, "pontuacao_media": 3.0},
                    OUTUBRO).status_code == 200
    outubro_antes = _retrato(_snaps(db, SnapshotMatific, ana.id)[-1])

    r = _matific(cliente, escola.id, ana.id,
                 {"atividades": 18, "estrelas": 120, "pontuacao_media": 2.1}, AGOSTO, tipo="pdf")
    assert r.status_code == 200, r.text
    r = _matific(cliente, escola.id, ana.id, {"atividades": 20, "pontuacao_media": 2.2}, AGOSTO)
    assert r.status_code == 200, r.text

    agosto, outubro = _snaps(db, SnapshotMatific, ana.id)
    assert (agosto.atividades, agosto.estrelas, agosto.pontuacao_media) == (20, 120, 2.2)
    assert _retrato(outubro) == outubro_antes


def test_relatorio_do_mesmo_dia_ou_mais_novo_segue_herdando_do_atual(cliente, db, escola_completa):
    """Sem retrodatar, nada muda: o Excel de 28/10 herda as estrelas do retrato de
    25/10 (o atual), e o do próprio 25/10 complementa esse retrato no lugar."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    assert _matific(cliente, escola.id, ana.id,
                    {"atividades": 50, "estrelas": 300, "pontuacao_media": 3.0},
                    OUTUBRO).status_code == 200
    assert _matific(cliente, escola.id, ana.id, {"atividades": 52, "pontuacao_media": 3.1},
                    "2026-10-25T20:00:00Z").status_code == 200
    assert [(s.atividades, s.estrelas) for s in _snaps(db, SnapshotMatific, ana.id)] == [(52, 300)]

    assert _matific(cliente, escola.id, ana.id, {"atividades": 60, "pontuacao_media": 3.2},
                    "2026-10-28T12:00:00Z").status_code == 200
    assert [(s.atividades, s.estrelas) for s in _snaps(db, SnapshotMatific, ana.id)] == [
        (52, 300), (60, 300)]


def test_retrodatado_recusa_tudo_se_um_aluno_nao_tem_de_onde_herdar(cliente, db, escola_completa):
    """Numa turma, um aluno com retrato de julho e outro sem retrato antes de agosto:
    a importação inteira é recusada (nada gravado, nem para quem tinha base)."""
    escola = escola_completa["escola"]
    ana, joao = escola_completa["alunos"][:2]
    for aluno, data in ((ana, JULHO), (ana, OUTUBRO), (joao, OUTUBRO)):
        r = cliente.post(API.format(escola.id), json={
            "plataforma": "matific", "formato": "resumo", "tipo": "pdf",
            "data_referencia": data,
            "linhas": [{"nome": aluno.nome, "aluno_id": aluno.id,
                        "dados": {"atividades": 10, "estrelas": 100, "pontuacao_media": 2.0}}]})
        assert r.status_code == 200, r.text
    antes = {a.id: [_retrato(s) for s in _snaps(db, SnapshotMatific, a.id)] for a in (ana, joao)}

    r = cliente.post(API.format(escola.id), json={
        "plataforma": "matific", "formato": "resumo", "tipo": "xlsx", "data_referencia": AGOSTO,
        "linhas": [{"nome": a.nome, "aluno_id": a.id,
                    "dados": {"atividades": 5, "pontuacao_media": 1.0}} for a in (ana, joao)]})

    assert r.status_code == 422, r.text
    assert "1 aluno(s)" in r.json()["detail"]
    assert {a.id: [_retrato(s) for s in _snaps(db, SnapshotMatific, a.id)]
            for a in (ana, joao)} == antes


def test_elefante_resumo_retrodatado_herda_niveis_do_retrato_da_data(cliente, db, escola_completa):
    """O relatório da turma do Elefante não traz os livros por nível: num arquivo de
    agosto, a distribuição vem do retrato de JULHO, não do de outubro."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    julho = {"livros_unicos": 4, "livros_por_nivel": {"AA": 4}, "tempo_leitura_min": 30,
             "questoes_tentativas": 10, "questoes_acertos": 8}
    outubro = {"livros_unicos": 12, "livros_por_nivel": {"AA": 6, "BB": 6},
               "tempo_leitura_min": 90, "questoes_tentativas": 40, "questoes_acertos": 30}
    assert _elefante(cliente, escola.id, ana, julho, JULHO).status_code == 200
    assert _elefante(cliente, escola.id, ana, outubro, OUTUBRO).status_code == 200

    r = _elefante(cliente, escola.id, ana,
                  {"livros_unicos": 7, "tempo_leitura_min": 50,
                   "questoes_tentativas": 20, "questoes_acertos": 15}, AGOSTO)

    assert r.status_code == 200, r.text
    s_jul, s_ago, s_out = _snaps(db, SnapshotElefante, ana.id)
    assert s_ago.data_referencia.date().isoformat() == "2026-08-15"
    assert (s_ago.livros_unicos, s_ago.tempo_leitura_min) == (7, 50)
    assert s_ago.livros_por_nivel == {"AA": 4}            # de julho, não {"AA": 6, "BB": 6}
    assert (s_out.livros_unicos, s_out.livros_por_nivel) == (12, {"AA": 6, "BB": 6})


def test_elefante_resumo_retrodatado_sem_retrato_naquela_data_e_recusado(
        cliente, db, escola_completa):
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    assert _elefante(cliente, escola.id, ana,
                     {"livros_unicos": 12, "livros_por_nivel": {"AA": 6, "BB": 6},
                      "tempo_leitura_min": 90, "questoes_tentativas": 40,
                      "questoes_acertos": 30}, OUTUBRO).status_code == 200

    r = _elefante(cliente, escola.id, ana,
                  {"livros_unicos": 7, "tempo_leitura_min": 50,
                   "questoes_tentativas": 20, "questoes_acertos": 15}, AGOSTO)

    assert r.status_code == 422, r.text
    assert "livros por nível" in r.json()["detail"]
    snaps = _snaps(db, SnapshotElefante, ana.id)
    assert [(s.livros_unicos, s.livros_por_nivel) for s in snaps] == [(12, {"AA": 6, "BB": 6})]
