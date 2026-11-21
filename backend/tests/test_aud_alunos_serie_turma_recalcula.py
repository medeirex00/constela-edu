"""Corrigir a SÉRIE (ou o turno) de uma turma recalcula as notas e as posições.

``PUT /turmas/{id}`` gravava ``ano_escolar`` e respondia sem recalcular a escola,
enquanto toda outra porta que muda a população do ranking (ações em massa, fusão,
exclusões, consolidar turmas, Lista Piloto) recalcula. A série decide QUEM concorre
(1º ao 5º ano; as Fases não) e o turno, no perfil personalizado, o bônus de livro
lido na escola. Sem o recálculo:

* Fase → Ano: as crianças que passam a concorrer ficam sem Nota e fora do ranking;
* Ano → Fase: a turma some das listas, mas as posições dos demais ficam com buraco
  (o 1º da escola aparece como 3º) e o "de N" não bate;
* Fase → Ano depois de um recálculo: a Nota congelada da Fase volta com a posição
  antiga e duas crianças ficam em 1º — e o certificado de mérito imprime "1ª
  posição" para as duas.

Achados ALUNOS-1 e RANKINGS-1 da auditoria. Dados fictícios.
"""
from datetime import date, datetime, time

from sqlalchemy import select

from app.models import (
    Aluno,
    Configuracao,
    Importacao,
    Leitura,
    Livro,
    Matricula,
    Nota,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
    Usuario,
)
from app.services import scoring

API = "/api/v1"
LEITOR = {"livros_unicos": 40, "tempo_leitura_min": 900,
          "questoes_tentativas": 100, "questoes_acertos": 95,
          "livros_por_nivel": {"D": 40}}
FRACO = {"livros_unicos": 2, "tempo_leitura_min": 30,
         "questoes_tentativas": 10, "questoes_acertos": 5,
         "livros_por_nivel": {"AA": 2}}


def _importacao(db, escola_id):
    imp = Importacao(escola_id=escola_id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    return imp


def _posicoes(cliente, base, **params):
    return [(i["aluno_id"], i["posicao"])
            for i in cliente.get(f"{base}/ranking", params=params).json()]


def test_fase_corrigida_para_ano_entra_no_ranking(cliente, db, escola_completa):
    """A criança da turma que vira 2º Ano passa a concorrer na hora (é a melhor
    leitora: fica em 1º)."""
    escola = escola_completa["escola"]
    for a in escola_completa["alunos"]:
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=a.id,
                                importacao_id=_importacao(db, escola.id).id, **FRACO))
    fase = Turma(escola_id=escola.id, nome="1ª Fase A", ano_escolar="1ª Fase",
                 ano_letivo=2026)
    db.add(fase)
    db.flush()
    x = Aluno(escola_id=escola.id, nome="CRIANCA FICTICIA SERIE CORRIGIDA")
    db.add(x)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=x.id, turma_id=fase.id,
                     ano_letivo=2026))
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=x.id,
                            importacao_id=_importacao(db, escola.id).id, **LEITOR))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    base = f"{API}/escolas/{escola.id}"
    x_id = x.id
    assert x_id not in [a for a, _p in _posicoes(cliente, base)]   # Fase não concorre

    r = cliente.put(f"{base}/turmas/{fase.id}", json={"ano_escolar": "2º Ano"})
    assert r.status_code == 200, r.text

    depois = _posicoes(cliente, base)
    db.expire_all()
    nota_x = db.execute(select(Nota).where(Nota.aluno_id == x_id)).scalar_one_or_none()
    assert nota_x is not None and nota_x.posicao == 1, \
        f"trocar a série não recalculou: Nota de X = {nota_x and nota_x.posicao}"
    assert depois[0] == (x_id, 1), depois
    assert [p for _a, p in depois] == list(range(1, len(depois) + 1)), depois
    # É exatamente o que um recálculo explícito daria.
    scoring.recalcular_escola(db, escola.id)
    assert _posicoes(cliente, base) == depois


