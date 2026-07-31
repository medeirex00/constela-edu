"""Detecção e fusão em LOTE de alunos duplicados (Fundir duplicatas).

Cobre os níveis de confiança (regra do dono: precisão acima de tudo):
  * nome curto ⊂ nome completo, MESMA turma → "revisar" (caso Akemi real);
  * nome idêntico + mesma turma → "alta";
  * abreviação posicional ("Agatha V" → "Agatha Vitoria…") → "revisar";
  * turma DIFERENTE → nunca sugere;
  * ambíguo (curto cabe em DOIS nomes completos) → nunca sugere;
e a aplicação em lote (só os confirmados), a confirmação obrigatória e a
permissão (professor não pode).
"""
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_senha
from app.main import app
from app.models import Aluno, Matricula, Turma, Usuario

API = "/api/v1"


def _base(escola_id: int) -> str:
    return f"{API}/escolas/{escola_id}"


def _add_aluno(db, escola_id, nome, turma_id, ano=2026, status="ativo",
               nascimento=None, ficha=None) -> Aluno:
    a = Aluno(escola_id=escola_id, nome=nome, status=status,
              data_nascimento=nascimento, ficha=ficha or {})
    db.add(a)
    db.flush()
    db.add(Matricula(escola_id=escola_id, aluno_id=a.id,
                     turma_id=turma_id, ano_letivo=ano))
    db.commit()
    return a


def _turma_b(db, escola_id) -> Turma:
    t = Turma(escola_id=escola_id, nome="3º Ano B", ano_escolar="3º Ano",
              ano_letivo=2026)
    db.add(t)
    db.commit()
    return t


def _cliente_professor(db, escola_id) -> TestClient:
    db.add(Usuario(escola_id=escola_id, nome="Prof", email="prof@teste.local",
                   senha_hash=hash_senha("s3nh4"), cargo="professor"))
    db.commit()
    c = TestClient(app)
    tok = c.post(f"{API}/auth/login",
                 data={"username": "prof@teste.local", "password": "s3nh4"}
                 ).json()["access_token"]
    c.headers["Authorization"] = f"Bearer {tok}"
    return c


def _duplicados(cliente, escola_id) -> dict:
    r = cliente.get(f"{_base(escola_id)}/alunos/duplicados")
    assert r.status_code == 200, r.text
    return r.json()


