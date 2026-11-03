"""GRUPO PEQUENO no nível da ESCOLA: a Secretaria não recebe o número de UMA
criança pelo cartão da escola, pelo ranking da rede nem pelo lado "escola" do
comparador.

Residual da correção das turmas (``test_grupo_pequeno_secretaria.py``): com uma
escola de 20 matriculados e só 1 aluno com retrato do Elefante, a turma já saía
escondida, mas ``/comparar`` (turma × escola), ``/redes/{id}/dashboard`` e
``/redes/{id}/ranking`` entregavam no lado/cartão da ESCOLA os livros, o tempo,
as questões e a nota DAQUELA criança — e, no nível "concorre", a média da escola
(só quem concorre) era a da criança quando a única outra turma com dado era uma
Fase.

Agora, só para a Secretaria: a matéria da escola com 1 a ``K_MINIMO_TURMA - 1``
crianças com dado sai nula com a marca ``oculto``; a escola sai da ordem do
ranking dessa matéria; os totais e as médias da rede deixam a matéria escondida
de fora (somá-la e escondê-la só no cartão devolveria a criança por subtração);
e a régua do índice é a melhor escola VISÍVEL. O Admin Global e a gestão da
escola recebem a resposta de sempre. Dados sintéticos.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import (Aluno, Escola, Importacao, Matricula, MetaRede, Nota, Rede,
                        ResultadoAvaliacao, SnapshotElefante, Turma, Usuario)
from app.services import avaliacoes as svc_avaliacoes
from app.services import evolucao as svc_evolucao
from app.services import grupo_pequeno, scoring
from app.services import rede as svc_rede

API = "/api/v1"
GP = grupo_pequeno.MOTIVO_GRUPO_PEQUENO
COMPLEMENTAR = grupo_pequeno.MOTIVO_COMPLEMENTAR
# O contrato da tela: os campos de Leitura do cartão que somem com a matéria.
CAMPOS_LEITURA = ("media_elefante", "livros", "tempo_leitura_min", "livros_por_aluno",
                  "livros_premiaveis", "tempo_premiaveis_min", "livros_por_matricula",
                  "tempo_por_matricula_min", "pontuacao_leitura")
# As chaves de sempre (as de antes desta correção) — o Admin Global e a gestão
# não podem ganhar nenhuma.
CHAVES_PAINEL = {"rede_id", "modulos", "totais", "equidade", "escolas", "atencao",
                 "recalculo_pendente"}
CHAVES_LADO_ESCOLA = {"tipo", "id", "nome", "total_alunos", "indicadores", "dimensoes",
                      "alcance", "notas"}
_SENHA = "s3nh4"


def _login(email: str) -> TestClient:
    c = TestClient(app)
    r = c.post(f"{API}/auth/login", data={"username": email, "password": _SENHA})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _usuarios(db, rede_id: int, escola_id: int | None = None, sufixo: str = "") -> dict:
    """Secretaria (cargo coordenador + rede, o pior caso), Admin Global e, se há
    escola, o coordenador dela (gestão da escola, sem rede)."""
    contas = [("sec", Usuario(escola_id=None, nome="SEC", email=f"sec{sufixo}@gpe.local",
                              senha_hash=hash_senha(_SENHA), cargo="coordenador",
                              rede_id=rede_id)),
              ("global", Usuario(escola_id=escola_id, nome="GLOBAL",
                                 email=f"global{sufixo}@gpe.local",
                                 senha_hash=hash_senha(_SENHA), cargo="admin",
                                 is_global=True))]
    if escola_id is not None:
        contas.append(("coord", Usuario(escola_id=escola_id, nome="COORD",
                                        email=f"coord{sufixo}@gpe.local",
                                        senha_hash=hash_senha(_SENHA), cargo="coordenador")))
    db.add_all([u for _, u in contas])
    db.commit()
    return {papel: _login(u.email) for papel, u in contas}


def _numeros(no) -> list:
    """Todos os números (folhas) de uma resposta JSON."""
    if isinstance(no, dict):
        return [n for v in no.values() for n in _numeros(v)]
    if isinstance(no, list):
        return [n for v in no for n in _numeros(v)]
    return [no] if isinstance(no, (int, float)) and not isinstance(no, bool) else []


# ---------------------------------------------------------------------------
# Cenário 1 — o do revisor: 20 matriculados, 1 aferido (motor de verdade)
# ---------------------------------------------------------------------------

@pytest.fixture()
def escola_de_um(db, escola_completa):
    escola = escola_completa["escola"]
    t4 = Turma(escola_id=escola.id, nome="4o Ano A", ano_escolar="4º Ano", ano_letivo=2026)
    db.add(t4)
    db.flush()
    alunos = []
    for i in range(20):
        a = Aluno(escola_id=escola.id, nome=f"ALUNO_SINT_{i:02d}")
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=t4.id, ano_letivo=2026))
        alunos.append(a)
    imp = Importacao(escola_id=escola.id, plataforma="elefante", tipo="seed")
    db.add(imp)
    db.flush()
    agora = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=alunos[7].id, importacao_id=imp.id,
                            data_referencia=agora - timedelta(days=1),
                            livros_unicos=19, tempo_leitura_min=47,
                            questoes_tentativas=13, questoes_acertos=11,
                            livros_por_nivel={"D": 19}))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    rede = Rede(nome="REDE_SINT_GPE", status="ativa")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    db.commit()
    return {"db": db, "escola": escola, "rede": rede, "t4": t4,
            **_usuarios(db, rede.id, escola.id)}


def _comparar_turma_escola(cenario, perfil):
    eid = cenario["escola"].id
    r = cenario[perfil].get(f"{API}/escolas/{eid}/comparar",
                            params={"tipo_a": "turma", "id_a": cenario["t4"].id,
                                    "tipo_b": "escola", "id_b": eid})
    assert r.status_code == 200, r.text
    return r.json()


def test_comparar_lado_escola_secretaria_sem_os_numeros_da_crianca(escola_de_um):
    escola = _comparar_turma_escola(escola_de_um, "sec")["b"]
    for chave in ("livros_unicos", "tempo_leitura_min", "questoes_tentativas",
                  "questoes_acertos"):
        assert escola["indicadores"][chave] is None, chave
    leitura = escola["dimensoes"]["leitura"]
    assert leitura["nota"] is None and leitura["n_aferidos"] == 1
    assert leitura["oculto"]["motivo"] == GP
    assert leitura["oculto"]["texto"] == grupo_pequeno.TEXTOS_ESCOLA[GP]
    assert "na escola" in leitura["oculto"]["texto"]
    assert leitura["oculto"]["parcial"] is False
    # A geral só teria a leitura: nula (sem matéria visível com dado).
    assert escola["notas"]["elefante"] is None and escola["notas"]["geral"] is None
    assert escola["grupo_pequeno"] is True
    assert escola["oculto"]["leitura"]["motivo"] == GP and escola["oculto"]["matematica"] is None
    assert "_aferidos" not in escola
    # A contagem (não o desempenho) continua: é ela que a tela explica.
    assert escola["total_alunos"] == 23
    assert not {19, 47, 100.0} & set(_numeros(escola))


@pytest.mark.parametrize("perfil", ["coord", "global"])
def test_comparar_lado_escola_gestao_e_admin_global_como_antes(escola_de_um, perfil):
    resposta = _comparar_turma_escola(escola_de_um, perfil)
    escola = resposta["b"]
    assert set(escola) == CHAVES_LADO_ESCOLA
    ind = escola["indicadores"]
    assert (ind["livros_unicos"], ind["tempo_leitura_min"],
            ind["questoes_tentativas"], ind["questoes_acertos"]) == (19, 47, 13, 11)
    assert escola["dimensoes"]["leitura"]["nota"] > 0
    assert "oculto" not in escola["dimensoes"]["leitura"]
    # A resposta inteira é a do serviço sem proteção, chave por chave.
    db, eid = escola_de_um["db"], escola_de_um["escola"].id
    assert resposta == svc_evolucao.comparar(db, eid, "turma", escola_de_um["t4"].id,
                                             "escola", eid)


def test_painel_da_rede_secretaria_esconde_a_escola_de_uma_crianca(escola_de_um):
    rid, eid = escola_de_um["rede"].id, escola_de_um["escola"].id
    r = escola_de_um["sec"].get(f"{API}/redes/{rid}/dashboard")
    assert r.status_code == 200, r.text
    painel = r.json()
    [cartao] = painel["escolas"]
    for campo in CAMPOS_LEITURA:
        assert cartao[campo] is None, campo
    assert cartao["media_geral"] is None and cartao["pontuacao_geral"] is None
    assert cartao["oculto"]["leitura"] == grupo_pequeno.bloco_oculto_escola(GP)
    assert cartao["oculto"]["matematica"] is None and cartao["grupo_pequeno"] is True
    # Sem matéria pontuada visível: fora da comparação, sem posição.
    assert cartao["comparada"] is False and cartao["posicao"] is None
    # As contagens seguem (são quantas crianças têm dado, não o desempenho).
    assert cartao["alunos_com_dados"] == 1 and cartao["ativos_elefante"] == 1
    # O total da rede não refaz a criança: a única escola com dado está escondida.
    totais = painel["totais"]
    for chave in ("livros", "tempo_leitura_min", "media_elefante", "livros_por_aluno",
                  "media_geral", "pontuacao_geral"):
        assert totais[chave] is None, chave
    assert totais["grupo_pequeno"]["leitura"] == 1
    assert totais["grupo_pequeno"]["matematica"] == 0
    assert totais["grupo_pequeno"]["texto"] == grupo_pequeno.TEXTO_FORA_DOS_TOTAIS_DA_REDE
    assert totais["melhor_escola"] is None
    assert painel["ocultas"] == [{"escola_id": eid, "nome": cartao["nome"],
                                  "grupo_pequeno": True, "oculto": cartao["oculto"]}]
    assert not {19, 47, 100.0} & set(_numeros(painel))
    assert "ALUNO_SINT" not in r.text


def test_painel_da_rede_admin_global_como_antes(escola_de_um):
    db, rid = escola_de_um["db"], escola_de_um["rede"].id
    r = escola_de_um["global"].get(f"{API}/redes/{rid}/dashboard")
    assert r.status_code == 200, r.text
    painel = r.json()
    assert set(painel) == CHAVES_PAINEL
    assert "grupo_pequeno" not in painel["totais"]
    [cartao] = painel["escolas"]
    chaves_kpi = set(svc_rede._kpis_da_rede(db, rid)[0])
    assert set(cartao) == chaves_kpi | {"comparada", "posicao"}
    assert (cartao["livros"], cartao["tempo_leitura_min"]) == (19, 47)
    assert cartao["media_elefante"] > 0 and cartao["comparada"] is True
    assert painel["totais"]["livros"] == 19
    assert painel == svc_rede.dashboard_rede(db, rid)


@pytest.mark.parametrize("metrica", ["geral", "indice_leitura", "livros_aluno",
                                     "elefante", "livros"])
def test_ranking_da_rede_secretaria_tira_a_escola_da_ordem(escola_de_um, metrica):
    rid, eid = escola_de_um["rede"].id, escola_de_um["escola"].id
    sec = escola_de_um["sec"].get(f"{API}/redes/{rid}/ranking", params={"metrica": metrica})
    assert sec.status_code == 200, sec.text
    assert eid not in [c["escola_id"] for c in sec.json()]
    adm = escola_de_um["global"].get(f"{API}/redes/{rid}/ranking",
                                     params={"metrica": metrica}).json()
    [item] = adm
    assert item["escola_id"] == eid and item["posicao"] == 1
    assert "oculto" not in item and "grupo_pequeno" not in item


def test_ranking_da_rede_engajamento_so_com_quem_a_secretaria_compara(escola_de_um):
    # A escola sem nenhuma matéria visível não é `comparada` para a Secretaria
    # (a mesma marca do painel): fica fora de todo ranking, até o de adoção.
    rid = escola_de_um["rede"].id
    assert escola_de_um["sec"].get(f"{API}/redes/{rid}/ranking",
                                   params={"metrica": "engajamento"}).json() == []


def test_metas_da_secretaria_nao_devolvem_o_total_escondido(escola_de_um):
    db, rid = escola_de_um["db"], escola_de_um["rede"].id
    db.add_all([MetaRede(rede_id=rid, metrica="livros", alvo=100.0),
                MetaRede(rede_id=rid, metrica="media_elefante", alvo=50.0)])
    db.commit()
    sec = {m["metrica"]: m for m in escola_de_um["sec"].get(f"{API}/redes/{rid}/metas").json()}
    assert sec["livros"]["atual"] == 0.0 and sec["livros"]["medida"] is False
    assert sec["media_elefante"]["atual"] == 0.0 and sec["media_elefante"]["medida"] is False
    adm = {m["metrica"]: m
           for m in escola_de_um["global"].get(f"{API}/redes/{rid}/metas").json()}
    assert adm["livros"]["atual"] == 19.0 and adm["livros"]["medida"] is True
    assert adm["media_elefante"]["medida"] is True


def test_boletim_da_secretaria_sai_sem_quebrar(escola_de_um):
    rid = escola_de_um["rede"].id
    r = escola_de_um["sec"].get(f"{API}/redes/{rid}/boletim")
    assert r.status_code == 200, r.text[:300]
    assert r.headers["content-type"] == "application/pdf"


# ---------------------------------------------------------------------------
# Cenário 2 — nível "concorre": a única outra turma com dado é uma Fase
# ---------------------------------------------------------------------------

@pytest.fixture()
def escola_com_fase(db, escola_completa):
    escola = escola_completa["escola"]
    imp = Importacao(escola_id=escola.id, plataforma="elefante", tipo="seed")
    db.add(imp)
    db.flush()
    agora = datetime.now(timezone.utc).replace(tzinfo=None)
    t4 = Turma(escola_id=escola.id, nome="4o Ano A", ano_escolar="4º Ano", ano_letivo=2026)
    fase = Turma(escola_id=escola.id, nome="1a Fase A", ano_escolar="1ª Fase", ano_letivo=2026)
    db.add_all([t4, fase])
    db.flush()
    leitor = None
    for turma, n, com_dado in ((t4, 5, 1), (fase, 4, 4)):
        for i in range(n):
            a = Aluno(escola_id=escola.id, nome=f"ALUNO_SINT {turma.nome} {i}")
            db.add(a)
            db.flush()
            db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id,
                             ano_letivo=2026))
            if i < com_dado:
                db.add(SnapshotElefante(escola_id=escola.id, aluno_id=a.id,
                                        importacao_id=imp.id,
                                        data_referencia=agora - timedelta(days=1),
                                        livros_unicos=6 + i, tempo_leitura_min=30,
                                        livros_por_nivel={"D": 6 + i}))
                leitor = leitor or (a if turma is t4 else None)
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    rede = Rede(nome="REDE_SINT_FASE", status="ativa")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    db.commit()
    return {"db": db, "escola": escola, "rede": rede, "t4": t4, "leitor": leitor,
            **_usuarios(db, rede.id, escola.id, sufixo=".fase")}


def test_media_da_escola_so_de_quem_concorre_nao_sai_igual_a_da_crianca(escola_com_fase):
    db, leitor = escola_com_fase["db"], escola_com_fase["leitor"]
    nota = db.query(Nota).filter_by(aluno_id=leitor.id).one().nota_elefante
    # O furo: para quem vê tudo, a média da escola (só quem concorre) É a nota dela.
    adm = _comparar_turma_escola(escola_com_fase, "coord")["b"]["dimensoes"]["leitura"]
    assert adm["n_aferidos"] == 1 and adm["nota"] == round(nota, 1)
    # Para a Secretaria, a matéria da escola sai inteira (média e totais), mesmo
    # com os 5 que têm dado (1 que concorre + 4 da Fase) somando mais de 3.
    sec = _comparar_turma_escola(escola_com_fase, "sec")["b"]
    assert sec["dimensoes"]["leitura"]["nota"] is None
    assert sec["dimensoes"]["leitura"]["oculto"]["motivo"] == GP
    assert sec["indicadores"]["livros_unicos"] is None
    rid = escola_com_fase["rede"].id
    [cartao] = escola_com_fase["sec"].get(f"{API}/redes/{rid}/dashboard").json()["escolas"]
    assert cartao["media_elefante"] is None and cartao["livros_premiaveis"] is None
    assert cartao["oculto"]["leitura"]["motivo"] == GP


# ---------------------------------------------------------------------------
# Rede sintética (notas semeadas com o carimbo institucional, como test_rede)
# ---------------------------------------------------------------------------

def _escola(db, rede_id, nome, *, concorrem, livros_cada, nota, fase=0, sem_dado=0,
            inep=None):
    """Escola com ``concorrem`` crianças com dado numa turma do 3º ano (nota +
    retrato do Elefante), ``sem_dado`` matriculadas sem retrato e ``fase``
    crianças com retrato numa turma da 1ª Fase (não concorrem). Só Leitura."""
    esc = Escola(nome=nome, ano_letivo_ativo=2026, rede_id=rede_id, status="ativa",
                 codigo_inep=inep)
    db.add(esc)
    db.flush()
    imp = Importacao(escola_id=esc.id, plataforma="seed", tipo="seed")
    terceiro = Turma(escola_id=esc.id, nome="3o Ano A", ano_escolar="3º Ano",
                     ano_letivo=2026, status="ativa")
    infantil = Turma(escola_id=esc.id, nome="1a Fase A", ano_escolar="1ª Fase",
                     ano_letivo=2026, status="ativa")
    db.add_all([imp, terceiro, infantil])
    db.flush()
    for i in range(concorrem + sem_dado + fase):
        turma = infantil if i >= concorrem + sem_dado else terceiro
        a = Aluno(escola_id=esc.id, nome=f"ALUNO_SINT {nome} {i}")
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=esc.id, aluno_id=a.id, turma_id=turma.id, ano_letivo=2026))
        if concorrem <= i < concorrem + sem_dado:
            continue
        db.add(SnapshotElefante(escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
                                livros_unicos=livros_cada, tempo_leitura_min=60))
        if turma is terceiro:
            db.add(Nota(detalhes=scoring.carimbo_institucional(), escola_id=esc.id,
                        aluno_id=a.id, ano_letivo=2026, nota_geral=nota,
                        nota_elefante=nota, nota_elefante_institucional=nota,
                        aferido_leitura=True))
    return esc


@pytest.fixture()
def rede_mista(db):
    """A: 2 crianças com dado (grupo pequeno) e o MAIOR per capita da rede (50
    livros por matrícula); B, C e D visíveis (5, 4 e 2 livros por matrícula)."""
    rede = Rede(nome="REDE_SINT_MISTA", status="ativa")
    db.add(rede)
    db.flush()
    e = {
        "a": _escola(db, rede.id, "Escola A", concorrem=2, livros_cada=50, nota=90.0,
                     inep="35000001"),
        "b": _escola(db, rede.id, "Escola B", concorrem=4, livros_cada=5, nota=60.0,
                     inep="35000002"),
        "c": _escola(db, rede.id, "Escola C", concorrem=3, livros_cada=4, nota=50.0,
                     inep="35000003"),
        "d": _escola(db, rede.id, "Escola D", concorrem=5, livros_cada=2, nota=40.0,
                     inep="35000004"),
    }
    db.commit()
    return {"db": db, "rede": rede, **e, **_usuarios(db, rede.id, sufixo=".mista")}


def _cartoes(cenario, perfil):
    r = cenario[perfil].get(f"{API}/redes/{cenario['rede'].id}/dashboard")
    assert r.status_code == 200, r.text
    painel = r.json()
    return painel, {c["nome"]: c for c in painel["escolas"]}


def test_totais_da_rede_da_secretaria_deixam_a_escola_escondida_de_fora(rede_mista):
    painel, cartoes = _cartoes(rede_mista, "sec")
    assert cartoes["Escola A"]["livros"] is None
    assert cartoes["Escola A"]["alunos_com_nota_elefante"] == 2
    # O total É a soma do que ela vê: "total − escolas visíveis" não devolve ninguém.
    visiveis = [c for c in cartoes.values() if c["livros"] is not None]
    assert painel["totais"]["livros"] == sum(c["livros"] for c in visiveis) == 20 + 12 + 10
    assert painel["totais"]["tempo_leitura_min"] == sum(c["tempo_leitura_min"]
                                                        for c in visiveis)
    assert painel["totais"]["media_elefante"] == round((4 * 60 + 3 * 50 + 5 * 40) / 12, 1)
    assert painel["totais"]["livros_por_aluno"] == round(42 / 12, 1)
    assert painel["totais"]["grupo_pequeno"]["leitura"] == 1
    assert [o["nome"] for o in painel["ocultas"]] == ["Escola A"]
    # Para o Admin Global, os totais de sempre (com a escola A).
    adm, _ = _cartoes(rede_mista, "global")
    assert adm["totais"]["livros"] == 100 + 42
    assert adm["totais"]["media_elefante"] == round(
        (2 * 90 + 4 * 60 + 3 * 50 + 5 * 40) / 14, 1)


def test_regua_do_indice_da_secretaria_e_a_melhor_escola_visivel(rede_mista):
    # A escola A (escondida) é a melhor per capita. Com ela de régua, o índice de
    # B (100 = 5/50) e o per capita de B (5, visível) devolveriam o per capita de
    # A — e, com as matrículas de A, os livros das duas crianças.
    _, sec = _cartoes(rede_mista, "sec")
    assert sec["Escola A"]["pontuacao_leitura"] is None
    assert sec["Escola A"]["livros_por_matricula"] is None
    assert sec["Escola B"]["pontuacao_leitura"] == 1000.0
    assert sec["Escola C"]["pontuacao_leitura"] == 800.0
    assert sec["Escola D"]["pontuacao_leitura"] == 400.0
    assert [sec[n]["posicao"] for n in ("Escola B", "Escola C", "Escola D")] == [1, 2, 3]
    assert sec["Escola A"]["posicao"] is None and sec["Escola A"]["comparada"] is False
    _, adm = _cartoes(rede_mista, "global")
    assert adm["Escola A"]["pontuacao_leitura"] == 1000.0
    assert adm["Escola B"]["pontuacao_leitura"] == 100.0
    ranking = rede_mista["sec"].get(f"{API}/redes/{rede_mista['rede'].id}/ranking",
                                    params={"metrica": "livros_aluno"}).json()
    assert [(c["posicao"], c["nome"]) for c in ranking] == [
        (1, "Escola B"), (2, "Escola C"), (3, "Escola D")]


def test_ranking_da_rede_admin_global_e_o_de_sempre(rede_mista):
    db, rid = rede_mista["db"], rede_mista["rede"].id
    for metrica in ("geral", "livros_aluno", "engajamento"):
        resposta = rede_mista["global"].get(f"{API}/redes/{rid}/ranking",
                                            params={"metrica": metrica}).json()
        assert resposta == svc_rede.ranking_escolas(db, rid, limite=50, metrica=metrica)
        assert resposta[0]["nome"] == "Escola A" or metrica == "engajamento"


def test_correlacao_da_secretaria_usa_o_que_ela_ve(rede_mista):
    db, rid = rede_mista["db"], rede_mista["rede"].id
    av = svc_avaliacoes.obter_avaliacao(db, "saresp")
    for chave, valor in (("a", 250.0), ("b", 230.0), ("c", 210.0), ("d", 190.0)):
        esc = rede_mista[chave]
        db.add(ResultadoAvaliacao(avaliacao_id=av.id, edicao=2024, rede_id=rid,
                                  escola_id=esc.id, codigo_inep=esc.codigo_inep,
                                  indicador="proficiencia", valor=valor, unidade="pontos"))
    db.commit()
    url = (f"{API}/redes/{rid}/avaliacoes/correlacao"
           "?avaliacao=saresp&indicador=proficiencia&edicao=2024")
    sec = rede_mista["sec"].get(url)
    assert sec.status_code == 200, sec.text
    sec = sec.json()
    pontos = {p["nome"]: p["x"] for p in sec["pontos"]}
    # A escola escondida sai do gráfico; as outras levam o índice que o painel
    # da Secretaria mostra (régua = melhor visível), não o cheio.
    assert pontos == {"Escola B": 1000.0, "Escola C": 800.0, "Escola D": 400.0}
    assert sec["n"] == 3
    assert sec["pearson"] == svc_avaliacoes._pearson(
        [(p["x"], p["y"]) for p in sec["pontos"]])
    adm = rede_mista["global"].get(url).json()
    assert adm["n"] == 4 and {p["nome"] for p in adm["pontos"]} >= {"Escola A"}


@pytest.fixture()
def rede_com_fase_pequena(db):
    """Escola com 4 crianças que concorrem com dado e 1 da 1ª Fase com dado: o
    cartão traz o total de todos e o de quem concorre — a diferença é a criança
    da Fase."""
    rede = Rede(nome="REDE_SINT_FASE_PEQ", status="ativa")
    db.add(rede)
    db.flush()
    esc = _escola(db, rede.id, "Escola F", concorrem=4, livros_cada=5, nota=70.0, fase=1)
    db.commit()
    return {"db": db, "rede": rede, "escola": esc, **_usuarios(db, rede.id, sufixo=".fp")}


def test_fase_com_uma_crianca_esconde_so_os_totais_de_todos(rede_com_fase_pequena):
    rid, eid = rede_com_fase_pequena["rede"].id, rede_com_fase_pequena["escola"].id
    sec = rede_com_fase_pequena["sec"]
    [cartao] = sec.get(f"{API}/redes/{rid}/dashboard").json()["escolas"]
    assert cartao["livros"] is None and cartao["tempo_leitura_min"] is None
    assert cartao["livros_por_aluno"] is None
    # A média e os números de quem concorre continuam (4 crianças).
    assert cartao["media_elefante"] == 70.0 and cartao["livros_premiaveis"] == 20
    assert cartao["livros_por_matricula"] == 5.0 and cartao["pontuacao_leitura"] == 1000.0
    assert cartao["oculto"]["leitura"] == grupo_pequeno.bloco_oculto_escola(COMPLEMENTAR)
    assert cartao["oculto"]["leitura"]["parcial"] is True
    assert cartao["grupo_pequeno"] is False
    assert cartao["comparada"] is True and cartao["posicao"] == 1
    # No ranking: segue no per capita (quem concorre) e na adoção (cobertura),
    # sai do total bruto.
    for metrica in ("livros_aluno", "engajamento", "geral"):
        [item] = sec.get(f"{API}/redes/{rid}/ranking", params={"metrica": metrica}).json()
        assert item["escola_id"] == eid and item["livros"] is None
    assert sec.get(f"{API}/redes/{rid}/ranking", params={"metrica": "livros"}).json() == []
    # No comparador, o lado escola perde os totais de todos e mantém a nota.
    lado = sec.get(f"{API}/escolas/{eid}/comparar",
                   params={"tipo_a": "escola", "id_a": eid,
                           "tipo_b": "escola", "id_b": eid}).json()["a"]
    assert lado["indicadores"]["livros_unicos"] is None
    assert lado["dimensoes"]["leitura"]["nota"] == 70.0
    assert lado["dimensoes"]["leitura"]["oculto"]["parcial"] is True
    assert lado["notas"]["elefante"] == 70.0 and lado["grupo_pequeno"] is False
    # Para o Admin Global, tudo como antes.
    [adm] = rede_com_fase_pequena["global"].get(f"{API}/redes/{rid}/dashboard").json()["escolas"]
    assert adm["livros"] == 25 and "oculto" not in adm


# ---------------------------------------------------------------------------
# As decisões puras
# ---------------------------------------------------------------------------

def _cont(media, todos, concorrem):
    return {"media": media, "indicadores": todos, "concorrem": concorrem}


@pytest.mark.parametrize(("contagem", "motivo"), [
    (_cont(1, 1, 1), GP),            # a criança do revisor
    (_cont(2, 2, 2), GP),            # 2: quem conhece uma descobre a outra
    (_cont(3, 3, 3), None),          # o limite exato
    (_cont(0, 0, 0), None),          # sem dado: nada a esconder
    (_cont(1, 5, 1), GP),            # nível "concorre": 1 que concorre + 4 da Fase
    (_cont(0, 2, 0), GP),            # só a Fase, com 2
    (_cont(2, 9, 9), GP),            # antes do recálculo: média de 2, totais de 9
    (_cont(0, 4, 4), None),          # antes do recálculo: sem média, totais de 4
    (_cont(4, 5, 4), COMPLEMENTAR),  # 1 da Fase: só os totais de todos
    (_cont(4, 7, 4), None),          # 3 da Fase: ninguém isolado
])
def test_decidir_escola(contagem, motivo):
    decisao = grupo_pequeno.decidir_escola({"leitura": contagem})
    assert decisao == {"leitura": motivo, "matematica": None}


def test_decidir_agrupa_a_serie_pela_serie_e_nao_pelo_rotulo():
    # '4º Ano' e '4° ano' são a mesma série: o complemento da turma pequena vem da
    # MESMA série (a de 8), não da menor turma de outra série (a do 5º).
    turmas = [
        {"turma": {"id": 1, "ano_escolar": "4º Ano"}, "n_leitura": 1, "n_matematica": 0,
         "_aferidos": {"leitura": 1, "matematica": 0}},
        {"turma": {"id": 2, "ano_escolar": "4° ano"}, "n_leitura": 8, "n_matematica": 0,
         "_aferidos": {"leitura": 8, "matematica": 0}},
        {"turma": {"id": 3, "ano_escolar": "5º Ano"}, "n_leitura": 3, "n_matematica": 0,
         "_aferidos": {"leitura": 3, "matematica": 0}},
        # As Fases não são série premiável: a chave é o rótulo NORMALIZADO, e
        # '1ª Fase' e '1a  fase' são a mesma série (o complemento vem dela, não
        # da menor turma de outra Fase).
        {"turma": {"id": 4, "ano_escolar": "1ª Fase"}, "n_leitura": 1, "n_matematica": 0,
         "_aferidos": {"leitura": 1, "matematica": 0}},
        {"turma": {"id": 5, "ano_escolar": "1a  fase"}, "n_leitura": 8, "n_matematica": 0,
         "_aferidos": {"leitura": 8, "matematica": 0}},
        {"turma": {"id": 6, "ano_escolar": "2ª Fase"}, "n_leitura": 3, "n_matematica": 0,
         "_aferidos": {"leitura": 3, "matematica": 0}},
        # '3° fase' (o grau no ordinal feminino) é a mesma série de '3ª Fase', e
        # 'pre i' a de 'Pré I' (acento): o complemento vem delas.
        {"turma": {"id": 7, "ano_escolar": "3ª Fase"}, "n_leitura": 1, "n_matematica": 0,
         "_aferidos": {"leitura": 1, "matematica": 0}},
        {"turma": {"id": 8, "ano_escolar": "3° fase"}, "n_leitura": 8, "n_matematica": 0,
         "_aferidos": {"leitura": 8, "matematica": 0}},
        {"turma": {"id": 9, "ano_escolar": "4ª Fase"}, "n_leitura": 3, "n_matematica": 0,
         "_aferidos": {"leitura": 3, "matematica": 0}},
        {"turma": {"id": 10, "ano_escolar": "Pré I"}, "n_leitura": 1, "n_matematica": 0,
         "_aferidos": {"leitura": 1, "matematica": 0}},
        {"turma": {"id": 11, "ano_escolar": "pre i"}, "n_leitura": 8, "n_matematica": 0,
         "_aferidos": {"leitura": 8, "matematica": 0}},
        {"turma": {"id": 12, "ano_escolar": "Pré II"}, "n_leitura": 3, "n_matematica": 0,
         "_aferidos": {"leitura": 3, "matematica": 0}},
    ]
    m = grupo_pequeno.decidir(turmas, premiaveis={1, 2, 3})
    assert m[1]["leitura"] == GP
    assert m[2]["leitura"] == COMPLEMENTAR
    assert m[3]["leitura"] is None
    assert m[4]["leitura"] == GP
    assert m[5]["leitura"] == COMPLEMENTAR
    assert m[6]["leitura"] is None
    assert m[7]["leitura"] == GP
    assert m[8]["leitura"] == COMPLEMENTAR
    assert m[9]["leitura"] is None
    assert m[10]["leitura"] == GP
    assert m[11]["leitura"] == COMPLEMENTAR
    assert m[12]["leitura"] is None
    # A mesma chave para as variações de digitação do rótulo da turma que não
    # concorre; séries diferentes continuam diferentes.
    serie = grupo_pequeno._serie
    assert serie("6º Ano") == serie("6° ano") == serie("6o ano") == serie(" 6 º  ANO ")
    assert serie("1ª Fase") == serie("1A FASE") == serie("1ª  fase")
    assert serie("1ª Fase") != serie("2ª Fase") != serie("2º Ano")
    # Qualquer marcador ordinal depois do número é um só, e o acento não conta.
    assert serie("1° Fase") == serie("1ª Fase") == serie("1º fase") == serie("1 ° FASE")
    assert serie("Pré I") == serie("pre i") == serie("PRÉ  I")
    assert serie("Pré I") != serie("Pré II")
    assert serie("1° Fase") != serie("2° Fase")
