"""G_ANALISE-1 — a ADOÇÃO da rede só conta as plataformas CONTRATADAS.

``alunos_com_dados`` (o numerador da adoção do cartão e dos totais, o alerta "Baixa
adoção" / "Nenhum aluno com dados", a aba Engajamento do Ranking da Rede) somava quem
tinha retrato do Elefante OU do Matific, sem olhar o contrato da rede. Uma rede que
deixou de contratar a Matemática e tem retratos antigos do Matific no banco via a escola
com 3 de 10 alunos na Leitura com 100% de adoção, em 1º no Engajamento e fora da lista
de atenção. É a regra de ``_cartoes_da_rede``: o que não foi contratado não entra em
média, ranking nem adoção.

(O corte do Matific pelo ANO letivo no mesmo numerador é decisão do dono registrada —
docs/navegacao/RODADA-2-SECRETARIA-MINHA-ESCOLA-VITRINE.md §6 — e não muda aqui.)

Redes, escolas e crianças FICTÍCIAS; números escolhidos à mão.
"""
from datetime import datetime

from app.models import Importacao, ModuloRede, SnapshotElefante, SnapshotMatific
from app.services import rede as svc
from tests.test_analise_base import nova_escola, nova_rede, turma_com_alunos

QUANDO = datetime(2026, 9, 30, 3, 0)


def _imp(db, escola, plataforma):
    imp = Importacao(escola_id=escola.id, plataforma=plataforma, tipo="seed",
                     status="concluida")
    db.add(imp)
    db.flush()
    return imp


def _ele(db, escola, aluno):
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id,
                            importacao_id=_imp(db, escola, "elefante").id,
                            data_referencia=QUANDO, livros_unicos=3, tempo_leitura_min=30,
                            questoes_tentativas=0, questoes_acertos=0, livros_por_nivel={}))


def _mat(db, escola, aluno):
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id,
                           importacao_id=_imp(db, escola, "matific").id,
                           data_referencia=QUANDO, atividades=10, estrelas=30,
                           pontuacao_media=0.0))


def _mundo_so_leitura(db, *, desligar_matematica=True):
    """Alfa: 10 crianças do 3º ano, 3 com retrato do Elefante e as outras 7 só com
    retrato do Matific (dado antigo). Beta: 10 do 3º ano, 5 com retrato do Elefante.
    (3, e não 2, na Leitura de Alfa: com 1 ou 2 a Secretaria nem vê a matéria — grupo
    pequeno — e a escola sai do Ranking da Rede dela por outro motivo.)"""
    rede = nova_rede(db, nome="Rede Inventada Só Leitura", codigo="3599951")
    if desligar_matematica:
        db.add(ModuloRede(rede_id=rede.id, modulo="matematica", ativo=False))
    alfa = nova_escola(db, rede, "EMEF Inventada Alfa", None)
    beta = nova_escola(db, rede, "EMEF Inventada Beta", None)
    criancas = turma_com_alunos(db, alfa, "3º Ano", 10)
    for crianca in criancas[:3]:
        _ele(db, alfa, crianca)
    for crianca in criancas[3:]:
        _mat(db, alfa, crianca)
    for crianca in turma_com_alunos(db, beta, "3º Ano", 10)[:5]:
        _ele(db, beta, crianca)
    db.commit()
    return rede, alfa, beta


def test_adocao_do_cartao_e_dos_totais_so_conta_o_modulo_contratado(db):
    rede, alfa, beta = _mundo_so_leitura(db)
    painel = svc.dashboard_rede(db, rede.id)
    assert painel["modulos"] == ["leitura"]
    cartoes = {c["escola_id"]: c for c in painel["escolas"]}
    a, b = cartoes[alfa.id], cartoes[beta.id]
    # Alfa: 3 de 10 com dado da Leitura (antes: 10 de 10, contando o Matific fora do plano).
    assert (a["alunos_com_dados"], a["adocao"]) == (3, 30.0)
    assert a["adocao"] == a["adocao_elefante"]
    # O peso da média geral é quem ela MEDE (REV2-REDE-1): neste mundo ninguém tem Nota
    # calculada, então a média de Alfa (0,0) é ausência e não pesa — não as 3 com dado.
    assert (a["media_geral"], a["alunos_com_dados_premiaveis"]) == (0.0, 0)
    assert (b["alunos_com_dados"], b["adocao"]) == (5, 50.0)
    # "Com dado de alguma plataforma" da rede: 8 de 20 (antes: 15 de 20 = 75%).
    assert (painel["totais"]["alunos_com_dados"], painel["totais"]["adocao"]) == (8, 40.0)


def test_engajamento_e_alerta_de_baixa_adocao_seguem_o_contrato(db):
    rede, _alfa, _beta = _mundo_so_leitura(db)
    for secretaria in (False, True):
        ranking = svc.ranking_escolas(db, rede.id, metrica="engajamento", secretaria=secretaria)
        assert [(r["nome"], r["adocao"]) for r in ranking] == [
            ("EMEF Inventada Beta", 50.0), ("EMEF Inventada Alfa", 30.0)]
    atencao = {c["nome"]: c["motivo_atencao"]
               for c in svc.dashboard_rede(db, rede.id)["atencao"]}
    assert atencao["EMEF Inventada Alfa"] == "Baixa adoção: só 30% dos alunos têm dados."


def test_escola_so_com_dado_do_modulo_fora_do_plano_nao_tem_aluno_com_dados(db):
    rede = nova_rede(db, nome="Rede Inventada Sem Matemática", codigo="3599953")
    db.add(ModuloRede(rede_id=rede.id, modulo="matematica", ativo=False))
    gama = nova_escola(db, rede, "EMEF Inventada Gama", None)
    for crianca in turma_com_alunos(db, gama, "3º Ano", 6):
        _mat(db, gama, crianca)
    db.commit()
    cartao = svc.dashboard_rede(db, rede.id)["escolas"][0]
    assert (cartao["alunos_com_dados"], cartao["adocao"]) == (0, 0.0)
    assert cartao["motivo_atencao"] == "Nenhum aluno com dados das plataformas ainda."


def test_rede_com_as_duas_plataformas_continua_contando_as_duas(db):
    """Sem módulo desligado nada muda: Alfa tem 10 de 10 com dado de alguma plataforma."""
    rede, alfa, _beta = _mundo_so_leitura(db, desligar_matematica=False)
    cartao = next(c for c in svc.dashboard_rede(db, rede.id)["escolas"]
                  if c["escola_id"] == alfa.id)
    assert (cartao["alunos_com_dados"], cartao["adocao"]) == (10, 100.0)
    assert svc._alunos_com_qualquer_dado(db, [alfa.id]) == {alfa.id: 10}
    assert svc._alunos_com_qualquer_dado(db, [alfa.id], {"leitura"}) == {alfa.id: 3}
