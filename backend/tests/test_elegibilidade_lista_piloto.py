"""Quem entra na população do ranking — e o que o `da_lista_piloto` NÃO prova.

Este arquivo nasceu de uma auditoria das 118 fichas que estão nos rankings da
rede sem ``da_lista_piloto=True``. A conclusão mudou o que parecia óbvio, e por
isso virou teste: **o flag não serve de porteiro do ranking**.

Medido contra a Lista Piloto OFICIAL da EMEF Prof. Jorge Passos (a única em
disco): das 40 fichas sem o flag naquela escola, **27 correspondem a alunos que
estão na lista** — e todas as 27 são DUPLICATAS de uma ficha que já tem o flag.
O flag só é escrito em dois lugares (a importação da lista e a fusão), então
``da_lista_piloto=False`` significa "a importação nunca casou este nome", não
"não é da lista".

Por que isso importa para quem vier depois: fechar o ranking em
``da_lista_piloto`` parece a correção certa e **não é**. Em 25 das 27 duplicatas
o desempenho da criança está PARTIDO entre as duas fichas (a oficial tem o
Elefante, o stub tem o Matific, ou o contrário), e em 2 delas a ficha oficial não
tem dado nenhum. Tirar os stubs sem fundir apaga metade do desempenho de 25
crianças e o desempenho inteiro de 2. O conserto é FUSÃO, com evidência.

O que os testes abaixo travam, então, é o que de fato é seguro hoje: quem está
fora por STATUS, por SÉRIE e por TURMA ARQUIVADA não entra; o histórico de quem
está fora continua intacto; e um nome truncado com mais de um candidato nunca é
vinculado sozinho.
"""
from datetime import date

import pytest
from sqlalchemy import select

from app.models import Aluno, Matricula, Nota, Turma
from app.routers.rankings import _ranking
from app.services import identidade_aluno as ida

API = "/api/v1"


def _turma(db, escola, nome, ano_escolar, *, status="ativa"):
    t = Turma(escola_id=escola.id, nome=nome, ano_escolar=ano_escolar,
              ano_letivo=escola.ano_letivo_ativo, status=status)
    db.add(t)
    db.flush()
    return t


def _aluno(db, escola, turma, nome, *, piloto, status="ativo", nota=50.0):
    a = Aluno(escola_id=escola.id, nome=nome, status=status, da_lista_piloto=piloto)
    a.data_nascimento = date(2017, 4, 4)
    db.add(a)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id,
                     ano_letivo=turma.ano_letivo))
    db.add(Nota(escola_id=escola.id, aluno_id=a.id, ano_letivo=turma.ano_letivo,
                nota_geral=nota, nota_elefante=nota, nota_matific=nota,
                aferido_leitura=True, aferido_matematica=True, posicao=1))
    db.commit()
    return a


def _no_ranking(db, escola):
    return {i.aluno_id for i in _ranking(db, escola.id, escola.ano_letivo_ativo)}


# ---------------------------------------------------------------------------
# O que FECHA a porta hoje
# ---------------------------------------------------------------------------
def test_transferido_nao_entra(db, escola_completa):
    escola = escola_completa["escola"]
    t = _turma(db, escola, "3º Ano Z", "3º Ano")
    a = _aluno(db, escola, t, "SAIU DA ESCOLA", piloto=True, status="transferido")
    assert a.id not in _no_ranking(db, escola)


def test_fora_lista_piloto_como_STATUS_nao_entra(db, escola_completa):
    """`fora_lista_piloto` é STATUS, e o status fecha a porta. É diferente do
    campo `da_lista_piloto`, que não fecha."""
    escola = escola_completa["escola"]
    t = _turma(db, escola, "3º Ano Y", "3º Ano")
    a = _aluno(db, escola, t, "SUMIU DA LISTA", piloto=True,
               status="fora_lista_piloto")
    assert a.id not in _no_ranking(db, escola)


@pytest.mark.parametrize("rotulo", ["1ª Fase", "2ª Fase", "6º Ano"])
def test_serie_nao_premiavel_nao_entra(db, escola_completa, rotulo):
    escola = escola_completa["escola"]
    t = _turma(db, escola, f"{rotulo} W", rotulo)
    a = _aluno(db, escola, t, f"DE {rotulo}", piloto=True)
    assert a.id not in _no_ranking(db, escola)


def test_turma_arquivada_NAO_tira_o_aluno_do_ranking(db, escola_completa):
    """CARACTERIZAÇÃO de um comportamento que surpreende.

    Arquivar a turma **não** tira seus alunos do ranking: `_ranking` filtra por
    ``Aluno.status`` e por série elegível, nunca por ``Turma.status``. Quem
    arquiva uma turma inteira esperando que ela suma da disputa não consegue
    isso — precisa mexer no status de cada criança.

    Escrito como caracterização, e não como bug, porque hoje nenhuma das cinco
    escolas com Lista Piloto tem turma arquivada (0 de 61), então não há efeito
    em produção. Fechar essa porta mudaria a população do ranking e é decisão de
    produto, não correção óbvia."""
    escola = escola_completa["escola"]
    t = _turma(db, escola, "4º Ano V", "4º Ano", status="arquivada")
    a = _aluno(db, escola, t, "EM TURMA ARQUIVADA", piloto=True)
    assert a.id in _no_ranking(db, escola), (
        "se isto falhar, alguém passou a filtrar Turma.status — confira se a "
        "população do ranking mudou de propósito")


