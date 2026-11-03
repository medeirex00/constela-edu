"""Resultados nunca usam retrato do Matific de OUTRO ano letivo (frente C).

O contador do Matific é DO ANO (``this-year``). O c5e78d3 já cortava o motor
(``scoring.snapshots_matific_do_ano``), as médias, o ranking por período e as
premiações. Faltavam os TOTAIS que somam o retrato "atual" sem janela de ano:

* ``atividades`` do painel da escola (``rankings.montar_dashboard``);
* estrelas/atividades da escola no painel da rede e o PER CAPITA, que é a régua
  do Ranking da Rede (``rede._totais_plataforma_por_escola``);
* cartões do cartaz (geral e da matéria);
* estatísticas do telão público;
* indicadores do resumo de turma/escola e do comparador (``evolucao``).

O Elefante NÃO recebe o corte, por DESENHO: o contador dele é vitalício (a sync
pede LIFETIME; livro lido não "zera" na virada do ano). O teste
``test_elefante_e_vitalicio_por_desenho`` trava essa regra para ela não mudar por
acidente — mudar é decisão do dono.

Cenário (dados fictícios): escola em 2026; Ana com Matific de 2026; João com
Matific de 2026 e um retrato de jan/2027 (a escola ainda não virou o ano); Sofia
só com Matific de dez/2025.
"""
from datetime import datetime

from sqlalchemy import select

from app.models import Importacao, Nota, SnapshotElefante, SnapshotMatific
from app.models.rede import Rede
from app.services import evolucao, rede as svc_rede, relatorios, scoring

API = "/api/v1"


def _imp(db, escola_id):
    imp = Importacao(escola_id=escola_id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    return imp


def _m(db, escola, imp, aluno, quando, atividades, estrelas):
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                           data_referencia=quando, atividades=atividades,
                           estrelas=estrelas, pontuacao_media=3.0))


def _cenario(db, escola_completa):
    escola = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    rede = Rede(nome="Rede Ficticia Ano")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    imp = _imp(db, escola.id)
    _m(db, escola, imp, ana, datetime(2026, 9, 1), 50, 120)
    _m(db, escola, imp, joao, datetime(2026, 10, 1), 10, 20)
    _m(db, escola, imp, joao, datetime(2027, 1, 10), 900, 4000)   # ano seguinte
    _m(db, escola, imp, sofia, datetime(2025, 12, 15), 300, 1400)  # ano anterior
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    db.commit()
    return {"escola": escola, "rede_id": rede.id, "ana": ana, "joao": joao, "sofia": sofia}


ATIVIDADES_2026 = 50 + 10
ESTRELAS_2026 = 120 + 20


def test_motor_so_afere_quem_tem_matific_do_ano(db, escola_completa):
    c = _cenario(db, escola_completa)
    notas = {n.aluno_id: n for n in db.execute(
        select(Nota).where(Nota.escola_id == c["escola"].id)).scalars()}
    assert notas[c["sofia"].id].aferido_matematica is False
    assert notas[c["joao"].id].detalhes["dimensoes"]["matematica"]["dados"]["atividades"] == 10


def test_painel_da_escola_soma_so_o_matific_do_ano(db, cliente, escola_completa):
    c = _cenario(db, escola_completa)
    d = cliente.get(f"{API}/escolas/{c['escola'].id}/dashboard").json()
    assert d["total_atividades"] == ATIVIDADES_2026


def test_painel_e_ranking_da_rede_somam_so_o_matific_do_ano(db, escola_completa):
    c = _cenario(db, escola_completa)
    painel = svc_rede.dashboard_rede(db, c["rede_id"])
    cartao = next(x for x in painel["escolas"] if x["escola_id"] == c["escola"].id)
    assert cartao["atividades"] == ATIVIDADES_2026
    assert cartao["estrelas"] == ESTRELAS_2026
    assert cartao["ativos_matific"] == 2
    # PER CAPITA (a régua do Ranking da Rede): numerador só do ano.
    assert cartao["estrelas_premiaveis"] == ESTRELAS_2026
    assert cartao["atividades_premiaveis"] == ATIVIDADES_2026


