"""REV2-REDE-1 (sobre G_ANALISE-5) — o PESO da média geral da rede é quem a média MEDE.

A média geral 0–100 de cada escola (``media_geral``) é a média das médias por
plataforma, e cada média por plataforma só olha a Nota CALCULADA (carimbo
institucional) de quem concorre e TEM dado dela (``rede._q_medias``): retrato do
Elefante ou Leitura itemizada; retrato do Matific DENTRO do ano letivo ativo
(Matific é contador do ano). O peso da escola na média geral da rede, no Panorama
Global e na meta "Média geral da rede" (``alunos_com_dados_premiaveis``) era contado
na COBERTURA (qualquer retrato, sem o corte do ano, sem olhar a Nota): pesava
crianças que a média não mede — a que só tem o Matific do ano passado, a que ainda
não tem Nota calculada — e deixava de fora a que só tem Leitura itemizada, que a
média mede.

Redes, escolas e crianças FICTÍCIAS; números escolhidos à mão.
"""
from datetime import datetime

import pytest

from app.models import (Aluno, Escola, Importacao, Leitura, Livro, Matricula, Nota, Rede,
                        SnapshotElefante, SnapshotMatific, Turma)
from app.models.base import agora
from app.services import rede as svc
from app.services import scoring
from tests._ano_letivo import ANO

ANO_PASSADO = datetime(ANO - 1, 6, 1)


def _rede(db, nome):
    rede = Rede(nome=nome, status="ativa")
    db.add(rede)
    db.flush()
    return rede


def _escola(db, rede, nome, *, medidas, nota, so_matific_antigo=0, so_leitura=0,
            sem_nota=0, nota_pendente=0):
    """Uma escola com uma turma do 3º ano.

    ``medidas``: crianças com retrato das duas plataformas (Matific do ano) e Nota
    calculada ``nota``. ``so_matific_antigo``: só o retrato do Matific do ano anterior, Nota
    calculada 0 (a média não as mede). ``so_leitura``: só Leitura itemizada no
    Elefante (sem retrato nenhum), Nota calculada ``nota`` (a média as mede).
    ``sem_nota``: retrato das duas plataformas e nenhuma Nota (o recálculo ainda não
    passou). ``nota_pendente``: retrato das duas e Nota sem o carimbo institucional."""
    esc = Escola(nome=nome, ano_letivo_ativo=ANO, rede_id=rede.id, status="ativa")
    db.add(esc)
    db.flush()
    imp = Importacao(escola_id=esc.id, plataforma="seed", tipo="seed")
    db.add(imp)
    turma = Turma(escola_id=esc.id, nome="3º Ano A", ano_escolar="3º Ano", ano_letivo=ANO,
                  status="ativa")
    db.add(turma)
    livro = Livro(escola_id=esc.id, titulo=f"Livro Inventado {nome}", nivel_codigo="K")
    db.add(livro)
    db.flush()
    grupos = (("medida", medidas), ("matific_antigo", so_matific_antigo),
              ("so_leitura", so_leitura), ("sem_nota", sem_nota),
              ("pendente", nota_pendente))
    posicao = 0
    for tipo, quantas in grupos:
        for i in range(quantas):
            a = Aluno(escola_id=esc.id, nome=f"Crianca Inventada {nome} {tipo} {i}",
                      status="ativo")
            db.add(a)
            db.flush()
            db.add(Matricula(escola_id=esc.id, aluno_id=a.id, turma_id=turma.id,
                             ano_letivo=ANO))
            if tipo in ("medida", "sem_nota", "pendente"):
                db.add(SnapshotElefante(escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
                                        livros_unicos=10, tempo_leitura_min=60))
                db.add(SnapshotMatific(escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
                                       atividades=10, estrelas=100))
            elif tipo == "matific_antigo":
                db.add(SnapshotMatific(escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
                                       atividades=5, estrelas=50,
                                       data_referencia=ANO_PASSADO))
            else:
                db.add(Leitura(escola_id=esc.id, aluno_id=a.id, livro_id=livro.id,
                               data=agora().replace(tzinfo=None), tempo_leitura_min=10,
                               nivel_codigo="K"))
            if tipo == "sem_nota":
                continue
            n = 0.0 if tipo == "matific_antigo" else nota
            posicao += 1
            db.add(Nota(detalhes=None if tipo == "pendente" else scoring.carimbo_institucional(),
                        escola_id=esc.id, aluno_id=a.id, ano_letivo=ANO, nota_geral=n,
                        nota_elefante=n, nota_matific=n,
                        nota_elefante_institucional=n,
                        nota_matific_institucional=0.0 if tipo == "so_leitura" else n,
                        posicao=posicao))
    db.flush()
    return esc


