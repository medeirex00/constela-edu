"""Congelar níveis (script) × PATCH /livros do Admin Global, num PostgreSQL REAL
(REV2-PLAT-1, sobre G_SCRIPTS-7).

O ``UPDATE`` condicional do ``congelar()`` confere o nível do livro na HORA do
comando — mas o PATCH não pedia a trava da escola (4711) e o EXISTS não bloqueia a
linha do livro. Na janela entre os UPDATEs e o commit do script (todos os lotes,
todos os níveis e a auditoria de uma escola), o PATCH corrigia o livro de K para M e
respondia que a leitura sem congelamento "segue o nível atual do livro"; ao comitar, o
script a deixava congelada no VELHO (K).

Agora o PATCH pede a mesma trava da escola antes de ler o livro: as duas ordens viram
uma fila, e o que cada lado diz é o que fica gravado.

  * script primeiro: o PATCH espera o commit, encontra a leitura já congelada em K
    (o que ela valia quando foi congelada) e não a conta como "sem congelamento";
  * PATCH primeiro: o script espera o commit do PATCH, o UPDATE condicional vê o livro
    em M e deixa a leitura nula (seguindo M), como o PATCH respondeu.

Local e descartável (``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test').
Dados fictícios.
"""
import importlib
import os
import threading

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base, get_db
from app.main import app
from app.models import Leitura, Livro, LogAuditoria, Usuario
from app.routers import plataformas
from app.schemas import LivroUpdate
from scripts import vincular_livros_catalogo as script

URL = os.environ.get("TEST_DATABASE_URL_PG", "")
pytestmark = [pytest.mark.postgres,
              pytest.mark.skipif(not URL, reason="defina TEST_DATABASE_URL_PG"),
              pytest.mark.skipif(bool(URL) and "test" not in (make_url(URL).database or ""),
                                 reason="o nome do banco PG de teste precisa conter 'test'")]

# Quanto o teste espera para concluir que o outro lado está PARADO na trava. Sem a
# trava, o lado de lá termina em milissegundos; com ela, só anda depois do "soltar".
ESPERA_NA_TRAVA_S = 3
TETO_DA_CENA_S = 30


