"""D10 na RESTAURAÇÃO do backup da escola — 2ª revisão de integração do e97
(identidade-sync, prova 5; dados-config, prova 1 teste 3 — invertidas).

``POST /escolas/{id}/restaurar`` (só o Admin Global) recria as fichas com o status
do arquivo e as identidades delas. Uma ficha excluída DEPOIS do backup, cuja conta
outra escola vinculou nesse meio-tempo, volta a valer aqui e a conta fica efetiva
nas DUAS escolas. Antes não saía aviso nem auditoria própria (só
``backup.restaurado``). Agora a rota segue (é a decisão do Admin Global), com a
auditoria ``aluno.reativacao_outra_escola_confirmada`` por conta (ação
``restaurar_backup``; sem nome) e ``avisos: [AVISO_CONTA_DE_OUTRA_ESCOLA]`` na
resposta — lista vazia nos demais casos.

Dados 100% fictícios (nomes de escola e de criança inventados); sem rede.
"""
import json

from sqlalchemy import select

from app.models import Aluno, IdentidadeExterna, RevisaoIdentidade
from app.models.nota import LogAuditoria
from app.services import backup as svc_backup
from app.services import identidade_aluno as ida

API = "/api/v1"
U = "u-ficticia-restauracao-d10"
K = "3 ANO A (300396804)"
AUD = "aluno.reativacao_outra_escola_confirmada"
NOME_B = "Crianca Ficticia B Da Restauracao"


def _nova_escola(db):
    from tests.test_sync_escola_cruzada import _nova_escola as nova

    return nova(db, nome="ESCOLA FICTICIA B DA RESTAURACAO", com_alunos=(NOME_B,))


def _copia(db, eid):
    db.expire_all()      # o export lê pela sessão do teste: nada de status em cache
    return json.dumps(svc_backup.exportar(db, eid), default=str).encode("utf-8")


def _restaurar(cliente_global, eid, copia):
    return cliente_global.post(f"{API}/escolas/{eid}/restaurar",
                               files={"arquivo": ("b.json", copia, "application/json")})


def _auditoria(db, acao):
    db.expire_all()
    return [a for a in db.execute(select(LogAuditoria).order_by(LogAuditoria.id)).scalars()
            if a.acao == acao]


def _vincular(db, escola_id, aluno_id, status="efetiva"):
    db.add(IdentidadeExterna(escola_id=escola_id, aluno_id=aluno_id, plataforma="matific",
                             id_externo=U, status=status))
    db.commit()


def _cena(db, escola_completa, cliente):
    """Backup de A com a ficha X (conta U); depois a gestão de A exclui X e B
    vincula U à ficha Y dela (legítimo). Devolve (e1, x, e2, y, copia)."""
    e1 = escola_completa["escola"].id
    x = escola_completa["alunos"][0]
    _vincular(db, e1, x.id)
    copia = _copia(db, e1)
    assert cliente.post(f"{API}/escolas/{e1}/alunos/acoes",
                        json={"aluno_ids": [x.id], "acao": "excluir"}).status_code == 200
    escola_b, _t, (y,) = _nova_escola(db)
    _vincular(db, escola_b.id, y.id)
    db.expire_all()
    assert ida.efetivas_em_outra_escola(db, escola_b.id, "matific", [U]) == {}
    return e1, x, escola_b.id, y, copia


