"""Importação — P3C: linha sem aluno vinculado NUNCA é descartada em silêncio
(auditoria + notificação + `ignorados`); P3D: resumo com livros e sem níveis
avisa (dificuldade desconhecida, não zero); P3E: campo ausente na API interna
(Elefante e Matific) não vira 0 nem sobrescreve snapshot válido; P3F: aluno
inativo homônimo não vira 2ª ficha ativa (pendência; histórico intacto)."""
import json

import pytest
from sqlalchemy import select

from app.models import (
    Aluno,
    LogAuditoria,
    Matricula,
    Notificacao,
    RevisaoIdentidade,
    SnapshotElefante,
    Turma,
)
from app.routers import importacoes as imp
from app.schemas.importacao import LinhaConfirmacao
from app.services import importacao as svc
from app.sync import orchestrator
from app.sync.interfaces import ArquivoObtido, Contexto


def _base(escola_id):
    return f"/api/v1/escolas/{escola_id}"


def _logs(db, escola_id, acao):
    return db.execute(select(LogAuditoria).where(
        LogAuditoria.escola_id == escola_id, LogAuditoria.acao == acao)).scalars().all()


# --------------------------------------------------------------------------
# P3C — linha sem vínculo
# --------------------------------------------------------------------------
def test_confirmar_expoe_ignorados_e_registra_pendencia(cliente, db, escola_completa):
    """Linha sem aluno vinculado e linha de turma inexistente (gate da sync):
    `ignorados` no resultado + auditoria + notificação — nunca silêncio."""
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    r = cliente.post(f"{_base(escola.id)}/importacoes/confirmar", json={
        "plataforma": "elefante", "formato": "resumo", "tipo": "texto",
        "permitir_criar_turma": False,
        "linhas": [
            {"nome": ana.nome, "aluno_id": ana.id, "dados": {"livros_unicos": 1}},
            {"nome": "Fulano Sem Vinculo", "dados": {"livros_unicos": 4}},
            {"nome": "Beltrano Da Turma Nova", "criar_em_turma_nome": "9º Ano Z",
             "dados": {"livros_unicos": 4}},
        ]})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["qtd_alunos"] == 1
    assert corpo["ignorados"] == [svc.normalizar_nome("Fulano Sem Vinculo"),
                                  svc.normalizar_nome("Beltrano Da Turma Nova")]
    assert any("Fulano Sem Vinculo" in a and "pendência" in a for a in corpo["avisos"])
    # As DUAS linhas (sem turma; turma fora do cadastro na sync) ficam preservadas
    # na fila de revisão de identidade — e auditadas como linha sem aluno vinculado.
    assert len(_logs(db, escola.id, "importacao.linha_ignorada")) == 2
    assert corpo["qtd_revisoes"] == 2
    assert {r.motivo for r in db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == escola.id)).scalars()} == {
        "sem_turma", "turma_nao_cadastrada"}
    assert db.execute(select(Notificacao).where(
        Notificacao.escola_id == escola.id,
        Notificacao.tipo == "importacao.linha_ignorada")).scalars().first() is not None
    # nenhum aluno errado foi criado
    assert db.execute(select(Aluno).where(Aluno.escola_id == escola.id,
                                          Aluno.nome.in_(["Fulano Sem Vinculo",
                                                          "Beltrano Da Turma Nova"]))
                      ).scalars().all() == []




