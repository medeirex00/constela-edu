"""Convenção de credenciais, reconciliação nome curto↔completo, deduplicação e
login case-insensitive das contas de professor."""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_senha
from app.main import app
from app.models import Professor, Usuario
from app.services import professores as P


def _login(username: str, senha: str) -> int:
    """Status do login por @usuario (testa senha + case-insensitivity)."""
    cliente = TestClient(app)
    r = cliente.post("/api/v1/auth/login", data={"username": username, "password": senha})
    return r.status_code


# --- Convenção ---------------------------------------------------------------

def test_convencao_usuario_e_senha():
    assert P.credenciais_professor("Paula Benedita Vilela Nogueira") == ("PaulaNogueira", "paulanogueira123")
    assert P.credenciais_professor("Sueli Macedo do Prado") == ("SueliPrado", "sueliprado123")  # pula "do"
    assert P.credenciais_professor("Ana Lucia") == ("AnaLucia", "analucia123")


# --- Reconciliação (raiz da duplicação) --------------------------------------

def test_curto_depois_completo_nao_duplica_e_promove(db, escola_completa):
    escola = escola_completa["escola"]
    p1, novo1 = P.garantir_professor(db, escola.id, "PAULA")
    assert novo1 is True
    p2, novo2 = P.garantir_professor(db, escola.id, "Paula Benedita Vilela Nogueira")
    assert novo2 is False and p2.id == p1.id            # reconciliou, não criou 2ª
    db.flush()
    assert p1.nome == "Paula Benedita Vilela Nogueira"  # promoveu o NOME de exibição
    u = P._usuario_do_professor(db, escola.id, p1)
    assert u.username == "Paula"                          # @/senha PRESERVADOS (não rotaciona)
    db.commit()
    assert _login("paula", "paula123") == 200            # credencial já entregue segue valendo


def test_import_nao_reconcilia_dois_nomes_com_sobrenome(db, escola_completa):
    """'Ana Paula' e 'Ana Paula Souza' são pessoas diferentes (ambos com
    sobrenome) — o import NÃO pode fundi-las."""
    escola = escola_completa["escola"]
    p1, _ = P.garantir_professor(db, escola.id, "Ana Paula")
    p2, novo = P.garantir_professor(db, escola.id, "Ana Paula Souza")
    db.flush()
    assert novo is True and p2.id != p1.id
    assert p1.nome == "Ana Paula"                        # não foi promovida/renomeada


def test_completo_depois_curto_nao_duplica(db, escola_completa):
    escola = escola_completa["escola"]
    p1, _ = P.garantir_professor(db, escola.id, "Fernanda Lima da Silva")
    p2, novo = P.garantir_professor(db, escola.id, "FERNANDA")
    assert novo is False and p2.id == p1.id             # curto casa no completo
    db.flush()
    assert p1.nome == "Fernanda Lima da Silva"          # não rebaixa o nome


def test_homonimos_nao_fundem(db, escola_completa):
    """Dois sobrenomes diferentes com o mesmo 1º nome NÃO se fundem sozinhos."""
    escola = escola_completa["escola"]
    P.garantir_professor(db, escola.id, "Maiara Silva")
    P.garantir_professor(db, escola.id, "Maiara Souza")
    _, novo = P.garantir_professor(db, escola.id, "MAIARA")   # ambíguo → cria
    db.flush()
    nomes = {p.nome for p in db.execute(
        select(Professor).where(Professor.escola_id == escola.id)).scalars()}
    assert {"Maiara Silva", "Maiara Souza", "MAIARA"} <= nomes


# --- Deduplicação do que já duplicou -----------------------------------------

def _par_duplicado(db, escola, turma):
    """Cria o par real: curto COM turma + completo SEM turma (como em produção)."""
    curto = Professor(escola_id=escola.id, nome="PAULA",
                      email="paula@professor.constelaedu.com")
    completo = Professor(escola_id=escola.id, nome="Paula Benedita Vilela Nogueira",
                         email="paulanogueira@professor.constelaedu.com")
    db.add_all([curto, completo])
    db.flush()
    turma.professor_id = curto.id
    db.add(Usuario(escola_id=escola.id, nome="PAULA", email=curto.email,
                   username="Paula", senha_hash=hash_senha("qualquer"), cargo="professor"))
    db.add(Usuario(escola_id=escola.id, nome="Paula Benedita Vilela Nogueira",
                   email=completo.email, username="paulanogueira",
                   senha_hash=hash_senha("qualquer"), cargo="professor"))
    db.commit()
    return curto, completo


