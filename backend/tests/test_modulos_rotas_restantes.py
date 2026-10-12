"""Trava de MÓDULO CONTRATADO nas rotas que ainda não a aplicavam.

Regra existente (``services/modulos``): o módulo que a rede não contratou não
existe para ela — some da interface e o SERVIDOR recusa ou oculta. Cada rota
aqui tem os dois lados: módulo ligado = igual a antes; desligado = 403 (rota
inteira do módulo) ou o pedaço do módulo some (lista mista).
"""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import (
    Aluno,
    Escola,
    Importacao,
    Matricula,
    Rede,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
    Usuario,
)
from app.services import modulos as svc_modulos
from app.services import relatorios as svc_relatorios
from app.services import scoring

API = "/api/v1"
CATEGORIAS_LEITURA = {"melhor_leitor", "mais_livros", "mais_tempo"}


def _login(email: str, senha: str = "s3nh4") -> TestClient:
    c = TestClient(app)
    r = c.post(f"{API}/auth/login", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


@pytest.fixture()
def cenario(db):
    """Rede + escola com as duas plataformas, notas pelo motor real e o admin
    da escola (gestão: passa nas checagens de permissão de cada rota)."""
    rede = Rede(nome="Rede Trava Sint", status="ativa")
    db.add(rede)
    db.flush()
    esc = Escola(nome="EM Trava Sint", ano_letivo_ativo=2026, rede_id=rede.id, status="ativa")
    db.add(esc)
    db.flush()
    turma = Turma(escola_id=esc.id, nome="3ºA", ano_escolar="3º Ano", ano_letivo=2026,
                  status="ativa")
    db.add(turma)
    db.flush()
    imp = Importacao(escola_id=esc.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    alunos = []
    for i in range(5):
        a = Aluno(escola_id=esc.id, nome=f"Crianca Trava {i}", status="ativo",
                  da_lista_piloto=True)
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=esc.id, aluno_id=a.id, turma_id=turma.id, ano_letivo=2026))
        db.add(SnapshotElefante(escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
                                livros_unicos=5 + i, tempo_leitura_min=60 + i * 10,
                                questoes_tentativas=20, questoes_acertos=16))
        db.add(SnapshotMatific(escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
                               atividades=20 + i, estrelas=100 + i * 10, pontuacao_media=4.0))
        alunos.append(a)
    db.add(Usuario(escola_id=esc.id, nome="Admin Trava", email="admin@trava.local",
                   senha_hash=hash_senha("s3nh4"), cargo="admin"))
    db.commit()
    scoring.recalcular_escola(db, esc.id)
    return {"rede": rede, "escola": esc, "alunos": alunos,
            "admin": _login("admin@trava.local")}


def _desligar(db, cenario, modulo):
    svc_modulos.definir(db, cenario["rede"].id, modulo, False)
    db.commit()


# --- Rotas inteiras do módulo Leitura ----------------------------------------

@pytest.mark.parametrize("sufixo", ["leituras", "evolucao-leitura"])
def test_historico_e_evolucao_de_leitura_exigem_o_modulo(db, cenario, sufixo):
    esc, aluno, admin = cenario["escola"], cenario["alunos"][0], cenario["admin"]
    url = f"{API}/escolas/{esc.id}/alunos/{aluno.id}/{sufixo}"
    assert admin.get(url).status_code == 200            # ligado: igual a antes
    _desligar(db, cenario, "matematica")                 # o OUTRO módulo não interfere
    assert admin.get(url).status_code == 200
    svc_modulos.definir(db, cenario["rede"].id, "matematica", True)
    _desligar(db, cenario, "leitura")
    r = admin.get(url)
    assert r.status_code == 403 and "plano" in r.json()["detail"].lower()


