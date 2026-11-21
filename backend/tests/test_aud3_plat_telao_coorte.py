"""A faixa "livros / atividades / estrelas" do telão soma só quem a faixa conta em
"alunos" (REG_NUMEROS-6).

``publico._dados_publicos`` somava o retrato atual de TODO aluno com retrato na escola,
sem recorte de população, ao lado de um "alunos" que conta só os ativos matriculados
no ano. O retrato não é apagado quando a criança sai (é o histórico): a criança muito
leitora transferida no meio do ano seguia somando no telão sem login — a mesma escola
mostrava 160 livros no Painel e 1160 no telão.

Agora o telão soma a coorte do próprio "alunos" (ativo + matrícula do ano letivo), a
mesma do Painel da coordenação (``rankings.montar_dashboard``). Dados fictícios.
"""
from datetime import datetime

from fastapi.testclient import TestClient

from app.main import app
from app.models import Aluno, Importacao, Matricula, SnapshotElefante, SnapshotMatific, Turma
from app.services import scoring

API = "/api/v1"
COLETA = datetime(2026, 9, 10, 10, 0)


def _cena(db, escola_completa) -> dict:
    """As três crianças da turma (10, 20, 30), uma da 1ª Fase (100) — a Fase não
    concorre, mas está matriculada e conta em "alunos", como no Painel — e duas que
    saíram da escola: transferida (1000) e arquivada (500)."""
    esc = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    imp = Importacao(escola_id=esc.id, plataforma="seed", tipo="seed")
    fase = Turma(escola_id=esc.id, nome="1ª Fase Inventada", ano_escolar="1ª Fase",
                 ano_letivo=esc.ano_letivo_ativo)
    db.add_all([imp, fase])
    db.flush()
    pequeno = Aluno(escola_id=esc.id, nome="Crianca Inventada da Fase")
    transferida = Aluno(escola_id=esc.id, nome="Crianca Inventada Transferida")
    arquivada = Aluno(escola_id=esc.id, nome="Crianca Inventada Arquivada")
    db.add_all([pequeno, transferida, arquivada])
    db.flush()
    db.add(Matricula(escola_id=esc.id, aluno_id=pequeno.id, turma_id=fase.id,
                     ano_letivo=esc.ano_letivo_ativo))
    for quem in (transferida, arquivada):
        db.add(Matricula(escola_id=esc.id, aluno_id=quem.id,
                         turma_id=escola_completa["turma"].id,
                         ano_letivo=esc.ano_letivo_ativo))
    valores = {ana: 10, joao: 20, sofia: 30, pequeno: 100, transferida: 1000,
               arquivada: 500}
    for aluno, n in valores.items():
        db.add(SnapshotElefante(escola_id=esc.id, aluno_id=aluno.id, importacao_id=imp.id,
                                data_referencia=COLETA, livros_unicos=n,
                                tempo_leitura_min=n, livros_por_nivel={"D": n}))
        db.add(SnapshotMatific(escola_id=esc.id, aluno_id=aluno.id, importacao_id=imp.id,
                               data_referencia=COLETA, atividades=n, estrelas=n,
                               pontuacao_media=3.0))
    db.commit()
    scoring.recalcular_escola(db, esc.id)
    transferida.status = "transferido"
    arquivada.status = "arquivado"
    db.commit()
    scoring.recalcular_escola(db, esc.id)
    return {"escola": esc.id}


def _telao(cliente, escola_id: int) -> dict:
    cfg = cliente.put(f"{API}/escolas/{escola_id}/painel-publico", json={"ativo": True})
    assert cfg.status_code == 200, cfg.text
    token = cfg.json()["url"].rsplit("/", 1)[1]
    r = TestClient(app).get(f"{API}/publico/{token}/painel")
    assert r.status_code == 200, r.text
    return r.json()["estatisticas"]


def test_telao_nao_soma_quem_saiu_da_escola(cliente, db, escola_completa):
    c = _cena(db, escola_completa)
    estatisticas = _telao(cliente, c["escola"])
    # 10 + 20 + 30 + 100: os quatro que estão em "alunos"; nem 1000 nem 500.
    assert estatisticas == {"alunos": 4, "livros": 160, "atividades": 160,
                            "estrelas": 160}, estatisticas


def test_telao_e_painel_da_coordenacao_dizem_o_mesmo_numero(cliente, db, escola_completa):
    c = _cena(db, escola_completa)
    estatisticas = _telao(cliente, c["escola"])
    painel = cliente.get(f"{API}/escolas/{c['escola']}/dashboard")
    assert painel.status_code == 200, painel.text
    p = painel.json()
    assert (estatisticas["alunos"], estatisticas["livros"], estatisticas["atividades"]) == (
        p["total_alunos"], p["total_livros"], p["total_atividades"]), (estatisticas, p)
