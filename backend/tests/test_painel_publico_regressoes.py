"""Regressões do telão público e da vitrine da rede (prontidão, integração 5).

Cada teste é a prova do achado INVERTIDA: o que antes passava mostrando o
defeito agora fixa o comportamento certo. Dados 100% fictícios (fixture
``escola_completa``)."""
import json
import pathlib
import re

from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    Aluno, Configuracao, Importacao, Matricula, ModuloRede, Rede, SnapshotElefante,
    SnapshotMatific,
)
from app.routers import publico
from app.services import modulos as svc_modulos
from app.services import scoring
from tests._ano_letivo import escola_no_ano_de_hoje  # noqa: F401 — fixture

API = "/api/v1"


def _snap_matific(db, escola, aluno, imp, atividades, estrelas, media):
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                           atividades=atividades, estrelas=estrelas,
                           pontuacao_media=media))


def _importacao(db, escola, plataforma="matific"):
    imp = Importacao(escola_id=escola.id, plataforma=plataforma, tipo="seed")
    db.add(imp)
    db.flush()
    return imp


def _ativar(cliente, escola_id, slides, **extra):
    r = cliente.put(f"{API}/escolas/{escola_id}/painel-publico",
                    json={"ativo": True, "slides": slides, "intervalo_s": 8,
                          "max_posicoes": 10, **extra})
    assert r.status_code == 200, r.text
    return r.json()["url"].rsplit("/", 1)[-1]


# --- (1) slide de ranking legado: ausência não é zero -------------------------


def test_sem_dado_fica_fora_do_telao_e_o_snapshot_zerado_fica(cliente, db,
                                                              escola_completa):
    escola = escola_completa["escola"]
    sem_dado, com_dado, zerado = escola_completa["alunos"]
    imp = _importacao(db, escola)
    _snap_matific(db, escola, com_dado, imp, 30, 20, 70)
    _snap_matific(db, escola, zerado, imp, 0, 0, 0)      # abriu e ainda não produziu
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    token = _ativar(cliente, escola.id, ["ranking"])
    anon = TestClient(app)

    ranking = anon.get(f"{API}/publico/{token}/painel").json()["ranking"]
    assert [i["aluno_id"] for i in ranking] == [com_dado.id, zerado.id]
    # A posição exibida é a CARIMBADA (a mesma do perfil e do Ranking Geral):
    # quem não tem dado empatou em zero com o zerado e ficou com o 2º lugar
    # legado, então a lista pula do 1 para o 3 — não é renumerada.
    assert [i["posicao"] for i in ranking] == [1, 3]
    assert ranking[1]["nota_geral"] == 0.0

    assert anon.get(f"{API}/publico/{token}/alunos/{sem_dado.id}").status_code == 404
    perfil_zerado = anon.get(f"{API}/publico/{token}/alunos/{zerado.id}")
    assert perfil_zerado.status_code == 200, perfil_zerado.text
    assert perfil_zerado.json()["posicao"] == 3


def test_escola_sem_nenhuma_coleta_nao_monta_podio(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    scoring.recalcular_escola(db, escola.id)       # Notas existem, todas sem dado
    token = _ativar(cliente, escola.id, ["ranking", "evolucao"])
    anon = TestClient(app)

    corpo = anon.get(f"{API}/publico/{token}/painel").json()
    assert corpo["ranking"] == [] and corpo["evolucao"] == []
    for aluno in escola_completa["alunos"]:
        assert anon.get(f"{API}/publico/{token}/alunos/{aluno.id}").status_code == 404


def test_dado_so_de_modulo_fora_do_plano_nao_entra_no_slide(cliente, db, escola_completa):
    """Coerente com a trava de módulo (T4): o motor carimba aferido=False na
    dimensão que a rede não contratou, então quem só tem Matific numa rede sem
    Matemática fica fora do telão — e quem tem Leitura continua."""
    escola = escola_completa["escola"]
    so_matific, so_elefante, _sem_nada = escola_completa["alunos"]
    rede = Rede(nome="REDE FICTICIA SEM MATEMATICA", status="ativa")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    for modulo in svc_modulos.TODOS:
        db.add(ModuloRede(rede_id=rede.id, modulo=modulo, ativo=(modulo != "matematica")))
    _snap_matific(db, escola, so_matific, _importacao(db, escola), 40, 30, 70)
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=so_elefante.id,
                            importacao_id=_importacao(db, escola, "elefante").id,
                            livros_unicos=4, tempo_leitura_min=50,
                            questoes_tentativas=10, questoes_acertos=8))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    token = _ativar(cliente, escola.id, ["ranking"])
    anon = TestClient(app)

    ranking = anon.get(f"{API}/publico/{token}/painel").json()["ranking"]
    assert [i["aluno_id"] for i in ranking] == [so_elefante.id]
    assert anon.get(f"{API}/publico/{token}/alunos/{so_matific.id}").status_code == 404


