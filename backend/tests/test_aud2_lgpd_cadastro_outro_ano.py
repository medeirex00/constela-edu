"""G_VIRADA-3: depois da virada, "Cadastrar aluno" de quem já é da escola não abre
uma 2ª ficha.

``criar_aluno`` só perguntava "essa pessoa já existe?" dentro da turma de destino,
no ano ativo. Na virada a turma de 2027 está vazia: a ficha antiga (matrícula só
em 2026) nunca era candidata, mesmo com RA e nascimento idênticos. Nascia uma
ficha nova (no ranking de 2027 com 0) e a coleta seguinte gravava o dado na antiga,
fora de qualquer ranking — e o "Fundir duplicatas" não mostrava o par.

Agora o cadastro procura na escola inteira (fichas não excluídas): o mesmo RA, ou
o mesmo nome com o mesmo nascimento (sem RA divergente), e responde 409 dizendo
onde está a ficha e como matriculá-la. O "Fundir duplicatas" passa a sugerir (para
conferir) o par "ficha sem turma no ano ativo × ficha da turma com o mesmo RA ou
nome e nascimento".

Dados 100% fictícios; sem rede.
"""
from datetime import date

import pytest
from sqlalchemy import func, select

from app.models import Aluno, IdentidadeExterna, LogAuditoria, Matricula, Turma

API = "/api/v1"
RA = "900000777"


@pytest.fixture()
def virada(cliente_global, db, escola_completa):
    """A Ana tem ficha de 2026 (3º Ano A) com RA, nascimento e conta no Matific; o
    Admin Global vira o ano para 2027 e a escola cria a turma de 2027."""
    eid = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]                 # "Ana Beatriz Souza"
    ana.data_nascimento = date(2017, 2, 2)
    ana.ficha = {"ra": "900.000.777"}
    db.add(IdentidadeExterna(escola_id=eid, aluno_id=ana.id, plataforma="matific",
                             id_externo="u-ana-ficticia"))
    db.commit()
    r = cliente_global.patch(f"{API}/escolas/{eid}", json={"ano_letivo_ativo": 2027})
    assert r.status_code == 200, r.text
    t = cliente_global.post(f"{API}/escolas/{eid}/turmas", json={
        "nome": "4º Ano A", "ano_escolar": "4º Ano", "ano_letivo": 2027})
    assert t.status_code == 201, t.text
    return {"eid": eid, "ana_id": ana.id, "turma_2027": t.json()["id"],
            "cliente": cliente_global}


def _fichas(db, eid, nome):
    return db.execute(select(Aluno.id).where(Aluno.escola_id == eid, Aluno.nome == nome)
                      ).scalars().all()


def _cadastrar(v, **campos):
    corpo = {"nome": "Ana Beatriz Souza", "turma_id": v["turma_2027"], **campos}
    return v["cliente"].post(f"{API}/escolas/{v['eid']}/alunos", json=corpo)


def test_rematricula_pelo_cadastro_nao_abre_segunda_ficha(virada, db):
    r = _cadastrar(virada, data_nascimento="2017-02-02", ficha={"ra": RA})
    db.expire_all()
    fichas = _fichas(db, virada["eid"], "Ana Beatriz Souza")
    assert fichas == [virada["ana_id"]], f"2ª ficha criada para a mesma criança: {fichas}"
    assert r.status_code == 409, r.text
    texto = r.json()["detail"]
    assert "já tem ficha nesta escola" in texto
    assert "3º Ano A, 2026" in texto
    assert "Editar dados › Turma" in texto
    assert "Mostrar arquivadas e de outros anos" in texto
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "aluno.criacao_recusada")).scalars().all()
    assert [entry.entidade_id for entry in log] == [virada["ana_id"]]
    assert log[0].detalhes["motivo"] == "aluno_ja_cadastrado_na_escola"


def test_mesmo_ra_com_o_nome_digitado_diferente(virada, db):
    r = _cadastrar(virada, nome="Ana Beatriz de Souza", ficha={"ra": "900000777"})
    assert r.status_code == 409, r.text
    assert "“Ana Beatriz Souza”" in r.json()["detail"]
    assert "mesmo RA" in r.json()["detail"]


def test_mesmo_nome_e_nascimento_sem_ra(virada, db):
    r = _cadastrar(virada, data_nascimento="2017-02-02")
    assert r.status_code == 409, r.text


def test_homonimo_com_outro_nascimento_cadastra(virada, db):
    r = _cadastrar(virada, data_nascimento="2016-09-09")
    assert r.status_code == 201, r.text


def test_mesmo_nome_e_nascimento_mas_ra_diferente_e_outra_crianca(virada, db):
    r = _cadastrar(virada, data_nascimento="2017-02-02", ficha={"ra": "900000999"})
    assert r.status_code == 201, r.text


