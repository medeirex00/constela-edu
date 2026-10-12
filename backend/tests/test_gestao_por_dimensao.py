"""PERFIL e LISTA DA TURMA por matéria — o que a tela da gestão lê no lugar da
nota geral (Decisão 1 do dono, 2026-10-12: transição da `nota_geral` para as
notas por disciplina, mantendo a coluna até sair o último uso legado).

O schema já declarava os campos por dimensão nos dois payloads
(`AlunoPerfilOut.dimensoes`/`adocao` e `AlunoGestaoOut.nota_leitura`…), mas as
rotas não os preenchiam — a tela só tinha a nota geral para mostrar. Estes
testes travam que agora eles chegam, com as mesmas regras do ranking por
dimensão:

  * AUSÊNCIA ≠ ZERO — sem snapshot da plataforma, nota e posição `None` (a tela
    mostra "—"), nunca 0,0;
  * CONTRATO antes de DADO — matéria que a rede não contratou não aparece no
    perfil nem preenche a lista, mesmo com snapshot no banco;
  * a ordem `desempenho_leitura`/`desempenho_matematica` da turma é a do
    ranking da dimensão, com os não aferidos no FIM (por nome, sem nota);
  * nada disso depende do legado: com `nota_geral`/`posicao` adulteradas no
    banco, tudo sai idêntico (a mesma sabotagem de `test_legado_nota_geral`);
  * o contrato antigo continua: `nota_geral`, `posicao` e `ordenar=desempenho`.
"""
import random

from app.models import Nota
from app.services import modulos as svc_modulos
from app.services import scoring
from tests.test_desempenho_por_dimensao import (
    LEITOR,
    LEITOR_FRACO,
    MATIFIC_FRACO,
    MATIFIC_TOPO,
    logar,
    montar_escola,
    novo_aluno,
)


def _cenario(db, *, com_rede=False):
    """As quatro situações que a arquitetura distingue, numa turma só."""
    rede, escola, turma, imp = montar_escola(db, com_rede=com_rede)
    alunos = {
        "duas": novo_aluno(db, escola, turma, imp, "Usa As Duas",
                           elefante=dict(LEITOR_FRACO), matific=dict(MATIFIC_TOPO)),
        "so_le": novo_aluno(db, escola, turma, imp, "So Leitura",
                            elefante=dict(LEITOR)),
        "so_conta": novo_aluno(db, escola, turma, imp, "So Conta",
                               matific=dict(MATIFIC_FRACO)),
        "nenhuma": novo_aluno(db, escola, turma, imp, "Nenhuma Plataforma"),
    }
    db.commit()
    return rede, escola, turma, imp, alunos


def _perfil(cliente, escola_id, aluno_id):
    r = cliente.get(f"/api/v1/escolas/{escola_id}/alunos/{aluno_id}/perfil")
    assert r.status_code == 200, r.text
    return r.json()


def _lista(cliente, escola_id, turma_id, ordenar="nome"):
    r = cliente.get(f"/api/v1/escolas/{escola_id}/turmas/{turma_id}/alunos"
                    f"?ordenar={ordenar}")
    assert r.status_code == 200, r.text
    return r.json()


def _por_dimensao(perfil):
    return {d["dimensao"]: d for d in perfil["dimensoes"]}


# --- Perfil -------------------------------------------------------------------

