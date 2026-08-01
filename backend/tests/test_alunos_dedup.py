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


def test_previa_em_lote_nao_faz_n_mais_1_de_queries(db, escola_completa):
    """Regressão de performance (Debora Pilon travava): a prévia calcula o impacto
    de TODOS os candidatos em poucas queries (GROUP BY), não ~6 por candidato."""
    from sqlalchemy import event
    from app.services import alunos_dedup

    escola_id = escola_completa["escola"].id
    turma_id = escola_completa["turma"].id
    for i in range(30):                      # 30 pares de nome idêntico
        _add_aluno(db, escola_id, f"Fulano{i} Sobrenome Teste", turma_id)
        _add_aluno(db, escola_id, f"Fulano{i} Sobrenome Teste", turma_id)

    contador = {"n": 0}
    bind = db.get_bind()

    def _conta(*_a, **_k):
        contador["n"] += 1

    event.listen(bind, "before_cursor_execute", _conta)
    try:
        plano = alunos_dedup.plano_deduplicacao(db, escola_id)
    finally:
        event.remove(bind, "before_cursor_execute", _conta)

    assert len(plano) >= 30
    assert plano[0]["impacto"] is not None
    # Constante (não proporcional aos 30 candidatos: seriam ~180 no N+1).
    assert contador["n"] < 20, f"queries demais: {contador['n']}"


def _turma(db, escola_id, nome) -> Turma:
    t = Turma(escola_id=escola_id, nome=nome, ano_escolar="4º Ano", ano_letivo=2026)
    db.add(t)
    db.commit()
    return t


def test_detecta_variante_em_turmas_fantasma_da_mesma_sala(cliente, db, escola_completa):
    """Passivo Debora Pilon: ABRAÃO LUÍS DIAS (Lista Piloto, turma '4ºC') e
    ABRAAO LUIZ DIAS (importado numa turma-fantasma '4 ANO C INTEGRAL (300303525)').
    São a MESMA sala (chave canônica '4|C') e nomes variantes → detecta 'revisar',
    survivor = o da Lista Piloto (mesmo estando em turmas com id diferente)."""
    escola_id = escola_completa["escola"].id
    t_boa = _turma(db, escola_id, "4ºC")
    t_fantasma = _turma(db, escola_id, "4 ANO C INTEGRAL (300303525)")
    luis = _add_aluno(db, escola_id, "ABRAÃO LUÍS DIAS", t_boa.id)
    luis.da_lista_piloto = True
    db.commit()
    luiz = _add_aluno(db, escola_id, "ABRAAO LUIZ DIAS", t_fantasma.id)

    corpo = _duplicados(cliente, escola_id)
    pares = [c for c in corpo["candidatos"] if "ABRA" in c["apagar"].upper()]
    assert len(pares) == 1
    assert pares[0]["loser_id"] == luiz.id and pares[0]["manter_id"] == luis.id
    assert pares[0]["confianca"] == "revisar" and pares[0]["motivo"] == "variante"


def test_leque_triplicado_funde_tudo_no_perfil_da_lista_piloto(cliente, db, escola_completa):
    """LEQUE: o perfil da Lista Piloto + duas fichas de MESMO nome (import repetido)
    na mesma turma, todas apontando para o piloto (A→S, B→S). "Selecionar todos"
    funde as duas de uma vez (manual) e sobra só o perfil principal."""
    escola_id = escola_completa["escola"].id
    turma_id = escola_completa["turma"].id
    piloto = _add_aluno(db, escola_id, "ABRAÃO LUÍS DIAS", turma_id)   # 1º id (LP)
    piloto.da_lista_piloto = True
    db.commit()
    dup1 = _add_aluno(db, escola_id, "ABRAÃO LUÍS DIAS", turma_id)     # ficha repetida
    dup2 = _add_aluno(db, escola_id, "ABRAAO LUIS DIAS", turma_id)     # variação de acento

    corpo = _duplicados(cliente, escola_id)
    pares = [c for c in corpo["candidatos"] if "ABRA" in c["apagar"].upper()]
    assert {p["manter_id"] for p in pares} == {piloto.id}      # tudo aponta p/ o LP
    losers = [p["loser_id"] for p in pares]
    assert set(losers) == {dup1.id, dup2.id}

    r = cliente.post(f"{_base(escola_id)}/alunos/duplicados/corrigir",
                     json={"loser_ids": losers, "confirmacao": "FUNDIR"})
    assert r.status_code == 200, r.text
    assert r.json()["fundidos"] == 2 and r.json()["falhas"] == []

    def existe(aid):
        return db.execute(select(Aluno.id).where(Aluno.id == aid)
                          ).scalar_one_or_none() is not None
    assert existe(piloto.id) and not existe(dup1.id) and not existe(dup2.id)


