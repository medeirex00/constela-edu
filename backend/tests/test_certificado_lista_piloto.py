"""Certificado não sai para ficha que a Lista Piloto nunca confirmou.

Descoberto no gate da cerimônia do 3º bimestre de 2026, horas antes da entrega.
Uma sincronização do Elefante criou duas fichas naquela manhã — 2351 LEONARDO
MEZURARO MIGLIORI (EMEI/EMEF Benedito Inácio Soares) e 2352 ADRYEL LUCAS DA S J
(EMEI/EMEF Prof. Bernardo Ferreira Louzada) — pelo passo 5 de
``identidade_aluno.decidir``: nenhum candidato plausível em lugar nenhum, e a sala
do relatório casava com uma turma cadastrada, então a ficha nasceu. Ela nasce com
``escola_id`` e ``nome`` e mais nada (``routers/importacoes.py``), portanto sem RA,
sem data de nascimento e com ``da_lista_piloto=False``.

As duas passavam nas TRÊS guardas que a rota já tinha — ativas, em turma de 1º a 5º
ano, com nota > 0 — e emitiriam certificado com um clique. Na rede havia 120 fichas
nessa condição. Não existe emissão em lote no produto (a rota é um aluno por vez),
mas o seletor da tela de Relatórios lista todo aluno ativo de série elegível, sem
olhar o campo, então "automático" aqui é o clique no nome errado.

Por que o conserto é no CERTIFICADO e não na população do ranking: fechar o ranking
em ``da_lista_piloto`` apagaria metade do desempenho de 25 crianças cujo dado está
partido entre a ficha oficial e o stub — está medido e documentado em
``test_elegibilidade_lista_piloto``. O ranking segue aberto de propósito; o que não
pode sair sozinho é o documento com brasão. O custo do erro é assimétrico: deixar
de emitir é um clique a mais; emitir errado é um documento oficial no nome de
alguém que talvez não exista.

A confirmação humana usa caminho que já existia: importar a Lista Piloto (casa o
nome e carimba o campo) ou fundir a duplicata em Alunos › Duplicatas.
"""
from datetime import date

from app.models import Aluno, Matricula, Nota, Turma

API = "/api/v1"


def _turma(db, escola, nome="3º Ano Z", ano_escolar="3º Ano"):
    t = Turma(escola_id=escola.id, nome=nome, ano_escolar=ano_escolar,
              ano_letivo=escola.ano_letivo_ativo, status="ativa")
    db.add(t)
    db.flush()
    return t


def _aluno(db, escola, turma, nome, *, piloto, status="ativo", nota=72.5):
    a = Aluno(escola_id=escola.id, nome=nome, status=status, da_lista_piloto=piloto)
    a.data_nascimento = date(2017, 5, 5)
    db.add(a)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id,
                     ano_letivo=turma.ano_letivo))
    if nota is not None:
        db.add(Nota(escola_id=escola.id, aluno_id=a.id, ano_letivo=turma.ano_letivo,
                    nota_geral=nota, nota_elefante=nota, nota_matific=nota,
                    aferido_leitura=True, aferido_matematica=True, posicao=1))
    db.commit()
    return a


def _emitir(cliente, escola, aluno, modelo=None):
    url = f"{API}/escolas/{escola.id}/certificados/{aluno.id}"
    if modelo:
        url += f"?modelo={modelo}"
    return cliente.get(url)


# ---------------------------------------------------------------------------
# A guarda nova
# ---------------------------------------------------------------------------
def test_ficha_fora_da_lista_piloto_nao_recebe_certificado(cliente, db,
                                                           escola_completa):
    """O caso real das fichas 2351 e 2352: ativas, série elegível, nota > 0."""
    escola = escola_completa["escola"]
    t = _turma(db, escola)
    a = _aluno(db, escola, t, "LEONARDO NASCEU DO RELATORIO", piloto=False)

    r = _emitir(cliente, escola, a)
    assert r.status_code == 409, r.text
    assert "Lista Piloto" in r.json()["detail"]


def test_a_guarda_vale_para_as_DUAS_artes_de_plataforma(cliente, db,
                                                        escola_completa):
    """As artes de participação não passam pela guarda de nota, de propósito —
    mas passam por esta. Senão o bloqueio do Mérito seria contornável trocando o
    parâmetro ``modelo`` na URL."""
    escola = escola_completa["escola"]
    t = _turma(db, escola, "4º Ano Y", "4º Ano")
    a = _aluno(db, escola, t, "ADRYEL SEM FICHA OFICIAL", piloto=False, nota=None)

    for modelo in ("elefante", "matific"):
        r = _emitir(cliente, escola, a, modelo)
        assert r.status_code == 409, f"{modelo}: {r.text}"
        assert "Lista Piloto" in r.json()["detail"]


