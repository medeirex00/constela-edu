"""S_G_GRUPO-1 — dado legado (matrícula do ano ativo numa turma de OUTRO ano): o cartão da
escola no Panorama da Rede menos a soma das turmas da Visão da Escola não pode devolver à
Secretaria os livros, o tempo, as atividades e as estrelas dessa criança.

O estado vem de antes das travas de escrita (um "Transferir" para uma turma do ano
passado, ou a correção do ano de uma turma com alunos): a matrícula é do ano ativo, a
turma não. Nenhuma porta o grava mais, por isso ele é plantado direto no banco (como em
``test_matricula_turma_outro_ano._plantar_legado``).

O defeito: o cartão da rede contava a matrícula do ano ativo em QUALQUER turma (e as turmas
premiáveis vinham de todos os anos), enquanto a Visão da Escola (``evolucao.resumo_escola``)
lista só as turmas do ano ativo. A diferença entre os dois era a criança. Agora o cartão
conta, como a Visão da Escola, só quem está numa turma do ano ativo da escola.

E o diagnóstico só de leitura (``scripts.diagnostico_matricula_turma_outro_ano``) encontra
esse estado, para o dono saber se a produção o tem. Escolas e crianças FICTÍCIAS.
"""
from __future__ import annotations

import sys
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_senha
from app.main import app
from app.models import (Aluno, Escola, Importacao, LogAuditoria, Matricula, Rede,
                        SnapshotElefante, SnapshotMatific, Turma, Usuario)
from app.models.base import agora
from app.services import elegibilidade, rede, scoring
from tests._ano_letivo import escola_no_ano_de_hoje  # noqa: F401 — fixture

API = "/api/v1"
SENHA = "s3nh4"
EMAIL_SEC = "secretaria@legado-inventado.local"
# Os números da criança "canário": nenhum outro aluno os tem.
CANARIO = {"livros": 37, "tempo": 1913, "atividades": 11, "estrelas": 47}


def _login(email: str) -> TestClient:
    c = TestClient(app)
    r = c.post(f"{API}/auth/login", data={"username": email, "password": SENHA})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _retratos(db, escola_id: int, aluno_id: int, imp: Importacao, *, livros: int,
              tempo: int, atividades: int, estrelas: int) -> None:
    ontem = agora() - timedelta(days=1)
    db.add(SnapshotElefante(escola_id=escola_id, aluno_id=aluno_id, importacao_id=imp.id,
                            data_referencia=ontem, livros_unicos=livros,
                            tempo_leitura_min=tempo, questoes_tentativas=5,
                            questoes_acertos=4, livros_por_nivel={"D": livros}))
    db.add(SnapshotMatific(escola_id=escola_id, aluno_id=aluno_id, importacao_id=imp.id,
                           data_referencia=ontem, atividades=atividades, estrelas=estrelas,
                           pontuacao_media=3.0))


def _cenario(db, escola_completa, *, legado: bool, turma_antiga_status: str = "ativa"):
    """A turma do ano ativo com 8 crianças (as 3 da fixture + 5) e a criança canário,
    cuja matrícula do ano ativo fica na turma do ano passado (``legado``) ou na do ano."""
    escola = escola_completa["escola"]
    ano = escola.ano_letivo_ativo
    turma = escola_completa["turma"]
    antiga = Turma(escola_id=escola.id, nome="3º Ano Z", ano_escolar="3º Ano",
                   ano_letivo=ano - 1, status=turma_antiga_status)
    db.add(antiga)
    db.flush()
    alunos = list(escola_completa["alunos"])
    for i in range(5):
        a = Aluno(escola_id=escola.id, nome=f"Crianca Inventada {i}")
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id,
                         ano_letivo=ano))
        alunos.append(a)
    canario = Aluno(escola_id=escola.id, nome="Crianca Inventada Canario")
    db.add(canario)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=canario.id,
                     turma_id=antiga.id if legado else turma.id, ano_letivo=ano))
    imp = Importacao(escola_id=escola.id, plataforma="elefante", tipo="seed")
    db.add(imp)
    db.flush()
    for a in alunos:
        _retratos(db, escola.id, a.id, imp, livros=10, tempo=100, atividades=4, estrelas=12)
    _retratos(db, escola.id, canario.id, imp, livros=CANARIO["livros"],
              tempo=CANARIO["tempo"], atividades=CANARIO["atividades"],
              estrelas=CANARIO["estrelas"])
    rede_ = Rede(nome="Rede Inventada Legado", status="ativa")
    db.add(rede_)
    db.flush()
    escola.rede_id = rede_.id
    db.add(Usuario(escola_id=None, nome="Secretaria Inventada", email=EMAIL_SEC,
                   senha_hash=hash_senha(SENHA), cargo="coordenador", rede_id=rede_.id))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    db.commit()
    return escola, rede_, canario, antiga