def test_variante_nao_pareia_criancas_diferentes(cliente, db, escola_completa):
    """ABRAÃO LUÍS DIAS × ABRAÃO LUCAS DIAS na MESMA turma são crianças DIFERENTES
    (LUÍS/LUCAS não é variante ortográfica) → NUNCA sugere."""
    escola_id = escola_completa["escola"].id
    turma_id = escola_completa["turma"].id
    _add_aluno(db, escola_id, "ABRAÃO LUÍS DIAS", turma_id)
    _add_aluno(db, escola_id, "ABRAÃO LUCAS DIAS", turma_id)

    corpo = _duplicados(cliente, escola_id)
    assert [c for c in corpo["candidatos"] if "ABRA" in c["apagar"].upper()] == []


# --- Regressões de SEGURANÇA da detecção (achados da revisão adversarial) ----
# (A auto-fusão foi removida por insegura; estes garantem que a detecção manual
#  não colapsa crianças diferentes.)

def test_homonimos_com_stub_nao_sao_sugeridos(cliente, db, escola_completa):
    """Achado adversarial [2]: dois homônimos 'MARIA EDUARDA SANTOS' + um stub
    'MARIA EDUARDA' → 2 alunos candidatos (ambíguo) → o stub NÃO é sugerido (não
    pode ser colado num dos homônimos por acaso)."""
    escola_id = escola_completa["escola"].id
    turma_id = escola_completa["turma"].id
    _add_aluno(db, escola_id, "MARIA EDUARDA SANTOS", turma_id)
    _add_aluno(db, escola_id, "MARIA EDUARDA SANTOS", turma_id)
    _add_aluno(db, escola_id, "MARIA EDUARDA", turma_id)

    corpo = _duplicados(cliente, escola_id)
    # O stub abreviado ambíguo NÃO vira sugestão de subconjunto/abreviação.
    assert [c for c in corpo["candidatos"]
            if c["apagar"] == "MARIA EDUARDA" and c["motivo"] in ("subconjunto", "abreviacao")] == []


def test_deteccao_preserva_perfil_da_lista_piloto_mesmo_curto(cliente, db, escola_completa):
    """Achado adversarial [3]: quando o perfil da Lista Piloto tem o nome MAIS
    CURTO ('MARIA SILVA') e há uma ficha de plataforma mais longa ('MARIA EDUARDA
    DA SILVA'), o survivor deve ser o PILOTO (nunca deletá-lo, nome oficial mantido)."""
    escola_id = escola_completa["escola"].id
    turma_id = escola_completa["turma"].id
    piloto = _add_aluno(db, escola_id, "MARIA SILVA", turma_id)
    piloto.da_lista_piloto = True
    db.commit()
    longa = _add_aluno(db, escola_id, "MARIA EDUARDA DA SILVA", turma_id)

    corpo = _duplicados(cliente, escola_id)
    pares = [c for c in corpo["candidatos"] if "MARIA" in c["apagar"].upper()]
    assert len(pares) == 1
    assert pares[0]["manter_id"] == piloto.id          # piloto sobrevive
    assert pares[0]["loser_id"] == longa.id            # a ficha longa é a que sai
