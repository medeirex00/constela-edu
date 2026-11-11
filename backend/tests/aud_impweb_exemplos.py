"""Auditoria (frente da tela de Importações): as respostas REAIS que os testes da tela usam.

A prévia da tela de Importações lê a turma que o backend decidiu para o aluno novo
(``correspondencia.turma_id``/``turma_nova``), trata "turma ambígua" e "turma de outra
etapa" como a turma arquivada, manda "Deixar para a Revisão" como instrução
(``deixar_para_revisao``) e mostra a recusa do mesmo aluno em duas linhas. Os testes da
tela (``apps/web/src/test/Aud*.test.tsx``) usam as respostas gravadas pelos
``test_aud_impweb_*.py`` — /analisar, /turmas e /confirmar da rota real, não mocks
montados à mão — e cada caso confere, do lado do backend, o que o corpo que a tela
passa a mandar faz de verdade.

Para regravar: ``GERAR_FIXTURES_IMPORTACAO=1 python -m pytest tests/test_aud_impweb_*.py``.
Sem a variável, cada teste confere que o exemplo gravado é a resposta de agora.
Dados fictícios.
"""
import json
import os
import pathlib

import pytest
from sqlalchemy import func, select

API = "/api/v1"
DATA = "2026-08-14T12:00:00"
RAIZ = pathlib.Path(__file__).resolve().parents[2]
PASTA = RAIZ / "apps" / "web" / "src" / "test" / "fixtures" / "importacoes" / "previa_da_tela"
GERAR = os.environ.get("GERAR_FIXTURES_IMPORTACAO") == "1"
# O token do arquivo guardado (PDF) é aleatório: não entra na comparação.
VOLATEIS = {"arquivo_token"}


def sem_volateis(valor):
    if isinstance(valor, dict):
        return {k: sem_volateis(v) for k, v in valor.items() if k not in VOLATEIS}
    if isinstance(valor, list):
        return [sem_volateis(v) for v in valor]
    return valor


def _exemplo(nome: str, real) -> None:
    """Grava (com GERAR_FIXTURES_IMPORTACAO=1) ou confere o exemplo da tela."""
    caminho = PASTA / nome
    if GERAR:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(json.dumps(real, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8", newline="\n")
    if not caminho.parent.parent.exists():
        pytest.skip("cópia sem apps/web: o exemplo da tela não está aqui")
    assert caminho.exists(), f"falta {nome}: regrave com GERAR_FIXTURES_IMPORTACAO=1"
    gravado = json.loads(caminho.read_text(encoding="utf-8"))
    assert sem_volateis(gravado) == sem_volateis(real), (
        f"{nome} está defasado: regrave com GERAR_FIXTURES_IMPORTACAO=1")


def _placar(turma, alunos):
    corpo = {"fonte": "matific-placar", "alunos": alunos}
    if turma is not None:
        corpo["turma"] = turma
    return json.dumps(corpo, ensure_ascii=False)


def _uma(turma, nome, uuid):
    return _placar(turma, [{"nome": nome, "uuid": uuid, "estrelas": 5, "atividades": 1}])


def _analise(cliente, eid, texto):
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/analisar", data={"texto": texto})
    assert r.status_code == 200, r.text
    return r.json()


def _turmas(cliente, eid):
    r = cliente.get(f"{API}/escolas/{eid}/turmas")
    assert r.status_code == 200, r.text
    return r.json()


def _post_confirmar(cliente, eid, analise, linhas):
    return cliente.post(f"{API}/escolas/{eid}/importacoes/confirmar", json={
        "plataforma": analise["plataforma"], "formato": analise["formato"],
        "tipo": analise["tipo"], "arquivo_token": analise.get("arquivo_token"),
        "arquivo_nome": analise.get("arquivo_nome"), "recalcular": False,
        "linhas": linhas, "data_referencia": DATA})


def _confirmar(cliente, eid, analise, linhas):
    r = _post_confirmar(cliente, eid, analise, linhas)
    assert r.status_code == 200, r.text
    return r.json()


def _turma(db, eid, nome, ano_escolar):
    from app.models import Turma
    t = Turma(escola_id=eid, nome=nome, ano_escolar=ano_escolar, ano_letivo=2026)
    db.add(t)
    db.commit()
    return t.id


def _turmas_do_aluno(db, eid, nome):
    from app.models import Aluno, Matricula, Turma
    db.expire_all()
    return db.execute(
        select(Turma.nome).join(Matricula, Matricula.turma_id == Turma.id)
        .join(Aluno, Aluno.id == Matricula.aluno_id)
        .where(Aluno.escola_id == eid, Aluno.nome == nome)).scalars().all()


def _motivos(db, eid):
    from app.models import RevisaoIdentidade
    db.expire_all()
    return sorted(r.motivo for r in db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == eid)).scalars())


def _fichas(db, eid):
    from app.models import Aluno
    db.expire_all()
    return db.scalar(select(func.count()).select_from(Aluno).where(Aluno.escola_id == eid))


def _linha(linha, **destino):
    """Uma linha do corpo como a tela a monta: nome, dados e o destino."""
    corpo = {"nome": linha["nome"], "dados": linha["dados"], "aluno_id": None,
             "criar_em_turma_id": None, "criar_em_turma_nome": None}
    corpo.update(destino)
    return corpo


def _relatorio(analise, linha):
    return linha["dados"].get("turma_relatorio") or analise["turma_detectada"]
