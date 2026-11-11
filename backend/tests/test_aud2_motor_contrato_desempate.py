"""G_MODULOS-2 — o módulo fora do plano não desempata a ordem legada (``Nota.posicao``).

A ordem legada é a do Ranking Geral, do Top 10, do telão, do cartaz e do
certificado "Geral". Ela desempata com ``nota_elefante → nota_matific →
livros_unicos → atividades → ...``. Numa rede de UM módulo só, a dimensão que a
rede não contratou não existe para ela: um retrato antigo dessa plataforma (o
contrato mudou no meio do ano, ou a escola veio de outra rede) não pode decidir
quem sai em 1º.

Cenário: 20 crianças; duas saturam a régua da dimensão contratada (nota 100,0
as duas). A que tem MAIS na dimensão contratada tem de ficar à frente, como no
ranking da própria dimensão. Dados 100% fictícios.
"""
from datetime import datetime, timedelta, timezone

from app.models import (
    Aluno,
    Configuracao,
    Importacao,
    Leitura,
    Livro,
    Matricula,
    ModuloRede,
    Nota,
    Rede,
    SnapshotElefante,
    SnapshotMatific,
)
from app.services import modulos as svc_modulos, scoring

API = "/api/v1"


def _ontem():
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)


def _rede(db, escola, desligado):
    """Põe a escola numa rede com ``desligado`` fora do plano (None = sem rede)."""
    if desligado is None:
        return
    rede = Rede(nome=f"Rede Inventada Sem {desligado}", status="ativa")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    for modulo in svc_modulos.TODOS:
        db.add(ModuloRede(rede_id=rede.id, modulo=modulo, ativo=(modulo != desligado)))


def _novo_aluno(db, escola, turma, nome):
    aluno = Aluno(escola_id=escola.id, nome=nome)
    db.add(aluno)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id, turma_id=turma.id,
                     ano_letivo=2026))
    return aluno


def _cenario_leitura(db, escola_completa, desligado):
    """18 leitores comuns e 2 que saturam a Leitura: Caio leu 40, Bia leu 30 —
    e só a Bia tem retrato do Matific."""
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    _rede(db, escola, desligado)
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    quando = _ontem()
    alunos = list(escola_completa["alunos"])
    alunos += [_novo_aluno(db, escola, turma, f"Leitor Inventado {i:02d}") for i in range(15)]
    for i, a in enumerate(alunos):
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=a.id, importacao_id=imp.id,
                                livros_unicos=2 + i % 4, tempo_leitura_min=30 + i,
                                questoes_tentativas=10, questoes_acertos=5,
                                livros_por_nivel={"D": 2 + i % 4}, data_referencia=quando))
    bia = _novo_aluno(db, escola, turma, "Bia Inventada")
    caio = _novo_aluno(db, escola, turma, "Caio Inventado")
    for a, livros in ((bia, 30), (caio, 40)):
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=a.id, importacao_id=imp.id,
                                livros_unicos=livros, tempo_leitura_min=900,
                                questoes_tentativas=200, questoes_acertos=190,
                                livros_por_nivel={"D": livros}, data_referencia=quando))
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=bia.id, importacao_id=imp.id,
                           atividades=50, estrelas=120, pontuacao_media=3.0,
                           data_referencia=quando))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    return escola, bia, caio


def _cenario_matematica(db, escola_completa, desligado):
    """18 crianças comuns no Matific e 2 que saturam a Matemática: Duda fez mais
    atividades e estrelas que o Edu — e só o Edu tem retrato do Elefante."""
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    _rede(db, escola, desligado)
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    quando = _ontem()
    alunos = list(escola_completa["alunos"])
    alunos += [_novo_aluno(db, escola, turma, f"Calculista Inventado {i:02d}")
               for i in range(15)]
    for i, a in enumerate(alunos):
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=a.id, importacao_id=imp.id,
                               atividades=3 + i % 4, estrelas=6 + i % 5,
                               pontuacao_media=2.0, data_referencia=quando))
    duda = _novo_aluno(db, escola, turma, "Duda Inventada")
    edu = _novo_aluno(db, escola, turma, "Edu Inventado")
    for a, atividades, estrelas in ((duda, 60, 200), (edu, 50, 120)):
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=a.id, importacao_id=imp.id,
                               atividades=atividades, estrelas=estrelas,
                               pontuacao_media=4.0, data_referencia=quando))
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=edu.id, importacao_id=imp.id,
                            livros_unicos=10, tempo_leitura_min=300,
                            questoes_tentativas=40, questoes_acertos=35,
                            livros_por_nivel={"D": 10}, data_referencia=quando))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    return escola, duda, edu


def _nota(db, aluno):
    db.expire_all()
    return db.query(Nota).filter(Nota.aluno_id == aluno.id).one()


