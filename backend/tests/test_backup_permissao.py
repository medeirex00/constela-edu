"""Restauração de backup: EXCLUSIVA do Admin Global.

O arquivo de backup carrega os livros, as leituras, as faixas de dificuldade, os
pesos e os parâmetros de pontuação da escola (inclusive o perfil de scoring).
Restaurá-lo é trocar a régua que decide nota, ranking e premiação — decisão que
não cabe ao admin da escola, ao coordenador, ao professor nem à Secretaria.

O que estes testes travam:
  * admin de escola, coordenador, professor e Secretaria recebem 403 — e NADA
    muda na escola (nem livro, nem peso, nem auditoria de "restaurado");
  * a recusa EXPLICA o que a restauração substitui e a quem pedir;
  * o Admin Global continua restaurando o backup como está (perfil incluído);
  * baixar o backup (exportação) continua com o admin da escola.
"""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_senha
from app.main import app
from app.models import Configuracao, Leitura, Livro, LogAuditoria, Rede, Usuario
from app.routers.admin import MSG_RESTAURACAO_SO_ADMIN_GLOBAL
from app.services import scoring

SENHA = "s3nh4"
PESOS_DEPOIS_DO_BACKUP = {"atividades": 20.0, "media": 60.0, "estrelas": 20.0}


def _base(escola_id: int) -> str:
    return f"/api/v1/escolas/{escola_id}"


def _login(email: str) -> TestClient:
    cliente = TestClient(app)
    r = cliente.post("/api/v1/auth/login", data={"username": email, "password": SENHA})
    assert r.status_code == 200, r.text
    cliente.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return cliente


def _restaurar(cliente: TestClient, escola_id: int, conteudo: bytes):
    return cliente.post(f"{_base(escola_id)}/restaurar",
                        files={"arquivo": ("backup.json", conteudo, "application/json")})


def _titulos(db, escola_id: int) -> set[str]:
    db.expire_all()
    return {livro.titulo for livro in db.execute(
        select(Livro).where(Livro.escola_id == escola_id)).scalars()}


def _pesos_matific(db, escola_id: int):
    db.expire_all()
    return scoring.obter_config(db, escola_id, "pesos.matific", "valores", None)


def _restauracoes(db) -> list[LogAuditoria]:
    db.expire_all()
    return db.execute(select(LogAuditoria)
                      .where(LogAuditoria.acao == "backup.restaurado")).scalars().all()


@pytest.fixture()
def cenario(db, escola_completa):
    """Escola de uma rede com todos os papéis, um backup baixado pelo admin DA
    ESCOLA e, depois dele, uma mudança que a restauração reverteria (livro novo
    e peso local diferente)."""
    escola = escola_completa["escola"]
    rede = Rede(nome="Rede Municipal", status="ativa")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    dono = Usuario(escola_id=escola.id, nome="Dono", email="dono@bkp.local",
                   senha_hash=hash_senha(SENHA), cargo="admin", is_global=True)
    db.add_all([
        Usuario(escola_id=escola.id, nome="Coord", email="coord@bkp.local",
                senha_hash=hash_senha(SENHA), cargo="coordenador"),
        Usuario(escola_id=escola.id, nome="Prof", email="prof@bkp.local",
                senha_hash=hash_senha(SENHA), cargo="professor"),
        # Secretaria no PIOR CASO documentado: veio de escola e tem cargo admin.
        Usuario(escola_id=escola.id, nome="Secretaria", email="sec@bkp.local",
                senha_hash=hash_senha(SENHA), cargo="admin", rede_id=rede.id),
        dono,
    ])
    livro = Livro(escola_id=escola.id, titulo="Livro do Backup", nivel_codigo="D")
    db.add(livro)
    db.flush()
    db.add(Leitura(escola_id=escola.id, aluno_id=escola_completa["alunos"][0].id,
                   livro_id=livro.id))
    db.commit()

    # Exportar continua com o admin DA ESCOLA.
    baixado = _login("admin@teste.local").get(f"{_base(escola.id)}/backup")
    assert baixado.status_code == 200, baixado.text

    db.add(Livro(escola_id=escola.id, titulo="Livro Depois do Backup", nivel_codigo="Z"))
    pesos = db.execute(select(Configuracao).where(
        Configuracao.escola_id == escola.id, Configuracao.namespace == "pesos.matific",
        Configuracao.chave == "valores")).scalar_one()
    pesos.valor = dict(PESOS_DEPOIS_DO_BACKUP)
    db.commit()
    return {"escola": escola, "arquivo": baixado.content, "dono_id": dono.id}


