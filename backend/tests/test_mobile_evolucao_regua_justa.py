"""App mobile: a aba "Evolução (30d)" usa a régua JUSTA, a mesma da web.

A web (``GET /ranking-evolucao``, desde 3f214a8) e o telão chamam
``evolucao.ranking_evolucao(..., base_no_periodo=True)``: sem retrato ANTERIOR à
janela, o acumulado de vida da criança NÃO vira "evolução do período" — só quem
cresceu de verdade sobe. O pacote do app (``/sincronizacao``) chamava com o
padrão ``False`` (régua antiga): a criança cujo PRIMEIRO retrato caía dentro dos
30 dias recebia o acumulado inteiro como crescimento e ia ao topo do app com
nota 100, enquanto na web tinha 0 (revisão de integração 5,
exportacoes-notificacoes, prova 502).

Regra travada aqui: na mesma janela de 30 dias, o app dá a MESMA ordem, as
mesmas posições e as mesmas notas de evolução que a web — para a gestão e para
o professor. Dados fictícios.
"""
from datetime import datetime, timedelta, timezone

from app.models import Importacao, SnapshotMatific
from app.services import scoring
from tests.test_permissoes import _cliente_como, cenario_professor  # noqa: F401 — fixture
from tests._ano_letivo import escola_no_ano_de_hoje  # noqa: F401 — fixture


def _cenario(db, escola_completa):
    escola = escola_completa["escola"]
    primeira, segunda, _terceira = escola_completa["alunos"]
    imp = Importacao(escola_id=escola.id, plataforma="matific", tipo="seed")
    db.add(imp)
    db.flush()
    agora = datetime.now(timezone.utc).replace(tzinfo=None)
    # 1ª criança: PRIMEIRO retrato há 5 dias, com acumulado grande (de antes da
    # janela) — não há base anterior, então não é crescimento do período.
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=primeira.id, importacao_id=imp.id,
                           data_referencia=agora - timedelta(days=5),
                           atividades=120, estrelas=360, pontuacao_media=4.0))
    # 2ª criança: retrato há 60 dias e outro há 5 — cresceu de verdade na janela.
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=segunda.id, importacao_id=imp.id,
                           data_referencia=agora - timedelta(days=60),
                           atividades=10, estrelas=30, pontuacao_media=3.0))
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=segunda.id, importacao_id=imp.id,
                           data_referencia=agora - timedelta(days=5),
                           atividades=25, estrelas=75, pontuacao_media=3.5))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    return escola, primeira, segunda


def _comparar(cliente_http, base):
    web = cliente_http.get(f"{base}/ranking-evolucao", params={"dias": 30})
    app = cliente_http.get(f"{base}/sincronizacao")
    assert web.status_code == 200 and app.status_code == 200, (web.text, app.text)
    linhas_web = [(i["aluno_id"], i["posicao"], i["nota_evolucao"]) for i in web.json()]
    linhas_app = [(i["aluno_id"], i["posicao"], i["nota_evolucao"])
                  for i in app.json()["evolucao"]]
    return linhas_web, linhas_app


def test_evolucao_do_app_igual_a_da_web_para_a_gestao(cliente, db, escola_completa):
    escola, primeira, segunda = _cenario(db, escola_completa)
    linhas_web, linhas_app = _comparar(cliente, f"/api/v1/escolas/{escola.id}")
    nota_app = {aid: nota for aid, _pos, nota in linhas_app}
    nota_web = {aid: nota for aid, _pos, nota in linhas_web}

    assert nota_app.get(primeira.id, 0.0) == nota_web.get(primeira.id, 0.0), \
        "a mesma criança, a mesma janela de 30 dias, duas 'evoluções'"
    assert linhas_app[:1] == linhas_web[:1], "o 1º do app não é o 1º da web"
    assert linhas_app[0][0] == segunda.id, "quem cresceu de verdade lidera"
    assert linhas_app == linhas_web[:20]


def test_evolucao_do_app_igual_a_da_web_para_o_professor(
        cenario_professor, db, escola_completa):  # noqa: F811
    escola, _primeira, segunda = _cenario(db, escola_completa)
    linhas_web, linhas_app = _comparar(cenario_professor["professor"],
                                       f"/api/v1/escolas/{escola.id}")
    assert linhas_app == linhas_web[:20]
    assert linhas_app[0][0] == segunda.id