def _cartao_e_turmas(sec: TestClient, escola_id: int, rede_id: int):
    painel = sec.get(f"{API}/redes/{rede_id}/dashboard")
    assert painel.status_code == 200, painel.text
    cartao = next(c for c in painel.json()["escolas"] if c["escola_id"] == escola_id)
    resumo = sec.get(f"{API}/escolas/{escola_id}/resumo-escola")
    assert resumo.status_code == 200, resumo.text
    return cartao, resumo.json()["turmas"]


def _diferenca(cartao: dict, turmas: list[dict]) -> dict:
    """Cartão − Σ turmas, campo a campo (a conta que a Secretaria pode fazer)."""
    def soma(chave):
        return sum((t["indicadores"].get(chave) or 0) for t in turmas)
    return {
        "livros": cartao["livros"] - soma("livros_unicos"),
        "tempo": cartao["tempo_leitura_min"] - soma("tempo_leitura_min"),
        "atividades": cartao["atividades"] - soma("atividades"),
        "estrelas": cartao["estrelas"] - soma("estrelas"),
        "alunos": cartao["total_alunos"] - sum(t.get("total_alunos") or 0 for t in turmas),
    }


def test_controle_sem_legado_o_cartao_e_a_soma_das_turmas(db, escola_completa):
    escola, rede_, _canario, _antiga = _cenario(db, escola_completa, legado=False)
    cartao, turmas = _cartao_e_turmas(_login(EMAIL_SEC), escola.id, rede_.id)
    assert cartao["total_alunos"] == 9
    assert _diferenca(cartao, turmas) == dict.fromkeys(
        ("livros", "tempo", "atividades", "estrelas", "alunos"), 0)


@pytest.mark.parametrize("status_antiga", ["ativa", "arquivada"])
def test_legado_cartao_menos_turmas_nao_devolve_a_crianca(db, escola_completa,
                                                          status_antiga):
    escola, rede_, _canario, _antiga = _cenario(db, escola_completa, legado=True,
                                                turma_antiga_status=status_antiga)
    cartao, turmas = _cartao_e_turmas(_login(EMAIL_SEC), escola.id, rede_.id)
    diferenca = _diferenca(cartao, turmas)
    # Antes: {"livros": 37, "tempo": 1913, "atividades": 11, "estrelas": 47 (ou as que
    # contam), "alunos": 1} — os números da criança canário.
    assert diferenca == dict.fromkeys(
        ("livros", "tempo", "atividades", "estrelas", "alunos"), 0), diferenca
    # A média do cartão é a da turma, com as mesmas crianças (antes, 9×média do cartão −
    # 8×média da turma dava a nota da criança).
    (turma,) = turmas
    assert cartao["alunos_com_nota_elefante"] == turma["n_leitura"] == 8
    assert cartao["media_elefante"] == pytest.approx(turma["media_leitura"], abs=0.06)
    assert cartao["alunos_premiaveis"] == 8


def test_legado_ranking_da_rede_conta_so_quem_esta_numa_turma_do_ano(db, escola_completa):
    escola, rede_, _canario, _antiga = _cenario(db, escola_completa, legado=True)
    (cartao,) = [c for c in rede.cartoes_da_rede(db, rede_.id) if c["escola_id"] == escola.id]
    assert cartao["total_alunos"] == 8
    assert cartao["alunos_com_dados"] == 8
    assert cartao["livros_premiaveis"] == 80
    assert cartao["livros_por_matricula"] == 10.0