def test_previa_nao_altera_nada(db, escola_completa):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    _par_duplicado(db, escola, turma)
    grupos = P.plano_deduplicacao(db, escola.id)
    assert len(grupos) == 1
    g = grupos[0]
    assert g["manter"] == "Paula Benedita Vilela Nogueira"
    assert g["usuario_novo"] == "PaulaNogueira" and g["senha_nova"] == "paulanogueira123"
    assert [a["nome"] for a in g["apagar"]] == ["PAULA"]
    # NADA mudou (é só prévia): as 2 contas continuam lá.
    assert db.execute(select(Usuario).where(Usuario.username == "Paula")).scalar_one_or_none() is not None


def test_aplicar_funde_move_turma_padroniza_e_loga(db, escola_completa):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    _par_duplicado(db, escola, turma)

    folha = P.aplicar_deduplicacao(db, escola.id)
    db.commit()

    assert folha == [{"nome": "Paula Benedita Vilela Nogueira",
                      "usuario": "PaulaNogueira", "senha": "paulanogueira123"}]
    nomes = {p.nome for p in db.execute(
        select(Professor).where(Professor.escola_id == escola.id)).scalars()}
    assert "PAULA" not in nomes and "Paula Benedita Vilela Nogueira" in nomes
    db.refresh(turma)
    completo = db.execute(select(Professor).where(
        Professor.nome == "Paula Benedita Vilela Nogueira")).scalar_one()
    assert turma.professor_id == completo.id                    # turma migrou
    assert db.execute(select(Usuario).where(Usuario.username == "Paula")).scalar_one_or_none() is None
    assert _login("PAULANOGUEIRA", "paulanogueira123") == 200   # @ maiúsculo + senha nova


def test_survivor_ja_ativo_preserva_senha_e_sessao(db, escola_completa):
    """Achado ALTO: se a professora JÁ usava a conta que fica (ultimo_acesso),
    a correção move a turma e apaga o curto, mas NÃO reseta a senha nem derruba
    a sessão dela — a senha própria continua valendo."""
    from datetime import datetime, timezone
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    _curto, completo = _par_duplicado(db, escola, turma)
    su = P._usuario_do_professor(db, escola.id, completo)
    su.senha_hash = hash_senha("MinhaSenhaForte#1")
    su.ultimo_acesso = datetime.now(timezone.utc)
    su.token_version = 3
    db.commit()
    hash_antes, tv_antes, user_antes = su.senha_hash, su.token_version, su.username

    folha = P.aplicar_deduplicacao(db, escola.id)
    db.commit()

    db.refresh(su)
    db.refresh(turma)
    assert su.senha_hash == hash_antes and su.token_version == tv_antes  # senha/sessão intactas
    assert su.username == user_antes
    assert turma.professor_id == completo.id                             # turma ainda migrou
    assert folha == [{"nome": "Paula Benedita Vilela Nogueira", "usuario": user_antes, "senha": None}]
    assert _login(user_antes, "MinhaSenhaForte#1") == 200                # a senha dela funciona


def test_bridge_nao_funde_homonimas(db, escola_completa):
    """Achado MÉDIO: 'Maria Silva' + 'Maria Souza' + 'Maria Silva Souza' são três
    pessoas diferentes; a dedup NÃO pode fundir ninguém (nenhum nome-curto)."""
    escola = escola_completa["escola"]
    db.add(Professor(escola_id=escola.id, nome="Maria Silva", email="m1@professor.constelaedu.com"))
    db.add(Professor(escola_id=escola.id, nome="Maria Souza", email="m2@professor.constelaedu.com"))
    db.add(Professor(escola_id=escola.id, nome="Maria Silva Souza", email="m3@professor.constelaedu.com"))
    db.commit()
    assert P.plano_deduplicacao(db, escola.id) == []


def test_username_em_uso_case_insensitive(db, escola_completa):
    """Achado MÉDIO: criar 'paulanogueira' ao lado de 'PaulaNogueira' quebraria o
    login (500). A checagem de disponibilidade é acento/caixa-insensível."""
    from app.routers.admin import _username_em_uso
    escola = escola_completa["escola"]
    db.add(Usuario(escola_id=escola.id, nome="P", email="pn@professor.constelaedu.com",
                   username="PaulaNogueira", senha_hash=hash_senha("x"), cargo="professor"))
    db.commit()
    assert _username_em_uso(db, "paulanogueira") is True
    assert _username_em_uso(db, "PAULANOGUEIRA") is True
    assert _username_em_uso(db, "outronome") is False


def test_login_aceita_qualquer_caixa(db, escola_completa):
    escola = escola_completa["escola"]
    db.add(Usuario(escola_id=escola.id, nome="Teste Prof", email="t@professor.constelaedu.com",
                   username="TesteProf", senha_hash=hash_senha("segredo123"), cargo="professor"))
    db.commit()
    assert _login("testeprof", "segredo123") == 200
    assert _login("TESTEPROF", "segredo123") == 200
