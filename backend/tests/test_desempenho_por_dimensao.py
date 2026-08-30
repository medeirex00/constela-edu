"""DESEMPENHO POR DIMENSÃO — Leitura e Matemática, cada uma com a sua ordem.

Arquitetura 2 (`docs/spec-arquitetura-2.md`): não existe mais ordem única entre
dimensões diferentes. O aluno é medido em cada matéria pelo que ele faz NAQUELA
matéria, e quem não tem dado sai da ordenação daquela dimensão — sem virar zero
e sem sumir da tela.

Estes testes travam mecanicamente as garantias que sustentam a arquitetura:

  * ISOLAMENTO — abrir a 2ª plataforma não muda a nota da 1ª nem por um
    centésimo, INCLUSIVE pela régua de normalização (o canal que existia era o
    tamanho da amostra, contado para as duas dimensões de uma vez);
  * AUSÊNCIA ≠ ZERO — sem snapshot, o aluno fica fora do ranking daquela
    dimensão e aparece na lista de "ainda não aferidos";
  * SNAPSHOT ZERADO ≠ AUSÊNCIA — quem abriu e ainda não produziu entra, em
    último, com 0,00 (zero legítimo), e pesa na média;
  * DESEMPATE LOCAL — a medalha de Leitura não pode ser decidida pela nota de
    Matemática;
  * a média da ESCOLA mede desempenho, não desempenho × cobertura.
"""
import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import (
    Aluno,
    Configuracao,
    Escola,
    Importacao,
    Matricula,
    NivelDificuldade,
    Nota,
    Rede,
    ReferenciaNormalizacao,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
    Usuario,
)
from app.services import modulos as svc_modulos
from app.services import scoring

LEITOR = {"livros_unicos": 30, "tempo_leitura_min": 600,
          "questoes_tentativas": 100, "questoes_acertos": 100,
          "livros_por_nivel": {"D": 30}}
LEITOR_FRACO = {"livros_unicos": 4, "tempo_leitura_min": 60,
                "questoes_tentativas": 20, "questoes_acertos": 10,
                "livros_por_nivel": {"D": 4}}
MATIFIC_TOPO = {"atividades": 100, "pontuacao_media": 5.0, "estrelas": 300}
MATIFIC_FRACO = {"atividades": 10, "pontuacao_media": 2.0, "estrelas": 20}
ELEFANTE_ZERADO = {"livros_unicos": 0, "tempo_leitura_min": 0,
                   "questoes_tentativas": 0, "questoes_acertos": 0,
                   "livros_por_nivel": {}}


def montar_escola(db, *, com_rede=False):
    rede = None
    if com_rede:
        rede = Rede(nome="Rede Dimensao", status="ativa")
        db.add(rede)
        db.flush()
    escola = Escola(nome="EM DIMENSAO", ano_letivo_ativo=2026, status="ativa",
                    rede_id=rede.id if rede else None)
    db.add(escola)
    db.flush()
    for namespace, valores in scoring.PESOS_PADRAO.items():
        db.add(Configuracao(escola_id=escola.id, namespace=namespace,
                            chave="valores", valor=valores))
    db.add(NivelDificuldade(escola_id=escola.id, nome="Nível 2", codigo="nivel_2",
                            codigos=["D", "E"], pontos_padrao=4.0, ordem=1))
    db.add(ReferenciaNormalizacao(escola_id=escola.id, modo="auto"))
    turma = Turma(escola_id=escola.id, nome="4ºA", ano_escolar="4º Ano",
                  ano_letivo=2026, status="ativa")
    db.add(turma)
    db.add(Usuario(escola_id=escola.id, nome="Gestora", email="gestora@dim.local",
                   senha_hash=hash_senha("s3nh4gestora"), cargo="coordenador"))
    db.flush()
    importacao = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(importacao)
    db.flush()
    return rede, escola, turma, importacao


def novo_aluno(db, escola, turma, imp, nome, *, elefante=None, matific=None):
    aluno = Aluno(escola_id=escola.id, nome=nome, status="ativo")
    db.add(aluno)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id, turma_id=turma.id,
                     ano_letivo=2026))
    if elefante is not None:
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id,
                                importacao_id=imp.id, **elefante))
    if matific is not None:
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id,
                               importacao_id=imp.id, **matific))
    return aluno


def notas_por_id(db, escola_id):
    return {n.aluno_id: n for n in db.query(Nota).filter(Nota.escola_id == escola_id)}


