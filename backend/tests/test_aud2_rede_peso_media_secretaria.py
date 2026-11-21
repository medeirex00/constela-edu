"""REV2-REDE-1 (sobre G_ANALISE-5), na visão da SECRETARIA — com uma matéria escondida
(grupo pequeno), a escola pesa na média geral da rede só por quem a média VISÍVEL mede.

Na resposta da Secretaria, a matéria com menos de 3 crianças com dado sai do cartão e a
``media_geral`` da escola passa a ser só a da matéria que sobra (``_proteger_cartoes``).
O peso dela na média geral da rede (``alunos_com_dados_premiaveis``) continuava sendo
quem está em ALGUMA das médias — inclusive as crianças que só estão na matéria
escondida, que a média visível não mede.

Rede, escolas e crianças FICTÍCIAS; números escolhidos à mão.
"""
from app.models import (Aluno, Escola, Importacao, Matricula, Nota, Rede, SnapshotElefante,
                        SnapshotMatific, Turma)
from app.services import rede as svc
from app.services import scoring
from tests._ano_letivo import ANO


def _escola(db, rede, nome, grupos):
    """``grupos``: (quantas crianças do 3º ano, plataformas com retrato, nota)."""
    esc = Escola(nome=nome, ano_letivo_ativo=ANO, rede_id=rede.id, status="ativa")
    db.add(esc)
    db.flush()
    imp = Importacao(escola_id=esc.id, plataforma="seed", tipo="seed")
    db.add(imp)
    turma = Turma(escola_id=esc.id, nome="3º Ano A", ano_escolar="3º Ano", ano_letivo=ANO,
                  status="ativa")
    db.add(turma)
    db.flush()
    posicao = 0
    for quantas, plataformas, nota in grupos:
        for i in range(quantas):
            a = Aluno(escola_id=esc.id, nome=f"Crianca Inventada {nome} {plataformas} {i}",
                      status="ativo")
            db.add(a)
            db.flush()
            db.add(Matricula(escola_id=esc.id, aluno_id=a.id, turma_id=turma.id,
                             ano_letivo=ANO))
            if "ele" in plataformas:
                db.add(SnapshotElefante(escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
                                        livros_unicos=10, tempo_leitura_min=60))
            if "mat" in plataformas:
                db.add(SnapshotMatific(escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
                                       atividades=10, estrelas=100))
            posicao += 1
            db.add(Nota(detalhes=scoring.carimbo_institucional(), escola_id=esc.id,
                        aluno_id=a.id, ano_letivo=ANO, nota_geral=nota,
                        nota_elefante=nota, nota_matific=nota,
                        nota_elefante_institucional=nota if "ele" in plataformas else 0.0,
                        nota_matific_institucional=nota if "mat" in plataformas else 0.0,
                        posicao=posicao))
    db.flush()
    return esc


def _mundo(db, nome="Rede Ficticia Materia Escondida"):
    """Alfa: 10 crianças nas duas plataformas, nota 80. Beta: 2 só no Elefante (nota 90:
    a Leitura de Beta é grupo pequeno para a Secretaria) e 10 só no Matific (nota 40)."""
    rede = Rede(nome=nome, status="ativa")
    db.add(rede)
    db.flush()
    _escola(db, rede, "EMEF Inventada Alfa", [(10, "ele+mat", 80.0)])
    _escola(db, rede, "EMEF Inventada Beta", [(2, "ele", 90.0), (10, "mat", 40.0)])
    db.commit()
    return rede


def test_secretaria_escola_com_materia_escondida_pesa_por_quem_a_media_visivel_mede(db):
    rede = _mundo(db)
    painel = svc.dashboard_rede(db, rede.id, secretaria=True)
    beta = next(c for c in painel["escolas"] if c["nome"] == "EMEF Inventada Beta")
    # A Leitura de Beta está escondida; a média geral dela é só a do Matific.
    assert beta["grupo_pequeno"] and beta["media_elefante"] is None
    assert (beta["media_geral"], beta["alunos_com_nota_matific"]) == (40.0, 10)
    assert beta["comparada"]
    # O peso é quem a média visível mede: as 10 do Matific. Antes: 12 (as 2 da Leitura
    # escondida também).
    assert beta["alunos_com_dados_premiaveis"] == 10
    # (80·10 + 40·10) ÷ 20. Com o peso antigo: (80·10 + 40·12) ÷ 22 = 58,2.
    assert painel["totais"]["media_geral"] == 60.0


def test_secretaria_meta_da_media_geral_le_o_mesmo_peso(db):
    rede = _mundo(db, "Rede Ficticia Materia Escondida Meta")
    svc.definir_meta(db, rede.id, "media_geral", 59.0)
    db.commit()
    painel = svc.dashboard_rede(db, rede.id, secretaria=True)
    meta = next(m for m in svc.metas_com_progresso(db, rede.id, dados=painel)
                if m["metrica"] == "media_geral")
    # Antes: 58,2 de 59 ("não atingida").
    assert (meta["atual"], meta["atingida"], meta["medida"]) == (60.0, True, True)


def test_admin_continua_pesando_quem_esta_em_alguma_das_medias(db):
    """Sem matéria escondida (Admin Global), a média geral de Beta é das duas matérias
    e o peso, quem está em alguma delas: as 12."""
    rede = _mundo(db, "Rede Ficticia Materia Visivel")
    painel = svc.dashboard_rede(db, rede.id)
    beta = next(c for c in painel["escolas"] if c["nome"] == "EMEF Inventada Beta")
    assert (beta["media_geral"], beta["alunos_com_dados_premiaveis"]) == (65.0, 12)
    # (80·10 + 65·12) ÷ 22.
    assert painel["totais"]["media_geral"] == 71.8
