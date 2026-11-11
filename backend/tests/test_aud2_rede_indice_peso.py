"""G_ANALISE-5 — o ÍNDICE da rede (0–1000) e a MÉDIA GERAL da rede não pesam as Fases.

O índice de cada escola é per capita de quem CONCORRE (1º–5º ano: livros e estrelas ÷
``alunos_premiaveis``) e as médias 0–100 de cada escola só olham as turmas premiáveis.
Mas o índice da rede, a média geral da rede, o índice entre redes do Panorama Global e o
peso da meta de média geral ponderavam as escolas por ``alunos_com_dados`` — cobertura,
que conta também as crianças da Educação Infantil (Fases) com dado. A escola com mais
crianças da Fase puxava o número da rede para o lado dela.

Os pesos agora são o DENOMINADOR de cada métrica (a regra de ``rede._ponderada``):

* índice (per capita por matrícula de quem concorre) → ``alunos_premiaveis``. Assim o
  índice da rede é o per capita da rede inteira na régua da melhor escola;
* média geral (desempenho de quem tem dado) → ``alunos_com_dados_premiaveis`` (quem
  concorre E tem dado de alguma plataforma): a ausência continua fora da conta.

Redes, escolas e crianças FICTÍCIAS; números escolhidos à mão.
"""
import pytest

from app.models import (Aluno, Escola, Importacao, Matricula, Nota, Rede, SnapshotElefante,
                        SnapshotMatific, Turma)
from app.services import rede as svc
from app.services import scoring


def _rede(db, nome):
    rede = Rede(nome=nome, status="ativa")
    db.add(rede)
    db.flush()
    return rede