def _topo(cliente, escola, n=2):
    corpo = cliente.get(f"{API}/escolas/{escola.id}/ranking").json()
    itens = corpo if isinstance(corpo, list) else corpo.get("itens", corpo)
    return [i["nome"] for i in itens[:n]]


def test_rede_so_leitura_o_matific_nao_desempata_o_geral(db, escola_completa, cliente):
    escola, bia, caio = _cenario_leitura(db, escola_completa, "matematica")
    nb, nc = _nota(db, bia), _nota(db, caio)
    assert nb.nota_elefante == nc.nota_elefante == 100.0
    assert nb.nota_geral == nc.nota_geral
    # Geral = Leitura: quem leu mais (Caio) fica à frente, como no ranking de Leitura.
    assert nc.posicao_leitura < nb.posicao_leitura
    assert nc.posicao < nb.posicao, (nb.posicao, nc.posicao)
    assert _topo(cliente, escola) == ["Caio Inventado", "Bia Inventada"]
    # A nota do módulo fora do plano não fica gravada com valor real.
    assert nb.nota_matific == 0.0 and nb.nota_matific_institucional == 0.0
    assert nb.aferido_matematica is False and nb.posicao_matematica is None
    assert nb.detalhes["dimensoes"]["matematica"]["snapshot_em"] is None


def test_rede_so_matematica_o_elefante_nao_desempata_o_geral(db, escola_completa, cliente):
    escola, duda, edu = _cenario_matematica(db, escola_completa, "leitura")
    nd, ne = _nota(db, duda), _nota(db, edu)
    assert nd.nota_matific == ne.nota_matific == 100.0
    assert nd.nota_geral == ne.nota_geral
    # Geral = Matemática: quem fez mais (Duda) fica à frente, como no ranking de
    # Matemática; o Elefante (fora do plano) não decide.
    assert nd.posicao_matematica < ne.posicao_matematica
    assert nd.posicao < ne.posicao, (nd.posicao, ne.posicao)
    assert _topo(cliente, escola) == ["Duda Inventada", "Edu Inventado"]
    assert ne.nota_elefante == 0.0 and ne.nota_elefante_institucional == 0.0
    assert ne.aferido_leitura is False and ne.posicao_leitura is None


def test_controle_escola_sem_rede_o_matific_desempata_por_desenho(db, escola_completa):
    """Com os dois módulos, o desempate pela nota do Matific é do desenho."""
    _escola, bia, caio = _cenario_leitura(db, escola_completa, None)
    nb, nc = _nota(db, bia), _nota(db, caio)
    assert nb.nota_matific > 0 and nb.aferido_matematica is True
    assert nb.posicao < nc.posicao


def test_rede_so_matematica_personalizada_bonus_de_leitura_nao_traz_o_elefante(
        db, escola_completa):
    """Perfil personalizado com o bônus "livro lido na escola" ligado: numa rede
    só com Matemática, nem as leituras itemizadas nem o bônus fazem nascer nota
    de Leitura (que desempataria a ordem legada)."""
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    ana, joao, sofia = escola_completa["alunos"]
    _rede(db, escola, "leitura")
    turma.turno = "manha"
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    for a in (ana, joao, sofia):
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=a.id, importacao_id=imp.id,
                               atividades=10, estrelas=30, pontuacao_media=3.0,
                               data_referencia=_ontem()))
    segunda_9h = datetime(2026, 7, 6, 9, 0)
    for i in range(3):
        livro = Livro(escola_id=escola.id, titulo=f"Livro Inventado {i}", nivel_codigo="D")
        db.add(livro)
        db.flush()
        db.add(Leitura(escola_id=escola.id, aluno_id=ana.id, livro_id=livro.id,
                       data=segunda_9h))
    db.add(Configuracao(escola_id=escola.id, namespace=scoring.PERFIL_SCORING_NS,
                        chave="modo", valor="personalizado"))
    db.add(Configuracao(escola_id=escola.id, namespace="pesos.elefante_extra",
                        chave="valores", valor={"ativo": True, "pontos_por_livro": 10.0}))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    na, nj = _nota(db, ana), _nota(db, joao)
    assert na.nota_elefante == 0.0 and na.nota_elefante_institucional == 0.0
    assert na.aferido_leitura is False
    assert na.detalhes["elefante"]["bonus_leitura_escola"] == 0.0
    # Empatados em tudo o que a rede contratou: a ordem cai no nome, não na leitura.
    assert na.posicao < nj.posicao


def test_rede_so_leitura_simulador_usa_a_mesma_regua_do_motor(db, escola_completa):
    """O simulador (``contexto_normalizacao``) e o motor leem o mesmo contexto: a
    régua do Matific de uma rede só com Leitura não nasce de dado fora do plano."""
    escola, *_ = _cenario_leitura(db, escola_completa, "matematica")
    refs, _modo, _k = scoring.contexto_normalizacao(db, escola.id)
    assert refs["max_atividades"] == 0 and refs["max_estrelas"] == 0
    assert refs["max_livros"] > 0
