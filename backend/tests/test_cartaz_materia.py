"""GET /escolas/{id}/ranking/cartaz?dimensao=leitura|matematica — o CARTAZ DA
MATÉRIA (pôster em PDF) que a aba Leitura/Matemática baixa.

Trava:
  * com ``dimensao`` as linhas SÃO as do ranking oficial por dimensão
    (``rankings._ranking`` com ``dimensao``): só os aferidos naquela matéria, na
    ordem e com a posição carimbada dela, mesma elegibilidade (arquivado fora),
    da escola inteira — colunas Posição/Aluno/Turma/Série/Nota da matéria;
  * o documento leva o nome da matéria no título e uma só coluna de nota;
  * sem ``dimensao`` nada muda (o cartaz do Ranking Geral, linhas legadas);
  * acesso: gestão apenas (professor 403), módulo da matéria não contratado
    403, dimensão fora da lista 422.
"""
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import (Importacao, ModuloRede, Rede, SnapshotElefante,
                        SnapshotMatific, Usuario)
from app.routers import relatorios as rota_relatorios
from app.services import relatorios as svc
from app.services import scoring

API = "/api/v1"


def _url(escola_id: int) -> str:
    return f"{API}/escolas/{escola_id}/ranking/cartaz"


def _dados(db, escola_completa) -> None:
    """Ana: Matific + Elefante. João: só Matific. Sofia: nada (não aferida)."""
    escola = escola_completa["escola"]
    ana, joao, _ = escola_completa["alunos"]
    importacao = Importacao(escola_id=escola.id, plataforma="matific", tipo="seed")
    db.add(importacao)
    db.flush()
    db.add_all([
        SnapshotMatific(escola_id=escola.id, aluno_id=ana.id, importacao_id=importacao.id,
                        atividades=60, estrelas=250, pontuacao_media=4.4),
        SnapshotElefante(escola_id=escola.id, aluno_id=ana.id, importacao_id=importacao.id,
                         livros_unicos=12, tempo_leitura_min=650,
                         questoes_tentativas=30, questoes_acertos=27,
                         livros_por_nivel={"AA": 8, "D": 4}),
        SnapshotMatific(escola_id=escola.id, aluno_id=joao.id, importacao_id=importacao.id,
                        atividades=5, estrelas=12, pontuacao_media=3.0),
    ])
    db.commit()
    scoring.recalcular_escola(db, escola.id)


def _espiar(monkeypatch) -> list[dict]:
    """Registra o que a rota entrega ao gerador do cartaz, sem trocar o gerador
    (o PDF continua sendo produzido de verdade)."""
    chamadas: list[dict] = []
    original = svc.gerar_cartaz_ranking

    def _espia(**kwargs):
        chamadas.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(rota_relatorios.svc, "gerar_cartaz_ranking", _espia)
    return chamadas


def _login(db, escola_id: int, email: str, cargo: str) -> TestClient:
    db.add(Usuario(escola_id=escola_id, nome=email.split("@")[0], email=email,
                   senha_hash=hash_senha("s3nh4"), cargo=cargo))
    db.commit()
    c = TestClient(app)
    r = c.post(f"{API}/auth/login", data={"username": email, "password": "s3nh4"})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _linhas_do_ranking_oficial(cliente, escola_id: int, dimensao: str) -> list[list]:
    itens = cliente.get(f"{API}/escolas/{escola_id}/ranking",
                        params={"dimensao": dimensao}).json()
    return [[i["posicao"], i["nome"], i["turma"], i["ano_escolar"], i["nota"]]
            for i in itens]


def test_cartaz_de_leitura_traz_so_os_aferidos_em_leitura(cliente, db, escola_completa,
                                                          monkeypatch):
    _dados(db, escola_completa)
    escola_id = escola_completa["escola"].id
    chamadas = _espiar(monkeypatch)

    resposta = cliente.get(_url(escola_id), params={"dimensao": "leitura"})

    assert resposta.status_code == 200, resposta.text
    assert resposta.content[:5] == b"%PDF-"
    assert resposta.headers["content-type"] == "application/pdf"
    assert "ranking_cartaz_leitura_" in resposta.headers["content-disposition"]
    (chamada,) = chamadas
    assert chamada["materia"] == "leitura"
    assert chamada["cabecalho"] == ["Posição", "Aluno", "Turma", "Série", "Nota de Leitura"]
    # Só Ana tem Elefante: João (só Matific) e Sofia (nada) ficam de fora.
    assert [linha[1] for linha in chamada["linhas"]] == ["Ana Beatriz Souza"]
    assert chamada["linhas"] == _linhas_do_ranking_oficial(cliente, escola_id, "leitura")


