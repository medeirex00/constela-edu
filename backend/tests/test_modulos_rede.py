"""MÓDULOS CONTRATADOS por rede (SaaS) — cenários A–F pedidos pelo dono.

Regras que estes testes travam:
  * ausência de configuração = módulo LIGADO (deploy não muda rede existente);
  * escola SEM rede = todos os módulos ligados;
  * módulo não contratado NÃO vira zero: ele some da média, do ranking e da API;
  * "contratado sem dados" ≠ "não contratado" — o primeiro continua valendo;
  * pesos.geral é redistribuído entre os módulos contratados (nota do aluno não
    cai pela metade numa rede de um módulo só).
"""
import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import (
    Aluno,
    Escola,
    Importacao,
    Matricula,
    ModuloRede,
    Nota,
    Rede,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
    Usuario,
)
from app.services import modulos as svc
from app.services import rede as svc_rede
from app.services import scoring


def _login(email: str, senha: str = "s3nh4") -> TestClient:
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _cenario(db, *, com_elefante=True, com_matific=True, alunos=6):
    """Rede + escola + alunos com snapshots das plataformas pedidas."""
    rede = Rede(nome="Rede Modulos", status="ativa")
    db.add(rede)
    db.flush()
    esc = Escola(nome="EM Modulos", ano_letivo_ativo=2026, rede_id=rede.id, status="ativa")
    db.add(esc)
    db.flush()
    turma = Turma(escola_id=esc.id, nome="1ºA", ano_escolar="1º Ano", ano_letivo=2026,
                  status="ativa")
    db.add(turma)
    db.flush()
    imp = Importacao(escola_id=esc.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    for i in range(alunos):
        a = Aluno(escola_id=esc.id, nome=f"Crianca {i}", status="ativo")
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=esc.id, aluno_id=a.id, turma_id=turma.id, ano_letivo=2026))
        if com_elefante:
            db.add(SnapshotElefante(escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
                                    livros_unicos=5 + i, tempo_leitura_min=60 + i * 10,
                                    questoes_tentativas=20, questoes_acertos=16))
        if com_matific:
            db.add(SnapshotMatific(escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
                                   atividades=20 + i, estrelas=100 + i * 10,
                                   pontuacao_media=4.0))
    db.add(Usuario(escola_id=None, nome="Secretaria", email="sec@mod.local",
                   senha_hash=hash_senha("s3nh4"), cargo="coordenador", rede_id=rede.id))
    db.add(Usuario(escola_id=esc.id, nome="Root", email="root@mod.local",
                   senha_hash=hash_senha("s3nh4"), cargo="admin", is_global=True))
    db.commit()
    # Notas AUTÊNTICAS pelo motor real (as médias da escola saem de `notas`).
    scoring.recalcular_escola(db, esc.id)
    return rede, esc


def _cartao(db, rede_id):
    return svc_rede._kpis_da_rede(db, rede_id)[0]


# --- Regra de ouro: sem configuração, tudo ligado ---------------------------

def test_sem_configuracao_todos_os_modulos_ligados(db):
    """A tabela nasce vazia: nenhuma rede existente muda de comportamento."""
    rede, _ = _cenario(db)
    assert svc.modulos_da_rede(db, rede.id) == {"leitura", "matematica"}


def test_escola_sem_rede_tem_todos_os_modulos(db, escola_completa):
    """Escola avulsa (rede_id nulo) é o estado padrão do sistema — segue inteira."""
    escola = escola_completa["escola"]
    assert escola.rede_id is None
    assert svc.modulos_da_escola(db, escola) == {"leitura", "matematica"}


# --- Cenário A: ambos contratados -------------------------------------------

def test_a_ambos_contratados(db):
    rede, _ = _cenario(db)
    c = _cartao(db, rede.id)
    assert set(c["modulos"]) == {"leitura", "matematica"}
    assert c["media_elefante"] > 0 and c["media_matific"] > 0
    assert c["dimensoes_com_dados"] == ["leitura", "matematica"]
    assert c["pontuacao_leitura"] > 0 and c["pontuacao_matematica"] > 0