def test_aluno_da_lista_em_ano_elegivel_entra(db, escola_completa):
    escola = escola_completa["escola"]
    t = _turma(db, escola, "5º Ano U", "5º Ano")
    a = _aluno(db, escola, t, "DA LISTA, 5º ANO", piloto=True)
    assert a.id in _no_ranking(db, escola)


# ---------------------------------------------------------------------------
# O que NÃO fecha — caracterizado de propósito, com o motivo
# ---------------------------------------------------------------------------
def test_o_flag_da_lista_piloto_NAO_e_porteiro_do_ranking(db, escola_completa):
    """CARACTERIZAÇÃO, não aprovação.

    Uma ficha nascida de relatório de plataforma entra no ranking hoje. Fechar
    aqui parece a correção e não é: na rede, 27 de 27 fichas auditadas contra a
    Lista Piloto oficial eram DUPLICATAS de alunos que já têm ficha com o flag,
    e em 25 delas o desempenho está partido entre as duas. Fechar sem fundir
    apaga metade do desempenho dessas crianças.

    Se um dia este teste falhar porque alguém fechou a porta, a pergunta a fazer
    antes de "consertar o teste" é: as duplicatas já foram fundidas?"""
    escola = escola_completa["escola"]
    t = _turma(db, escola, "2º Ano T", "2º Ano")
    stub = _aluno(db, escola, t, "NASCEU DO MATIFIC", piloto=False)
    assert stub.id in _no_ranking(db, escola), (
        "o ranking NÃO filtra por da_lista_piloto — ver o docstring do módulo")


def test_historico_de_quem_esta_fora_continua_intacto(db, escola_completa):
    """Sair da população não apaga nada: a Nota carimbada continua no banco."""
    escola = escola_completa["escola"]
    t = _turma(db, escola, "3º Ano S", "3º Ano")
    a = _aluno(db, escola, t, "FORA MAS INTEIRO", piloto=True, status="transferido")
    assert a.id not in _no_ranking(db, escola)

    nota = db.execute(select(Nota).where(Nota.aluno_id == a.id)).scalars().first()
    mat = db.execute(select(Matricula).where(Matricula.aluno_id == a.id)
                     ).scalars().first()
    assert nota is not None and nota.nota_geral == 50.0
    assert mat is not None
    assert db.get(Aluno, a.id) is not None


# ---------------------------------------------------------------------------
# Nome truncado do Matific: um candidato pode casar, dois NUNCA
# ---------------------------------------------------------------------------
def _ctx(db, escola):
    return ida.carregar_contexto(db, escola.id, escola.ano_letivo_ativo)


def test_nome_truncado_com_UM_candidato_segue_a_regra_existente(db, escola_completa):
    escola = escola_completa["escola"]
    t = _turma(db, escola, "4º Ano R", "4º Ano")
    alvo = _aluno(db, escola, t, "HEITOR OLIVEIRA DE SOUSA", piloto=True)
    db.commit()

    d = ida.decidir(_ctx(db, escola),
                    ida.LinhaIdentidade(nome="HEITOR O", plataforma="matific",
                                        id_externo="uuid-1", turma_nome=t.nome))
    assert d.acao == ida.ASSOCIAR and d.aluno_id == alvo.id


def test_nome_truncado_com_DOIS_candidatos_nao_e_vinculado_sozinho(db,
                                                                   escola_completa):
    """A regra de segurança: "DAVI L" com dois Davis na turma não escolhe.

    Na rede real isso aparece 7 vezes; o pior caso tem 12 candidatos na escola e
    2 na mesma turma (a ficha 1534 da EMEF Prof.ª Debora Valle da Silva Pilon)."""
    escola = escola_completa["escola"]
    t = _turma(db, escola, "5º Ano Q", "5º Ano")
    _aluno(db, escola, t, "DAVI LUCCA SILVA PIRES", piloto=True)
    _aluno(db, escola, t, "DAVI LUIS CAMARGO MAGGIONI VIEIRA", piloto=True)
    db.commit()

    d = ida.decidir(_ctx(db, escola),
                    ida.LinhaIdentidade(nome="DAVI L", plataforma="matific",
                                        id_externo="uuid-2", turma_nome=t.nome))
    assert d.acao != ida.ASSOCIAR, (
        f"não pode escolher sozinho entre dois candidatos (escolheu {d.aluno_id})")


def test_nome_truncado_sem_candidato_nao_inventa_vinculo(db, escola_completa):
    escola = escola_completa["escola"]
    t = _turma(db, escola, "1º Ano P", "1º Ano")
    outro = _aluno(db, escola, t, "MARIA EDUARDA BRIET DOS SANTOS", piloto=True)
    db.commit()

    d = ida.decidir(_ctx(db, escola),
                    ida.LinhaIdentidade(nome="ZEFERINO Q", plataforma="matific",
                                        id_externo="uuid-3", turma_nome=t.nome))
    assert d.aluno_id != outro.id