# --- (2) cache do telão por processo: vale a config que está no banco ----------


def _com_notas(db, escola_completa):
    escola = escola_completa["escola"]
    imp = _importacao(db, escola)
    for i, aluno in enumerate(escola_completa["alunos"]):
        _snap_matific(db, escola, aluno, imp, 10 * (i + 1), 20, 70)
    db.commit()
    scoring.recalcular_escola(db, escola.id)


def _outro_worker(monkeypatch):
    """O PUT cai em OUTRO processo: neste, `invalidar_cache_painel` não roda."""
    monkeypatch.setattr(publico, "invalidar_cache_painel", lambda *_a, **_k: None)


def test_ligar_a_protecao_do_nome_vale_no_worker_que_nao_recebeu_o_put(
        cliente, db, escola_completa, monkeypatch):
    escola = escola_completa["escola"]
    _com_notas(db, escola_completa)
    completos = {a.nome for a in escola_completa["alunos"]}
    token = _ativar(cliente, escola.id, ["ranking"], anonimizar=False,
                    confirmar_exposicao=True)
    anon = TestClient(app)
    antes = anon.get(f"{API}/publico/{token}/painel").json()["ranking"]
    assert {i["nome"] for i in antes} == completos           # cache aquecido

    _outro_worker(monkeypatch)
    _ativar(cliente, escola.id, ["ranking"], anonimizar=True)

    depois = anon.get(f"{API}/publico/{token}/painel").json()["ranking"]
    assert len(depois) == 3
    assert {i["nome"] for i in depois}.isdisjoint(completos)
    assert all(i["turma"] is None for i in depois)


def test_config_gravada_direto_no_banco_nao_reaproveita_o_cache(cliente, db,
                                                                 escola_completa):
    escola = escola_completa["escola"]
    _com_notas(db, escola_completa)
    token = _ativar(cliente, escola.id, ["ranking"], anonimizar=False,
                    confirmar_exposicao=True)
    anon = TestClient(app)
    completos = {a.nome for a in escola_completa["alunos"]}
    assert {i["nome"] for i in anon.get(f"{API}/publico/{token}/painel")
            .json()["ranking"]} == completos

    row = db.query(Configuracao).filter_by(escola_id=escola.id,
                                           namespace="painel_publico").one()
    row.valor = {**row.valor, "anonimizar": True}
    db.commit()

    nomes = {i["nome"] for i in anon.get(f"{API}/publico/{token}/painel").json()["ranking"]}
    assert nomes.isdisjoint(completos)


