"""Exclusão permanente (LGPD) de uma criança que já ABSORVEU uma duplicata.

O DEFEITO (ALUNOS-8). A fusão grava no log permanente a ``foto_pre_fusao`` da ficha
absorvida (nascimento, observações, foto, nome) e as entradas antigas dessa ficha
(``aluno.criado_auto`` do stub da importação) ficam com o ``entidade_id`` DELA. A
anonimização da exclusão só olhava o nome da ficha excluída e as entradas do id
dela: sobravam no log da escola o nome abreviado, o nascimento e as observações da
criança que pediu esquecimento — e o RETENCAO-TECNICA §2.3 diz que o log fica
"sem nome".

O RA fica de fora destes testes de propósito: o docstring de
``_anonimizar_logs_do_aluno`` declara o RA como "porquê técnico" que continua
intacto, e mudar isso é decisão do dono.

Dados fictícios.
"""
import json
from datetime import date

from sqlalchemy import select

from app.models import Aluno, LogAuditoria, Matricula
from app.routers import academico
from app.services.audit import registrar

API = "/api/v1"
RA = "987650001"
OBS = "Laudo de acompanhamento ficticio XPTO"
FOTO = "https://exemplo.invalid/fotos/ana-ficticia.png"
NASC = "2017-04-09"


def _stub(db, escola, turma, admin, nome, **campos):
    """Ficha criada pela importação, com o log que a importação grava."""
    stub = Aluno(escola_id=escola.id, nome=nome, **campos)
    db.add(stub)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=stub.id, turma_id=turma.id,
                     ano_letivo=2026))
    registrar(db, "aluno.criado_auto", escola_id=escola.id, usuario_id=admin.id,
              entidade="aluno", entidade_id=stub.id,
              detalhes={"origem": nome, "turma": turma.nome,
                        "decisao": "NEW_STUDENT", "fonte": "importacao"})
    db.commit()
    return stub.id


def _fundir(cliente, escola_id, manter_id, remover_id):
    r = cliente.post(f"{API}/escolas/{escola_id}/alunos/fundir", json={
        "manter_id": manter_id, "remover_id": remover_id, "confirmacao": "FUNDIR"})
    assert r.status_code == 200, r.text


def _excluir(cliente_global, escola_id, aluno_id):
    r = cliente_global.post(f"{API}/escolas/{escola_id}/alunos/excluir-permanente",
                            json={"aluno_ids": [aluno_id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text


def _sobras(db, escola_id, marcas) -> list[tuple]:
    db.expire_all()
    achadas = []
    for log in db.execute(select(LogAuditoria).where(
            LogAuditoria.escola_id == escola_id)).scalars():
        texto = json.dumps(log.detalhes or {}, ensure_ascii=False)
        achadas += [(log.acao, log.entidade_id, m) for m in marcas if m in texto]
    return achadas


def test_esquecer_crianca_que_absorveu_duplicata(cliente, cliente_global, db, escola_completa):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    oficial_id = escola_completa["alunos"][0].id               # "Ana Beatriz Souza"
    stub_id = _stub(db, escola, turma, escola_completa["admin"], "ANA B. SOUZA",
                    data_nascimento=date(2017, 4, 9), observacoes=OBS, foto_url=FOTO,
                    ficha={"ra": RA})
    _fundir(cliente, escola.id, oficial_id, stub_id)
    _excluir(cliente_global, escola.id, oficial_id)
    assert db.get(Aluno, oficial_id) is None

    sobras = _sobras(db, escola.id, (NASC, OBS, FOTO, "ANA B. SOUZA"))
    print("DADOS DA CRIANCA ESQUECIDA QUE FICARAM NO LOG:", sobras)
    assert not sobras

    # O "quê/quando/sobre qual registro" continua: a fusão e a criação do stub
    # seguem no log, com ids e contagens.
    fusao = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "aluno.fundido")).scalars().one()
    assert fusao.detalhes["removido"]["id"] == stub_id
    assert fusao.detalhes["foto_pre_fusao"]["id"] == stub_id
    assert fusao.detalhes["foto_pre_fusao"]["contagens"] is not None
    criado = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "aluno.criado_auto")).scalars().one()
    assert criado.detalhes["decisao"] == "NEW_STUDENT"
    assert criado.detalhes["origem"] == "[removido]"


