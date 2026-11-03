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
import re
from datetime import datetime

from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import (Aluno, Importacao, Matricula, ModuloRede, Rede,
                        SnapshotElefante, SnapshotMatific, Turma, Usuario)
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


# ---------------------------------------------------------------------------
# Cartões de estatística do cartaz da MATÉRIA
# ---------------------------------------------------------------------------
# Os quatro cartões do rodapé eram sempre os totais GERAIS da escola (atividades
# do Matific + livros do Elefante), também no cartaz de Leitura e no de
# Matemática. Agora, no cartaz de uma matéria, os dois primeiros cartões são DA
# MATÉRIA e somam só os alunos que o cartaz LISTA (os aferidos da dimensão):
#   * Leitura: livros lidos e tempo de leitura (SnapshotElefante atual);
#   * Matemática: atividades e estrelas (SnapshotMatific atual);
# seguidos de "estudantes ranqueados" e da faixa de anos. O Ranking Geral não muda.

_RE_TILE = re.compile(
    r'<div class="tile"><div class="n">(.*?)</div><div class="r">(.*?)</div></div>')

# Snapshot ATUAL semeado para cada aluno do cenário (o que os cartões devem somar).
_ELEFANTE_ATUAL = {"Ana Beatriz Souza": (12, 650), "João Pedro Barbosa": (5, 130),
                   "Caio da Fase": (40, 900)}
_MATIFIC_ATUAL = {"Ana Beatriz Souza": (60, 250), "João Pedro Barbosa": (5, 12),
                  "Caio da Fase": (70, 300)}


def _tiles(html: str) -> list[tuple[str, str]]:
    return _RE_TILE.findall(html)


def _dados_com_cartoes(db, escola_completa) -> None:
    """O cenário de `_dados` mais três coisas que separam "alunos listados" de
    "escola inteira" e "snapshot atual" de "qualquer snapshot":

    * João também lê (Elefante) — o cartaz de Leitura passa a ter 2 linhas;
    * Caio, da 1ª Fase (Educação Infantil, não concorre): ativo e matriculado,
      com Matific e Elefante — entra nos totais GERAIS, mas não está em nenhum
      cartaz de matéria, então não pode entrar nos cartões dela;
    * Ana tem um retrato ANTIGO (2020) de cada plataforma com números enormes:
      a fonte é o snapshot atual, então eles não podem aparecer em lugar nenhum."""
    escola = escola_completa["escola"]
    ana, joao, _ = escola_completa["alunos"]
    _dados(db, escola_completa)
    fase = Turma(escola_id=escola.id, nome="1ª Fase A", ano_escolar="1ª Fase",
                 ano_letivo=2026)
    caio = Aluno(escola_id=escola.id, nome="Caio da Fase")
    db.add_all([fase, caio])
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=caio.id, turma_id=fase.id,
                     ano_letivo=2026))
    importacao = Importacao(escola_id=escola.id, plataforma="elefante", tipo="seed")
    db.add(importacao)
    db.flush()
    antigo = datetime(2020, 1, 1)
    db.add_all([
        SnapshotElefante(escola_id=escola.id, aluno_id=joao.id, importacao_id=importacao.id,
                         livros_unicos=5, tempo_leitura_min=130,
                         questoes_tentativas=4, questoes_acertos=3,
                         livros_por_nivel={"AA": 5}),
        SnapshotElefante(escola_id=escola.id, aluno_id=caio.id, importacao_id=importacao.id,
                         livros_unicos=40, tempo_leitura_min=900,
                         questoes_tentativas=0, questoes_acertos=0,
                         livros_por_nivel={"AA": 40}),
        SnapshotMatific(escola_id=escola.id, aluno_id=caio.id, importacao_id=importacao.id,
                        atividades=70, estrelas=300, pontuacao_media=4.0),
        SnapshotElefante(escola_id=escola.id, aluno_id=ana.id, importacao_id=importacao.id,
                         data_referencia=antigo, livros_unicos=999, tempo_leitura_min=99999,
                         questoes_tentativas=0, questoes_acertos=0,
                         livros_por_nivel={"AA": 999}),
        SnapshotMatific(escola_id=escola.id, aluno_id=ana.id, importacao_id=importacao.id,
                        data_referencia=antigo, atividades=8888, estrelas=77777,
                        pontuacao_media=5.0),
    ])
    db.commit()
    scoring.recalcular_escola(db, escola.id)


def _documento(chamada: dict) -> str:
    """O HTML que o Chromium imprimiria com exatamente o que a rota entregou."""
    return svc._cartaz_documento_html(
        chamada["escola_nome"], chamada["ano_letivo"], chamada["linhas"],
        chamada["estatisticas"], chamada["logos"], materia=chamada["materia"])


def test_cartoes_do_cartaz_de_leitura_somam_so_a_leitura_dos_alunos_listados(
        cliente, db, escola_completa, monkeypatch):
    _dados_com_cartoes(db, escola_completa)
    escola_id = escola_completa["escola"].id
    chamadas = _espiar(monkeypatch)

    assert cliente.get(_url(escola_id), params={"dimensao": "leitura"}).status_code == 200

    (chamada,) = chamadas
    listados = [linha[1] for linha in chamada["linhas"]]
    assert sorted(listados) == ["Ana Beatriz Souza", "João Pedro Barbosa"]  # Caio fora
    livros = sum(_ELEFANTE_ATUAL[nome][0] for nome in listados)
    minutos = sum(_ELEFANTE_ATUAL[nome][1] for nome in listados)
    assert (livros, minutos) == (17, 780)
    assert chamada["estatisticas"] == {"livros": livros, "tempo_leitura_min": minutos}

    html = _documento(chamada)
    assert _tiles(html) == [("17", "livros lidos"), ("13h", "tempo de leitura"),
                            ("2", "estudantes ranqueados"), ("3º", "ano")]
    # Nada do Matific no cartaz de Leitura (nem o rótulo, nem os números).
    assert "atividade" not in html.lower()
    valores = {n for n, _ in _tiles(html)}
    assert not valores & {"65", "135", "262", "562"}


