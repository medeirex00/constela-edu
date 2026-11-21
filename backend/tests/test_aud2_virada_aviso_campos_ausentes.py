"""PEND-10 (REV-SYNC-4 vizinho) — o aviso da sincronização sobre linhas sem campo
essencial fala a língua de quem usa ("livros lidos"), não o código interno
("livros_unicos"). O código estável em ``avisos_criticos`` não muda: o serviço
da sincronização o lê.

Dados fictícios; a resposta da plataforma é montada à mão.
"""
import json

from app.sync import orchestrator
from app.sync.interfaces import ArquivoObtido, Contexto


def _aplicar(db, escola, students):
    payload = {"courseSchoolDescriptors": {"courseName": "3 ANO A"}, "students": students}
    arq = ArquivoObtido(conteudo=json.dumps(payload).encode("utf-8"),
                        nome_arquivo="t.json", plataforma="elefante",
                        content_type=orchestrator.CT_ELEFANTE_API, formato_hint="resumo")
    ctx = Contexto(escola_id=escola.id, execucao_id=None, log=lambda e, n, m: None)
    return orchestrator.aplicar_arquivo(db, escola, arq, usuario_id=None,
                                        recalcular=False, contexto=ctx)


def test_aviso_de_campo_ausente_usa_o_rotulo_e_nao_o_codigo(db, escola_completa,
                                                            monkeypatch):
    escola = escola_completa["escola"]
    ana, joao = escola_completa["alunos"][:2]
    monkeypatch.setattr(orchestrator.imp, "_guardar_temporario", lambda *a, **k: None)

    res = _aplicar(db, escola, [
        {"studentId": 1, "studentName": ana.nome, "totalBooksRead": 4,
         "totalReadTime": 600, "responses": 3, "approvedResponses": 2},
        {"studentId": 2, "studentName": joao.nome, "responses": 5,
         "approvedResponses": 4},
    ])

    avisos = [a for a in res["avisos"] if "na resposta da plataforma" in a]
    assert len(avisos) == 1, res["avisos"]
    assert "1 linha(s) sem livros lidos na resposta da plataforma" in avisos[0], avisos
    assert "livros_unicos" not in avisos[0]
    # o código estável, lido pelo serviço da sincronização, continua igual
    assert res["avisos_criticos"] == ["campos_ausentes:livros_unicos"]
