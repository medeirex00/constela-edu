"""G_VIRADA-6 — rede com escolas em ANOS LETIVOS diferentes (a virada do ano).

O Admin Global troca o ano escola por escola: durante dias ou semanas a rede tem escolas em
2027 e outras ainda em 2026. Cada escola é medida no PRÓPRIO ano letivo (coorte, Notas e a
janela do Matific), e o painel, o Ranking da Rede e o Boletim comparavam as duas sem dizer
nada — a escola que acabou de virar aparecia sem dado, fora do ranking de Matemática ou atrás
das que ainda estão no ano fechado. A análise de plataformas já declarava "As escolas da rede
estão em anos letivos diferentes"; o painel e o ranking, não.

O conserto: o ano letivo de cada escola vai no cartão (``ano_letivo``) e o painel diz os anos
da rede (``anos_letivos``); o Boletim escreve o aviso. Tirar a escola de outro ano do ranking é
decisão do dono (fica como está).

Redes, escolas e crianças FICTÍCIAS.
"""
from datetime import datetime

from app.models import Importacao, SnapshotElefante, SnapshotMatific
from app.services import rede as svc
from app.services import relatorios
from tests.test_analise_base import nova_escola, nova_rede, turma_com_alunos

API = "/api/v1"


def _imp(db, escola, plataforma):
    imp = Importacao(escola_id=escola.id, plataforma=plataforma, tipo="seed",
                     status="concluida")
    db.add(imp)
    db.flush()
    return imp


def _ele(db, escola, aluno, quando):
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id,
                            importacao_id=_imp(db, escola, "elefante").id,
                            data_referencia=quando, livros_unicos=4, tempo_leitura_min=40,
                            questoes_tentativas=0, questoes_acertos=0, livros_por_nivel={}))


def _mat(db, escola, aluno, quando):
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id,
                           importacao_id=_imp(db, escola, "matific").id,
                           data_referencia=quando, atividades=10, estrelas=30,
                           pontuacao_media=0.0))


def _rede_na_virada(db, *, ano_beta=2027):
    """Alfa continua em 2026; Beta já virou para ``ano_beta`` (com a turma e o dado do ano
    novo). Cada uma com 4 crianças do 3º/4º ano, todas com dado das duas plataformas."""
    rede = nova_rede(db, nome="Rede Inventada da Virada", codigo="3599961")
    alfa = nova_escola(db, rede, "EMEF Inventada Alfa", None, ano=2026)
    beta = nova_escola(db, rede, "EMEF Inventada Beta", None, ano=ano_beta)
    for crianca in turma_com_alunos(db, alfa, "3º Ano", 4, ano=2026):
        _ele(db, alfa, crianca, datetime(2026, 11, 20, 12))
        _mat(db, alfa, crianca, datetime(2026, 11, 20, 12))
    for crianca in turma_com_alunos(db, beta, "4º Ano", 4, ano=ano_beta):
        _ele(db, beta, crianca, datetime(ano_beta, 2, 10, 12))
        _mat(db, beta, crianca, datetime(ano_beta, 2, 10, 12))
    db.commit()
    return rede, alfa, beta


def test_painel_e_ranking_dizem_o_ano_letivo_de_cada_escola(db):
    rede, alfa, beta = _rede_na_virada(db)
    painel = svc.dashboard_rede(db, rede.id)
    assert painel["anos_letivos"] == [2026, 2027]
    anos = {c["escola_id"]: c["ano_letivo"] for c in painel["escolas"]}
    assert anos == {alfa.id: 2026, beta.id: 2027}
    # O Ranking da Rede (uma LISTA: o envelope não muda) traz o ano em cada escola.
    for metrica in ("geral", "estrelas_aluno", "livros_aluno"):
        ranking = svc.ranking_escolas(db, rede.id, metrica=metrica)
        assert {r["escola_id"]: r["ano_letivo"] for r in ranking} == anos, metrica
    # A Secretaria recebe o mesmo (o ano não é dado de criança).
    painel_sec = svc.dashboard_rede(db, rede.id, secretaria=True)
    assert painel_sec["anos_letivos"] == [2026, 2027]
    assert {c["escola_id"]: c["ano_letivo"] for c in painel_sec["escolas"]} == anos


def test_rede_toda_no_mesmo_ano_tem_um_ano_so(db):
    rede, _alfa, _beta = _rede_na_virada(db, ano_beta=2026)
    painel = svc.dashboard_rede(db, rede.id)
    assert painel["anos_letivos"] == [2026]
    assert {c["ano_letivo"] for c in painel["escolas"]} == {2026}


def test_rede_sem_escola_nao_tem_ano(db):
    rede = nova_rede(db, nome="Rede Inventada Vazia", codigo="3599962")
    db.commit()
    assert svc.dashboard_rede(db, rede.id)["anos_letivos"] == []


def test_rota_do_painel_leva_os_anos_letivos(cliente_global, db):
    rede, alfa, beta = _rede_na_virada(db)
    r = cliente_global.get(f"{API}/redes/{rede.id}/dashboard")
    assert r.status_code == 200, r.text
    assert r.json()["anos_letivos"] == [2026, 2027]
    r = cliente_global.get(f"{API}/redes/{rede.id}/ranking?metrica=estrelas_aluno")
    assert r.status_code == 200, r.text
    assert {c["escola_id"]: c["ano_letivo"] for c in r.json()} == {alfa.id: 2026,
                                                                   beta.id: 2027}


def test_boletim_avisa_quando_as_escolas_estao_em_anos_diferentes(db):
    rede, _alfa, _beta = _rede_na_virada(db)
    html = relatorios._shell_boletim_rede(rede.nome, svc.dashboard_rede(db, rede.id))
    assert "anos letivos diferentes (2026, 2027)" in html
    assert "EMEF Inventada Beta" in html.split("anos letivos diferentes")[1].split("</p>")[0]


def test_boletim_de_rede_num_ano_so_nao_avisa(db):
    rede, _alfa, _beta = _rede_na_virada(db, ano_beta=2026)
    html = relatorios._shell_boletim_rede(rede.nome, svc.dashboard_rede(db, rede.id))
    assert "anos letivos diferentes" not in html