def _cartoes(painel):
    return {c["nome"]: c for c in painel["escolas"]}


def _mundo_matific_antigo(db, nome="Rede Ficticia Matific Antigo"):
    """Alfa: 10 medidas, nota 80. Beta: 10 medidas, nota 40, e mais 30 só com o
    retrato do Matific do ano anterior (o motor não as afere: Matific é contador do ano)."""
    rede = _rede(db, nome)
    _escola(db, rede, "EMEF Inventada Alfa", medidas=10, nota=80.0)
    _escola(db, rede, "EMEF Inventada Beta", medidas=10, nota=40.0, so_matific_antigo=30)
    db.commit()
    return rede


def test_quem_so_tem_o_matific_do_ano_passado_nao_pesa_na_media_geral(db):
    rede = _mundo_matific_antigo(db)
    painel = svc.dashboard_rede(db, rede.id)
    beta = _cartoes(painel)["EMEF Inventada Beta"]
    assert beta["media_geral"] == 40.0
    assert (beta["alunos_com_nota_elefante"], beta["alunos_com_nota_matific"]) == (10, 10)
    # A cobertura (numerador da adoção) continua do jeito dela: é outra conta.
    assert beta["alunos_com_dados"] == 40
    # O peso é quem a média mede: as 10. Antes: 40.
    assert beta["alunos_com_dados_premiaveis"] == 10
    # (80·10 + 40·10) ÷ 20. Com o peso antigo: (80·10 + 40·40) ÷ 50 = 48,0.
    assert painel["totais"]["media_geral"] == 60.0


def test_panorama_global_e_meta_da_media_geral_pesam_quem_a_media_mede(db):
    rede = _mundo_matific_antigo(db, "Rede Ficticia Matific Antigo Global")
    global_ = svc.dashboard_global(db)
    cartao = next(r for r in global_["redes"] if r["rede_id"] == rede.id)
    assert cartao["media_geral"] == 60.0
    assert global_["totais"]["media_geral"] == 60.0
    svc.definir_meta(db, rede.id, "media_geral", 55.0)
    db.commit()
    meta = next(m for m in svc.metas_com_progresso(db, rede.id)
                if m["metrica"] == "media_geral")
    # Antes: 48,0 de 55 ("não atingida").
    assert (meta["atual"], meta["atingida"], meta["medida"]) == (60.0, True, True)


def test_quem_so_tem_leitura_itemizada_pesa_na_media_geral(db):
    """O inverso: a média do Elefante conta a Leitura itemizada (dado do Elefante sem
    retrato), e o peso não contava. Beta: 10 medidas nas duas plataformas e mais 10
    só com Leitura itemizada, todas com nota 40 (a média de Leitura de Beta é das 20)."""
    rede = _rede(db, "Rede Ficticia Leitura Itemizada")
    _escola(db, rede, "EMEF Inventada Alfa", medidas=10, nota=80.0)
    _escola(db, rede, "EMEF Inventada Beta", medidas=10, nota=40.0, so_leitura=10)
    db.commit()
    painel = svc.dashboard_rede(db, rede.id)
    beta = _cartoes(painel)["EMEF Inventada Beta"]
    assert (beta["alunos_com_nota_elefante"], beta["alunos_com_nota_matific"]) == (20, 10)
    assert beta["media_geral"] == 40.0
    # O peso é quem a média mede: as 20. Antes: 10 (só quem tinha retrato).
    assert beta["alunos_com_dados_premiaveis"] == 20
    # (80·10 + 40·20) ÷ 30. Com o peso antigo: (80·10 + 40·10) ÷ 20 = 60,0.
    assert painel["totais"]["media_geral"] == pytest.approx(53.3, abs=0.05)


