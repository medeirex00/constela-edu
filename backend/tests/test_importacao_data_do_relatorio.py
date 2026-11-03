"""Upload manual sem a DATA DO RELATÓRIO não vira "o dado de hoje" por cima da
sincronização (achado [10] da auditoria de 31/10).

Sem ``data_referencia``, o /confirmar datava o retrato com o relógio de agora. Um
relatório antigo enviado à mão (o arquivo de exemplo de agosto, na demonstração)
passava a ser o retrato ATUAL — ranking e nota caíam para o valor antigo e o selo
de frescor dizia "em dia" — e, se a sincronização já tinha gravado o retrato do
mesmo dia, ele era SOBRESCRITO no lugar, sem deixar rastro do dado coletado.

Agora: no total acumulado (formato resumo, sem período), upload manual SEM data
sobre aluno cujo retrato atual veio da sincronização é recusado (422) pedindo a
data, antes de gravar qualquer coisa. Com a data, o relatório entra na data dele.
Entre uploads manuais (o Excel complementando o PDF no mesmo dia), nada muda —
``test_importacao.py::test_reimportar_*_mesmo_dia_atualiza_o_snapshot``.
"""
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import Importacao, SincronizacaoExecucao, SnapshotElefante, SnapshotMatific
from app.sync.interfaces import ArquivoObtido, Contexto

TURMA_MATIFIC = "3 ANO A (300396804)"


def _agora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _execucao(db, escola_id: int, plataforma: str) -> SincronizacaoExecucao:
    """Uma execução de sincronização EM ANDAMENTO (a janela em que a importação da
    sync acontece)."""
    execucao = SincronizacaoExecucao(
        escola_id=escola_id, plataforma=plataforma, origem="manual",
        status="executando", iniciada_em=_agora() - timedelta(minutes=1))
    db.add(execucao)
    db.commit()
    return execucao


def _sync_matific(db, escola, monkeypatch, *, atividades: int, estrelas: int):
    """Grava o retrato do Matific PELA SINCRONIZAÇÃO real (orquestrador + JSON do
    Placar), dentro da janela de uma execução."""
    from app.sync import orchestrator

    monkeypatch.setattr(orchestrator.imp, "_guardar_temporario", lambda *a, **k: None)
    execucao = _execucao(db, escola.id, "matific")
    payload = {"turma": TURMA_MATIFIC, "duration": "this-year", "alunos": [
        {"nome": "Ana Beatriz Souza", "nome_abrev": "Ana B", "uuid": "u-ana",
         "turma": TURMA_MATIFIC, "estrelas": estrelas, "atividades": atividades}]}
    arquivo = ArquivoObtido(
        conteudo=json.dumps(payload).encode("utf-8"), nome_arquivo="matific_3-ano-a.json",
        plataforma="matific", content_type=orchestrator.CT_MATIFIC_API, formato_hint="resumo")
    res = orchestrator.aplicar_arquivo(
        db, escola, arquivo, usuario_id=None, recalcular=False,
        contexto=Contexto(escola_id=escola.id, execucao_id=execucao.id,
                          log=lambda etapa, nivel, msg: None))
    assert res["qtd_alunos"] == 1
    execucao.status = "concluida"
    execucao.finalizada_em = _agora()
    db.commit()


def _snaps_matific(db, aluno_id: int) -> list[SnapshotMatific]:
    db.expire_all()
    return list(db.execute(
        select(SnapshotMatific).where(SnapshotMatific.aluno_id == aluno_id)
        .order_by(SnapshotMatific.data_referencia, SnapshotMatific.id)).scalars())


def _upload_matific(cliente, escola_id: int, aluno_id: int, *, atividades: int,
                    estrelas: int, data_referencia: str | None = None, **extra):
    corpo = {"plataforma": "matific", "formato": "resumo", "tipo": "pdf",
             "linhas": [{"nome": "Ana Beatriz Souza", "aluno_id": aluno_id,
                         "dados": {"atividades": atividades, "estrelas": estrelas,
                                   "pontuacao_media": 3.0}}], **extra}
    if data_referencia is not None:
        corpo["data_referencia"] = data_referencia
    return cliente.post(f"/api/v1/escolas/{escola_id}/importacoes/confirmar", json=corpo)