# --- Cenário B: somente Elefante --------------------------------------------

def test_b_somente_elefante(db):
    """Matific desligado: some da média, do índice e da adoção — e a Geral NÃO
    é dividida por dois."""
    rede, _ = _cenario(db)
    svc.definir(db, rede.id, "matematica", False)
    db.commit()

    c = _cartao(db, rede.id)
    assert c["modulos"] == ["leitura"]
    assert c["dimensoes_com_dados"] == ["leitura"]
    assert c["media_matific"] == 0.0                      # não computado
    assert c["media_geral"] == c["media_elefante"]        # e NÃO metade
    assert c["pontuacao_matematica"] == 0.0
    assert c["pontuacao_geral"] == c["pontuacao_leitura"]


# --- Cenário C: somente Matific ---------------------------------------------

def test_c_somente_matific(db):
    rede, _ = _cenario(db)
    svc.definir(db, rede.id, "leitura", False)
    db.commit()

    c = _cartao(db, rede.id)
    assert c["modulos"] == ["matematica"]
    assert c["dimensoes_com_dados"] == ["matematica"]
    assert c["media_elefante"] == 0.0
    assert c["media_geral"] == c["media_matific"]
    assert c["pontuacao_geral"] == c["pontuacao_matematica"]


# --- Cenário D: contratado SEM dados ≠ não contratado -----------------------

def test_d_modulo_contratado_sem_dados_continua_contratado(db):
    """Matific contratado mas sem nenhuma importação: segue no plano (aparece na
    interface), e a Geral usa só a dimensão COM dados — sem virar 'não
    contratado'."""
    rede, _ = _cenario(db, com_matific=False)      # contratado, porém sem dados
    c = _cartao(db, rede.id)

    assert set(c["modulos"]) == {"leitura", "matematica"}   # CONTINUA contratado
    assert c["ativos_matific"] == 0                         # mas sem dados
    assert c["dimensoes_com_dados"] == ["leitura"]          # só leitura pontua
    assert c["media_geral"] == c["media_elefante"]
    # A diferença entre os dois estados é observável no payload:
    svc.definir(db, rede.id, "matematica", False)
    db.commit()
    assert _cartao(db, rede.id)["modulos"] == ["leitura"]   # agora, não contratado


# --- Cenário E: Admin Global liga/desliga -----------------------------------

def test_e_admin_global_altera_modulos_e_efeito_e_imediato(db):
    rede, _ = _cenario(db)
    root = _login("root@mod.local")

    antes = root.get(f"/api/v1/redes/{rede.id}/modulos").json()
    assert {m["chave"] for m in antes} == {"leitura", "matematica"}
    assert all(m["ativo"] for m in antes)

    r = root.put(f"/api/v1/redes/{rede.id}/modulos", json={"matematica": False})
    assert r.status_code == 200
    assert ({m["chave"]: m["ativo"] for m in r.json()["modulos"]}
            == {"leitura": True, "matematica": False})

    # A Secretaria recarrega e já vê a rede como só-Leitura.
    sec = _login("sec@mod.local")
    dash = sec.get(f"/api/v1/redes/{rede.id}/dashboard").json()
    assert dash["modulos"] == ["leitura"]
    assert dash["escolas"][0]["dimensoes_com_dados"] == ["leitura"]

    # E religar devolve o estado anterior.
    root.put(f"/api/v1/redes/{rede.id}/modulos", json={"matematica": True})
    dash = sec.get(f"/api/v1/redes/{rede.id}/dashboard").json()
    assert dash["modulos"] == ["leitura", "matematica"]


