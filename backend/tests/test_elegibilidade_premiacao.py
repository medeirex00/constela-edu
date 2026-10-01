"""As premiações são do 1º ao 5º ano. As Fases da Educação Infantil não concorrem.

Decisão de produto. A Lista Piloto de uma escola que também tem EMEI traz as
turmas de Fase junto, e elas vinham disputando ranking e certificado com crianças
do Fundamental — crianças que, nessas turmas, não têm conta em plataforma
nenhuma e entram com 0,00, ocupando posições no meio da lista.

É regra de ELEGIBILIDADE, nunca de cadastro: matrícula, turma, status e histórico
ficam exatamente como estão. O que muda é quem concorre.

A armadilha que este arquivo trava: ``serie_numero("1ª Fase")`` devolve ``1``,
idêntico a ``"1º Ano"``. Um teste de faixa ``1 <= n <= 5`` admitiria a EMEI
inteira — por isso o veto por ETAPA existe e vem ANTES da faixa.
"""
from datetime import date

import pytest

from app.models import Aluno, Matricula, Nota, Turma
from app.services import elegibilidade

API = "/api/v1"


# --------------------------------------------------------------------------
# A regra, isolada
# --------------------------------------------------------------------------
@pytest.mark.parametrize("rotulo,esperado", [
    ("1º Ano", 1), ("2º Ano", 2), ("3º Ano", 3), ("4º Ano", 4), ("5º Ano", 5),
    ("1º ANO", 1), ("1 ANO", 1), ("1", 1),           # variações da rede
    ("4ºB", 4), ("1ºA", 1), ("3ºD", 3),              # com letra colada
    ("2° Ano", 2), ("5° Ano", 5),                    # grau U+00B0 em vez de U+00BA
    ("Terceiro Ano", 3),
])
def test_anos_do_fundamental_participam(rotulo, esperado):
    assert elegibilidade.ano_premiavel(rotulo) == esperado
    assert elegibilidade.participa_de_premiacao(rotulo)


@pytest.mark.parametrize("rotulo", [
    "1ª Fase", "2ª Fase", "1ª FASE", "2ª FASE", "1 FASE A", "2 Fase B",
    "Fase II", "EMEI", "Educação Infantil", "Maternal 2", "Berçário",
    "Jardim I", "Pré II", "Creche", "EJA 3º", "Etapa 1",
])
def test_etapas_de_fora_nao_participam(rotulo):
    assert elegibilidade.ano_premiavel(rotulo) is None
    assert not elegibilidade.participa_de_premiacao(rotulo)


@pytest.mark.parametrize("rotulo", ["6º Ano", "7º Ano", "9º Ano", "", None, "   "])
def test_fora_do_fundamental_i_tambem_nao_participa(rotulo):
    assert not elegibilidade.participa_de_premiacao(rotulo)


def test_a_armadilha_do_serie_numero():
    """Documenta POR QUE o helper novo existe: o antigo não distingue."""
    from app.services.dificuldade_livro import serie_numero

    assert serie_numero("1ª Fase") == serie_numero("1º Ano") == 1
    assert elegibilidade.participa_de_premiacao("1º Ano")
    assert not elegibilidade.participa_de_premiacao("1ª Fase")


def test_ano_explicito_vence_a_palavra_de_etapa():
    """Errar tirando o certificado de uma criança do Fundamental é pior do que
    errar para o outro lado, que a escola confere na lista antes de emitir."""
    assert elegibilidade.participa_de_premiacao("4º Ano - Fase 2")
    assert elegibilidade.ano_premiavel("4º Ano - Fase 2") == 4


def test_o_importador_nao_fabrica_mais_ano_a_partir_de_fase():
    """A raiz: o padrão tinha ``(?:ano)?`` OPCIONAL, então "1 FASE A" casava o
    dígito e saía como "1º Ano" — a turma entrava no banco com rótulo de
    Fundamental e nenhuma regra a jusante conseguia excluí-la."""
    from app.routers.importacoes import _ano_escolar_do_nome

    assert _ano_escolar_do_nome("1 FASE A") == "1ª Fase"
    assert _ano_escolar_do_nome("2 FASE B") == "2ª Fase"
    assert _ano_escolar_do_nome("5 ANO B MANHA ANUAL") == "5º Ano"
    assert _ano_escolar_do_nome("3 ANO C") == "3º Ano"
    assert not elegibilidade.participa_de_premiacao(_ano_escolar_do_nome("1 FASE A"))