def test_upload_sem_data_nao_sobrescreve_o_retrato_da_sync_do_mesmo_dia(
        cliente, db, escola_completa, monkeypatch):
    """Caso B: a sync gravou 50 hoje; o upload antigo traz 20. Antes: sobrava UM
    retrato, com 20 (o dado coletado sumia). Agora: 422 e o retrato da sync intacto."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    _sync_matific(db, escola, monkeypatch, atividades=50, estrelas=300)
    assert [(s.atividades, s.estrelas) for s in _snaps_matific(db, ana.id)] == [(50, 300)]

    resposta = _upload_matific(cliente, escola.id, ana.id, atividades=20, estrelas=100)

    assert resposta.status_code == 422, resposta.text
    detalhe = resposta.json()["detail"]
    assert "Informe a data do relatório" in detalhe
    assert "Nada foi gravado" in detalhe
    snaps = _snaps_matific(db, ana.id)
    assert [(s.atividades, s.estrelas) for s in snaps] == [(50, 300)]
    # Nem a importação recusada ficou registrada.
    assert db.execute(select(Importacao).where(
        Importacao.escola_id == escola.id, Importacao.tipo == "pdf")).first() is None


def test_upload_sem_data_nao_vira_o_retrato_atual_sobre_a_sync_antiga(
        cliente, db, escola_completa, monkeypatch):
    """Caso A: a sync gravou 50 há 10 dias; o upload antigo traz 20. Antes: nascia
    um retrato datado de agora com 20, que virava o atual (ranking e nota caíam e o
    frescor dizia "em dia"). Agora: 422 e o atual continua o da sync."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    _sync_matific(db, escola, monkeypatch, atividades=50, estrelas=300)
    (snap,) = _snaps_matific(db, ana.id)
    snap.data_referencia = _agora() - timedelta(days=10)
    db.commit()

    resposta = _upload_matific(cliente, escola.id, ana.id, atividades=20, estrelas=100)

    assert resposta.status_code == 422, resposta.text
    snaps = _snaps_matific(db, ana.id)
    assert len(snaps) == 1 and snaps[-1].atividades == 50


