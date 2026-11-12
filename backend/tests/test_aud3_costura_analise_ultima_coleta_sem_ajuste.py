"""Análise Educacional: o ajuste manual não é "a última coleta" da escola (costura da fase D,
OBS-analise-ultima-coleta; a regra do frescor em eca2202d).

``analise.plataformas._partes_coletas`` tirava a primeira e a última coleta de cada
plataforma do ``min``/``max`` de TODOS os retratos — inclusive o do ajuste manual
(``Importacao.tipo == "manual"``, o botão Editar das telas Matific/Elefante; numa escola
integrada, o "fale com o suporte" do Admin Global). Um número digitado hoje para uma criança
fazia a escola com a coleta parada há três semanas aparecer com "última coleta: hoje" e
cobertura completa — a Secretaria lia "em dia" uma escola sem dado novo.

Agora a última coleta é a da última COLETA (retrato que não é ajuste manual); na escola sem
coleta nenhuma (sem integração, que digita os números), continua sendo a do ajuste mais
recente, o único dado que ela tem. Mundo FICTÍCIO.
"""
from datetime import date, datetime

from app.models import Importacao, SnapshotElefante, SnapshotMatific
from app.services.analise import plataformas as plat
from app.services.evolucao import IMPORTACAO_AJUSTE_MANUAL
from tests.test_analise_base import (nova_escola, nova_rede, retrato_elefante, retrato_matific,
                                     turma_com_alunos)

COLETA = datetime(2026, 10, 1, 15, 0)        # 01/10 12h de Brasília
AJUSTE = datetime(2026, 10, 30, 15, 0)       # 30/10 12h de Brasília
HOJE = date(2026, 10, 31)


def _ajuste(db, escola, aluno, quando, *, plataforma: str) -> None:
    imp = Importacao(escola_id=escola.id, usuario_id=None, plataforma=plataforma,
                     tipo=IMPORTACAO_AJUSTE_MANUAL, arquivo_original=None, qtd_alunos=1,
                     qtd_erros=0, tempo_ms=0, status="concluida")
    db.add(imp)
    db.flush()
    if plataforma == "elefante":
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                                data_referencia=quando, livros_unicos=3, tempo_leitura_min=30,
                                questoes_tentativas=0, questoes_acertos=0,
                                livros_por_nivel={}))
    else:
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                               data_referencia=quando, atividades=9, estrelas=27,
                               pontuacao_media=0.0))
    db.flush()


def _escola(db, rede, nome, *, com_coleta: bool):
    escola = nova_escola(db, rede, nome, None)
    alunos = turma_com_alunos(db, escola, "3º Ano", 6)
    for a in alunos:
        if com_coleta:
            retrato_elefante(db, escola, a, COLETA)
            retrato_matific(db, escola, a, COLETA, atividades=4, estrelas=12)
    for plataforma in ("elefante", "matific"):
        _ajuste(db, escola, alunos[0], AJUSTE, plataforma=plataforma)
    db.flush()
    return escola


def test_ajuste_manual_nao_vira_a_ultima_coleta_da_escola(db):
    rede = nova_rede(db, nome="Rede Fictícia do Ajuste", codigo="3599961")
    integrada = _escola(db, rede, "EMEF Fictícia Integrada", com_coleta=True)
    r = plat.plataformas_da_rede(db, rede, preset="ano_letivo", hoje=HOJE)
    item = next(e for e in r["escolas"] if e["escola_id"] == integrada.id)
    # Antes: "2026-10-30..." (o ajuste) e 1 dia — a escola parecia coletada ontem.
    for p in ("elefante", "matific"):
        assert item["ultima_coleta"][p].startswith("2026-10-01"), (p, item["ultima_coleta"])
        assert item["dias_desde_ultima_coleta"][p] == 30, (p, item["dias_desde_ultima_coleta"])
    ficha = plat.plataformas_da_escola(db, integrada, preset="ano_letivo", hoje=HOJE)
    assert ficha["ultima_coleta"]["elefante"].startswith("2026-10-01")


def test_escola_sem_coleta_continua_com_a_data_do_ajuste(db):
    """Controle: sem integração, o número digitado é o único dado — a escola não vira
    "sem coleta"."""
    rede = nova_rede(db, nome="Rede Fictícia Só Digitada", codigo="3599960")
    digitada = _escola(db, rede, "EMEF Fictícia Digitada", com_coleta=False)
    r = plat.plataformas_da_rede(db, rede, preset="ano_letivo", hoje=HOJE)
    item = next(e for e in r["escolas"] if e["escola_id"] == digitada.id)
    for p in ("elefante", "matific"):
        assert item["ultima_coleta"][p].startswith("2026-10-30"), (p, item["ultima_coleta"])
        assert item["cobertura"][p] != plat.SEM_COLETA, (p, item["cobertura"])