# --------------------------------------------------------------------------
# P3D — resumo com livros e sem distribuição por nível
# --------------------------------------------------------------------------
def test_resumo_sem_niveis_avisa_dificuldade_desconhecida(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    r = cliente.post(f"{_base(escola.id)}/importacoes/confirmar", json={
        "plataforma": "elefante", "formato": "resumo", "tipo": "texto",
        "linhas": [{"nome": ana.nome, "aluno_id": ana.id, "dados": {"livros_unicos": 5}}]})
    assert r.status_code == 200, r.text
    assert any("distribuição por nível" in a and "não zero" in a for a in r.json()["avisos"])
    snap = db.execute(select(SnapshotElefante).where(SnapshotElefante.aluno_id == ana.id)).scalar_one()
    assert snap.livros_unicos == 5 and not snap.livros_por_nivel




# --------------------------------------------------------------------------
# P3E — campo ausente na API interna
# --------------------------------------------------------------------------
def test_analisar_elefante_api_campo_ausente_nao_vira_zero():
    a = svc.analisar_elefante_api({
        "courseSchoolDescriptors": {"courseName": "5 ANO B"},
        "students": [{"studentId": 1, "studentName": "Veronica X",
                      "totalReadTime": 600, "responses": "abc"}]})   # sem totalBooksRead
    d = a.linhas[0].dados
    assert "livros_unicos" not in d and "questoes_tentativas" not in d
    assert d["tempo_leitura_min"] == 10 and "questoes_acertos" not in d
    assert a.erros_gerais and "Campos ausentes" in a.erros_gerais[0]
    assert "livros_unicos: 1 aluno(s)" in a.erros_gerais[0]


def test_analisar_matific_api_campo_ausente_nao_vira_zero():
    """Mesma guarda no Placar do Matific: sem `estrelas` a chave não entra (o
    importador herda o snapshot anterior) e a média não é fabricada."""
    a = svc.analisar_matific_api({"turma": "T", "alunos": [
        {"nome": "X", "atividades": 100},                       # sem estrelas
        {"nome": "Y", "atividades": 10, "estrelas": 36}]})
    dx, dy = a.linhas[0].dados, a.linhas[1].dados
    assert dx["atividades"] == 100 and "estrelas" not in dx and "pontuacao_media" not in dx
    assert dy["estrelas"] == 36 and dy["pontuacao_media"] == 3.6
    assert a.erros_gerais and "estrelas: 1 aluno(s)" in a.erros_gerais[0]


def test_api_com_campo_ausente_preserva_snapshot_valido(db, escola_completa, monkeypatch):
    """Sync 1 grava 42 livros / 200 min. Sync 2 (mesmo dia) vem SEM totalBooksRead e
    SEM totalReadTime (campo renomeado na API): livros e tempo ficam 42/200 — não 0;
    só as questões (presentes) atualizam."""
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    monkeypatch.setattr(orchestrator.imp, "_guardar_temporario", lambda *a, **k: None)

    def aplicar(students):
        payload = {"courseSchoolDescriptors": {"courseName": "3 ANO A"}, "students": students}
        arq = ArquivoObtido(conteudo=json.dumps(payload).encode("utf-8"),
                            nome_arquivo="t.json", plataforma="elefante",
                            content_type=orchestrator.CT_ELEFANTE_API, formato_hint="resumo")
        ctx = Contexto(escola_id=escola.id, execucao_id=None, log=lambda e, n, m: None)
        return orchestrator.aplicar_arquivo(db, escola, arq, usuario_id=None,
                                            recalcular=False, contexto=ctx)

    aplicar([{"studentId": 1, "studentName": ana.nome, "totalBooksRead": 42,
              "totalReadTime": 12000, "responses": 30, "approvedResponses": 25}])
    aplicar([{"studentId": 1, "studentName": ana.nome, "responses": 31, "approvedResponses": 26}])
    snap = db.execute(select(SnapshotElefante).where(SnapshotElefante.aluno_id == ana.id)).scalar_one()
    assert snap.livros_unicos == 42 and snap.tempo_leitura_min == 200
    assert snap.questoes_tentativas == 31 and snap.questoes_acertos == 26




# --------------------------------------------------------------------------
# P3F — aluno inativo homônimo
# --------------------------------------------------------------------------
def _linha(nome, turma_id):
    return LinhaConfirmacao(nome=nome, dados={"livros_unicos": 1}, criar_em_turma_id=turma_id)


def _n_alunos(db, escola_id, nome):
    return len(db.execute(select(Aluno).where(Aluno.escola_id == escola_id,
                                              Aluno.nome == nome)).scalars().all())


@pytest.mark.parametrize("status_", ["arquivado", "fora_lista_piloto"])
def test_inativo_em_outra_turma_nao_vira_segunda_ficha_ativa(db, escola_completa, status_):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    ana = escola_completa["alunos"][0]
    ana.status = status_
    turma2 = Turma(escola_id=escola.id, nome="4º Ano B", ano_escolar="4º Ano", ano_letivo=2026)
    db.add(turma2)
    db.flush()

    avisos: list[str] = []
    res = imp._resolver_aluno(db, escola.id, 2026, _linha(ana.nome, turma2.id), avisos, {}, {})
    assert res is None                                  # linha fica pendente
    assert _n_alunos(db, escola.id, ana.nome) == 1      # NENHUMA duplicata
    assert ana.status == status_                        # não reativa sozinho
    assert db.execute(select(Matricula).where(Matricula.aluno_id == ana.id)).scalar_one().turma_id == turma.id
    assert any(status_ in a and "NÃO foi criada uma 2ª ficha" in a for a in avisos)
    logs = _logs(db, escola.id, "aluno.revisao_necessaria")
    assert logs and logs[-1].detalhes["motivo"] == "homonimo_em_outra_sala"
    assert logs[-1].entidade_id == ana.id


def test_inativo_na_mesma_turma_vai_para_revisao_sem_duplicata(db, escola_completa):
    """Porta única (2026-09-21): ficha INATIVA não recebe dado nem ganha 2ª ficha
    sozinha — a linha fica na fila de revisão até o gestor decidir (resolver para a
    ficha inativa vale para as próximas importações)."""
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    ana = escola_completa["alunos"][0]
    ana.status = "arquivado"
    db.flush()
    avisos: list[str] = []
    res = imp._resolver_aluno(db, escola.id, 2026, _linha(ana.nome, turma.id), avisos, {}, {})
    assert res is None                                  # não aplica dado à ficha inativa
    assert _n_alunos(db, escola.id, ana.nome) == 1      # e não abre 2ª ficha
    assert any("arquivado" in a for a in avisos)
    assert _logs(db, escola.id, "aluno.revisao_necessaria")[-1].detalhes["motivo"] == "ficha_inativa"


def test_excluido_nao_ressuscita_e_nao_bloqueia_ficha_nova(db, escola_completa):
    """Regra de 276381f mantida: 'excluido' não conta como inativo homônimo."""
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    ana.status = "excluido"
    turma2 = Turma(escola_id=escola.id, nome="4º Ano B", ano_escolar="4º Ano", ano_letivo=2026)
    db.add(turma2)
    db.flush()
    res = imp._resolver_aluno(db, escola.id, 2026, _linha(ana.nome, turma2.id), [], {}, {})
    assert res is not None and res.id != ana.id and res.status == "ativo"
    assert ana.status == "excluido"