def _cenario_rotulo_errado(db, escola_completa):
    """Turma "1 FASE A" importada como "1º Ano": os dois pequenos têm MAIS dado e
    ficam em 1º e 2º no cálculo com o rótulo errado."""
    esc = escola_completa["escola"]
    imp = _importacao(db, esc.id)
    rotulo_errado = Turma(escola_id=esc.id, nome="1 FASE A", ano_escolar="1º Ano",
                          ano_letivo=2026, status="ativa")
    db.add(rotulo_errado)
    db.flush()
    pequenos = []
    for nome in ("Pequeno Um Ficticio", "Pequeno Dois Ficticio"):
        a = Aluno(escola_id=esc.id, nome=nome, status="ativo")
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=esc.id, aluno_id=a.id, turma_id=rotulo_errado.id,
                         ano_letivo=2026))
        pequenos.append(a)
    todos = ([(a, 50 - 5 * i) for i, a in enumerate(pequenos)]
             + [(a, 10 + i) for i, a in enumerate(escola_completa["alunos"])])
    for aluno, n in todos:
        db.add(SnapshotElefante(escola_id=esc.id, aluno_id=aluno.id, importacao_id=imp.id,
                                data_referencia=datetime(2026, 10, 1), livros_unicos=n,
                                tempo_leitura_min=10 * n, livros_por_nivel={"D": n}))
        db.add(SnapshotMatific(escola_id=esc.id, aluno_id=aluno.id, importacao_id=imp.id,
                               data_referencia=datetime(2026, 10, 1), atividades=n,
                               estrelas=2 * n, pontuacao_media=3.0))
    db.commit()
    scoring.recalcular_escola(db, esc.id)
    return esc, rotulo_errado


def test_ano_corrigido_para_fase_nao_deixa_buraco_nas_posicoes(cliente, db,
                                                                escola_completa):
    esc, turma = _cenario_rotulo_errado(db, escola_completa)
    base = f"{API}/escolas/{esc.id}"
    assert len(_posicoes(cliente, base)) == 5
    r = cliente.put(f"{base}/turmas/{turma.id}", json={"ano_escolar": "1ª Fase"})
    assert r.status_code == 200, r.text

    geral = cliente.get(f"{base}/ranking").json()
    leitura = cliente.get(f"{base}/ranking", params={"dimensao": "leitura"}).json()
    top10 = cliente.get(f"{base}/dashboard").json()["top10"]
    assert len(geral) == 3
    assert [i["posicao"] for i in geral] == [1, 2, 3], \
        f"posição com buraco depois de corrigir a série: {[i['posicao'] for i in geral]}"
    assert [i["posicao"] for i in leitura] == [1, 2, 3]
    assert all(i["posicao"] <= i["n_aferidos"] for i in leitura), \
        "posição maior que o 'de N' na mesma linha"
    assert [i["posicao"] for i in top10] == [1, 2, 3]


def test_fase_que_volta_a_ser_ano_nao_repete_posicao(cliente, db, escola_completa):
    esc, turma = _cenario_rotulo_errado(db, escola_completa)
    base = f"{API}/escolas/{esc.id}"
    # 1º passo: a turma vira Fase e a escola é recalculada (por esta rota ou por
    # qualquer outra ação, como uma importação).
    assert cliente.put(f"{base}/turmas/{turma.id}",
                       json={"ano_escolar": "1ª Fase"}).status_code == 200
    db.expire_all()
    scoring.recalcular_escola(db, esc.id)
    # 2º passo: a coordenação percebe que era 1º Ano mesmo e devolve o rótulo.
    r = cliente.put(f"{base}/turmas/{turma.id}", json={"ano_escolar": "1º Ano"})
    assert r.status_code == 200, r.text
    posicoes = [p for _a, p in _posicoes(cliente, base)]
    assert posicoes == [1, 2, 3, 4, 5], f"posições repetidas ou com buraco: {posicoes}"