def logar(email="gestora@dim.local", senha="s3nh4gestora"):
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def ranking(cliente, escola_id, dimensao):
    r = cliente.get(f"/api/v1/escolas/{escola_id}/ranking?dimensao={dimensao}")
    assert r.status_code == 200, r.text
    return r.json()


# --- Quem aparece em cada ranking --------------------------------------------

def test_so_elefante_aparece_em_leitura_e_nao_em_matematica(db):
    """A criança que só lê compete em Leitura, com quem lê. Em Matemática ela
    não é última com 0,0 — ela simplesmente não está na lista."""
    _, escola, turma, imp = montar_escola(db)
    so_le = novo_aluno(db, escola, turma, imp, "Leitora Pura", elefante=dict(LEITOR))
    for i in range(4):
        novo_aluno(db, escola, turma, imp, f"Colega {i}",
                   elefante=dict(LEITOR_FRACO), matific=dict(MATIFIC_FRACO))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    cliente = logar()

    leitura = ranking(cliente, escola.id, "leitura")
    assert [i["nome"] for i in leitura][0] == "Leitora Pura"
    assert all(i["aferido"] for i in leitura)
    assert {i["n_aferidos"] for i in leitura} == {5}

    matematica = ranking(cliente, escola.id, "matematica")
    assert so_le.id not in [i["aluno_id"] for i in matematica]
    assert {i["n_aferidos"] for i in matematica} == {4}


def test_so_matific_aparece_em_matematica_e_nao_em_leitura(db):
    _, escola, turma, imp = montar_escola(db)
    so_conta = novo_aluno(db, escola, turma, imp, "Matematico Puro",
                          matific=dict(MATIFIC_TOPO))
    for i in range(4):
        novo_aluno(db, escola, turma, imp, f"Colega {i}",
                   elefante=dict(LEITOR_FRACO), matific=dict(MATIFIC_FRACO))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    cliente = logar()

    matematica = ranking(cliente, escola.id, "matematica")
    assert [i["nome"] for i in matematica][0] == "Matematico Puro"
    assert so_conta.id not in [i["aluno_id"] for i in ranking(cliente, escola.id, "leitura")]


def test_quem_usa_as_duas_aparece_nos_dois_rankings_com_posicoes_proprias(db):
    """As duas posições são verdade ao mesmo tempo; nenhuma média precisa
    escondê-las. É o caso "Íris": última em Leitura, pódio em Matemática."""
    _, escola, turma, imp = montar_escola(db)
    iris = novo_aluno(db, escola, turma, imp, "Iris Faria",
                      elefante=dict(LEITOR_FRACO), matific=dict(MATIFIC_TOPO))
    for i in range(4):
        novo_aluno(db, escola, turma, imp, f"Colega {i}",
                   elefante=dict(LEITOR), matific=dict(MATIFIC_FRACO))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    cliente = logar()

    def posicao_de(dimensao):
        return next(i["posicao"] for i in ranking(cliente, escola.id, dimensao)
                    if i["aluno_id"] == iris.id)

    assert posicao_de("matematica") == 1     # o topo da matemática
    assert posicao_de("leitura") == 5        # e o fim da leitura
    nota = notas_por_id(db, escola.id)[iris.id]
    assert nota.aferido_leitura and nota.aferido_matematica
    assert nota.posicao_matematica == 1 and nota.posicao_leitura == 5


# --- Ausência não é zero ------------------------------------------------------

def test_sem_snapshot_nao_recebe_zero_fica_nao_aferido(db):
    """O corte é a EXISTÊNCIA do snapshot. Sem ele: `aferido=False`, posição
    NULA e nota `null` no detalhamento — nunca o valor 0,0."""
    _, escola, turma, imp = montar_escola(db)
    ninguem = novo_aluno(db, escola, turma, imp, "Nunca Alcancada")
    novo_aluno(db, escola, turma, imp, "Com Dado", elefante=dict(LEITOR),
               matific=dict(MATIFIC_TOPO))
    db.commit()
    scoring.recalcular_escola(db, escola.id)

    nota = notas_por_id(db, escola.id)[ninguem.id]
    assert (nota.aferido_leitura, nota.aferido_matematica) == (False, False)
    assert (nota.posicao_leitura, nota.posicao_matematica) == (None, None)
    for dimensao in ("leitura", "matematica"):
        detalhe = nota.detalhes["dimensoes"][dimensao]
        assert detalhe["aferido"] is False
        assert detalhe["nota"] is None, "ausência tem de ser `—`, não 0,0"
        assert detalhe["posicao"] is None
    assert nota.detalhes["adocao"]["pct"] == 0.0

    cliente = logar()
    for dimensao in ("leitura", "matematica"):
        assert ninguem.id not in [i["aluno_id"]
                                  for i in ranking(cliente, escola.id, dimensao)]


