"""O link de cada aviso segue as guardas de rota da web.

O sino só põe link onde o perfil pode abrir a tela; quem não pode recebe o aviso
sem o link (na web, o link o mandaria de volta à página inicial). A régua é a da
web — ``apps/web/src/lib/rotasGuardadas.ts``, o espelho das guardas do App.tsx —,
e o backend a repete só para as rotas que os avisos usam
(``notificacoes.GUARDAS_DAS_ROTAS``). Antes ela cobria só /revisoes-identidade e
/importacoes: o professor recebia "Dados da Matific editados manualmente" (aviso
do aluno dele) com o link /matific, tela de operação da escola que ele não abre.

Estes testes leem a tabela da web e falham se as duas divergirem. Dados fictícios.
"""
import pathlib
import re

import pytest

from app.services import audit, notificacoes
from tests.test_notificacoes import _cenario, _login

ROTAS_GUARDADAS_TS = (pathlib.Path(__file__).resolve().parents[2]
                      / "apps" / "web" / "src" / "lib" / "rotasGuardadas.ts")


def _tabela_da_web() -> dict[str, tuple[str, ...]]:
    fonte = ROTAS_GUARDADAS_TS.read_text(encoding="utf-8")
    linhas = re.findall(r'\{\s*caminho:\s*"([^"]+)",\s*guardas:\s*\[([^\]]*)\]', fonte)
    assert linhas, "a tabela da web mudou de forma: ajuste o leitor deste teste"
    return {caminho: tuple(re.findall(r'"([^"]+)"', guardas)) for caminho, guardas in linhas}


def _rotas_que_os_avisos_usam() -> set[str]:
    rotas = {notificacoes.ROTA_REVISOES}
    for _titulo, _sev, rota_de in notificacoes.NOTIFICAVEIS.values():
        rotas |= {rota_de(None), rota_de(41)}
    return rotas


def _guardas_na_web(tabela, rota):
    alvo = [s for s in rota.split("?")[0].split("/") if s]
    for caminho, guardas in tabela.items():
        p = [s for s in caminho.split("/") if s]
        if len(p) == len(alvo) and all(a.startswith(":") or a == b for a, b in zip(p, alvo)):
            return guardas
    return ()


def test_as_guardas_do_backend_sao_as_da_web():
    web = _tabela_da_web()
    for caminho, guardas in notificacoes.GUARDAS_DAS_ROTAS.items():
        assert caminho in web, caminho
        assert web[caminho] == guardas, (caminho, web[caminho], guardas)


@pytest.mark.parametrize("rota", sorted(_rotas_que_os_avisos_usam()))
def test_toda_rota_de_aviso_tem_as_guardas_da_web(rota):
    assert notificacoes.guardas_da_rota(rota) == _guardas_na_web(_tabela_da_web(), rota), rota


def test_professor_recebe_o_aviso_da_plataforma_sem_o_link(db, escola_completa):
    ids = _cenario(db, escola_completa)
    for acao in ("matific.editado", "elefante.editado", "aluno.criado"):
        audit.registrar(db, acao, escola_id=ids["escola"], entidade="aluno",
                        entidade_id=ids["aluno_prof"])
    db.commit()

    prof = {n["tipo"]: n["rota"]
            for n in _login("prof@notif.local").get("/api/v1/notificacoes").json()}
    assert prof == {"matific.editado": None, "elefante.editado": None,
                    # A ficha do aluno ele abre: o link fica.
                    "aluno.criado": f"/alunos/{ids['aluno_prof']}"}

    gestao = {n["tipo"]: n["rota"]
              for n in _login("admin@teste.local").get("/api/v1/notificacoes").json()}
    assert gestao == {"matific.editado": "/matific", "elefante.editado": "/elefante",
                      "aluno.criado": f"/alunos/{ids['aluno_prof']}"}


def test_coordenacao_recebe_o_backup_sem_o_link_de_configuracoes(db, escola_completa):
    """Configurações Gerais é só do administrador (RotaAdmin): a coordenação recebe
    o aviso do backup, sem o link; o administrador, com ele."""
    from app.core.security import hash_senha
    from app.models import Usuario

    ids = _cenario(db, escola_completa)
    db.add(Usuario(escola_id=ids["escola"], nome="Coord Notif", email="coord@notif.local",
                   senha_hash=hash_senha("s3nh4"), cargo="coordenador"))
    audit.registrar(db, "backup.gerado", escola_id=ids["escola"])
    db.commit()
    coord = _login("coord@notif.local").get("/api/v1/notificacoes").json()
    assert [(n["tipo"], n["rota"]) for n in coord] == [("backup.gerado", None)]
    admin = _login("admin@teste.local").get("/api/v1/notificacoes").json()
    assert [(n["tipo"], n["rota"]) for n in admin] == [("backup.gerado", "/configuracoes")]