def test_cartaz_soma_so_o_matific_do_ano(db, escola_completa):
    c = _cenario(db, escola_completa)
    eid = c["escola"].id
    assert relatorios.estatisticas_cartaz(db, eid)["atividades"] == ATIVIDADES_2026
    todos = [c["ana"].id, c["joao"].id, c["sofia"].id]
    materia = relatorios.estatisticas_cartaz_materia(db, eid, "matematica", todos)
    assert materia["atividades"] == ATIVIDADES_2026
    assert materia["estrelas"] == ESTRELAS_2026


def test_telao_publico_soma_so_o_matific_do_ano(db, escola_completa):
    from app.routers import publico
    c = _cenario(db, escola_completa)
    dados = publico._dados_publicos(db, c["escola"], publico._config(db, c["escola"].id))
    assert dados["estatisticas"]["atividades"] == ATIVIDADES_2026
    assert dados["estatisticas"]["estrelas"] == ESTRELAS_2026


def test_resumo_de_turma_e_comparador_somam_so_o_matific_do_ano(db, escola_completa):
    c = _cenario(db, escola_completa)
    eid = c["escola"].id
    turma = escola_completa["turma"]
    assert evolucao.resumo_turma(db, eid, turma.id)["indicadores"]["atividades"] == ATIVIDADES_2026
    linha = next(t for t in evolucao.resumo_escola(db, eid)["turmas"]
                 if t["turma"]["id"] == turma.id)
    assert linha["indicadores"]["atividades"] == ATIVIDADES_2026
    assert evolucao._lado_aluno(db, eid, c["sofia"].id)["indicadores"]["atividades"] == 0
    assert evolucao._lado_aluno(db, eid, c["joao"].id)["indicadores"]["atividades"] == 10
    assert evolucao._lado_escola(db, eid)["indicadores"]["atividades"] == ATIVIDADES_2026


def test_ranking_por_periodo_e_premiacao_do_ano_ignoram_outro_ano(db, cliente, escola_completa):
    c = _cenario(db, escola_completa)
    eid = c["escola"].id
    ids = {i["aluno_id"] for i in cliente.get(
        f"{API}/escolas/{eid}/ranking/matematica?periodo=tudo").json()}
    assert c["sofia"].id not in ids
    premios = cliente.get(f"{API}/escolas/{eid}/premiacoes?periodo=ano_letivo&limite=50").json()
    mat = next(cat for cat in premios["categorias"] if cat["chave"] == "melhor_matematica")
    assert c["sofia"].id not in {linha["aluno_id"] for linha in mat["podio"]}
    joao = next(linha for linha in mat["podio"] if linha["aluno_id"] == c["joao"].id)
    assert joao["data_atual"].startswith("2026-10-01"), "o retrato de 2027 não fecha 2026"


def test_elefante_e_vitalicio_por_desenho(db, escola_completa):
    """REGRA DOCUMENTADA (não é defeito): o retrato do Elefante de dez/2025 é o
    estado ATUAL de quem não foi coletado em 2026 — o contador é vitalício.
    Mudar isso (diferença entre o retrato atual e o último antes do início do ano
    letivo, e Leitura.data filtrada pelo ano) é decisão do dono: muda todas as
    notas de Leitura da rede."""
    escola = escola_completa["escola"]
    sofia = escola_completa["alunos"][2]
    imp = _imp(db, escola.id)
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=sofia.id, importacao_id=imp.id,
                            data_referencia=datetime(2025, 12, 15), livros_unicos=7,
                            livros_por_nivel={"D": 7}, tempo_leitura_min=70,
                            questoes_tentativas=21, questoes_acertos=14))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    db.commit()
    nota = db.execute(select(Nota).where(Nota.aluno_id == sofia.id)).scalar_one()
    assert nota.aferido_leitura is True
    assert nota.detalhes["dimensoes"]["leitura"]["dados"]["livros_unicos"] == 7