def test_zero_legitimo_entra_no_ranking_da_dimensao_em_ultimo(db):
    """Snapshot zerado NÃO é ausência: quem abriu a plataforma e ainda não
    produziu tem um zero legítimo, aparece em último e pesa na média."""
    _, escola, turma, imp = montar_escola(db)
    zerado = novo_aluno(db, escola, turma, imp, "Abriu E Nao Leu",
                        elefante=dict(ELEFANTE_ZERADO))
    for i in range(3):
        novo_aluno(db, escola, turma, imp, f"Colega {i}", elefante=dict(LEITOR))
    db.commit()
    scoring.recalcular_escola(db, escola.id)

    nota = notas_por_id(db, escola.id)[zerado.id]
    assert nota.aferido_leitura is True
    assert nota.nota_elefante == 0.0
    assert nota.posicao_leitura == 4              # entra, em último
    assert nota.detalhes["dimensoes"]["leitura"]["nota"] == 0.0

    leitura = ranking(logar(), escola.id, "leitura")
    assert leitura[-1]["aluno_id"] == zerado.id
    assert leitura[-1]["nota"] == 0.0


def test_sem_dado_numa_dimensao_nao_penaliza_a_outra(db):
    """Duas crianças com a MESMA leitura têm a MESMA nota e ficam empatadas no
    topo de Leitura — mesmo que só uma delas use o Matific. É o "paradoxo do par
    gêmeo" (Ana 1ª × Alice 11ª) desaparecendo."""
    _, escola, turma, imp = montar_escola(db)
    ana = novo_aluno(db, escola, turma, imp, "Ana Clara", elefante=dict(LEITOR))
    alice = novo_aluno(db, escola, turma, imp, "Alice Ramos", elefante=dict(LEITOR),
                       matific=dict(MATIFIC_FRACO))
    for i in range(3):
        novo_aluno(db, escola, turma, imp, f"Colega {i}",
                   elefante=dict(LEITOR_FRACO), matific=dict(MATIFIC_TOPO))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    notas = notas_por_id(db, escola.id)

    assert notas[ana.id].nota_elefante == notas[alice.id].nota_elefante
    assert {notas[ana.id].posicao_leitura, notas[alice.id].posicao_leitura} == {1, 2}


# --- ISOLAMENTO: a garantia central ------------------------------------------

def test_abrir_o_matific_nao_altera_a_nota_de_leitura_de_ninguem(db):
    """A catraca do item 6: `nota_elefante` é função EXCLUSIVA de dado do
    Elefante — inclusive da régua de normalização.

    O canal que existia era o TAMANHO DA AMOSTRA: ele era contado como
    `max(alunos_matific, alunos_elefante)` e decidia, para as DUAS dimensões, se
    a escola usava a régua robusta (P90 + saturação) ou a simples (máximo). Com
    3 leitores e 10 alunos no Matific, os 10 do Matific ligavam a régua robusta
    da LEITURA e mudavam a nota de quem nunca abriu o Matific.
    """
    _, escola, turma, imp = montar_escola(db)
    leitores = [
        novo_aluno(db, escola, turma, imp, f"Leitor {i}",
                   elefante={**LEITOR, "livros_unicos": livros,
                             "livros_por_nivel": {"D": livros},
                             "tempo_leitura_min": livros * 20,
                             "questoes_tentativas": livros * 3,
                             "questoes_acertos": livros * 2})
        for i, livros in enumerate((10, 20, 40))
    ]
    outros = [novo_aluno(db, escola, turma, imp, f"Outro {i}") for i in range(7)]
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    antes = {aid: n.nota_elefante for aid, n in notas_por_id(db, escola.id).items()}
    posicoes_antes = {aid: n.posicao_leitura
                      for aid, n in notas_por_id(db, escola.id).items()}

    # Agora TODA a escola (10 alunos, inclusive os 3 leitores) passa a usar o
    # Matific. Nada de leitura mudou.
    for indice, aluno in enumerate(leitores + outros):
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id,
                               importacao_id=imp.id, atividades=10 + indice * 7,
                               pontuacao_media=3.0, estrelas=30 + indice * 11))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    depois = notas_por_id(db, escola.id)

    for aluno_id, nota_antes in antes.items():
        assert depois[aluno_id].nota_elefante == nota_antes, (
            "adotar o Matific mexeu na nota de LEITURA — o isolamento entre "
            "dimensões quebrou")
        assert depois[aluno_id].posicao_leitura == posicoes_antes[aluno_id]
    # E o Matific de fato entrou (senão o teste passaria por não ter feito nada).
    assert all(n.aferido_matematica for n in depois.values())


