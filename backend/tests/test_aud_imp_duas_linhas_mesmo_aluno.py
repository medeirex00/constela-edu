"""Auditoria (frente importação): duas linhas do relatório FIXADAS no mesmo aluno.

IMPORTACAO-9: o gestor escolhia a mesma ficha em duas linhas (a 2ª oferecia "→ Ana
Beatriz Souza (90%)"). A escolha explícita sempre associa (``decidir``, passo 0), o
/confirmar agrupa as linhas por aluno e grava só a ÚLTIMA (``linhas_aluno[-1]``),
sem aviso — o retrato da Ana ficava com os 3 estrelas da outra conta, e as duas
contas iam para a ficha dela (as coletas seguintes mandavam as duas para a Revisão).
O /resolver já tinha a guarda equivalente (``linhas_divergentes_do_mesmo_id``).

Agora o /confirmar recusa (422, nada gravado) duas ou mais linhas fixadas no mesmo
aluno com contas da plataforma diferentes, ou com números diferentes no retrato. A
mesma linha repetida (mesma conta, mesmos números) continua valendo. Dados fictícios.
"""
import json

from sqlalchemy import func, select

API = "/api/v1"
DATA = "2026-08-14T12:00:00"


def _placar(alunos):
    return json.dumps({"fonte": "matific-placar", "turma": "3º Ano A", "alunos": alunos},
                      ensure_ascii=False)


def _analise(cliente, eid, texto):
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/analisar", data={"texto": texto})
    assert r.status_code == 200, r.text
    return r.json()


def _post_confirmar(cliente, eid, analise, linhas, formato=None):
    return cliente.post(f"{API}/escolas/{eid}/importacoes/confirmar", json={
        "plataforma": analise["plataforma"], "formato": formato or analise["formato"],
        "tipo": "texto", "recalcular": False, "linhas": linhas, "data_referencia": DATA})


def _estado(db, aluno_id):
    from app.models import IdentidadeExterna, Importacao, SnapshotMatific
    db.expire_all()
    return (db.scalar(select(func.count()).select_from(SnapshotMatific)
                      .where(SnapshotMatific.aluno_id == aluno_id)),
            db.scalar(select(func.count()).select_from(IdentidadeExterna)
                      .where(IdentidadeExterna.aluno_id == aluno_id)),
            db.scalar(select(func.count()).select_from(Importacao)))


def _fixadas(analise, aluno_id):
    return [{"nome": linha["nome"], "dados": linha["dados"], "aluno_id": aluno_id}
            for linha in analise["linhas"]]


def test_duas_contas_fixadas_no_mesmo_aluno_sao_recusadas(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    analise = _analise(cliente, eid, _placar([
        {"nome": "Ana Beatriz Souza", "uuid": "uuid-fict-ana", "estrelas": 70, "atividades": 20},
        {"nome": "Ana Beatriz Sousa", "uuid": "uuid-fict-ana2", "estrelas": 3, "atividades": 1}]))
    assert ana.id in [a["aluno_id"] for a in
                      analise["linhas"][1]["correspondencia"]["alternativas"]]
    antes = _estado(db, ana.id)
    r = _post_confirmar(cliente, eid, analise, _fixadas(analise, ana.id))
    assert r.status_code == 422, (r.status_code, r.text)
    assert "Ana Beatriz Souza" in r.json()["detail"]
    assert _estado(db, ana.id) == antes            # nada gravado: retrato, conta, importação


def test_mesma_conta_com_numeros_diferentes_fixada_no_mesmo_aluno_e_recusada(
        cliente, db, escola_completa):
    """A mesma conta em duas linhas com números diferentes (id_externo_duplicado na
    prévia) e as duas fixadas na mesma ficha: qual vale seria um chute."""
    eid = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    analise = _analise(cliente, eid, _placar([
        {"nome": "Ana Beatriz Souza", "uuid": "uuid-fict-ana", "estrelas": 70, "atividades": 20},
        {"nome": "Ana Beatriz Souza", "uuid": "uuid-fict-ana", "estrelas": 3, "atividades": 1}]))
    r = _post_confirmar(cliente, eid, analise, _fixadas(analise, ana.id))
    assert r.status_code == 422, (r.status_code, r.text)


def test_a_mesma_linha_repetida_continua_valendo(cliente, db, escola_completa):
    """A mesma conta com os mesmos números em duas linhas (a criança em duas turmas do
    Placar) não é conflito: grava um retrato."""
    eid = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    linha = {"nome": "Ana Beatriz Souza", "uuid": "uuid-fict-ana", "estrelas": 70,
             "atividades": 20}
    analise = _analise(cliente, eid, json.dumps({"fonte": "matific-placar", "alunos": [
        {**linha, "turma": "3º Ano A"}, {**linha, "turma": "4º Ano B"}]}, ensure_ascii=False))
    r = _post_confirmar(cliente, eid, analise, _fixadas(analise, ana.id))
    assert r.status_code == 200, r.text
    assert _estado(db, ana.id)[:2] == (1, 1)


def test_linhas_de_alunos_diferentes_seguem_normais(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    ana, joao = escola_completa["alunos"][:2]
    analise = _analise(cliente, eid, _placar([
        {"nome": "Ana Beatriz Souza", "uuid": "uuid-fict-ana", "estrelas": 70, "atividades": 20},
        {"nome": "João Pedro Barbosa", "uuid": "uuid-fict-jp", "estrelas": 3, "atividades": 1}]))
    linhas = [{"nome": l["nome"], "dados": l["dados"], "aluno_id": a.id}
              for l, a in zip(analise["linhas"], (ana, joao))]
    r = _post_confirmar(cliente, eid, analise, linhas)
    assert r.status_code == 200, r.text
    assert r.json()["qtd_alunos"] == 2