@pytest.fixture()
def db():
    importlib.import_module("app.quest.models")   # registra o schema completo
    engine = create_engine(URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    sessao = TestSession()

    def _get_db():
        outra = TestSession()
        try:
            yield outra
        finally:
            outra.close()

    app.dependency_overrides[get_db] = _get_db
    yield sessao
    sessao.close()
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _cena(db, escola_completa) -> dict:
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    glob = Usuario(escola_id=escola.id, nome="Admin Global Fictício",
                   email="global-congelar@aud2-plat.local", senha_hash="x",
                   cargo="admin", is_global=True)
    livro = Livro(escola_id=escola.id, titulo="Livro Fictício da Fila",
                  nivel_codigo="K", origem_nivel="legado")
    db.add_all([glob, livro])
    db.flush()
    # Leitura anterior ao congelamento (nível nulo): vale o nível atual do livro.
    leitura = Leitura(escola_id=escola.id, aluno_id=ana.id, livro_id=livro.id)
    db.add(leitura)
    db.commit()
    return {"global": glob.id, "livro": livro.id, "leitura": leitura.id,
            "escola": escola.id, "nome": escola.nome, "engine": db.get_bind()}


def _patch(ids: dict, resultado: dict, erros: list) -> None:
    """O que a rota PATCH /livros faz, numa sessão própria (a da requisição)."""
    try:
        with Session(ids["engine"]) as api:
            resultado["out"] = plataformas.atualizar_livro(
                livro_id=ids["livro"],
                dados=LivroUpdate(nivel_codigo="M", motivo="nível conferido na plataforma"),
                usuario=api.get(Usuario, ids["global"]), escola_id=ids["escola"], db=api)
    except Exception as erro:  # noqa: BLE001
        erros.append(erro)


def _estado_final(ids: dict) -> tuple[str | None, str, str]:
    with Session(ids["engine"]) as v:
        congelado = v.get(Leitura, ids["leitura"]).nivel_codigo
        efetivo = v.execute(
            select(func.coalesce(Leitura.nivel_codigo, Livro.nivel_codigo))
            .join(Livro, Livro.id == Leitura.livro_id)
            .where(Leitura.id == ids["leitura"])).scalar_one()
        nivel_livro = v.get(Livro, ids["livro"]).nivel_codigo
    return congelado, efetivo, nivel_livro


def test_patch_que_chega_durante_a_gravacao_espera_o_commit_do_script(
        db, escola_completa, monkeypatch):
    """A cena da revisão: o script já gravou e ainda não comitou quando o PATCH chega."""
    ids = _cena(db, escola_completa)

    # Pausa o script DEPOIS dos UPDATEs e ANTES do commit (no registrar da auditoria,
    # que congelar() chama entre o último UPDATE e o db.commit()).
    entrou, soltar = threading.Event(), threading.Event()
    real = script.registrar

    def _lento(sessao, acao, *a, **k):
        r = real(sessao, acao, *a, **k)
        if threading.current_thread().name == "SCRIPT":
            entrou.set()
            assert soltar.wait(TETO_DA_CENA_S)
        return r

    monkeypatch.setattr(script, "registrar", _lento)
    res_script, erros_script = {}, []

    def _script():
        try:
            with Session(ids["engine"]) as s:
                relatorio = script.analisar_congelamento(s, ids["escola"], ids["nome"])
                res_script["n"] = script.congelar(s, relatorio)
        except Exception as erro:  # noqa: BLE001
            erros_script.append(erro)

    t_script = threading.Thread(target=_script, name="SCRIPT")
    t_script.start()
    try:
        assert entrou.wait(TETO_DA_CENA_S), erros_script
        resultado, erros = {}, []
        t_patch = threading.Thread(target=_patch, args=(ids, resultado, erros), name="PATCH")
        t_patch.start()
        t_patch.join(ESPERA_NA_TRAVA_S)
        patch_esperou = t_patch.is_alive()
    finally:
        soltar.set()                               # o script segue e comita a escola
        t_script.join(TETO_DA_CENA_S)
    t_patch.join(TETO_DA_CENA_S)
    assert not erros_script and not erros, (erros_script, erros)
    assert res_script["n"] == 1

    out = resultado["out"]
    congelado, efetivo, nivel_livro = _estado_final(ids)
    # A leitura foi congelada em K (o que ela valia) e a correção vale para as próximas.
    assert (congelado, efetivo, nivel_livro) == ("K", "K", "M")
    # O PATCH diz o que ficou gravado: nenhuma leitura "sem congelamento" seguindo M.
    assert out.leituras_sem_nivel_congelado == 0, out.aviso_correcao
    assert "anteriores ao congelamento" not in (out.aviso_correcao or "")
    assert patch_esperou, "o PATCH corrigiu o livro sem esperar o commit do script"


def test_script_que_grava_durante_o_patch_espera_e_deixa_a_leitura_no_nivel_novo(
        db, escola_completa, monkeypatch):
    """A ordem inversa: o PATCH já corrigiu e ainda não comitou quando o script grava.
    O docstring do script promete: a leitura fica nula, seguindo o nível novo."""
    ids = _cena(db, escola_completa)

    # O script analisa ANTES da correção (lê K)...
    sessao_script = Session(ids["engine"])
    relatorio = script.analisar_congelamento(sessao_script, ids["escola"], ids["nome"])
    assert {n: len(v) for n, v in relatorio.por_nivel.items()} == {"K": 1}

    # ...e o PATCH pausa no registrar da auditoria, com a correção feita e sem commit.
    entrou, soltar = threading.Event(), threading.Event()
    real = plataformas.registrar

    def _lento(sessao, acao, *a, **k):
        r = real(sessao, acao, *a, **k)
        if threading.current_thread().name == "PATCH" and acao == "livro.atualizado":
            sessao.flush()                         # a correção já está no banco
            entrou.set()
            assert soltar.wait(TETO_DA_CENA_S)
        return r

    monkeypatch.setattr(plataformas, "registrar", _lento)
    resultado, erros = {}, []
    t_patch = threading.Thread(target=_patch, args=(ids, resultado, erros), name="PATCH")
    t_patch.start()
    res_script, erros_script = {}, []

    def _script():
        try:
            res_script["n"] = script.congelar(sessao_script, relatorio)
        except Exception as erro:  # noqa: BLE001
            erros_script.append(erro)

    t_script = threading.Thread(target=_script, name="SCRIPT")
    try:
        assert entrou.wait(TETO_DA_CENA_S), erros
        t_script.start()
        t_script.join(ESPERA_NA_TRAVA_S)
        script_esperou = t_script.is_alive()
    finally:
        soltar.set()                               # o PATCH segue e comita a correção
        t_patch.join(TETO_DA_CENA_S)
    t_script.join(TETO_DA_CENA_S)
    sessao_script.close()
    assert not erros_script and not erros, (erros_script, erros)

    congelado, efetivo, nivel_livro = _estado_final(ids)
    # A leitura não foi congelada no nível velho: segue o livro corrigido (M)...
    assert (congelado, efetivo, nivel_livro) == (None, "M", "M")
    assert res_script["n"] == 0
    # ...como o PATCH respondeu; o script não gravou nada, então não audita congelamento.
    assert resultado["out"].leituras_sem_nivel_congelado == 1
    with Session(ids["engine"]) as v:
        assert v.execute(select(LogAuditoria).where(
            LogAuditoria.acao == "leitura.nivel_congelado")).first() is None
    assert script_esperou, "o script gravou sem esperar o commit da correção"