def test_abrir_o_elefante_nao_altera_a_nota_de_matematica_de_ninguem(db):
    """O simétrico: `nota_matific` é função exclusiva de dado do Matific."""
    _, escola, turma, imp = montar_escola(db)
    contas = [
        novo_aluno(db, escola, turma, imp, f"Conta {i}",
                   matific={"atividades": ativ, "pontuacao_media": 3.0,
                            "estrelas": ativ * 3})
        for i, ativ in enumerate((10, 20, 40))
    ]
    outros = [novo_aluno(db, escola, turma, imp, f"Outro {i}") for i in range(7)]
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    antes = {aid: n.nota_matific for aid, n in notas_por_id(db, escola.id).items()}

    for indice, aluno in enumerate(contas + outros):
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id,
                                importacao_id=imp.id, livros_unicos=3 + indice * 2,
                                tempo_leitura_min=50 + indice * 10,
                                questoes_tentativas=10 + indice,
                                questoes_acertos=5 + indice,
                                livros_por_nivel={"D": 3 + indice * 2}))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    depois = notas_por_id(db, escola.id)

    for aluno_id, nota_antes in antes.items():
        assert depois[aluno_id].nota_matific == nota_antes, (
            "adotar o Elefante mexeu na nota de MATEMÁTICA")
    assert all(n.aferido_leitura for n in depois.values())


def test_referencias_de_uma_dimensao_nao_dependem_da_outra(db):
    """O mesmo isolamento, medido direto na régua: as referências de leitura
    são idênticas com e sem uma escola inteira no Matific."""
    _, escola, turma, imp = montar_escola(db)
    for i, livros in enumerate((10, 20, 40)):
        novo_aluno(db, escola, turma, imp, f"Leitor {i}",
                   elefante={**LEITOR, "livros_unicos": livros,
                             "livros_por_nivel": {"D": livros}})
    for i in range(7):
        novo_aluno(db, escola, turma, imp, f"Outro {i}")
    db.commit()
    refs_antes, _, k_antes = scoring.contexto_normalizacao(db, escola.id)

    for i in range(10):
        aluno = db.query(Aluno).filter(Aluno.escola_id == escola.id).all()[i]
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id,
                               importacao_id=imp.id, atividades=10 + i,
                               pontuacao_media=3.0, estrelas=20 + i))
    db.commit()
    refs_depois, _, k_depois = scoring.contexto_normalizacao(db, escola.id)

    for chave in ("max_livros", "max_tempo", "max_tentativas", "max_acertos",
                  "max_pontos_dificuldade"):
        assert refs_antes[chave] == refs_depois[chave], f"régua de leitura mudou: {chave}"
    for indicador in ("livros", "tempo", "tentativas"):
        assert k_antes.get(indicador) == k_depois.get(indicador)


# --- Desempate LOCAL à dimensão ----------------------------------------------

def test_desempate_de_leitura_nao_olha_a_nota_de_matematica(db):
    """Empate na nota de Leitura decide-se por dificuldade/livros/acertos —
    nunca pela matemática. Senão a medalha de leitura seria dada pela conta."""
    _, escola, turma, imp = montar_escola(db)
    # Mesma leitura (mesmos livros/tempo/questões) → empate na nota de Leitura.
    leitura_igual = {"livros_unicos": 10, "tempo_leitura_min": 200,
                     "questoes_tentativas": 40, "questoes_acertos": 40,
                     "livros_por_nivel": {"D": 10}}
    fraco_na_conta = novo_aluno(db, escola, turma, imp, "Aaa Empatada",
                                elefante=dict(leitura_igual),
                                matific=dict(MATIFIC_FRACO))
    forte_na_conta = novo_aluno(db, escola, turma, imp, "Zzz Empatada",
                                elefante=dict(leitura_igual),
                                matific=dict(MATIFIC_TOPO))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    notas = notas_por_id(db, escola.id)

    assert notas[fraco_na_conta.id].nota_elefante == notas[forte_na_conta.id].nota_elefante
    assert notas[fraco_na_conta.id].nota_matific < notas[forte_na_conta.id].nota_matific
    # Empatados em tudo o que é leitura → decide o NOME (critério local), e não
    # a nota de matemática: quem tem o nome menor vem primeiro.
    assert notas[fraco_na_conta.id].posicao_leitura == 1
    assert notas[forte_na_conta.id].posicao_leitura == 2