def test_upload_com_a_data_do_relatorio_entra_na_data_dele(
        cliente, db, escola_completa, monkeypatch):
    """Com a data (o que a tela agora exige), o relatório antigo é gravado na data
    dele: entra no histórico e o retrato atual continua o da sincronização."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    _sync_matific(db, escola, monkeypatch, atividades=50, estrelas=300)
    agosto = "2026-08-15T02:59:59Z"   # fim do dia 14/08 em Brasília

    resposta = _upload_matific(cliente, escola.id, ana.id, atividades=20, estrelas=100,
                               data_referencia=agosto)

    assert resposta.status_code == 200, resposta.text
    snaps = _snaps_matific(db, ana.id)
    assert [(s.atividades, s.estrelas) for s in snaps] == [(20, 100), (50, 300)]
    assert snaps[0].data_referencia.date().isoformat() == "2026-08-15"
    assert snaps[-1].atividades == 50   # o atual é o da sincronização


def test_recusa_nao_move_o_arquivo_original_e_o_mesmo_envio_segue_com_a_data(
        cliente, db, escola_completa, monkeypatch, tmp_path):
    """A recusa acontece antes de mover o original de /temporarios: o MESMO token
    serve para confirmar de novo, agora com a data."""
    from app.core.config import settings

    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    _sync_matific(db, escola, monkeypatch, atividades=50, estrelas=300)
    monkeypatch.setattr(settings, "UPLOADS_DIR", tmp_path)
    token = "a" * 32 + ".pdf"
    temporario = tmp_path / "temporarios" / token
    temporario.parent.mkdir(parents=True)
    temporario.write_bytes(b"%PDF-1.4 relatorio de teste")

    recusada = _upload_matific(cliente, escola.id, ana.id, atividades=20, estrelas=100,
                               arquivo_token=token, arquivo_nome="Matific.pdf")
    assert recusada.status_code == 422, recusada.text
    assert temporario.exists()
    assert not (tmp_path / "matific").exists()

    aceita = _upload_matific(cliente, escola.id, ana.id, atividades=20, estrelas=100,
                             arquivo_token=token, arquivo_nome="Matific.pdf",
                             data_referencia="2026-08-15T02:59:59Z")
    assert aceita.status_code == 200, aceita.text
    assert not temporario.exists()
    assert len(list((tmp_path / "matific").iterdir())) == 1


def test_upload_sem_data_sobre_retrato_do_elefante_vindo_da_sync(
        cliente, db, escola_completa):
    """A mesma regra no resumo do Elefante (``_importar_elefante_resumo``)."""
    from app.routers import importacoes as imp
    from app.schemas import ImportacaoConfirm

    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    execucao = _execucao(db, escola.id, "elefante")
    imp.confirmar(
        dados=ImportacaoConfirm(
            plataforma="elefante", formato="resumo", tipo="texto", recalcular=False,
            sincronizar_turma=True, permitir_criar_turma=False,
            linhas=[{"nome": ana.nome, "aluno_id": ana.id,
                     "dados": {"livros_unicos": 12, "tempo_leitura_min": 90}}]),
        escola_id=escola.id, usuario=escola_completa["admin"], db=db)
    execucao.status = "concluida"
    execucao.finalizada_em = _agora()
    db.commit()

    resposta = cliente.post(
        f"/api/v1/escolas/{escola.id}/importacoes/confirmar",
        json={"plataforma": "elefante", "formato": "resumo", "tipo": "pdf",
              "linhas": [{"nome": ana.nome, "aluno_id": ana.id,
                          "dados": {"livros_unicos": 3, "tempo_leitura_min": 10}}]})

    assert resposta.status_code == 422, resposta.text
    db.expire_all()
    snaps = list(db.execute(select(SnapshotElefante).where(
        SnapshotElefante.aluno_id == ana.id)).scalars())
    assert [s.livros_unicos for s in snaps] == [12]


def test_upload_sem_data_sobre_upload_manual_segue_complementar(cliente, db, escola_completa):
    """Sem sincronização no caminho, o comportamento já testado não muda: o upload
    manual do mesmo dia complementa/atualiza o retrato do upload manual."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    assert _upload_matific(cliente, escola.id, ana.id, atividades=10,
                           estrelas=2).status_code == 200
    assert _upload_matific(cliente, escola.id, ana.id, atividades=25,
                           estrelas=7).status_code == 200
    snaps = _snaps_matific(db, ana.id)
    assert [(s.atividades, s.estrelas) for s in snaps] == [(25, 7)]


def test_a_propria_sincronizacao_segue_sem_data(db, escola_completa, monkeypatch):
    """A sincronização não manda ``data_referencia`` (usa o relógio da coleta): a
    recusa é só do upload manual — a coleta seguinte do mesmo dia atualiza o retrato."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    _sync_matific(db, escola, monkeypatch, atividades=50, estrelas=300)
    _sync_matific(db, escola, monkeypatch, atividades=55, estrelas=320)
    snaps = _snaps_matific(db, ana.id)
    assert [(s.atividades, s.estrelas) for s in snaps] == [(55, 320)]


# --- Revisão do achado [10] (31/10/2026) --------------------------------------
# A dispensa da sincronização é um sinal do SERVIDOR (o pedido montado pelo
# orquestrador), não o campo ``sincronizar_turma`` do corpo; e a data do relatório
# no futuro é recusada no upload manual.

def test_sincronizar_turma_do_cliente_nao_dispensa_a_data(
        cliente, db, escola_completa, monkeypatch):
    """``sincronizar_turma`` é um campo aberto do ``ImportacaoConfirm``: um POST
    manual sem data e com ``sincronizar_turma=true`` era aceito (200) e gravava
    "como hoje" por cima do retrato da sincronização. Agora: 422, como sem o campo."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    _sync_matific(db, escola, monkeypatch, atividades=50, estrelas=300)

    resposta = _upload_matific(cliente, escola.id, ana.id, atividades=20, estrelas=100,
                               sincronizar_turma=True)

    assert resposta.status_code == 422, resposta.text
    assert "Informe a data do relatório" in resposta.json()["detail"]
    assert [(s.atividades, s.estrelas) for s in _snaps_matific(db, ana.id)] == [(50, 300)]


