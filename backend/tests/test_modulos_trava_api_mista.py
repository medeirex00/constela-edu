"""Trava de MÓDULO CONTRATADO nas rotas que entregavam o Matific com a
Matemática fora do plano (achado e97/autorização 1).

O desenho (``services/modulos``) diz que o módulo que a rede não contratou não
existe para ela, nem na interface nem na API. Antes, só o front escondia o
Matific: o placar ao vivo, a evolução, a linha do tempo, o espelho, o perfil
(autenticado e público), o telão, a coleta e a importação seguiam entregando ou
coletando o dado. Aqui cada superfície tem o lado desligado (o que a rede SEM
Matemática recebe) e um controle (escola sem rede = tudo ligado, ou o outro
módulo desligado). Dados 100% fictícios.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.core import deps
from app.core.security import hash_senha
from app.main import app
from app.models import (
    EventoAluno,
    Importacao,
    ModuloRede,
    Nota,
    Professor,
    Rede,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
    Usuario,
)
from app.models.sincronizacao import (
    SincronizacaoAlerta,
    SincronizacaoConfig,
    SincronizacaoExecucao,
)
from app.services import modulos as svc_modulos
from app.services import scoring
from tests._ano_letivo import escola_no_ano_de_hoje  # noqa: F401 — fixture

API = "/api/v1"


def _agora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


EMAIL_PROF = "prof.trava.mista@teste.local"


def _login(email: str) -> TestClient:
    c = TestClient(app)
    r = c.post(f"{API}/auth/login", data={"username": email, "password": "s3nh4"})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _rede_com(db, escola, desligado: str | None):
    """Põe a escola numa rede com ``desligado`` fora do plano (None = tudo ligado)."""
    rede = Rede(nome=f"Rede Trava Mista {desligado}", status="ativa")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    for modulo in svc_modulos.TODOS:
        db.add(ModuloRede(rede_id=rede.id, modulo=modulo, ativo=(modulo != desligado)))
    db.flush()
    return rede


def _dados_das_duas(db, escola, aluno):
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                           atividades=21, estrelas=63, pontuacao_media=3.5,
                           data_referencia=_agora()))
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                            livros_unicos=4, tempo_leitura_min=50,
                            questoes_tentativas=10, questoes_acertos=8,
                            data_referencia=_agora()))
    db.add(EventoAluno(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                       plataforma="matific", tipo_evento="atividade",
                       ocorrido_em=_agora(), chave_natural="trava-mista-m",
                       conteudo_titulo="Atividade ficticia", pontuacao=2.0,
                       tempo_segundos=600))
    db.add(EventoAluno(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                       plataforma="elefante", tipo_evento="leitura",
                       ocorrido_em=_agora() - timedelta(hours=1),
                       chave_natural="trava-mista-e", conteudo_titulo="Livro ficticio",
                       tempo_segundos=300))


def _professor_da_turma(db, escola, turma):
    prof = Professor(escola_id=escola.id, nome="Prof Trava Mista", email=EMAIL_PROF)
    db.add(prof)
    db.flush()
    turma.professor_id = prof.id
    db.add(Usuario(escola_id=escola.id, nome="Prof Trava Mista", email=EMAIL_PROF,
                   senha_hash=hash_senha("s3nh4"), cargo="professor"))


@pytest.fixture()
def sem_matematica(db, escola_completa):
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    _rede_com(db, escola, "matematica")
    _dados_das_duas(db, escola, aluno)
    _professor_da_turma(db, escola, escola_completa["turma"])
    db.commit()
    return escola, aluno


@pytest.fixture()
def tudo_ligado(db, escola_completa):
    """Controle: escola AVULSA (sem rede) = todos os módulos ligados."""
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    _dados_das_duas(db, escola, aluno)
    _professor_da_turma(db, escola, escola_completa["turma"])
    db.commit()
    return escola, aluno


# --- Placar ao vivo do Matific ------------------------------------------------

def _placar_nao_pode_ser_chamado(monkeypatch):
    from app.sync import aovivo

    def _explode(*_a, **_k):
        raise AssertionError("o placar do Matific foi consultado com a Matemática "
                             "fora do plano")
    monkeypatch.setattr(aovivo, "placar_matific", _explode)


@pytest.mark.parametrize("quem", ["gestao", "professor"])
def test_placar_ao_vivo_recusa_403_antes_da_chamada_externa(
        db, sem_matematica, cliente, monkeypatch, quem):
    escola, _ = sem_matematica
    _placar_nao_pode_ser_chamado(monkeypatch)
    c = cliente if quem == "gestao" else _login(EMAIL_PROF)
    r = c.get(f"{API}/escolas/{escola.id}/sync/matific/placar-ao-vivo?periodo=semana")
    assert r.status_code == 403, r.text
    assert "plano" in r.json()["detail"].lower()


def test_placar_ao_vivo_com_o_modulo_ligado_segue_igual(db, tudo_ligado, cliente,
                                                        monkeypatch):
    escola, aluno = tudo_ligado
    from app.sync import aovivo
    monkeypatch.setattr(aovivo, "placar_matific",
                        lambda db_, eid, **kw: {"itens": [{"aluno_id": aluno.id,
                                                            "estrelas": 63}]})
    r = cliente.get(f"{API}/escolas/{escola.id}/sync/matific/placar-ao-vivo?periodo=semana")
    assert r.status_code == 200, r.text
    assert r.json()["itens"][0]["estrelas"] == 63


def test_placar_ao_vivo_tem_a_trava_no_decorador_e_exigir_modulo_falso_saiu():
    rota = next(rt for rt in app.routes if isinstance(rt, APIRoute)
                and rt.path.endswith("/sync/matific/placar-ao-vivo"))

    def _nomes(dep, acc):
        for d in dep.dependencies:
            acc.add(getattr(d.call, "__qualname__", repr(d.call)))
            _nomes(d, acc)
        return acc
    assert any("exigir_modulo_da_escola" in n for n in _nomes(rota.dependant, set()))
    # A dependência por usuário que se dizia "aplicada no registro do router" e não
    # estava em rota nenhuma não existe mais (docstring falsa).
    assert not hasattr(deps, "exigir_modulo")


# --- Evolução, linha do tempo e espelho ---------------------------------------

def test_evolucao_sem_matematica_tira_a_serie_e_o_resumo_do_matific(
        db, sem_matematica, cliente):
    escola, aluno = sem_matematica
    r = cliente.get(f"{API}/escolas/{escola.id}/alunos/{aluno.id}/evolucao?dias=366")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["linha_do_tempo"]["matific"] == []          # a chave fica, vazia
    assert corpo["linha_do_tempo"]["elefante"][0]["livros_unicos"] == 4
    indicadores = {i["indicador"] for i in corpo["resumo"]["indicadores"]}
    assert not indicadores & {"atividades", "estrelas", "pontuacao_media"}
    assert "livros_unicos" in indicadores


def test_evolucao_do_professor_tambem_sai_sem_matific(db, sem_matematica):
    escola, aluno = sem_matematica
    prof = _login(EMAIL_PROF)
    r = prof.get(f"{API}/escolas/{escola.id}/alunos/{aluno.id}/evolucao?dias=366")
    assert r.status_code == 200, r.text
    assert r.json()["linha_do_tempo"]["matific"] == []


def test_evolucao_com_tudo_ligado_segue_igual(db, tudo_ligado, cliente):
    escola, aluno = tudo_ligado
    r = cliente.get(f"{API}/escolas/{escola.id}/alunos/{aluno.id}/evolucao?dias=366")
    assert r.status_code == 200, r.text
    assert r.json()["linha_do_tempo"]["matific"][0]["estrelas"] == 63
    indicadores = {i["indicador"] for i in r.json()["resumo"]["indicadores"]}
    assert {"atividades", "estrelas", "livros_unicos"} <= indicadores


def test_ranking_de_evolucao_omite_ganhos_de_matematica_fora_do_plano(sem_matematica, cliente):
    escola, aluno = sem_matematica
    resposta = cliente.get(f"{API}/escolas/{escola.id}/ranking-evolucao?dias=30")
    assert resposta.status_code == 200, resposta.text
    item = next(i for i in resposta.json() if i["aluno_id"] == aluno.id)
    assert set(item["ganhos"]) == {"livros", "tempo_leitura_min", "acertos", "pontos_dificuldade"}
    assert item["dimensoes"]["matematica"]["contratada"] is False


def test_linha_do_tempo_sem_matematica(db, sem_matematica, cliente):
    escola, aluno = sem_matematica
    base = f"{API}/escolas/{escola.id}/alunos/{aluno.id}/linha-do-tempo"
    r = cliente.get(f"{base}?plataforma=matific")
    assert r.status_code == 403, r.text
    assert "plano" in r.json()["detail"].lower()
    todos = cliente.get(base)
    assert todos.status_code == 200, todos.text
    assert [i["plataforma"] for i in todos.json()["itens"]] == ["elefante"]
    assert cliente.get(f"{base}?plataforma=elefante").status_code == 200


def test_linha_do_tempo_com_tudo_ligado_segue_igual(db, tudo_ligado, cliente):
    escola, aluno = tudo_ligado
    base = f"{API}/escolas/{escola.id}/alunos/{aluno.id}/linha-do-tempo"
    assert {i["plataforma"] for i in cliente.get(base).json()["itens"]} == {
        "matific", "elefante"}
    r = cliente.get(f"{base}?plataforma=matific")
    assert r.status_code == 200 and r.json()["itens"][0]["plataforma"] == "matific"


def test_espelho_sem_matematica_nao_conta_o_matific(db, sem_matematica, cliente):
    escola, aluno = sem_matematica
    r = cliente.get(f"{API}/escolas/{escola.id}/alunos/{aluno.id}/espelho")
    assert r.status_code == 200, r.text
    espelho = r.json()["espelho"]
    assert espelho["por_plataforma"] == {"elefante": 1}
    assert espelho["total_eventos"] == 1
    assert espelho["tempo_total_segundos"] == 300
    assert "atividade" not in espelho["por_tipo"]


def test_espelho_com_tudo_ligado_conta_as_duas(db, tudo_ligado, cliente):
    escola, aluno = tudo_ligado
    espelho = cliente.get(
        f"{API}/escolas/{escola.id}/alunos/{aluno.id}/espelho").json()["espelho"]
    assert espelho["por_plataforma"] == {"elefante": 1, "matific": 1}
    assert espelho["tempo_total_segundos"] == 900


# --- Perfil (autenticado e público) e telão -----------------------------------

def test_perfil_sem_matematica_anula_a_nota_e_tira_o_passo_a_passo(
        db, sem_matematica, cliente):
    escola, aluno = sem_matematica
    scoring.recalcular_escola(db, escola.id)
    r = cliente.get(f"{API}/escolas/{escola.id}/alunos/{aluno.id}/perfil")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["nota_matific"] is None                  # mesma regra do ranking
    assert corpo["nota_elefante"] is not None
    assert "matific" not in corpo["detalhes"]
    assert "elefante" in corpo["detalhes"]
    assert not {"max_atividades", "max_estrelas", "max_media"} & set(
        corpo["detalhes"].get("referencias", {}))
    # O motor ainda grava a data do snapshot do Matific na dimensão não
    # contratada, e o `geral.dimensoes_com_dados` cita o Matific: não saem.
    _perfil_sem_nada_do_matific(corpo)
    # O professor (passo a passo liberado) recebe o mesmo recorte.
    prof = _login(EMAIL_PROF).get(f"{API}/escolas/{escola.id}/alunos/{aluno.id}/perfil")
    assert prof.status_code == 200, prof.text
    assert prof.json()["nota_matific"] is None
    assert "matific" not in prof.json()["detalhes"]
    _perfil_sem_nada_do_matific(prof.json())


def test_perfil_com_tudo_ligado_segue_igual(db, tudo_ligado, cliente):
    escola, aluno = tudo_ligado
    scoring.recalcular_escola(db, escola.id)
    corpo = cliente.get(f"{API}/escolas/{escola.id}/alunos/{aluno.id}/perfil").json()
    assert corpo["nota_matific"] > 0
    assert "matific" in corpo["detalhes"]
    mat = corpo["detalhes"]["dimensoes"]["matematica"]
    assert mat["contratada"] is True and mat["nota"] is not None
    assert mat["dados"]["estrelas"] == 63 and mat["snapshot_em"] is not None
    assert corpo["detalhes"]["geral"]["dimensoes_com_dados"] == ["elefante", "matific"]
    assert corpo["detalhes"]["adocao"]["contratadas"] == ["leitura", "matematica"]


# Chaves que só existem com dado BRUTO do Matific: os indicadores da criança
# (atividades/estrelas/média) e as referências / saturação deles.
_CHAVES_DO_MATIFIC = {"atividades", "estrelas", "media", "pontuacao_media",
                      "max_atividades", "max_estrelas", "max_media"}


def _chaves(obj) -> set:
    if isinstance(obj, dict):
        return set(obj) | {c for valor in obj.values() for c in _chaves(valor)}
    if isinstance(obj, list):
        return {c for valor in obj for c in _chaves(valor)}
    return set()


def _perfil_sem_nada_do_matific(corpo: dict) -> None:
    """Nenhum ponto do perfil traz nota, posição, dado bruto ou data do Matific;
    a Leitura (contratada) segue inteira."""
    assert corpo["nota_matific"] is None
    det = corpo["detalhes"]
    assert "matific" not in det
    assert not _CHAVES_DO_MATIFIC & _chaves(det), _CHAVES_DO_MATIFIC & _chaves(det)
    mat = det["dimensoes"]["matematica"]
    assert mat["nota"] is None and mat["posicao"] is None and mat["n_aferidos"] == 0
    assert mat["dados"] == {} and mat["snapshot_em"] is None
    assert mat["aferido"] is False and mat["contratada"] is False
    assert det["adocao"]["contratadas"] == ["leitura"]
    assert det["adocao"]["com_dados"] == ["leitura"] and det["adocao"]["pct"] == 100.0
    assert det["geral"]["dimensoes_com_dados"] == ["elefante"]
    leitura = det["dimensoes"]["leitura"]
    assert leitura["contratada"] is True and leitura["nota"] is not None
    assert leitura["dados"]["livros_unicos"] == 4 and leitura["snapshot_em"] is not None


def test_perfil_com_nota_anterior_ao_contrato_nao_traz_o_matific(
        db, escola_completa, cliente):
    """Nota calculada com a Matemática no plano e o módulo desligado SEM
    recálculo (o recálculo da escola falhou em ``aplicar_contrato``): o perfil
    olha o contrato de agora, não o da nota gravada."""
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    rede = _rede_com(db, escola, None)
    _dados_das_duas(db, escola, aluno)
    _professor_da_turma(db, escola, escola_completa["turma"])
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    gravada = db.query(Nota).filter_by(aluno_id=aluno.id).one()
    assert gravada.detalhes["dimensoes"]["matematica"]["dados"]["estrelas"] == 63
    db.query(ModuloRede).filter_by(rede_id=rede.id, modulo="matematica").update(
        {"ativo": False})
    db.commit()
    for c in (cliente, _login(EMAIL_PROF)):
        r = c.get(f"{API}/escolas/{escola.id}/alunos/{aluno.id}/perfil")
        assert r.status_code == 200, r.text
        _perfil_sem_nada_do_matific(r.json())
    # Só a resposta é filtrada: a Nota gravada não muda.
    db.expire_all()
    gravada = db.get(Nota, gravada.id)
    assert gravada.detalhes["dimensoes"]["matematica"]["dados"]["estrelas"] == 63


def test_perfil_ao_vincular_a_escola_a_rede_sem_matematica_pela_api(
        db, tudo_ligado, cliente, cliente_global):
    """O fluxo do revisor, pela API: escola avulsa já com Nota (tudo ligado); o
    Admin Global cria a rede só com Leitura e DEPOIS vincula a escola."""
    escola, aluno = tudo_ligado
    scoring.recalcular_escola(db, escola.id)
    r = cliente_global.post(f"{API}/redes", json={"nome": "Rede Ficticia Sem Mat"})
    assert r.status_code == 201, r.text
    rede_id = r.json()["id"]
    r = cliente_global.put(f"{API}/redes/{rede_id}/modulos",
                           json={"leitura": True, "matematica": False})
    assert r.status_code == 200, r.text
    r = cliente_global.put(f"{API}/redes/{rede_id}/escolas",
                           json={"escola_ids": [escola.id]})
    assert r.status_code == 200, r.text
    for c in (cliente, _login(EMAIL_PROF)):
        r = c.get(f"{API}/escolas/{escola.id}/alunos/{aluno.id}/perfil")
        assert r.status_code == 200, r.text
        _perfil_sem_nada_do_matific(r.json())


def test_perfil_com_nota_anterior_sem_leitura_neutraliza_a_dimensao_leitura(
        db, escola_completa, cliente):
    """O mesmo recorte com o outro módulo fora: a Leitura sai neutralizada e a
    Matemática fica inteira."""
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    rede = _rede_com(db, escola, None)
    _dados_das_duas(db, escola, aluno)
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    db.query(ModuloRede).filter_by(rede_id=rede.id, modulo="leitura").update(
        {"ativo": False})
    db.commit()
    corpo = cliente.get(f"{API}/escolas/{escola.id}/alunos/{aluno.id}/perfil").json()
    det = corpo["detalhes"]
    assert corpo["nota_elefante"] is None and "elefante" not in det
    leitura = det["dimensoes"]["leitura"]
    assert leitura["nota"] is None and leitura["dados"] == {}
    assert leitura["snapshot_em"] is None and leitura["contratada"] is False
    assert det["adocao"]["contratadas"] == ["matematica"]
    assert det["geral"]["dimensoes_com_dados"] == ["matific"]
    assert det["dimensoes"]["matematica"]["dados"]["estrelas"] == 63


def test_detalhes_no_plano_tudo_contratado_ou_sem_detalhes_fica_intacto():
    from app.routers.academico import _detalhes_no_plano
    detalhes = {"dimensoes": {"matematica": {"nota": 1.0}}, "geral": {}}
    assert _detalhes_no_plano(detalhes, set()) is detalhes
    assert _detalhes_no_plano({}, {"matific"}) == {}
    # Nota de antes desta arquitetura (sem `dimensoes`/`adocao`): não quebra.
    assert _detalhes_no_plano({"modo_normalizacao": "auto", "matific": {}},
                              {"matific"}) == {"modo_normalizacao": "auto"}


def _ligar_painel(cliente, escola) -> str:
    r = cliente.put(f"{API}/escolas/{escola.id}/painel-publico",
                    json={"ativo": True, "anonimizar": True})
    assert r.status_code == 200, r.text
    return r.json()["url"].rsplit("/p/", 1)[1]


def test_painel_e_perfil_publicos_sem_matematica(db, sem_matematica, cliente):
    escola, aluno = sem_matematica
    scoring.recalcular_escola(db, escola.id)
    token = _ligar_painel(cliente, escola)
    anon = TestClient(app)
    painel = anon.get(f"{API}/publico/{token}/painel")
    assert painel.status_code == 200, painel.text
    estat = painel.json()["estatisticas"]
    assert estat["estrelas"] is None and estat["atividades"] is None
    assert estat["livros"] == 4
    pub = anon.get(f"{API}/publico/{token}/alunos/{aluno.id}")
    assert pub.status_code == 200, pub.text
    assert pub.json()["nota_matific"] is None


def test_painel_publico_com_tudo_ligado_segue_igual(db, tudo_ligado, cliente):
    escola, aluno = tudo_ligado
    scoring.recalcular_escola(db, escola.id)
    token = _ligar_painel(cliente, escola)
    estat = TestClient(app).get(f"{API}/publico/{token}/painel").json()["estatisticas"]
    assert estat["estrelas"] == 63 and estat["atividades"] == 21 and estat["livros"] == 4


# --- Ranking de leitura por turno (a rota exige a Leitura e levava as duas notas)

def _item_do_turno(db, escola, aluno, c) -> dict:
    escola_turma = db.query(Turma).filter_by(escola_id=escola.id).first()
    escola_turma.turno = "manha"
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    r = c.get(f"{API}/escolas/{escola.id}/ranking/leitura/turnos")
    assert r.status_code == 200, r.text
    itens = [a for t in r.json() for a in t["alunos"] if a["aluno_id"] == aluno.id]
    assert len(itens) == 1, r.json()
    return itens[0]


@pytest.mark.parametrize("quem", ["gestao", "professor"])
def test_ranking_de_leitura_por_turno_sem_matematica_anula_a_nota_do_matific(
        db, sem_matematica, cliente, quem):
    escola, aluno = sem_matematica
    item = _item_do_turno(db, escola, aluno,
                          cliente if quem == "gestao" else _login(EMAIL_PROF))
    assert item["nota_matific"] is None                    # mesma regra de _ranking
    assert item["nota_elefante"] is not None and item["nota"] == item["nota_elefante"]


def test_ranking_de_leitura_por_turno_com_tudo_ligado_segue_igual(
        db, tudo_ligado, cliente):
    escola, aluno = tudo_ligado
    item = _item_do_turno(db, escola, aluno, cliente)
    assert item["nota_matific"] is not None and item["nota_matific"] > 0


def test_destaques_do_telao_perdem_os_ganhos_do_modulo_fora():
    from app.routers import publico
    destaques = {
        "dia": {"nome": "Ana B.", "ganhos": {"atividades": 5, "estrelas": 9, "livros": 2,
                                             "tempo_leitura_min": 30}},
        "semana": None,
        "mes": {"nome": "Ana B.", "ganhos": {"estrelas": 1}},
    }
    saida = publico._destaques_no_plano(destaques, {"matific"})
    assert saida["dia"]["ganhos"] == {"livros": 2, "tempo_leitura_min": 30}
    assert saida["dia"]["nome"] == "Ana B."
    assert saida["semana"] is None and saida["mes"]["ganhos"] == {}
    assert publico._destaques_no_plano(destaques, set()) is destaques   # tudo ligado


# --- Coleta (manual, agendada, fila) e importação ------------------------------

def _credenciais(db, escola, *plataformas):
    from app.sync import vault
    from app.sync.interfaces import Credenciais
    for plat in plataformas:
        vault.salvar_credencial(db, escola.id, plat,
                                Credenciais(usuario="ficticio", senha="ficticia"))
    db.commit()


def test_sincronizar_agora_recusa_o_matific_e_coleta_so_o_contratado(
        db, sem_matematica, cliente, monkeypatch):
    escola, _ = sem_matematica
    from app.sync import service
    _credenciais(db, escola, "matific", "elefante")
    disparos = []
    monkeypatch.setattr(service, "disparar_em_thread", lambda eid: disparos.append(eid))
    r = cliente.post(f"{API}/escolas/{escola.id}/sync/agora?plataforma=matific")
    assert r.status_code == 403, r.text
    assert "plano" in r.json()["detail"].lower()
    assert disparos == []
    assert db.query(SincronizacaoExecucao).count() == 0
    # "Sincronizar agora" de TODAS: o Matific fica de fora, o Elefante segue.
    r = cliente.post(f"{API}/escolas/{escola.id}/sync/agora")
    assert r.status_code == 200, r.text
    assert [e["plataforma"] for e in r.json()] == ["elefante"]
    assert len(disparos) == 1


def test_sincronizar_agora_com_tudo_ligado_coleta_o_matific(db, tudo_ligado, cliente,
                                                           monkeypatch):
    escola, _ = tudo_ligado
    from app.sync import service
    _credenciais(db, escola, "matific")
    monkeypatch.setattr(service, "disparar_em_thread", lambda eid: None)
    r = cliente.post(f"{API}/escolas/{escola.id}/sync/agora?plataforma=matific")
    assert r.status_code == 200, r.text
    assert r.json()[0]["plataforma"] == "matific"


def test_agendador_nao_enfileira_o_matific_e_avanca_a_agenda(db, sem_matematica):
    escola, _ = sem_matematica
    from app.sync import service
    vencida = service._agora() - timedelta(hours=1)   # há pouco: atraso de dias só recalcula
    for plat in ("matific", "elefante"):
        db.add(SincronizacaoConfig(escola_id=escola.id, plataforma=plat, ativo=True,
                                   cadencia="diaria", hora_local="03:00",
                                   proxima_execucao=vencida))
    db.commit()
    assert service.enfileirar_agendados(db) == 1          # só o Elefante
    execs = db.query(SincronizacaoExecucao).all()
    assert [e.plataforma for e in execs] == ["elefante"]
    db.expire_all()
    cfg_m = db.query(SincronizacaoConfig).filter_by(plataforma="matific").one()
    assert cfg_m.proxima_execucao > vencida  # avançou: não vence de novo
    assert service.enfileirar_agendados(db) == 0


def test_execucao_ja_na_fila_e_cancelada_sem_coletar(db, sem_matematica, monkeypatch):
    escola, _ = sem_matematica
    from app.sync import service

    def _explode(*_a, **_k):
        raise AssertionError("coletou o Matific fora do plano")
    monkeypatch.setattr(service, "_coletar", _explode)
    ex = SincronizacaoExecucao(escola_id=escola.id, plataforma="matific",
                               origem="scheduler", status="fila", tentativa=2,
                               parametros={})
    db.add(ex)
    db.commit()
    service.executar(db, ex)
    db.expire_all()
    ex = db.get(SincronizacaoExecucao, ex.id)
    assert ex.status == "cancelada"
    assert "plano" in (ex.erro_resumo or "")
    assert db.query(SincronizacaoAlerta).count() == 0       # não é falha: sem alerta


def _agenda_velha(db, escola, plataforma):
    """Agenda diária ativa há 30 dias, sem nenhuma coleta: pela regra única de
    obsolescência, estaria desatualizada."""
    cfg = SincronizacaoConfig(escola_id=escola.id, plataforma=plataforma, ativo=True,
                              cadencia="diaria", hora_local="03:00")
    db.add(cfg)
    db.flush()
    cfg.updated_at = _agora() - timedelta(days=30)
    db.commit()
    return cfg


def test_alerta_desatualizada_nao_vale_para_modulo_fora(db, sem_matematica):
    """Sem coleta (o módulo saiu do plano), a agenda do Matific não 'envelhece'."""
    escola, _ = sem_matematica
    from app.sync import service
    cfg = _agenda_velha(db, escola, "matific")
    service.abrir_alerta(db, escola.id, "matific", "desatualizada", "velho",
                         severidade="critico")
    db.commit()
    assert service.atualizar_alerta_desatualizada(db, cfg) is False
    db.commit()
    assert db.query(SincronizacaoAlerta).filter_by(
        plataforma="matific", tipo="desatualizada", resolvido=False).count() == 0
    assert escola.id not in service.escolas_desatualizadas(db)


def test_alerta_desatualizada_com_tudo_ligado_segue_igual(db, tudo_ligado):
    escola, _ = tudo_ligado
    from app.sync import service
    cfg = _agenda_velha(db, escola, "matific")
    assert service.atualizar_alerta_desatualizada(db, cfg) is True
    assert escola.id in service.escolas_desatualizadas(db)


TEXTO_MATIFIC = """Relatório Matific — Turma 3º Ano A
Nome do aluno\tAtividades finalizadas\tPontuação média\tEstrelas
Ana Beatriz Souza\t42\t85,5\t120
"""


def test_importacao_recusa_o_matific_fora_do_plano(db, sem_matematica, cliente):
    escola, aluno = sem_matematica
    url = f"{API}/escolas/{escola.id}/importacoes"
    # Escolhido no formulário: 403 antes de ler o arquivo.
    r = cliente.post(f"{url}/analisar", data={"texto": TEXTO_MATIFIC,
                                              "plataforma": "matific"})
    assert r.status_code == 403, r.text
    # Detectado pelo parser: 403 depois da análise, antes de casar/arquivar.
    r = cliente.post(f"{url}/analisar", data={"texto": TEXTO_MATIFIC})
    assert r.status_code == 403, r.text
    antes = db.query(SnapshotMatific).count()
    r = cliente.post(f"{url}/confirmar", json={
        "plataforma": "matific", "formato": "resumo", "tipo": "texto",
        "linhas": [{"nome": aluno.nome,
                    "dados": {"atividades": 42, "pontuacao_media": 85.5, "estrelas": 120},
                    "aluno_id": aluno.id}]})
    assert r.status_code == 403, r.text
    db.expire_all()
    assert db.query(SnapshotMatific).count() == antes
    assert db.query(Importacao).filter_by(plataforma="matific").count() == 0


def test_importacao_com_tudo_ligado_segue_igual(db, tudo_ligado, cliente):
    escola, _ = tudo_ligado
    r = cliente.post(f"{API}/escolas/{escola.id}/importacoes/analisar",
                     data={"texto": TEXTO_MATIFIC})
    assert r.status_code == 200, r.text
    assert r.json()["plataforma"] == "matific"


def test_helpers_de_plataforma_do_catalogo():
    assert svc_modulos.plataformas_fora_do_plano({"leitura"}) == {"matific"}
    assert svc_modulos.plataformas_fora_do_plano(set(svc_modulos.TODOS)) == set()
    assert svc_modulos.plataforma_contratada({"leitura"}, "elefante")
    assert not svc_modulos.plataforma_contratada({"leitura"}, "matific")
    # Plataforma fora do catálogo (fallback manual) não tem contrato a barrar.
    assert svc_modulos.plataforma_contratada(set(), "manual")
    svc_modulos.exigir_plataforma(set(), None)
