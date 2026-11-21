"""Auditoria (Revisões de identidade): "outra conta leva ao mesmo aluno" sem afirmar que
a ficha já tem outra conta.

IMPORTACAO-11 / REVERIFICACAO-2 (parte da tela): o motivo ``outra_identidade_na_plataforma``
nasce por três caminhos (a ficha já tem outra conta; outra conta do mesmo relatório leva
a ela; uma conta numa pendência aberta leva a ela). A tela dizia "Duas contas na mesma
ficha", "O aluno encontrado já tem outra conta…" e "Atenção: esta ficha tem duas contas"
também quando a ficha não tem conta nenhuma. E ``id_externo_duplicado`` dizia "Conta
repetida no relatório" / "veio em mais de uma linha" quando a disputa vem de um relatório
anterior, com a conta numa linha só.

Aqui, as respostas REAIS (/revisoes e /identidades/{plataforma}/aluno/{id}) que
AudRevisoesOutraConta.test.tsx usa. As datas de gravação (variam a cada execução) vão
fixas. Para regravar: ``GERAR_FIXTURES_IMPORTACAO=1``. Dados fictícios.
"""
from sqlalchemy import select

from tests.aud_impweb_exemplos import API, _exemplo
from tests.test_importacao_previa_motivo import (
    PLACAR_DUP_1, PLACAR_DUP_2, PLACAR_SOFIA_DUAS, PLACAR_SOFIA_UMA, _analise, _confirmar,
    _corpo_padrao, _placar)

DATA_FIXA = "2026-08-14T12:00:00"
DATAS = {"created_at", "atualizada_em", "resolvida_em", "aposentada_em"}


def _datas_fixas(valor):
    if isinstance(valor, dict):
        return {k: (DATA_FIXA if k in DATAS and v else _datas_fixas(v)) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_datas_fixas(v) for v in valor]
    return valor


def _get(cliente, caminho):
    r = cliente.get(f"{API}{caminho}")
    assert r.status_code == 200, r.text
    return r.json()


def _sofia(db, eid):
    from app.models import Aluno
    return db.execute(select(Aluno).where(Aluno.escola_id == eid,
                                          Aluno.nome == "Sofia Almeida Duarte")).scalar_one()


def _importar(cliente, eid, turma, placar):
    analise = _analise(cliente, eid, placar)
    return _confirmar(cliente, eid, analise, _corpo_padrao(analise, turma))


def test_sofia_sem_conta_a_fila_e_as_contas(cliente, db, escola_completa):
    """Duas contas sem vínculo levam à Sofia; no Placar seguinte, só uma. As pendências
    são "outra conta leva ao mesmo aluno" — e a ficha não tem conta nenhuma."""
    eid, turma = escola_completa["escola"].id, escola_completa["turma"].id
    _importar(cliente, eid, turma, PLACAR_SOFIA_DUAS)
    _importar(cliente, eid, turma, PLACAR_SOFIA_UMA)
    sofia = _sofia(db, eid)
    fila = _get(cliente, f"/escolas/{eid}/importacoes/revisoes")
    assert {r["motivo"] for r in fila} == {"outra_identidade_na_plataforma"}
    assert all(r["candidatos"] and r["candidatos"][0]["aluno_id"] == sofia.id for r in fila)
    contas = _get(cliente, f"/escolas/{eid}/importacoes/identidades/matific/aluno/{sofia.id}")
    assert contas == []
    _exemplo("revisoes_sofia_fila.json", _datas_fixas(fila))
    _exemplo("revisoes_sofia_contas.json", contas)


def test_sofia_com_conta_a_fila_e_as_contas(cliente, db, escola_completa):
    """Contraprova: a Sofia já tem a conta "uuid-ficticio-s0" (vinculada no 1º Placar) e
    chega outra conta com o nome dela — aí a ficha TEM outra conta."""
    eid, turma = escola_completa["escola"].id, escola_completa["turma"].id
    _importar(cliente, eid, turma, _placar("3º Ano A", [
        {"nome": "Sofia Almeida Duarte", "uuid": "uuid-ficticio-s0", "estrelas": 5,
         "atividades": 1}]))
    _importar(cliente, eid, turma, _placar("3º Ano A", [
        {"nome": "Sofia Almeida Duarte", "uuid": "uuid-ficticio-s9", "estrelas": 6,
         "atividades": 2}]))
    sofia = _sofia(db, eid)
    fila = _get(cliente, f"/escolas/{eid}/importacoes/revisoes")
    assert [(r["motivo"], r["id_externo"]) for r in fila] == [
        ("outra_identidade_na_plataforma", "uuid-ficticio-s9")]
    contas = _get(cliente, f"/escolas/{eid}/importacoes/identidades/matific/aluno/{sofia.id}")
    assert [(c["id_externo"], c["status"]) for c in contas] == [("uuid-ficticio-s0", "efetiva")]
    _exemplo("revisoes_sofia_com_conta_fila.json", _datas_fixas(fila))
    _exemplo("revisoes_sofia_com_conta_contas.json", _datas_fixas(contas))


def test_conta_repetida_de_relatorio_anterior(cliente, db, escola_completa):
    """A mesma conta com dois nomes no 1º Placar; no seguinte ela vem numa linha só e
    a pendência continua "id_externo_duplicado" — por causa da que espera na fila."""
    eid, turma = escola_completa["escola"].id, escola_completa["turma"].id
    _importar(cliente, eid, turma, PLACAR_DUP_1)
    _importar(cliente, eid, turma, PLACAR_DUP_2)
    fila = _get(cliente, f"/escolas/{eid}/importacoes/revisoes")
    assert {r["motivo"] for r in fila} == {"id_externo_duplicado"}
    _exemplo("revisoes_dup_fila.json", _datas_fixas(fila))