def test_a_mensagem_diz_o_que_fazer(cliente, db, escola_completa):
    """Quem recebe o 409 precisa saber o caminho, não só o impedimento."""
    escola = escola_completa["escola"]
    t = _turma(db, escola, "5º Ano W", "5º Ano")
    a = _aluno(db, escola, t, "STUB COM NOTA", piloto=False)

    detalhe = _emitir(cliente, escola, a).json()["detail"]
    assert "Lista Piloto" in detalhe
    assert "Duplicatas" in detalhe        # o outro caminho: fundir
    assert "STUB COM NOTA" in detalhe     # nomeia a criança


# ---------------------------------------------------------------------------
# O que NÃO pode ter mudado
# ---------------------------------------------------------------------------
def test_ficha_confirmada_continua_emitindo(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    t = _turma(db, escola, "2º Ano V", "2º Ano")
    a = _aluno(db, escola, t, "ANA DA LISTA PILOTO", piloto=True)

    r = _emitir(cliente, escola, a)
    assert r.status_code == 200, r.text
    assert r.content[:4] == b"%PDF"


def test_confirmada_emite_as_tres_artes(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    t = _turma(db, escola, "1º Ano U", "1º Ano")
    a = _aluno(db, escola, t, "PEDRO DA LISTA", piloto=True)

    for modelo in (None, "elefante", "matific"):
        r = _emitir(cliente, escola, a, modelo)
        assert r.status_code == 200, f"{modelo}: {r.text}"
        assert r.content[:4] == b"%PDF"


def test_a_ordem_das_guardas_nao_mudou_transferido_ainda_da_409(cliente, db,
                                                                escola_completa):
    """Transferido COM o flag continua bloqueado pela guarda de população — a
    guarda nova não substituiu nenhuma das antigas."""
    escola = escola_completa["escola"]
    t = _turma(db, escola, "3º Ano T", "3º Ano")
    a = _aluno(db, escola, t, "SAIU DA ESCOLA", piloto=True, status="transferido")

    r = _emitir(cliente, escola, a)
    assert r.status_code == 409
    assert "situação" in r.json()["detail"]      # mensagem da guarda de status


def test_fase_com_flag_ainda_da_409_pela_serie(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    t = _turma(db, escola, "1ª Fase S", "1ª Fase")
    a = _aluno(db, escola, t, "CRIANCA DA FASE", piloto=True)

    r = _emitir(cliente, escola, a)
    assert r.status_code == 409
    assert "1º ao 5º ano" in r.json()["detail"]  # mensagem da guarda de série


def test_sem_desempenho_com_flag_ainda_da_422(cliente, db, escola_completa):
    """A guarda de mérito do Mérito continua existindo e vem DEPOIS desta."""
    escola = escola_completa["escola"]
    t = _turma(db, escola, "4º Ano R", "4º Ano")
    a = _aluno(db, escola, t, "SEM NOTA NENHUMA", piloto=True, nota=0.0)

    r = _emitir(cliente, escola, a)
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# Nada de ranking/pontuação mudou
# ---------------------------------------------------------------------------
def test_a_guarda_nao_mexe_no_ranking_nem_na_nota(cliente, db, escola_completa):
    """A ficha sem flag continua na população do ranking e com a nota intacta —
    esta mudança é só sobre EMITIR documento, não sobre quem concorre."""
    from app.routers.rankings import _ranking

    escola = escola_completa["escola"]
    t = _turma(db, escola, "5º Ano Q", "5º Ano")
    stub = _aluno(db, escola, t, "STUB QUE CONCORRE", piloto=False, nota=88.0)

    antes = {i.aluno_id: round(i.nota_geral or 0, 4)
             for i in _ranking(db, escola.id, escola.ano_letivo_ativo)}
    assert stub.id in antes, "a ficha sem flag tem de continuar no ranking"
    assert antes[stub.id] == 88.0

    r = _emitir(cliente, escola, stub)
    assert r.status_code == 409

    depois = {i.aluno_id: round(i.nota_geral or 0, 4)
              for i in _ranking(db, escola.id, escola.ano_letivo_ativo)}
    assert depois == antes, "tentar emitir não pode alterar ranking nem nota"