def test_ranking_de_leitura_nao_muda_quando_a_nota_de_matematica_muda(db):
    _, escola, turma, imp = montar_escola(db)
    alunos = [novo_aluno(db, escola, turma, imp, f"Aluno {i}",
                         elefante={**LEITOR, "livros_unicos": 5 + i,
                                   "livros_por_nivel": {"D": 5 + i}},
                         matific=dict(MATIFIC_FRACO))
              for i in range(6)]
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    ordem_antes = [n.aluno_id for n in sorted(
        notas_por_id(db, escola.id).values(), key=lambda n: n.posicao_leitura)]

    # Inverte completamente o desempenho em matemática.
    for indice, aluno in enumerate(alunos):
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id,
                               importacao_id=imp.id, atividades=500 - indice * 50,
                               pontuacao_media=5.0, estrelas=900 - indice * 90))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    ordem_depois = [n.aluno_id for n in sorted(
        notas_por_id(db, escola.id).values(), key=lambda n: n.posicao_leitura)]

    assert ordem_antes == ordem_depois


# --- Visão operacional de NÃO AFERIDOS ---------------------------------------

def test_nao_aferidos_lista_quem_falta_em_cada_dimensao_e_em_nenhuma(db):
    """Ao sair do ranking, a criança sem dado não pode sumir: ela é justamente
    quem a coordenação precisa ver. Sem nota e sem posição — é lista de ação."""
    _, escola, turma, imp = montar_escola(db)
    novo_aluno(db, escola, turma, imp, "Usa As Duas", elefante=dict(LEITOR),
               matific=dict(MATIFIC_TOPO))
    so_leitura = novo_aluno(db, escola, turma, imp, "So Leitura",
                            elefante=dict(LEITOR_FRACO))
    so_conta = novo_aluno(db, escola, turma, imp, "So Conta",
                          matific=dict(MATIFIC_FRACO))
    nenhuma = novo_aluno(db, escola, turma, imp, "Nenhuma Plataforma")
    db.commit()
    scoring.recalcular_escola(db, escola.id)

    r = logar().get(f"/api/v1/escolas/{escola.id}/nao-aferidos")
    assert r.status_code == 200, r.text
    dados = r.json()
    assert dados["total_alunos"] == 4
    assert dados["contratadas"] == ["leitura", "matematica"]
    por_dimensao = {d["dimensao"]: d for d in dados["dimensoes"]}
    # Ordenada por turma e nome — é lista de trabalho, não de classificação.
    assert [a["nome"] for a in por_dimensao["leitura"]["alunos"]] == [
        "Nenhuma Plataforma", "So Conta"]
    assert {a["aluno_id"] for a in por_dimensao["leitura"]["alunos"]} == {
        so_conta.id, nenhuma.id}
    assert {a["aluno_id"] for a in por_dimensao["matematica"]["alunos"]} == {
        so_leitura.id, nenhuma.id}
    assert por_dimensao["leitura"]["n_aferidos"] == 2
    assert [a["aluno_id"] for a in dados["sem_nenhuma"]] == [nenhuma.id]
    # Operacional, não competitivo: nem nota nem posição na resposta.
    assert set(dados["sem_nenhuma"][0]) == {"aluno_id", "nome", "turma", "ano_escolar"}


def test_nao_aferidos_inclui_aluno_que_nunca_entrou_num_recalculo(db):
    """Sem recálculo não existe linha em `notas` — e é exatamente esse aluno que
    mais precisa aparecer. A consulta parte das MATRÍCULAS, não das notas."""
    _, escola, turma, imp = montar_escola(db)
    novato = novo_aluno(db, escola, turma, imp, "Recem Matriculado")
    db.commit()

    dados = logar().get(f"/api/v1/escolas/{escola.id}/nao-aferidos").json()
    assert [a["aluno_id"] for a in dados["sem_nenhuma"]] == [novato.id]


def test_secretaria_nao_ve_nomes_na_lista_de_nao_aferidos(db):
    """PII: a Secretaria agrega a rede e NUNCA enxerga criança individual. O
    mesmo mecanismo do ranking (turmas permitidas vazias) vale aqui."""
    rede, escola, turma, imp = montar_escola(db, com_rede=True)
    novo_aluno(db, escola, turma, imp, "Crianca Real")
    db.add(Usuario(nome="Secretaria", email="sec@dim.gov",
                   senha_hash=hash_senha("s3nh4secretar"), cargo="coordenador",
                   rede_id=rede.id))
    db.commit()

    sec = logar("sec@dim.gov", "s3nh4secretar")
    dados = sec.get(f"/api/v1/escolas/{escola.id}/nao-aferidos").json()
    assert dados["sem_nenhuma"] == [] and dados["total_alunos"] == 0
    assert all(d["alunos"] == [] for d in dados["dimensoes"])


