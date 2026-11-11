"""G_LGPD-7 — restaurar o backup não apaga QUEM fez cada importação.

``backup.IGNORADAS = {"id", "escola_id", "usuario_id"}`` ("recriadas na restauração")
tirava ``importacoes.usuario_id`` do arquivo, e ``restaurar`` não o recriava: depois de
qualquer restauração, o histórico de Importações (``GET /importacoes`` →
``usuario_nome``) mostrava todo envio anterior sem autor — o registro que a política
de retenção diz que FICA por obrigação de auditoria (quem, quando, quantos). Agora a
coluna sai no arquivo e vale como as demais referências a usuário
(``REFERENCIAS_A_USUARIO``): volta como veio quando o usuário existe e vira NULL quando
ele não existe mais. Arquivo antigo, sem o campo, continua aceito (sem autor, como
antes).

Dados 100% fictícios (fixture escola_completa); sem rede.
"""
import json

from sqlalchemy import select

from app.models import Importacao
from app.services import backup as svc_backup

API = "/api/v1"


def _importar(cliente, escola_completa):
    eid = escola_completa["escola"].id
    linha = {"nome": "Ana Beatriz Souza", "dados": {
        "matific_uuid": "u-ficticio-aud2-autoria", "estrelas": 5, "atividades": 3,
        "pontuacao_media": 70, "turma_relatorio": escola_completa["turma"].nome}}
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/confirmar", json={
        "plataforma": "matific", "formato": "resumo", "tipo": "pdf",
        "recalcular": False, "linhas": [linha]})
    assert r.status_code == 200, r.text


def _historico(cliente, eid):
    r = cliente.get(f"{API}/escolas/{eid}/importacoes")
    assert r.status_code == 200, r.text
    return [(i["plataforma"], i.get("usuario_nome")) for i in r.json()]


def _restaurar(cliente_global, eid, conteudo: bytes):
    r = cliente_global.post(f"{API}/escolas/{eid}/restaurar",
                            files={"arquivo": ("b.json", conteudo, "application/json")})
    assert r.status_code == 200, r.text


def _autores(db, eid):
    db.expire_all()
    return db.execute(select(Importacao.usuario_id).where(
        Importacao.escola_id == eid)).scalars().all()


def test_restauracao_mantem_quem_fez_cada_importacao(db, escola_completa, cliente,
                                                     cliente_global):
    eid = escola_completa["escola"].id
    _importar(cliente, escola_completa)
    antes = _historico(cliente, eid)
    assert antes == [("matific", "Admin")]
    baixado = cliente.get(f"{API}/escolas/{eid}/backup")
    assert baixado.status_code == 200, baixado.text
    _restaurar(cliente_global, eid, baixado.content)
    assert _historico(cliente, eid) == antes, "a restauração apagou quem fez cada importação"


def test_autor_que_nao_existe_mais_vira_vazio_e_a_restauracao_segue(db, escola_completa,
                                                                     cliente, cliente_global):
    """O usuário removido de vez depois do backup (ou o arquivo levado para outro banco):
    só a autoria some, a importação volta."""
    eid = escola_completa["escola"].id
    _importar(cliente, escola_completa)
    dados = svc_backup.exportar(db, eid)
    [linha] = dados["tabelas"]["importacoes"]
    assert linha["usuario_id"] == escola_completa["admin"].id
    linha["usuario_id"] = 987654                     # usuário que não existe
    _restaurar(cliente_global, eid, json.dumps(dados, default=str).encode("utf-8"))
    assert _autores(db, eid) == [None]
    assert _historico(cliente, eid) == [("matific", None)]


def test_arquivo_antigo_sem_o_autor_continua_aceito(db, escola_completa, cliente,
                                                    cliente_global):
    eid = escola_completa["escola"].id
    _importar(cliente, escola_completa)
    dados = svc_backup.exportar(db, eid)
    for linha in dados["tabelas"]["importacoes"]:
        linha.pop("usuario_id")                      # como saía antes da correção
    _restaurar(cliente_global, eid, json.dumps(dados, default=str).encode("utf-8"))
    assert _autores(db, eid) == [None]


def test_autoria_da_importacao_esta_entre_as_referencias_a_usuario():
    assert svc_backup.REFERENCIAS_A_USUARIO["importacoes"] == ("usuario_id",)
    assert "usuario_id" not in svc_backup.IGNORADAS