def test_detecta_subconjunto_mesma_turma_como_revisar(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    turma_id = escola_completa["turma"].id
    curto = _add_aluno(db, escola_id, "Akemi Carolina Vieira", turma_id)
    _add_aluno(db, escola_id, "Akemi Carolina Vieira Gomes Kariya", turma_id)

    corpo = _duplicados(cliente, escola_id)
    pares = [c for c in corpo["candidatos"] if c["apagar"].startswith("Akemi")]
    assert len(pares) == 1
    par = pares[0]
    assert par["loser_id"] == curto.id
    assert par["apagar"] == "Akemi Carolina Vieira"
    assert par["manter"] == "Akemi Carolina Vieira Gomes Kariya"
    assert par["confianca"] == "revisar"
    assert par["motivo"] == "subconjunto"
    assert par["turma"] == "3º Ano A"
    assert corpo["revisar"] >= 1


def test_nome_identico_sem_nascimento_e_revisar(cliente, db, escola_completa):
    """Mesmo nome, mesma turma, SEM data de nascimento nos dois → 'revisar' (pode
    ser homônimo/gêmeo). Não vira 'alta' nem entra pré-marcado."""
    escola_id = escola_completa["escola"].id
    turma_id = escola_completa["turma"].id
    primeiro = _add_aluno(db, escola_id, "Bruno Alves Costa", turma_id)
    _add_aluno(db, escola_id, "Bruno Alves Costa", turma_id)

    corpo = _duplicados(cliente, escola_id)
    pares = [c for c in corpo["candidatos"] if c["apagar"] == "Bruno Alves Costa"]
    assert len(pares) == 1
    assert pares[0]["manter_id"] == primeiro.id     # survivor = menor id
    assert pares[0]["confianca"] == "revisar"
    assert pares[0]["motivo"] == "nome_identico"


def test_nome_identico_nascimento_igual_e_alta(cliente, db, escola_completa):
    """Nascimento IGUAL nos dois corrobora → 'alta'."""
    escola_id = escola_completa["escola"].id
    turma_id = escola_completa["turma"].id
    nasc = date(2016, 3, 10)
    _add_aluno(db, escola_id, "Bruno Alves Costa", turma_id, nascimento=nasc)
    _add_aluno(db, escola_id, "Bruno Alves Costa", turma_id, nascimento=nasc)

    corpo = _duplicados(cliente, escola_id)
    pares = [c for c in corpo["candidatos"] if c["apagar"] == "Bruno Alves Costa"]
    assert len(pares) == 1
    assert pares[0]["confianca"] == "alta"


def test_nascimento_diferente_veta_a_sugestao(cliente, db, escola_completa):
    """Mesmo nome e turma, mas nascimento DIFERENTE = crianças distintas → NUNCA
    sugere (nem para revisar)."""
    escola_id = escola_completa["escola"].id
    turma_id = escola_completa["turma"].id
    _add_aluno(db, escola_id, "Bruno Alves Costa", turma_id, nascimento=date(2016, 3, 10))
    _add_aluno(db, escola_id, "Bruno Alves Costa", turma_id, nascimento=date(2017, 8, 1))

    corpo = _duplicados(cliente, escola_id)
    assert [c for c in corpo["candidatos"] if c["apagar"] == "Bruno Alves Costa"] == []


def test_cadeia_e_recusada_sem_colapsar_tres(cliente, db, escola_completa):
    """A='Maria Silva', B='Maria Silva' (gêmeo), C='Maria Silva Souza' na mesma
    turma: A→C e B→A formam uma CADEIA. Selecionar ambos NÃO pode colapsar as três
    crianças — os pares em cadeia são recusados e reportados."""
    escola_id = escola_completa["escola"].id
    turma_id = escola_completa["turma"].id
    a = _add_aluno(db, escola_id, "Maria Silva", turma_id)
    b = _add_aluno(db, escola_id, "Maria Silva", turma_id)
    c = _add_aluno(db, escola_id, "Maria Silva Souza", turma_id)

    corpo = _duplicados(cliente, escola_id)
    losers = [cand["loser_id"] for cand in corpo["candidatos"]]
    assert a.id in losers and b.id in losers

    r = cliente.post(f"{_base(escola_id)}/alunos/duplicados/corrigir",
                     json={"loser_ids": losers, "confirmacao": "FUNDIR"})
    assert r.status_code == 200, r.text
    assert r.json()["fundidos"] == 0
    assert len(r.json()["falhas"]) >= 1

    # As três crianças permanecem — nada colapsou.
    def existe(aluno_id: int) -> bool:
        return db.execute(
            select(Aluno.id).where(Aluno.id == aluno_id)).scalar_one_or_none() is not None
    assert existe(a.id) and existe(b.id) and existe(c.id)


def test_abreviacao_posicional_e_revisar(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    turma_id = escola_completa["turma"].id
    _add_aluno(db, escola_id, "Agatha V", turma_id)
    _add_aluno(db, escola_id, "Agatha Vitoria Moura", turma_id)

    corpo = _duplicados(cliente, escola_id)
    pares = [c for c in corpo["candidatos"] if c["apagar"] == "Agatha V"]
    assert len(pares) == 1
    assert pares[0]["manter"] == "Agatha Vitoria Moura"
    assert pares[0]["motivo"] == "abreviacao"


def test_turma_diferente_nunca_sugere(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    turma_a = escola_completa["turma"].id
    turma_b = _turma_b(db, escola_id)
    _add_aluno(db, escola_id, "Carla Dias", turma_a)
    _add_aluno(db, escola_id, "Carla Dias Souza", turma_b.id)

    corpo = _duplicados(cliente, escola_id)
    assert [c for c in corpo["candidatos"] if c["apagar"].startswith("Carla")] == []


def test_ambiguo_dois_completos_nao_sugere(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    turma_id = escola_completa["turma"].id
    _add_aluno(db, escola_id, "Diego", turma_id)          # curto (1 token)
    _add_aluno(db, escola_id, "Diego Alves", turma_id)
    _add_aluno(db, escola_id, "Diego Barros", turma_id)

    corpo = _duplicados(cliente, escola_id)
    # "Diego" cabe em DOIS nomes completos → ambíguo → não entra.
    assert [c for c in corpo["candidatos"] if c["apagar"] == "Diego"] == []


def test_aplicar_funde_apenas_selecionados_e_recalcula(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    turma_id = escola_completa["turma"].id
    curto_id = _add_aluno(db, escola_id, "Akemi Carolina Vieira", turma_id).id
    completo_id = _add_aluno(db, escola_id,
                             "Akemi Carolina Vieira Gomes Kariya", turma_id).id

    r = cliente.post(f"{_base(escola_id)}/alunos/duplicados/corrigir",
                     json={"loser_ids": [curto_id], "confirmacao": "FUNDIR"})
    assert r.status_code == 200, r.text
    assert r.json()["fundidos"] == 1

    # O cadastro curto sumiu; o completo permanece. Consulta por COLUNA (bypassa
    # o identity map da sessão do teste, que é outra que a do endpoint).
    def existe(aluno_id: int) -> bool:
        return db.execute(
            select(Aluno.id).where(Aluno.id == aluno_id)
        ).scalar_one_or_none() is not None
    assert not existe(curto_id)
    assert existe(completo_id)


def test_corrigir_exige_confirmacao(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    turma_id = escola_completa["turma"].id
    curto = _add_aluno(db, escola_id, "Akemi Carolina Vieira", turma_id)
    _add_aluno(db, escola_id, "Akemi Carolina Vieira Gomes Kariya", turma_id)

    r = cliente.post(f"{_base(escola_id)}/alunos/duplicados/corrigir",
                     json={"loser_ids": [curto.id], "confirmacao": ""})
    assert r.status_code == 400
    assert db.get(Aluno, curto.id) is not None   # nada fundido


def test_professor_nao_acessa(db, escola_completa):
    escola_id = escola_completa["escola"].id
    pc = _cliente_professor(db, escola_id)
    assert pc.get(f"{_base(escola_id)}/alunos/duplicados").status_code == 403
    assert pc.post(f"{_base(escola_id)}/alunos/duplicados/corrigir",
                   json={"loser_ids": [], "confirmacao": "FUNDIR"}).status_code == 403