def test_e2_apenas_admin_global_altera(db):
    rede, _ = _cenario(db)
    sec = _login("sec@mod.local")
    assert sec.put(f"/api/v1/redes/{rede.id}/modulos", json={"leitura": False}).status_code == 403
    # …mas a Secretaria PODE ler o próprio plano (a interface precisa dele).
    assert sec.get(f"/api/v1/redes/{rede.id}/modulos").status_code == 200


def test_e3_modulo_desconhecido_e_recusado(db):
    rede, _ = _cenario(db)
    root = _login("root@mod.local")
    r = root.put(f"/api/v1/redes/{rede.id}/modulos", json={"astrologia": True})
    assert r.status_code == 400 and "desconhecido" in r.json()["detail"].lower()


# --- Cenário F: SEGURANÇA — API recusa módulo não contratado ----------------

def test_f_api_recusa_modulo_nao_contratado(db):
    """O frontend esconde, mas a trava é do servidor: digitar a URL não passa."""
    rede, esc = _cenario(db)
    svc.definir(db, rede.id, "matematica", False)
    db.commit()
    sec = _login("sec@mod.local")

    negado = sec.get(f"/api/v1/escolas/{esc.id}/matific")
    assert negado.status_code == 403 and "plano" in negado.json()["detail"].lower()
    assert sec.get(f"/api/v1/escolas/{esc.id}/ranking/matematica").status_code == 403
    # O módulo contratado continua acessível.
    assert sec.get(f"/api/v1/escolas/{esc.id}/elefante").status_code == 200


def test_f2_admin_global_tambem_respeita_o_plano_da_escola(db):
    """O admin global vê o catálogo inteiro, mas ao operar uma ESCOLA vale o
    plano da rede DAQUELA escola (senão ele furaria o isolamento por engano)."""
    rede, esc = _cenario(db)
    svc.definir(db, rede.id, "leitura", False)
    db.commit()
    root = _login("root@mod.local")
    assert root.get(f"/api/v1/escolas/{esc.id}/elefante").status_code == 403
    assert root.get(f"/api/v1/escolas/{esc.id}/matific").status_code == 200


# --- Renormalização dos pesos (nota do ALUNO) -------------------------------

def test_pesos_geral_redistribuidos_entre_modulos_contratados(db):
    """Rede só-Leitura: pesos.geral vira {elefante: 1,0} e a nota do aluno deixa
    de ser metade. Com os dois módulos, continua 50/50 (nada muda)."""
    rede, esc = _cenario(db)
    assert scoring.obter_pesos(db, esc.id, "pesos.geral") == {"matific": 0.5, "elefante": 0.5}

    svc.definir(db, rede.id, "matematica", False)
    db.commit()
    assert scoring.obter_pesos(db, esc.id, "pesos.geral") == {"elefante": 1.0}

    # E a nota gravada acompanha: geral passa a ser a própria nota de leitura.
    scoring.recalcular_escola(db, esc.id)
    nota = db.query(Nota).filter(Nota.escola_id == esc.id).first()
    assert nota.nota_geral == pytest.approx(nota.nota_elefante, abs=0.01)


def test_pesos_de_dentro_da_plataforma_nao_mudam(db):
    """A contratação só afeta a combinação ENTRE plataformas. Os pesos DENTRO de
    cada uma (livros/dificuldade/questões…) seguem intocados."""
    rede, esc = _cenario(db)
    antes = scoring.obter_pesos(db, esc.id, "pesos.elefante")
    svc.definir(db, rede.id, "matematica", False)
    db.commit()
    assert scoring.obter_pesos(db, esc.id, "pesos.elefante") == antes


# --- Recálculo automático ao mudar o contrato -------------------------------