# --- Contrato antes de dado ---------------------------------------------------

def test_modulo_nao_contratado_nao_tem_ranking_nem_lista_de_nao_aferidos(db):
    """Cascata CONTRATO → DADO: ninguém é 'não aferido' num produto que a rede
    não comprou, e o ranking daquela dimensão responde 403 (não 404)."""
    rede, escola, turma, imp = montar_escola(db, com_rede=True)
    novo_aluno(db, escola, turma, imp, "Usa As Duas", elefante=dict(LEITOR),
               matific=dict(MATIFIC_TOPO))
    db.commit()
    svc_modulos.definir(db, rede.id, "matematica", False)
    db.commit()
    scoring.recalcular_escola(db, escola.id)

    nota = notas_por_id(db, escola.id).popitem()[1]
    assert nota.aferido_leitura is True
    assert nota.aferido_matematica is False       # contratada? não. logo, não existe
    assert nota.detalhes["dimensoes"]["matematica"]["contratada"] is False
    assert nota.detalhes["adocao"] == {"contratadas": ["leitura"],
                                       "com_dados": ["leitura"], "pct": 100.0}

    cliente = logar()
    assert cliente.get(
        f"/api/v1/escolas/{escola.id}/ranking?dimensao=matematica").status_code == 403
    assert len(ranking(cliente, escola.id, "leitura")) == 1
    dados = cliente.get(f"/api/v1/escolas/{escola.id}/nao-aferidos").json()
    assert dados["contratadas"] == ["leitura"]
    assert [d["dimensao"] for d in dados["dimensoes"]] == ["leitura"]


def test_dimensao_invalida_e_400(db):
    _, escola, _, _ = montar_escola(db)
    db.commit()
    r = logar().get(f"/api/v1/escolas/{escola.id}/ranking?dimensao=historia")
    assert r.status_code == 400


# --- Média da escola: desempenho, não desempenho × cobertura -----------------

def test_media_da_escola_ignora_ausencia_mas_conta_o_zero_legitimo(db):
    """`media_leitura` é a média de QUEM LÊ. Quem não tem snapshot fica de fora
    (nunca houve o que medir); quem abriu e produziu zero entra e pesa."""
    _, escola, turma, imp = montar_escola(db)
    novo_aluno(db, escola, turma, imp, "Le Bem", elefante=dict(LEITOR))
    novo_aluno(db, escola, turma, imp, "Abriu E Nao Leu",
               elefante=dict(ELEFANTE_ZERADO))
    novo_aluno(db, escola, turma, imp, "Nunca Alcancada")
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    notas = notas_por_id(db, escola.id)

    dash = logar().get(f"/api/v1/escolas/{escola.id}/dashboard").json()
    esperado = round(sum(n.nota_elefante for n in notas.values()
                         if n.aferido_leitura) / 2, 1)
    assert dash["alunos_com_dado_leitura"] == 2     # o zero legítimo conta
    assert dash["media_leitura"] == esperado
    assert dash["media_leitura"] > 0                # não foi diluída pelo ausente
    # Alcance e "ainda não aferidos" são a outra metade da história.
    assert dash["total_alunos"] == 3
    assert dash["alcance"] == round(2 / 3 * 100, 1)
    assert dash["nao_aferidos"] == 1


def test_media_da_escola_bate_com_a_do_cartao_da_rede(db):
    """A MESMA escola exibia dois números chamados 'média geral': o painel da
    escola com os zeros de quem não tem dado, o cartão da rede sem eles. Agora é
    a mesma régua nos dois — a divergência era um defeito, não uma opção."""
    from app.services import rede as svc_rede

    rede, escola, turma, imp = montar_escola(db, com_rede=True)
    novo_aluno(db, escola, turma, imp, "Le E Conta", elefante=dict(LEITOR),
               matific=dict(MATIFIC_TOPO))
    novo_aluno(db, escola, turma, imp, "So Le", elefante=dict(LEITOR_FRACO))
    novo_aluno(db, escola, turma, imp, "Sem Nada")
    db.commit()
    scoring.recalcular_escola(db, escola.id)

    dash = logar().get(f"/api/v1/escolas/{escola.id}/dashboard").json()
    cartao = next(c for c in svc_rede._kpis_da_rede(db, rede.id)
                  if c["escola_id"] == escola.id)
    assert dash["media_geral"] == cartao["media_geral"]
    assert dash["media_leitura"] == cartao["media_elefante"]
    assert dash["media_matematica"] == cartao["media_matific"]
    assert dash["alunos_com_dado_leitura"] == cartao["alunos_com_nota_elefante"]