# --- Quem NÃO restaura ---------------------------------------------------------

@pytest.mark.parametrize("email", ["admin@teste.local", "coord@bkp.local", "prof@bkp.local"])
def test_quem_nao_e_admin_global_recebe_403_explicado_e_nada_muda(cenario, db, email):
    escola = cenario["escola"]

    r = _restaurar(_login(email), escola.id, cenario["arquivo"])

    assert r.status_code == 403, r.text
    detalhe = r.json()["detail"]
    assert detalhe == MSG_RESTAURACAO_SO_ADMIN_GLOBAL
    for termo in ("livros", "leituras", "faixas", "pesos", "parâmetros", "Admin Global"):
        assert termo in detalhe, termo
    # NADA foi tocado: o livro posterior ao backup e o peso local continuam.
    assert "Livro Depois do Backup" in _titulos(db, escola.id)
    assert _pesos_matific(db, escola.id) == PESOS_DEPOIS_DO_BACKUP
    assert _restauracoes(db) == []


def test_secretaria_nao_restaura(cenario, db):
    """A Secretaria é barrada na RAIZ do router administrativo (C-04), antes da
    dependência da rota — a resposta é a recusa estrutural dela, também 403."""
    escola = cenario["escola"]

    r = _restaurar(_login("sec@bkp.local"), escola.id, cenario["arquivo"])

    assert r.status_code == 403, r.text
    assert "Livro Depois do Backup" in _titulos(db, escola.id)
    assert _pesos_matific(db, escola.id) == PESOS_DEPOIS_DO_BACKUP
    assert _restauracoes(db) == []


# --- Quem restaura -------------------------------------------------------------

def test_admin_global_restaura(cenario, db):
    escola = cenario["escola"]

    r = _restaurar(_login("dono@bkp.local"), escola.id, cenario["arquivo"])

    assert r.status_code == 200, r.text
    assert "Backup restaurado" in r.json()["mensagem"]
    titulos = _titulos(db, escola.id)
    assert "Livro do Backup" in titulos
    assert "Livro Depois do Backup" not in titulos
    assert _pesos_matific(db, escola.id) == scoring.PESOS_PADRAO["pesos.matific"]
    logs = _restauracoes(db)
    assert len(logs) == 1 and logs[0].usuario_id == cenario["dono_id"]


def test_admin_global_restaura_o_backup_como_esta_inclusive_o_perfil(cenario, db):
    """Comportamento do Admin Global preservado: o perfil de scoring gravado no
    arquivo volta junto (nada é "corrigido" por baixo dos panos)."""
    escola = cenario["escola"]
    dados = json.loads(cenario["arquivo"])
    configs = dados["tabelas"]["configuracoes"]
    linha = dict(configs[0])
    linha.update({"_id": max(c["_id"] for c in configs) + 1,
                  "namespace": scoring.PERFIL_SCORING_NS, "chave": "modo",
                  "valor": "personalizado"})
    configs.append(linha)

    r = _restaurar(_login("dono@bkp.local"), escola.id, json.dumps(dados).encode("utf-8"))

    assert r.status_code == 200, r.text
    db.expire_all()
    assert scoring._scoring_personalizado(db, escola.id)


# --- Exportar continua -----------------------------------------------------------

def test_exportar_backup_continua_com_o_admin_da_escola(cenario):
    r = _login("admin@teste.local").get(f"{_base(cenario['escola'].id)}/backup")
    assert r.status_code == 200, r.text
    assert "Livro Depois do Backup" in r.text   # é o estado ATUAL da escola