def _notas_gravadas(db, escola_id) -> dict[int, tuple[float, float, float]]:
    """``{aluno_id: (geral, elefante, matific)}`` LIDO DO BANCO.

    ``expire_all`` é obrigatório: a mudança de contrato acontece na sessão do
    request (TestClient), não nesta — sem expirar, leríamos o cache antigo do
    mapa de identidade e o teste "passaria" sem provar nada."""
    db.expire_all()
    return {n.aluno_id: (n.nota_geral, n.nota_elefante, n.nota_matific)
            for n in db.query(Nota).filter(Nota.escola_id == escola_id)}


def test_recalculo_ciclo_completo_desligar_e_religar(db):
    """Os 8 passos do ciclo: dois módulos → desliga → recalcula → só o
    contratado → religa → recalcula → volta ao estado dos dois.

    O que está em jogo: a nota GRAVADA (a que o aluno, o ranking e o boletim
    mostram) precisa descrever o contrato vigente, não o de ontem."""
    # 1 e 2 — rede com os dois módulos e notas calculadas com os dois.
    rede, esc = _cenario(db)
    com_dois = _notas_gravadas(db, esc.id)
    assert com_dois, "o cenário precisa ter notas para o teste significar algo"
    for geral, ele, mat in com_dois.values():
        assert ele > 0 and mat > 0
        assert geral == pytest.approx(0.5 * ele + 0.5 * mat, abs=0.01)

    # 3 e 4 — o Admin Global desliga Matemática; o PUT recalcula sozinho.
    root = _login("root@mod.local")
    r = root.put(f"/api/v1/redes/{rede.id}/modulos", json={"matematica": False})
    assert r.status_code == 200, r.text
    rec = r.json()["recalculo"]
    assert rec["escolas"] == 1 and rec["falhas"] == []
    assert rec["alunos"] == len(com_dois)
    assert r.json()["de"] == ["leitura", "matematica"] and r.json()["para"] == ["leitura"]

    # 5 — as notas passam a refletir SÓ o módulo contratado.
    so_leitura = _notas_gravadas(db, esc.id)
    assert so_leitura != com_dois, "o recálculo não rodou: as notas não mudaram"
    for aluno_id, (geral, ele, mat) in so_leitura.items():
        assert geral == pytest.approx(ele, abs=0.01)      # Geral = Leitura
        assert ele == pytest.approx(com_dois[aluno_id][1], abs=0.01)  # a de leitura não muda
        assert mat == com_dois[aluno_id][2]  # o DADO do Matific continua lá (reversível)

    # 6 e 7 — religa; o PUT recalcula de novo.
    r = root.put(f"/api/v1/redes/{rede.id}/modulos", json={"matematica": True})
    assert r.status_code == 200 and r.json()["recalculo"]["falhas"] == []

    # 8 — volta exatamente ao estado dos dois módulos.
    assert _notas_gravadas(db, esc.id) == com_dois


def test_recalculo_e_idempotente(db):
    """Reenviar o mesmo pedido não muda nada nem duplica linha — é o que torna
    "tentar novamente" uma recuperação segura."""
    from app.models import ModuloRede

    rede, esc = _cenario(db)
    root = _login("root@mod.local")
    root.put(f"/api/v1/redes/{rede.id}/modulos", json={"matematica": False})
    uma_vez = _notas_gravadas(db, esc.id)
    linhas_nota = db.query(Nota).filter(Nota.escola_id == esc.id).count()

    for _ in range(2):
        assert root.put(f"/api/v1/redes/{rede.id}/modulos",
                        json={"matematica": False}).status_code == 200

    assert _notas_gravadas(db, esc.id) == uma_vez
    assert db.query(Nota).filter(Nota.escola_id == esc.id).count() == linhas_nota
    assert db.query(ModuloRede).filter(ModuloRede.rede_id == rede.id).count() == 1


