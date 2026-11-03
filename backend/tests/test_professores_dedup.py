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
    """O @ segue a convenção; a senha não (Fase 3A)."""
    assert P.usuario_base_professor("Telma Belinora Varoni Testelli") == "TelmaTestelli"
    assert P.usuario_base_professor("Gertrudes Simulatti do Fictelo") == "GertrudesFictelo"  # pula "do"
    assert P.usuario_base_professor("Ivone Celia") == "IvoneCelia"
    usuario, senha = P.credenciais_professor("Ivone Celia")
    assert usuario == "IvoneCelia"
    assert senha not in P._senhas_da_convencao_antiga("Ivone Celia", usuario)


def _senha_e_aleatoria(senha, nome, usuario):
    assert senha and senha not in P._senhas_da_convencao_antiga(nome, usuario)


# --- Reconciliação (raiz da duplicação) --------------------------------------

def test_curto_depois_completo_nao_duplica_e_promove(db, escola_completa):
    escola = escola_completa["escola"]
    p1, novo1 = P.garantir_professor(db, escola.id, "TELMA")
    assert novo1 is True
    db.flush()
    hash_original = P._usuario_do_professor(db, escola.id, p1).senha_hash
    p2, novo2 = P.garantir_professor(db, escola.id, "Telma Belinora Varoni Testelli")
    assert novo2 is False and p2.id == p1.id            # reconciliou, não criou 2ª
    db.flush()
    assert p1.nome == "Telma Belinora Varoni Testelli"  # promoveu o NOME de exibição
    u = P._usuario_do_professor(db, escola.id, p1)
    assert u.username == "Telma"                          # @/senha PRESERVADOS (não rotaciona)
    hash_antes = hash_original
    db.commit()
    db.refresh(u)
    # A reconciliação não rotaciona a senha: quem já recebeu a credencial (pelo
    # link de redefinição ou por uma folha) continua entrando com ela.
    assert u.senha_hash == hash_antes


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
    curto = Professor(escola_id=escola.id, nome="TELMA",
                      email="telma@professor.constelaedu.com")
    completo = Professor(escola_id=escola.id, nome="Telma Belinora Varoni Testelli",
                         email="telmatestelli@professor.constelaedu.com")
    db.add_all([curto, completo])
    db.flush()
    turma.professor_id = curto.id
    db.add(Usuario(escola_id=escola.id, nome="TELMA", email=curto.email,
                   username="Telma", senha_hash=hash_senha("qualquer"), cargo="professor"))
    db.add(Usuario(escola_id=escola.id, nome="Telma Belinora Varoni Testelli",
                   email=completo.email, username="telmatestelli",
                   senha_hash=hash_senha("qualquer"), cargo="professor"))
    db.commit()
    return curto, completo


def test_previa_nao_altera_nada(db, escola_completa):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    curto, _completo = _par_duplicado(db, escola, turma)
    cands = P.plano_deduplicacao(db, escola.id)
    assert len(cands) == 1
    c = cands[0]
    assert c["apagar"] == "TELMA" and c["manter"] == "Telma Belinora Varoni Testelli"
    assert c["confianca"] == "alta"      # primeiro nome sozinho = certeza
    assert c["usuario_novo"] == "TelmaTestelli"
    # A prévia não carrega senha nenhuma — só avisa que uma será gerada.
    assert c["senha_nova"] == P.SENHA_GERADA_AO_APLICAR
    assert c["loser_id"] == curto.id
    # NADA mudou (é só prévia): as 2 contas continuam lá.
    assert db.execute(select(Usuario).where(Usuario.username == "Telma")).scalar_one_or_none() is not None


def test_aplicar_funde_move_turma_padroniza_e_loga(db, escola_completa):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    curto, _completo = _par_duplicado(db, escola, turma)

    folha = P.aplicar_deduplicacao(db, escola.id, [curto.id])
    db.commit()

    assert len(folha) == 1
    assert folha[0]["nome"] == "Telma Belinora Varoni Testelli"
    assert folha[0]["usuario"] == "TelmaTestelli"
    senha_da_folha = folha[0]["senha"]
    _senha_e_aleatoria(senha_da_folha, "Telma Belinora Varoni Testelli", "TelmaTestelli")
    nomes = {p.nome for p in db.execute(
        select(Professor).where(Professor.escola_id == escola.id)).scalars()}
    assert "TELMA" not in nomes and "Telma Belinora Varoni Testelli" in nomes
    db.refresh(turma)
    completo = db.execute(select(Professor).where(
        Professor.nome == "Telma Belinora Varoni Testelli")).scalar_one()
    assert turma.professor_id == completo.id                    # turma migrou
    assert db.execute(select(Usuario).where(Usuario.username == "Telma")).scalar_one_or_none() is None
    assert _login("TELMATESTELLI", senha_da_folha) == 200   # @ maiúsculo + senha da folha
    assert _login("TELMATESTELLI", "telmatestelli123") == 401  # a derivada não entra