# --- Carimbos de auditoria ----------------------------------------------------

def test_detalhes_carimba_dimensao_dados_adocao_e_regra(db):
    """`detalhes` passa a responder, por dimensão: aferido, nota, posição,
    denominador, DATA do snapshot e os dados brutos que sustentam a nota. Mais o
    carimbo da regra, que é como se detecta escola ainda não recalculada."""
    _, escola, turma, imp = montar_escola(db)
    aluno = novo_aluno(db, escola, turma, imp, "Auditavel", elefante=dict(LEITOR),
                       matific=dict(MATIFIC_TOPO))
    # Este teste audita a régua CONFIGURÁVEL da escola (o NivelDificuldade custom
    # de `montar_escola`, pontos_padrao=4.0 → 30 livros = 120,0). No modo padrão
    # (institucional) a dificuldade custom é ignorada (A3), então marcamos a
    # escola como PERSONALIZADA para restaurar o carimbo de dados que o teste afere.
    db.add(Configuracao(escola_id=escola.id, namespace="scoring.perfil",
                        chave="modo", valor="personalizado"))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    nota = notas_por_id(db, escola.id)[aluno.id]

    assert nota.detalhes["composicao"] == "por_dimensao_v1"
    leitura = nota.detalhes["dimensoes"]["leitura"]
    assert leitura["plataforma"] == "elefante"
    assert leitura["aferido"] is True
    assert leitura["nota"] == nota.nota_elefante
    assert leitura["posicao"] == 1 and leitura["n_aferidos"] == 1
    assert leitura["snapshot_em"] is not None
    assert leitura["dados"]["livros_unicos"] == 30
    assert leitura["dados"]["pontos_dificuldade"] == pytest.approx(120.0)
    matematica = nota.detalhes["dimensoes"]["matematica"]
    assert matematica["dados"]["atividades"] == 100
    assert matematica["dados"]["estrelas"] == 300
    assert nota.detalhes["adocao"]["pct"] == 100.0


def test_ranking_de_dimensao_entrega_dados_e_adocao_por_item(db):
    _, escola, turma, imp = montar_escola(db)
    novo_aluno(db, escola, turma, imp, "So Le", elefante=dict(LEITOR))
    db.commit()
    scoring.recalcular_escola(db, escola.id)

    item = ranking(logar(), escola.id, "leitura")[0]
    assert item["dimensao"] == "leitura"
    assert item["nota"] == item["nota_elefante"]
    assert item["dados"]["livros_unicos"] == 30
    assert item["n_aferidos"] == 1
    assert item["adocao"] == 50.0            # usa 1 das 2 dimensões contratadas
    assert item["snapshot_em"] is not None


# --- Ranking de VOLUME por período: intocado ---------------------------------

def test_ranking_de_volume_por_periodo_continua_existindo(db):
    """`/ranking/leitura` e `/ranking/matematica` são os rankings de VOLUME NO
    PERÍODO (base das premiações). A rota de desempenho por dimensão é
    `?dimensao=`, justamente para não destruí-los."""
    _, escola, turma, imp = montar_escola(db)
    novo_aluno(db, escola, turma, imp, "Leitora", elefante=dict(LEITOR))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    cliente = logar()

    volume = cliente.get(f"/api/v1/escolas/{escola.id}/ranking/leitura").json()
    assert volume and "livros" in volume[0] and "pontos" in volume[0]
    assert "nota" not in volume[0]           # volume, não nota 0–100
    desempenho = ranking(cliente, escola.id, "leitura")
    assert "nota" in desempenho[0] and "livros" not in desempenho[0]


# --- A migração 0027: aditiva, sem destruir dado, com backfill ---------------

