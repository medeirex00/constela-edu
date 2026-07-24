"""Testes da Fase 5 — Painel Público sem login, restrito a dados pedagógicos."""
from app.models import Importacao, SnapshotMatific
from app.services import scoring


def _ativar_painel(cliente, escola_id: int) -> str:
    resposta = cliente.put(
        f"/api/v1/escolas/{escola_id}/painel-publico",
        json={"ativo": True, "slides": ["ranking", "destaques"],
              "intervalo_s": 8, "max_posicoes": 5},
    )
    assert resposta.status_code == 200, resposta.text
    url = resposta.json()["url"]
    assert url is not None
    # Regressão: sem PUBLIC_BASE_URL no ambiente, o link deve apontar para o
    # site publicado — nunca para "localhost", que não abre em outro aparelho.
    assert "localhost" not in url
    return url.rsplit("/", 1)[-1]  # token


def _com_notas(db, escola_completa):
    escola = escola_completa["escola"]
    importacao = Importacao(escola_id=escola.id, plataforma="matific", tipo="seed")
    db.add(importacao)
    db.flush()
    for indice, aluno in enumerate(escola_completa["alunos"]):
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id,
                               importacao_id=importacao.id,
                               atividades=10 * (indice + 1), estrelas=20,
                               pontuacao_media=70))
    db.commit()
    scoring.recalcular_escola(db, escola.id)


def test_painel_desativado_retorna_404(cliente, db, escola_completa):
    resposta = cliente.get("/api/v1/publico/token-inexistente/painel")
    assert resposta.status_code == 404


def test_painel_publico_sem_login(cliente, db, escola_completa):
    _com_notas(db, escola_completa)
    token = _ativar_painel(cliente, escola_completa["escola"].id)

    from fastapi.testclient import TestClient
    from app.main import app
    anonimo = TestClient(app)  # sem Authorization
    resposta = anonimo.get(f"/api/v1/publico/{token}/painel")
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["escola"]["nome"] == "ESCOLA TESTE"
    assert corpo["slides"] == ["ranking", "destaques"]
    assert corpo["intervalo_s"] == 8
    assert len(corpo["ranking"]) == 3
    # Somente campos pedagógicos no ranking público
    assert set(corpo["ranking"][0].keys()) == {
        "posicao", "aluno_id", "nome", "turma", "nota_geral"}


def test_a1_aluno_arquivado_some_de_todas_as_superficies(cliente, db, escola_completa):
    """A1: aluno arquivado/inativo NÃO aparece no painel público, no Ranking
    Geral, no dashboard nem na exportação — mesmo com a Nota ÓRFÃ ainda no banco
    (arquivar não apaga a Nota; a defesa é o filtro Aluno.status na leitura)."""
    _com_notas(db, escola_completa)
    escola_id = escola_completa["escola"].id
    alvo = escola_completa["alunos"][0]   # tem Nota calculada no recálculo

    # Arquiva SEM recalcular: a Nota órfã do alvo permanece no banco.
    alvo.status = "arquivado"
    db.commit()
    nome_alvo = alvo.nome

    # 1) Painel público (sem login) — a superfície LGPD mais crítica.
    token = _ativar_painel(cliente, escola_id)
    from fastapi.testclient import TestClient
    from app.main import app
    anonimo = TestClient(app)
    ranking_pub = anonimo.get(f"/api/v1/publico/{token}/painel").json()["ranking"]
    assert all(item["aluno_id"] != alvo.id for item in ranking_pub)
    assert nome_alvo not in [i["nome"] for i in ranking_pub]

    # 2) Ranking Geral (autenticado)
    ranking = cliente.get(f"/api/v1/escolas/{escola_id}/ranking").json()
    assert all(item["aluno_id"] != alvo.id for item in ranking)

    # 3) Dashboard (top10)
    dash = cliente.get(f"/api/v1/escolas/{escola_id}/dashboard").json()
    assert all(item["aluno_id"] != alvo.id for item in dash["top10"])

    # 4) Exportação do ranking (CSV)
    export = cliente.get(f"/api/v1/escolas/{escola_id}/relatorios/ranking?formato=csv")
    assert export.status_code == 200
    assert nome_alvo not in export.text