def test_ivone_celia_composto_funde_so_quando_confirmado(db, escola_completa):
    """Nome COMPOSTO ('Ivone Celia' → 'Ivone Celia Fortunelli de Ficticio') É proposto
    (confiança 'revisar') e funde quando o gestor confirma — resolve o caso real
    que a regra estrita de 1 token não pegava."""
    escola = escola_completa["escola"]
    curto = Professor(escola_id=escola.id, nome="Ivone Celia",
                      email="ivonecelia@professor.constelaedu.com")
    completo = Professor(escola_id=escola.id, nome="Ivone Celia Fortunelli de Ficticio",
                         email="ivoneficticio@professor.constelaedu.com")
    db.add_all([curto, completo])
    db.flush()
    db.add(Usuario(escola_id=escola.id, nome="Ivone Celia", email=curto.email,
                   username="IvoneCelia", senha_hash=hash_senha("x"), cargo="professor"))
    db.add(Usuario(escola_id=escola.id, nome="Ivone Celia Fortunelli de Ficticio",
                   email=completo.email, username="IvoneFicticio",
                   senha_hash=hash_senha("y"), cargo="professor"))
    db.commit()

    alvo = next(c for c in P.plano_deduplicacao(db, escola.id) if c["apagar"] == "Ivone Celia")
    assert alvo["manter"] == "Ivone Celia Fortunelli de Ficticio"
    assert alvo["confianca"] == "revisar"           # composto → pede conferência
    assert alvo["usuario_novo"] == "IvoneFicticio"

    folha = P.aplicar_deduplicacao(db, escola.id, [curto.id])
    db.commit()
    assert [(f["nome"], f["usuario"]) for f in folha] == [
        ("Ivone Celia Fortunelli de Ficticio", "IvoneFicticio")]
    _senha_e_aleatoria(folha[0]["senha"], "Ivone Celia Fortunelli de Ficticio", "IvoneFicticio")
    assert db.execute(select(Professor).where(Professor.nome == "Ivone Celia")).scalar_one_or_none() is None


def test_survivor_ja_ativo_preserva_senha_e_sessao(db, escola_completa):
    """Achado ALTO: se a professora JÁ usava a conta que fica (ultimo_acesso),
    a correção move a turma e apaga o curto, mas NÃO reseta a senha nem derruba
    a sessão dela — a senha própria continua valendo."""
    from datetime import datetime, timezone
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    curto, completo = _par_duplicado(db, escola, turma)
    su = P._usuario_do_professor(db, escola.id, completo)
    su.senha_hash = hash_senha("MinhaSenhaForte#1")
    su.ultimo_acesso = datetime.now(timezone.utc)
    su.token_version = 3
    db.commit()
    hash_antes, tv_antes, user_antes = su.senha_hash, su.token_version, su.username

    folha = P.aplicar_deduplicacao(db, escola.id, [curto.id])
    db.commit()

    db.refresh(su)
    db.refresh(turma)
    assert su.senha_hash == hash_antes and su.token_version == tv_antes  # senha/sessão intactas
    assert su.username == user_antes
    assert turma.professor_id == completo.id                             # turma ainda migrou
    assert folha == [{"nome": "Telma Belinora Varoni Testelli", "usuario": user_antes, "senha": None}]
    assert _login(user_antes, "MinhaSenhaForte#1") == 200                # a senha dela funciona


def test_bridge_homonimas_pede_revisao_e_nao_funde_sozinho(db, escola_completa):
    """Achado MÉDIO: 'Maria Silva' + 'Maria Souza' + 'Maria Silva Souza' podem ser
    pessoas diferentes. São propostas como 'revisar', mas aplicar SEM confirmar
    (loser_ids vazio) não funde ninguém."""
    escola = escola_completa["escola"]
    db.add(Professor(escola_id=escola.id, nome="Maria Silva", email="m1@professor.constelaedu.com"))
    db.add(Professor(escola_id=escola.id, nome="Maria Souza", email="m2@professor.constelaedu.com"))
    db.add(Professor(escola_id=escola.id, nome="Maria Silva Souza", email="m3@professor.constelaedu.com"))
    db.commit()

    cands = P.plano_deduplicacao(db, escola.id)
    revisar = {c["apagar"] for c in cands if c["confianca"] == "revisar"}
    assert {"Maria Silva", "Maria Souza"} <= revisar   # sinalizadas, não fundidas
    assert P.aplicar_deduplicacao(db, escola.id, []) == []
    restantes = db.execute(
        select(Professor).where(Professor.escola_id == escola.id)).scalars().all()
    assert len(restantes) == 3                          # nada foi apagado