def test_so_o_nome_igual_sem_mais_nada_cadastra(virada, db):
    """Sem RA nem nascimento não há prova de ser a mesma criança (homônimo é
    legítimo): o cadastro segue, como antes."""
    r = _cadastrar(virada)
    assert r.status_code == 201, r.text


def test_ficha_excluida_nao_trava_o_cadastro(virada, db):
    db.get(Aluno, virada["ana_id"]).status = "excluido"
    db.commit()
    r = _cadastrar(virada, data_nascimento="2017-02-02", ficha={"ra": RA})
    assert r.status_code == 201, r.text


def test_ficha_arquivada_diz_a_situacao(virada, db):
    db.get(Aluno, virada["ana_id"]).status = "arquivado"
    db.commit()
    r = _cadastrar(virada, ficha={"ra": RA})
    assert r.status_code == 409, r.text
    assert "arquivado" in r.json()["detail"]
    assert "Reativar" in r.json()["detail"]


def test_ja_matriculada_em_outra_turma_do_ano(virada, db):
    eid = virada["eid"]
    outra = virada["cliente"].post(f"{API}/escolas/{eid}/turmas", json={
        "nome": "4º Ano B", "ano_escolar": "4º Ano", "ano_letivo": 2027})
    assert outra.status_code == 201, outra.text
    db.add(Matricula(escola_id=eid, aluno_id=virada["ana_id"], turma_id=outra.json()["id"],
                     ano_letivo=2027))
    db.commit()
    r = _cadastrar(virada, ficha={"ra": RA})
    assert r.status_code == 409, r.text
    texto = r.json()["detail"]
    assert "4º Ano B, 2027" in texto
    assert "Editar dados › Turma" in texto


def test_fundir_duplicatas_sugere_a_ficha_de_outro_ano(virada, db):
    """A 2ª ficha que já existe (criada antes desta correção, ou por outro
    caminho): o "Fundir duplicatas" mostra o par para conferir, e a fusão deixa
    uma ficha só, com a conta do Matific e a matrícula de 2027."""
    eid = virada["eid"]
    nova = Aluno(escola_id=eid, nome="Ana Beatriz Souza", data_nascimento=date(2017, 2, 2),
                 ficha={"ra": RA})
    db.add(nova)
    db.flush()
    db.add(Matricula(escola_id=eid, aluno_id=nova.id, turma_id=virada["turma_2027"],
                     ano_letivo=2027))
    db.commit()
    nova_id = nova.id
    cliente = virada["cliente"]
    cands = cliente.get(f"{API}/escolas/{eid}/alunos/duplicados").json()["candidatos"]
    par = [c for c in cands if {c["loser_id"], c["manter_id"]} == {nova_id, virada["ana_id"]}]
    assert len(par) == 1, cands
    assert par[0]["confianca"] == "revisar"
    assert par[0]["motivo"] == "outro_ano"
    assert par[0]["manter_id"] == virada["ana_id"]          # a mais antiga (com a conta)
    assert par[0]["turma"] == "4º Ano A"

    r = cliente.post(f"{API}/escolas/{eid}/alunos/duplicados/corrigir",
                     json={"loser_ids": [nova_id], "confirmacao": "FUNDIR"})
    assert r.status_code == 200 and r.json()["fundidos"] == 1, r.text
    db.expire_all()
    assert _fichas(db, eid, "Ana Beatriz Souza") == [virada["ana_id"]]
    anos = dict(db.execute(select(Matricula.ano_letivo, Turma.nome)
                           .join(Turma, Turma.id == Matricula.turma_id)
                           .where(Matricula.aluno_id == virada["ana_id"])).all())
    assert anos == {2026: "3º Ano A", 2027: "4º Ano A"}
    assert db.execute(select(func.count()).select_from(IdentidadeExterna).where(
        IdentidadeExterna.aluno_id == virada["ana_id"])).scalar_one() == 1


def test_dedup_nao_sugere_outro_ano_com_nascimento_diferente(virada, db):
    eid = virada["eid"]
    nova = Aluno(escola_id=eid, nome="Ana Beatriz Souza", data_nascimento=date(2016, 9, 9))
    db.add(nova)
    db.flush()
    db.add(Matricula(escola_id=eid, aluno_id=nova.id, turma_id=virada["turma_2027"],
                     ano_letivo=2027))
    db.commit()
    cands = virada["cliente"].get(f"{API}/escolas/{eid}/alunos/duplicados").json()["candidatos"]
    assert not [c for c in cands if nova.id in (c["loser_id"], c["manter_id"])]
