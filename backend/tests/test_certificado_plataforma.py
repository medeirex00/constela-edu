"""Certificado por plataforma (Elefante Letrado / Matific) — preenchimento
automático (instituição, nome, bimestre, data) sobre a arte oficial, em PDF."""
from app.models import Aluno
from app.services import relatorios as svc

API = "/api/v1"


def test_bimestre_por_mes():
    assert svc._bimestre_por_mes(2) == 1 and svc._bimestre_por_mes(4) == 1
    assert svc._bimestre_por_mes(5) == 2 and svc._bimestre_por_mes(7) == 2
    assert svc._bimestre_por_mes(8) == 3 and svc._bimestre_por_mes(9) == 3
    assert svc._bimestre_por_mes(10) == 4 and svc._bimestre_por_mes(12) == 4


def test_tam_fonte_nome_encolhe_para_nomes_longos():
    assert svc._tam_fonte_nome("Ana") == 52                      # curto → teto
    assert svc._tam_fonte_nome("Maria Eduarda Santos Oliveira") < 40  # longo → encolhe


def test_html_plataforma_preenche_e_resolve_tudo():
    html = svc._certificado_plataforma_html("Escola Municipal Teste", "João da Silva", "elefante")
    assert "Escola Municipal Teste" in html          # instituição
    assert "João da Silva" in html                   # nome (maiúsculo é via CSS)
    assert "data:image/png;base64," in html          # a arte embutida
    assert "⟦" not in html and "⟧" not in html       # nenhum placeholder sobrou


def test_html_plataforma_arte_e_posicoes_por_plataforma():
    h_el = svc._certificado_plataforma_html("E", "A", "elefante")
    h_mt = svc._certificado_plataforma_html("E", "A", "matific")
    assert h_el != h_mt                               # arte + coordenadas diferentes


def test_endpoint_emite_pdf_por_plataforma(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    aluno = Aluno(escola_id=escola.id, nome="Maria Teste")
    db.add(aluno)
    db.commit()

    for modelo in ("elefante", "matific"):
        r = cliente.get(f"{API}/escolas/{escola.id}/certificados/{aluno.id}?modelo={modelo}")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        assert r.content[:4] == b"%PDF"                # PDF de verdade