def test_b2_perfil_publico_bloqueia_enumeracao_fora_do_painel(cliente, db, escola_completa):
    """B2/IDOR: o perfil público só abre para alunos EXIBIDOS no painel. Um
    atacante anônimo com o token (público, do QR) não pode varrer aluno_id
    sequencial e coletar nome+notas de quem está fora do top-N."""
    from app.models import Aluno, Matricula
    _com_notas(db, escola_completa)
    escola_id = escola_completa["escola"].id
    # 4º aluno ATIVO e matriculado, porém SEM nota → nunca aparece no painel.
    fora_aluno = Aluno(escola_id=escola_id, nome="Invisivel No Painel")
    db.add(fora_aluno)
    db.flush()
    db.add(Matricula(escola_id=escola_id, aluno_id=fora_aluno.id,
                     turma_id=escola_completa["turma"].id, ano_letivo=2026))
    db.commit()
    fora_id = fora_aluno.id

    r = cliente.put(f"/api/v1/escolas/{escola_id}/painel-publico",
                    json={"ativo": True, "slides": ["ranking", "evolucao"],
                          "intervalo_s": 8, "max_posicoes": 3})
    token = r.json()["url"].rsplit("/", 1)[-1]

    from fastapi.testclient import TestClient
    from app.main import app
    anon = TestClient(app)  # sem Authorization — o "atacante"
    painel = anon.get(f"/api/v1/publico/{token}/painel").json()
    visiveis = ({i["aluno_id"] for i in painel["ranking"]}
                | {i["aluno_id"] for i in painel["evolucao"]})
    assert visiveis and fora_id not in visiveis   # o sem-nota não é exibido

    # Aluno fora do painel: enumeração barrada (404), mesmo ativo e existente.
    assert anon.get(f"/api/v1/publico/{token}/alunos/{fora_id}").status_code == 404
    # Aluno exibido no painel: perfil abre normalmente (200) — feature preservada.
    assert anon.get(
        f"/api/v1/publico/{token}/alunos/{next(iter(visiveis))}").status_code == 200


def test_medio7_perfil_publico_usa_cache_de_visiveis(cliente, db, escola_completa,
                                                     monkeypatch):
    """Médio-7 (perf): abrir perfis públicos não recomputa a evolução da escola
    a cada request — os ids visíveis ficam em cache por TTL (como o painel)."""
    _com_notas(db, escola_completa)
    escola_id = escola_completa["escola"].id
    r = cliente.put(f"/api/v1/escolas/{escola_id}/painel-publico",
                    json={"ativo": True, "slides": ["ranking"],
                          "intervalo_s": 8, "max_posicoes": 5})
    token = r.json()["url"].rsplit("/", 1)[-1]
    alvo = escola_completa["alunos"][0].id

    from app.routers import publico
    chamadas = {"n": 0}
    original = publico.svc_evolucao.ranking_evolucao

    def espiao(*a, **k):
        chamadas["n"] += 1
        return original(*a, **k)

    monkeypatch.setattr(publico.svc_evolucao, "ranking_evolucao", espiao)

    from fastapi.testclient import TestClient
    from app.main import app
    anon = TestClient(app)
    # Duas aberturas de perfil dentro do TTL → a evolução é computada só 1x.
    assert anon.get(f"/api/v1/publico/{token}/alunos/{alvo}").status_code == 200
    assert anon.get(f"/api/v1/publico/{token}/alunos/{alvo}").status_code == 200
    assert chamadas["n"] == 1


def test_painel_publico_anonimiza_nomes_por_padrao(cliente, db, escola_completa):
    """LGPD/ECA: o telão SEM login não expõe o nome COMPLETO da criança — por
    padrão mostra 'primeiro nome + inicial' (ex.: 'Ana Beatriz Souza' -> 'Ana B.')."""
    from app.services.gamificacao import anonimizar_nome
    _com_notas(db, escola_completa)
    escola_id = escola_completa["escola"].id
    token = _ativar_painel(cliente, escola_id)

    from fastapi.testclient import TestClient
    from app.main import app
    anon = TestClient(app)
    corpo = anon.get(f"/api/v1/publico/{token}/painel").json()

    completos = {a.nome for a in escola_completa["alunos"]}
    ranking = corpo["ranking"]
    assert ranking  # há ranking
    for item in ranking:
        assert item["nome"] not in completos      # nenhum nome completo vaza
        aluno = next(a for a in escola_completa["alunos"] if a.id == item["aluno_id"])
        assert item["nome"] == anonimizar_nome(aluno.nome)  # forma reduzida correta

    # A configuração reflete o padrão seguro (anonimização ligada).
    cfg = cliente.get(f"/api/v1/escolas/{escola_id}/painel-publico").json()
    assert cfg["anonimizar"] is True