# --------------------------------------------------------------------------
# A regra no endpoint — o backend barra, não só a tela
# --------------------------------------------------------------------------
def _turma(db, escola, nome, ano_escolar):
    t = Turma(escola_id=escola.id, nome=nome, ano_escolar=ano_escolar,
              ano_letivo=escola.ano_letivo_ativo)
    db.add(t)
    db.flush()
    return t


def _aluno(db, escola, turma, nome, *, geral=0.0, aferido=False):
    a = Aluno(escola_id=escola.id, nome=nome, status="ativo", da_lista_piloto=True)
    a.data_nascimento = date(2018, 3, 3)
    db.add(a)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id,
                     ano_letivo=turma.ano_letivo))
    db.add(Nota(escola_id=escola.id, aluno_id=a.id, ano_letivo=turma.ano_letivo,
                nota_geral=geral, nota_elefante=geral, nota_matific=geral,
                aferido_leitura=aferido, aferido_matematica=aferido, posicao=1))
    db.commit()
    return a


@pytest.mark.parametrize("rotulo", ["1ª Fase", "2ª Fase"])
def test_fase_nao_emite_nenhum_dos_tres_documentos(cliente, db, escola_completa,
                                                   rotulo):
    escola = escola_completa["escola"]
    turma = _turma(db, escola, f"{rotulo} A", rotulo)
    a = _aluno(db, escola, turma, "CRIANCA DA EMEI", geral=80.0, aferido=True)

    for query in ("", "?modelo=elefante", "?modelo=matific"):
        r = cliente.get(f"{API}/escolas/{escola.id}/certificados/{a.id}{query}")
        assert r.status_code == 409, (rotulo, query, r.status_code)
        assert "1º ao 5º ano" in r.text


@pytest.mark.parametrize("rotulo", ["1º Ano", "2º Ano", "3º Ano", "4º Ano", "5º Ano"])
def test_do_1o_ao_5o_a_arte_de_participacao_sai(cliente, db, escola_completa, rotulo):
    """DECISÃO DE PRODUTO: a arte é de PARTICIPAÇÃO. Nota 0, nenhuma atividade e
    nenhuma identidade de plataforma não impedem — ela não imprime nota nem
    posição. O que impede é não ser do Fundamental I."""
    escola = escola_completa["escola"]
    turma = _turma(db, escola, f"{rotulo} Z", rotulo)
    a = _aluno(db, escola, turma, f"SEM NADA {rotulo}", geral=0.0, aferido=False)

    for modelo in ("elefante", "matific"):
        r = cliente.get(
            f"{API}/escolas/{escola.id}/certificados/{a.id}?modelo={modelo}")
        assert r.status_code == 200, (rotulo, modelo, r.text[:200])
        assert r.content[:4] == b"%PDF"


def test_o_merito_continua_exigindo_desempenho(cliente, db, escola_completa):
    """A regra da arte NÃO afrouxou o certificado de mérito: são produtos
    diferentes. Sem desempenho aferido, o mérito segue recusando."""
    escola = escola_completa["escola"]
    turma = _turma(db, escola, "5º Ano W", "5º Ano")
    a = _aluno(db, escola, turma, "SEM DESEMPENHO", geral=0.0, aferido=False)

    r = cliente.get(f"{API}/escolas/{escola.id}/certificados/{a.id}")
    assert r.status_code == 422, r.text


def test_a_guarda_de_populacao_continua_valendo(cliente, db, escola_completa):
    """Transferido do 3º ano: ano elegível, mas fora da população ativa."""
    escola = escola_completa["escola"]
    turma = _turma(db, escola, "3º Ano Q", "3º Ano")
    a = _aluno(db, escola, turma, "SAIU DA ESCOLA", geral=70.0, aferido=True)
    a.status = "transferido"
    db.commit()

    r = cliente.get(f"{API}/escolas/{escola.id}/certificados/{a.id}?modelo=matific")
    assert r.status_code == 409
    assert "transferido" in r.text