def test_perfil_traz_as_dimensoes_e_a_adocao_sem_zero_de_ausencia(db):
    _, escola, _, _, alunos = _cenario(db)
    scoring.recalcular_escola(db, escola.id)
    cliente = logar()

    so_le = _perfil(cliente, escola.id, alunos["so_le"].id)
    dims = _por_dimensao(so_le)
    assert [d["dimensao"] for d in so_le["dimensoes"]] == ["leitura", "matematica"]
    leitura, matematica = dims["leitura"], dims["matematica"]
    assert leitura["aferido"] is True and leitura["nota"] > 0
    assert leitura["posicao"] >= 1 and leitura["n_aferidos"] == 2
    assert leitura["dados"]["livros_unicos"] == 30
    # Nunca abriu o Matific: AUSÊNCIA, não 0,0 — e sem posição.
    assert matematica["aferido"] is False
    assert matematica["nota"] is None and matematica["posicao"] is None
    assert so_le["adocao"] == {"contratadas": ["leitura", "matematica"],
                               "com_dados": ["leitura"], "pct": 50.0}

    nenhuma = _perfil(cliente, escola.id, alunos["nenhuma"].id)
    assert all(d["aferido"] is False and d["nota"] is None
               for d in nenhuma["dimensoes"])
    assert nenhuma["adocao"]["pct"] == 0.0 and nenhuma["adocao"]["com_dados"] == []

    # A posição do perfil é a MESMA do ranking da dimensão (fonte única).
    ranking = cliente.get(
        f"/api/v1/escolas/{escola.id}/ranking?dimensao=leitura").json()
    posicoes = {i["aluno_id"]: i["posicao"] for i in ranking}
    assert leitura["posicao"] == posicoes[alunos["so_le"].id]

    # O contrato legado segue no payload (clientes não migrados, app em campo).
    assert "nota_geral" in so_le and "posicao" in so_le


def test_perfil_sem_nota_calculada_nao_afirma_ausencia(db):
    """Aluno sem linha de `notas` (ainda não calculado): lista vazia e adoção
    nula — a tela diz "sem nota calculada", não "não aferido"."""
    _, escola, turma, imp, _ = _cenario(db)
    scoring.recalcular_escola(db, escola.id)
    novato = novo_aluno(db, escola, turma, imp, "Chegou Depois",
                        elefante=dict(LEITOR))
    db.commit()

    perfil = _perfil(logar(), escola.id, novato.id)
    assert perfil["dimensoes"] == []
    assert perfil["adocao"] is None


def test_perfil_e_lista_so_mostram_a_materia_contratada(db):
    """Cascata CONTRATO → DADO: a rede sem Matemática não vê Matemática no
    perfil nem na lista da turma, mesmo com o snapshot do Matific no banco."""
    rede, escola, turma, _, alunos = _cenario(db, com_rede=True)
    svc_modulos.definir(db, rede.id, "matematica", False)
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    cliente = logar()

    perfil = _perfil(cliente, escola.id, alunos["duas"].id)
    assert [d["dimensao"] for d in perfil["dimensoes"]] == ["leitura"]
    assert perfil["adocao"]["contratadas"] == ["leitura"]

    duas = next(a for a in _lista(cliente, escola.id, turma.id)
                if a["id"] == alunos["duas"].id)
    assert duas["aferido_leitura"] is True and duas["nota_leitura"] is not None
    assert duas["aferido_matematica"] is False
    assert duas["nota_matematica"] is None and duas["posicao_matematica"] is None


# --- Lista da turma -----------------------------------------------------------

def test_lista_da_turma_traz_a_nota_de_cada_materia_com_o_corte_de_aferido(db):
    _, escola, turma, _, alunos = _cenario(db)
    scoring.recalcular_escola(db, escola.id)
    cliente = logar()
    linhas = {a["id"]: a for a in _lista(cliente, escola.id, turma.id)}

    so_le = linhas[alunos["so_le"].id]
    assert so_le["aferido_leitura"] is True and so_le["nota_leitura"] > 0
    assert so_le["posicao_leitura"] >= 1
    assert so_le["aferido_matematica"] is False
    assert so_le["nota_matematica"] is None and so_le["posicao_matematica"] is None

    so_conta = linhas[alunos["so_conta"].id]
    assert so_conta["aferido_matematica"] is True and so_conta["nota_matematica"] > 0
    assert so_conta["nota_leitura"] is None

    nenhuma = linhas[alunos["nenhuma"].id]
    assert nenhuma["nota_leitura"] is None and nenhuma["nota_matematica"] is None
    assert nenhuma["aferido_leitura"] is False and nenhuma["aferido_matematica"] is False