def test_migracao_0027_preenche_aferido_e_posicao_sem_perder_dado(tmp_path):
    """Um banco na revisão anterior, com notas e snapshots REAIS, sobe até o head
    e nasce com as colunas por dimensão já preenchidas — sem tocar em nenhum
    valor que já existia."""
    from alembic import command
    from sqlalchemy import create_engine, text

    from app.core.migracoes import _config, aplicar_migracoes

    engine = create_engine(f"sqlite:///{tmp_path / 'antes-do-0027.db'}")
    try:
        cfg = _config()
        with engine.begin() as conexao:
            cfg.attributes["connection"] = conexao
            command.upgrade(cfg, "0026_modulos_rede")

        agora = "2026-08-01 00:00:00"
        with engine.begin() as c:
            c.execute(text(
                "INSERT INTO escolas (id, nome, ano_letivo_ativo, status, created_at)"
                f" VALUES (1, 'EM Legado', 2026, 'ativa', '{agora}')"))
            c.execute(text(
                "INSERT INTO importacoes (id, escola_id, plataforma, tipo, qtd_alunos,"
                f" qtd_erros, tempo_ms, status, created_at) VALUES (1, 1, 'seed',"
                f" 'seed', 0, 0, 0, 'ok', '{agora}')"))
            for aluno_id, nome, ele, mat in (
                (1, 'Le Muito', 80.0, 10.0),
                (2, 'Le Pouco', 20.0, 90.0),
                (3, 'Sem Nada', 0.0, 0.0),
            ):
                c.execute(text(
                    "INSERT INTO alunos (id, escola_id, nome, status, da_lista_piloto,"
                    f" ficha, created_at) VALUES ({aluno_id}, 1, '{nome}', 'ativo', 0,"
                    f" '{{}}', '{agora}')"))
                c.execute(text(
                    "INSERT INTO notas (id, escola_id, aluno_id, ano_letivo,"
                    " nota_matific, nota_elefante, nota_geral, posicao, detalhes,"
                    f" calculada_em) VALUES ({aluno_id}, 1, {aluno_id}, 2026, {mat},"
                    f" {ele}, {round((ele + mat) / 2, 2)}, {aluno_id}, '{{}}',"
                    f" '{agora}')"))
            # Só os dois primeiros têm dado do Elefante; só o segundo, do Matific.
            for aluno_id in (1, 2):
                c.execute(text(
                    "INSERT INTO snapshots_elefante (escola_id, aluno_id,"
                    " importacao_id, data_referencia, livros_unicos,"
                    " tempo_leitura_min, questoes_tentativas, questoes_acertos,"
                    f" livros_por_nivel) VALUES (1, {aluno_id}, 1, '{agora}', 10, 100,"
                    " 20, 15, '{}')"))
            c.execute(text(
                "INSERT INTO snapshots_matific (escola_id, aluno_id, importacao_id,"
                f" data_referencia, atividades, estrelas, pontuacao_media)"
                f" VALUES (1, 2, 1, '{agora}', 30, 60, 4.0)"))

        aplicar_migracoes(engine)

        with engine.connect() as c:
            linhas = {
                linha.aluno_id: linha for linha in c.execute(text(
                    "SELECT aluno_id, nota_elefante, nota_matific, nota_geral,"
                    " posicao, aferido_leitura, aferido_matematica, posicao_leitura,"
                    " posicao_matematica FROM notas")).all()
            }
        # NADA do que já existia foi tocado.
        assert [(linhas[i].nota_elefante, linhas[i].nota_geral, linhas[i].posicao)
                for i in (1, 2, 3)] == [(80.0, 45.0, 1), (20.0, 55.0, 2), (0.0, 0.0, 3)]
        # Aferido = existe snapshot da plataforma (nunca `nota > 0`).
        assert [bool(linhas[i].aferido_leitura) for i in (1, 2, 3)] == [True, True, False]
        assert [bool(linhas[i].aferido_matematica) for i in (1, 2, 3)] == [False, True, False]
        # Posição só entre os aferidos, por nota decrescente; ausente fica NULA.
        assert (linhas[1].posicao_leitura, linhas[2].posicao_leitura) == (1, 2)
        assert linhas[3].posicao_leitura is None
        assert linhas[2].posicao_matematica == 1
        assert linhas[1].posicao_matematica is None
    finally:
        engine.dispose()


# --- Legado preservado --------------------------------------------------------

def test_ranking_sem_dimensao_continua_sendo_o_geral_legado(db):
    """Compatibilidade durante a migração: sem `?dimensao=`, a rota devolve o
    Ranking Geral de sempre, com `nota_geral` e a posição única."""
    _, escola, turma, imp = montar_escola(db)
    novo_aluno(db, escola, turma, imp, "Aluna", elefante=dict(LEITOR),
               matific=dict(MATIFIC_TOPO))
    db.commit()
    scoring.recalcular_escola(db, escola.id)

    itens = logar().get(f"/api/v1/escolas/{escola.id}/ranking").json()
    assert itens[0]["posicao"] == 1
    assert itens[0]["dimensao"] is None and itens[0]["n_aferidos"] is None
    assert itens[0]["nota_geral"] > 0