def test_falha_no_recalculo_nao_derruba_as_outras_escolas_nem_o_contrato(db, monkeypatch):
    """Segurança da operação: se o recálculo de uma escola falhar,

    * as OUTRAS escolas ainda são recalculadas (uma escola ruim não trava a rede);
    * o CONTRATO continua gravado — ele é a fonte da verdade, as notas derivam
      dele; nunca sobra um contrato meio aplicado;
    * a resposta diz exatamente o que ficou para trás, e reenviar o mesmo pedido
      conserta.
    """
    rede, esc = _cenario(db)
    outra = Escola(nome="EM Segunda", ano_letivo_ativo=2026, rede_id=rede.id, status="ativa")
    db.add(outra)
    db.commit()

    original = scoring.recalcular_escola

    def quebra_na_primeira(sessao, escola_id):
        if escola_id == esc.id:
            raise RuntimeError("banco indisponível")
        return original(sessao, escola_id)

    monkeypatch.setattr(scoring, "recalcular_escola", quebra_na_primeira)
    root = _login("root@mod.local")
    r = root.put(f"/api/v1/redes/{rede.id}/modulos", json={"matematica": False})

    assert r.status_code == 200, r.text
    rec = r.json()["recalculo"]
    assert [f["escola_id"] for f in rec["falhas"]] == [esc.id]
    assert [x["escola_id"] for x in rec["recalculadas"]] == [outra.id]  # seguiu adiante

    db.expire_all()
    assert svc.modulos_da_rede(db, rede.id) == {"leitura"}  # contrato gravado
    nota = db.query(Nota).filter(Nota.escola_id == esc.id).first()
    assert nota.nota_geral != pytest.approx(nota.nota_elefante, abs=0.01)  # nota ATRASADA

    # Recuperação: o mesmo pedido de novo, agora sem a falha.
    monkeypatch.setattr(scoring, "recalcular_escola", original)
    r2 = root.put(f"/api/v1/redes/{rede.id}/modulos", json={"matematica": False})
    assert r2.status_code == 200 and r2.json()["recalculo"]["falhas"] == []
    db.expire_all()
    nota = db.query(Nota).filter(Nota.escola_id == esc.id).first()
    assert nota.nota_geral == pytest.approx(nota.nota_elefante, abs=0.01)


def test_recalculo_alcanca_todas_as_escolas_da_rede_e_so_elas(db):
    """A mudança vale para a rede inteira — e não encosta em escola de fora."""
    rede, esc = _cenario(db)
    avulsa = Escola(nome="EM Avulsa", ano_letivo_ativo=2026, status="ativa")  # sem rede
    db.add(avulsa)
    db.commit()

    root = _login("root@mod.local")
    rec = root.put(f"/api/v1/redes/{rede.id}/modulos",
                   json={"matematica": False}).json()["recalculo"]
    assert {x["escola_id"] for x in rec["recalculadas"]} == {esc.id}
    assert avulsa.id not in {x["escola_id"] for x in rec["recalculadas"]}
    # E a escola avulsa segue com os dois módulos (regra: sem rede = tudo ligado).
    assert svc.modulos_da_escola(db, avulsa) == {"leitura", "matematica"}


# --- Contrato vazio é recusado na borda -------------------------------------

def test_rede_nao_pode_ficar_sem_nenhum_modulo(db):
    """Zero módulos é um estado que o produto não sabe explicar: o contrato diria
    "nada contratado", mas `pesos.geral` cairia no fallback de segurança e o
    aluno continuaria recebendo nota das duas plataformas. Barrado na rota."""
    rede, esc = _cenario(db)
    root = _login("root@mod.local")

    r = root.put(f"/api/v1/redes/{rede.id}/modulos",
                 json={"leitura": False, "matematica": False})
    assert r.status_code == 400
    assert "pelo menos um módulo" in r.json()["detail"]
    # Nada foi gravado: o contrato continua inteiro.
    assert svc.modulos_da_rede(db, rede.id) == {"leitura", "matematica"}

    # Também barra o pedido que APAGA o último módulo restante.
    assert root.put(f"/api/v1/redes/{rede.id}/modulos",
                    json={"matematica": False}).status_code == 200
    r = root.put(f"/api/v1/redes/{rede.id}/modulos", json={"leitura": False})
    assert r.status_code == 400
    db.expire_all()
    assert svc.modulos_da_rede(db, rede.id) == {"leitura"}

    # E desligar um, mantendo o outro, segue permitido.
    assert root.put(f"/api/v1/redes/{rede.id}/modulos",
                    json={"leitura": True, "matematica": False}).status_code == 200