def test_gemeos_exatos_voltam_a_ser_oferecidos(db, escola_completa):
    """Duas contas com o MESMO nome completo (ex.: dupla criada numa corrida de
    import) voltam a poder ser unidas — confiança 'revisar'."""
    escola = escola_completa["escola"]
    db.add(Professor(escola_id=escola.id, nome="Maria Silva", email="ms1@professor.constelaedu.com"))
    db.add(Professor(escola_id=escola.id, nome="Maria Silva", email="ms2@professor.constelaedu.com"))
    db.commit()
    cands = P.plano_deduplicacao(db, escola.id)
    assert len(cands) == 1
    assert cands[0]["apagar"] == "Maria Silva" and cands[0]["manter"] == "Maria Silva"
    assert cands[0]["confianca"] == "revisar"


def test_username_em_uso_case_insensitive(db, escola_completa):
    """Achado MÉDIO: criar 'telmatestelli' ao lado de 'TelmaTestelli' quebraria o
    login (500). A checagem de disponibilidade é acento/caixa-insensível."""
    from app.routers.admin import _username_em_uso
    escola = escola_completa["escola"]
    db.add(Usuario(escola_id=escola.id, nome="P", email="tt@professor.constelaedu.com",
                   username="TelmaTestelli", senha_hash=hash_senha("x"), cargo="professor"))
    db.commit()
    assert _username_em_uso(db, "telmatestelli") is True
    assert _username_em_uso(db, "TELMATESTELLI") is True
    assert _username_em_uso(db, "outronome") is False


def test_padronizar_usernames_recaixa_usados_e_regenera_novos(db, escola_completa):
    """Padroniza o @ de TODAS as professoras: conta nunca usada ganha @ CamelCase
    + senha nova; conta já usada só re-caixa o @ (senha/sessão intactas)."""
    from datetime import datetime, timezone
    escola = escola_completa["escola"]
    nova = Professor(escola_id=escola.id, nome="Gabriela Mockelli",
                     email="gabrielamockelli@professor.constelaedu.com")
    usada = Professor(escola_id=escola.id, nome="Zuleide",
                      email="zuleide@professor.constelaedu.com")
    db.add_all([nova, usada])
    db.flush()
    db.add(Usuario(escola_id=escola.id, nome="Gabriela Mockelli", email=nova.email,
                   username="gabrielamockelli", senha_hash=hash_senha("x"), cargo="professor"))
    db.add(Usuario(escola_id=escola.id, nome="Zuleide", email=usada.email,
                   username="zuleide", senha_hash=hash_senha("SenhaDela#1"),
                   cargo="professor", ultimo_acesso=datetime.now(timezone.utc)))
    db.commit()

    folha = P.padronizar_usernames(db, escola.id)
    db.commit()

    # Nunca usada: @ CamelCase + senha nova (aleatória) na folha.
    gabriela = next(f for f in folha if f["nome"] == "Gabriela Mockelli")
    assert gabriela["usuario"] == "GabrielaMockelli"
    _senha_e_aleatoria(gabriela["senha"], "Gabriela Mockelli", "GabrielaMockelli")
    assert _login("GabrielaMockelli", gabriela["senha"]) == 200
    assert db.execute(select(Usuario).where(
        Usuario.username == "GabrielaMockelli")).scalar_one_or_none() is not None
    # Já usada: só re-caixa (senha mantida) e a senha dela continua entrando.
    u2 = db.execute(select(Usuario).where(Usuario.username == "Zuleide")).scalar_one()
    assert u2.username == "Zuleide"
    assert {"nome": "Zuleide", "usuario": "Zuleide", "senha": None} in folha
    assert _login("zuleide", "SenhaDela#1") == 200


def test_login_aceita_qualquer_caixa(db, escola_completa):
    escola = escola_completa["escola"]
    db.add(Usuario(escola_id=escola.id, nome="Teste Prof", email="t@professor.constelaedu.com",
                   username="TesteProf", senha_hash=hash_senha("segredo123"), cargo="professor"))
    db.commit()
    assert _login("testeprof", "segredo123") == 200
    assert _login("TESTEPROF", "segredo123") == 200