def test_painel_publico_nome_completo_so_quando_escola_opta(cliente, db, escola_completa):
    """A escola PODE optar por exibir o nome completo (com consentimento):
    anonimizar=False. É explícito e não é o padrão."""
    _com_notas(db, escola_completa)
    escola_id = escola_completa["escola"].id
    resposta = cliente.put(
        f"/api/v1/escolas/{escola_id}/painel-publico",
        json={"ativo": True, "slides": ["ranking"], "intervalo_s": 8,
              "max_posicoes": 5, "anonimizar": False},
    )
    assert resposta.status_code == 200
    assert resposta.json()["anonimizar"] is False
    token = resposta.json()["url"].rsplit("/", 1)[-1]

    from fastapi.testclient import TestClient
    from app.main import app
    anon = TestClient(app)
    corpo = anon.get(f"/api/v1/publico/{token}/painel").json()
    nomes_no_painel = {i["nome"] for i in corpo["ranking"]}
    completos = {a.nome for a in escola_completa["alunos"]}
    # Com anonimização desligada, aparece pelo menos um nome completo real.
    assert nomes_no_painel & completos


def test_painel_publico_evolucao_justa_nao_infla_acumulado(cliente, db, escola_completa):
    """Telão público: a evolução mede só o crescimento DENTRO da janela
    (base_no_periodo=True). Um aluno com apenas o acumulado de vida (um único
    snapshot, sem histórico anterior) NÃO aparece 'evoluindo tudo' — evita o
    'caso Antonella' no telão, que é público. Falharia com o comportamento antigo
    (acumulado exibido como evolução)."""
    from datetime import datetime, timezone

    from app.models import Importacao, SnapshotMatific
    from app.services import scoring

    escola = escola_completa["escola"]
    imp = Importacao(escola_id=escola.id, plataforma="matific", tipo="seed")
    db.add(imp)
    db.flush()
    hoje = datetime.now(timezone.utc).replace(tzinfo=None)
    for indice, aluno in enumerate(escola_completa["alunos"]):
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id,
                               importacao_id=imp.id, atividades=100 * (indice + 1),
                               estrelas=50, pontuacao_media=70, data_referencia=hoje))
    db.commit()
    scoring.recalcular_escola(db, escola.id)

    resposta = cliente.put(
        f"/api/v1/escolas/{escola.id}/painel-publico",
        json={"ativo": True, "slides": ["ranking", "evolucao"],
              "intervalo_s": 8, "max_posicoes": 10},
    )
    token = resposta.json()["url"].rsplit("/", 1)[-1]

    from fastapi.testclient import TestClient
    from app.main import app
    anon = TestClient(app)
    corpo = anon.get(f"/api/v1/publico/{token}/painel").json()
    # O ranking geral (acumulado) funciona normalmente.
    assert corpo["ranking"]
    # Mas a evolução do telão fica VAZIA: sem base anterior, ninguém "cresceu no
    # período", então o acumulado de vida não é atribuído nem exibido. (Com o
    # bug antigo, os de maior acumulado apareceriam inflados aqui.)
    assert corpo["evolucao"] == []


def test_max_posicoes_limita_o_ranking(cliente, db, escola_completa):
    _com_notas(db, escola_completa)
    escola_id = escola_completa["escola"].id
    cliente.put(
        f"/api/v1/escolas/{escola_id}/painel-publico",
        json={"ativo": True, "slides": ["ranking"], "intervalo_s": 10, "max_posicoes": 3},
    )
    token = cliente.get(f"/api/v1/escolas/{escola_id}/painel-publico").json()["url"].rsplit("/", 1)[-1]
    corpo = cliente.get(f"/api/v1/publico/{token}/painel").json()
    assert len(corpo["ranking"]) == 3


def test_perfil_publico_restrito_a_dados_pedagogicos(cliente, db, escola_completa):
    _com_notas(db, escola_completa)
    token = _ativar_painel(cliente, escola_completa["escola"].id)
    ana = escola_completa["alunos"][0]

    from fastapi.testclient import TestClient
    from app.main import app
    anonimo = TestClient(app)
    resposta = anonimo.get(f"/api/v1/publico/{token}/alunos/{ana.id}")
    assert resposta.status_code == 200
    corpo = resposta.json()
    # Link público → nome ANONIMIZADO por padrão (não o nome completo da criança).
    from app.services.gamificacao import anonimizar_nome
    assert corpo["nome"] == anonimizar_nome(ana.nome)
    assert corpo["nome"] != ana.nome
    assert "conquistas" in corpo
    # Nada de dados pessoais sensíveis (PRD §120)
    for campo in ("data_nascimento", "observacoes", "numero_chamada", "email", "foto_url"):
        assert campo not in corpo