def test_quem_ainda_nao_tem_nota_calculada_nao_pesa_na_media_geral(db):
    """A média só olha a Nota CALCULADA pelo motor vigente (com o carimbo). A criança
    com retrato e sem Nota, ou com a Nota ainda sem carimbo (recálculo pendente), não
    é medida — e pesava."""
    rede = _rede(db, "Rede Ficticia Nota Pendente")
    _escola(db, rede, "EMEF Inventada Alfa", medidas=10, nota=80.0)
    _escola(db, rede, "EMEF Inventada Beta", medidas=10, nota=40.0, sem_nota=15,
            nota_pendente=15)
    db.commit()
    painel = svc.dashboard_rede(db, rede.id)
    beta = _cartoes(painel)["EMEF Inventada Beta"]
    assert (beta["alunos_com_nota_elefante"], beta["alunos_com_nota_matific"]) == (10, 10)
    assert beta["alunos_com_dados_premiaveis"] == 10
    # Com o peso antigo: (80·10 + 40·40) ÷ 50 = 48,0.
    assert painel["totais"]["media_geral"] == 60.0


def test_meta_da_media_geral_nao_e_medida_sem_nota_calculada(db):
    """A rede em que as crianças têm dado mas o recálculo ainda não passou: a escola é
    comparada (tem per capita), a média geral é 0,0 por AUSÊNCIA e a meta não pode sair
    "medida" — o "0,0 / 70" que ``medida`` existe para não publicar."""
    rede = _rede(db, "Rede Ficticia Sem Recalculo")
    _escola(db, rede, "EMEF Inventada Alfa", medidas=0, nota=0.0, sem_nota=10)
    svc.definir_meta(db, rede.id, "media_geral", 70.0)
    db.commit()
    painel = svc.dashboard_rede(db, rede.id)
    alfa = _cartoes(painel)["EMEF Inventada Alfa"]
    assert alfa["comparada"] and alfa["media_geral"] == 0.0
    assert alfa["alunos_com_dados_premiaveis"] == 0
    meta = next(m for m in svc.metas_com_progresso(db, rede.id)
                if m["metrica"] == "media_geral")
    # Antes: medida=True, com o peso das 10 que têm retrato e nenhuma Nota.
    assert meta["medida"] is False


def test_peso_da_media_e_o_dos_modulos_contratados(db):
    """Rede só com a Leitura: o retrato do Matific (fora do plano) não faz ninguém ser
    medido. Beta: 10 medidas e mais 30 só com o Matific do ano (fora do plano)."""
    from app.models import ModuloRede

    rede = _rede(db, "Rede Ficticia So Leitura Peso")
    db.add(ModuloRede(rede_id=rede.id, modulo="matematica", ativo=False))
    _escola(db, rede, "EMEF Inventada Alfa", medidas=10, nota=80.0)
    beta = _escola(db, rede, "EMEF Inventada Beta", medidas=10, nota=40.0)
    imp = Importacao(escola_id=beta.id, plataforma="seed", tipo="seed")
    db.add(imp)
    turma = db.query(Turma).filter(Turma.escola_id == beta.id).one()
    for i in range(30):
        a = Aluno(escola_id=beta.id, nome=f"Crianca Inventada Beta Matific {i}",
                  status="ativo")
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=beta.id, aluno_id=a.id, turma_id=turma.id, ano_letivo=ANO))
        db.add(SnapshotMatific(escola_id=beta.id, aluno_id=a.id, importacao_id=imp.id,
                               atividades=10, estrelas=100))
        db.add(Nota(detalhes=scoring.carimbo_institucional(), escola_id=beta.id,
                    aluno_id=a.id, ano_letivo=ANO, nota_geral=0.0, nota_elefante=0.0,
                    nota_matific=0.0, nota_elefante_institucional=0.0,
                    nota_matific_institucional=0.0, posicao=100 + i))
    db.commit()
    painel = svc.dashboard_rede(db, rede.id)
    assert painel["modulos"] == ["leitura"]
    cartao = _cartoes(painel)["EMEF Inventada Beta"]
    assert cartao["alunos_com_dados_premiaveis"] == 10
    assert painel["totais"]["media_geral"] == 60.0
