"""Prévia = confirmação também para a linha que a confirmação IGNORA (G_LGPD-1/prévia).

A conta de uma criança excluída para sempre (``conta_esquecida``) e a conta que a
escola aposentou (``identidade_aposentada``) são ignoradas pelo /confirmar
(``identidade_aluno.decidir`` → IGNORAR). A prévia caía no ramo do CRIAR e
mostrava "nao_encontrado"/"novo" — "a confirmação cria a ficha" —, e a confirmação
ignorava a linha. Agora a prévia devolve ``status: "ignorado"`` com o motivo, sem
aluno nem alternativa a escolher. Dados fictícios.
"""
from datetime import datetime, timezone

from app.models import IdentidadeExterna
from app.services import importacao as svc

API = "/api/v1"
CONTA = "uuid-ficticio-previa-ignorada-1"
APOSENTADA = "uuid-ficticio-previa-aposentada-2"


def _confirmar(cliente, eid, nome, conta):
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/confirmar", json={
        "plataforma": "matific", "formato": "resumo", "tipo": "texto", "recalcular": False,
        "linhas": [{"nome": nome, "dados": {"matific_uuid": conta, "turma_relatorio": "3º Ano A",
                                            "atividades": 4, "estrelas": 9,
                                            "pontuacao_media": 70}}]})
    assert r.status_code == 200, r.text
    return r.json()


def _previa(db, eid, nome, conta):
    linhas = [svc.LinhaImportacao(numero=1, nome=nome, dados={
        "matific_uuid": conta, "turma_relatorio": "3º Ano A", "atividades": 6})]
    svc.casar_nomes(db, eid, linhas, plataforma="matific")
    return linhas[0].correspondencia


def test_previa_da_conta_esquecida_diz_que_a_linha_sera_ignorada(
        db, cliente, cliente_global, escola_completa):
    eid = escola_completa["escola"].id
    crianca = escola_completa["alunos"][2]
    assert _confirmar(cliente, eid, crianca.nome, CONTA)["qtd_alunos"] == 1
    r = cliente_global.post(f"{API}/escolas/{eid}/alunos/excluir-permanente",
                            json={"aluno_ids": [crianca.id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text

    corresp = _previa(db, eid, crianca.nome, CONTA)
    assert (corresp["status"], corresp["motivo"]) == ("ignorado", "conta_esquecida"), corresp
    assert corresp["aluno_id"] is None and corresp["alternativas"] == []
    # A confirmação faz o que a prévia disse: nada aplicado, nada criado.
    depois = _confirmar(cliente, eid, crianca.nome, CONTA)
    assert depois["qtd_alunos"] == 0 and depois["linhas_descartadas"] == {"conta_esquecida": 1}


def test_previa_da_conta_aposentada_diz_que_a_linha_sera_ignorada(db, cliente, escola_completa):
    eid = escola_completa["escola"].id
    aluno = escola_completa["alunos"][0]
    db.add(IdentidadeExterna(escola_id=eid, aluno_id=aluno.id, plataforma="matific",
                             id_externo=APOSENTADA, status="aposentada",
                             aposentada_em=datetime.now(timezone.utc).replace(tzinfo=None),
                             motivo_aposentadoria="conta duplicada (teste ficticio)"))
    db.commit()

    corresp = _previa(db, eid, aluno.nome, APOSENTADA)
    assert (corresp["status"], corresp["motivo"]) == ("ignorado", "identidade_aposentada")
    depois = _confirmar(cliente, eid, aluno.nome, APOSENTADA)
    assert depois["qtd_alunos"] == 0
    assert depois["linhas_descartadas"] == {"identidade_aposentada": 1}


def test_o_schema_da_resposta_leva_o_status_e_o_motivo():
    """O CorrespondenciaOut da resposta da análise não descarta o status novo."""
    from app.schemas.importacao import CorrespondenciaOut
    saida = CorrespondenciaOut(**{"status": "ignorado", "via": "", "motivo": "conta_esquecida",
                                  "aluno_id": None, "aluno_nome": None, "similaridade": None,
                                  "alternativas": []})
    assert (saida.status, saida.motivo, saida.alternativas) == ("ignorado", "conta_esquecida", [])