def test_desligar_um_slide_vale_no_outro_worker_e_fecha_o_perfil(cliente, db,
                                                                 escola_completa,
                                                                 monkeypatch):
    escola = escola_completa["escola"]
    _com_notas(db, escola_completa)
    token = _ativar(cliente, escola.id, ["ranking", "mural"])
    anon = TestClient(app)
    ranking = anon.get(f"{API}/publico/{token}/painel").json()["ranking"]
    assert ranking
    aberto = ranking[0]["aluno_id"]
    assert anon.get(f"{API}/publico/{token}/alunos/{aberto}").status_code == 200

    _outro_worker(monkeypatch)
    _ativar(cliente, escola.id, ["mural"])

    corpo = anon.get(f"{API}/publico/{token}/painel").json()
    assert corpo["ranking"] == [] and corpo["slides"] == ["mural"]
    # O cache de visíveis também casa com a config nova: quem só estava no
    # ranking desligado não tem mais o perfil aberto.
    assert anon.get(f"{API}/publico/{token}/alunos/{aberto}").status_code == 404


def test_mesma_config_continua_saindo_do_cache(cliente, db, escola_completa, monkeypatch):
    """Controle: a assinatura não desliga o cache — com a config igual, o
    segundo poll do telão não remonta o payload."""
    escola = escola_completa["escola"]
    _com_notas(db, escola_completa)
    token = _ativar(cliente, escola.id, ["ranking"])
    montagens = []
    original = publico._dados_publicos

    def _contando(*args, **kwargs):
        montagens.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(publico, "_dados_publicos", _contando)
    anon = TestClient(app)
    primeiro = anon.get(f"{API}/publico/{token}/painel").json()
    segundo = anon.get(f"{API}/publico/{token}/painel").json()
    assert primeiro == segundo
    assert len(montagens) == 1


# --- (3)/(6) vitrine pública da rede --------------------------------------------


def _rede_com_dados(db, escola_completa, token, desligado=None):
    """Rede ATIVA com a vitrine ligada (token) e dado das DUAS plataformas na
    escola-base; ``desligado`` = módulo fora do plano (None = tudo contratado).

    A escola-base ganha mais 2 crianças (3 + 2 = K_MINIMO): com menos de 5 que
    concorrem a vitrine não publica o per capita (``test_vitrine_rede_k_minimo.py``)."""
    escola = escola_completa["escola"]
    rede = Rede(nome="REDE FICTICIA VITRINE", status="ativa", token_publico=token)
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    for modulo in svc_modulos.TODOS:
        db.add(ModuloRede(rede_id=rede.id, modulo=modulo, ativo=(modulo != desligado)))
    imp_m = _importacao(db, escola)
    imp_e = _importacao(db, escola, "elefante")
    extras = []
    for i in (4, 5):
        aluno = Aluno(escola_id=escola.id, nome=f"Crianca Ficticia Vitrine {i}")
        db.add(aluno)
        db.flush()
        db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id,
                         turma_id=escola_completa["turma"].id,
                         ano_letivo=escola.ano_letivo_ativo))
        extras.append(aluno)
    for aluno in [*escola_completa["alunos"], *extras]:
        _snap_matific(db, escola, aluno, imp_m, 40, 30, 70)
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id,
                                importacao_id=imp_e.id, livros_unicos=4,
                                tempo_leitura_min=50, questoes_tentativas=10,
                                questoes_acertos=8))
    return rede


def _vitrine(token):
    r = TestClient(app).get(f"{API}/publico/rede/{token}")
    assert r.status_code == 200, r.text
    return r.json()


def test_vitrine_sem_matematica_nao_publica_o_top_de_matematica(db, escola_completa):
    _rede_com_dados(db, escola_completa, "tok-vitrine-regr-sem-mat", desligado="matematica")
    db.commit()
    corpo = _vitrine("tok-vitrine-regr-sem-mat")
    assert corpo["top_matematica"] == []
    assert [e["nome"] for e in corpo["top_leitura"]] == [escola_completa["escola"].nome]
    # A tela não monta o cartão da Matemática (Vitest: PainelPublicoRede.test.tsx).
    assert corpo["modulos"] == ["leitura"]


def test_vitrine_sem_leitura_nao_publica_o_top_de_leitura(db, escola_completa):
    _rede_com_dados(db, escola_completa, "tok-vitrine-regr-sem-lei", desligado="leitura")
    db.commit()
    corpo = _vitrine("tok-vitrine-regr-sem-lei")
    assert corpo["top_leitura"] == []
    assert [e["nome"] for e in corpo["top_matematica"]] == [escola_completa["escola"].nome]
    assert corpo["modulos"] == ["matematica"]