def test_cartoes_do_cartaz_de_matematica_somam_so_a_matematica_dos_alunos_listados(
        cliente, db, escola_completa, monkeypatch):
    _dados_com_cartoes(db, escola_completa)
    escola_id = escola_completa["escola"].id
    chamadas = _espiar(monkeypatch)

    assert cliente.get(_url(escola_id),
                       params={"dimensao": "matematica"}).status_code == 200

    (chamada,) = chamadas
    listados = [linha[1] for linha in chamada["linhas"]]
    assert listados == ["Ana Beatriz Souza", "João Pedro Barbosa"]          # Caio fora
    atividades = sum(_MATIFIC_ATUAL[nome][0] for nome in listados)
    estrelas = sum(_MATIFIC_ATUAL[nome][1] for nome in listados)
    assert (atividades, estrelas) == (65, 262)
    assert chamada["estatisticas"] == {"atividades": atividades, "estrelas": estrelas}

    html = _documento(chamada)
    assert _tiles(html) == [("65", "atividades"), ("262", "estrelas"),
                            ("2", "estudantes ranqueados"), ("3º", "ano")]
    # Nada do Elefante no cartaz de Matemática (nem o rótulo, nem os números).
    assert "livro" not in html.lower() and "tempo de leitura" not in html
    valores = {n for n, _ in _tiles(html)}
    assert not valores & {"17", "57", "13h", "28h"}


def test_cartoes_do_ranking_geral_nao_mudam(cliente, db, escola_completa, monkeypatch):
    """Sem dimensão: os mesmos cartões de sempre — atividades + livros da
    população ativa matriculada (Caio da Fase incluído), via `estatisticas_cartaz`."""
    _dados_com_cartoes(db, escola_completa)
    escola_id = escola_completa["escola"].id
    chamadas = _espiar(monkeypatch)

    assert cliente.get(_url(escola_id)).status_code == 200

    (chamada,) = chamadas
    assert chamada["materia"] is None
    assert chamada["estatisticas"] == svc.estatisticas_cartaz(db, escola_id)
    assert chamada["estatisticas"] == {
        "atividades": sum(a for a, _ in _MATIFIC_ATUAL.values()),          # 135
        "livros": sum(livros for livros, _ in _ELEFANTE_ATUAL.values()),   # 57
    }
    tiles = _tiles(_documento(chamada))
    assert tiles[:2] == [("135", "atividades"), ("57", "livros lidos")]
    assert tiles[2][1] == "estudantes ranqueados"
    assert tiles[2][0] == str(len(chamada["linhas"]))


def test_documento_cartoes_por_materia_sem_banco():
    """Conferência direta do HTML (sem navegador): cada cartaz escolhe os SEUS
    cartões, mesmo que receba chaves de outra matéria — e o geral é o de antes."""
    linhas_m = [[1, "Ana", "3º Ano A", "3º Ano", 87.5], [2, "João", "5º Ano B", "5º Ano", 40]]
    misturado = {"atividades": 4321, "livros": 1234, "estrelas": 9876,
                 "tempo_leitura_min": 75000}

    leitura = svc._cartaz_documento_html("ESCOLA X", 2026, linhas_m, misturado,
                                         materia="leitura")
    assert _tiles(leitura) == [("1.234", "livros lidos"), ("1.250h", "tempo de leitura"),
                               ("2", "estudantes ranqueados"), ("3º–5º", "anos atendidos")]
    assert "4.321" not in leitura and "atividade" not in leitura.lower()

    matematica = svc._cartaz_documento_html("ESCOLA X", 2026, linhas_m, misturado,
                                            materia="matematica")
    assert _tiles(matematica) == [("4.321", "atividades"), ("9.876", "estrelas"),
                                  ("2", "estudantes ranqueados"),
                                  ("3º–5º", "anos atendidos")]
    assert "1.234" not in matematica and "livro" not in matematica.lower()

    geral = svc._cartaz_documento_html(
        "ESCOLA X", 2026, [[1, "Ana", "3º Ano A", "3º Ano", 80, 90, 85]],
        {"atividades": 4321, "livros": 1234})
    assert _tiles(geral) == [("4.321", "atividades"), ("1.234", "livros lidos"),
                             ("1", "estudantes ranqueados"), ("3º", "ano")]

    # Sem estatísticas (falha best-effort): zeros, nunca um buraco no cartaz.
    vazio = svc._cartaz_documento_html("ESCOLA X", 2026, linhas_m, {}, materia="leitura")
    assert _tiles(vazio)[:2] == [("0", "livros lidos"), ("0 min", "tempo de leitura")]


def test_tempo_de_leitura_do_cartao():
    assert svc._tempo_cartaz(0) == "0 min"
    assert svc._tempo_cartaz(45) == "45 min"
    assert svc._tempo_cartaz(60) == "1h"
    assert svc._tempo_cartaz(650) == "10h 50min"
    assert svc._tempo_cartaz(75_000) == "1.250h"
    assert svc._tempo_cartaz(None) == "0 min"