def test_trocar_token_invalida_o_link_antigo(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    token_antigo = _ativar_painel(cliente, escola_id)
    assert cliente.get(f"/api/v1/publico/{token_antigo}/painel").status_code == 200

    novo = cliente.post(f"/api/v1/escolas/{escola_id}/painel-publico/novo-token")
    assert novo.status_code == 200
    token_novo = novo.json()["url"].rsplit("/", 1)[-1]
    assert token_novo != token_antigo
    assert cliente.get(f"/api/v1/publico/{token_antigo}/painel").status_code == 404
    assert cliente.get(f"/api/v1/publico/{token_novo}/painel").status_code == 200


def test_desativar_painel_bloqueia_acesso(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    token = _ativar_painel(cliente, escola_id)
    cliente.put(
        f"/api/v1/escolas/{escola_id}/painel-publico",
        json={"ativo": False, "slides": ["ranking"], "intervalo_s": 10, "max_posicoes": 10},
    )
    assert cliente.get(f"/api/v1/publico/{token}/painel").status_code == 404


def test_reativar_painel_gera_novo_endereco(cliente, db, escola_completa):
    """Gerar um novo painel (reativar) cria um endereço NOVO — o QR e o link
    anteriores param de funcionar, sem precisar clicar em 'Gerar novo endereço'."""
    escola_id = escola_completa["escola"].id
    token1 = _ativar_painel(cliente, escola_id)
    assert cliente.get(f"/api/v1/publico/{token1}/painel").status_code == 200

    # Desativa: o link cai.
    cliente.put(f"/api/v1/escolas/{escola_id}/painel-publico",
                json={"ativo": False, "slides": ["ranking"], "intervalo_s": 8, "max_posicoes": 5})
    assert cliente.get(f"/api/v1/publico/{token1}/painel").status_code == 404

    # Reativa = painel NOVO: endereço diferente; o antigo continua morto.
    token2 = _ativar_painel(cliente, escola_id)
    assert token2 != token1
    assert cliente.get(f"/api/v1/publico/{token2}/painel").status_code == 200
    assert cliente.get(f"/api/v1/publico/{token1}/painel").status_code == 404


def test_editar_painel_ativo_preserva_endereco(cliente, db, escola_completa):
    """Ajustar um painel JÁ ativo (slides/intervalo) NÃO troca o endereço — não
    derruba o telão nem o QR já impresso no meio do uso."""
    escola_id = escola_completa["escola"].id
    token1 = _ativar_painel(cliente, escola_id)
    r = cliente.put(f"/api/v1/escolas/{escola_id}/painel-publico",
                    json={"ativo": True, "slides": ["ranking", "destaques", "evolucao"],
                          "intervalo_s": 20, "max_posicoes": 8})
    assert r.status_code == 200
    assert r.json()["url"].rsplit("/", 1)[-1] == token1
    assert cliente.get(f"/api/v1/publico/{token1}/painel").status_code == 200


def test_qr_code_svg(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    _ativar_painel(cliente, escola_id)
    resposta = cliente.get(f"/api/v1/escolas/{escola_id}/painel-publico/qr")
    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("image/svg")
    assert b"<svg" in resposta.content


def test_configuracao_exige_papel(cliente, db, escola_completa):
    from app.core.security import hash_senha
    from app.models import Usuario
    escola = escola_completa["escola"]
    db.add(Usuario(escola_id=escola.id, nome="Visitante", email="visita@teste.com.br",
                   senha_hash=hash_senha("s3nh4"), cargo="visitante"))
    db.commit()
    from fastapi.testclient import TestClient
    from app.main import app
    visitante = TestClient(app)
    login = visitante.post("/api/v1/auth/login",
                           data={"username": "visita@teste.com.br", "password": "s3nh4"})
    visitante.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    resposta = visitante.put(
        f"/api/v1/escolas/{escola.id}/painel-publico",
        json={"ativo": True, "slides": ["ranking"], "intervalo_s": 10, "max_posicoes": 10},
    )
    assert resposta.status_code == 403
