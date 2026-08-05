"""Teste REAL (ambiente seguro, banco de teste) dos 8 cenários de importação que o
dono pediu — provando, para CADA um, que a PRÉVIA (casar_nomes) mostra o mesmo que
a CONFIRMAÇÃO (_resolver_aluno) fará. Roda o motor único de ponta a ponta.

Imprime uma tabela com o resultado de cada cenário (rodar com -s para ver)."""
from datetime import date
from types import SimpleNamespace

from sqlalchemy import func, select

from app.models import Aluno, Escola, Matricula, Turma
from app.routers import importacoes
from app.services import importacao as svc


def _monta_escola(db):
    esc = Escola(nome="EMEF Teste Seguro", ano_letivo_ativo=2026, status="ativa")
    db.add(esc)
    db.flush()
    turmas = {}
    for nome, ano_escolar in [("5ºA", "5º Ano"), ("5ºB", "5º Ano")]:
        t = Turma(escola_id=esc.id, nome=nome, ano_escolar=ano_escolar,
                  ano_letivo=2026, status="ativa")
        db.add(t)
        db.flush()
        turmas[nome] = t

    def matricular(turma, nome, chamada=None, nascimento=None):
        a = Aluno(escola_id=esc.id, nome=nome, status="ativo", da_lista_piloto=True,
                  numero_chamada=chamada, data_nascimento=nascimento)
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=esc.id, aluno_id=a.id, turma_id=turma.id,
                         ano_letivo=2026))
        return a

    roster = {
        "maria": matricular(turmas["5ºA"], "MARIA EDUARDA SILVA",
                            chamada=10, nascimento=date(2015, 3, 1)),
        "gabriel": matricular(turmas["5ºA"], "GABRIEL SILVA"),
        "abraao": matricular(turmas["5ºA"], "ABRAÃO LUÍS DIAS"),
        "clara": matricular(turmas["5ºB"], "MARIA CLARA SANTOS"),
        "cecilia": matricular(turmas["5ºB"], "MARIA CECILIA LIMA"),
    }
    db.commit()
    return esc, roster


def _conta(db, esc_id):
    return db.execute(select(func.count()).select_from(Aluno)
                      .where(Aluno.escola_id == esc_id)).scalar_one()


def _confirmar(db, esc_id, nome, dados, corr) -> str:
    """Aplica a MESMA regra do frontend (só vinculado/exato pré-selecionam → importar;
    o resto → criar) e roda _resolver_aluno. Devolve o desfecho real da CONFIRMAÇÃO."""
    st = corr.get("status")
    if corr.get("aluno_id") and st in ("vinculado", "exato"):
        linha = SimpleNamespace(nome=nome, aluno_id=corr["aluno_id"],
                                criar_em_turma_id=None, criar_em_turma_nome=None,
                                numero_chamada=None, dados=dados)
    else:  # revisar / bloqueado / nao_encontrado → cria (passa pelo motor seguro)
        linha = SimpleNamespace(nome=nome, aluno_id=None, criar_em_turma_id=None,
                                criar_em_turma_nome=dados.get("turma_relatorio"),
                                numero_chamada=None, dados=dados)
    antes = _conta(db, esc_id)
    r = importacoes._resolver_aluno(db, esc_id, 2026, linha, [], {}, {})
    db.flush()
    novos = _conta(db, esc_id) - antes
    if r is None:
        return "PULOU (ambíguo — não cria, vai p/ revisão)"
    if novos == 0:
        return f"VINCULOU ao id {r.id} ({r.nome})"
    return f"CRIOU novo id {r.id} ({r.nome})"


def test_oito_cenarios_do_dono(db):
    esc, roster = _monta_escola(db)
    maria = roster["maria"]

    cenarios = [
        ("1. Nome completo exato",        "MARIA EDUARDA SILVA", {"turma_relatorio": "5ºA"}),
        ("2. Abreviado 'MARIA E'",        "MARIA E",             {"turma_relatorio": "5ºA"}),
        ("3. Inicial 'M. EDUARDA'",       "M. EDUARDA",          {"turma_relatorio": "5ºA"}),
        ("4. Truncado 'MARIA EDU'",       "MARIA EDU",           {"turma_relatorio": "5ºA"}),
        ("5. Typo 'GABRYEL SILVA'",       "GABRYEL SILVA",       {"turma_relatorio": "5ºA"}),
        ("6. Abreviado ambíguo 'MARIA C'", "MARIA C",            {"turma_relatorio": "5ºB"}),
        ("7. Conflito de nascimento",     "MARIA EDUARDA SILVA",
            {"turma_relatorio": "5ºA", "data_nascimento": "2018-09-09"}),
    ]

    # PRÉVIA: roda o motor em TODAS as linhas de uma vez (read-only).
    linhas = [svc.LinhaImportacao(numero=i, nome=n, dados=d)
              for i, (_, n, d) in enumerate(cenarios, 1)]
    svc.casar_nomes(db, esc.id, linhas)

    print("\n\n========= TESTE DOS 8 CENARIOS (ambiente seguro) =========")
    print(f"{'CENARIO':<34}{'PREVIA':<13}{'-> CONFIRMACAO'}")
    print("-" * 90)
    # Cenário 5 (typo no 1º nome GABRYEL/GABRIEL, 2 tokens) → REVISAR: variação de 1º
    # nome não é "segura" p/ auto-vínculo (guard-rail do red-team 2026-08-04). A
    # variação SEGURA de nome do meio (ex.: ABRAÃO LUÍS/LUIZ) é que vincula.
    esperado = ["vinculado_exato", "vinculado", "vinculado", "vinculado",
                "revisar", "revisar", "bloqueado"]
    for (rotulo, nome, dados), linha, exp in zip(cenarios, linhas, esperado):
        corr = linha.correspondencia
        st = corr["status"]
        confirm = _confirmar(db, esc.id, nome, dados, corr)
        print(f"{rotulo:<34}{st:<13}-> {confirm}")
        # Verifica a EQUIVALÊNCIA prévia = confirmação por cenário.
        if exp == "vinculado_exato":
            assert st in ("vinculado", "exato")
            assert "VINCULOU" in confirm and str(maria.id) in confirm
        elif exp == "vinculado":
            assert st == "vinculado" and corr["aluno_id"] == maria.id
            assert f"VINCULOU ao id {maria.id}" in confirm
        elif exp == "revisar":
            assert st == "revisar"
            assert "VINCULOU" not in confirm      # nunca vínculo automático
        elif exp == "bloqueado":
            assert st == "bloqueado"
            assert "VINCULOU" not in confirm      # conflito → não vincula (cria outro)

    # CENÁRIO 8: reimportar os MESMOS dados não cria duplicatas.
    antes = _conta(db, esc.id)
    linhas2 = [svc.LinhaImportacao(numero=i, nome=n, dados=d)
               for i, (_, n, d) in enumerate(cenarios, 1)]
    svc.casar_nomes(db, esc.id, linhas2)
    for (_, nome, dados), linha in zip(cenarios, linhas2):
        _confirmar(db, esc.id, nome, dados, linha.correspondencia)
    depois = _conta(db, esc.id)
    print("-" * 90)
    print(f"8. Reimportação dos mesmos dados: alunos antes={antes}, depois={depois} "
          f"(delta={depois - antes})")
    print("=" * 90)
    assert depois == antes, "reimportar NAO pode criar duplicatas"