def test_o_sinal_da_sincronizacao_e_do_servidor():
    """O orquestrador marca o pedido que monta (``confirmacao_da_sincronizacao``):
    mesmos valores, mesmos campos informados — e o corpo HTTP, validado como
    ``ImportacaoConfirm``, nunca chega com essa marca."""
    from app.routers import importacoes as imp
    from app.schemas import ImportacaoConfirm

    pedido = ImportacaoConfirm(
        plataforma="matific", formato="resumo", tipo="texto", sincronizar_turma=True,
        permitir_criar_turma=False,
        linhas=[{"nome": "Ana Beatriz Souza", "dados": {"atividades": 1, "estrelas": 2}}])
    marcado = imp.confirmacao_da_sincronizacao(pedido)

    assert isinstance(marcado, imp._ConfirmacaoDaSincronizacao)
    assert marcado.model_dump() == pedido.model_dump()
    assert marcado.model_fields_set == pedido.model_fields_set
    assert not isinstance(ImportacaoConfirm.model_validate(pedido.model_dump()),
                          imp._ConfirmacaoDaSincronizacao)


def test_data_do_relatorio_no_futuro_e_recusada(cliente, db, escola_completa, monkeypatch):
    """Um retrato datado de 2027 viraria o atual até lá (por cima de toda coleta).
    Agora: 422 e nada gravado. Recusa é só para DIA (de Brasília) depois de hoje: do
    dia de hoje mas adiantada (o relógio do aparelho à frente; a tela manda "agora"
    quando a data é hoje), grava com o agora do servidor — revisão de 01/11/2026:
    a folga de 10 min recusava o "hoje" de um notebook com o relógio errado."""
    from app.routers import importacoes as imp

    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    futuro = (datetime.now(timezone.utc) + timedelta(days=400)).isoformat()

    resposta = _upload_matific(cliente, escola.id, ana.id, atividades=5, estrelas=1,
                               data_referencia=futuro)

    assert resposta.status_code == 422, resposta.text
    assert "no futuro" in resposta.json()["detail"]
    assert "Nada foi gravado" in resposta.json()["detail"]
    assert _snaps_matific(db, ana.id) == []
    assert db.execute(select(Importacao).where(Importacao.escola_id == escola.id)).first() is None

    # Relógio do servidor fixo em 20/10/2026 12h de Brasília (15h UTC).
    agora = datetime(2026, 10, 20, 15, 0, 0)
    monkeypatch.setattr(imp, "_agora_utc", lambda: agora)
    amanha_cedo = "2026-10-21T00:30:00-03:00"      # 12,5 h à frente, e já é amanhã
    assert _upload_matific(cliente, escola.id, ana.id, atividades=5, estrelas=1,
                           data_referencia=amanha_cedo).status_code == 422
    assert _snaps_matific(db, ana.id) == []
    hoje_mais_tarde = "2026-10-20T23:30:00-03:00"  # 11,5 h à frente, ainda hoje
    resposta = _upload_matific(cliente, escola.id, ana.id, atividades=5, estrelas=1,
                               data_referencia=hoje_mais_tarde)
    assert resposta.status_code == 200, resposta.text
    (snap,) = _snaps_matific(db, ana.id)
    assert (snap.atividades, snap.estrelas) == (5, 1)
    assert snap.data_referencia.replace(tzinfo=None) == agora   # gravado com o agora