def _escola(db, rede, nome, *, concorrem, sem_dado=0, fase=0):
    """``concorrem``: (quantas crianças do 3º ano, livros, estrelas, nota 0–100) — todas
    com retrato das duas plataformas e Nota institucional carimbada. ``sem_dado``:
    crianças do 3º ano sem retrato nenhum. ``fase``: crianças de uma 1ª Fase com retrato
    das duas plataformas (não concorrem)."""
    esc = Escola(nome=nome, ano_letivo_ativo=2026, rede_id=rede.id, status="ativa")
    db.add(esc)
    db.flush()
    imp = Importacao(escola_id=esc.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    quantas, livros, estrelas, nota = concorrem
    grupos = (("3º Ano", quantas, True), ("3º Ano", sem_dado, False), ("1ª Fase", fase, True))
    turmas: dict[str, Turma] = {}
    for rotulo, n, com_dado in grupos:
        if rotulo not in turmas:
            turmas[rotulo] = Turma(escola_id=esc.id, nome=f"{rotulo} A", ano_escolar=rotulo,
                                   ano_letivo=2026, status="ativa")
            db.add(turmas[rotulo])
            db.flush()
        for i in range(n):
            a = Aluno(escola_id=esc.id, nome=f"Crianca Inventada {nome} {rotulo} {i}",
                      status="ativo")
            db.add(a)
            db.flush()
            db.add(Matricula(escola_id=esc.id, aluno_id=a.id, turma_id=turmas[rotulo].id,
                             ano_letivo=2026))
            if not com_dado:
                continue
            fase_ = rotulo == "1ª Fase"
            db.add(SnapshotElefante(escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
                                    livros_unicos=3 if fase_ else livros,
                                    tempo_leitura_min=60))
            # Atividades bastantes para as estrelas caberem no teto (5 por atividade):
            # acima dele, a rede soma só as que contam.
            est = 50 if fase_ else estrelas
            db.add(SnapshotMatific(escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
                                   atividades=max(10, -(-est // 5)), estrelas=est))
            if not fase_:
                db.add(Nota(detalhes=scoring.carimbo_institucional(), escola_id=esc.id,
                            aluno_id=a.id, ano_letivo=2026, nota_geral=nota,
                            nota_elefante=nota, nota_matific=nota,
                            nota_elefante_institucional=nota,
                            nota_matific_institucional=nota, posicao=i + 1))
    db.flush()
    return esc


def _rede_com_fase(db, nome="Rede Ficticia Peso das Fases"):
    """A: 10 do 3º ano, 20 livros e 400 estrelas cada, nota 80 → índice 1000.
    B: 10 do 3º ano, 10 livros e 200 estrelas cada, nota 40 → índice 500; e mais
    40 crianças da 1ª Fase com retrato (cobertura de B = 50)."""
    rede = _rede(db, nome)
    _escola(db, rede, "EMEF Inventada Alfa", concorrem=(10, 20, 400, 80.0))
    _escola(db, rede, "EMEF Inventada Beta", concorrem=(10, 10, 200, 40.0), fase=40)
    db.commit()
    return rede


def test_indice_e_media_geral_da_rede_nao_pesam_as_criancas_da_fase(db):
    rede = _rede_com_fase(db)
    painel = svc.dashboard_rede(db, rede.id)
    por_nome = {c["nome"]: c for c in painel["escolas"]}
    alfa, beta = por_nome["EMEF Inventada Alfa"], por_nome["EMEF Inventada Beta"]
    assert (alfa["pontuacao_geral"], beta["pontuacao_geral"]) == (1000.0, 500.0)
    assert (alfa["media_geral"], beta["media_geral"]) == (80.0, 40.0)
    totais = painel["totais"]
    # (1000·10 + 500·10) ÷ 20. Com o peso da cobertura: (1000·10 + 500·50) ÷ 60 = 583,3.
    assert totais["pontuacao_geral"] == 750.0
    # (80·10 + 40·10) ÷ 20. Com o peso da cobertura: (80·10 + 40·50) ÷ 60 = 46,7.
    assert totais["media_geral"] == 60.0
    assert painel["equidade"]["escolas_abaixo_do_indice_medio"] == 1
    assert painel["equidade"]["escolas_abaixo_da_media"] == 1
    # A cobertura de Beta continua contando as Fases (é dela também)...
    assert beta["alunos_com_dados"] == 50 and beta["alunos_premiaveis"] == 10
    # ... mas o peso de quem concorre com dado é 10.
    assert beta["alunos_com_dados_premiaveis"] == 10


def test_metas_de_indice_e_de_media_geral_leem_o_peso_de_quem_concorre(db):
    rede = _rede_com_fase(db, "Rede Ficticia Metas das Fases")
    svc.definir_meta(db, rede.id, "pontuacao_geral", 700.0)
    svc.definir_meta(db, rede.id, "media_geral", 50.0)
    db.commit()
    metas = {m["metrica"]: m for m in svc.metas_com_progresso(db, rede.id)}
    indice, media = metas["pontuacao_geral"], metas["media_geral"]
    # Antes: 583,3 de 700 (83,3%, "não atingida") e 46,7 de 50 ("não atingida").
    assert (indice["atual"], indice["atingida"], indice["progresso"]) == (750.0, True, 100.0)
    assert (media["atual"], media["atingida"], media["medida"]) == (60.0, True, True)


def test_peso_do_indice_e_quem_concorre_e_o_da_media_e_quem_concorre_com_dado(db):
    """Os dois pesos separados, sem Fase nenhuma: Gama tem 10 crianças que concorrem e
    só 2 com dado. O índice dela é por matrícula (as 8 sem dado contam no denominador
    do per capita), então ela pesa 10 no índice da rede; a média dela é só das 2 que
    têm dado, então pesa 2 na média geral (ausência não é zero)."""
    rede = _rede(db, "Rede Ficticia Dois Pesos")
    _escola(db, rede, "EMEF Inventada Alfa", concorrem=(10, 20, 400, 80.0))
    _escola(db, rede, "EMEF Inventada Gama", concorrem=(2, 20, 400, 20.0), sem_dado=8)
    db.commit()
    painel = svc.dashboard_rede(db, rede.id)
    gama = next(c for c in painel["escolas"] if c["nome"] == "EMEF Inventada Gama")
    # Per capita de Gama: 40 livros ÷ 10 = 4 e 800 estrelas ÷ 10 = 80 → 200 de 1000.
    assert gama["pontuacao_geral"] == 200.0
    totais = painel["totais"]
    # = o per capita da rede (240 livros ÷ 20 = 12) na régua da melhor (20): 600.
    # Com o peso da cobertura: (1000·10 + 200·2) ÷ 12 = 866,7.
    assert totais["pontuacao_geral"] == 600.0
    assert totais["media_geral"] == pytest.approx((80 * 10 + 20 * 2) / 12, abs=0.05)
    assert gama["alunos_premiaveis"] == 10 and gama["alunos_com_dados_premiaveis"] == 2


def test_panorama_global_pesa_redes_e_escolas_por_quem_concorre(db):
    """Entre redes: o índice global pondera cada rede por quem concorre nela, e a rede
    em que só a Fase tem dado (índice 0 por ausência) fica de fora, como no painel."""
    x = _rede_com_fase(db, "Rede Ficticia Xis")
    y = _rede(db, "Rede Ficticia Ypsilon")
    _escola(db, y, "EMEF Inventada Delta", concorrem=(10, 5, 100, 30.0), fase=90)
    z = _rede(db, "Rede Ficticia Zeta")
    _escola(db, z, "EMEF Inventada Epsilon", concorrem=(0, 0, 0, 0.0), sem_dado=5, fase=30)
    db.commit()

    global_ = svc.dashboard_global(db)
    redes = {r["rede_id"]: r for r in global_["redes"]}
    # Per capita das redes: Xis 300 livros ÷ 20 = 15 e 6000 estrelas ÷ 20 = 300 (a
    # melhor: 1000); Ypsilon 5 e 100 → 333,3; Zeta sem dado de quem concorre.
    assert redes[x.id]["pontuacao_geral"] == 1000.0
    assert redes[y.id]["pontuacao_geral"] == 333.3
    assert redes[z.id]["dimensoes_pontuadas"] == []
    # (1000·20 + 333,3·10) ÷ 30. Com o peso da cobertura (Xis 60, Ypsilon 100, Zeta 30)
    # dava (1000·60 + 333,3·100) ÷ 190 = 491,2.
    assert global_["totais"]["pontuacao_geral"] == 777.8
    # A média geral da rede no Panorama é a do painel dela; a global, das escolas.
    assert redes[x.id]["media_geral"] == svc.dashboard_rede(db, x.id)["totais"]["media_geral"]
    assert redes[x.id]["media_geral"] == 60.0
    # (80·10 + 40·10 + 30·10) ÷ 30. Com a cobertura: (800 + 2000 + 3000) ÷ 160 = 36,2.
    assert global_["totais"]["media_geral"] == 50.0