def test_turmas_premiaveis_da_rede_no_ano_ativo_de_cada_escola(db):
    """Duas escolas da rede em anos diferentes (a virada em andamento): cada uma com as
    turmas do SEU ano ativo."""
    velha = Escola(nome="Escola Inventada Velha", ano_letivo_ativo=2026)
    nova = Escola(nome="Escola Inventada Nova", ano_letivo_ativo=2027)
    db.add_all([velha, nova])
    db.flush()
    turmas = {
        (e.id, ano, rotulo): Turma(escola_id=e.id, nome=f"{rotulo} {ano}", ano_escolar=rotulo,
                                   ano_letivo=ano)
        for e in (velha, nova) for ano in (2026, 2027) for rotulo in ("3º Ano", "1ª Fase")}
    db.add_all(turmas.values())
    db.commit()
    premiaveis = elegibilidade.turmas_premiaveis_da_rede(db, [velha.id, nova.id],
                                                         no_ano_ativo=True)
    assert sorted(premiaveis) == sorted([turmas[(velha.id, 2026, "3º Ano")].id,
                                         turmas[(nova.id, 2027, "3º Ano")].id])
    # O padrão de sempre (todas as turmas premiáveis, de qualquer ano) continua.
    assert len(elegibilidade.turmas_premiaveis_da_rede(db, [velha.id, nova.id])) == 4


# --- O diagnóstico só de leitura -----------------------------------------------------------

class _SessaoSemFechar:
    """O ``main()`` do script fecha a sessão no ``finally``; o teste ainda a usa."""

    def __init__(self, sessao):
        self._sessao = sessao
        self.commits = 0

    def __getattr__(self, nome):
        return getattr(self._sessao, nome)

    def commit(self):
        self.commits += 1

    def close(self):
        pass


def _rodar(monkeypatch, db, *argumentos) -> tuple[int, _SessaoSemFechar]:
    from scripts import diagnostico_matricula_turma_outro_ano as diagnostico

    sessao = _SessaoSemFechar(db)
    monkeypatch.setattr(diagnostico, "SessionLocal", lambda: sessao)
    monkeypatch.setattr(sys, "argv", ["diagnostico_matricula_turma_outro_ano", *argumentos])
    return diagnostico.main(), sessao


def test_diagnostico_acha_a_matricula_do_ano_numa_turma_de_outro_ano(
        db, escola_completa, monkeypatch, capsys):
    escola, _rede, canario, antiga = _cenario(db, escola_completa, legado=True)
    # A correção do ano da turma (antes da trava) deixou rastro no log: o diagnóstico o mostra.
    db.add(LogAuditoria(escola_id=escola.id, acao="turma.atualizada", entidade="turma",
                        entidade_id=antiga.id, detalhes={"ano_letivo": antiga.ano_letivo}))
    db.commit()
    antes = sorted(db.execute(select(Matricula.id, Matricula.turma_id)).all())

    codigo, sessao = _rodar(monkeypatch, db)
    saida = capsys.readouterr().out

    assert codigo == 0
    assert f"Escola {escola.id}" in saida
    assert f"turma {antiga.id} “3º Ano Z” ({antiga.ano_letivo}, ativa)" in saida
    assert "matrículas do ano ativo: 1 (1 de aluno ativo)" in saida
    assert f"ano letivo mudado para {antiga.ano_letivo} em" in saida
    assert "TOTAL: 1 matrícula(s) do ano ativo em turma de outro ano, em 1 escola(s)" in saida
    # Sem --listar, só contagens; com ele, os ids das fichas (nunca o nome da criança).
    assert "alunos (id)" not in saida
    assert canario.nome not in saida
    codigo, _ = _rodar(monkeypatch, db, "--escola", str(escola.id), "--listar")
    saida = capsys.readouterr().out
    assert f"alunos (id): {canario.id}" in saida and canario.nome not in saida
    # Só leitura: nada gravado, nada mudado.
    assert sessao.commits == 0
    assert sorted(db.execute(select(Matricula.id, Matricula.turma_id)).all()) == antes


def test_diagnostico_sem_legado_diz_que_nao_ha_nada(db, escola_completa, monkeypatch,
                                                    capsys):
    _cenario(db, escola_completa, legado=False)
    codigo, _ = _rodar(monkeypatch, db)
    assert codigo == 0
    assert ("TOTAL: nenhuma matrícula do ano ativo em turma de outro ano"
            in capsys.readouterr().out)