def test_vitrine_com_tudo_contratado_publica_as_duas_listas(db, escola_completa):
    _rede_com_dados(db, escola_completa, "tok-vitrine-regr-tudo")
    db.commit()
    corpo = _vitrine("tok-vitrine-regr-tudo")
    nome = escola_completa["escola"].nome
    assert [e["nome"] for e in corpo["top_leitura"]] == [nome]
    assert [e["nome"] for e in corpo["top_matematica"]] == [nome]
    assert corpo["top_matematica"][0]["valor"] == 30.0
    assert corpo["modulos"] == ["leitura", "matematica"]


def test_vitrine_de_rede_sem_contrato_gravado_lista_os_dois_modulos(db, escola_completa):
    """Tabela de módulos esparsa: sem linha nenhuma = tudo contratado
    (services/modulos.py, regra 1). A vitrine segue a mesma regra, e o campo
    novo só leva chaves do catálogo — nenhum dado de escola ou de criança."""
    escola = escola_completa["escola"]
    rede = Rede(nome="REDE FICTICIA SEM CONTRATO", status="ativa",
                token_publico="tok-vitrine-regr-sem-linha")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    db.commit()
    corpo = _vitrine("tok-vitrine-regr-sem-linha")
    assert corpo["modulos"] == sorted(svc_modulos.TODOS) == ["leitura", "matematica"]
    assert set(corpo) == {"rede_nome", "top_leitura", "top_matematica",
                          "unidade_leitura", "unidade_matematica", "modulos"}
    # Contratado sem dado continua contratado: a lista vazia vira "Sem dados
    # ainda." na tela, não some (são casos diferentes).
    assert corpo["top_leitura"] == [] and corpo["top_matematica"] == []


def test_vitrine_nao_publica_escola_inativa(db, escola_completa):
    """docs/operacao/STATUS-ESCOLA-REDE.md: na vitrine pública da rede, a
    escola inativa não entra (o telão dela já dá 404). O controle com a
    escola ativa é `test_vitrine_com_tudo_contratado_publica_as_duas_listas`."""
    _rede_com_dados(db, escola_completa, "tok-vitrine-regr-inativa")
    escola_completa["escola"].status = "inativa"
    db.commit()
    corpo = _vitrine("tok-vitrine-regr-inativa")
    assert corpo["top_leitura"] == [] and corpo["top_matematica"] == []


# --- (4) telão e vitrine não indexáveis ------------------------------------------

RAIZ = pathlib.Path(__file__).resolve().parents[2]
NAO_INDEXAR = "noindex, nofollow, noarchive"


def _cabecalhos_vercel() -> dict[str, dict[str, str]]:
    vercel = json.loads((RAIZ / "vercel.json").read_text(encoding="utf-8"))
    return {bloco["source"]: {h["key"].lower(): h["value"] for h in bloco["headers"]}
            for bloco in vercel["headers"]}


def _locations_nginx() -> dict[str, str]:
    texto = (RAIZ / "apps/web/nginx.conf").read_text(encoding="utf-8")
    return dict(re.findall(r"location\s+([^\s{]+)\s*\{([^}]*)\}", texto))


def test_borda_marca_noindex_so_no_telao_e_na_vitrine():
    vercel = _cabecalhos_vercel()
    assert vercel["/p/(.*)"]["x-robots-tag"] == NAO_INDEXAR
    assert vercel["/rede/p/(.*)"]["x-robots-tag"] == NAO_INDEXAR
    # NÃO no SPA inteiro: desindexaria o login e as demais páginas.
    assert "x-robots-tag" not in vercel["/(.*)"]

    nginx = _locations_nginx()
    for rota in ("/p/", "/rede/p/"):
        bloco = nginx[rota]
        assert f'X-Robots-Tag "{NAO_INDEXAR}" always' in bloco, rota
        # Serve o SPA no próprio location (sem redirecionamento interno para o
        # `location /`, que perderia o cabeçalho) e mantém os de segurança.
        assert "try_files /index.html =404;" in bloco, rota
        for cabecalho in ("X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy"):
            assert cabecalho in bloco, (rota, cabecalho)
    assert "X-Robots-Tag" not in nginx["/"]

    index = (RAIZ / "apps/web/index.html").read_text(encoding="utf-8").lower()
    assert 'name="robots"' not in index and "noindex" not in index


