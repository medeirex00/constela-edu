""""Ainda não aferidos" (GET /nao-aferidos) com o MESMO recorte do ranking.

A rota diz ter "escopo idêntico ao do ranking", mas não aplicava
`_apenas_premiaveis` e decide pelo cache `Nota.aferido_*` — que o motor não
grava para quem não concorre (as Fases da Educação Infantil). Resultado:
* a Nota congelada da Fase contava como "aferida" e o "N de M aferidos em
  Leitura" do painel não batia com o denominador do ranking de Leitura;
* a criança da Fase sem Nota aparecia em "sem nenhuma dimensão", embora tenha
  retrato das duas plataformas — o professor ia procurar dado que já existe.
Achado RANKINGS-8. Cenário fictício de `tests/test_ranking_fases_cobertura.py`.
"""
from datetime import datetime

from app.models import Importacao, SnapshotElefante, SnapshotMatific
from tests.test_ranking_fases_cobertura import _aluno, cenario  # noqa: F401

API = "/api/v1"


def _fase_nova_com_as_duas(db, cenario):  # noqa: F811
    escola = cenario["escola"]
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    nova = _aluno(db, escola, cenario["fase"], "Crianca Fase Nova Teste")
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=nova.id, importacao_id=imp.id,
                            data_referencia=datetime(2026, 10, 1), livros_unicos=4,
                            tempo_leitura_min=40, livros_por_nivel={"D": 4}))
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=nova.id, importacao_id=imp.id,
                           data_referencia=datetime(2026, 10, 1), atividades=8,
                           estrelas=20, pontuacao_media=2.5))
    db.commit()
    return nova


def test_nao_aferidos_tem_o_recorte_do_ranking(cliente, db, cenario):  # noqa: F811
    nova = _fase_nova_com_as_duas(db, cenario)
    base = f"{API}/escolas/{cenario['escola'].id}"
    na = cliente.get(f"{base}/nao-aferidos")
    assert na.status_code == 200, na.text
    na = na.json()
    citados = ({a["aluno_id"] for a in na["sem_nenhuma"]}
               | {a["aluno_id"] for d in na["dimensoes"] for a in d["alunos"]})
    # A Fase não concorre: não é "não aferida" — nem a nova, nem a da Nota antiga.
    assert nova.id not in citados, "criança com retrato das duas plataformas listada"
    assert not citados & cenario["fases"], citados & cenario["fases"]
    for dimensao in na["contratadas"]:
        ranking = cliente.get(f"{base}/ranking", params={"dimensao": dimensao}).json()
        bloco = next(d for d in na["dimensoes"] if d["dimensao"] == dimensao)
        assert ranking, dimensao
        # O "N aferidos" do painel é o denominador da lista do ranking.
        assert bloco["n_aferidos"] == ranking[0]["n_aferidos"] == len(ranking), (
            dimensao, bloco["n_aferidos"], ranking[0]["n_aferidos"], len(ranking))
        # E o "de M" é a população que concorre: aferidos + não aferidos.
        assert bloco["total"] == na["total_alunos"] == bloco["n_aferidos"] + len(bloco["alunos"])