def test_resultado_do_contrato_simula_sem_gravar(db):
    rede, _ = _cenario(db)
    assert svc.resultado_do_contrato(db, rede.id, {}) == {"leitura", "matematica"}
    assert svc.resultado_do_contrato(db, rede.id, {"matematica": False}) == {"leitura"}
    assert svc.resultado_do_contrato(db, rede.id, {"leitura": False, "matematica": False}) == set()
    # Simulação PURA: nada foi para o banco.
    assert db.query(ModuloRede).filter(ModuloRede.rede_id == rede.id).count() == 0


# --- Corrida na PRIMEIRA criação da linha -----------------------------------

def test_corrida_de_criacao_vira_update_em_vez_de_500(db, monkeypatch):
    """Dois admins mexendo no MESMO módulo pela primeira vez: os dois leem "não
    existe" e os dois tentam inserir. O índice único barra o segundo — e antes
    isso derrubava a requisição inteira (500) sem aplicar nada.

    Aqui reproduzimos exatamente o estado do PERDEDOR: a linha já existe no
    banco, mas a nossa leitura (obsoleta) diz que não. O esperado é o pedido ser
    aplicado assim mesmo, virando UPDATE."""
    rede, _ = _cenario(db)
    svc.definir(db, rede.id, "matematica", True)   # o "vencedor" criou a linha
    db.commit()

    execute_real = db.execute
    ja_enganou = []

    class _LeituraObsoleta:
        """O resultado REAL, só que a primeira leitura diz "não achei"."""

        def __init__(self, real):
            self._real = real

        def scalar_one_or_none(self):
            return None

        def __getattr__(self, nome):
            return getattr(self._real, nome)

    def execute_com_leitura_obsoleta(*args, **kwargs):
        resultado = execute_real(*args, **kwargs)
        if not ja_enganou:
            ja_enganou.append(True)
            return _LeituraObsoleta(resultado)
        return resultado

    monkeypatch.setattr(db, "execute", execute_com_leitura_obsoleta)
    linha = svc.definir(db, rede.id, "matematica", False)
    assert linha.ativo is False                     # o pedido do perdedor VALEU
    monkeypatch.undo()
    db.commit()
    db.expire_all()
    assert svc.modulos_da_rede(db, rede.id) == {"leitura"}
    assert db.query(ModuloRede).filter(
        ModuloRede.rede_id == rede.id, ModuloRede.modulo == "matematica").count() == 1


# --- Regressão: dashboard_global não quebra (decisão adiada pelo dono) ------

def test_dashboard_global_nao_quebra_com_modulos_heterogeneos(db):
    """O dono decidiu NÃO mudar a fórmula do painel global agora. Este teste só
    garante que módulos heterogêneos não o quebram.

    COMPORTAMENTO ATUAL DOCUMENTADO: `dashboard_global` consolida TODAS as redes
    numa média ponderada única (media_geral/matific/elefante), sem olhar módulos.
    Com redes de módulos diferentes, essa média mistura bases distintas — uma
    rede só-Leitura entra na média de matemática com 0. Não é erro de código; é
    uma decisão de produto em aberto."""
    rede, _ = _cenario(db)
    svc.definir(db, rede.id, "matematica", False)
    db.commit()

    g = svc_rede.dashboard_global(db)
    assert g["totais"]["redes"] >= 1
    assert isinstance(g["totais"]["media_geral"], float)      # não estoura
    assert g["redes"] and g["top_escolas"] is not None
