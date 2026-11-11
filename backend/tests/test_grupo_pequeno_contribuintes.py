"""GRUPO PEQUENO por CONTRIBUINTES: ter retrato não é somar no total.

Resíduo da revisão das correções de grupo pequeno (turma e escola). O k contava
quem TEM retrato da plataforma, mas o import do relatório da turma grava um
retrato para cada linha, inclusive as zeradas. No começo do piloto, "20
matriculados, 1 lê" chega como 20 retratos: a proteção não disparava e a
Secretaria via, no cartão da rede, no lado "escola" do comparador e no resumo
por turma, os livros, o tempo e as questões DAQUELA criança, e uma média que,
vezes os 20 da conta, é a nota dela. O mesmo no Matific (estrelas [x, 0, 0]).

Agora, só para a Secretaria, contam também os contribuintes de cada campo
somado (quem tem o campo > 0) e, na média, quem tem nota > 0: de 1 a
``K_MINIMO_TURMA - 1`` é grupo pequeno da matéria inteira. O Admin Global e a
gestão da escola recebem exatamente a resposta de sempre. Dados sintéticos.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import (Aluno, Escola, Importacao, Matricula, Nota, Rede, SnapshotElefante,
                        SnapshotMatific, Turma, Usuario)
from app.services import evolucao as svc_evolucao
from app.services import grupo_pequeno, scoring
from app.services import rede as svc_rede
from app.services import relatorios as svc_relatorios
from tests._ano_letivo import ANO

API = "/api/v1"
GP = grupo_pequeno.MOTIVO_GRUPO_PEQUENO
COMPLEMENTAR = grupo_pequeno.MOTIVO_COMPLEMENTAR
_SENHA = "s3nh4"
# Os campos do cartão da rede que somem com cada matéria (o contrato da tela).
CAMPOS_LEITURA = ("media_elefante", "livros", "tempo_leitura_min", "livros_por_aluno",
                  "livros_premiaveis", "tempo_premiaveis_min", "livros_por_matricula",
                  "tempo_por_matricula_min", "pontuacao_leitura")
CAMPOS_MATEMATICA = ("media_matific", "atividades", "estrelas", "atividades_premiaveis",
                     "estrelas_premiaveis", "atividades_por_matricula",
                     "estrelas_por_matricula", "pontuacao_matematica")
# Números da criança que lê sozinha (escolhidos para não colidir com ids).
LIVROS, TEMPO, TENTATIVAS, ACERTOS, NOTA = 419, 947, 313, 211, 91.3
# ...e da que soma sozinha no Matific.
ATIVIDADES, ESTRELAS, PONTUACAO, NOTA_MAT = 417, 1123, 81.7, 73.3


def _login(email: str) -> TestClient:
    c = TestClient(app)
    r = c.post(f"{API}/auth/login", data={"username": email, "password": _SENHA})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _numeros(no) -> list:
    """Todos os números (folhas) de uma resposta JSON."""
    if isinstance(no, dict):
        return [n for v in no.values() for n in _numeros(v)]
    if isinstance(no, list):
        return [n for v in no for n in _numeros(v)]
    return [no] if isinstance(no, (int, float)) and not isinstance(no, bool) else []


def _escola(db, rede_id, nome, *, livros, notas, questoes=None, matific=None,
            fase_livros=()):
    """Escola com uma turma do 3º ano: cada criança tem retrato do Elefante (com
    ``livros[i]``; o tempo acompanha os livros) e nota carimbada ``notas[i]``,
    como depois do import do relatório da turma e do recálculo. ``matific`` =
    lista de (atividades, estrelas, pontuação, nota) da mesma criança.
    ``fase_livros``: crianças da 1ª Fase (não concorrem), só com retrato."""
    esc = Escola(nome=nome, ano_letivo_ativo=ANO, rede_id=rede_id, status="ativa")
    db.add(esc)
    db.flush()
    imp = Importacao(escola_id=esc.id, plataforma="seed", tipo="seed")
    terceiro = Turma(escola_id=esc.id, nome="3o Ano A", ano_escolar="3º Ano",
                     ano_letivo=ANO, status="ativa")
    fase = Turma(escola_id=esc.id, nome="1a Fase A", ano_escolar="1ª Fase",
                 ano_letivo=ANO, status="ativa")
    db.add_all([imp, terceiro, fase])
    db.flush()
    ontem = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)

    def _crianca(turma, i, qtd_livros, tentativas_acertos=(0, 0)):
        a = Aluno(escola_id=esc.id, nome=f"ALUNO_SINT {nome} {turma.nome} {i}")
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=esc.id, aluno_id=a.id, turma_id=turma.id, ano_letivo=ANO))
        tempo = TEMPO if qtd_livros == LIVROS else qtd_livros * 10
        db.add(SnapshotElefante(escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
                                data_referencia=ontem, livros_unicos=qtd_livros,
                                tempo_leitura_min=tempo,
                                questoes_tentativas=tentativas_acertos[0],
                                questoes_acertos=tentativas_acertos[1]))
        return a

    for i, qtd in enumerate(livros):
        a = _crianca(terceiro, i, qtd, (questoes or {}).get(i, (0, 0)))
        atividades, estrelas, pontuacao, nota_mat = (matific[i] if matific else (0, 0, 0.0, 0.0))
        if matific:
            db.add(SnapshotMatific(escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
                                   data_referencia=ontem, atividades=atividades,
                                   estrelas=estrelas, pontuacao_media=pontuacao))
        db.add(Nota(detalhes=scoring.carimbo_institucional(), escola_id=esc.id,
                    aluno_id=a.id, ano_letivo=ANO, nota_geral=notas[i],
                    nota_elefante=notas[i], nota_elefante_institucional=notas[i],
                    aferido_leitura=True, nota_matific=nota_mat,
                    nota_matific_institucional=nota_mat, aferido_matematica=bool(matific)))
    for i, qtd in enumerate(fase_livros):
        _crianca(fase, i, qtd)
    return esc, terceiro, fase


@pytest.fixture()
def rede(db):
    rede = Rede(nome="REDE_SINT_CONTRIB", status="ativa")
    db.add(rede)
    db.flush()
    zeros = [0] * 19
    # 20 retratos, 1 criança leu (o cenário do revisor, como o import grava).
    um, um_turma, _ = _escola(db, rede.id, "Escola Um Leitor", livros=[LIVROS] + zeros,
                              notas=[NOTA] + [0.0] * 19,
                              questoes={0: (TENTATIVAS, ACERTOS)})
    # 20 retratos, 3 leram: o limite exato, segue visível.
    tres, _, _ = _escola(db, rede.id, "Escola Tres Leitores", livros=[4, 5, 6] + [0] * 17,
                         notas=[50.0, 60.0, 70.0] + [0.0] * 17)
    # 3 leram, mas só 1 tem nota > 0: a média × 3 é a nota dela.
    nota, _, _ = _escola(db, rede.id, "Escola Nota Isolada", livros=[5, 6, 7],
                         notas=[NOTA, 0.0, 0.0])
    # Leitura de 3 (visível); no Matific, 3 retratos e só 1 com estrelas.
    mat, _, _ = _escola(db, rede.id, "Escola Matematica Isolada", livros=[5, 5, 5],
                        notas=[60.0, 60.0, 60.0],
                        matific=[(ATIVIDADES, ESTRELAS, PONTUACAO, NOTA_MAT),
                                 (0, 0, 0.0, 0.0), (0, 0, 0.0, 0.0)])
    # 4 que concorrem leram; na 1ª Fase, 5 retratos e só 1 leu.
    fase, _, fase_turma = _escola(db, rede.id, "Escola Fase Isolada", livros=[5, 5, 5, 5],
                                  notas=[70.0] * 4, fase_livros=[9, 0, 0, 0, 0])
    contas = [("sec", Usuario(escola_id=None, nome="SEC", email="sec@contrib.local",
                              senha_hash=hash_senha(_SENHA), cargo="coordenador",
                              rede_id=rede.id)),
              ("global", Usuario(escola_id=um.id, nome="GLOBAL", email="global@contrib.local",
                                 senha_hash=hash_senha(_SENHA), cargo="admin",
                                 is_global=True)),
              ("coord", Usuario(escola_id=um.id, nome="COORD", email="coord@contrib.local",
                                senha_hash=hash_senha(_SENHA), cargo="coordenador"))]
    db.add_all([u for _, u in contas])
    db.commit()
    return {"db": db, "rede": rede, "um": um, "um_turma": um_turma, "tres": tres,
            "nota": nota, "mat": mat, "fase": fase, "fase_turma": fase_turma,
            **{papel: _login(u.email) for papel, u in contas}}


def _painel(cenario, perfil):
    r = cenario[perfil].get(f"{API}/redes/{cenario['rede'].id}/dashboard")
    assert r.status_code == 200, r.text
    painel = r.json()
    return painel, {c["nome"]: c for c in painel["escolas"]}


def _comparar(cenario, perfil, escola, tipo_a, id_a):
    r = cenario[perfil].get(f"{API}/escolas/{escola.id}/comparar",
                            params={"tipo_a": tipo_a, "id_a": id_a,
                                    "tipo_b": "escola", "id_b": escola.id})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Leitura: 20 retratos, 1 leitor
# ---------------------------------------------------------------------------

def test_um_leitor_em_vinte_retratos_some_do_cartao_da_secretaria(rede):
    painel, cartoes = _painel(rede, "sec")
    um = cartoes["Escola Um Leitor"]
    for campo in CAMPOS_LEITURA:
        assert um[campo] is None, campo
    assert um["oculto"]["leitura"] == grupo_pequeno.bloco_oculto_escola(GP)
    assert um["grupo_pequeno"] is True and um["comparada"] is False
    # As contagens que o k olhava antes continuam: 20 retratos, 20 na média.
    assert um["ativos_elefante"] == 20 and um["alunos_com_nota_elefante"] == 20
    # Quem soma (o k da decisão) não sai no cartão da Secretaria.
    for c in painel["escolas"]:
        assert "com_livros_premiaveis" not in c and "com_estrelas_premiaveis" not in c
        assert "_contribuintes" not in c
    assert "Escola Um Leitor" in [o["nome"] for o in painel["ocultas"]]
    # Nem o cartão nem o total da rede trazem os números da criança.
    assert not {LIVROS, TEMPO} & set(_numeros(painel))
    assert "ALUNO_SINT" not in str(painel)


def test_um_leitor_comparador_resumo_e_ranking_de_turmas_da_secretaria(rede):
    um, turma = rede["um"], rede["um_turma"]
    resposta = _comparar(rede, "sec", um, "turma", turma.id)
    for lado in (resposta["a"], resposta["b"]):
        for chave in ("livros_unicos", "tempo_leitura_min", "questoes_tentativas",
                      "questoes_acertos"):
            assert lado["indicadores"][chave] is None, (lado["tipo"], chave)
        assert lado["dimensoes"]["leitura"]["nota"] is None
        assert lado["dimensoes"]["leitura"]["oculto"]["motivo"] == GP
        assert lado["notas"]["elefante"] is None
        assert not {"_aferidos", "_contribuintes"} & set(lado)
    # Lado turma: média da turma nula; lado escola: o texto da escola.
    assert resposta["b"]["dimensoes"]["leitura"]["oculto"]["texto"] == \
        grupo_pequeno.TEXTOS_ESCOLA[GP]
    assert not {LIVROS, TEMPO, TENTATIVAS, ACERTOS} & set(_numeros(resposta))

    r = rede["sec"].get(f"{API}/escolas/{um.id}/resumo-escola")
    assert r.status_code == 200, r.text
    [linha] = [t for t in r.json()["turmas"] if t["turma"]["id"] == turma.id]
    assert linha["media_leitura"] is None and linha["media_geral"] is None
    assert linha["indicadores"]["livros_unicos"] is None
    assert linha["oculto"]["leitura"]["motivo"] == GP
    assert linha["n_leitura"] == 20
    assert not {"_aferidos", "_contribuintes"} & set(linha)
    assert not {LIVROS, TEMPO, TENTATIVAS, ACERTOS} & set(_numeros(r.json()))

    rk = rede["sec"].get(f"{API}/escolas/{um.id}/ranking/turmas",
                         params={"dimensao": "leitura"}).json()
    assert turma.id not in [i["turma_id"] for i in rk["itens"]]
    assert [o["turma_id"] for o in rk["ocultas"]] == [turma.id]


@pytest.mark.parametrize("perfil", ["coord", "global"])
def test_um_leitor_gestao_e_admin_global_como_antes(rede, perfil):
    db, um, turma = rede["db"], rede["um"], rede["um_turma"]
    resposta = _comparar(rede, perfil, um, "turma", turma.id)
    assert resposta == svc_evolucao.comparar(db, um.id, "turma", turma.id, "escola", um.id)
    # O cenário revelava: quem vê tudo vê os números da criança.
    assert resposta["b"]["indicadores"]["livros_unicos"] == LIVROS
    resumo = rede[perfil].get(f"{API}/escolas/{um.id}/resumo-escola").json()
    assert resumo == svc_evolucao.resumo_escola(db, um.id)
    rk = rede[perfil].get(f"{API}/escolas/{um.id}/ranking/turmas",
                          params={"dimensao": "leitura"}).json()
    assert [i["turma_id"] for i in rk["itens"]] == [turma.id] and "ocultas" not in rk


def test_painel_e_ranking_da_rede_do_admin_global_iguais_ao_servico(rede):
    db, rid = rede["db"], rede["rede"].id
    painel, cartoes = _painel(rede, "global")
    assert painel == svc_rede.dashboard_rede(db, rid)
    assert cartoes["Escola Um Leitor"]["livros"] == LIVROS
    assert cartoes["Escola Um Leitor"]["com_livros_premiaveis"] == 1
    for metrica in ("geral", "livros_aluno", "estrelas_aluno", "elefante", "engajamento"):
        resposta = rede["global"].get(f"{API}/redes/{rid}/ranking",
                                      params={"metrica": metrica}).json()
        assert resposta == svc_rede.ranking_escolas(db, rid, limite=50, metrica=metrica)


def test_tres_leitores_em_vinte_retratos_seguem_visiveis(rede):
    _, cartoes = _painel(rede, "sec")
    tres = cartoes["Escola Tres Leitores"]
    assert tres["oculto"]["leitura"] is None and tres["grupo_pequeno"] is False
    assert tres["livros"] == 15 and tres["media_elefante"] == 9.0
    assert tres["comparada"] is True


def test_totais_da_rede_da_secretaria_so_com_quem_soma_visivel(rede):
    painel, cartoes = _painel(rede, "sec")
    visiveis = [c for c in cartoes.values() if c["livros"] is not None]
    assert {c["nome"] for c in visiveis} == {"Escola Tres Leitores",
                                             "Escola Matematica Isolada"}
    assert painel["totais"]["livros"] == sum(c["livros"] for c in visiveis) == 15 + 15
    assert painel["totais"]["grupo_pequeno"]["leitura"] == 3
    assert painel["totais"]["grupo_pequeno"]["matematica"] == 1
    adm, _ = _painel(rede, "global")
    assert adm["totais"]["livros"] == LIVROS + 15 + 18 + 15 + 20 + 9


# ---------------------------------------------------------------------------
# A média: 3 com dado, só 1 com nota > 0
# ---------------------------------------------------------------------------

def test_nota_isolada_esconde_a_media_da_escola_e_da_turma(rede):
    _, cartoes = _painel(rede, "sec")
    cartao = cartoes["Escola Nota Isolada"]
    assert cartao["media_elefante"] is None and cartao["livros"] is None
    assert cartao["oculto"]["leitura"]["motivo"] == GP
    escola = rede["nota"]
    lado = _comparar(rede, "sec", escola, "escola", escola.id)["a"]
    assert lado["dimensoes"]["leitura"]["nota"] is None and lado["notas"]["elefante"] is None
    resumo = rede["sec"].get(f"{API}/escolas/{escola.id}/resumo-escola").json()
    [linha] = [t for t in resumo["turmas"] if t["n_leitura"]]
    assert linha["media_leitura"] is None
    # Para quem vê tudo, média × 3 = a nota da criança.
    _, adm = _painel(rede, "global")
    assert adm["Escola Nota Isolada"]["media_elefante"] * 3 == pytest.approx(NOTA, abs=0.2)


# ---------------------------------------------------------------------------
# Matemática: estrelas [x, 0, 0]
# ---------------------------------------------------------------------------

def test_estrelas_de_uma_crianca_somem_e_a_leitura_fica(rede):
    rid = rede["rede"].id
    _, cartoes = _painel(rede, "sec")
    cartao = cartoes["Escola Matematica Isolada"]
    for campo in CAMPOS_MATEMATICA:
        assert cartao[campo] is None, campo
    assert cartao["oculto"]["matematica"]["motivo"] == GP
    assert cartao["oculto"]["leitura"] is None and cartao["livros"] == 15
    # Segue comparada pela leitura: a geral é só a matéria visível.
    assert cartao["comparada"] is True and cartao["media_geral"] == 60.0
    assert cartao["dimensoes_pontuadas"] == ["leitura"]
    sec = rede["sec"]
    estrelas = sec.get(f"{API}/redes/{rid}/ranking", params={"metrica": "estrelas_aluno"}).json()
    assert "Escola Matematica Isolada" not in [c["nome"] for c in estrelas]
    geral = sec.get(f"{API}/redes/{rid}/ranking", params={"metrica": "geral"}).json()
    assert "Escola Matematica Isolada" in [c["nome"] for c in geral]

    escola = rede["mat"]
    lado = _comparar(rede, "sec", escola, "escola", escola.id)["a"]
    for chave in ("atividades", "estrelas", "pontuacao_media"):
        assert lado["indicadores"][chave] is None, chave
    assert lado["notas"]["matific"] is None and lado["notas"]["geral"] == 60.0
    assert lado["indicadores"]["livros_unicos"] == 15
    resumo = sec.get(f"{API}/escolas/{escola.id}/resumo-escola").json()
    [linha] = [t for t in resumo["turmas"] if t["n_leitura"]]
    assert linha["media_matematica"] is None and linha["indicadores"]["estrelas"] is None
    assert linha["media_leitura"] == 60.0
    for corpo in (cartoes, lado, resumo):
        assert not {ATIVIDADES, ESTRELAS, PONTUACAO} & set(_numeros(corpo))


# ---------------------------------------------------------------------------
# Complementar: 1 leitor entre os 5 retratos da 1ª Fase
# ---------------------------------------------------------------------------

def test_um_leitor_na_fase_esconde_so_os_totais_de_todos(rede):
    _, cartoes = _painel(rede, "sec")
    cartao = cartoes["Escola Fase Isolada"]
    # Retratos: 9 de todos − 4 de quem concorre = 5 (passaria). Quem soma: 5 − 4 = 1.
    assert cartao["oculto"]["leitura"] == grupo_pequeno.bloco_oculto_escola(COMPLEMENTAR)
    assert cartao["livros"] is None and cartao["tempo_leitura_min"] is None
    assert cartao["livros_premiaveis"] == 20 and cartao["media_elefante"] == 70.0
    assert cartao["comparada"] is True
    escola, fase = rede["fase"], rede["fase_turma"]
    lado = _comparar(rede, "sec", escola, "escola", escola.id)["a"]
    assert lado["indicadores"]["livros_unicos"] is None
    assert lado["dimensoes"]["leitura"]["nota"] == 70.0
    resumo = rede["sec"].get(f"{API}/escolas/{escola.id}/resumo-escola").json()
    [linha] = [t for t in resumo["turmas"] if t["turma"]["id"] == fase.id]
    assert linha["indicadores"]["livros_unicos"] is None
    assert linha["oculto"]["leitura"]["motivo"] == GP
    _, adm = _painel(rede, "global")
    assert adm["Escola Fase Isolada"]["livros"] == 29


# ---------------------------------------------------------------------------
# Boletim da rede (Secretaria)
# ---------------------------------------------------------------------------

def test_boletim_da_secretaria_diz_o_motivo_certo_e_a_protecao(rede):
    db, rid = rede["db"], rede["rede"].id
    dados = svc_rede.dashboard_rede(db, rid, secretaria=True)
    html = svc_relatorios._shell_boletim_rede("Rede Sintetica", dados)
    fora = html.split("Escolas fora da comparação", 1)[1].split("</table>", 1)[0]
    assert "Escola Um Leitor" in fora and "Escola Nota Isolada" in fora
    assert "Sem aluno do 1º ao 5º ano" not in fora
    assert "Leitura: " + grupo_pequeno.TEXTOS_ESCOLA[GP] in fora
    assert grupo_pequeno.TEXTO_FORA_DOS_TOTAIS_DA_REDE in html
    ranking = html.split("Ranking das escolas", 1)[1].split("</table>", 1)[0]
    assert "None" not in ranking and "Escola Matematica Isolada" in ranking
    # A reserva fpdf usa as mesmas linhas: a média escondida é '—', nunca None.
    cabecalho, linhas = svc_relatorios.linhas_boletim_rede(dados)
    [mat] = [linha for linha in linhas if linha[1] == "Escola Matematica Isolada"]
    assert mat[cabecalho.index("Matific")] == "—"
    assert mat[cabecalho.index("Elefante")] == "60,0"
    assert all(v is not None for linha in linhas for v in linha)


def test_boletim_sem_escola_escondida_mantem_o_texto_de_sem_dado():
    dados = {"totais": {}, "equidade": {}, "escolas": [
        {"nome": "EM Fase Ficticia", "comparada": False, "total_alunos": 5,
         "adocao": 100.0, "media_matific": 0.0, "media_elefante": 0.0,
         "media_geral": 0.0}]}
    html = svc_relatorios._shell_boletim_rede("Rede Ficticia", dados)
    fora = html.split("Escolas fora da comparação", 1)[1].split("</table>", 1)[0]
    assert "Sem aluno do 1º ao 5º ano" in fora
    assert "Proteção das crianças" not in html
    # A escola fora da comparação não tem "desempenho a comparar": o boletim mede
    # o uso das plataformas.
    assert "não há o que comparar com as demais escolas" in fora
    assert "desempenho" not in html.lower()


# ---------------------------------------------------------------------------
# As decisões puras
# ---------------------------------------------------------------------------

def _cont(media, todos, concorrem, *, positiva=None, somam=None, somam_concorrem=None):
    return {"media": media, "indicadores": todos, "concorrem": concorrem,
            "media_positiva": media if positiva is None else positiva,
            "contribuintes": somam or {}, "contribuintes_concorrem": somam_concorrem or {}}


@pytest.mark.parametrize(("contagem", "motivo"), [
    # 20 retratos, 1 leu: os livros são dela.
    (_cont(20, 20, 20, positiva=1, somam={"livros_unicos": 1, "tempo_leitura_min": 1},
           somam_concorrem={"livros_unicos": 1, "tempo_leitura_min": 1}), GP),
    # 3 leram: o limite exato.
    (_cont(20, 20, 20, positiva=3, somam={"livros_unicos": 3, "tempo_leitura_min": 3},
           somam_concorrem={"livros_unicos": 3, "tempo_leitura_min": 3}), None),
    # Todos leram, mas só 1 tem nota > 0 na média.
    (_cont(3, 3, 3, positiva=1, somam={"livros_unicos": 3},
           somam_concorrem={"livros_unicos": 3}), GP),
    # Ninguém leu ainda: total 0, nada a esconder.
    (_cont(20, 20, 20, positiva=0, somam={"livros_unicos": 0},
           somam_concorrem={"livros_unicos": 0}), None),
    # Só o tempo tem 2 que somam (o campo, não a matéria, é o que conta).
    (_cont(9, 9, 9, somam={"livros_unicos": 9, "tempo_leitura_min": 2},
           somam_concorrem={"livros_unicos": 9, "tempo_leitura_min": 2}), GP),
    # Questões (só no comparador, sem par de quem concorre): 1 que soma.
    (_cont(9, 9, 9, somam={"livros_unicos": 9, "questoes_acertos": 1},
           somam_concorrem={"livros_unicos": 9}), GP),
    # 1 leitor da Fase: só "todos − quem concorre" em quem soma.
    (_cont(4, 9, 4, somam={"livros_unicos": 5}, somam_concorrem={"livros_unicos": 4}),
     COMPLEMENTAR),
    # 3 leitores da Fase: ninguém isolado.
    (_cont(4, 9, 4, somam={"livros_unicos": 7}, somam_concorrem={"livros_unicos": 4}), None),
])
def test_decidir_escola_conta_quem_soma(contagem, motivo):
    assert grupo_pequeno.decidir_escola({"leitura": contagem}) == {
        "leitura": motivo, "matematica": None}


def _t(tid, serie, n, *, aferidos=None, contrib=None):
    return {"turma": {"id": tid, "ano_escolar": serie},
            "n_leitura": n, "n_matematica": 0,
            "_aferidos": {"leitura": n if aferidos is None else aferidos, "matematica": 0},
            "_contribuintes": {"leitura": contrib or {}, "matematica": {}}}


def test_decidir_turma_conta_quem_soma_e_quem_tem_nota():
    leu_um = {"nota": 1, "livros_unicos": 1, "tempo_leitura_min": 1}
    leram = {"nota": 9, "livros_unicos": 9, "tempo_leitura_min": 9}
    turmas = [_t(1, "3º Ano", 20, contrib=leu_um),   # 20 retratos, 1 leu
              _t(2, "3º Ano", 9, contrib=leram),     # complemento da série
              _t(3, "4º Ano", 9, contrib=leram)]
    m = grupo_pequeno.decidir(turmas, premiaveis={1, 2, 3})
    assert m[1]["leitura"] == GP
    assert m[2]["leitura"] == COMPLEMENTAR
    assert m[3]["leitura"] is None


def test_complemento_vem_de_quem_tem_alguem_na_coluna_em_falta():
    # A turma 2 (menor) não tem ninguém que leu: escondê-la não mudaria a soma
    # dos livros escondidos (1). O complemento é a turma 3, que tem leitores.
    turmas = [_t(1, "3º Ano", 20, contrib={"nota": 1, "livros_unicos": 1}),
              _t(2, "3º Ano", 4, contrib={"nota": 0, "livros_unicos": 0}),
              _t(3, "3º Ano", 9, contrib={"nota": 9, "livros_unicos": 9})]
    m = grupo_pequeno.decidir(turmas, premiaveis={1, 2, 3})
    assert (m[1]["leitura"], m[2]["leitura"], m[3]["leitura"]) == (GP, None, COMPLEMENTAR)