def test_ordem_por_materia_segue_o_ranking_e_poe_os_nao_aferidos_no_fim(db):
    _, escola, turma, _, alunos = _cenario(db)
    scoring.recalcular_escola(db, escola.id)
    cliente = logar()

    for dimensao, sem_dado in (("leitura", ["Nenhuma Plataforma", "So Conta"]),
                               ("matematica", ["Nenhuma Plataforma", "So Leitura"])):
        ranking = cliente.get(
            f"/api/v1/escolas/{escola.id}/ranking?dimensao={dimensao}").json()
        lista = _lista(cliente, escola.id, turma.id, f"desempenho_{dimensao}")
        nomes = [a["nome"] for a in lista]
        # Aferidos na ordem do ranking oficial da dimensão (mesmo desempate)…
        assert nomes[:len(ranking)] == [i["nome"] for i in ranking]
        # …e quem não tem dado vai para o FIM, por nome, sem nota.
        assert nomes[len(ranking):] == sem_dado
        assert all(a[f"nota_{dimensao}"] is None for a in lista[len(ranking):])

    # Valor RESIDUAL na coluna de quem não é aferido (ex.: Matific só de ano
    # anterior) não fura a fila: o corte é a marca de aferido, e entre os não
    # aferidos quem decide é o nome.
    notas = {n.aluno_id: n for n in db.query(Nota).filter(Nota.escola_id == escola.id)}
    # (o maior resíduo vai para quem vem DEPOIS no nome — se a nota ordenasse,
    # a ordem inverteria)
    notas[alunos["nenhuma"].id].nota_elefante = 50.0
    notas[alunos["so_conta"].id].nota_elefante = 99.0
    db.commit()
    nomes = [a["nome"] for a in _lista(cliente, escola.id, turma.id,
                                       "desempenho_leitura")]
    assert nomes[2:] == ["Nenhuma Plataforma", "So Conta"]


def test_contrato_legado_da_lista_continua(db):
    """`ordenar=desempenho` e os campos `nota_geral`/`posicao` seguem no ar para
    cliente não migrado — a tela web é que deixou de pedi-los."""
    _, escola, turma, _, alunos = _cenario(db)
    scoring.recalcular_escola(db, escola.id)
    lista = _lista(logar(), escola.id, turma.id, "desempenho")
    assert {a["id"] for a in lista} == {a.id for a in alunos.values()}
    assert all("nota_geral" in a and "posicao" in a for a in lista)


def test_perfil_e_lista_por_materia_nao_dependem_do_legado(db):
    """Sabotagem: com `nota_geral` e `posicao` embaralhadas no banco, o perfil
    por dimensão, a lista por matéria e as duas ordens oficiais da turma saem
    IDÊNTICOS. Se não saíssem, a tela ainda dependeria da ordem única."""
    _, escola, turma, _, alunos = _cenario(db)
    scoring.recalcular_escola(db, escola.id)
    cliente = logar()

    def oficial():
        perfis = {}
        for chave, aluno in alunos.items():
            perfil = _perfil(cliente, escola.id, aluno.id)
            perfis[chave] = (perfil["dimensoes"], perfil["adocao"])
        campos = ("nota_leitura", "aferido_leitura", "posicao_leitura",
                  "nota_matematica", "aferido_matematica", "posicao_matematica")
        lista = {a["id"]: tuple(a[c] for c in campos)
                 for a in _lista(cliente, escola.id, turma.id)}
        ordens = {d: [a["id"] for a in _lista(cliente, escola.id, turma.id,
                                             f"desempenho_{d}")]
                  for d in ("leitura", "matematica")}
        return perfis, lista, ordens

    antes = oficial()
    notas = db.query(Nota).filter(Nota.escola_id == escola.id).all()
    sorteio = random.Random(20261012)
    valores = [999.0, -5.0, 0.0, 42.0][:len(notas)]
    sorteio.shuffle(valores)
    for nota, valor, posicao in zip(notas, valores, range(len(notas), 0, -1)):
        nota.nota_geral = valor
        nota.posicao = posicao
    db.commit()

    assert oficial() == antes
