"""Restaurar o backup da escola NÃO desfaz as travas da sincronização — 2ª revisão
de integração do e97 (dados-config, prova 1, testes 1 e 2 invertidos).

Antes, ``backup.restaurar`` só preservava os segredos (``SEGREDOS_DE_CONFIGURACAO``)
e regravava as demais configurações a partir do arquivo:
  * a política "bloquear" (só o Admin Global grava, com de/para) voltava ao padrão
    "permitir" com um arquivo anterior a ela — a coleta seguinte voltava a CRIAR
    fichas, o que é irreversível;
  * o vínculo da escola externa era apagado, ou regravado com uma escola externa
    que hoje é o vínculo de OUTRA escola, sem a regra do 409 — as duas coletas
    paravam com ``escola_externa_em_outra_escola``.

Agora os dois namespaces ficam como estão (``PRESERVADAS_NA_RESTAURACAO``) e as
linhas do arquivo são ignoradas; o export continua igual.

Dados 100% fictícios (nomes de escola e ids externos inventados); sem rede.
"""
import io
import json

from sqlalchemy import select

from app.models import Escola, LogAuditoria
from app.services import backup, politica_sync
from app.sync import escola_externa

API = "/api/v1"
SCHOOL_X = "424242"
NOME_X = "Escola Ficticia Da Plataforma"


def _restaurar(cliente_global, escola_id, arquivo):
    corpo = json.dumps(arquivo).encode("utf-8")
    return cliente_global.post(
        f"{API}/escolas/{escola_id}/restaurar",
        files={"arquivo": ("backup.json", io.BytesIO(corpo), "application/json")})


def _vinculo(cliente_global, escola_id, metodo="put"):
    url = f"{API}/escolas/{escola_id}/sync/escola-externa/elefante"
    if metodo == "delete":
        return cliente_global.delete(url)
    return cliente_global.put(url, json={"id_externo": SCHOOL_X, "nome": NOME_X})


def test_restauracao_mantem_bloquear_e_vinculo_explicito(db, escola_completa, cliente_global):
    """Arquivo de ANTES da política e do vínculo: os dois continuam valendo."""
    a = escola_completa["escola"].id
    arquivo = json.loads(json.dumps(backup.exportar(db, a)))
    r = cliente_global.put(f"{API}/escolas/{a}/configuracoes/sincronizacao",
                           json={"criar_aluno": "bloquear", "motivo": "A6"})
    assert r.status_code == 200, r.text
    assert _vinculo(cliente_global, a).status_code == 200
    db.expire_all()
    assert politica_sync.pode_criar_aluno(db, a) is False

    r = _restaurar(cliente_global, a, arquivo)
    assert r.status_code == 200, r.text
    db.expire_all()
    assert politica_sync.pode_criar_aluno(db, a) is False
    vinculo = escola_externa.obter(db, a, "elefante")
    assert vinculo["origem"] == "explicito" and vinculo["id"] == SCHOOL_X
    # Nenhuma troca de política escondida: só a de permitir→bloquear, pela API.
    acoes = list(db.execute(select(LogAuditoria.acao)).scalars())
    assert acoes.count("sincronizacao.politica_alterada") == 1


def test_restauracao_nao_repoe_permitir_do_arquivo(db, escola_completa, cliente_global):
    """Arquivo com a linha da política "permitir" (gravada antes do backup): a
    restauração ignora a linha do arquivo e mantém o "bloquear" atual."""
    a = escola_completa["escola"].id
    assert cliente_global.put(f"{API}/escolas/{a}/configuracoes/sincronizacao",
                              json={"criar_aluno": "permitir", "motivo": "teste"}
                              ).status_code == 200
    arquivo = json.loads(json.dumps(backup.exportar(db, a)))
    # O export continua levando a política e o vínculo (só a restauração os ignora).
    assert [c for c in arquivo["tabelas"]["configuracoes"]
            if c["namespace"] == politica_sync.NAMESPACE]
    assert cliente_global.put(f"{API}/escolas/{a}/configuracoes/sincronizacao",
                              json={"criar_aluno": "bloquear", "motivo": "A6"}
                              ).status_code == 200
    assert _restaurar(cliente_global, a, arquivo).status_code == 200
    db.expire_all()
    assert politica_sync.pode_criar_aluno(db, a) is False


def test_restauracao_nao_planta_vinculo_que_a_api_recusa_com_409(db, escola_completa,
                                                                 cliente_global):
    """O vínculo X passou de A para B pela API: restaurar o backup antigo de A não
    devolve X para A (a API recusaria com 409) e B continua coletando."""
    a = escola_completa["escola"].id
    b_escola = Escola(nome="ESCOLA FICTICIA B DAS TRAVAS", ano_letivo_ativo=2026)
    db.add(b_escola)
    db.commit()
    b = b_escola.id
    assert _vinculo(cliente_global, a).status_code == 200
    arquivo = json.loads(json.dumps(backup.exportar(db, a)))          # leva o vínculo X
    assert [c for c in arquivo["tabelas"]["configuracoes"]
            if c["namespace"] == escola_externa.NAMESPACE]
    assert _vinculo(cliente_global, a, "delete").status_code == 204
    assert _vinculo(cliente_global, b).status_code == 200
    assert _vinculo(cliente_global, a).status_code == 409             # controle

    r = _restaurar(cliente_global, a, arquivo)
    assert r.status_code == 200, r.text
    db.expire_all()
    assert escola_externa.escolas_com_o_mesmo_vinculo(db, "elefante", SCHOOL_X) == [b]
    assert escola_externa.obter(db, a, "elefante") is None
    assert SCHOOL_X not in escola_externa.ids_de_outras_escolas(db, "elefante", b)


def test_preservadas_cobrem_segredos_e_travas_da_sync():
    """Catraca: o conjunto preservado tem os segredos e as duas travas da sync, e
    as travas não viraram segredo (continuam saindo no arquivo)."""
    assert set(backup.SEGREDOS_DE_CONFIGURACAO) <= set(backup.PRESERVADAS_NA_RESTAURACAO)
    assert politica_sync.NAMESPACE in backup.PRESERVADAS_NA_RESTAURACAO
    assert escola_externa.NAMESPACE in backup.PRESERVADAS_NA_RESTAURACAO
    assert politica_sync.NAMESPACE not in backup.SEGREDOS_DE_CONFIGURACAO
    assert escola_externa.NAMESPACE not in backup.SEGREDOS_DE_CONFIGURACAO