_ADD_HEADER = re.compile(r'add_header\s+([A-Za-z-]+)\s+"([^"]*)"(\s+always)?\s*;')
_LOCATION = re.compile(r"location\s+((?:[=~^*]+\s+)?[^\s{]+)\s*\{([^}]*)\}")


def _nginx_server_e_locations(texto: str) -> tuple[dict[str, tuple[str, bool]],
                                                   dict[str, str]]:
    """({cabeçalho do nível server: (valor, always)}, {location: corpo}), sem os
    comentários (que citam add_header). Nenhum location tem bloco aninhado."""
    sem_comentario = re.sub(r"#[^\n]*", "", texto)
    locations = dict(_LOCATION.findall(sem_comentario))
    nivel_server = _LOCATION.sub("", sem_comentario)
    server = {nome: (valor, bool(always))
              for nome, valor, always in _ADD_HEADER.findall(nivel_server)}
    return server, locations


def _locations_do_spa_sem_os_cabecalhos_do_server(texto: str) -> dict[str, list[str]]:
    """Para cada location que serve o index.html E tem add_header próprio (logo
    não herda nada do server), os cabeçalhos de segurança do server que faltam
    nele ou estão com outro valor."""
    server, locations = _nginx_server_e_locations(texto)
    faltando = {}
    for rota, corpo in locations.items():
        if not re.search(r"try_files[^;]*/index\.html", corpo):
            continue
        proprios = {nome: (valor, bool(always))
                    for nome, valor, always in _ADD_HEADER.findall(corpo)}
        if not proprios:
            continue                    # sem add_header próprio: herda os do server
        faltando[rota] = sorted(nome for nome, par in server.items()
                                if proprios.get(nome) != par)
    return faltando


def test_todo_location_que_serve_o_spa_leva_a_csp_e_os_cabecalhos_do_server():
    """nginx (instalação própria): add_header só é herdado do server pelo
    location que não tem NENHUM add_header próprio. O SPA (/), o telão (/p/) e
    a vitrine (/rede/p/) têm os seus; sem repetir a CSP, o HTML que mostra nome
    de criança saía sem Content-Security-Policy. A Vercel manda a dela pelo
    vercel.json, que não muda aqui."""
    texto = (RAIZ / "apps/web/nginx.conf").read_text(encoding="utf-8")
    server, _ = _nginx_server_e_locations(texto)
    csp, sempre = server["Content-Security-Policy"]
    assert sempre
    for diretiva in ("default-src 'self'", "script-src 'self'", "base-uri 'self'",
                     "form-action 'self'", "frame-ancestors 'self'"):
        assert diretiva in csp, diretiva
    assert set(server) >= {"X-Content-Type-Options", "X-Frame-Options",
                           "Referrer-Policy", "Content-Security-Policy"}

    faltando = _locations_do_spa_sem_os_cabecalhos_do_server(texto)
    # Os três que servem o HTML hoje estão na conta (um location novo que sirva
    # o SPA entra sozinho na mesma verificação).
    assert set(faltando) >= {"/", "/p/", "/rede/p/"}
    assert faltando == {rota: [] for rota in faltando}


