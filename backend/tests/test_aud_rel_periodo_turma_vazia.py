"""Relatório por Período de uma TURMA sem alunos ativos: o PDF e o nome do arquivo
dizem QUAL turma é pelo nome, não pelo id interno.

``_quem`` tirava o nome da turma das linhas do resultado (``por_turma``/``por_aluno``)
e, com a coorte vazia (turma nova, ou com todos transferidos/arquivados), recuava para
o ``turma_id`` — o documento, que circula sozinho, dizia "Turma: 2". O nome da turma
está no banco e não é dado de criança. Achado RELATORIOS-10. Dados INVENTADOS.
"""
from datetime import date

from app.models import Turma
from app.services import relatorios_periodo as rp
from app.services import relatorios_periodo_pdf as rpp

HOJE = date(2026, 10, 5)


def _turma_vazia(db, escola):
    vazia = Turma(escola_id=escola.id, nome="5º Ano C", ano_escolar="5º Ano", ano_letivo=2026)
    db.add(vazia)
    db.commit()
    return vazia


def test_turma_sem_alunos_sai_com_o_nome_da_turma(db, escola_completa):
    escola = escola_completa["escola"]
    vazia = _turma_vazia(db, escola)
    dados = rp.gerar(db, escola.id, preset="mes_anterior", plataformas=("elefante",),
                     escopo="turma", turma_id=vazia.id, hoje=HOJE)
    assert dados["alunos"]["considerados"] == 0
    subtitulo = rpp._subtitulo(dados)
    assert "Turma: 5º Ano C" in subtitulo, subtitulo
    assert dados["escopo"]["turma_nome"] == "5º Ano C"
    assert "5º Ano C" in rpp.montar_html(dados)
    nome = rpp.nome_arquivo(dados)
    assert "-turma-5o-ano-c-" in nome, nome
    assert f"-turma-{vazia.id}-" not in nome, nome


def test_turma_com_alunos_continua_com_o_nome_do_resultado(db, escola_completa):
    escola = escola_completa["escola"]
    turma = escola_completa["turma"]
    dados = rp.gerar(db, escola.id, preset="mes_anterior", plataformas=("elefante",),
                     escopo="turma", turma_id=turma.id, hoje=HOJE)
    assert dados["alunos"]["considerados"] > 0
    assert f"Turma: {turma.nome}" in rpp._subtitulo(dados)


def test_turma_de_outra_escola_nao_empresta_o_nome(db, escola_completa):
    """O serviço não confia no pedido: turma de outra escola não vira nome no papel
    (a rota já devolve 404 antes; isto é a segunda camada)."""
    from app.models import Escola

    escola = escola_completa["escola"]
    outra = Escola(nome="Outra Escola Ficticia", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    alheia = Turma(escola_id=outra.id, nome="9º Ano Z", ano_escolar="9º Ano", ano_letivo=2026)
    db.add(alheia)
    db.commit()
    dados = rp.gerar(db, escola.id, preset="mes_anterior", plataformas=("elefante",),
                     escopo="turma", turma_id=alheia.id, hoje=HOJE)
    assert dados["escopo"]["turma_nome"] is None
    assert "9º Ano Z" not in rpp.montar_html(dados)
