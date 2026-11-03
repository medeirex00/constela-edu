"""Perfil do aluno × ranking renumerado: a mesma criança, para o mesmo usuário, tem
UMA posição.

Desde o 874e85a o pacote ``/sincronizacao`` do app renumera 1..N o ranking do
professor (só as turmas dele), como a web (``GET /ranking``, desde o 79d1ba2). O toque
na linha do Ranking abre o PerfilAluno, que no app (``apps/mobile/src/telas/
PerfilAluno.tsx``) e na web (``apps/web/src/pages/PerfilAluno.tsx``) lê a MESMA rota,
``GET /alunos/{id}/perfil``, e mostra "{posicao}º no ranking". Essa rota devolvia a
posição global carimbada da escola (``Nota.posicao``): a aba dizia 1º e o perfil, 100º.

Agora o perfil segue a perspectiva do ranking: o professor recebe a posição relativa
às turmas dele (a mesma lista e a mesma ordem do ranking renumerado), ou ``None``
quando a criança não está nessa lista (a Nota antiga de turma que não concorre); a
gestão segue com a posição global.

Regressão do achado 1 da dimensão mobile-quest (integração 6 do e97; prova
test_prova_601, invertida). Dados fictícios (fixtures escola_completa e
cenario_professor).
"""
from pathlib import Path

from app.core.config import PROJECT_ROOT
from app.models import Aluno, Matricula, Nota, Turma
from tests.test_permissoes import cenario_professor  # noqa: F401  (fixture)

_ROTA_DO_PERFIL = "/alunos/${"


def _notas(db, escola, alunos, fora):
    """Posições globais 100/105/110 na turma do professor e 103 na turma de fora."""
    posicoes = {alunos[0].id: 100, alunos[1].id: 105, alunos[2].id: 110, fora.id: 103}
    valores = {alunos[0].id: 50.0, alunos[1].id: 40.0, alunos[2].id: 30.0, fora.id: 45.0}
    for aid, pos in posicoes.items():
        db.add(Nota(escola_id=escola.id, aluno_id=aid, ano_letivo=2026,
                    nota_geral=valores[aid], posicao=pos))
    db.commit()


def _tres_visoes(cliente, base):
    """(app, web, perfil): posição por aluno_id no pacote do app, no GET /ranking e
    no perfil aberto pelo toque em cada linha."""
    app = {i["aluno_id"]: i["posicao"]
           for i in cliente.get(f"{base}/sincronizacao").json()["ranking"]}
    web = {i["aluno_id"]: i["posicao"] for i in cliente.get(f"{base}/ranking").json()}
    perfil = {}
    for aid in app:
        r = cliente.get(f"{base}/alunos/{aid}/perfil")
        assert r.status_code == 200, r.text
        perfil[aid] = r.json()["posicao"]
    return app, web, perfil


def test_professor_ve_no_perfil_a_mesma_posicao_da_aba_ranking(
        cenario_professor, escola_completa, db):  # noqa: F811
    c = cenario_professor
    escola = escola_completa["escola"]
    alunos = escola_completa["alunos"]
    _notas(db, escola, alunos, c["aluno_fora"])
    base = f"/api/v1/escolas/{escola.id}"

    app, web, perfil = _tres_visoes(c["professor"], base)

    esperado = {alunos[0].id: 1, alunos[1].id: 2, alunos[2].id: 3}
    assert app == esperado                       # aba Ranking Geral do app (874e85a)
    assert web == esperado                       # Ranking Geral da web (79d1ba2)
    assert perfil == esperado                    # o perfil aberto pelo toque: era 100/105/110
    # A criança de fora continua invisível para ele.
    assert c["professor"].get(f"{base}/alunos/{c['aluno_fora'].id}/perfil").status_code == 404


def test_gestao_segue_com_a_posicao_global_no_perfil(
        cenario_professor, escola_completa, db):  # noqa: F811
    c = cenario_professor
    escola = escola_completa["escola"]
    alunos = escola_completa["alunos"]
    _notas(db, escola, alunos, c["aluno_fora"])
    base = f"/api/v1/escolas/{escola.id}"

    app, web, perfil = _tres_visoes(c["coordenador"], base)

    esperado = {alunos[0].id: 100, c["aluno_fora"].id: 103,
                alunos[1].id: 105, alunos[2].id: 110}
    assert app == web == perfil == esperado


def test_professor_sem_posicao_no_perfil_para_quem_o_ranking_nao_lista(
        cenario_professor, escola_completa, db):  # noqa: F811
    """A Nota antiga de uma criança de turma que NÃO concorre (fase) fica no banco;
    o ranking não a lista, então o perfil do professor não inventa uma posição
    (antes saía a posição carimbada 7). A gestão segue vendo a carimbada."""
    c = cenario_professor
    escola = escola_completa["escola"]
    alunos = escola_completa["alunos"]
    _notas(db, escola, alunos, c["aluno_fora"])
    fase = Turma(escola_id=escola.id, nome="1ª Fase A", ano_escolar="1ª Fase",
                 ano_letivo=2026, professor_id=c["turma_a"].professor_id)
    db.add(fase)
    db.flush()
    pequeno = Aluno(escola_id=escola.id, nome="Aluno Da Fase Ficticio")
    db.add(pequeno)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=pequeno.id, turma_id=fase.id,
                     ano_letivo=2026))
    db.add(Nota(escola_id=escola.id, aluno_id=pequeno.id, ano_letivo=2026,
                nota_geral=60.0, posicao=7))
    db.commit()
    base = f"/api/v1/escolas/{escola.id}"

    app, web, perfil = _tres_visoes(c["professor"], base)
    assert pequeno.id not in app and pequeno.id not in web
    assert perfil == {alunos[0].id: 1, alunos[1].id: 2, alunos[2].id: 3}
    r = c["professor"].get(f"{base}/alunos/{pequeno.id}/perfil")
    assert r.status_code == 200, r.text
    assert r.json()["posicao"] is None
    assert c["coordenador"].get(f"{base}/alunos/{pequeno.id}/perfil").json()["posicao"] == 7


def test_professor_sem_nota_fica_sem_posicao(cenario_professor, escola_completa):  # noqa: F811
    c = cenario_professor
    base = f"/api/v1/escolas/{escola_completa['escola'].id}"
    aluno = escola_completa["alunos"][0]
    r = c["professor"].get(f"{base}/alunos/{aluno.id}/perfil")
    assert r.status_code == 200, r.text
    assert r.json()["posicao"] is None


def test_app_e_web_abrem_o_perfil_pela_mesma_rota():
    """A correção mora no backend porque os dois clientes leem a mesma rota e
    mostram o mesmo campo: se um deles passar a ler outra, este teste avisa."""
    for rel in ("apps/mobile/src/telas/PerfilAluno.tsx", "apps/web/src/pages/PerfilAluno.tsx"):
        texto = (Path(PROJECT_ROOT) / rel).read_text(encoding="utf-8")
        assert _ROTA_DO_PERFIL in texto and "}/perfil`" in texto, rel
        assert "perfil.posicao" in texto, rel
