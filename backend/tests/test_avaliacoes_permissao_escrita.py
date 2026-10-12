"""Quem grava e quem apaga resultados de AVALIAÇÕES EXTERNAS (IDEB, SAEB...).

Decisão do dono: importar e excluir é do admin global e da Secretaria da PRÓPRIA
rede. A coordenação e a administração de escola (e o professor) recebem 403 em
TODA rota de escrita — inclusive `analisar`, que é o 1º passo da importação. A
Secretaria continua limitada às escolas da rede dela: escola de outra rede (ou
sem rede) nunca casa nem é apagada. A leitura não muda.

O cenário tem as três situações de escola que importam para o escopo — da rede
A, da rede B e sem rede — e o arquivo traz o INEP das três: se algum filtro
falhar, a escola indevida casa e o teste acusa.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.security import hash_senha
from app.main import app
from app.models import Escola, Rede, ResultadoAvaliacao, Usuario
from app.routers import avaliacoes as router_avaliacoes
from app.services import avaliacoes as svc

SENHA = "C0nstela#Aval1acoes"
INEP_A, INEP_B, INEP_SEM_REDE = "35012345", "35067890", "35011111"

# Prefixo estável da mensagem de 403 (deps.exigir_admin_global_ou_secretaria).
MSG_403 = "Só o administrador global e a Secretaria da rede podem importar"


def _csv(linhas: list[list[str]]) -> bytes:
    return "\n".join(";".join(c for c in linha) for linha in linhas).encode("utf-8")


# IDEB por escola: pré-âmbulo + cabeçalho + as três escolas + um INEP inexistente.
_PLANILHA = _csv([
    ["Resultados do IDEB - Anos Iniciais"],
    ["CO_ESCOLA", "NO_ESCOLA", "IDEB"],
    [INEP_A, "EM da Rede A", "6,1"],
    [INEP_B, "EM da Rede B", "5,3"],
    [INEP_SEM_REDE, "EM sem rede", "4,8"],
    ["99999999", "EM fora do banco", "4,0"],
])

# Criança Alfabetizada (preset de 1 clique): INEP · taxa (%).
_PLANILHA_ALFAB = _csv([
    ["CO_ESCOLA", "TAXA_ALFABETIZADOS_PCT"],
    [INEP_A, "96.8"], [INEP_B, "90.1"], [INEP_SEM_REDE, "88.0"],
])

_MAPEAMENTO = {"avaliacao": "ideb", "indicador": "ideb", "unidade": "indice",
               "linha_dados": 2, "col_inep": 0, "col_valor": 2,
               "etapa_fixa": "anos_iniciais"}


@pytest.fixture()
def cenario(db, escola_completa):
    """Rede A (com a escola-base), rede B e uma escola independente, cada uma
    com o INEP que está no arquivo; contas de cada perfil."""
    rede_a = Rede(nome="Rede A", status="ativa")
    rede_b = Rede(nome="Rede B", status="ativa")
    db.add_all([rede_a, rede_b])
    db.flush()
    escola_a = escola_completa["escola"]
    escola_a.rede_id, escola_a.codigo_inep = rede_a.id, INEP_A
    escola_b = Escola(nome="EM da Rede B", ano_letivo_ativo=2026, status="ativa",
                      rede_id=rede_b.id, codigo_inep=INEP_B)
    escola_sem_rede = Escola(nome="EM sem rede", ano_letivo_ativo=2026, status="ativa",
                             codigo_inep=INEP_SEM_REDE)
    db.add_all([escola_b, escola_sem_rede])
    db.flush()

    def conta(email, cargo, *, escola_id=None, rede_id=None, is_global=False):
        return Usuario(nome=email.split("@")[0], email=email, cargo=cargo,
                       senha_hash=hash_senha(SENHA), escola_id=escola_id,
                       rede_id=rede_id, is_global=is_global)

    contas = {
        "global": conta("global@aval.local", "admin", escola_id=escola_a.id,
                        is_global=True),
        # Secretaria típica: conta de rede com cargo de coordenador.
        "sec_a": conta("sec.a@aval.local", "coordenador", rede_id=rede_a.id),
        # Secretaria promovida de uma conta de escola: mantém o escola_id de
        # origem e tem cargo admin — o alcance continua sendo a REDE inteira.
        "sec_a_admin": conta("sec.a.admin@aval.local", "admin",
                             escola_id=escola_a.id, rede_id=rede_a.id),
        # Conta de rede com cargo de professor: a regra antiga já a barrava pelo
        # cargo e a decisão só RESTRINGE — continua barrada.
        "sec_a_prof": conta("sec.a.prof@aval.local", "professor", rede_id=rede_a.id),
        "coord_a": conta("coord.a@aval.local", "coordenador", escola_id=escola_a.id),
        "admin_a": conta("admin.a@aval.local", "admin", escola_id=escola_a.id),
        "prof_a": conta("prof.a@aval.local", "professor", escola_id=escola_a.id),
    }
    db.add_all(list(contas.values()))
    db.commit()
    return {"rede_a": rede_a.id, "rede_b": rede_b.id, "escola_a": escola_a.id,
            "escola_b": escola_b.id, "escola_sem_rede": escola_sem_rede.id}


def _login(chave: str) -> TestClient:
    email = {"global": "global@aval.local", "sec_a": "sec.a@aval.local",
             "sec_a_admin": "sec.a.admin@aval.local",
             "sec_a_prof": "sec.a.prof@aval.local", "coord_a": "coord.a@aval.local",
             "admin_a": "admin.a@aval.local", "prof_a": "prof.a@aval.local"}[chave]
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", data={"username": email, "password": SENHA})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _semear_ideb_2023(db) -> None:
    """IDEB 2023 gravado nas TRÊS escolas (como o admin global faria)."""
    svc.importar_resultados(
        db, _PLANILHA, "ideb.csv", avaliacao_chave="ideb", edicao=2023,
        indicador="ideb", unidade="indice", linha_dados=2, col_inep=0, col_valor=2,
        etapa_fixa="anos_iniciais", escopo_escolas=None)
    db.commit()


def _retrato(db) -> set[tuple]:
    db.expire_all()
    return {(r.avaliacao_id, r.edicao, r.escola_id, r.indicador, r.etapa,
             r.componente, round(r.valor, 2))
            for r in db.execute(select(ResultadoAvaliacao)).scalars()}


def _escolas_com_resultado(db) -> set[int]:
    db.expire_all()
    return set(db.execute(select(ResultadoAvaliacao.escola_id)).scalars())


# Pedidos VÁLIDOS para cada rota de escrita: o 403 tem de vir da permissão, não
# de um corpo malformado (422) que mascararia a falta da trava.
def _analisar(c):
    return c.post("/api/v1/avaliacoes/analisar",
                  files={"arquivo": ("ideb.csv", _PLANILHA, "text/csv")})


def _importar(c, edicao=2025):
    return c.post("/api/v1/avaliacoes/importar", data={**_MAPEAMENTO, "edicao": edicao},
                  files={"arquivo": ("ideb.csv", _PLANILHA, "text/csv")})


def _importar_preset(c):
    return c.post("/api/v1/avaliacoes/importar-preset",
                  data={"preset": "crianca_alfab", "edicao": 2025},
                  files={"arquivo": ("alfab.csv", _PLANILHA_ALFAB, "text/csv")})


def _excluir(c):
    return c.delete("/api/v1/avaliacoes/resultados?avaliacao=ideb&edicao=2023"
                    "&indicador=ideb&etapa=anos_iniciais")


ROTAS_DE_ESCRITA = {"analisar": _analisar, "importar": _importar,
                    "importar-preset": _importar_preset, "excluir": _excluir}


# --- Quem NÃO pode -------------------------------------------------------------

@pytest.mark.parametrize("rota", sorted(ROTAS_DE_ESCRITA))
@pytest.mark.parametrize("perfil", ["coord_a", "admin_a", "prof_a", "sec_a_prof"])
def test_escrita_negada_a_quem_nao_e_global_nem_secretaria(cenario, db, perfil, rota):
    """Coordenação e administração de escola, professor e conta de rede sem cargo
    de gestão: 403 com mensagem que diz quem pode — e nada muda no banco."""
    _semear_ideb_2023(db)
    antes = _retrato(db)

    resposta = ROTAS_DE_ESCRITA[rota](_login(perfil))

    assert resposta.status_code == 403, (perfil, rota, resposta.text)
    assert resposta.json()["detail"].startswith(MSG_403)
    assert _retrato(db) == antes      # nada gravado, nada apagado


def test_coordenacao_de_escola_nao_reescreve_o_ideb_da_propria_escola(cenario, db):
    """O caso que motivou a decisão: a coordenação reimportando um valor diferente
    para a PRÓPRIA escola não pode sobrescrever o IDEB que a rede usa."""
    _semear_ideb_2023(db)
    adulterado = _csv([["pre"], ["CO", "NO", "IDEB"], [INEP_A, "EM da Rede A", "9,9"]])
    r = _login("coord_a").post(
        "/api/v1/avaliacoes/importar", data={**_MAPEAMENTO, "edicao": 2023},
        files={"arquivo": ("ideb.csv", adulterado, "text/csv")})
    assert r.status_code == 403, r.text
    db.expire_all()
    valor = db.execute(select(ResultadoAvaliacao.valor).where(
        ResultadoAvaliacao.escola_id == cenario["escola_a"])).scalar_one()
    assert round(valor, 1) == 6.1


def test_varredura_toda_rota_de_escrita_do_router_barra_a_escola(cenario):
    """Rota de escrita NOVA no router de avaliações nasce protegida: a coordenação
    e a administração de escola recebem 403 em todo POST/PUT/PATCH/DELETE (as do
    robô continuam com a trava de admin global)."""
    verificadas = 0
    for perfil in ("coord_a", "admin_a"):
        cli = _login(perfil)
        for rota in router_avaliacoes.router.routes:
            metodos = rota.methods - {"GET", "HEAD", "OPTIONS"}
            caminho = "/api/v1" + rota.path.replace("{fonte_id}", "1")
            assert "{" not in caminho, f"parâmetro não mapeado no teste: {rota.path}"
            for metodo in sorted(metodos):
                resposta = cli.request(metodo, caminho)
                assert resposta.status_code == 403, (perfil, metodo, rota.path,
                                                     resposta.status_code)
                verificadas += 1
    assert verificadas >= 16, "a varredura deixou de enxergar as rotas de escrita"


# --- Secretaria: pode, mas só na própria rede ---------------------------------

@pytest.mark.parametrize("perfil", ["sec_a", "sec_a_admin"])
def test_secretaria_analisa_a_planilha(cenario, perfil):
    r = _analisar(_login(perfil))
    assert r.status_code == 200, r.text
    assert r.json()["primeiras_linhas"][1] == ["CO_ESCOLA", "NO_ESCOLA", "IDEB"]


@pytest.mark.parametrize("perfil", ["sec_a", "sec_a_admin"])
def test_secretaria_importa_so_nas_escolas_da_propria_rede(cenario, db, perfil):
    r = _importar(_login(perfil))
    assert r.status_code == 200, r.text
    corpo = r.json()
    # Só a escola da rede A casa; a da rede B, a sem rede e o INEP inexistente não.
    assert corpo["casados"] == 1 and corpo["inseridos"] == 1
    assert corpo["nao_casados"] == 3
    assert _escolas_com_resultado(db) == {cenario["escola_a"]}


def test_secretaria_importa_preset_so_na_propria_rede(cenario, db):
    r = _importar_preset(_login("sec_a"))
    assert r.status_code == 200, r.text
    assert r.json()["series"][0]["casados"] == 1
    assert _escolas_com_resultado(db) == {cenario["escola_a"]}


def test_secretaria_exclui_so_na_propria_rede(cenario, db):
    _semear_ideb_2023(db)
    assert _escolas_com_resultado(db) == {cenario["escola_a"], cenario["escola_b"],
                                          cenario["escola_sem_rede"]}
    r = _excluir(_login("sec_a"))
    assert r.status_code == 200, r.text
    assert r.json()["removidos"] == 1
    # A rede B e a escola sem rede continuam com o IDEB delas.
    assert _escolas_com_resultado(db) == {cenario["escola_b"], cenario["escola_sem_rede"]}


# --- Admin global: todas as escolas -------------------------------------------

def test_admin_global_importa_e_exclui_em_todas_as_escolas(cenario, db):
    cli = _login("global")
    assert _analisar(cli).status_code == 200
    r = _importar(cli, edicao=2023)
    assert r.status_code == 200, r.text
    assert r.json()["casados"] == 3
    assert _importar_preset(cli).json()["series"][0]["casados"] == 3
    assert _escolas_com_resultado(db) == {cenario["escola_a"], cenario["escola_b"],
                                          cenario["escola_sem_rede"]}

    r = _excluir(cli)
    assert r.status_code == 200 and r.json()["removidos"] == 3
    db.expire_all()
    # Sobrou só a Criança Alfabetizada (outra série): o IDEB saiu das três.
    restantes = db.execute(select(func.count(ResultadoAvaliacao.id))
                           .where(ResultadoAvaliacao.indicador == "ideb")).scalar_one()
    assert restantes == 0


# --- O que NÃO muda -------------------------------------------------------------

@pytest.mark.parametrize("perfil", ["global", "sec_a", "sec_a_prof", "coord_a",
                                    "admin_a", "prof_a"])
def test_leitura_do_catalogo_e_dos_presets_segue_aberta(cenario, perfil):
    cli = _login(perfil)
    assert cli.get("/api/v1/avaliacoes").status_code == 200
    assert cli.get("/api/v1/avaliacoes/presets-import").status_code == 200


def test_leitura_da_rede_segue_com_as_regras_de_antes(cenario, db):
    """Correlação/opções continuam pela trava de REDE (`exigir_rede`): global e
    Secretaria da própria rede leem; Secretaria não lê outra rede; escola não lê."""
    _semear_ideb_2023(db)
    rede_a, rede_b = cenario["rede_a"], cenario["rede_b"]
    opcoes = f"/api/v1/redes/{rede_a}/avaliacoes/opcoes"
    correlacao = (f"/api/v1/redes/{rede_a}/avaliacoes/correlacao"
                  "?avaliacao=ideb&indicador=ideb&edicao=2023&etapa=anos_iniciais")
    for perfil in ("global", "sec_a"):
        cli = _login(perfil)
        assert cli.get(opcoes).status_code == 200, perfil
        assert cli.get(correlacao).status_code == 200, perfil
    assert _login("sec_a").get(
        f"/api/v1/redes/{rede_b}/avaliacoes/opcoes").status_code == 403
    assert _login("coord_a").get(opcoes).status_code == 403


def test_fontes_do_robo_continuam_so_do_admin_global(cenario):
    """A nova dependência não abriu as fontes de coleta para a Secretaria."""
    sec = _login("sec_a")
    assert sec.get("/api/v1/avaliacoes/fontes").status_code == 403
    criar = sec.post("/api/v1/avaliacoes/fontes", json={
        "avaliacao": "ideb", "nome": "x", "url": "https://download.inep.gov.br/x.csv",
        "edicao": 2023, "indicador": "ideb", "unidade": "indice",
        "mapeamento": {"linha_dados": 2, "col_inep": 0, "col_valor": 2}})
    assert criar.status_code == 403
    assert "administradores globais" in criar.json()["detail"]
