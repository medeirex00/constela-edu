"""Escalada de privilégio e PII administrativa (auditoria 360: C-03/C-04/C-05).

C-03 — o administrador de UMA escola tomava a conta da Secretaria (que mantém
       o `escola_id` de origem) e passava a ler a REDE inteira.
C-04 — `GET /escolas/{id}/backup` entregava à Secretaria o JSON completo da
       escola: nome civil, data de nascimento e `observacoes` (campo livre onde
       entram laudos) de crianças de QUALQUER escola do município.
C-05 — e-mail cravado no código era promovido a `is_global` a cada boot: em
       ambiente novo (município, staging, homologação, restauração) bastava
       criar um usuário com aquele e-mail para virar dono da plataforma.

Os testes cobrem os dois lados: o ataque é recusado E quem tem direito continua
passando (sem over-block).
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import config as config_mod
from app.core.security import hash_senha
from app.main import app
from app.models import Aluno, Escola, Matricula, Rede, Usuario

SENHA = "C0nstela#Forte"
ISCA_NOME = "Zoraide Bait Xyzzy"
ISCA_OBS = "LAUDO-CONFIDENCIAL-ISCA"


def _login(email: str, senha: str = SENHA) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


@pytest.fixture()
def cenario(db, escola_completa):
    """Município (rede) com duas escolas + uma escola de OUTRA rede.

    A conta da Secretaria é montada no PIOR CASO documentado: veio de um usuário
    de escola (mantém `escola_id`) e tem `cargo="admin"` — as duas condições que
    faziam `escola_autorizada` + `exigir_papeis("admin")` liberarem o backup.
    """
    escola = escola_completa["escola"]
    turma = escola_completa["turma"]
    rede = Rede(nome="Rede Municipal", status="ativa")
    outra_rede = Rede(nome="Outra Rede", status="ativa")
    db.add_all([rede, outra_rede])
    db.flush()
    escola.rede_id = rede.id
    escola_b = Escola(nome="Escola B da Rede", status="ativa", rede_id=rede.id,
                      ano_letivo_ativo=2026)
    escola_fora = Escola(nome="Escola de Outra Rede", status="ativa",
                         rede_id=outra_rede.id, ano_letivo_ativo=2026)
    db.add_all([escola_b, escola_fora])
    db.flush()

    isca = Aluno(escola_id=escola.id, nome=ISCA_NOME, observacoes=ISCA_OBS)
    db.add(isca)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=isca.id, turma_id=turma.id,
                     ano_letivo=2026))

    contas = {
        "admin_a": Usuario(escola_id=escola.id, nome="Admin A",
                           email="admin.a@priv.local", senha_hash=hash_senha(SENHA),
                           cargo="admin"),
        "admin_a2": Usuario(escola_id=escola.id, nome="Admin A2",
                            email="admin.a2@priv.local", senha_hash=hash_senha(SENHA),
                            cargo="admin"),
        "coord_a": Usuario(escola_id=escola.id, nome="Coord A",
                           email="coord.a@priv.local", senha_hash=hash_senha(SENHA),
                           cargo="coordenador"),
        "prof_a": Usuario(escola_id=escola.id, nome="Prof A",
                          email="prof.a@priv.local", senha_hash=hash_senha(SENHA),
                          cargo="professor"),
        "admin_b": Usuario(escola_id=escola_b.id, nome="Admin B",
                           email="admin.b@priv.local", senha_hash=hash_senha(SENHA),
                           cargo="admin"),
        # Secretaria: rede vinculada, NÃO global, com escola_id e cargo admin.
        "secretaria": Usuario(escola_id=escola.id, nome="Secretaria",
                              email="sec@priv.local", senha_hash=hash_senha(SENHA),
                              cargo="admin", rede_id=rede.id),
        "global": Usuario(escola_id=escola.id, nome="Dono", email="dono@priv.local",
                          senha_hash=hash_senha(SENHA), cargo="admin",
                          is_global=True),
    }
    db.add_all(list(contas.values()))
    db.commit()
    ids = {chave: conta.id for chave, conta in contas.items()}
    return {"escola": escola.id, "escola_b": escola_b.id, "fora": escola_fora.id,
            "rede": rede.id, "isca": isca.id, "turma": turma.id, "ids": ids}


# =============================================================================
# C-03 — a conta da Secretaria não é administrável por gestor de escola
# =============================================================================

def test_admin_de_escola_nao_toma_a_conta_da_secretaria(cenario):
    """Os dois vetores do PoC: trocar a senha e gerar link de redefinição."""
    eid, sec = cenario["escola"], cenario["ids"]["secretaria"]
    cli = _login("admin.a@priv.local")

    troca = cli.patch(f"/api/v1/escolas/{eid}/usuarios/{sec}",
                      json={"senha": "S3nha#DoAtacante"})
    assert troca.status_code == 403, troca.text

    link = cli.post(f"/api/v1/escolas/{eid}/usuarios/{sec}/redefinir-senha")
    assert link.status_code == 403, link.text
    assert "token" not in link.text


def test_admin_de_escola_nao_desativa_nem_exclui_a_secretaria(cenario, db):
    """Negar de saída também protege disponibilidade: um gestor de escola não
    derruba a conta institucional do município."""
    eid, sec = cenario["escola"], cenario["ids"]["secretaria"]
    cli = _login("admin.a@priv.local")

    assert cli.patch(f"/api/v1/escolas/{eid}/usuarios/{sec}",
                     json={"status": "inativo"}).status_code == 403
    assert cli.delete(f"/api/v1/escolas/{eid}/usuarios/{sec}").status_code == 403
    assert cli.put(f"/api/v1/escolas/{eid}/usuarios/{sec}/turmas",
                   json={"turma_ids": []}).status_code == 403
    db.expire_all()
    conta = db.get(Usuario, sec)
    assert conta.status == "ativo" and conta.rede_id == cenario["rede"]


def test_senha_da_secretaria_intacta_apos_a_tentativa(cenario):
    """Prova de ponta a ponta: depois do ataque, a Secretaria ainda entra com a
    senha dela — e o atacante não entra com a que tentou gravar."""
    eid, sec = cenario["escola"], cenario["ids"]["secretaria"]
    cli = _login("admin.a@priv.local")
    cli.patch(f"/api/v1/escolas/{eid}/usuarios/{sec}",
              json={"senha": "S3nha#DoAtacante"})

    anonimo = TestClient(app)
    invasao = anonimo.post("/api/v1/auth/login",
                           data={"username": "sec@priv.local",
                                 "password": "S3nha#DoAtacante"})
    assert invasao.status_code == 401
    _login("sec@priv.local")  # a dona da conta continua entrando


def test_admin_global_continua_gerenciando_a_conta_de_rede(cenario):
    """Sem over-block: quem administra a plataforma segue administrando."""
    eid, sec = cenario["escola"], cenario["ids"]["secretaria"]
    cli = _login("dono@priv.local")
    assert cli.patch(f"/api/v1/escolas/{eid}/usuarios/{sec}",
                     json={"nome": "Secretaria Municipal"}).status_code == 200
    assert cli.post(
        f"/api/v1/escolas/{eid}/usuarios/{sec}/redefinir-senha").status_code == 200


def test_gestor_de_escola_administra_a_propria_equipe(cenario):
    """A correção não pode fechar o uso legítimo: professor da própria escola
    continua administrável pelo admin local."""
    eid, prof = cenario["escola"], cenario["ids"]["prof_a"]
    cli = _login("admin.a@priv.local")
    assert cli.patch(f"/api/v1/escolas/{eid}/usuarios/{prof}",
                     json={"nome": "Prof A Silva"}).status_code == 200
    assert cli.post(
        f"/api/v1/escolas/{eid}/usuarios/{prof}/redefinir-senha").status_code == 200


def test_isolamento_entre_escolas_e_contas_globais(cenario):
    """Usuário de outra escola: 404 (não revela existência). Conta global: 403."""
    eid = cenario["escola"]
    cli = _login("admin.a@priv.local")
    assert cli.patch(f"/api/v1/escolas/{eid}/usuarios/{cenario['ids']['admin_b']}",
                     json={"nome": "x"}).status_code == 404
    assert cli.patch(f"/api/v1/escolas/{eid}/usuarios/{cenario['ids']['global']}",
                     json={"nome": "x"}).status_code == 403
    # E o admin da escola A não alcança a escola B nem pela rota dela.
    assert cli.get(
        f"/api/v1/escolas/{cenario['escola_b']}/usuarios").status_code == 403


def test_professor_e_coordenador_nao_administram_usuarios(cenario):
    eid = cenario["escola"]
    alvo = cenario["ids"]["prof_a"]
    prof = _login("prof.a@priv.local")
    coord = _login("coord.a@priv.local")
    assert prof.get(f"/api/v1/escolas/{eid}/usuarios").status_code == 200  # só a si
    assert prof.patch(f"/api/v1/escolas/{eid}/usuarios/{alvo}",
                      json={"cargo": "admin"}).status_code == 403
    assert coord.patch(f"/api/v1/escolas/{eid}/usuarios/{alvo}",
                       json={"cargo": "admin"}).status_code == 403
    # Coordenador exclui professor (permitido), mas não administrador.
    assert coord.delete(
        f"/api/v1/escolas/{eid}/usuarios/{cenario['ids']['admin_a2']}"
    ).status_code == 403


def test_promover_para_admin_nao_concede_alcance_de_rede(cenario, db):
    """A promoção que o gestor PODE fazer (cargo) não vira alcance: nem
    `is_global`, nem `rede_id`, nem leitura da rede/de outra escola."""
    eid = cenario["escola"]
    cli = _login("admin.a@priv.local")
    r = cli.patch(f"/api/v1/escolas/{eid}/usuarios/{cenario['ids']['prof_a']}",
                  json={"cargo": "admin"})
    assert r.status_code == 200 and r.json()["cargo"] == "admin"
    db.expire_all()
    virou = db.get(Usuario, cenario["ids"]["prof_a"])
    assert virou.is_global is False and virou.rede_id is None

    novo = _login("prof.a@priv.local")
    assert novo.get(f"/api/v1/redes/{cenario['rede']}/dashboard").status_code == 403
    assert novo.get(f"/api/v1/escolas/{cenario['escola_b']}/ranking").status_code == 403
    assert novo.get("/api/v1/redes/panorama-global").status_code == 403


def test_criacao_de_usuario_nao_permite_definir_alcance(cenario, db):
    """`is_global` e `rede_id` não são campos de entrada: mandá-los é ignorado."""
    eid = cenario["escola"]
    cli = _login("admin.a@priv.local")
    r = cli.post(f"/api/v1/escolas/{eid}/usuarios",
                 json={"nome": "Escalada Silva", "email": "escalada@exemplo.com",
                       "senha": SENHA, "cargo": "professor",
                       "is_global": True, "rede_id": cenario["rede"],
                       "escola_id": cenario["escola_b"]})
    assert r.status_code == 201, r.text
    criado = db.get(Usuario, r.json()["id"])
    assert criado.is_global is False
    assert criado.rede_id is None
    assert criado.escola_id == eid


def test_conta_de_rede_nao_conta_como_administrador_da_escola(cenario, db):
    """A Secretaria (cargo admin, hospedada na escola) não substitui o gestor
    local: rebaixar o ÚNICO admin de escola continua barrado por lockout."""
    eid = cenario["escola"]
    dono = _login("dono@priv.local")
    # Sobra um único admin de escola (o do fixture `escola_completa` e o A2 saem).
    for chave in ("admin_a2",):
        assert dono.patch(f"/api/v1/escolas/{eid}/usuarios/{cenario['ids'][chave]}",
                          json={"status": "inativo"}).status_code == 200
    admin_fixture = db.execute(
        Usuario.__table__.select().where(Usuario.email == "admin@teste.local")
    ).first()
    assert dono.patch(f"/api/v1/escolas/{eid}/usuarios/{admin_fixture.id}",
                      json={"status": "inativo"}).status_code == 200
    # Resta só "Admin A" — com a Secretaria presente e com cargo admin.
    barrado = dono.patch(f"/api/v1/escolas/{eid}/usuarios/{cenario['ids']['admin_a']}",
                         json={"status": "inativo"})
    assert barrado.status_code == 400
    assert "único administrador" in barrado.json()["detail"]


def test_administracao_de_usuarios_exige_autenticacao(cenario):
    anonimo = TestClient(app)
    eid, sec = cenario["escola"], cenario["ids"]["secretaria"]
    assert anonimo.get(f"/api/v1/escolas/{eid}/usuarios").status_code == 401
    assert anonimo.patch(f"/api/v1/escolas/{eid}/usuarios/{sec}",
                         json={"senha": SENHA}).status_code == 401


# =============================================================================
# C-04 — PII de criança não sai da escola pelo router administrativo
# =============================================================================

def test_secretaria_nao_baixa_backup_com_pii_de_crianca(cenario):
    """O furo original: 200 com NOME, NASC e OBSERVAÇÕES de qualquer escola."""
    sec = _login("sec@priv.local")
    for escola in (cenario["escola"], cenario["escola_b"]):
        r = sec.get(f"/api/v1/escolas/{escola}/backup")
        assert r.status_code == 403, (escola, r.status_code)
        assert ISCA_NOME not in r.text and ISCA_OBS not in r.text


def test_secretaria_nao_restaura_backup(cenario):
    """A restauração APAGA os dados pedagógicos da escola — a Secretaria não
    opera escola nem para ler nem para escrever."""
    sec = _login("sec@priv.local")
    r = sec.post(f"/api/v1/escolas/{cenario['escola']}/restaurar",
                 files={"arquivo": ("b.json", b'{"tabelas": {}}', "application/json")})
    assert r.status_code == 403, r.text


def test_gestor_da_escola_e_admin_global_continuam_com_backup(cenario):
    """Sem over-block: quem é dono do dado continua exportando."""
    eid = cenario["escola"]
    for email in ("admin.a@priv.local", "dono@priv.local"):
        r = _login(email).get(f"/api/v1/escolas/{eid}/backup")
        assert r.status_code == 200, (email, r.text[:200])
        assert ISCA_NOME in r.text  # é o backup da PRÓPRIA escola


def test_backup_negado_a_outra_escola_e_a_anonimo(cenario):
    eid = cenario["escola"]
    assert _login("admin.b@priv.local").get(
        f"/api/v1/escolas/{eid}/backup").status_code == 403
    assert TestClient(app).get(f"/api/v1/escolas/{eid}/backup").status_code == 401


def test_router_administrativo_inteiro_nega_a_secretaria(cenario):
    """Proteção ESTRUTURAL, não rota a rota: a dependência está no router, então
    qualquer rota nova nasce protegida. Se este teste falhar depois de alguém
    acrescentar uma rota em `routers/admin.py`, é sinal de que a dependência
    saiu do lugar — não de que o teste envelheceu."""
    from app.routers import admin as router_admin

    sec = _login("sec@priv.local")
    subs = {"escola_id": cenario["escola"], "usuario_id": cenario["ids"]["prof_a"],
            "aluno_id": cenario["isca"], "turma_id": cenario["turma"]}
    verificadas = 0
    for rota in router_admin.router.routes:
        caminho = "/api/v1" + rota.path
        for chave, valor in subs.items():
            caminho = caminho.replace("{%s}" % chave, str(valor))
        assert "{" not in caminho, f"parâmetro não mapeado no teste: {rota.path}"
        for metodo in sorted(rota.methods - {"HEAD", "OPTIONS"}):
            resposta = sec.request(metodo, caminho, json={})
            assert resposta.status_code == 403, (metodo, rota.path,
                                                 resposta.status_code)
            assert "Secretaria" in resposta.json().get("detail", "")
            verificadas += 1
    assert verificadas >= 15, "varredura não cobriu o router (rotas somem?)"


def test_nenhuma_rota_de_leitura_entrega_pii_de_crianca_a_secretaria(cenario):
    """Varredura ampla (a mesma da auditoria, agora permanente): a Secretaria
    percorre TODAS as rotas GET da API e o nome/observação da criança-isca não
    pode aparecer em nenhuma resposta. É o teste que pega a "rota equivalente"
    que alguém venha a criar amanhã."""
    sec = _login("sec@priv.local")
    subs = {"escola_id": cenario["escola"], "aluno_id": cenario["isca"],
            "turma_id": cenario["turma"], "usuario_id": cenario["ids"]["prof_a"],
            "rede_id": cenario["rede"], "namespace": "geral", "tipo": "alunos",
            "conversa_id": 1, "execucao_id": 1, "avaliacao_id": 1, "fonte_id": 1,
            "id": 1, "notificacao_id": 1, "livro_id": 1, "token": "x",
            "plataforma": "matific"}
    # Consultas obrigatórias de rotas que sem elas devolvem 422 (e não seriam
    # exercidas de verdade) — as duas apontam DIRETO para a criança-isca.
    query = {
        "/api/v1/escolas/{escola_id}/pesquisa": {"q": ISCA_NOME.split()[0]},
        "/api/v1/escolas/{escola_id}/comparar": {
            "tipo_a": "aluno", "id_a": cenario["isca"],
            "tipo_b": "aluno", "id_b": cenario["isca"]},
    }
    vistas, vazamentos = set(), []
    for rota in app.routes:
        metodos = getattr(rota, "methods", None) or set()
        caminho = getattr(rota, "path", "")
        if "GET" not in metodos or not caminho.startswith("/api/") or caminho in vistas:
            continue
        vistas.add(caminho)
        url = caminho
        for chave, valor in subs.items():
            url = url.replace("{%s}" % chave, str(valor))
        if "{" in url:
            continue
        resposta = sec.get(url, params=query.get(caminho))
        if ISCA_NOME in resposta.text or ISCA_OBS in resposta.text:
            vazamentos.append((caminho, resposta.status_code))
    assert not vazamentos, f"PII de criança vazou para a Secretaria: {vazamentos}"
    assert len(vistas) >= 60, "a varredura deixou de enxergar as rotas da API"


def test_secretaria_mantem_a_visao_agregada_da_rede(cenario):
    """A blindagem não pode transformar a Secretaria em conta inútil: o que ela
    existe para ver continua aberto."""
    sec = _login("sec@priv.local")
    for rota in (f"/api/v1/redes/{cenario['rede']}/dashboard",
                 f"/api/v1/redes/{cenario['rede']}/ranking",
                 f"/api/v1/escolas/{cenario['escola']}/resumo-escola",
                 f"/api/v1/escolas/{cenario['escola_b']}/dashboard",
                 "/api/v1/escolas"):
        assert sec.get(rota).status_code == 200, rota


# =============================================================================
# C-05 — nenhum ambiente nasce com conta administrativa secreta
# =============================================================================

_EMAIL_ANTIGO_DO_CODIGO = "edumedeiros1405@gmail.com"


def test_email_do_dono_nao_esta_mais_cravado_no_codigo():
    """Guarda contra reintrodução: configuração de tenant não volta ao código."""
    fonte = Path(config_mod.__file__).with_name("database.py").read_text("utf-8")
    assert _EMAIL_ANTIGO_DO_CODIGO not in fonte
    assert "@gmail.com" not in fonte


def test_ambiente_novo_nao_promove_ninguem_a_admin_global(db, escola_completa,
                                                          monkeypatch):
    """Município novo / staging / homologação / restauração: sem
    ADMIN_GLOBAL_EMAIL declarado, o boot NÃO promove conta nenhuma — nem a que
    um admin de escola criou com o e-mail que antes estava no código."""
    from app.core.database import garantir_dados_base

    monkeypatch.setattr(config_mod.settings, "ADMIN_GLOBAL_EMAIL", "")
    reivindicada = Usuario(escola_id=escola_completa["escola"].id, nome="Atacante",
                           email=_EMAIL_ANTIGO_DO_CODIGO,
                           senha_hash=hash_senha(SENHA), cargo="professor")
    db.add(reivindicada)
    db.commit()

    garantir_dados_base(db.get_bind())          # tudo o que o boot faria
    db.expire_all()
    assert db.get(Usuario, reivindicada.id).is_global is False

    # E o acesso segue sendo o de um professor de UMA escola.
    cli = _login(_EMAIL_ANTIGO_DO_CODIGO)
    assert cli.get("/api/v1/redes/panorama-global").status_code == 403


def test_promocao_explicita_funciona_e_e_idempotente(db, escola_completa,
                                                     monkeypatch):
    """Declarado no ambiente, o comportamento útil continua: promove uma vez,
    repetir não tem efeito colateral, e o casamento é insensível à caixa."""
    from app.core.database import _promover_admin_global

    monkeypatch.setattr(config_mod.settings, "ADMIN_GLOBAL_EMAIL",
                        "dona.da.plataforma@exemplo.com")
    dona = Usuario(escola_id=escola_completa["escola"].id, nome="Dona",
                   email="Dona.Da.Plataforma@Exemplo.com",  # caixa diferente
                   senha_hash=hash_senha(SENHA), cargo="admin")
    db.add(dona)
    db.commit()
    assert dona.is_global is False

    motor = db.get_bind()
    _promover_admin_global(motor)
    db.expire_all()
    assert db.get(Usuario, dona.id).is_global is True
    _promover_admin_global(motor)
    db.expire_all()
    assert db.get(Usuario, dona.id).is_global is True


def test_gestor_de_escola_nao_reivindica_a_conta_do_dono(cenario, monkeypatch):
    """Com a variável declarada, o e-mail do dono fica RESERVADO: as duas rotas
    de escola que criam conta de acesso recusam criá-la."""
    monkeypatch.setattr(config_mod.settings, "ADMIN_GLOBAL_EMAIL",
                        "dona.da.plataforma@exemplo.com")
    eid = cenario["escola"]
    cli = _login("admin.a@priv.local")

    direto = cli.post(f"/api/v1/escolas/{eid}/usuarios",
                      json={"nome": "Nao Sou A Dona",
                            "email": "Dona.Da.Plataforma@exemplo.com",
                            "senha": SENHA, "cargo": "professor"})
    assert direto.status_code == 403, direto.text

    via_professor = cli.post(
        f"/api/v1/escolas/{eid}/professores/completo",
        json={"nome": "Nao Sou A Dona", "email": "dona.da.plataforma@exemplo.com",
              "criar_acesso": True})
    assert via_professor.status_code == 403, via_professor.text

    # Sem a variável declarada nada é reservado (nada é promovido tampouco).
    monkeypatch.setattr(config_mod.settings, "ADMIN_GLOBAL_EMAIL", "")
    livre = cli.post(f"/api/v1/escolas/{eid}/usuarios",
                     json={"nome": "Pessoa Comum",
                           "email": "dona.da.plataforma@exemplo.com",
                           "senha": SENHA, "cargo": "professor"})
    assert livre.status_code == 201, livre.text


def test_admin_global_email_malformado_barra_producao(monkeypatch):
    """Fail-closed no molde do SECRET_KEY: um valor que jamais casaria com uma
    conta (lista/curinga/espaço) falharia em SILÊNCIO — produção recusa subir."""
    monkeypatch.setenv("ENV", "producao")
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:y@localhost/z")
    for invalido in ("*", "a@b.com, c@d.com", "sem-arroba", "dono@exemplo.com extra"):
        monkeypatch.setenv("ADMIN_GLOBAL_EMAIL", invalido)
        with pytest.raises(RuntimeError, match="ADMIN_GLOBAL_EMAIL"):
            config_mod.Settings()

    monkeypatch.setenv("ADMIN_GLOBAL_EMAIL", "  Dono@Exemplo.COM  ")
    assert config_mod.Settings().ADMIN_GLOBAL_EMAIL == "dono@exemplo.com"


def test_padrao_de_fabrica_nao_declara_dono(monkeypatch):
    monkeypatch.delenv("ADMIN_GLOBAL_EMAIL", raising=False)
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    assert config_mod.Settings().ADMIN_GLOBAL_EMAIL == ""
    assert config_mod.email_reservado_ao_dono("qualquer@coisa.com") is False