def test_a_trava_vem_depois_da_permissao(db, cenario):
    """Professor continua recebendo a recusa de PERFIL (a checagem já existente
    vem primeiro), com o módulo ligado ou não."""
    esc, aluno = cenario["escola"], cenario["alunos"][0]
    db.add(Usuario(escola_id=esc.id, nome="Prof Trava", email="prof@trava.local",
                   senha_hash=hash_senha("s3nh4"), cargo="professor"))
    db.commit()
    _desligar(db, cenario, "leitura")
    prof = _login("prof@trava.local")
    for sufixo in ("leituras", "evolucao-leitura"):
        r = prof.get(f"{API}/escolas/{esc.id}/alunos/{aluno.id}/{sufixo}")
        assert r.status_code == 403
        assert "dados individuais" in r.json()["detail"]


# --- Premiações: categorias por módulo ---------------------------------------

def _premiacoes(admin, esc, **params):
    r = admin.get(f"{API}/escolas/{esc.id}/premiacoes", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_premiacoes_com_os_dois_modulos_igual_a_antes(db, cenario):
    dados = _premiacoes(cenario["admin"], cenario["escola"], turnos="true")
    assert [c["chave"] for c in dados["categorias"]] == [
        "melhor_leitor", "melhor_matematica", "mais_livros", "mais_tempo"]
    assert "regua_matematica" in dados
    for grupo in dados["turnos"]:
        assert len(grupo["categorias"]) == 4


def test_premiacoes_sem_matematica_tiram_a_categoria_e_a_regua(db, cenario):
    _desligar(db, cenario, "matematica")
    dados = _premiacoes(cenario["admin"], cenario["escola"], turnos="true")
    assert [c["chave"] for c in dados["categorias"]] == [
        "melhor_leitor", "mais_livros", "mais_tempo"]
    assert "regua_matematica" not in dados
    for grupo in dados["turnos"]:
        assert {c["chave"] for c in grupo["categorias"]} == CATEGORIAS_LEITURA


def test_premiacoes_sem_leitura_tiram_as_categorias_de_leitura(db, cenario):
    _desligar(db, cenario, "leitura")
    dados = _premiacoes(cenario["admin"], cenario["escola"], turnos="true")
    assert [c["chave"] for c in dados["categorias"]] == ["melhor_matematica"]
    assert "regua_matematica" in dados
    for grupo in dados["turnos"]:
        assert [c["chave"] for c in grupo["categorias"]] == ["melhor_matematica"]


def test_premiacoes_mantem_o_podio_das_categorias_que_ficam(db, cenario):
    """Tirar a Matemática não mexe nos pódios de Leitura (mesma ordem/valores)."""
    antes = {c["chave"]: c for c in _premiacoes(cenario["admin"], cenario["escola"],
                                                periodo="tudo")["categorias"]}
    _desligar(db, cenario, "matematica")
    depois = {c["chave"]: c for c in _premiacoes(cenario["admin"], cenario["escola"],
                                                 periodo="tudo")["categorias"]}
    for chave in CATEGORIAS_LEITURA:
        assert depois[chave] == antes[chave]


# --- Relatórios ----------------------------------------------------------------

def _csv(admin, esc, tipo):
    return admin.get(f"{API}/escolas/{esc.id}/relatorios/{tipo}", params={"formato": "csv"})


def _cabecalho_e_linhas(resposta):
    texto = resposta.content.decode("utf-8-sig")
    linhas = [l for l in texto.splitlines() if l.strip()]
    sep = ";" if ";" in linhas[0] else ","
    return linhas[0].split(sep), [l.split(sep) for l in linhas[1:]]


def test_relatorio_de_livros_exige_leitura(db, cenario):
    esc, admin = cenario["escola"], cenario["admin"]
    assert _csv(admin, esc, "livros").status_code == 200
    _desligar(db, cenario, "leitura")
    r = _csv(admin, esc, "livros")
    assert r.status_code == 403 and "plano" in r.json()["detail"].lower()
    assert _csv(admin, esc, "alunos").status_code == 200      # o resto segue igual


def test_relatorio_de_ranking_sem_a_coluna_do_modulo_fora_do_plano(db, cenario):
    esc, admin = cenario["escola"], cenario["admin"]
    r = _csv(admin, esc, "ranking")
    assert r.status_code == 200
    cab, linhas = _cabecalho_e_linhas(r)
    assert cab == ["Posição", "Aluno", "Turma", "Série", "Nota Matific",
                   "Nota Elefante", "Nota Geral"]
    completo = linhas

    _desligar(db, cenario, "matematica")
    cab, linhas = _cabecalho_e_linhas(_csv(admin, esc, "ranking"))
    assert cab == ["Posição", "Aluno", "Turma", "Série", "Nota Elefante", "Nota Geral"]
    # mesmas linhas, na mesma ordem, só sem a coluna
    assert linhas == [l[:4] + l[5:] for l in completo]

    svc_modulos.definir(db, cenario["rede"].id, "matematica", True)
    _desligar(db, cenario, "leitura")
    cab, linhas = _cabecalho_e_linhas(_csv(admin, esc, "ranking"))
    assert cab == ["Posição", "Aluno", "Turma", "Série", "Nota Matific", "Nota Geral"]
    assert linhas == [l[:5] + l[6:] for l in completo]


def test_cartaz_do_ranking_geral_sem_a_coluna_do_modulo_fora_do_plano(db, cenario):
    """O pôster do Ranking Geral (GET /ranking/cartaz) segue a mesma regra do
    relatório: a nota da plataforma fora do plano não vai para o PDF."""
    esc, admin = cenario["escola"], cenario["admin"]
    recebidos = []

    def capturar(**kw):
        recebidos.append(kw["cabecalho"])
        return b"%PDF-1.4 sintetico"

    with patch.object(svc_relatorios, "gerar_cartaz_ranking", side_effect=capturar):
        assert admin.get(f"{API}/escolas/{esc.id}/ranking/cartaz").status_code == 200
        _desligar(db, cenario, "matematica")
        assert admin.get(f"{API}/escolas/{esc.id}/ranking/cartaz").status_code == 200
    assert "Nota Matific" in recebidos[0] and "Nota Elefante" in recebidos[0]
    assert "Nota Matific" not in recebidos[1] and "Nota Elefante" in recebidos[1]


def test_sem_notas_fora_do_plano_com_tudo_contratado_devolve_o_mesmo():
    cab = ["Posição", "Aluno", "Turma", "Série", "Nota Matific", "Nota Elefante",
           "Nota Geral"]
    linhas = [[1, "A", "3ºA", "3º Ano", 7.0, 8.0, 7.5]]
    assert svc_relatorios.sem_notas_fora_do_plano(cab, linhas, {"leitura", "matematica"}) \
        == (cab, linhas)
    cab2, linhas2 = svc_relatorios.sem_notas_fora_do_plano(cab, linhas, {"leitura"})
    assert cab2 == ["Posição", "Aluno", "Turma", "Série", "Nota Elefante", "Nota Geral"]
    assert linhas2 == [[1, "A", "3ºA", "3º Ano", 8.0, 7.5]]


def test_cartaz_do_ranking_acompanha_as_colunas():
    """O PDF (cartaz) do Ranking monta cabeçalho e células pelo cabeçalho que
    recebe: completo = exatamente o HTML de antes; sem Matemática, a coluna
    Nota Matific some do <thead> e de cada linha."""
    cab = ["Posição", "Aluno", "Turma", "Série", "Nota Matific", "Nota Elefante",
           "Nota Geral"]
    linha = [1, "Ana", "3ºA", "3º Ano", 7.0, 8.0, 7.5]
    completo = svc_relatorios._linhas_cartaz_html([linha], cab)
    # HTML fixado à mão a partir da versão anterior (sem cabeçalho dinâmico):
    # as duas células de nota da plataforma, nesta ordem, entre Série e Geral.
    antes = ('<tr class="top"><td class="pos"><span class="medalha m1">1</span></td>'
             '<td class="aluno">Ana</td><td class="turma">3ºA</td>'
             '<td class="serie">3º Ano</td><td>7,0</td><td>8,0</td>'
             '<td class="geral">7,5</td></tr>')
    assert completo == antes
    assert svc_relatorios._linhas_cartaz_html([linha]) == antes        # padrão = antes
    assert svc_relatorios._th_notas_cartaz(cab) == (
        "<th>⟦IC_STAR⟧Nota Matific</th><th>⟦IC_ELE⟧Nota Elefante</th>")
    cab2, [linha2] = svc_relatorios.sem_notas_fora_do_plano(cab, [linha], {"leitura"})
    reduzido = svc_relatorios._linhas_cartaz_html([linha2], cab2)
    assert reduzido.count("<td>") == 1 and "8,0" in reduzido and "7,0" not in reduzido
    assert svc_relatorios._th_notas_cartaz(cab2) == "<th>⟦IC_ELE⟧Nota Elefante</th>"


# --- Certificado com a arte da plataforma -------------------------------------

@pytest.mark.parametrize("modelo, modulo, outro", [
    ("matific", "matematica", "elefante"),
    ("elefante", "leitura", "matific"),
])
def test_certificado_da_plataforma_exige_o_modulo(db, cenario, modelo, modulo, outro):
    esc, aluno, admin = cenario["escola"], cenario["alunos"][0], cenario["admin"]
    url = f"{API}/escolas/{esc.id}/certificados/{aluno.id}"
    with patch("app.services.relatorios.gerar_certificado_plataforma",
               return_value=b"%PDF-fake"):
        assert admin.get(url, params={"modelo": modelo}).status_code == 200
        _desligar(db, cenario, modulo)
        r = admin.get(url, params={"modelo": modelo})
        assert r.status_code == 403 and "plano" in r.json()["detail"].lower()
        # a arte da outra plataforma (módulo contratado) continua saindo
        assert admin.get(url, params={"modelo": outro}).status_code == 200


# --- Listas legadas com nota por plataforma ------------------------------------

def _ordem_e_notas(itens):
    return ([i["aluno_id"] for i in itens],
            {i["aluno_id"]: (i["nota_matific"], i["nota_elefante"], i["nota_geral"])
             for i in itens})


def test_listas_legadas_anulam_a_nota_do_modulo_fora_do_plano(db, cenario):
    esc, admin = cenario["escola"], cenario["admin"]
    rotas = {
        "ranking": lambda: admin.get(f"{API}/escolas/{esc.id}/ranking").json(),
        "top10": lambda: admin.get(f"{API}/escolas/{esc.id}/dashboard").json()["top10"],
        "mobile": lambda: admin.get(f"{API}/escolas/{esc.id}/sincronizacao").json()["ranking"],
        "mobile_top10": lambda: admin.get(
            f"{API}/escolas/{esc.id}/sincronizacao").json()["dashboard"]["top10"],
    }
    antes = {nome: _ordem_e_notas(f()) for nome, f in rotas.items()}
    for nome, (ordem, notas) in antes.items():
        assert ordem, nome
        assert all(m is not None and e is not None for m, e, _ in notas.values()), nome

    _desligar(db, cenario, "matematica")
    for nome, f in rotas.items():
        ordem, notas = _ordem_e_notas(f())
        assert ordem == antes[nome][0], nome                     # ordenação intacta
        for aid, (m, e, g) in notas.items():
            m0, e0, g0 = antes[nome][1][aid]
            assert m is None and (e, g) == (e0, g0), nome

    svc_modulos.definir(db, cenario["rede"].id, "matematica", True)
    _desligar(db, cenario, "leitura")
    for nome, f in rotas.items():
        ordem, notas = _ordem_e_notas(f())
        assert ordem == antes[nome][0], nome
        for aid, (m, e, g) in notas.items():
            m0, e0, g0 = antes[nome][1][aid]
            assert e is None and (m, g) == (m0, g0), nome