def test_esquecer_alcanca_a_cadeia_de_fusoes(cliente, cliente_global, db, escola_completa):
    """O stub que absorveu OUTRO stub antes de ser absorvido: as entradas do
    primeiro também são da criança esquecida."""
    escola, turma, admin = (escola_completa["escola"], escola_completa["turma"],
                            escola_completa["admin"])
    oficial_id = escola_completa["alunos"][0].id
    stub_id = _stub(db, escola, turma, admin, "ANA B. SOUZA")
    neto_id = _stub(db, escola, turma, admin, "BIA SOUZA FICTICIA",
                    data_nascimento=date(2017, 4, 9), observacoes=OBS)
    _fundir(cliente, escola.id, stub_id, neto_id)
    _fundir(cliente, escola.id, oficial_id, stub_id)
    _excluir(cliente_global, escola.id, oficial_id)

    sobras = _sobras(db, escola.id, (NASC, OBS, "ANA B. SOUZA", "BIA SOUZA FICTICIA"))
    print("SOBRAS NA CADEIA:", sobras)
    assert not sobras


def test_nao_toca_quem_continua(cliente, cliente_global, db, escola_completa):
    """A fusão de OUTRA criança (que fica) e a criança viva que usa um id que a
    fusão antiga liberou continuam com o log intacto."""
    escola, turma, admin = (escola_completa["escola"], escola_completa["turma"],
                            escola_completa["admin"])
    oficial_id = escola_completa["alunos"][0].id
    viva = escola_completa["alunos"][1]                        # "João Pedro Barbosa"
    viva_id = viva.id
    stub_da_viva = _stub(db, escola, turma, admin, "JOAO P. BARBOSA",
                         data_nascimento=date(2016, 2, 3), observacoes="Obs da viva")
    _fundir(cliente, escola.id, viva_id, stub_da_viva)
    # Log de fusão antiga cujo id "removido" hoje é de uma ficha VIVA (id reaproveitado):
    # ela não é a criança esquecida.
    registrar(db, "aluno.fundido", escola_id=escola.id, entidade="aluno",
              entidade_id=oficial_id,
              detalhes={"mantido": {"id": oficial_id}, "removido": {"id": viva_id,
                                                                     "nome": "X"}})
    registrar(db, "aluno.atualizado", escola_id=escola.id, entidade="aluno",
              entidade_id=viva_id, detalhes={"nome": viva.nome, "campos": ["turno"]})
    db.commit()
    _excluir(cliente_global, escola.id, oficial_id)

    db.expire_all()
    assert db.get(Aluno, viva_id) is not None
    fusao_da_viva = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "aluno.fundido",
        LogAuditoria.entidade_id == viva_id)).scalars().one()
    assert fusao_da_viva.detalhes["foto_pre_fusao"]["data_nascimento"] == "2016-02-03"
    assert fusao_da_viva.detalhes["foto_pre_fusao"]["observacoes"] == "Obs da viva"
    editada = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "aluno.atualizado")).scalars().one()
    assert editada.detalhes["nome"] == viva.nome


def test_nome_da_absorvida_que_e_parte_do_nome_de_quem_fica(
        cliente, cliente_global, db, escola_completa):
    """O stub "ANA SOUZA" era da criança esquecida, mas "Ana Souza" também é parte
    do nome de uma criança que continua: o nome dela fica intacto no log; o do
    stub cai nas entradas do próprio stub."""
    escola, turma, admin = (escola_completa["escola"], escola_completa["turma"],
                            escola_completa["admin"])
    oficial_id = escola_completa["alunos"][0].id
    viva = Aluno(escola_id=escola.id, nome="Ana Souza Lima")
    db.add(viva)
    db.flush()
    viva_id = viva.id
    registrar(db, "aluno.atualizado", escola_id=escola.id, entidade="aluno",
              entidade_id=viva_id, detalhes={"nome": "Ana Souza Lima", "campos": ["turno"]})
    db.commit()
    stub_id = _stub(db, escola, turma, admin, "ANA SOUZA")
    _fundir(cliente, escola.id, oficial_id, stub_id)
    _excluir(cliente_global, escola.id, oficial_id)

    db.expire_all()
    da_viva = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "aluno.atualizado",
        LogAuditoria.entidade_id == viva_id)).scalars().one()
    assert da_viva.detalhes["nome"] == "Ana Souza Lima"
    do_stub = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "aluno.criado_auto",
        LogAuditoria.entidade_id == stub_id)).scalars().one()
    assert do_stub.detalhes["origem"] == "[removido]"


def test_exclusao_permanente_toma_a_trava_da_escola_antes_de_ler(
        cliente_global, db, escola_completa, monkeypatch):
    """Com a trava (no-op no SQLite; no PostgreSQL serializa com fusão e coleta), a
    fusão não grava log novo da criança no meio da exclusão."""
    eid = escola_completa["escola"].id
    aluno_id = escola_completa["alunos"][0].id
    chamadas: list[int] = []
    real = academico.bloquear_escola_para_importacao

    def _espia(sessao, escola_id):
        chamadas.append(escola_id)
        return real(sessao, escola_id)

    monkeypatch.setattr(academico, "bloquear_escola_para_importacao", _espia)
    _excluir(cliente_global, eid, aluno_id)
    assert chamadas == [eid]