def test_certificado_de_merito_nao_imprime_posicao_repetida(cliente, db, escola_completa):
    """A guarda do certificado Geral (``exigir_merito``) devolve a Nota cuja posição
    vai IMPRESSA. Depois de Ano → Fase → Ano, cada criança imprime a sua."""
    from app.models import Escola
    from app.routers import relatorios as emissao

    esc, turma = _cenario_rotulo_errado(db, escola_completa)
    base = f"{API}/escolas/{esc.id}"
    cliente.put(f"{base}/turmas/{turma.id}", json={"ano_escolar": "1ª Fase"})
    db.expire_all()
    scoring.recalcular_escola(db, esc.id)      # uma importação qualquer, no meio
    cliente.put(f"{base}/turmas/{turma.id}", json={"ano_escolar": "1º Ano"})
    db.expire_all()
    for a in db.query(Aluno).filter_by(escola_id=esc.id).all():
        a.da_lista_piloto = True
    db.commit()
    escola = db.get(Escola, esc.id)
    admin = db.query(Usuario).filter_by(email="admin@teste.local").one()
    impressas = {}
    for a in db.query(Aluno).filter_by(escola_id=esc.id).all():
        preparo = emissao.preparar_certificado(db, escola, admin, a.id)
        impressas[a.nome] = emissao.exigir_merito(db, preparo).posicao
    assert sorted(impressas.values()) == [1, 2, 3, 4, 5], \
        f"certificados de mérito com posição repetida: {impressas}"


def test_trocar_o_turno_recalcula_o_bonus_de_leitura_na_escola(cliente, db,
                                                               escola_completa):
    """Perfil personalizado com bônus por livro lido NA ESCOLA: a janela vem do
    turno da turma. Ana leu 4 livros numa segunda às 9h; com a turma sem turno não
    há bônus, e ao marcar "manhã" a nota dela tem de subir na hora."""
    escola = escola_completa["escola"]
    turma = escola_completa["turma"]
    ana = next(a for a in escola_completa["alunos"] if a.nome == "Ana Beatriz Souza")
    imp = _importacao(db, escola.id)
    for a in escola_completa["alunos"]:
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=a.id, importacao_id=imp.id,
                                **(FRACO if a.id == ana.id else LEITOR)))
    segunda = date(2026, 7, 6)
    assert segunda.weekday() == 0
    for i in range(4):
        livro = Livro(escola_id=escola.id, titulo=f"Livro ficticio da escola {i}",
                      nivel_codigo="D")
        db.add(livro)
        db.flush()
        db.add(Leitura(escola_id=escola.id, aluno_id=ana.id, livro_id=livro.id,
                       data=datetime.combine(segunda, time(9, 0))))
    db.add(Configuracao(escola_id=escola.id, namespace=scoring.PERFIL_SCORING_NS,
                        chave="modo", valor="personalizado"))
    db.add(Configuracao(escola_id=escola.id, namespace="pesos.elefante_extra",
                        chave="valores", valor={"ativo": True, "pontos_por_livro": 10.0}))
    turma.turno = None
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    ana_id = ana.id

    def _nota_da_ana():
        db.expire_all()
        nota = db.execute(select(Nota).where(Nota.aluno_id == ana_id)).scalar_one()
        bonus = ((nota.detalhes or {}).get("elefante") or {}).get("bonus_leitura_escola")
        return nota.nota_elefante, bonus

    antes = _nota_da_ana()
    r = cliente.put(f"{API}/escolas/{escola.id}/turmas/{turma.id}",
                    json={"turno": "manha"})
    assert r.status_code == 200, r.text
    depois = _nota_da_ana()
    scoring.recalcular_escola(db, escola.id)
    certo = _nota_da_ana()
    assert certo[0] != antes[0] and certo[1] == 40.0,         f"o cenário não exercita o bônus do turno: antes={antes} certo={certo}"
    assert depois == certo, f"trocar o turno não recalculou: antes={antes} depois={depois}"