def test_catraca_da_csp_do_nginx_pega_o_location_sem_csp():
    """Controle da catraca acima: tirando a CSP de um location (o estado
    anterior desta correção), ela aponta exatamente esse location."""
    texto = (RAIZ / "apps/web/nginx.conf").read_text(encoding="utf-8")
    inicio = texto.index("location /rede/p/ {")
    fim = texto.index("}", inicio)
    bloco = texto[inicio:fim]
    sem_csp = re.sub(r"\n[^\n]*add_header Content-Security-Policy[^\n]*", "", bloco)
    assert sem_csp != bloco
    faltando = _locations_do_spa_sem_os_cabecalhos_do_server(
        texto[:inicio] + sem_csp + texto[fim:])
    assert faltando["/rede/p/"] == ["Content-Security-Policy"]
    assert faltando["/"] == [] and faltando["/p/"] == []


def test_paginas_publicas_do_front_pedem_noindex():
    for arquivo in sorted((RAIZ / "apps/web/src/pages/publico").glob("*.tsx")):
        assert "useSemIndexacao();" in arquivo.read_text(encoding="utf-8"), arquivo.name
    hook = (RAIZ / "apps/web/src/hooks/useSemIndexacao.ts").read_text(encoding="utf-8")
    assert f'"{NAO_INDEXAR}"' in hook


def test_api_publica_manda_x_robots_tag(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    _com_notas(db, escola_completa)
    token = _ativar(cliente, escola.id, ["ranking"])
    anon = TestClient(app)
    painel = anon.get(f"{API}/publico/{token}/painel")
    assert painel.status_code == 200
    assert painel.headers["x-robots-tag"] == NAO_INDEXAR
    assert painel.headers["cache-control"] == "no-store"         # continua junto
    aluno = painel.json()["ranking"][0]["aluno_id"]
    perfil = anon.get(f"{API}/publico/{token}/alunos/{aluno}")
    assert perfil.status_code == 200 and perfil.headers["x-robots-tag"] == NAO_INDEXAR

    rede = Rede(nome="REDE FICTICIA ROBOTS", status="ativa", token_publico="tok-robots-1")
    db.add(rede)
    db.commit()
    vitrine = anon.get(f"{API}/publico/rede/tok-robots-1")
    assert vitrine.status_code == 200 and vitrine.headers["x-robots-tag"] == NAO_INDEXAR
    # Por rota: o resto da API não ganha o cabeçalho.
    assert "x-robots-tag" not in anon.get("/api/health/live").headers


# --- (5) a barreira de exposição do nome não é anulada pelo próprio cliente ------


def test_aba_antiga_que_so_muda_o_intervalo_nao_reexpoe_os_nomes(cliente, db,
                                                                 escola_completa):
    """O PainelPublicoConfig manda confirmar_exposicao=true SÓ no checkbox de
    privacidade com o aviso aceito (Vitest: PainelPublicoConfig.test.tsx).
    Aqui, o corpo exato que a aba antiga manda agora ao salvar o intervalo:
    o servidor recusa e o telão continua protegido."""
    escola = escola_completa["escola"]
    _com_notas(db, escola_completa)
    url = f"{API}/escolas/{escola.id}/painel-publico"
    token = _ativar(cliente, escola.id, ["ranking"], anonimizar=False,
                    confirmar_exposicao=True)
    aba_a = cliente.get(url).json()                 # estado guardado pela aba A
    assert aba_a["anonimizar"] is False
    _ativar(cliente, escola.id, ["ranking"], anonimizar=True)   # B liga a proteção

    corpo = {"ativo": aba_a["ativo"], "slides": aba_a["slides"], "intervalo_s": 15,
             "max_posicoes": aba_a["max_posicoes"], "anonimizar": aba_a["anonimizar"],
             "confirmar_exposicao": False}
    r = cliente.put(url, json=corpo)
    assert r.status_code == 400
    assert "confirmar a exposição" in r.json()["detail"]

    completos = {a.nome for a in escola_completa["alunos"]}
    ranking = TestClient(app).get(f"{API}/publico/{token}/painel").json()["ranking"]
    assert {i["nome"] for i in ranking}.isdisjoint(completos)
    assert cliente.get(url).json()["anonimizar"] is True
