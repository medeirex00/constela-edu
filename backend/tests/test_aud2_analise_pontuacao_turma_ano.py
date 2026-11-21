"""'Pontuação por turma' depois da virada do ano letivo (G_VIRADA-5).

As turmas de um ano letivo novo são linhas novas, e a pontuação por turma é guardada por
``turma_id``: o motor aplica às Notas do ano ativo só a configuração das turmas desse ano.
Antes, o seletor listava as turmas ATIVAS de todos os anos com o mesmo rótulo
('3º Ano A · 3º Ano' duas vezes) — a de 2026 continuava editável e o "salva. Notas
recalculadas." não mudava nada no ranking.

O que estes testes sustentam:

* a tela recebe só as turmas do ano letivo ATIVO da escola, cada uma com ``ano_letivo``, e o
  ano letivo da lista (``ano_letivo``), para o rótulo dizer de que ano são;
* antes da virada, as turmas do ano em curso continuam lá com a configuração salva;
* o PUT recusa (400) a turma de outro ano letivo — a principal ou uma de ``aplicar_em`` (um
  cliente antigo, ou a API direto) — e não grava nada: o "salva. Notas recalculadas." de
  uma configuração que não pesa em nada era falso (REV2-ANALISE-4).

Dados INVENTADOS (fixture ``escola_completa``).
"""

URL = "/api/v1/escolas/{eid}/configuracoes/pontuacao-turma"


def _patch_ano(cliente, eid, ano):
    return cliente.patch(f"/api/v1/escolas/{eid}", json={"ano_letivo_ativo": ano})


def test_antes_da_virada_a_turma_do_ano_aparece_com_a_configuracao(cliente_global,
                                                                     escola_completa):
    eid, t26 = escola_completa["escola"].id, escola_completa["turma"]
    r = cliente_global.put(URL.format(eid=eid), json={"turma_id": t26.id, "pontos": {"D": 9}})
    assert r.status_code == 200, r.text
    dados = cliente_global.get(URL.format(eid=eid)).json()
    assert dados["ano_letivo"] == 2026
    assert [(t["turma_id"], t["ano_letivo"], t["pontos"]) for t in dados["turmas"]] == [
        (t26.id, 2026, {"D": 9.0})]


def test_depois_da_virada_so_as_turmas_do_ano_ativo(cliente_global, escola_completa):
    eid, t26 = escola_completa["escola"].id, escola_completa["turma"]
    r = cliente_global.put(URL.format(eid=eid), json={"turma_id": t26.id, "pontos": {"D": 9}})
    assert r.status_code == 200, r.text
    assert _patch_ano(cliente_global, eid, 2027).status_code == 200
    novo = cliente_global.post(f"/api/v1/escolas/{eid}/turmas", json={
        "nome": "3º Ano A", "ano_escolar": "3º Ano", "ano_letivo": 2027})
    assert novo.status_code == 201, novo.text
    dados = cliente_global.get(URL.format(eid=eid)).json()
    # A turma de 2026 (ainda ativa, não arquivada) não aparece: a configuração dela não
    # pesa nas Notas de 2027 e o seletor teria duas opções '3º Ano A · 3º Ano'.
    assert [(t["turma_id"], t["nome"], t.get("ano_letivo"), t["pontos"])
            for t in dados["turmas"]] == [(novo.json()["id"], "3º Ano A", 2027, {})]
    assert dados["ano_letivo"] == 2027


def _pontos_gravados(db, eid, tid):
    from sqlalchemy import select

    from app.models import PontuacaoNivelTurma
    db.expire_all()
    row = db.execute(select(PontuacaoNivelTurma).where(
        PontuacaoNivelTurma.escola_id == eid, PontuacaoNivelTurma.turma_id == tid)
    ).scalar_one_or_none()
    return None if row is None else row.pontos_por_codigo


def _virar_para_2027(cliente, eid):
    assert _patch_ano(cliente, eid, 2027).status_code == 200
    novo = cliente.post(f"/api/v1/escolas/{eid}/turmas", json={
        "nome": "3º Ano A", "ano_escolar": "3º Ano", "ano_letivo": 2027})
    assert novo.status_code == 201, novo.text
    return novo.json()["id"]


def test_depois_da_virada_o_put_recusa_a_turma_do_ano_anterior(cliente_global,
                                                               escola_completa, db):
    eid, t26 = escola_completa["escola"].id, escola_completa["turma"]
    assert cliente_global.put(URL.format(eid=eid), json={
        "turma_id": t26.id, "pontos": {"D": 9}}).status_code == 200
    _virar_para_2027(cliente_global, eid)
    r = cliente_global.put(URL.format(eid=eid), json={"turma_id": t26.id, "pontos": {"D": 3}})
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == (
        "A turma 3º Ano A é do ano letivo 2026: a pontuação por turma vale só para as "
        "turmas do ano letivo ativo (2027).")
    assert _pontos_gravados(db, eid, t26.id) == {"D": 9.0}


def test_depois_da_virada_aplicar_em_com_turma_do_ano_anterior_nao_grava_nada(
        cliente_global, escola_completa, db):
    eid, t26 = escola_completa["escola"].id, escola_completa["turma"]
    t27 = _virar_para_2027(cliente_global, eid)
    r = cliente_global.put(URL.format(eid=eid), json={
        "turma_id": t27, "pontos": {"D": 3}, "aplicar_em": [t26.id]})
    assert r.status_code == 400, r.text
    assert "do ano letivo 2026" in r.json()["detail"]
    assert _pontos_gravados(db, eid, t27) is None
    assert _pontos_gravados(db, eid, t26.id) is None
    # A turma do ano ativo, sozinha, continua aceita.
    r = cliente_global.put(URL.format(eid=eid), json={"turma_id": t27, "pontos": {"D": 3}})
    assert r.status_code == 200, r.text
    assert _pontos_gravados(db, eid, t27) == {"D": 3.0}
