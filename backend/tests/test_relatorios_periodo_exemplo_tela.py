"""O exemplo do Relatório por Período que a tela usa é a resposta REAL da rota.

Os testes da tela (``apps/web/src/test/RelatorioPeriodo.test.tsx``) montam a resposta à
mão; para um campo que a tela lê do backend, isso deixa passar o campo que o backend
não manda (foi o que aconteceu com o ``motivo`` da prévia de importação, T1). Aqui a
cena é montada no banco, a rota ``/relatorios/periodo`` responde, e o JSON fica gravado
para a tela (``apps/web/src/test/fixtures/relatorio_periodo/``), que o consome sem
adaptação — como ``test_importacao_previa_motivo``.

A cena (setembro, Elefante e Matific):
  * Ana: coletas de 15/08 (com as questões), 01/09 (a coleta do INÍCIO, que veio SEM as
    questões) e 01/10 (que mede o fim) — a conta parte de 15/08 e inclui o intervalo;
  * João: coletas de 01/09 e 01/10, as duas com as questões; e Matific em 30/08 e 29/09;
  * Sofia: sem coleta.

Para regravar:
``GERAR_FIXTURES_RELATORIO=1 python -m pytest tests/test_relatorios_periodo_exemplo_tela.py``.
Dados fictícios.
"""
import json
import os
import pathlib
from datetime import datetime

import pytest

from app.models import Importacao, SnapshotElefante, SnapshotMatific
from app.models.plataformas import IMPORTACAO_SEM_QUESTOES

RAIZ = pathlib.Path(__file__).resolve().parents[2]
EXEMPLO_WEB = (RAIZ / "apps" / "web" / "src" / "test" / "fixtures" / "relatorio_periodo"
               / "setembro_inicio_sem_questoes.json")
GERAR = os.environ.get("GERAR_FIXTURES_RELATORIO") == "1"
ROTA = "/api/v1/escolas/{eid}/relatorios/periodo"


def _importacao(db, eid, plataforma, quando, *, sem_questoes=False) -> int:
    imp = Importacao(escola_id=eid, usuario_id=None, plataforma=plataforma, tipo="pdf",
                     arquivo_original=None, qtd_alunos=0, qtd_erros=0, tempo_ms=0,
                     created_at=quando,
                     status=IMPORTACAO_SEM_QUESTOES if sem_questoes else "concluida")
    db.add(imp)
    db.flush()
    return imp.id


def _elefante(db, eid, aluno_id, quando, tentativas, acertos, *, sem_questoes=False):
    db.add(SnapshotElefante(
        escola_id=eid, aluno_id=aluno_id, data_referencia=quando, livros_unicos=3,
        tempo_leitura_min=40, questoes_tentativas=tentativas, questoes_acertos=acertos,
        livros_por_nivel={},
        importacao_id=_importacao(db, eid, "elefante", quando, sem_questoes=sem_questoes)))


def _matific(db, eid, aluno_id, quando, atividades, estrelas):
    db.add(SnapshotMatific(escola_id=eid, aluno_id=aluno_id, data_referencia=quando,
                           atividades=atividades, estrelas=estrelas,
                           importacao_id=_importacao(db, eid, "matific", quando)))


def _noite(dia: int, mes: int = 9) -> datetime:
    """A coleta da agenda: 00:10 em Brasília (03:10 UTC)."""
    return datetime(2026, mes, dia, 3, 10)


def _resposta(cliente, escola_completa, db) -> dict:
    eid = escola_completa["escola"].id
    ana, joao, _sofia = (a.id for a in escola_completa["alunos"])
    _elefante(db, eid, ana, _noite(15, 8), 40, 30)
    _elefante(db, eid, ana, _noite(1), 40, 30, sem_questoes=True)   # a coleta do início
    _elefante(db, eid, ana, _noite(1, 10), 55, 40)
    _elefante(db, eid, joao, _noite(1), 10, 5)
    _elefante(db, eid, joao, _noite(1, 10), 20, 10)
    _matific(db, eid, joao, datetime(2026, 8, 30, 12, 0), 20, 30)
    _matific(db, eid, joao, datetime(2026, 9, 29, 12, 0), 35, 50)
    db.commit()
    r = cliente.get(ROTA.format(eid=eid), params={
        "periodo": "personalizado", "inicio": "2026-09-01", "fim": "2026-09-30",
        "plataformas": ["elefante", "matific"]})
    assert r.status_code == 200, r.text
    return r.json()


def test_resposta_real_traz_o_que_a_tela_le(cliente, escola_completa, db):
    """O que os testes da tela usam deste exemplo vem mesmo do backend: o aviso da
    coleta do início sem as questões (R2) e a forma de ``suporte``/``nao_suportado``
    que decide o "Como ler estes números" (R4)."""
    dados = _resposta(cliente, escola_completa, db)
    ele = dados["elefante"]
    cob = ele["cobertura_questoes"]
    assert (ele["questoes_tentativas"], ele["questoes_acertos"]) == (25, 15)
    assert cob["status"] == "ampliada", cob
    assert (cob["alunos_inicio_sem_questoes"], cob["alunos_ampliados"]) == (1, 0), cob
    assert cob["alunos_medidos"] == 2
    assert cob["coleta_base_inicio_sem_questoes"].startswith("2026-08-15T03:10"), cob
    assert cob["antecedencia_inicio_sem_questoes_horas"] == 17 * 24, cob
    # O Elefante calcula as questões ("questoes" em suporte); o Matific não as tem
    # ({matific, questoes} em nao_suportado) — a mesma chave, em plataformas diferentes.
    assert ele["suporte"]["questoes"]["classificacao"] == "SUPORTADO COM RESSALVA"
    assert {"plataforma": "matific", "metrica": "questoes"} in [
        {k: n[k] for k in ("plataforma", "metrica")} for n in dados["nao_suportado"]]
    assert not any(n["plataforma"] == "elefante" and n["metrica"] == "questoes"
                   for n in dados["nao_suportado"])


def _sem_ids(valor):
    """O que não depende do banco: os ids (sequências do PostgreSQL) ficam de fora."""
    if isinstance(valor, dict):
        return {k: _sem_ids(v) for k, v in valor.items() if k != "id" and not k.endswith("_id")}
    if isinstance(valor, list):
        return [_sem_ids(v) for v in valor]
    return valor


def test_exemplo_da_tela_e_a_resposta_real(cliente, escola_completa, db):
    real = _resposta(cliente, escola_completa, db)
    if GERAR:
        EXEMPLO_WEB.parent.mkdir(parents=True, exist_ok=True)
        EXEMPLO_WEB.write_text(json.dumps(real, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8", newline="\n")
    if not EXEMPLO_WEB.parent.parent.exists():
        pytest.skip("cópia sem apps/web: o exemplo da tela não está aqui")
    assert EXEMPLO_WEB.exists(), "falta o exemplo da tela: regrave com GERAR_FIXTURES_RELATORIO=1"
    gravado = json.loads(EXEMPLO_WEB.read_text(encoding="utf-8"))
    assert _sem_ids(gravado) == _sem_ids(real), (
        "o exemplo da tela está defasado: regrave com GERAR_FIXTURES_RELATORIO=1")