def test_cartaz_de_matematica_segue_a_ordem_e_a_posicao_da_dimensao(cliente, db,
                                                                    escola_completa,
                                                                    monkeypatch):
    _dados(db, escola_completa)
    escola_id = escola_completa["escola"].id
    chamadas = _espiar(monkeypatch)

    resposta = cliente.get(_url(escola_id), params={"dimensao": "matematica"})

    assert resposta.status_code == 200, resposta.text
    assert resposta.content[:5] == b"%PDF-"
    (chamada,) = chamadas
    assert chamada["materia"] == "matematica"
    assert chamada["cabecalho"][-1] == "Nota de Matemática"
    linhas = chamada["linhas"]
    assert [linha[1] for linha in linhas] == ["Ana Beatriz Souza", "João Pedro Barbosa"]
    assert [linha[0] for linha in linhas] == [1, 2]
    assert all(len(linha) == 5 for linha in linhas)
    assert linhas == _linhas_do_ranking_oficial(cliente, escola_id, "matematica")


def test_cartaz_da_materia_respeita_a_elegibilidade_do_ranking(cliente, db,
                                                               escola_completa,
                                                               monkeypatch):
    """Aluno arquivado não aparece no ranking — nem no cartaz da matéria."""
    _dados(db, escola_completa)
    escola_id = escola_completa["escola"].id
    escola_completa["alunos"][1].status = "arquivado"   # João
    db.commit()
    chamadas = _espiar(monkeypatch)

    assert cliente.get(_url(escola_id),
                       params={"dimensao": "matematica"}).status_code == 200
    assert [linha[1] for linha in chamadas[0]["linhas"]] == ["Ana Beatriz Souza"]


def test_sem_dimensao_continua_o_cartaz_do_ranking_geral(cliente, db, escola_completa,
                                                         monkeypatch):
    _dados(db, escola_completa)
    escola_id = escola_completa["escola"].id
    chamadas = _espiar(monkeypatch)

    resposta = cliente.get(_url(escola_id))

    assert resposta.status_code == 200, resposta.text
    assert resposta.content[:5] == b"%PDF-"
    (chamada,) = chamadas
    assert chamada["materia"] is None
    assert (chamada["cabecalho"], chamada["linhas"]) == svc.linhas_ranking(db, escola_id)


def test_dimensao_invalida_e_422(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    assert cliente.get(_url(escola_id),
                       params={"dimensao": "ciencias"}).status_code == 422


def test_professor_nao_baixa_o_cartaz_da_materia(db, escola_completa):
    escola_id = escola_completa["escola"].id
    professor = _login(db, escola_id, "prof@cartaz.local", "professor")
    assert professor.get(_url(escola_id),
                         params={"dimensao": "leitura"}).status_code == 403


def test_materia_nao_contratada_e_403(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    rede = Rede(nome="Rede So Leitura")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    db.add(ModuloRede(rede_id=rede.id, modulo="leitura", ativo=True))
    db.add(ModuloRede(rede_id=rede.id, modulo="matematica", ativo=False))
    db.commit()
    _dados(db, escola_completa)

    assert cliente.get(_url(escola.id),
                       params={"dimensao": "matematica"}).status_code == 403
    assert cliente.get(_url(escola.id),
                       params={"dimensao": "leitura"}).status_code == 200


def test_documento_da_materia_tem_o_nome_dela_e_uma_coluna_de_nota():
    linhas = [[1, "Ana", "3º Ano A", "3º Ano", 87.5], [2, "João", "3º Ano A", "3º Ano", 40]]
    html = svc._cartaz_documento_html("ESCOLA X", 2026, linhas, {}, materia="matematica")
    assert "RANKING DE MATEMÁTICA" in html
    assert "Nota de Matemática" in html
    assert "Nota Elefante" not in html and "Nota Geral" not in html
    assert "87,5" in html and "40,0" in html
    assert "⟦" not in html

    geral = svc._cartaz_documento_html(
        "ESCOLA X", 2026, [[1, "Ana", "3º Ano A", "3º Ano", 80, 90, 85]], {})
    assert "RANKING GERAL" in geral
    assert "Nota Matific" in geral and "Nota Elefante" in geral and "Nota Geral" in geral
    assert "⟦" not in geral


def test_reserva_sem_navegador_tambem_gera_o_cartaz_da_materia(monkeypatch):
    def _sem_chromium(*args, **kwargs):
        raise RuntimeError("sem navegador")

    monkeypatch.setattr(svc, "_cartaz_html_pdf", _sem_chromium)
    pdf = svc.gerar_cartaz_ranking(
        escola_nome="ESCOLA X", cor="#1B2A4A", ano_letivo=2026,
        cabecalho=svc.cabecalho_cartaz_materia("leitura"),
        linhas=[[1, "Ana", "3º Ano A", "3º Ano", 87.5]],
        estatisticas={}, materia="leitura")
    assert pdf[:5] == b"%PDF-"