def test_restaurar_avisa_e_audita_a_conta_que_passa_a_valer_nas_duas(
        db, escola_completa, cliente, cliente_global):
    e1, x, e2, y, copia = _cena(db, escola_completa, cliente)
    nome_x, y_id = x.nome, y.id          # a restauração apaga e recria as fichas de A
    r = _restaurar(cliente_global, e1, copia)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["avisos"] == [ida.AVISO_CONTA_DE_OUTRA_ESCOLA]
    db.expire_all()
    # A restauração segue (decisão do Admin Global): a conta vale nas duas.
    assert ida.efetivas_em_outra_escola(db, e2, "matific", [U]) == {U: e1}
    restaurada = db.execute(select(Aluno).where(Aluno.escola_id == e1,
                                                Aluno.nome == nome_x)).scalar_one()
    assert restaurada.status == "ativo"
    [aud] = _auditoria(db, AUD)
    assert (aud.escola_id, aud.entidade, aud.entidade_id) == (e1, "aluno", restaurada.id)
    assert aud.usuario_id is not None
    assert aud.detalhes["acao"] == "restaurar_backup"
    assert (aud.detalhes["plataforma"], aud.detalhes["id_externo"]) == ("matific", U)
    assert aud.detalhes["outra_escola_id"] == e2
    assert nome_x not in str(aud.detalhes) and NOME_B not in str(aud.detalhes)
    assert len(_auditoria(db, "backup.restaurado")) == 1
    # A outra escola não é alterada.
    assert db.execute(select(IdentidadeExterna.aluno_id).where(
        IdentidadeExterna.escola_id == e2,
        IdentidadeExterna.id_externo == U)).scalar_one() == y_id


def test_restaurar_nao_grava_memoria_e_a_coleta_daqui_tambem_revisa(
        db, escola_completa, cliente, cliente_global):
    """A restauração não decide por ficha nenhuma: não grava a memória do D10, e a
    coleta seguinte DESTA escola também manda a conta para a revisão (quem decide
    é o Admin Global, no /resolver) — o comportamento declarado na documentação."""
    e1, x, _e2, _y, copia = _cena(db, escola_completa, cliente)
    nome_x = x.nome
    assert _restaurar(cliente_global, e1, copia).status_code == 200
    db.expire_all()
    assert db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == e1)).scalars().all() == []
    linha = {"nome": nome_x, "dados": {"matific_uuid": U, "estrelas": 30, "atividades": 10,
                                      "pontuacao_media": 80, "turma_relatorio": K}}
    r = cliente.post(f"{API}/escolas/{e1}/importacoes/confirmar", json={
        "plataforma": "matific", "formato": "resumo", "tipo": "pdf",
        "recalcular": False, "linhas": [linha]})
    assert r.status_code == 200, r.text
    assert r.json()["ids_de_outra_escola"] == [U]


def test_restaurar_sem_conta_de_outra_escola_devolve_avisos_vazio(
        db, escola_completa, cliente_global):
    e1 = escola_completa["escola"].id
    _vincular(db, e1, escola_completa["alunos"][0].id)
    r = _restaurar(cliente_global, e1, _copia(db, e1))
    assert r.status_code == 200, r.text
    assert r.json()["avisos"] == []
    assert _auditoria(db, AUD) == []


def test_ficha_excluida_no_arquivo_nao_conta(db, escola_completa, cliente, cliente_global):
    """A ficha que já estava excluída no backup volta excluída: a conta dela não
    passa a valer aqui, então não há aviso."""
    e1 = escola_completa["escola"].id
    x = escola_completa["alunos"][0]
    _vincular(db, e1, x.id)
    assert cliente.post(f"{API}/escolas/{e1}/alunos/acoes",
                        json={"aluno_ids": [x.id], "acao": "excluir"}).status_code == 200
    copia = _copia(db, e1)
    escola_b, _t, (y,) = _nova_escola(db)
    _vincular(db, escola_b.id, y.id)
    r = _restaurar(cliente_global, e1, copia)
    assert r.status_code == 200, r.text
    assert r.json()["avisos"] == []
    assert _auditoria(db, AUD) == []
    db.expire_all()
    assert ida.efetivas_em_outra_escola(db, escola_b.id, "matific", [U]) == {}


def test_conta_aposentada_no_arquivo_nao_conta(db, escola_completa, cliente_global):
    """A identidade APOSENTADA restaurada não vale aqui: sem aviso."""
    e1 = escola_completa["escola"].id
    x = escola_completa["alunos"][0]
    _vincular(db, e1, x.id, status="aposentada")
    copia = _copia(db, e1)
    escola_b, _t, (y,) = _nova_escola(db)
    _vincular(db, escola_b.id, y.id)
    r = _restaurar(cliente_global, e1, copia)
    assert r.status_code == 200, r.text
    assert r.json()["avisos"] == []
    assert _auditoria(db, AUD) == []
