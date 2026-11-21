"""Auditoria (importação em lote): o arquivo que a confirmação manda para a Revisão.

IMPORTACAO-8: o lote transformava toda linha "revisar" (nome parecido, mais de um
aluno possível…) com turma achada em "Aluno novo — será criado nesta turma." e marcava
o arquivo como "importado" em qualquer resposta 200 — mas o backend não criava nem
importava nada: a linha ia para Revisões de identidade. Com a política "bloquear", o
mesmo com todo aluno sem ficha.

Aqui, as respostas REAIS (/analisar do PDF individual, /turmas e /confirmar com o
corpo que o lote passa a mandar) que AudLoteRevisao.test.tsx usa, e o que esse corpo
faz no backend. Para regravar: ``GERAR_FIXTURES_IMPORTACAO=1``. Dados fictícios.
"""
from app.services import politica_sync
from tests.aud_impweb_exemplos import API, _exemplo, _fichas, _motivos, _turmas


def _analisar_pdf(cliente, eid, nome, turma="3 ANO A"):
    from tests.test_import_individual import _pdf_individual

    pdf = _pdf_individual(nome=nome, turma=turma)
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/analisar",
                     files={"arquivo": ("relatorio-ficticio.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    return r.json()


def _confirmar_lote(cliente, eid, analise, **destino):
    """O corpo de ImportacaoLoteContext.importarTodos: as linhas sem erro, com o
    destino do arquivo, sem data (o relatório individual traz a data de cada leitura)."""
    linhas = [{"nome": l["nome"], "dados": l["dados"], "aluno_id": None,
               "criar_em_turma_id": None, "criar_em_turma_nome": None,
               "deixar_para_revisao": False, **destino}
              for l in analise["linhas"] if not l["erros"]]
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/confirmar", json={
        "plataforma": analise["plataforma"], "formato": analise["formato"],
        "tipo": analise["tipo"], "arquivo_token": analise["arquivo_token"],
        "arquivo_nome": analise["arquivo_nome"],
        "periodo_inicio": analise["periodo_inicio"] or None,
        "periodo_fim": analise["periodo_fim"] or None,
        "data_referencia": None, "linhas": linhas, "recalcular": False})
    assert r.status_code == 200, r.text
    return r.json()


def test_nome_parecido_vai_para_a_revisao_e_nada_e_criado(cliente, db, escola_completa):
    """"SOFIA ALMEIDA DURTE" lembra a "Sofia Almeida Duarte" da ficha: a prévia diz
    revisar. O lote deixa o arquivo para a Revisão (``deixar_para_revisao``, com a turma
    do relatório como contexto): nenhuma ficha nasce, nada é importado e a pendência
    leva o motivo do backend."""
    eid = escola_completa["escola"].id
    analise = _analisar_pdf(cliente, eid, "SOFIA ALMEIDA DURTE")
    corr = analise["linhas"][0]["correspondencia"]
    assert (corr["status"], corr["motivo"], corr["aluno_nome"]) == (
        "revisar", "correspondencia_insegura", "Sofia Almeida Duarte")
    _exemplo("lote_nome_parecido_analise.json", analise)
    _exemplo("lote_revisao_turmas.json", _turmas(cliente, eid))

    fichas = _fichas(db, eid)
    resposta = _confirmar_lote(cliente, eid, analise, deixar_para_revisao=True,
                               criar_em_turma_nome="3 ANO A")
    assert (resposta["qtd_alunos"], resposta["qtd_revisoes"]) == (0, 1)
    assert _motivos(db, eid) == ["correspondencia_insegura"]
    assert _fichas(db, eid) == fichas
    _exemplo("lote_nome_parecido_confirmar.json", resposta)


def test_politica_bloquear_o_aluno_sem_ficha_vai_para_a_revisao(cliente, db, escola_completa):
    """Política "bloquear": a prévia dá a turma da ficha nova (3º Ano A) e marca a
    escola. O lote manda o "criar" de sempre (a pendência nasce com a turma resolvida e
    o motivo da política) — e o backend não cria nem importa: 0 alunos, 1 revisão."""
    eid = escola_completa["escola"].id
    politica_sync.definir(db, eid, "bloquear")
    db.commit()
    analise = _analisar_pdf(cliente, eid, "CRIANCA FICTICIA SEM FICHA")
    corr = analise["linhas"][0]["correspondencia"]
    turma_id = escola_completa["turma"].id
    assert analise["criacao_bloqueada_por_politica"] is True
    assert (corr["status"], corr["turma_id"]) == ("nao_encontrado", turma_id)
    _exemplo("lote_bloquear_analise.json", analise)

    fichas = _fichas(db, eid)
    resposta = _confirmar_lote(cliente, eid, analise, criar_em_turma_id=turma_id)
    assert (resposta["qtd_alunos"], resposta["qtd_revisoes"], resposta["criacao_bloqueada"]) == (
        0, 1, 1)
    assert _motivos(db, eid) == ["criacao_bloqueada_por_politica"]
    assert _fichas(db, eid) == fichas
    _exemplo("lote_bloquear_confirmar.json", resposta)


def test_contraprova_aluno_novo_sem_politica_e_criado_e_importado(cliente, db, escola_completa):
    """Sem a política, o aluno sem ficha nasce na turma que a prévia disse e os dados
    entram: a resposta conta 1 aluno e nenhuma revisão — é o "importado" do lote."""
    eid = escola_completa["escola"].id
    analise = _analisar_pdf(cliente, eid, "CRIANCA FICTICIA NOVA")
    corr = analise["linhas"][0]["correspondencia"]
    turma_id = escola_completa["turma"].id
    assert (corr["status"], corr["turma_id"]) == ("nao_encontrado", turma_id)
    assert analise["criacao_bloqueada_por_politica"] is False
    _exemplo("lote_novo_analise.json", analise)

    fichas = _fichas(db, eid)
    resposta = _confirmar_lote(cliente, eid, analise, criar_em_turma_id=turma_id)
    assert (resposta["qtd_alunos"], resposta["qtd_revisoes"]) == (1, 0)
    assert _fichas(db, eid) == fichas + 1
    _exemplo("lote_novo_confirmar.json", resposta)