def test_sem_matricula_o_contrato_antigo_continua(cliente, db, escola_completa):
    """Sem matrícula no ano não dá para afirmar que é fase — e o contrato antigo
    (``test_certificado_plataforma``) diz que esse aluno recebe a arte."""
    escola = escola_completa["escola"]
    a = Aluno(escola_id=escola.id, nome="SEM MATRICULA NENHUMA")
    db.add(a)
    db.commit()

    r = cliente.get(f"{API}/escolas/{escola.id}/certificados/{a.id}?modelo=elefante")
    assert r.status_code == 200, r.text[:200]


# --------------------------------------------------------------------------
# A regra no ranking e no pódio
# --------------------------------------------------------------------------
def test_fase_nao_aparece_no_ranking(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    fund = _turma(db, escola, "4º Ano K", "4º Ano")
    emei = _turma(db, escola, "1ª Fase K", "1ª Fase")
    do_fund = _aluno(db, escola, fund, "DO FUNDAMENTAL", geral=55.0, aferido=True)
    da_fase = _aluno(db, escola, emei, "DA EDUCACAO INFANTIL", geral=99.0,
                     aferido=True)

    r = cliente.get(f"{API}/escolas/{escola.id}/ranking")
    assert r.status_code == 200, r.text
    ids = {x["aluno_id"] for x in r.json()}
    assert do_fund.id in ids
    assert da_fase.id not in ids, "a Fase não concorre, nem com nota alta"


def test_fase_nao_aparece_no_painel_publico(cliente, db, escola_completa):
    """O painel PÚBLICO monta o ranking por conta própria, sem passar por
    `rankings._ranking` — e é a única superfície que qualquer pessoa abre sem
    senha. Se o corte das fases não for repetido lá, ele vira o único lugar do
    sistema ainda mostrando a Educação Infantil disputando."""
    escola = escola_completa["escola"]
    fund = _turma(db, escola, "5º Ano P", "5º Ano")
    emei = _turma(db, escola, "2ª Fase P", "2ª Fase")
    do_fund = _aluno(db, escola, fund, "APARECE NO TELAO", geral=61.0, aferido=True)
    da_fase = _aluno(db, escola, emei, "NAO APARECE NO TELAO", geral=97.0,
                     aferido=True)

    r = cliente.put(f"{API}/escolas/{escola.id}/painel-publico",
                    json={"ativo": True, "slides": ["ranking"],
                          "intervalo_s": 8, "max_posicoes": 50})
    assert r.status_code == 200, r.text
    token = r.json()["url"].rsplit("/", 1)[-1]

    painel = cliente.get(f"{API}/publico/{token}/painel")
    assert painel.status_code == 200, painel.text
    ids = {x["aluno_id"] for x in painel.json()["ranking"]}
    assert do_fund.id in ids
    assert da_fase.id not in ids, "a Fase não disputa, nem no telão sem login"


def test_turmas_premiaveis_lista_so_o_fundamental(db, escola_completa):
    escola = escola_completa["escola"]
    fund = _turma(db, escola, "2º Ano J", "2º Ano")
    emei = _turma(db, escola, "2ª Fase J", "2ª Fase")
    db.commit()

    ids = elegibilidade.turmas_premiaveis(db, escola.id, escola.ano_letivo_ativo)
    assert fund.id in ids
    assert emei.id not in ids


def test_o_motor_nao_pontua_a_fase(db, escola_completa):
    """A população do scoring é a mesma régua — sair dela é o que faz a POSIÇÃO
    ficar certa em todo lugar de uma vez."""
    from app.services import scoring

    escola = escola_completa["escola"]
    emei = _turma(db, escola, "1ª Fase M", "1ª Fase")
    da_fase = _aluno(db, escola, emei, "NAO CONCORRE", geral=0.0)
    db.commit()

    scoring.recalcular_escola(db, escola.id, commit=True)
    nota = db.execute(
        Nota.__table__.select().where(Nota.aluno_id == da_fase.id)).first()
    assert nota is None or nota.posicao is None or nota.nota_geral == 0.0
